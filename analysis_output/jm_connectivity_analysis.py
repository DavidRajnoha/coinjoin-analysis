"""
JoinMarket transaction connectivity, and the single-taker leak it exposes.

MOTIVATION
----------
In a JoinMarket coinjoin one participant is the taker; the rest are yield generators
remixing coins they already hold. If EVERY mixed output of a transaction is spent
onward into another JoinMarket transaction except ONE, the odd one out is the natural
candidate for the taker's coin leaving the system. The same argument runs on the input
side. A transaction that is "all but one" on both sides narrows the taker to a single
output, which is a deanonymisation signal rather than a mere statistic.

This module measures how often that pattern occurs. It does NOT establish that the
pattern implies a single taker - that is a conditional probability which must be
measured against ground truth in emulation (see simulate_single_taker_leak.py).
Treat every number here as the frequency of a SIGNAL, not of a successful attack.

WHAT COUNTS AS A JOINMARKET TRANSACTION
---------------------------------------
Two modes, because corpus labeling is demonstrably incomplete:
  * 'corpus'    - only labeled coinjoins. Conservative, but understates connectivity
                  badly because missing labels break chains.
  * 'candidates'- labeled coinjoins plus the structurally-verified candidates from
                  mainnet_remix_analysis.py. 92/100 sampled candidates match the
                  JoinMarket output shape against a 0/100 random-chain base rate.

OUTPUT-SIDE vs INPUT-SIDE
-------------------------
The output side asks: where did this transaction's mixed outputs go? The input side
asks: where did its inputs come from? The input side generates its own candidate set -
external transactions that FEED many distinct coinjoins - which is a different
population from the output-side candidates and is reported separately.

IMPORTANT CAVEATS
-----------------
  * One layer deep. Candidates are not themselves expanded, so connectivity here is a
    floor under the 'candidates' assumption, not a converged value.
  * Right-censored. Recent outputs may simply not be spent yet; 2025 is badly affected.
  * 'All but one' has a trivial failure mode: a transaction with exactly one mixed
    output satisfies it vacuously. Those are excluded from the all-but-one counts and
    reported separately.

Run:  .venv/bin/python analysis_output/jm_connectivity_analysis.py [--mode candidates]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics as st
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

CORPUS = 'data/joinmarket/real-data/coinjoin_tx_info.json'
CANDIDATES = 'analysis_output/suspicious_unlabeled_cj_candidates.txt'
OUT_DIR = 'analysis_output'

# An external tx fed by / feeding at least this many distinct coinjoins is a candidate.
MIN_SOURCES = 3


def load(corpus_path: str = CORPUS):
    with open(corpus_path) as fh:
        return json.load(fh)['coinjoins']


def out_spender(output: Dict[str, Any]) -> Optional[str]:
    """The txid that spent this output ('vout_..' record stores 'vin_<txid>_<n>')."""
    sb = output.get('spend_by_tx')
    return sb.split('_')[1] if sb and sb.startswith('vin_') else None


def in_source(inp: Dict[str, Any]) -> Optional[str]:
    """The txid that produced this input ('spending_tx' stores 'vout_<txid>_<n>')."""
    st = inp.get('spending_tx')
    return st.split('_')[1] if st and st.startswith('vout_') else None


def load_candidates(path: str = CANDIDATES) -> Set[str]:
    if not os.path.exists(path):
        return set()
    with open(path) as fh:
        return {l.strip() for l in fh if l.strip()}


def input_side_candidates(cjs: Dict[str, Any], min_sources: int = MIN_SOURCES) -> Set[str]:
    """External transactions that FEED >= min_sources distinct coinjoins.

    This is the input-side mirror of the output-side candidate heuristic, and it is a
    genuinely different population: a tx feeding many coinjoins looks like a source of
    liquidity (an exchange withdrawal, or an unlabeled coinjoin whose outputs were
    spread across several later ones).
    """
    feeds: Dict[str, Set[str]] = collections.defaultdict(set)
    for txid, cj in cjs.items():
        for inp in cj['inputs'].values():
            src = in_source(inp)
            if src is not None and src not in cjs:
                feeds[src].add(txid)
    return {k for k, v in feeds.items() if len(v) >= min_sources}


def analyse(cjs: Dict[str, Any], jm_set: Set[str], denom_only: bool = True,
            min_amount_btc: float = 0.0) -> Dict[str, Any]:
    """Per-transaction connectivity on both the output and the input side.

    For each transaction we count how many of its mixed outputs go onward to a JM tx,
    and how many of its inputs came from one. 'all' means zero misses; 'all_but_one'
    means exactly one miss (transactions with a single mixed output are excluded from
    all_but_one, where the condition would hold vacuously).

    min_amount_btc filters on the median mixed-output value. This matters: the remix
    rate rises monotonically with CoinJoin amount (3.5% below 0.01 BTC, 54% above
    20 BTC), so pooling all amounts mixes two very different populations. Filtering to
    >=1 BTC also removes most of the apparent 2022-23 collapse, which was largely a
    shift in the amount mix rather than a change in behaviour.
    """
    res = {
        'out': collections.Counter(), 'in': collections.Counter(),
        'both': collections.Counter(),
        'out_miss': collections.Counter(), 'in_miss': collections.Counter(),
        'per_year': collections.defaultdict(collections.Counter),
        'all_but_one_txids': [],
    }
    for txid, cj in cjs.items():
        year = cj['broadcast_time'][:4]

        outs = [o for o in cj['outputs'].values()
                if o.get('is_standard_denom')] if denom_only else list(cj['outputs'].values())
        ins = list(cj['inputs'].values())
        if not outs or not ins:
            continue

        if min_amount_btc > 0:
            if st.median(o['value'] for o in outs) / 1e8 < min_amount_btc:
                res['filtered_out'] = res.get('filtered_out', 0) + 1
                continue

        out_hit = sum(1 for o in outs if out_spender(o) in jm_set)
        in_hit = sum(1 for i in ins if in_source(i) in jm_set)
        out_miss, in_miss = len(outs) - out_hit, len(ins) - in_hit

        res['out']['total'] += 1
        res['in']['total'] += 1
        res['both']['total'] += 1
        res['per_year'][year]['total'] += 1
        res['out_miss'][min(out_miss, 5)] += 1
        res['in_miss'][min(in_miss, 5)] += 1

        # Vacuous case: a single mixed output trivially satisfies "all but one".
        out_single = len(outs) == 1
        in_single = len(ins) == 1

        if out_miss == 0:
            res['out']['all'] += 1
            res['per_year'][year]['out_all'] += 1
        if out_miss == 1 and not out_single:
            res['out']['all_but_one'] += 1
            res['per_year'][year]['out_abo'] += 1
        if out_single:
            res['out']['single_output'] += 1

        if in_miss == 0:
            res['in']['all'] += 1
            res['per_year'][year]['in_all'] += 1
        if in_miss == 1 and not in_single:
            res['in']['all_but_one'] += 1
            res['per_year'][year]['in_abo'] += 1
        if in_single:
            res['in']['single_input'] += 1

        # The strong signal: one unexplained output AND one unexplained input.
        if out_miss == 1 and in_miss == 1 and not out_single and not in_single:
            res['both']['all_but_one'] += 1
            res['per_year'][year]['both_abo'] += 1
            res['all_but_one_txids'].append(txid)
        if out_miss == 0 and in_miss == 0:
            res['both']['all'] += 1
            res['per_year'][year]['both_all'] += 1
    return res


def _pct(n: int, d: int) -> float:
    return n / d * 100 if d else 0.0


def report(res: Dict[str, Any], label: str):
    o, i, b = res['out'], res['in'], res['both']
    t = o['total']
    print(f"\n{'=' * 72}\n{label}  (n={t} transactions)\n{'=' * 72}")

    print("  OUTPUT SIDE (mixed outputs only)")
    print(f"    all mixed outputs -> JM        : {o['all']:>6} ({_pct(o['all'], t):5.1f}%)")
    print(f"    exactly one output unexplained : {o['all_but_one']:>6} ({_pct(o['all_but_one'], t):5.1f}%)")
    print(f"    all + all-but-one              : {o['all'] + o['all_but_one']:>6} "
          f"({_pct(o['all'] + o['all_but_one'], t):5.1f}%)")
    print(f"    (single-output txs excluded    : {o['single_output']})")

    print("  INPUT SIDE")
    print(f"    all inputs from JM             : {i['all']:>6} ({_pct(i['all'], t):5.1f}%)")
    print(f"    exactly one input unexplained  : {i['all_but_one']:>6} ({_pct(i['all_but_one'], t):5.1f}%)")
    print(f"    (single-input txs excluded     : {i['single_input']})")

    print("  BOTH SIDES  <- the deanonymisation signal")
    print(f"    fully connected both sides     : {b['all']:>6} ({_pct(b['all'], t):5.1f}%)")
    print(f"    one unexplained in AND one out : {b['all_but_one']:>6} ({_pct(b['all_but_one'], t):5.1f}%)")

    print("  distribution of unexplained outputs / inputs per tx:")
    for k in range(6):
        lbl = f"{k}" if k < 5 else "5+"
        print(f"    {lbl:>2}: outputs {res['out_miss'][k]:>6} ({_pct(res['out_miss'][k], t):5.1f}%)"
              f"   inputs {res['in_miss'][k]:>6} ({_pct(res['in_miss'][k], t):5.1f}%)")


def report_years(res: Dict[str, Any], min_n: int = 20):
    """Full per-year breakdown. Years with fewer than min_n transactions are flagged:
    the tail years are both thin and right-censored, so their rates are unreliable."""
    print(f"\n  {'year':>5} {'txs':>6} {'out all':>8} {'out abo':>8} {'out a+abo':>10}"
          f" {'in all':>7} {'in abo':>7} {'both all':>9} {'both abo':>9}")
    for year in sorted(res['per_year']):
        a = res['per_year'][year]
        n = a['total']
        if not n:
            continue
        flag = ' *' if n < min_n else ''
        print(f"  {year:>5} {n:>6} {_pct(a['out_all'], n):>7.1f}% {_pct(a['out_abo'], n):>7.1f}%"
              f" {_pct(a['out_all'] + a['out_abo'], n):>9.1f}% {_pct(a['in_all'], n):>6.1f}%"
              f" {_pct(a['in_abo'], n):>6.1f}% {_pct(a['both_all'], n):>8.1f}%"
              f" {_pct(a['both_abo'], n):>8.1f}%{flag}")
    print(f"    * fewer than {min_n} transactions - rate is unreliable")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default=CORPUS)
    ap.add_argument('--candidates', default=CANDIDATES,
                    help='output-side candidate txids, from mainnet_remix_analysis.py')
    ap.add_argument('--out', default=OUT_DIR)
    ap.add_argument('--mode', choices=['corpus', 'candidates', 'both'], default='both')
    ap.add_argument('--all-outputs', action='store_true',
                    help='count every output, not just standard-denomination ones')
    ap.add_argument('--min-amount', type=float, default=0.0, metavar='BTC',
                    help='only transactions whose median mixed output is >= this (BTC)')
    ap.add_argument('--export', action='store_true',
                    help='write the both-sides all-but-one txids for follow-up')
    args = ap.parse_args()

    cjs = load(args.corpus)
    out_cand = load_candidates(args.candidates)
    in_cand = input_side_candidates(cjs)

    print(f"corpus coinjoins            : {len(cjs)}")
    print(f"output-side candidates      : {len(out_cand)}")
    print(f"input-side candidates       : {len(in_cand)}  (feed >={MIN_SOURCES} distinct coinjoins)")
    print(f"  overlap between the two   : {len(out_cand & in_cand)}")
    print(f"denominator                 : "
          f"{'all outputs' if args.all_outputs else 'standard-denomination outputs only'}")

    denom_only = not args.all_outputs
    results = {}
    if args.min_amount > 0:
        print(f"amount filter               : median mixed output >= {args.min_amount} BTC")
    if args.mode in ('corpus', 'both'):
        res = analyse(cjs, set(cjs), denom_only, args.min_amount)
        report(res, "JM = labeled corpus only")
        results['corpus'] = res
    if args.mode in ('candidates', 'both'):
        res = analyse(cjs, set(cjs) | out_cand | in_cand, denom_only, args.min_amount)
        report(res, "JM = labeled corpus + output-side + input-side candidates")
        report_years(res)
        results['candidates'] = res

    if args.export and 'candidates' in results:
        path = os.path.join(args.out, 'both_sides_all_but_one.txt')
        with open(path, 'w') as fh:
            for txid in sorted(results['candidates']['all_but_one_txids']):
                fh.write(txid + "\n")
        print(f"\n  wrote {path} "
              f"({len(results['candidates']['all_but_one_txids'])} txids)")

    print("\n  NOTE: these are SIGNAL frequencies. The probability that an all-but-one")
    print("  transaction really has a single identifiable taker must be measured")
    print("  against ground truth - see simulate_single_taker_leak.py.")


if __name__ == '__main__':
    main()
