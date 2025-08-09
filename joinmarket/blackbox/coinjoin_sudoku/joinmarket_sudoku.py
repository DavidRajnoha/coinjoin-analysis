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

import time
from decimal import Decimal, getcontext
from typing import Any, Dict, List, Tuple

import numpy as np

from joinmarket.blackbox.coinjoin_sudoku.strategies.dfs_matrix_sudoku import MatrixSudokuDFSContext
from joinmarket.blackbox.coinjoin_sudoku.utils.build_participants import _build_participants
from joinmarket.blackbox.coinjoin_sudoku.strategies.dfs_pruned import SudokuDFSContext
from joinmarket.blackbox.coinjoin_sudoku.strategies.meet_in_the_middle import _solve_taker_sweep_global
from joinmarket.blackbox.coinjoin_sudoku.utils.decomposition_helpers import prepare_inputs_outputs, classify_outputs, \
    is_valid_cj_structure, calculate_miner_fee, calculate_target_sum, build_parts, canonical_key

import os

# ─────────────────────────────────────────────────────────────────────────────
# Decimal / denomination setup
# ─────────────────────────────────────────────────────────────────────────────
getcontext().prec = 30                        # plenty for 64‑bit ints
SAT_MULT = Decimal('100000000')               # BTC → satoshi
SAT      = Decimal('1')                       # one satoshi (after ×100 M)

MAX_INPUTS_SWEEP = 25
MAX_OUTPUTS_SWEEP = 30

MAX_INPUTS_NON_SWEEP = 25
MAX_OUTPUTS_NON_SWEEP = 20


SUBSET_INDICATORS_CACHE = {}

# ─────────────────────────────────────────────────────────────────────────────
# External dataclasses  (import paths unchanged)
# ─────────────────────────────────────────────────────────────────────────────
from joinmarket.common.coinjoin_model import (
    CoinJoin
)

# ─────────────────────────────────────────────────────────────────────────────
# Orchestration: analyze_and_solve_sudoku_for_tx (single tx)
# ─────────────────────────────────────────────────────────────────────────────

def analyze_and_solve_sudoku_for_tx(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal = Decimal(20),
    maker_gain_max: Decimal = Decimal(500000),
) -> List[List[Dict[str, Any]]]:
    """
    Analyze and solve input/output assignment (Sudoku) for a single CoinJoin transaction.
    Handles both sweep and non-sweep (change) cases symmetrically.
    Returns all valid input/output assignments.
    """
    inputs, outputs = prepare_inputs_outputs(tx, tx_map)
    cj_val, cj_outs, ch_outs = classify_outputs(outputs)
    if not is_valid_cj_structure(cj_outs, ch_outs):
        return []
    N = len(cj_outs)
    miner_fee = calculate_miner_fee(inputs, outputs)
    target_sum = calculate_target_sum(miner_fee)

    return sudoku_matrix_multiplication(
        inputs, cj_outs, ch_outs, N, miner_fee, maker_gain_max, fee_tol, target_sum
    )

    # Check input/output limits
    if len(ch_outs) != N:
        if len(inputs) < MAX_INPUTS_NON_SWEEP and len(outputs) < MAX_OUTPUTS_NON_SWEEP:
            return sudoku_dfs_assignment(
                inputs, cj_outs, ch_outs, N, miner_fee, maker_gain_max, fee_tol, target_sum
            )
        elif len(inputs) > MAX_INPUTS_SWEEP or len(outputs) > MAX_OUTPUTS_SWEEP:
            return []
        return sudoku_taker_sweep(
            inputs, cj_outs, ch_outs, cj_val, miner_fee, maker_gain_max, fee_tol
        )
    else:
        if len(inputs) > MAX_INPUTS_NON_SWEEP or len(outputs) > MAX_OUTPUTS_NON_SWEEP:
            return []
        return sudoku_dfs_assignment(
            inputs, cj_outs, ch_outs, N, miner_fee, maker_gain_max, fee_tol, target_sum
        )

# ─────────────────────────────────────────────────────────────────────────────
# Batch driver: solve_sudoku_for_coinjoin_set
# ─────────────────────────────────────────────────────────────────────────────

