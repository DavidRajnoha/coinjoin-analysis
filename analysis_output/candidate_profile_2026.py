"""
Why are the post-fix candidates still missing from the corpus?

The 2026 corpus was produced by Dumplings with the D5 fix (DUMPLINGS_JOINMARKET_D5_FIX.md)
and then post-processed by parse_dumplings.py. Candidates are external transactions
absorbing outputs of >=3 distinct labeled coinjoins (mainnet_remix_analysis.py).

Part 1 (local, all candidates): what happened to the old candidate set, and how the
new candidates sit in the coinjoin graph.

Part 2 (API sample): re-evaluate every detection rule on fetched transactions and
attribute each miss to a stage:
  * DUMPLINGS  - the patched isOtherCj rejects it (D0-D4, n>=3, D5 patched OR >=2 JM parents,
                 Wasabi 2 precedence)
  * POSTPROC   - Dumplings would accept it, but parse_dumplings CJ_TX_CHECK.BASIC drops it
  * NEITHER    - both stages accept it; the loss is elsewhere (demotion, false_cjtxs, scan range)
Labeled corpus controls must come out as accepted by both stages - otherwise the
re-implementation is wrong, not the pipeline.

Run: .venv/bin/python analysis_output/candidate_profile_2026.py [--n 150] [--controls 30]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import random
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jm_connectivity_analysis as conn  # noqa: E402

CORPUS = 'data/joinmarket/real-data-2026/coinjoin_tx_info.json'
NEW_CAND = 'analysis_output/2026/suspicious_unlabeled_cj_candidates.csv'
OLD_CAND = 'analysis_output/suspicious_unlabeled_cj_candidates.txt'
OUT = 'analysis_output/2026/candidate_profile.json'
ENDPOINTS = ['https://mempool.space/api/tx/{}', 'https://blockstream.info/api/tx/{}']


def fetch(txid):
    for a in range(4):
        try:
            req = urllib.request.Request(ENDPOINTS[a % 2].format(txid),
                                         headers={'User-Agent': 'CJ-Research/1.0'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(0.6 * 2 ** a)
    return None


def rules(tx, jm_parents: int):
    """{rule: passed} for one Esplora tx, plus shape diagnostics prefixed with '_'."""
    outs, ins = tx['vout'], tx['vin']
    ov = [o['value'] for o in outs]
    iv = [i['prevout']['value'] for i in ins]
    groups = {v: c for v, c in collections.Counter(ov).items() if c > 1}
    r = {'_n_in': len(ins), '_n_out': len(outs), '_jm_parents': jm_parents}
    r['D0_has_equal_outputs'] = bool(groups)
    if not groups:
        return r
    v, n = max(groups.items(), key=lambda kv: kv[1])
    non_eq = [x for x in ov if x != v]
    r.update(_n=n, _eq_btc=v / 1e8, _n_groups=len(groups))
    r['D1_single_equal_group'] = len(groups) == 1
    r['D2_change_count_n_or_n-1'] = n == len(outs) - n or n == len(outs) - n + 1
    r['D3_distinct_out_scripts'] = len({o['scriptpubkey'] for o in outs}) >= n
    r['D4_distinct_in_scripts'] = len({i['prevout']['scriptpubkey'] for i in ins}) >= n
    r['Dn_min3_equal'] = n >= 3
    bound = v + max(non_eq) if non_eq else None
    r['D5_patched_bound'] = bound is not None and max(iv) <= bound + max(100_000, v * 5 // 1000)
    r['D5_parent_rule'] = jm_parents >= 2
    seg = all(i['prevout']['scriptpubkey_type'] in ('v0_p2wpkh', 'v1_p2tr') for i in ins)
    r['PRE_not_wasabi2'] = not (seg and len(ins) >= 50 and iv == sorted(iv, reverse=True)
                                and ov == sorted(ov, reverse=True))
    scripts = [i['prevout']['scriptpubkey'] for i in ins] + [o['scriptpubkey'] for o in outs]
    r['P_ratio<=4'] = max(len(ins), len(outs)) / min(len(ins), len(outs)) <= 4
    r['P_num<=100'] = len(ins) <= 100 and len(outs) <= 100
    r['P_reuse<=0.34'] = collections.Counter(scripts).most_common(1)[0][1] / len(scripts) <= 0.34
    r['P_no_opreturn'] = not any(o['scriptpubkey_type'] == 'op_return' for o in outs)
    r['_max_in_excess_sat'] = (max(iv) - bound) if bound else None
    return r


DUMPLINGS_STRUCT = ['D0_has_equal_outputs', 'D1_single_equal_group', 'D2_change_count_n_or_n-1',
                    'D3_distinct_out_scripts', 'D4_distinct_in_scripts', 'Dn_min3_equal',
                    'PRE_not_wasabi2']
POSTPROC = ['P_ratio<=4', 'P_num<=100', 'P_reuse<=0.34', 'P_no_opreturn']


def stage(r):
    """Which stage rejects the tx, and the failing rules of that stage."""
    fail_struct = [k for k in DUMPLINGS_STRUCT if not r.get(k, False)]
    d5_ok = r.get('D5_patched_bound', False) or r.get('D5_parent_rule', False)
    if fail_struct or not d5_ok:
        return 'DUMPLINGS', fail_struct + ([] if d5_ok else ['D5_bound_and_parents'])
    fail_post = [k for k in POSTPROC if not r[k]]
    if fail_post:
        return 'POSTPROC', fail_post
    return 'NEITHER', []


def summarize(results, label):
    n = len(results)
    stages = collections.Counter(r['_stage'] for r in results)
    print(f"\n=== {label}: {n} fetched ===")
    for s in ('DUMPLINGS', 'POSTPROC', 'NEITHER'):
        print(f"  rejected at {s:10}: {stages[s]:>4} ({stages[s] / n * 100:5.1f}%)" if n else '')
    for s in ('DUMPLINGS', 'POSTPROC'):
        sub = [r for r in results if r['_stage'] == s]
        if not sub:
            continue
        c = collections.Counter(k for r in sub for k in r['_fails'])
        sole = collections.Counter(r['_fails'][0] for r in sub if len(r['_fails']) == 1)
        print(f"  {s} failing rules (any): {dict(c.most_common())}")
        print(f"  {s} sole failing rule  : {dict(sole.most_common())}")
    return stages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default=CORPUS)
    ap.add_argument('--n', type=int, default=150)
    ap.add_argument('--controls', type=int, default=30)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    cjs = conn.load(args.corpus)
    with open(NEW_CAND) as fh:
        new = {row['txid']: row for row in csv.DictReader(fh)}
    old = {l.strip() for l in open(OLD_CAND) if l.strip()}
    out = {}

    # ---- Part 1: local profile -------------------------------------------------
    print("=" * 72 + "\n1. OLD CANDIDATES (15,926, pre-fix) IN THE 2026 CORPUS\n" + "=" * 72)
    fate = {'now_labeled': len(old & set(cjs)), 'still_candidate': len(old & set(new)),
            'neither': len(old - set(cjs) - set(new))}
    out['old_candidate_fate'] = fate
    for k, v in fate.items():
        print(f"  {k:16}: {v:>6} ({v / len(old) * 100:5.1f}%)")

    # Children: how many distinct corpus coinjoins each candidate FEEDS.
    feeds = collections.defaultdict(set)
    for txid, cj in cjs.items():
        for i in cj['inputs'].values():
            src = conn.in_source(i)
            if src in new:
                feeds[src].add(txid)
    # Which absorbed outputs are standard denomination?
    absorbed = collections.Counter()
    absorbed_std = collections.Counter()
    for cj in cjs.values():
        for o in cj['outputs'].values():
            sp = conn.out_spender(o)
            if sp in new:
                absorbed[sp] += 1
                absorbed_std[sp] += bool(o.get('is_standard_denom'))

    def dist(vals, edges):
        c = collections.Counter()
        for v in vals:
            c[next(lbl for lo, lbl in reversed(edges) if v >= lo)] += 1
        return {lbl: c[lbl] for _, lbl in reversed(edges)}

    n_children = [len(feeds[t]) for t in new]
    n_parents = [int(r['n_source_coinjoins']) for r in new.values()]
    std_share = [absorbed_std[t] / absorbed[t] for t in new if absorbed[t]]
    years = collections.Counter(r['earliest_source_cj_time'][:4] for r in new.values())
    corpus_years = collections.Counter(c['broadcast_time'][:4] for c in cjs.values())
    edges = [(0, '0'), (1, '1-2'), (3, '3-5'), (6, '6-10'), (11, '11+')]
    out['new_profile'] = {
        'n': len(new),
        'parents_dist': dist(n_parents, [(3, '3'), (4, '4-5'), (6, '6-10'), (11, '11+')]),
        'children_dist': dist(n_children, edges),
        'feeds_ge3_corpus_cjs': sum(c >= 3 for c in n_children),
        'feeds_any_corpus_cj': sum(c >= 1 for c in n_children),
        'absorbed_std_share_all_std': sum(s == 1 for s in std_share),
        'absorbed_std_share_none_std': sum(s == 0 for s in std_share),
        'per_year': {y: {'candidates': years[y], 'corpus': corpus_years[y],
                         'ratio': years[y] / corpus_years[y] if corpus_years[y] else None}
                     for y in sorted(corpus_years)},
    }
    p = out['new_profile']
    print("\n" + "=" * 72 + f"\n2. NEW CANDIDATES ({len(new)}) - GRAPH POSITION\n" + "=" * 72)
    print(f"  labeled JM parents          : {p['parents_dist']}")
    print(f"  labeled JM children         : {p['children_dist']}")
    print(f"  feed >=1 labeled coinjoin   : {p['feeds_any_corpus_cj']} "
          f"({p['feeds_any_corpus_cj'] / len(new) * 100:.1f}%)")
    print(f"  feed >=3 labeled coinjoins  : {p['feeds_ge3_corpus_cjs']} "
          f"({p['feeds_ge3_corpus_cjs'] / len(new) * 100:.1f}%)")
    print(f"  absorbed outputs all mixed  : {p['absorbed_std_share_all_std']}"
          f"   none mixed: {p['absorbed_std_share_none_std']}")
    print("  per year (by earliest parent): candidates / corpus coinjoins")
    for y, v in p['per_year'].items():
        print(f"    {y}: {v['candidates']:>6} / {v['corpus']:>6}  = {v['ratio'] or 0:.2f}")

    # ---- Part 2: API rule diagnostic ---------------------------------------------
    rng = random.Random(args.seed)
    sample = rng.sample(sorted(new), args.n)
    controls = rng.sample(sorted(cjs), args.controls)
    jm_known = set(cjs)

    def run(txids, label):
        res = []
        for k, t in enumerate(txids, 1):
            if k % 25 == 0:
                print(f"  [{label}] {k}/{len(txids)}", flush=True)
            tx = fetch(t)
            time.sleep(0.4)
            if not tx:
                continue
            parents = len({i['txid'] for i in tx['vin']} & jm_known)
            r = rules(tx, parents)
            r['_txid'] = t
            r['_children'] = len(feeds.get(t, ()))
            r['_stage'], r['_fails'] = stage(r)
            res.append(r)
        return res

    print("\n" + "=" * 72 + "\n3. RULE DIAGNOSTIC (API)\n" + "=" * 72)
    ctrl = run(controls, 'ctrl')
    cand = run(sample, 'cand')
    out['controls'] = ctrl
    out['candidates'] = cand
    summarize(ctrl, 'LABELED 2026 CORPUS CONTROLS (expect NEITHER)')
    summarize(cand, 'CANDIDATES')

    with open(OUT, 'w') as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n  wrote {OUT}")


if __name__ == '__main__':
    main()
