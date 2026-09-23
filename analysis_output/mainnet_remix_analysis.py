"""
Mainnet JoinMarket remix analysis.

Measures how often a CoinJoin output is respent into another CoinJoin, using the
labeled mainnet corpus (data/joinmarket/real-data/coinjoin_tx_info.json).

WHAT THIS DOES *NOT* MEASURE
----------------------------
Maker-specific reuse. Mainnet `wallet_name` is uniformly 'real_unknown', so there is
no role attribution: we cannot tell a maker's output from a taker's. Everything here
is remixing by ANY participant. Maker-specific rates exist only in whitebox data
(see joinmarket/common/maker_utxo_reuse.py), where roles are known but the observation
window is too short for the rate to stabilise.

THE MEASURED RATE IS A LOWER BOUND
----------------------------------
An output counts as remixed only if its spender is itself a LABELED corpus coinjoin.
Coinjoins missing from the corpus therefore read as "spent outside". Section 4
estimates how large that gap may be, by flagging external transactions that absorb
outputs from many distinct corpus coinjoins - a convergence pattern ordinary onward
spends do not produce. Those are CANDIDATES, not confirmations: without the external
transactions' input/output structure they cannot be verified, and the resulting upper
bound is highly sensitive to the threshold (section 5).

Sections
  1. Corpus overview and spender coverage
  2. Remix-by-age, with a fixed denominator per age (the trustworthy estimator)
  3. Per-year rates on an equal observation window
  4. Three-way fate split and the lower/upper bounds
  5. Sensitivity of the upper bound to the 'suspicious' threshold
  6. Per-year fate split
  7. Export of candidate txids

Run:  .venv/bin/python analysis_output/mainnet_remix_analysis.py [--out DIR] [--min-sources N]
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import os
import statistics as st
from typing import Any, Dict, List, Set, Tuple

CORPUS_PATH = 'data/joinmarket/real-data/coinjoin_tx_info.json'
DEFAULT_OUT = 'analysis_output'

# An external tx fed by at least this many DISTINCT corpus coinjoins is flagged as a
# possible unlabeled coinjoin. See section 5 - the upper bound moves a lot with this.
DEFAULT_MIN_SOURCES = 3

# Ages (days) for the fixed-denominator remix curve.
AGE_DAYS = [1, 3, 7, 14, 30, 60, 90, 180, 365]

# Observation window used when comparing years on equal terms.
EQUAL_WINDOW_DAYS = 90


def load_corpus(path: str = CORPUS_PATH) -> Tuple[Dict[str, Any], Dict[str, dt.datetime]]:
    """Load the corpus and parse each coinjoin's broadcast time."""
    with open(path) as fh:
        data = json.load(fh)
    cjs = data['coinjoins']
    times = {
        txid: dt.datetime.strptime(c['broadcast_time'], "%Y-%m-%d %H:%M:%S.%f")
        for txid, c in cjs.items()
    }
    return cjs, times


def _spender(output: Dict[str, Any]) -> str | None:
    """The txid that spent this output, or None if none is recorded.

    The corpus stores it as 'vin_<txid>_<n>'.
    """
    sb = output.get('spend_by_tx')
    if not sb or not sb.startswith('vin_'):
        return None
    return sb.split('_')[1]