def solve_sudoku_for_coinjoin_set(
    coinjoins: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
    tx_map: Dict[str, Dict[str, Any]],
) -> Tuple[List[CoinJoin], List[Dict[str, Any]]]:
    """
    Run Sudoku assignment for all CoinJoin candidates in the set.
    Returns (coinjoin_objects, coinjoin_results).
    """
    coinjoin_results: List[Dict[str, Any]] = []
    coinjoin_objects: List[CoinJoin] = []

    for txid, tx, block in coinjoins:
        try:
            if len(tx['vin']) > MAX_INPUTS_SWEEP or len(tx['vout']) > MAX_OUTPUTS_SWEEP:
                print(f'solve_sudoku_for_coinjoin_set: skipping {txid} (too big)')
                solutions = None
            else:
                print(f'solve_sudoku_for_coinjoin_set: solving {txid}')
                solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map)
                coinjoin_results.append({'txid': txid, 'solutions': solutions})
        except KeyboardInterrupt as e:
            solutions = None
            print(f'solve_sudoku_for_coinjoin_set: skipping {txid} (interrupted)')


        # —— modal CJ value (works on BTC values in raw tx) ————————
        if solutions:
            best_solution = solutions[0]
            cj_value = max(set(o['cj']['value'] for o in best_solution), key=lambda x: sum(1 for o in best_solution if o['cj']['value'] == x))
            participants = _build_participants(best_solution, tx, cj_value) if solutions else []
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
# Sudoku taker sweep solver
# ─────────────────────────────────────────────────────────────────────────────

def sudoku_taker_sweep(
    inputs, cj_outs, ch_outs, cj_val, miner_fee, maker_gain_max, fee_tol
) -> List[List[Dict[str, Any]]]:
    """
    Handles the taker sweep case (no change for taker) via the global optimization path.
    """
    sweep_solution = _solve_taker_sweep_global(
        inputs, cj_outs, ch_outs, cj_val, miner_fee, maker_gain_max, fee_tol
    )
    return sweep_solution if sweep_solution else []

# ─────────────────────────────────────────────────────────────────────────────
# Sudoku DFS assignment solver
# ─────────────────────────────────────────────────────────────────────────────

def sudoku_dfs_assignment(
    inputs, cj_outs, ch_outs, N, miner_fee, maker_gain_max, fee_tol, target_sum
) -> List[List[Dict[str, Any]]]:
    """
    Handles the non-sweep (taker has change) case via DFS/backtracking.
    """
    taker_cj = cj_outs[0]
    maker_cj_outs = cj_outs[1:]
    taker_change_candidates = ch_outs if len(ch_outs) == N else [None]
    results = []
    for t_ch in taker_change_candidates:
        maker_changes = sorted([c for c in ch_outs if c != t_ch], key=lambda o: o['n'])
        parts = build_parts(maker_cj_outs, maker_changes, taker_cj, t_ch)
        ctx = SudokuDFSContext(parts, inputs, N, miner_fee, maker_gain_max, fee_tol, target_sum, canonical_key)
        results.extend(ctx.run())
    return results


def generate_subset_indicators(num_inputs, cache_dir="subset_cache"):
    # Check in-memory cache first
    if num_inputs in SUBSET_INDICATORS_CACHE:
        print('using cached subset indicators (memory)')
        return SUBSET_INDICATORS_CACHE[num_inputs]

    # Create cache directory if it doesn't exist
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"subset_indicators_{num_inputs}.npy")

    # Try to load from disk
    if os.path.exists(cache_file):
        print(f'loading subset indicators from disk: {cache_file}')
        subset_matrix = np.load(cache_file)
        SUBSET_INDICATORS_CACHE[num_inputs] = subset_matrix
        return subset_matrix

    # Generate if not cached
    print(f'generating subset indicators for {num_inputs} inputs')
    num_subsets = 2 ** num_inputs

    # Create arrays for broadcasting
    i_vals = np.arange(num_subsets, dtype=np.uint32)[:, np.newaxis]  # Shape: (num_subsets, 1)
    j_vals = np.arange(num_inputs, dtype=np.uint8)[np.newaxis, :]  # Shape: (1, num_inputs)

    # Generate all combinations at once using broadcasting
    subset_matrix = ((i_vals >> j_vals) & 1).astype(np.uint8)

    # Cache to memory and disk
    SUBSET_INDICATORS_CACHE[num_inputs] = subset_matrix
    np.save(cache_file, subset_matrix)
    print(f'saved subset indicators to disk: {cache_file}')

    return subset_matrix

