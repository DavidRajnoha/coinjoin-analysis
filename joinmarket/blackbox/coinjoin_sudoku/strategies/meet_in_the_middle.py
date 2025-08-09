from decimal import Decimal
from itertools import combinations
from typing import Any, Dict, List, Optional

def _solve_taker_sweep_global(
        inputs: List[Dict],
        cj_outs: List[Dict],
        ch_outs: List[Dict],
        cj_val: Decimal,
        miner_fee: Decimal,
        maker_gain_max: Decimal,
        fee_tol: Decimal
) -> Optional[List[List[Dict]]]:
    """
    Global optimization for taker sweep scenarios.
    Returns a solution in the same format as your existing code.
    """
    N = len(cj_outs)

    # Try each CJ output as potential taker
    for taker_idx, taker_cj in enumerate(cj_outs):
        maker_cj_outs = [cj for i, cj in enumerate(cj_outs) if i != taker_idx]

        # Generate multiple taker candidates instead of just one
        tgt_lo = cj_val + miner_fee - fee_tol
        tgt_hi = cj_val + miner_fee + (N - 1) * maker_gain_max + fee_tol

        # Get multiple candidates in this range
        candidates = _get_multiple_taker_candidates(inputs, tgt_lo, tgt_hi, max_count=5)

        for taker_subset in candidates:
            if taker_subset is None:
                continue

            taker_input_sum = sum(c['value'] for c in taker_subset)
            taker_delta = cj_val - taker_input_sum

            # Get remaining inputs for makers
            remaining_inputs = [
                inp for inp in inputs
                if not any(t_inp['vin']['txid'] == inp['vin']['txid'] and
                           t_inp['vin']['vout'] == inp['vin']['vout']
                           for t_inp in taker_subset)
            ]

            # Check if makers can be satisfied
            remaining_sum = sum(inp['value'] for inp in remaining_inputs)
            required_for_makers = sum(cj['value'] for cj in maker_cj_outs) + sum(ch['value'] for ch in ch_outs)
            available_for_maker_fees = remaining_sum - required_for_makers

            # Quick feasibility check
            if available_for_maker_fees < Decimal(0) or available_for_maker_fees > (N - 1) * maker_gain_max * 2:
                continue

            # Try to allocate inputs to makers
            maker_allocation = _allocate_to_makers_simple(
                remaining_inputs, maker_cj_outs, ch_outs, maker_gain_max
            )

            if maker_allocation:
                # Build the solution in your existing format
                taker_part = {
                    'role': 'taker',
                    'cj': taker_cj,
                    'change': None,
                    'inputs': taker_subset,
                    'delta': taker_delta,
                }

                solution = maker_allocation + [taker_part]
                return [solution]  # Return first valid solution

    return None


def _get_multiple_taker_candidates(inputs: List[Dict], lo: Decimal, hi: Decimal, max_count: int = 5) -> List[
    List[Dict]]:
    """Get multiple subset candidates using your existing meet-in-the-middle approach."""
    candidates = []

    # First try your existing single-solution approach
    single_result = _taker_sweep_mim(inputs, lo, hi)
    if single_result:
        candidates.append(single_result)

    # Then try some variations by adjusting the range slightly
    variations = [
        (lo * Decimal('0.99'), hi * Decimal('1.01')),
        (lo * Decimal('0.98'), hi * Decimal('1.02')),
        (lo * Decimal('1.01'), hi * Decimal('1.03')),
    ]

    for var_lo, var_hi in variations:
        if len(candidates) >= max_count:
            break
        result = _taker_sweep_mim(inputs, var_lo, var_hi)
        if result and result not in candidates:
            candidates.append(result)

    return candidates[:max_count]


