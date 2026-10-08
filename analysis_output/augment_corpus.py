"""
Recover JoinMarket coinjoins that Dumplings filed as post-mix because of protocol precedence.

Dumplings labels a native-segwit tx with >=10 equal ~0.1 BTC outputs as Wasabi 1, ahead of
the JoinMarket ('other') rule. parse_dumplings' restore_false_positives_for_others moves
such mislabeled JoinMarket coinjoins back, but copies their CHILDREN only as post-mix
records: a child spending a 'Wasabi 1' output was demoted at scan time (isOtherCj=false)
and is never re-evaluated. They end up in the 'postmix' section of coinjoin_tx_info.json.

This script promotes every post-mix tx that
  * passes the patched Dumplings isOtherCj (D5 fix: allowance max(0.001 BTC, 0.5% of v),
    n>=3 equal outputs, or >=2 JoinMarket parents),
  * passes parse_dumplings CJ_TX_CHECK.BASIC (in/out ratio <=4, <=100 ins/outs,
    script reuse <=0.34, no OP_RETURN) and carries no fp_reason,
  * is not itself Wasabi 1 / Wasabi 2 / Samourai shaped,
iterating until no more are promoted (promotion adds JoinMarket parents for the parent rule).

It deliberately ignores demotion. It cannot recover hidden coinjoins that are absent from
the file altogether (all their JoinMarket parents were hidden): ~500-800 by an API-sampled
estimate, which needs a spend index or a Dumplings rescan.

Promoted txs with fewer than 5 equal outputs are tagged fp_reason=MIN_SAME_VALUES_THRESHOLD,
matching how the 2026 corpus tags its own 3-4 party coinjoins.

Writes:
  <out>                    corpus + promoted, all MIN_SAME-tagged txs kept
  <out stem>_min5.json     same without MIN_SAME-tagged txs (sensitivity variant)

Run: .venv/bin/python analysis_output/augment_corpus.py [--corpus PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import collections
import json
import os

CORPUS = 'data/joinmarket/real-data-2026/coinjoin_tx_info.json'
OUT = 'data/joinmarket/real-data-2026/coinjoin_tx_info_augmented.json'
SEG = 'TxWitnessV0Keyhash'
SAMOURAI_POOLS = {100_000, 1_000_000, 5_000_000, 50_000_000, 25_000_000, 2_500_000}
W1_FROM = '2020-01-07'   # ~block 610,000, Constants.FirstWasabiNoCoordAddressBlock
W2_FROM = '2022-06-18'   # ~block 741,213, Constants.FirstWasabi2Block
MIN_SAME = 5             # 2026 corpus tags coinjoins with 3-4 equal outputs


def parent_txids(tx):
    return {i['spending_tx'].split('_')[1] for i in tx['inputs'].values()
            if i.get('spending_tx', '').startswith('vout_')}


def accept(tx, n_jm_parents: int) -> bool:
    """Patched Dumplings isOtherCj + BASIC post-processing + no other-protocol shape."""
    if 'fp_reason' in tx:
        return False
    ins, outs = list(tx['inputs'].values()), list(tx['outputs'].values())
    if not ins or not outs:
        return False
    ov = [o['value'] for o in outs]
    iv = [i['value'] for i in ins]
    counts = collections.Counter(ov)
    groups = {v: c for v, c in counts.items() if c > 1}
    if len(groups) != 1:                                                   # D0, D1
        return False
    v, n = next(iter(groups.items()))
    if n < 3 or not (n == len(outs) - n or n == len(outs) - n + 1):        # n>=3, D2
        return False
    if len({o['script'] for o in outs}) < n or len({i['script'] for i in ins}) < n:  # D3, D4
        return False
    non_eq = [x for x in ov if x != v]
    bound_ok = bool(non_eq) and max(iv) <= v + max(non_eq) + max(100_000, v * 5 // 1000)
    if not bound_ok and n_jm_parents < 2:                                   # D5 or parent rule
        return False
    # BASIC post-processing
    scripts = [i['script'] for i in ins] + [o['script'] for o in outs]
    if max(len(ins), len(outs)) / min(len(ins), len(outs)) > 4 or len(ins) > 100 or len(outs) > 100:
        return False
    if collections.Counter(scripts).most_common(1)[0][1] / len(scripts) > 0.34:
        return False
    if any(o['script_type'] == 'TxNullData' for o in outs):
        return False
    # Not another protocol's coinjoin
    t = tx['broadcast_time']
    segonly = all(i['script_type'] == SEG for i in ins) and all(o['script_type'] == SEG for o in outs)
    if (t >= W1_FROM and segonly and n >= 10 and len(ins) >= n and 8_000_000 <= v <= 12_000_000
            and sum(1 for c in counts.values() if c == 1) >= 2):
        return False
    if (t >= W2_FROM and len(ins) >= 50 and iv == sorted(iv, reverse=True) and ov == sorted(ov, reverse=True)
            and all(i['script_type'] in (SEG, 'TxWitnessV1Taproot') for i in ins)):
        return False
    if segonly and 5 <= len(ins) <= 10 and len(ins) == len(outs) and len(counts) == 1 and ov[0] in SAMOURAI_POOLS:
        return False
    return True


def promote(cjs, pm):
    """Move every acceptable post-mix tx into cjs, iterating to a fixed point.

    Modifies cjs in place and returns the promoted txids.
    """
    jm = set(cjs)
    promoted = []
    rnd = 0
    while True:
        rnd += 1
        new = [t for t, tx in pm.items()
               if t not in jm and accept(tx, len(parent_txids(tx) & jm))]
        print(f'round {rnd}: promoted {len(new)}')
        if not new:
            break
        jm.update(new)
        promoted.extend(new)

    tagged = 0
    for t in promoted:
        tx = pm[t]
        counts = collections.Counter(o['value'] for o in tx['outputs'].values())
        for o in tx['outputs'].values():
            o['is_standard_denom'] = counts[o['value']] > 1
        if max(counts.values()) < MIN_SAME:
            tx['fp_reason'] = 'MIN_SAME_VALUES_THRESHOLD'
            tagged += 1
        tx['promoted_from_postmix'] = True
        cjs[t] = tx
    print(f'promoted {len(promoted)} txs ({tagged} tagged MIN_SAME_VALUES_THRESHOLD); '
          f'corpus now {len(cjs)}')
    return promoted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default=CORPUS)
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()

    with open(args.corpus) as fh:
        data = json.load(fh)
    cjs, pm = data['coinjoins'], data['postmix']
    promoted = promote(cjs, pm)

    years = collections.Counter(pm[t]['broadcast_time'][:4] for t in promoted)
    print('promoted per year:', dict(sorted(years.items())))

    meta = {'source': os.path.abspath(args.corpus), 'promoted': sorted(promoted)}
    with open(args.out, 'w') as fh:
        json.dump({'coinjoins': cjs, 'augmentation': meta}, fh)
    print(f'wrote {args.out}')

    stem, ext = os.path.splitext(args.out)
    min5 = {t: c for t, c in cjs.items() if c.get('fp_reason') != 'MIN_SAME_VALUES_THRESHOLD'}
    with open(f'{stem}_min5{ext}', 'w') as fh:
        json.dump({'coinjoins': min5, 'augmentation': meta}, fh)
    print(f'wrote {stem}_min5{ext} ({len(min5)} coinjoins)')


if __name__ == '__main__':
    main()
