"""Thesis-style summary (Tables 3.9 and 3.10) from the merged blackbox cache of a run."""
import collections
import json
import os
import pickle
import statistics as st
import sys

sys.path.insert(0, '/app')

run = sys.argv[1]
with open(os.path.join(run, 'analysis_cache', 'blackbox_cj_objs.pkl'), 'rb') as fh:
    objs = pickle.load(fh)


def status(o):
    if o.meta.get('sudoku_solved'):
        return 'Solved'
    return 'Skipped' if o.meta.get('skipped') else 'Unsolved'


def participants(o):
    if o.participants:
        return len(o.participants)
    vals = collections.Counter(v['value'] for v in o.tx['vout'])
    return vals.most_common(1)[0][1]  # equal outputs = participants


rows = {}
for s in ('Solved', 'Skipped', 'Unsolved'):
    sub = [o for o in objs if status(o) == s]
    if not sub:
        rows[s] = {'count': 0}
        continue
    ins = [len(o.tx['vin']) for o in sub]
    par = [participants(o) for o in sub]
    rows[s] = {'count': len(sub), 'avg_inputs': round(st.fmean(ins), 2), 'avg_participants': round(st.fmean(par), 2),
               'avg_inputs_per_participant': round(st.fmean(i / p for i, p in zip(ins, par)), 2)}

sols = sorted(o.meta.get('num_solutions', 0) for o in objs if status(o) == 'Solved')
cdf = {k: sum(1 for s in sols if s <= k) for k in (1, 2, 4, 10, 100, 1000)}
out = {'transactions': len(objs), 'table_3_9': rows,
       'table_3_10': {str(k): {'transactions': v, 'cumulative_pct': round(v / len(sols) * 100, 2) if sols else 0}
                      for k, v in cdf.items()}}

report = os.path.join(run, 'report_unified', 'unified_coinjoin_report.json')
if os.path.exists(report):
    with open(report) as fh:
        r = json.load(fh)
    cc = r.get('chain_comparison_summary', {})
    out['chains_total_including_singletons'] = cc.get('total_blackbox_chains')
    out['taker_outputs_identified'] = (cc.get('taker_cj_output_details') or {}).get('bb_attributed_count')

with open(os.path.join(run, 'thesis_tables.json'), 'w') as fh:
    json.dump(out, fh, indent=1)
print(json.dumps(out, indent=1))
