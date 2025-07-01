#!/usr/bin/env python3
"""
Blockchain Analyst Report Generator (Decimal / satoshi‑exact version)

All monetary values are converted **once** from BTC to *satoshis*
(1 BTC = 100 000 000 sat) and thereafter carried as `Decimal` integers.
This avoids float‑rounding artefacts when comparing miner‑fee deltas.

Changes in this revision
-----------------------
* **Taker overspend bound** – we now cap the taker’s negative Δ so that it
  can never exceed the theoretical maximum the makers could absorb
  ( miner_fee + (N‑1)·maker_gain_max + fee_tol ).  This eliminates the
  huge –100 M sat deltas you saw in the debugger and prevents premature
  pruning.
* Added prefix‑sum pruning for the taker analogous to the maker branch.
* Fixed identity test (`is` → `!=`) when building `maker_changes` to avoid
  accidental empty maker lists after deepcopy‑heavy pipelines.

The public API is unchanged.
"""

from __future__ import annotations

from decimal import Decimal, getcontext
from itertools import combinations
from typing import Any, Dict, List, Tuple
from collections import defaultdict

# ─────────────────────────────────────────────────────────────────────────────
# Decimal / denomination setup
# ─────────────────────────────────────────────────────────────────────────────
getcontext().prec = 30                        # plenty for 64‑bit ints
SAT_MULT = Decimal('100000000')               # BTC → satoshi
SAT      = Decimal('1')                       # one satoshi (after ×100 M)


# ─────────────────────────────────────────────────────────────────────────────
# External dataclasses  (import paths unchanged)
# ─────────────────────────────────────────────────────────────────────────────
from joinmarket.common.coinjoin_model import (
    CoinJoin,
    TxInput,
    TxOutput,
    CoinJoinParticipant,
)

# ─────────────────────────────────────────────────────────────────────────────
# Sudoku participant helper
# ─────────────────────────────────────────────────────────────────────────────

def _build_participants(best_solution: List[Dict[str, Any]], tx: Dict[str, Any]) -> List[CoinJoinParticipant]:
    """Translate one Sudoku solution into ``CoinJoinParticipant`` objects."""
    participants: List[CoinJoinParticipant] = []

    for part in best_solution:
        # —— inputs ——————————————————————————
        inputs = [
            TxInput(
                txid=vin_info['vin']['txid'],
                vout=vin_info['vin']['vout'],
                value=vin_info['value'],              # Decimal (sat)
                address=None,                         # black‑box ⇒ unknown
            )
            for vin_info in part['inputs']
        ]

        # —— outputs —————————————————————————
        cj_out = part['cj']
        cj_output = TxOutput(
            n=cj_out['n'],
            value=cj_out['value'],                    # Decimal (sat)
            address=tx['vout'][cj_out['n']].get('scriptPubKey', {}).get('address'),
            is_change=False,
        )

        change_output = None
        if part['change'] is not None:
            ch_out = part['change']
            change_output = TxOutput(
                n=ch_out['n'],
                value=ch_out['value'],
                address=tx['vout'][ch_out['n']].get('scriptPubKey', {}).get('address'),
                is_change=True,
            )

        participants.append(
            CoinJoinParticipant(
                inputs=inputs,
                cj_output=cj_output,
                change_output=change_output,
                role=part['role'],
                delta=part['delta'],
            )
        )
    return participants

# ─────────────────────────────────────────────────────────────────────────────
# Top‑level driver
# ─────────────────────────────────────────────────────────────────────────────

def solve_joinmarket_sudoku(
    coinjoins: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
    tx_map: Dict[str, Dict[str, Any]],
):
    """Attempt Sudoku on each candidate CJ, preserving original API."""
    coinjoin_objects: List[CoinJoin] = []
    coinjoin_results: List[Dict[str, Any]] = []

    for txid, tx, block in coinjoins:
        if len(tx['vin']) > 20 or len(tx['vout']) > 30:
            print(f'coinjoin_sudoku: skipping {txid} (too big)')
            solutions = None
        else:
            print(f'coinjoin_sudoku: solving {txid}')
            solutions = coinjoin_sudoku(tx, tx_map)
            coinjoin_results.append({'txid': txid, 'solutions': solutions})

        # —— modal CJ value (works on BTC values in raw tx) ————————
        value_buckets: defaultdict[Decimal, List[int]] = defaultdict(list)
        for n, vout in enumerate(tx['vout']):
            amt_sat = (Decimal(str(vout['value'])) * SAT_MULT).quantize(SAT)
            value_buckets[amt_sat].append(n)
        cj_value = max(
            (v for v, idxs in value_buckets.items() if len(idxs) > 1),
            key=lambda v: len(value_buckets[v]),
            default=None,
        )

        participants = _build_participants(solutions[0], tx) if solutions else []

        coinjoin_objects.append(
            CoinJoin(
                txid=txid,
                block_height=block.get('height', 0),
                tx=tx,
                participants=participants,
                meta={
                    'blackbox_analysis': True,
                    'sudoku_solved': bool(solutions),
                    'candidate_cj_value': cj_value,  # Decimal (sat)
                    'input_count': len(tx['vin']),
                    'output_count': len(tx['vout']),
                },
            )
        )

    return coinjoin_objects, coinjoin_results

# ─────────────────────────────────────────────────────────────────────────────
# Sudoku core (aggressive pruning, Decimal arithmetic)
# ─────────────────────────────────────────────────────────────────────────────