def _allocate_to_makers_simple(
        remaining_inputs: List[Dict],
        maker_cj_outs: List[Dict],
        maker_changes: List[Dict],
        maker_gain_max: Decimal
) -> Optional[List[Dict]]:
    """
    Simple greedy allocation of inputs to makers.
    Returns list of maker dicts or None if impossible.
    """
    num_makers = len(maker_cj_outs)
    if len(maker_changes) != num_makers:
        return None

    # Calculate requirements for each maker
    requirements = []
    for i in range(num_makers):
        total_needed = maker_cj_outs[i]['value'] + maker_changes[i]['value']
        requirements.append((i, total_needed))

    # Sort by requirement (largest first)
    requirements.sort(key=lambda x: x[1], reverse=True)

    allocated_makers = []
    available = remaining_inputs[:]

    # Greedy allocation
    for maker_idx, requirement in requirements:
        best_allocation = None
        best_delta = None

        # Try 1-3 inputs for this maker
        for num_inputs in range(1, min(len(available) + 1, 4)):
            for combo in combinations(available, num_inputs):
                combo_sum = sum(inp['value'] for inp in combo)
                delta = requirement - combo_sum

                # Check if delta is reasonable for a maker
                if -Decimal(1) <= delta <= maker_gain_max:
                    if best_allocation is None or abs(delta) < abs(best_delta):
                        best_allocation = combo
                        best_delta = delta

        if best_allocation is None:
            return None  # Cannot satisfy this maker

        # Allocate these inputs to this maker
        maker_part = {
            'role': 'maker',
            'cj': maker_cj_outs[maker_idx],
            'change': maker_changes[maker_idx],
            'inputs': list(best_allocation),
            'delta': best_delta,
        }
        allocated_makers.append(maker_part)

        # Remove allocated inputs from available pool
        available = [inp for inp in available if inp not in best_allocation]

    return allocated_makers


# Updated meet-in-the-middle implementation (keeping your improvements)
def _taker_sweep_mim(inputs: list, lo: Decimal, hi: Decimal):
    """
    Updated version of your meet-in-the-middle implementation.
    This is kept for compatibility but the global approach above is preferred.
    """
    if not inputs:
        return None

    n = len(inputs)
    if n == 0:
        return None

    # Handle small cases directly
    if n <= 20:
        return _brute_force_subset(inputs, lo, hi)

    half = n // 2
    left, right = inputs[:half], inputs[half:]

    # Generate all subset sums for left half
    sums_L: list[tuple[Decimal, list]] = []
    for mask in range(1 << len(left)):
        s, subset = Decimal(0), []
        for i in range(len(left)):
            if mask & (1 << i):
                s += left[i]["value"]
                subset.append(left[i])
        sums_L.append((s, subset))

    # Sort by sum value
    sums_L.sort(key=lambda t: t[0])
    sums_only = [s for s, _ in sums_L]

    best_subset = None
    best_sum = None

    # Try all subsets of right half
    for mask in range(1 << len(right)):
        sR, subsetR = Decimal(0), []
        for i in range(len(right)):
            if mask & (1 << i):
                sR += right[i]["value"]
                subsetR.append(right[i])

        # What do we need from left half?
        lo_need = lo - sR
        hi_need = hi - sR

        # Find valid range in left sums
        from bisect import bisect_left, bisect_right
        left_idx = bisect_left(sums_only, lo_need)
        right_idx = bisect_right(sums_only, hi_need)

        # Check all valid combinations in this range
        for idx in range(left_idx, min(right_idx, len(sums_only))):
            total_sum = sR + sums_only[idx]
            if lo <= total_sum <= hi:
                candidate_subset = subsetR + sums_L[idx][1]
                if best_subset is None or total_sum < best_sum:
                    best_subset = candidate_subset
                    best_sum = total_sum

    return best_subset


def _brute_force_subset(inputs: list, lo: Decimal, hi: Decimal):
    """Brute force for small input sets"""
    best_subset = None
    best_sum = None

    for mask in range(1, 1 << len(inputs)):  # Start from 1 to skip empty set
        s, subset = Decimal(0), []
        for i in range(len(inputs)):
            if mask & (1 << i):
                s += inputs[i]["value"]
                subset.append(inputs[i])

        if lo <= s <= hi:
            if best_subset is None or s < best_sum:
                best_subset = subset
                best_sum = s

    return best_subset