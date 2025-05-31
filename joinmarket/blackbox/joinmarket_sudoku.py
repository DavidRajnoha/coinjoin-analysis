#!/usr/bin/env python3
"""
Blockchain Analyst Report Generator (initial version)

Loads and parses all block data from btc-node, with no knowledge of wallets or internal simulator data.
Ready for further analysis as instructed.
"""
from typing import Dict, Any
from collections import defaultdict
from typing import List, Tuple


from itertools import combinations

# Import the CoinJoin model
from joinmarket.common.coinjoin_model import CoinJoin, TxInput, TxOutput, CoinJoinParticipant

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BTC_NODE_DIR = "btc-node"
SAT = 1e-8  # 1 sat (float representation)
# ---------------------------------------------------------------------------
# CoinJoin Detection & CoinJoin Sudoku
# ---------------------------------------------------------------------------




def _build_participants(best_solution: list[dict], tx: dict) -> list[CoinJoinParticipant]:
    """Translate one sudoku solution into CoinJoinParticipant objects."""
    participants: list[CoinJoinParticipant] = []

    for part in best_solution:
        # ---- inputs --------------------------------------------------------
        inputs = [
            TxInput(
                txid=vin_info['vin']['txid'],
                vout=vin_info['vin']['vout'],
                value=vin_info['value'],
                address=None,                # black-box ⇒ we don’t know
            )
            for vin_info in part['inputs']
        ]

        # ---- outputs -------------------------------------------------------
        cj_out = part['cj']
        cj_output = TxOutput(
            n=cj_out['n'],
            value=cj_out['value'],
            address=tx['vout'][cj_out['n']].get('scriptPubKey', {}).get('address'),
            is_change=False,
        )

        change_output = None
        if part['change']:
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


def solve_joinmarket_sudoku(
    coinjoins: List[Tuple[str, dict, dict]],
    tx_map: dict,
):
    """
    Attempt a JoinMarket sudoku decomposition for each candidate CJ tx, but
    *always* return a CoinJoin object – even when no valid decomposition exists.
    """
    coinjoin_objects: list[CoinJoin] = []
    coinjoin_results: list[dict]      = []          # full raw solver output

    for txid, tx, block in coinjoins:
        solutions = coinjoin_sudoku(tx, tx_map)
        coinjoin_results.append({'txid': txid, 'solutions': solutions})

        # ── candidate CJ output amount ─────────────────────────────────────
        value_buckets: defaultdict[float, list] = defaultdict(list)
        for n, vout in enumerate(tx['vout']):
            value_buckets[vout['value']].append(n)
        cj_value = max(
            (v for v, idxs in value_buckets.items() if len(idxs) > 1),
            key=lambda v: len(value_buckets[v]),
            default=None,
        )

        # ── participants (only if we have at least one solution) ───────────
        participants = (
            _build_participants(solutions[0], tx) if solutions else []
        )

        coinjoin_objects.append(
            CoinJoin(
                txid=txid,
                block_height=block.get('height', 0),
                tx=tx,
                participants=participants,           # may be empty
                meta={
                    'blackbox_analysis': True,
                    'sudoku_solved': bool(solutions),
                    'candidate_cj_value': cj_value,
                    'input_count': len(tx['vin']),
                    'output_count': len(tx['vout']),
                },
            )
        )

    return coinjoin_objects, coinjoin_results




