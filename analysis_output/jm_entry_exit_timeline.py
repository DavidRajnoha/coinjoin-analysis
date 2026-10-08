"""
Entering and leaving the JoinMarket mixing chain: a timeline, and how far an exit can be
linked back to its entry.

Classes (untraced = source / spender is not a JoinMarket tx; an unspent output is untraced):
  entry   1 untraced input, every mixed and change output traced into JoinMarket.
          Fresh coins come in and all of them stay in the chain (e.g. a tumbler's first hop).
  exit    no untraced input; 1 untraced mixed output and 1 untraced change output, or 1 untraced
          mixed output and no change at all for one participant (sweep: n_change == n_mixed - 1).
          Coins that were already in the chain leave it (e.g. a tumbler's last hop).

Linking. For each exit, walk the coinjoin graph backwards (input -> the labeled coinjoin that
created it) within a time window and collect the reachable entries: the exit's coins can only
have entered there. Labeled coinjoins only, since candidates carry no timestamp.
  value filter: an entry is value-consistent if its untraced input is worth at least the exit's
  untraced outputs (coins cannot grow; a tumbler splits them, so the exit may be smaller).
  baseline: entries in the same time window that are NOT reachable - how much the graph
  narrows the set compared with timing alone.

Run: .venv/bin/python analysis_output/jm_entry_exit_timeline.py --corpus PATH --candidates PATH [--out DIR]
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as dt
import json
import os
import random
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jm_connectivity_analysis as conn  # noqa: E402

FMT = "%Y-%m-%d %H:%M:%S.%f"
WINDOWS_DAYS = (1, 7, 30)
SAMPLE = 3000  # exits linked per window (backward walks are the expensive part)


def classify(cj, jm):
    outs = list(cj['outputs'].values())
    mixed = [o for o in outs if o.get('is_standard_denom')]
    change = [o for o in outs if not o.get('is_standard_denom')]
    ins = list(cj['inputs'].values())
    if len(mixed) < 2 or len(ins) < 2:
        return None
    ui = [i for i in ins if conn.in_source(i) not in jm]
    um = [o for o in mixed if conn.out_spender(o) not in jm]
    uc = [o for o in change if conn.out_spender(o) not in jm]
    if len(ui) == 1 and not um and not uc:
        return 'entry', ui[0]['value']
    if not ui and len(um) == 1 and (len(uc) == 1 or (not uc and len(change) == len(mixed) - 1)):
        return 'exit', um[0]['value'] + sum(o['value'] for o in uc)
    return None


def q(vals, ps=(10, 25, 50, 75, 90)):
    s = sorted(vals)
    return {p: s[min(len(s) - 1, len(s) * p // 100)] for p in ps} if s else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--candidates', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    cjs = conn.load(args.corpus)
    jm = set(cjs) | conn.load_candidates(args.candidates) | conn.input_side_candidates(cjs)
    t = {k: dt.datetime.strptime(c['broadcast_time'], FMT) for k, c in cjs.items()}
    cls = {}
    for k, c in cjs.items():
        r = classify(c, jm)
        if r:
            cls[k] = r
    entries = {k: v for k, (c, v) in cls.items() if c == 'entry'}
    exits = {k: v for k, (c, v) in cls.items() if c == 'exit'}
    out = {'n_entries': len(entries), 'n_exits': len(exits), 'n_coinjoins': len(cjs)}

    # ---- 1. Timeline -----------------------------------------------------------
    print("=" * 78 + "\n1. TIMELINE OF ENTERING AND LEAVING\n" + "=" * 78)
    print(f"  coinjoins {len(cjs)} | entries {len(entries)} ({len(entries)/len(cjs)*100:.1f}%) | "
          f"exits {len(exits)} ({len(exits)/len(cjs)*100:.1f}%)")
    by_q = collections.defaultdict(collections.Counter)
    for k in cjs:
        qk = f"{t[k].year}Q{(t[k].month - 1) // 3 + 1}"
        by_q[qk]['cj'] += 1
        if k in entries:
            by_q[qk]['entry'] += 1; by_q[qk]['entry_btc'] += entries[k] / 1e8
        if k in exits:
            by_q[qk]['exit'] += 1; by_q[qk]['exit_btc'] += exits[k] / 1e8
    out['quarterly'] = {k: dict(v) for k, v in sorted(by_q.items())}
    print(f"  {'quarter':>8} {'coinjoins':>9} {'entries':>8} {'exits':>6} {'in BTC':>9} {'out BTC':>9}")
    for k, v in sorted(by_q.items()):
        print(f"  {k:>8} {v['cj']:>9} {v['entry']:>8} {v['exit']:>6} {v['entry_btc']:>9.1f} {v['exit_btc']:>9.1f}")

    # ---- 2. Linking exits back to entries -----------------------------------------
    parents = {k: {s for i in c['inputs'].values() if (s := conn.in_source(i)) in cjs}
               for k, c in cjs.items()}
    entry_times = sorted((t[k], k) for k in entries)
    et_keys = [x[0] for x in entry_times]
    rng = random.Random(args.seed)
    sample = rng.sample(sorted(exits), min(SAMPLE, len(exits)))
    out['linking'] = {}
    print("\n" + "=" * 78 + f"\n2. LINKING EXITS BACK TO ENTRIES  ({len(sample)} sampled exits)\n" + "=" * 78)
    print("  reachable = entries upstream of the exit in the coinjoin graph within the window")
    print("  value-ok  = reachable entries whose input is worth >= the exit's untraced outputs")
    print("  timing    = all entries in the same window, graph ignored (baseline)\n")
    for W in WINDOWS_DAYS:
        win = dt.timedelta(days=W)
        reach_n, value_n, time_n, lag_nearest = [], [], [], []
        none_reach = 0
        for x in sample:
            t0, lo = t[x], t[x] - win
            seen, stack, found = {x}, [x], []
            while stack:
                cur = stack.pop()
                for p in parents[cur]:
                    if p in seen or t[p] < lo:
                        continue
                    seen.add(p)
                    stack.append(p)
                    if p in entries:
                        found.append(p)
            ok = [e for e in found if entries[e] >= exits[x]]
            reach_n.append(len(found)); value_n.append(len(ok))
            time_n.append(bisect.bisect_left(et_keys, t0) - bisect.bisect_left(et_keys, lo))
            if ok:
                lag_nearest.append(min((t0 - t[e]).total_seconds() / 86400 for e in ok))
            else:
                none_reach += 1
        row = {'reachable': q(reach_n), 'value_ok': q(value_n), 'timing_only': q(time_n),
               'exactly_one_value_ok': sum(v == 1 for v in value_n),
               'no_value_ok': none_reach, 'nearest_lag_days': q(lag_nearest) if lag_nearest else {}}
        out['linking'][W] = row
        n = len(sample)
        print(f"  window {W:>2} d   median sets: timing {row['timing_only'].get(50)}, "
              f"reachable {row['reachable'].get(50)}, value-ok {row['value_ok'].get(50)}")
        print(f"               p10/p90 value-ok: {row['value_ok'].get(10)} / {row['value_ok'].get(90)}"
              f" | exactly one candidate entry: {row['exactly_one_value_ok']} ({row['exactly_one_value_ok']/n*100:.1f}%)"
              f" | none: {none_reach} ({none_reach/n*100:.1f}%)")
        if lag_nearest:
            nl = row['nearest_lag_days']
            print(f"               lag to nearest value-ok entry (days) p25/p50/p75: "
                  f"{nl[25]:.2f} / {nl[50]:.2f} / {nl[75]:.2f}\n")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, 'entry_exit_timeline.json'), 'w') as fh:
            json.dump(out, fh, indent=1, default=str)
        print(f"  wrote {args.out}/entry_exit_timeline.json")


if __name__ == '__main__':
    main()
