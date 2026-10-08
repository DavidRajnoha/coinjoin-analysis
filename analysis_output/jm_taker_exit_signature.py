"""
The taker-exit signature: one untraced input, one untraced mixed output, one untraced change.

A maker's coins stay in JoinMarket: its mixed output and its change are offered again and
get spent into later coinjoins. A taker who exits takes BOTH its mixed output and its
change to its own wallet. A coinjoin where every input, mixed output and change output is
traced into JoinMarket except exactly one of each is therefore the shape of a single
exiting taker, a stricter version of the both-sides all-but-one signal in
jm_connectivity_analysis.py (which ignores change outputs).

Classes per coinjoin (untraced = spender / source is not a JoinMarket tx; an unspent
output counts as untraced):
  exit_1_1_1     1 untraced input, 1 untraced mixed, 1 untraced change, n_change >= 1
  sweep_1_1_0    1 untraced input, 1 untraced mixed, 0 untraced change, and n_change == n_mixed - 1
                 (the taker swept its wallet, so it has no change output)
  both_abo       1 untraced input, 1 untraced mixed, any change (the existing signal)

For exit_1_1_1, whether the untraced mixed output and the untraced change are later spent
by the SAME transaction: if so, one wallet holds both, which is what a taker exit predicts.

JoinMarket = labeled corpus + output-side + input-side candidates, as in the connectivity
analysis. Mixed = output value repeated at least twice (is_standard_denom).

Run: .venv/bin/python analysis_output/jm_taker_exit_signature.py --corpus PATH --candidates PATH [--out DIR]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jm_connectivity_analysis as conn  # noqa: E402

THRESHOLDS = (0.0, 1.0, 5.0, 10.0)


def classify(cj, jm):
    outs = list(cj['outputs'].values())
    mixed = [o for o in outs if o.get('is_standard_denom')]
    change = [o for o in outs if not o.get('is_standard_denom')]
    ins = list(cj['inputs'].values())
    if len(mixed) < 2 or len(ins) < 2:
        return None
    um = [o for o in mixed if conn.out_spender(o) not in jm]
    uc = [o for o in change if conn.out_spender(o) not in jm]
    mi = sum(1 for i in ins if conn.in_source(i) not in jm)
    r = {'amount': st.median(o['value'] for o in mixed) / 1e8, 'year': cj['broadcast_time'][:4],
         'mi': mi, 'mm': len(um), 'mc': len(uc), 'n_mixed': len(mixed), 'n_change': len(change)}
    r['both_abo'] = mi == 1 and len(um) == 1
    r['exit_1_1_1'] = r['both_abo'] and len(uc) == 1
    r['sweep_1_1_0'] = r['both_abo'] and len(uc) == 0 and len(change) == len(mixed) - 1
    r['exit_any'] = r['exit_1_1_1'] or r['sweep_1_1_0']
    if r['exit_1_1_1']:
        sm, sc = conn.out_spender(um[0]), conn.out_spender(uc[0])
        r['cospend'] = 'same tx' if sm and sm == sc else ('both unspent' if not sm and not sc else
                                                          ('one unspent' if not sm or not sc else 'different txs'))
    # Relaxed: taker may fund from several UTXOs - any number of untraced inputs >= 1.
    r['exit_k_1_1'] = mi >= 1 and len(um) == 1 and len(uc) == 1
    return r


def pct(a, b):
    return a / b * 100 if b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--candidates', required=True)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    cjs = conn.load(args.corpus)
    jm = set(cjs) | conn.load_candidates(args.candidates) | conn.input_side_candidates(cjs)
    rows = {t: r for t, c in cjs.items() if (r := classify(c, jm))}
    out = {}

    print("=" * 78 + "\nTAKER-EXIT SIGNATURE  (JM = corpus + candidates)\n" + "=" * 78)
    hdr = f"  {'min BTC':>8} {'n':>8} {'both abo':>9} {'exit 1/1/1':>11} {'sweep 1/1/0':>12} {'exit any':>9} {'k/1/1':>7}"
    print(hdr)
    out['by_amount'] = {}
    for m in THRESHOLDS:
        sub = [r for r in rows.values() if r['amount'] >= m]
        n = len(sub)
        row = {k: sum(r[k] for r in sub) for k in ('both_abo', 'exit_1_1_1', 'sweep_1_1_0', 'exit_any', 'exit_k_1_1')}
        out['by_amount'][m] = dict(n=n, **row)
        print(f"  {m:>8} {n:>8} " + " ".join(f"{pct(row[k], n):>{w}.1f}%" for k, w in
              (('both_abo', 8), ('exit_1_1_1', 10), ('sweep_1_1_0', 11), ('exit_any', 8), ('exit_k_1_1', 6))))

    ge1 = [r for r in rows.values() if r['amount'] >= 1.0]
    abo = [r for r in ge1 if r['both_abo']]
    print(f"\n  >=1 BTC both-sides all-but-one ({len(abo)} txs) split by untraced change outputs:")
    split = collections.Counter(min(r['mc'], 3) for r in abo)
    out['abo_change_split_ge1'] = {str(k): v for k, v in sorted(split.items())}
    for k in sorted(split):
        print(f"    {('3+' if k == 3 else k)} untraced change: {split[k]:>6} ({pct(split[k], len(abo)):5.1f}%)")

    ex = [r for r in ge1 if r['exit_1_1_1']]
    cs = collections.Counter(r['cospend'] for r in ex)
    out['cospend_ge1'] = dict(cs)
    print(f"\n  >=1 BTC exit 1/1/1 ({len(ex)} txs): fate of the untraced mixed + change pair")
    for k in ('same tx', 'different txs', 'one unspent', 'both unspent'):
        print(f"    {k:14}: {cs[k]:>6} ({pct(cs[k], len(ex)):5.1f}%)")

    print("\n  per year, >=1 BTC:")
    print(f"  {'year':>5} {'n':>6} {'both abo':>9} {'exit 1/1/1':>11} {'sweep':>7} {'exit any':>9} {'co-spent':>9}")
    out['per_year_ge1'] = {}
    for y in sorted({r['year'] for r in ge1}):
        sub = [r for r in ge1 if r['year'] == y]
        n = len(sub)
        e = [r for r in sub if r['exit_1_1_1']]
        row = dict(n=n, both_abo=sum(r['both_abo'] for r in sub), exit_1_1_1=len(e),
                   sweep_1_1_0=sum(r['sweep_1_1_0'] for r in sub), exit_any=sum(r['exit_any'] for r in sub),
                   cospent=sum(r['cospend'] == 'same tx' for r in e))
        out['per_year_ge1'][y] = row
        print(f"  {y:>5} {n:>6} {pct(row['both_abo'], n):>8.1f}% {pct(row['exit_1_1_1'], n):>10.1f}% "
              f"{pct(row['sweep_1_1_0'], n):>6.1f}% {pct(row['exit_any'], n):>8.1f}% "
              f"{pct(row['cospent'], len(e)):>8.1f}%")

    # Untraced-input distribution among txs whose outputs look like one exit
    k = collections.Counter(min(r['mi'], 5) for r in ge1 if r['mm'] == 1 and r['mc'] == 1)
    out['untraced_inputs_given_out_1_1_ge1'] = {str(a): b for a, b in sorted(k.items())}
    print("\n  >=1 BTC with 1 untraced mixed + 1 untraced change, by untraced inputs:",
          {('5+' if a == 5 else a): b for a, b in sorted(k.items())})

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        ids = sorted(t for t, r in rows.items() if r['amount'] >= 1.0 and r['exit_any'])
        with open(os.path.join(args.out, 'taker_exit_signature_ge1.txt'), 'w') as fh:
            fh.write('\n'.join(ids) + '\n')
        with open(os.path.join(args.out, 'taker_exit_signature.json'), 'w') as fh:
            json.dump(out, fh, indent=1)
        print(f"\n  wrote {len(ids)} txids and summary to {args.out}")


if __name__ == '__main__':
    main()