def broad_filter(all_subset_sums, cj_outs, ch_outs, N, maker_gain_max):
    min_change = min(int(ch['value']) for ch in ch_outs)
    max_change = max(int(ch['value']) for ch in ch_outs)
    cj_value = max(int(o['value']) for o in cj_outs)

    lower_bound = cj_value + min_change - int(maker_gain_max) * (N - 1)
    upper_bound = cj_value + max_change + int(maker_gain_max)

    valid_mask = (all_subset_sums >= lower_bound) & (all_subset_sums <= upper_bound)
    valid_indices = np.where(valid_mask)[0]
    valid_sums = all_subset_sums[valid_mask]

    return valid_indices, valid_sums

def build_compatibility_matrix(valid_indices,
                               valid_sums,
                               valid_subset_indicators,
                               change_outputs,
                               cj_outs,
                               fee_tol,
                               maker_gain_max,):
    cj_value = max(int(o['value']) for o in cj_outs)
    maker_gain_max_int = int(maker_gain_max)
    change_outputs = [int(ch['value']) for ch in change_outputs]
    num_makers = len(cj_outs) - 1

    compatibility = {}
    compatibility_taker = {}

    for i, subset_idx in enumerate(valid_indices):
        compatible_changes = []
        compatible_changes_taker = []
        subset_sum = valid_sums[i]
        subset_inputs = valid_subset_indicators[i]  # This is the binary pattern showing which inputs are included

        for j, change_output in enumerate(change_outputs):
            diff = cj_value + change_output - subset_sum

            if maker_gain_max_int >= diff >= 0:
                compatible_changes.append(j)

            if 0 >= diff >= - maker_gain_max_int * num_makers:
                compatible_changes_taker.append(j)

        compatibility[subset_idx] = {
            'compatible_changes': compatible_changes,
            'input_composition': subset_inputs,  # Binary array showing which inputs are included
            'subset_sum': subset_sum
        }

        compatibility_taker[subset_idx] = {
            'compatible_changes': compatible_changes_taker,
            'input_composition': subset_inputs,  # Binary array showing which inputs are included
            'subset_sum': subset_sum
        }

    return compatibility, compatibility_taker


def subsets_overlap(subset_idx_a, subset_idx_b):
    """
    Check if two subsets (represented by their binary indices) overlap.
    Returns True if they share any common inputs.
    """
    return (subset_idx_a & subset_idx_b) != 0


def find_valid_assignments(compatibility, compatibility_taker, ch_outs, cj_outs, maker_gain_max, fee_tol, miner_fee, subset_indicators):

    context = MatrixSudokuDFSContext(
        compatibility=compatibility,
        change_outputs=ch_outs,
        cj_outs=cj_outs,
        maker_gain_max=maker_gain_max,
        fee_tol=fee_tol,
        miner_fee=miner_fee,
        subset_indicators=subset_indicators,
        compatibility_taker=compatibility_taker
    )
    # Run the search
    assignment_solutions = context.run()
    print(f"Pruned {context.prune_count} invalid branches")
    return assignment_solutions


def filter_by_input_count(valid_indices, valid_sums, valid_subset_indicators, inputs, cj_outs):
    max_input_per_subset = len(inputs) - len(cj_outs) + 1

    # Create boolean mask for rows to keep
    keep_mask = np.array([np.count_nonzero(row) <= max_input_per_subset
                          for row in valid_subset_indicators])

    num_valid = np.sum(keep_mask)
    print(f"Pruned {len(keep_mask) - num_valid} invalid subsets by input count")

    # Apply mask to filter all arrays
    valid_indices = valid_indices[keep_mask]
    valid_sums = valid_sums[keep_mask]
    valid_subset_indicators = valid_subset_indicators[keep_mask]

    return valid_indices, valid_sums, valid_subset_indicators