def coinjoin_sudoku( tx : Dict[str, Any],
                     tx_map: Dict[str, Dict[str, Any]],
                     fee_tol: float = 3 * SAT,
                     maker_gain_max: float = 50 * SAT
                     ) -> List[List[Dict[str, Any]]]:
    """
    All JoinMarket-compatible decompositions – *duplicates removed*.

    Makers: ≥1 inputs, 1 cj_out (value = cj_val), 1 change_out,  Δ ≥ 0.
    Taker : ≥1 inputs, 1 cj_out, 0/1 change_out,                 Δ < 0.
    ΣΔ  ≈  – miner_fee   (within `fee_tol`).

    Returns
    -------
    List[solution];  each solution is a list of participant dicts:
        { role  : 'maker' | 'taker',
          inputs: [ {vin, value}, … ],
          cj    : {n, value},
          change: {n, value} | None,
          delta : float  }              # outputs_sum − inputs_sum
    """

    # ------------------------------------------------ collect tx data
    def vin_value(vin):
        prev = tx_map[vin['txid']]['tx']
        return next(o['value'] for o in prev['vout'] if o['n'] == vin['vout'])

    inputs = [{'vin': v, 'value': vin_value(v)} for v in tx['vin']]
    outputs = [{'n': o['n'], 'value': o['value']} for o in tx['vout']]

    # modal output value  ==  coin-join denomination
    cj_val = max(set(o['value'] for o in outputs),
                 key=lambda x: sum(1 for o in outputs if o['value'] == x))
    cj_outs = [o for o in outputs if o['value'] == cj_val]
    ch_outs = [o for o in outputs if o['value'] != cj_val]

    n_participants = len(cj_outs)
    if n_participants == 0:  # not a CJ
        return []

    if len(ch_outs) not in (n_participants, n_participants - 1):
        return []  # JM shape mismatch

    miner_fee = sum(i['value'] for i in inputs) - sum(o['value'] for o in outputs)
    sols, seen_keys = [], set()  # <- dedup set

    # ------------------------------------------------ helper
    def canonical_key(part_list) -> Tuple:
        """collapse permutations of makers with identical (inputs,change)"""
        maker_keys = []
        for p in part_list:
            key = (tuple(sorted(f"{i['vin']['txid']}:{i['vin']['vout']}"
                                for i in p['inputs'])),
                   p['change']['n'] if p['change'] else -1)
            if p['role'] == 'maker':
                maker_keys.append(key)
            else:
                taker_key = key
        maker_keys.sort()
        return (taker_key, tuple(maker_keys))

    # ------------------------------------------------ recursive assignment
    def assign_inputs(idx: int,
                      parts: List[Dict[str, Any]],
                      remaining: List[Dict[str, Any]]):
        if idx == len(parts):  # base case
            total_delta = sum(p['delta'] for p in parts)
            if abs(total_delta + miner_fee) <= fee_tol:
                key = canonical_key(parts)
                if key not in seen_keys:  # dedup!
                    seen_keys.add(key)
                    sols.append([dict(p) for p in parts])
            return

        part = parts[idx]
        outsum = cj_val + (part['change']['value'] if part['change'] else 0)

        min_left = len(parts) - idx - 1  # reserve ≥1 input each
        for r in range(1, len(remaining) - min_left + 1):
            for combo in combinations(remaining, r):
                ins_sum = sum(i['value'] for i in combo)
                delta = outsum - ins_sum

                if part['role'] == 'maker':
                    if delta < -SAT or delta > maker_gain_max:  # maker can't lose
                        continue
                else:  # taker
                    if delta >= -SAT:
                        continue

                part['inputs'] = list(combo)
                part['delta'] = delta
                assign_inputs(idx + 1,
                              parts,
                              [i for i in remaining if i not in combo])

    # ------------------------------------------------ main enumeration
    taker_has_change = (len(ch_outs) == n_participants)

    for taker_cj_idx in range(n_participants):

        maker_cj_outs = [cj for i, cj in enumerate(cj_outs) if i != taker_cj_idx]

        if taker_has_change:
            # choose which change output is taker's; makers get the rest (orderless)
            for t_ch in ch_outs:
                m_ch = [c for c in ch_outs if c is not t_ch]
                # sort to canonical order
                m_ch_sorted = sorted(m_ch, key=lambda o: o['n'])
                parts = ([{'role': 'maker', 'cj': cj, 'change': ch}
                          for cj, ch in zip(maker_cj_outs, m_ch_sorted)] +
                         [{'role': 'taker', 'cj': cj_outs[taker_cj_idx], 'change': t_ch}])
                assign_inputs(0, parts, inputs)

        else:  # taker sweep: makers consume *all* change outs
            m_ch_sorted = sorted(ch_outs, key=lambda o: o['n'])
            parts = ([{'role': 'maker', 'cj': cj, 'change': ch}
                      for cj, ch in zip(maker_cj_outs, m_ch_sorted)] +
                     [{'role': 'taker', 'cj': cj_outs[taker_cj_idx], 'change': None}])
            assign_inputs(0, parts, inputs)

    return sols
