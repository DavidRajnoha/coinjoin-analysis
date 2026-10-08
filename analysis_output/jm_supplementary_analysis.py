"""
Supplementary FINDINGS.md figures not produced by the other scripts.

  §1  mixed-output share and per-tx count
  §3  remix rate by CoinJoin amount (90-day window) and per-year amount mix
  §4  connectivity at several amount thresholds (all / >=1 / >=5 / >=10 BTC)
  §5  monthly traffic density vs connectivity, raw and within-year
  §8.1 lag until all mixed outputs are remixed, in days and intervening JM txs
  H1  resolution timescale: all-but-one vs fully-mixed transactions

Definitions follow mainnet_remix_analysis.py and jm_connectivity_analysis.py:
'mixed' = is_standard_denom, 'amount' = median mixed-output value, connectivity
counts output- and input-side candidates as JoinMarket. Lags use labeled spenders
only, since candidates carry no timestamp.

Run:  .venv/bin/python analysis_output/jm_supplementary_analysis.py \
          --corpus PATH --candidates PATH [--json OUT]
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as dt
import json
import statistics as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jm_connectivity_analysis as conn  # noqa: E402

FMT = "%Y-%m-%d %H:%M:%S.%f"
BUCKETS = [(0, 0.01, '<0.01'), (0.01, 0.1, '0.01-0.1'), (0.1, 0.5, '0.1-0.5'),
           (0.5, 1, '0.5-1'), (1, 5, '1-5'), (5, 20, '5-20'), (20, float('inf'), '>20')]
WINDOW = 90


def pearson(xs, ys):
    mx, my = st.fmean(xs), st.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else float('nan')


def pct(a, b):
    return a / b * 100 if b else 0.0


def quantiles(vals, qs=(50, 75, 90, 95, 99)):
    s = sorted(vals)
    return {q: s[min(len(s) - 1, int(len(s) * q / 100))] for q in qs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default=conn.CORPUS)
    ap.add_argument('--candidates', default=conn.CANDIDATES)
    ap.add_argument('--json', help='write all results here')
    args = ap.parse_args()

    cjs = conn.load(args.corpus)
    times = {t: dt.datetime.strptime(c['broadcast_time'], FMT) for t, c in cjs.items()}
    last = max(times.values())
    order = sorted(times.values())
    jm = set(cjs) | conn.load_candidates(args.candidates) | conn.input_side_candidates(cjs)
    out = {}

    # §1 mixed outputs
    n_out = sum(len(c['outputs']) for c in cjs.values())
    mixed = [sum(1 for o in c['outputs'].values() if o.get('is_standard_denom'))
             for c in cjs.values()]
    q = sorted(mixed)
    out['s1'] = {'outputs': n_out, 'mixed_share': pct(sum(mixed), n_out),
                 'mixed_median': st.median(mixed), 'p10': q[len(q) // 10],
                 'p90': q[len(q) * 9 // 10]}
    print("§1 mixed share %.1f%%, median %s mixed/tx (p10 %s, p90 %s)" % (
        out['s1']['mixed_share'], out['s1']['mixed_median'], out['s1']['p10'], out['s1']['p90']))

    # §3 remix rate by amount, 90-day window, mixed outputs
    cutoff = last - dt.timedelta(days=WINDOW)
    agg = {b[2]: collections.Counter() for b in BUCKETS}
    year_mix = collections.defaultdict(collections.Counter)
    for txid, c in cjs.items():
        outs = [o for o in c['outputs'].values() if o.get('is_standard_denom')]
        if not outs:
            continue
        amt = st.median(o['value'] for o in outs) / 1e8
        label = next(b[2] for b in BUCKETS if b[0] <= amt < b[1])
        year_mix[c['broadcast_time'][:4]][label] += 1
        if times[txid] > cutoff:
            continue
        a = agg[label]
        a['txs'] += 1
        for o in outs:
            a['outputs'] += 1
            sp = conn.out_spender(o)
            if sp in cjs and (times[sp] - times[txid]).days <= WINDOW:
                a['remixed'] += 1
            if sp is not None and sp not in jm:
                a['outside'] += 1
            if sp is not None and sp not in cjs:
                a['outside_incl_cand'] += 1
    out['s3'] = {k: dict(v, rate=pct(v['remixed'], v['outputs']),
                         outside_share=pct(v['outside'], v['outputs']),
                         outside_incl_cand_share=pct(v['outside_incl_cand'], v['outputs']))
                for k, v in agg.items()}
    out['s3_year_mix'] = {y: {k: pct(v[k], sum(v.values())) for k in agg}
                          for y, v in sorted(year_mix.items())}
    print("\n§3 remix by amount (90d window, mixed outputs)")
    print(f"  {'amount':>9} {'txs':>7} {'outputs':>8} {'rate':>6} {'outside':>8} {'not in corpus':>14}")
    for k, v in out['s3'].items():
        print(f"  {k:>9} {v['txs']:>7} {v['outputs']:>8} {v['rate']:>5.1f}% {v['outside_share']:>7.1f}%"
              f" {v['outside_incl_cand_share']:>13.1f}%")
    print("  per-year share of txs by amount bucket:")
    print("  year " + " ".join(f"{b[2]:>8}" for b in BUCKETS))
    for y, v in out['s3_year_mix'].items():
        print(f"  {y} " + " ".join(f"{v[b[2]]:>7.1f}%" for b in BUCKETS))

    # §4 connectivity at several thresholds
    out['s4'] = {}
    print("\n§4 connectivity (JM = corpus + candidates, mixed outputs)")
    hdr = ['n', 'out all', 'out abo', 'out a+abo', 'in all', 'in abo', 'both all', 'both abo',
           'out 5+', 'in 5+']
    print("  " + f"{'min BTC':>8} " + " ".join(f"{h:>9}" for h in hdr))
    res_by_min = {}
    for m in (0.0, 1.0, 5.0, 10.0):
        r = conn.analyse(cjs, jm, True, m)
        res_by_min[m] = r
        t = r['out']['total']
        row = {'n': t, 'out_all': pct(r['out']['all'], t), 'out_abo': pct(r['out']['all_but_one'], t),
               'out_a_abo': pct(r['out']['all'] + r['out']['all_but_one'], t),
               'in_all': pct(r['in']['all'], t), 'in_abo': pct(r['in']['all_but_one'], t),
               'both_all': pct(r['both']['all'], t), 'both_abo': pct(r['both']['all_but_one'], t),
               'out_5plus': pct(r['out_miss'][5], t), 'in_5plus': pct(r['in_miss'][5], t),
               'both_abo_count': r['both']['all_but_one']}
        out['s4'][m] = row
        print(f"  {m:>8} {t:>9} " + " ".join(f"{v:>8.1f}%" for k, v in row.items()
                                               if k not in ('n', 'both_abo_count')))
    r1 = res_by_min[1.0]
    out['s4_years_ge1'] = {}
    print("\n§4.1 per-year, >=1 BTC")
    print(f"  {'year':>5} {'txs':>6} {'out all':>8} {'out abo':>8} {'out a+abo':>10}"
          f" {'in all':>7} {'in abo':>7} {'both all':>9} {'both abo':>9}")
    for y in sorted(r1['per_year']):
        a = r1['per_year'][y]
        n = a['total']
        row = {'n': n, 'out_all': pct(a['out_all'], n), 'out_abo': pct(a['out_abo'], n),
               'out_a_abo': pct(a['out_all'] + a['out_abo'], n), 'in_all': pct(a['in_all'], n),
               'in_abo': pct(a['in_abo'], n), 'both_all': pct(a['both_all'], n),
               'both_abo': pct(a['both_abo'], n)}
        out['s4_years_ge1'][y] = row
        print(f"  {y:>5} {n:>6} " + " ".join(f"{v:>8.1f}%" for k, v in row.items() if k != 'n'))

    # §5 monthly density, >=1 BTC, months with n>=30
    monthly = collections.defaultdict(collections.Counter)
    for txid, c in cjs.items():
        outs = [o for o in c['outputs'].values() if o.get('is_standard_denom')]
        ins = list(c['inputs'].values())
        if not outs or not ins or st.median(o['value'] for o in outs) / 1e8 < 1.0:
            continue
        om = sum(1 for o in outs if conn.out_spender(o) not in jm)
        im = sum(1 for i in ins if conn.in_source(i) not in jm)
        m = monthly[c['broadcast_time'][:7]]
        m['n'] += 1
        m['out_all'] += om == 0
        m['out_a_abo'] += om == 0 or (om == 1 and len(outs) > 1)
        m['both_abo'] += om == 1 and im == 1 and len(outs) > 1 and len(ins) > 1
    months = {k: v for k, v in sorted(monthly.items()) if v['n'] >= 30}
    out['s5'] = {'months': len(months)}
    if len(months) >= 3:
        ns = [v['n'] for v in months.values()]
        out['s5'].update(median_n=st.median(ns), min_n=min(ns), max_n=max(ns))
        print(f"\n§5 monthly density, >=1 BTC, {len(months)} months with n>=30 "
              f"(median {st.median(ns)}, range {min(ns)}-{max(ns)})")
        print(f"  {'metric':>12} {'raw r':>7} {'within-yr r':>12}")
        for metric in ('out_all', 'out_a_abo', 'both_abo'):
            xs = [v['n'] for v in months.values()]
            ys = [pct(v[metric], v['n']) for v in months.values()]
            yrs = [k[:4] for k in months]
            by_year = collections.defaultdict(list)
            for yr, x, y in zip(yrs, xs, ys):
                by_year[yr].append((x, y))
            mean = {yr: (st.fmean(p[0] for p in v), st.fmean(p[1] for p in v))
                    for yr, v in by_year.items()}
            dx = [x - mean[yr][0] for yr, x in zip(yrs, xs)]
            dy = [y - mean[yr][1] for yr, y in zip(yrs, ys)]
            raw, within = pearson(xs, ys), pearson(dx, dy)
            out['s5'][metric] = {'raw': raw, 'within_year': within}
            print(f"  {metric:>12} {raw:>+7.2f} {within:>+12.2f}")

    # §8.1 lag until all mixed outputs remixed; outputs into candidates count as remixed
    # but carry no timestamp, so the lag runs to the last LABELED spender. H1 timescale
    lag_days, lag_txs, abo_txs = [], [], []
    for txid, c in cjs.items():
        outs = [o for o in c['outputs'].values() if o.get('is_standard_denom')]
        if len(outs) < 2:
            continue
        sps = [conn.out_spender(o) for o in outs]
        known = [s for s in sps if s in cjs]
        miss = sum(1 for s in sps if s not in jm)
        if miss > 1 or not known:
            continue
        t0 = times[txid]
        tl = max(times[s] for s in known)
        between = max(0, bisect.bisect_left(order, tl) - bisect.bisect_right(order, t0))
        if miss == 0:
            lag_days.append((tl - t0).total_seconds() / 86400)
            lag_txs.append(between)
        else:
            abo_txs.append(between)
    out['s8_1'] = {'n': len(lag_days), 'days': quantiles(lag_days), 'txs': quantiles(lag_txs),
                   'within_50': pct(sum(x <= 50 for x in lag_txs), len(lag_txs)),
                   'within_100': pct(sum(x <= 100 for x in lag_txs), len(lag_txs)),
                   'within_500': pct(sum(x <= 500 for x in lag_txs), len(lag_txs)),
                   'h1_median_full': st.median(lag_txs) if lag_txs else None,
                   'h1_median_abo': st.median(abo_txs) if abo_txs else None}
    s = out['s8_1']
    print(f"\n§8.1 lag until all mixed outputs remixed (n={s['n']}, lag to labeled spenders only)")
    print("  unit   " + " ".join(f"{'p' + str(k):>8}" for k in s['days']))
    print("  days   " + " ".join(f"{v:>8.1f}" for v in s['days'].values()))
    print("  JM txs " + " ".join(f"{v:>8}" for v in s['txs'].values()))
    print(f"  within 50/100/500 txs: {s['within_50']:.1f}% / {s['within_100']:.1f}% / {s['within_500']:.1f}%")
    print(f"  H1: median intervening txs, fully-mixed {s['h1_median_full']} vs all-but-one {s['h1_median_abo']}")

    if args.json:
        with open(args.json, 'w') as fh:
            json.dump(out, fh, indent=1, default=str)
        print(f"\n  wrote {args.json}")


if __name__ == '__main__':
    main()