def coinjoin_sudoku(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal = Decimal(20),          # 3 000 sat tolerance
    maker_gain_max: Decimal = Decimal(2000000),   # maker earns ≤5 000 sat
) -> List[List[Dict[str, Any]]]:
    """Pruned JoinMarket Sudoku – **all values in Decimal satoshis**."""

    #―― constants —————————————————————————————
    to_sat = lambda v: (Decimal(str(v)) * SAT_MULT).quantize(SAT)

    #―― gather inputs / outputs in satoshi‐Decimal ——————————————
    def vin_value(vin):
        prev = tx_map[vin['txid']]['tx']
        return to_sat(next(o['value'] for o in prev['vout'] if o['n'] == vin['vout']))

    inputs  = [{'vin': v, 'value': vin_value(v)} for v in tx['vin']]
    outputs = [{'n': o['n'], 'value': to_sat(o['value'])} for o in tx['vout']]

    cj_val  = max({o['value'] for o in outputs}, key=lambda x: sum(1 for o in outputs if o['value'] == x))
    cj_outs = [o for o in outputs if o['value'] == cj_val]
    ch_outs = [o for o in outputs if o['value'] != cj_val]

    N = len(cj_outs)
    if N == 0 or len(ch_outs) not in {N, N - 1}:
        return []  # not a JoinMarket CJ

    miner_fee  = sum(i['value'] for i in inputs) - sum(o['value'] for o in outputs)
    target_sum = -miner_fee

    #―― canonical‑key for dedup ————————————————————————————
    def canonical_key(part_list):
        makers = []
        for p in part_list:
            inp_key = tuple(sorted(f"{i['vin']['txid']}:{i['vin']['vout']}" for i in p['inputs']))
            ch_idx  = p['change']['n'] if p['change'] else -1
            if p['role'] == 'maker':
                makers.append((inp_key, ch_idx))
            else:
                taker = (inp_key, ch_idx)
        makers.sort()
        return taker, tuple(makers)

    results, seen = [], set()

    inputs.sort(key=lambda i: i['value'], reverse=True)  # big first → prune

    taker_cj = cj_outs[0]
    maker_cj_outs = cj_outs[1:]
    taker_has_change = len(ch_outs) == N
    taker_change_candidates = ch_outs if taker_has_change else [None]
    prune_count = 0

    for t_ch in taker_change_candidates:
        maker_changes = sorted([c for c in ch_outs if c != t_ch], key=lambda o: o['n'])
        parts = (
            [{'role': 'maker', 'cj': cj, 'change': ch} for cj, ch in zip(maker_cj_outs, maker_changes)]
            + [{'role': 'taker', 'cj': taker_cj, 'change': t_ch}]
        )
        parts.sort(key=lambda p: p['cj']['value'] + (p['change']['value'] if p['change'] else Decimal(0)), reverse=True)

        max_taker_overspend = miner_fee + (N - 1) * maker_gain_max + fee_tol

        def dfs(idx: int, remaining: List[Dict[str, Any]], delta_sum: Decimal, taker_seen: bool):
            parts_left = len(parts) - idx

            makers_left = parts_left - (0 if taker_seen else 1)

            makers_left_max = (parts_left - (0 if taker_seen else 1)) * maker_gain_max

            # largest delta we could still reach
            nonlocal prune_count
            max_possible = (delta_sum
                            + makers_left * maker_gain_max
                            + (Decimal(0) if taker_seen else -SAT))  # taker overspends only 1 sat

            # smallest delta we could still reach
            min_possible = (delta_sum
                            - makers_left * SAT  # each maker loses 1 sat
                            - (Decimal(0) if taker_seen else max_taker_overspend))

            if max_possible < target_sum - fee_tol:
                prune_count += 1
                return
            if min_possible > target_sum + fee_tol:
                prune_count += 1
                return

            if idx == len(parts):
                if taker_seen and abs(delta_sum - target_sum) <= fee_tol:
                    key = canonical_key(parts)
                    if key not in seen:
                        seen.add(key)
                        results.append([dict(p) for p in parts])
                return

            part   = parts[idx]
            outsum = part['cj']['value'] + (part['change']['value'] if part['change'] else Decimal(0))
            min_left = len(parts) - idx - 1

            for r in range(1, len(remaining) - min_left + 1):
                prefix_sum = sum(remaining[i]['value'] for i in range(r))
                if part['role'] == 'maker':
                    # if prefix_sum > outsum + maker_gain_max:
                    #     break
                    # *Over*‑shoot is **not** definitive, because replacing one
                    # of those big inputs by a smaller one can bring the sum
                    # down into the window. So we just *do not* early‑break
                    # here any more.
                    if prefix_sum < outsum - maker_gain_max:
                        continue
                else:  # taker
                    if prefix_sum < outsum - max_taker_overspend:
                        continue
                    # compute minimum possible sum using the *smallest* r inputs;
                    # if even that overshoots, every future combo of size r will.
                    min_r_sum = sum([x['value'] for x in remaining[-r:]]) if r <= len(remaining) else prefix_sum
                    if min_r_sum > outsum + max_taker_overspend:
                        break

                for combo in combinations(remaining, r):
                    ins_sum = sum(i['value'] for i in combo)
                    delta   = outsum - ins_sum

                    # per‑participant legality
                    if part['role'] == 'maker':
                        if not (-SAT <= delta <= maker_gain_max):
                            continue
                    else:  # taker
                        if delta >= -SAT or delta < -max_taker_overspend:
                            continue

                    part['inputs'] = list(combo)
                    part['delta']  = delta
                    dfs(
                        idx + 1,
                        [i for i in remaining if i not in combo],
                        delta_sum + delta,
                        taker_seen or part['role'] == 'taker',
                    )
                    # clean up so the dict is pristine for the next combo
                    del part['inputs']
                    del part['delta']

        dfs(0, inputs, Decimal(0), False)

    print(f"PRUNE_COUNTER: {prune_count}")
    return results