def external_source_map(cjs: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Map each EXTERNAL spender tx to the set of corpus coinjoins feeding it.

    External means the spender is not itself a labeled corpus coinjoin. A tx fed by
    many distinct coinjoins is a candidate unlabeled coinjoin.
    """
    ext: Dict[str, Set[str]] = collections.defaultdict(set)
    for txid, cj in cjs.items():
        for output in cj['outputs'].values():
            spender = _spender(output)
            if spender is not None and spender not in cjs:
                ext[spender].add(txid)
    return ext


def classify_outputs(cjs: Dict[str, Any], candidates: Set[str]):
    """Assign every corpus output to exactly one fate bucket.

    Returns (counts, per_year) where buckets are:
        known     - respent into a labeled corpus coinjoin
        suspicious- respent into a flagged multi-source external tx
        outside   - respent into an ordinary external tx
        never     - no spender recorded (unspent, or spend not captured)
    """
    counts = collections.Counter()
    per_year = collections.defaultdict(collections.Counter)
    for txid, cj in cjs.items():
        year = cj['broadcast_time'][:4]
        for output in cj['outputs'].values():
            counts['total'] += 1
            per_year[year]['total'] += 1
            spender = _spender(output)
            if spender is None:
                bucket = 'never'
            elif spender in cjs:
                bucket = 'known'
            elif spender in candidates:
                bucket = 'suspicious'
            else:
                bucket = 'outside'
            counts[bucket] += 1
            per_year[year][bucket] += 1
    return counts, per_year


def remix_by_age(cjs, times, ages=AGE_DAYS):
    """Fraction respent into a known coinjoin within A days, per age A.

    Each row's denominator counts only outputs that were observable for the full A
    days, so rows are comparable to each other and not distorted by the corpus edge.
    """
    last = max(times.values())
    rows = []
    for age in ages:
        cutoff = last - dt.timedelta(days=age)
        at_risk = hits = 0
        for txid, cj in cjs.items():
            t0 = times[txid]
            if t0 > cutoff:
                continue
            for output in cj['outputs'].values():
                at_risk += 1
                spender = _spender(output)
                if spender in cjs and (times[spender] - t0).total_seconds() <= age * 86400:
                    hits += 1
        if at_risk:
            rows.append({'age_days': age, 'at_risk': at_risk, 'remixed': hits,
                         'rate': hits / at_risk * 100})
    return rows


def per_year_equal_window(cjs, times, window_days=EQUAL_WINDOW_DAYS):
    """Per-year remix rate measured on an identical observation window.

    Without this, recent years look artificially low purely because their outputs
    have had less time to be respent.
    """
    last = max(times.values())
    cutoff = last - dt.timedelta(days=window_days)
    per_year = collections.defaultdict(lambda: [0, 0])
    for txid, cj in cjs.items():
        t0 = times[txid]
        if t0 > cutoff:
            continue
        year = t0.year
        for output in cj['outputs'].values():
            per_year[year][0] += 1
            spender = _spender(output)
            if spender in cjs and (times[spender] - t0).days <= window_days:
                per_year[year][1] += 1
    return {y: {'at_risk': n, 'remixed': r, 'rate': r / n * 100}
            for y, (n, r) in sorted(per_year.items()) if n}


def threshold_sensitivity(cjs, ext, thresholds=(2, 3, 4, 5, 8, 12, 20)):
    """How the upper bound moves with the 'suspicious' threshold.

    Included because the bound is a judgement call, not a measurement: at N>=8 it
    nearly collapses onto the measured rate.
    """
    total = sum(len(c['outputs']) for c in cjs.values())
    known = sum(1 for c in cjs.values() for o in c['outputs'].values()
                if (_spender(o) or '') in cjs)
    rows = []
    for n in thresholds:
        flagged = {k for k, v in ext.items() if len(v) >= n}
        absorbed = sum(1 for c in cjs.values() for o in c['outputs'].values()
                       if (_spender(o) or '') in flagged)
        rows.append({'threshold': n, 'n_ext_txs': len(flagged), 'outputs': absorbed,
                     'share': absorbed / total * 100,
                     'upper_bound': (known + absorbed) / total * 100})
    return rows


def export_candidates(candidates, ext, cjs, times, out_dir):
    """Write candidate txids for later structural verification against a node."""
    os.makedirs(out_dir, exist_ok=True)
    txt = os.path.join(out_dir, 'suspicious_unlabeled_cj_candidates.txt')
    csv_path = os.path.join(out_dir, 'suspicious_unlabeled_cj_candidates.csv')

    absorbed = collections.Counter()
    earliest = {}
    for txid, cj in cjs.items():
        for output in cj['outputs'].values():
            spender = _spender(output)
            if spender in candidates:
                absorbed[spender] += 1
                t0 = times[txid]
                if spender not in earliest or t0 < earliest[spender]:
                    earliest[spender] = t0

    with open(txt, 'w') as fh:
        for txid in sorted(candidates):
            fh.write(txid + "\n")

    with open(csv_path, 'w', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['txid', 'n_source_coinjoins', 'n_corpus_outputs_absorbed',
                         'earliest_source_cj_time'])
        for txid in sorted(candidates, key=lambda t: -len(ext[t])):
            writer.writerow([txid, len(ext[txid]), absorbed[txid],
                             earliest[txid].isoformat()])
    return txt, csv_path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--corpus', default=CORPUS_PATH)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--min-sources', type=int, default=DEFAULT_MIN_SOURCES,
                    help='external tx fed by >= this many distinct coinjoins is flagged')
    args = ap.parse_args()

    cjs, times = load_corpus(args.corpus)
    ext = external_source_map(cjs)
    candidates = {k for k, v in ext.items() if len(v) >= args.min_sources}

    # 1. Overview
    total_outputs = sum(len(c['outputs']) for c in cjs.values())
    with_spender = sum(1 for c in cjs.values() for o in c['outputs'].values()
                       if _spender(o) is not None)
    print("=" * 78)
    print("1. CORPUS OVERVIEW")
    print("=" * 78)
    print(f"  coinjoins                  : {len(cjs)}")
    print(f"  span                       : {min(times.values()).date()} -> {max(times.values()).date()}")
    print(f"  outputs                    : {total_outputs}")
    print(f"  with a recorded spender    : {with_spender} ({with_spender/total_outputs*100:.1f}%)")
    print("  NOTE: no role attribution on mainnet - this is remixing by ANY participant.")

    # 2. Remix by age
    print("\n" + "=" * 78)
    print("2. REMIX BY AGE  (fixed denominator per age - the trustworthy estimator)")
    print("=" * 78)
    print(f"  {'age (d)':>8} {'at risk':>10} {'remixed':>9} {'rate':>7}")
    rows = remix_by_age(cjs, times)
    for r in rows:
        print(f"  {r['age_days']:>8} {r['at_risk']:>10} {r['remixed']:>9} {r['rate']:>6.1f}%")
    if len(rows) >= 3:
        tail = [r['rate'] for r in rows[-3:]]
        print(f"  tail spread over last 3 ages: {max(tail)-min(tail):.1f} pp "
              f"({'converged' if max(tail)-min(tail) < 2 else 'still moving'})")

    # 3. Per-year, equal window
    print("\n" + "=" * 78)
    print(f"3. PER-YEAR RATE  (equal {EQUAL_WINDOW_DAYS}-day observation window)")
    print("=" * 78)
    print(f"  {'year':>6} {'at risk':>10} {'remixed':>9} {'rate':>7}")
    for year, r in per_year_equal_window(cjs, times).items():
        print(f"  {year:>6} {r['at_risk']:>10} {r['remixed']:>9} {r['rate']:>6.1f}%")

    # 4. Fate split
    counts, per_year = classify_outputs(cjs, candidates)
    total = counts['total']
    print("\n" + "=" * 78)
    print(f"4. FATE OF EVERY OUTPUT  (candidate threshold: >={args.min_sources} sources)")
    print("=" * 78)
    for key, label in [('known', 'respent into a KNOWN corpus coinjoin'),
                       ('suspicious', 'respent into a SUSPICIOUS multi-source ext tx'),
                       ('outside', 'respent completely OUTSIDE'),
                       ('never', 'never spent / no spender recorded')]:
        print(f"  {label:48}: {counts[key]:>7} ({counts[key]/total*100:5.1f}%)")
    lower = counts['known'] / total * 100
    upper = (counts['known'] + counts['suspicious']) / total * 100
    print(f"\n  LOWER BOUND (known remix only) : {lower:.1f}%")
    print(f"  UPPER BOUND (known + suspicious): {upper:.1f}%")
    print("  The upper bound counts unverified candidates - treat it as soft.")

    # 5. Threshold sensitivity
    print("\n" + "=" * 78)
    print("5. SENSITIVITY OF THE UPPER BOUND TO THE THRESHOLD")
    print("=" * 78)
    print(f"  {'N':>3} {'ext txs':>9} {'outputs':>9} {'share':>7} {'upper bound':>12}")
    for r in threshold_sensitivity(cjs, ext):
        print(f"  {r['threshold']:>3} {r['n_ext_txs']:>9} {r['outputs']:>9} "
              f"{r['share']:>6.1f}% {r['upper_bound']:>11.1f}%")
    print("  The bound is a judgement call, not a measurement.")

    # 6. Per-year fate
    print("\n" + "=" * 78)
    print("6. PER-YEAR FATE SPLIT")
    print("=" * 78)
    print(f"  {'year':>6} {'outputs':>9} {'known':>7} {'suspic':>7} {'outside':>8} "
          f"{'never':>6} {'bounds':>16}")
    for year in sorted(per_year):
        a = per_year[year]
        n = a['total']
        lo = a['known'] / n * 100
        hi = (a['known'] + a['suspicious']) / n * 100
        print(f"  {year:>6} {n:>9} {lo:>6.1f}% {a['suspicious']/n*100:>6.1f}% "
              f"{a['outside']/n*100:>7.1f}% {a['never']/n*100:>5.1f}% "
              f"{lo:>6.1f}..{hi:<6.1f}")

    # 7. Export
    txt, csv_path = export_candidates(candidates, ext, cjs, times, args.out)
    print("\n" + "=" * 78)
    print("7. EXPORT")
    print("=" * 78)
    print(f"  candidates: {len(candidates)}  ({len(candidates)/len(cjs)*100:.0f}% of labeled corpus)")
    print(f"  wrote {txt}")
    print(f"  wrote {csv_path}")
    print("  Verify these structurally against a node before trusting the upper bound:")
    print("  expect n equal-valued outputs, n or n-1 change outputs, and >= n inputs.")


if __name__ == '__main__':
    main()