def sudoku_matrix_multiplication(inputs, cj_outs, ch_outs, N, miner_fee, maker_gain_max, fee_tol, target_sum):
    input_values = np.array([int(i['value']) for i in inputs], dtype=np.int64)
    if len(input_values) > 28:
        print(f"Too many inputs: {len(input_values)}")
        return []

    start = time.time()
    subset_indicators = generate_subset_indicators(len(inputs))
    end = time.time()
    print(f"Subset indicators took {end - start} seconds")

    start = time.time()
    all_subsets = subset_indicators @ input_values
    end = time.time()
    print(f"Subset multiplication took {end - start} seconds")


    valid_indices, valid_sums = broad_filter(all_subsets, cj_outs, ch_outs, N, maker_gain_max)
    valid_subset_indicators = subset_indicators[valid_indices]

    valid_indices, valid_sums, valid_subset_indicators = filter_by_input_count(
        valid_indices, valid_sums, valid_subset_indicators, inputs, cj_outs)

    compatibility, compatibility_taker = build_compatibility_matrix(
        valid_indices, valid_sums, valid_subset_indicators,
        ch_outs, cj_outs, fee_tol, maker_gain_max
    )

    valid_assignments = find_valid_assignments(compatibility,
                                               compatibility_taker,
                                               ch_outs,
                                               cj_outs,
                                               maker_gain_max,
                                               fee_tol,
                                               miner_fee,
                                               subset_indicators)

    results = reconstruct_sudoku_solutions(valid_assignments,
                                           inputs,
                                           cj_outs,
                                           ch_outs,
                                           subset_indicators,
                                           valid_indices,
                                           cj_outs[0]['value'],
                                           miner_fee)

    return results


def reconstruct_sudoku_solutions(solutions, inputs, cj_outs, ch_outs, subset_indicators, valid_indices, cj_value, miner_fee):
    """
    Convert the assignment solutions back to the original rich object format.

    This function bridges between our efficient matrix representation and
    the detailed participant objects that the rest of the system expects.
    """
    reconstruct_sudoku_solutions = []


    for solution in solutions:
        assigned_input_indices = set()
        participants = []
        for subset_idx, change_idx in solution.items():

            input_pattern = subset_indicators[subset_idx]

            # Extract the actual input objects for this subset
            subset_inputs = []
            for input_index, is_included in enumerate(input_pattern):
                if is_included:
                    subset_inputs.append(inputs[input_index])
                    assigned_input_indices.add(input_index)

            # Get the corresponding change output
            change_output = ch_outs[change_idx]

            # Calculate the delta (difference from expected coinjoin amount)
            total_input_value = sum(int(inp['value']) for inp in subset_inputs)
            expected_output_value = int(cj_value) + int(change_output['value'])
            delta = expected_output_value - total_input_value

            # Determine role based on delta sign
            role = 'maker' if delta >= 0 else 'taker'

            participant = {
                'inputs': subset_inputs,
                'change': change_output,
                'cj': {'n': cj_outs[0]['n'], 'value': cj_value},  # Standard coinjoin output
                'delta': Decimal(str(delta)),
                'role': role
            }

            participants.append(participant)

        # Handle any remaining unassigned inputs (these might form the taker's input set)
        unassigned_inputs = []
        for input_idx, input_obj in enumerate(inputs):
            if input_idx not in assigned_input_indices:
                unassigned_inputs.append(input_obj)

        # If there are unassigned inputs, they likely belong to a taker with no change
        if unassigned_inputs:
            total_input_value = sum(int(inp['value']) for inp in unassigned_inputs)
            delta = int(cj_value) - total_input_value  # No change output for taker

            taker_participant = {
                'inputs': unassigned_inputs,
                'change': None,  # Taker sweep case
                'cj': {'n': cj_outs[0]['n'], 'value': cj_value},
                'delta': Decimal(str(delta)),
                'role': 'taker'  # This will likely be negative delta
            }

            participants.append(taker_participant)

        # Now validate the role distribution
        taker_count = sum(1 for p in participants if p['role'] == 'taker')

        delta_sum = sum(p['delta'] for p in participants)

        if abs(delta_sum) > miner_fee:
            continue

        # Only accept solutions with exactly one taker
        if taker_count == 1:
            reconstruct_sudoku_solutions.append(participants)
        # If we have zero takers or multiple takers, this assignment is invalid

    print("Found {} valid assignments".format(len(reconstruct_sudoku_solutions)))

    min_taker_fee_solutions = [max([(min([x['delta'] for x in n]), n) for n in reconstruct_sudoku_solutions], key=lambda x: x[0])[1]] if len(reconstruct_sudoku_solutions) > 0 else []

    return min_taker_fee_solutions