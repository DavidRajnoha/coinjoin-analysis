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
from joinmarket.blackbox.coinjoin_sudoku.sudoku_statistics import SudokuStatisticsCollector, SudokuSolveStatistics

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
from joinmarket.common.analysis_config import AnalysisConfig, DEFAULT_CONFIG
from joinmarket.common.coinjoin_model import (
    CoinJoin, relabel_roles
)

# ─────────────────────────────────────────────────────────────────────────────
# Orchestration: analyze_and_solve_sudoku_for_tx (single tx)
# ─────────────────────────────────────────────────────────────────────────────

def analyze_and_solve_sudoku_for_tx(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal = Decimal(20),
    maker_gain_max: Decimal = Decimal(600000),
) -> List[List[Dict[str, Any]]]:
    """
    Analyze and solve input/output assignment (Sudoku) for a single CoinJoin transaction.
    Handles both sweep and non-sweep (change) cases symmetrically.
    Returns all valid input/output assignments.
    """
    inputs, outputs = prepare_inputs_outputs(tx, tx_map)
    cj_val, cj_outs, ch_outs = classify_outputs(outputs)
    if not is_valid_cj_structure(cj_outs, ch_outs):
        print(
            "No blackbox attribution: invalid CJ structure "
            f"(cj_outs={len(cj_outs)}, ch_outs={len(ch_outs)}, "
            f"inputs={len(inputs)}, outputs={len(outputs)})"
        )
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
# Binary search wrapper for optimal maker_gain_max
# ─────────────────────────────────────────────────────────────────────────────

def analyze_and_solve_sudoku_with_optimal_gain(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal = Decimal(20),
    lower_bound: Decimal = Decimal(10000),
    upper_bound: Decimal = Decimal(600000),
    initial_guess: Decimal = Decimal(50000),
    max_iterations: int = None,
    search_strategy: str = "start_middle",
) -> List[List[Dict[str, Any]]]:
    """
    Wrapper around analyze_and_solve_sudoku_for_tx that uses binary search
    to find the optimal (smallest) maker_gain_max value that returns solutions.

    Args:
        tx: Transaction to analyze
        tx_map: Map of all transactions
        fee_tol: Fee tolerance
        lower_bound: Minimum maker_gain_max to try (default: 10000 sat)
        upper_bound: Maximum maker_gain_max to try (default: 600000 sat)
        initial_guess: Starting point for search (default: 50000 sat)
        max_iterations: Maximum number of iterations (default: None = unlimited)
        search_strategy: Search strategy to use:
            - "start_middle": Start at initial_guess, search up/down (original approach, 85% success)
            - "start_high": Start at upper_bound, only search down
            - "start_high_always_search": Start at upper_bound, search down even if fails (binary search)
            - "aggressive_downscale": Aggressive downscale steps (512k→128k→32k→8k), then binary search

    Returns:
        List of solutions found with the optimal maker_gain_max, or empty list
    """
    if search_strategy == "start_middle":
        return _search_start_middle(tx, tx_map, fee_tol, lower_bound, upper_bound, initial_guess, max_iterations)
    elif search_strategy == "start_high":
        return _search_start_high(tx, tx_map, fee_tol, lower_bound, upper_bound, max_iterations)
    elif search_strategy == "start_high_always_search":
        return _search_start_high_always(tx, tx_map, fee_tol, lower_bound, upper_bound, max_iterations)
    elif search_strategy == "aggressive_downscale":
        return _search_aggressive_downscale(tx, tx_map, fee_tol, lower_bound, upper_bound, max_iterations)
    else:
        raise ValueError(f"Unknown search_strategy: {search_strategy}")


def _search_start_middle(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
    initial_guess: Decimal,
    max_iterations: int,
) -> List[List[Dict[str, Any]]]:
    """
    Original strategy: Start at middle value (50k), search both up and down.
    This was the FIRST implementation that achieved 85% taker match.
    """
    print(f"[Strategy: start_middle] Trying initial maker_gain_max={initial_guess}")
    solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, initial_guess)
    iteration_count = 1

    if solutions:
        # We found solutions at initial_guess, search for smaller value
        best_maker_gain_max = initial_guess
        best_solutions = solutions
        high = initial_guess
        low = lower_bound

        print(f"Found solutions at {initial_guess}, searching for smaller maker_gain_max...")

        while low < high:
            # Check max iterations limit
            if max_iterations and iteration_count >= max_iterations:
                print(f"Reached max_iterations limit ({max_iterations}), returning best solution found")
                return best_solutions

            mid = low + (high - low) // 2

            print(f"Binary search iteration {iteration_count + 1}: trying maker_gain_max={mid} (range: {low}-{high})")
            solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, mid)
            iteration_count += 1

            if solutions:
                best_maker_gain_max = mid
                best_solutions = solutions
                high = mid
            else:
                low = mid + 1

        print(f"Optimal maker_gain_max found: {best_maker_gain_max} (total iterations: {iteration_count})")
        return best_solutions
    else:
        # No solutions at initial_guess, search for larger value
        low = initial_guess
        high = upper_bound

        print(f"No solutions at {initial_guess}, searching for larger maker_gain_max...")

        best_maker_gain_max = None
        best_solutions = []

        while low < high:
            # Check max iterations limit
            if max_iterations and iteration_count >= max_iterations:
                print(f"Reached max_iterations limit ({max_iterations})")
                if best_solutions:
                    print(f"Returning best solution found at maker_gain_max={best_maker_gain_max}")
                    return best_solutions
                else:
                    print(f"No solutions found within {max_iterations} iterations")
                    return []

            mid = low + (high - low) // 2

            print(f"Binary search iteration {iteration_count + 1}: trying maker_gain_max={mid} (range: {low}-{high})")
            solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, mid)
            iteration_count += 1

            if solutions:
                best_maker_gain_max = mid
                best_solutions = solutions
                high = mid
            else:
                low = mid + 1

        # Final check at the boundary
        if not (max_iterations and iteration_count >= max_iterations) and low <= upper_bound:
            print(f"Final check (iteration {iteration_count + 1}): trying maker_gain_max={low}")
            solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, low)
            iteration_count += 1
            if solutions:
                print(f"Optimal maker_gain_max found: {low} (total iterations: {iteration_count})")
                return solutions

        if best_solutions:
            print(f"Optimal maker_gain_max found: {best_maker_gain_max} (total iterations: {iteration_count})")
            return best_solutions

        print(f"No solutions found in range [{lower_bound}, {upper_bound}] (total iterations: {iteration_count})")
        return []


def _search_start_high(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
    max_iterations: int,
) -> List[List[Dict[str, Any]]]:
    """
    Second strategy: Start at high value (600k), only search down.
    Stop immediately if no solution at 600k (don't search lower).
    """
    print(f"[Strategy: start_high] Trying initial maker_gain_max={upper_bound}")
    solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, upper_bound)
    iteration_count = 1

    if not solutions:
        print(f"No solutions found at {upper_bound}, stopping search (higher values won't help)")
        return []

    # Found solutions at upper_bound, now search downward for minimum
    best_maker_gain_max = upper_bound
    best_solutions = solutions
    high = upper_bound
    low = lower_bound

    print(f"Found solutions at {upper_bound}, searching for smaller maker_gain_max...")

    while low < high:
        if max_iterations and iteration_count >= max_iterations:
            print(f"Reached max_iterations limit ({max_iterations}), returning best solution found")
            return best_solutions

        mid = low + (high - low) // 2

        print(f"Binary search iteration {iteration_count + 1}: trying maker_gain_max={mid} (range: {low}-{high})")
        solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, mid)
        iteration_count += 1

        if solutions:
            best_maker_gain_max = mid
            best_solutions = solutions
            high = mid
        else:
            low = mid + 1

    print(f"Optimal maker_gain_max found: {best_maker_gain_max} (total iterations: {iteration_count})")
    return best_solutions


def _search_start_high_always(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
    max_iterations: int,
) -> List[List[Dict[str, Any]]]:
    """
    Third strategy: Start at high value (600k), always search down.
    Even if no solution at 600k, search lower (fewer branches may help).
    """
    print(f"[Strategy: start_high_always_search] Trying initial maker_gain_max={upper_bound}")
    solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, upper_bound)
    iteration_count = 1

    # Initialize search range - always search downward
    best_maker_gain_max = upper_bound if solutions else None
    best_solutions = solutions if solutions else []
    high = upper_bound
    low = lower_bound

    if solutions:
        print(f"Found solutions at {upper_bound}, searching for smaller maker_gain_max...")
    else:
        print(f"No solutions found at {upper_bound}, but searching lower values (fewer branches may help)...")

    while low < high:
        if max_iterations and iteration_count >= max_iterations:
            print(f"Reached max_iterations limit ({max_iterations}), returning best solution found")
            return best_solutions

        mid = low + (high - low) // 2

        print(f"Binary search iteration {iteration_count + 1}: trying maker_gain_max={mid} (range: {low}-{high})")
        solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, mid)
        iteration_count += 1

        if solutions:
            best_maker_gain_max = mid
            best_solutions = solutions
            high = mid
        else:
            low = mid + 1

    if best_maker_gain_max is not None:
        print(f"Optimal maker_gain_max found: {best_maker_gain_max} (total iterations: {iteration_count})")
    else:
        print(f"No solutions found in range [{lower_bound}, {upper_bound}] (total iterations: {iteration_count})")
    return best_solutions


def _search_aggressive_downscale(
    tx: Dict[str, Any],
    tx_map: Dict[str, Dict[str, Any]],
    fee_tol: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
    max_iterations: int,
    downscale_ratio: Decimal = Decimal('0.25'),
) -> List[List[Dict[str, Any]]]:
    """
    Fourth strategy: Aggressive downscaling when no solution found.

    Uses predetermined steps to aggressively search down when no solution is found.
    Default: 512k -> 128k -> 32k -> 8k (ratio = 0.25)
    Alternative hardcoded: 600k -> 150k -> 50k -> 20k -> 10k

    When a solution is found, performs binary search downward to find minimum.

    Args:
        downscale_ratio: Ratio for aggressive downscaling (default: 0.25 for 1/4 steps)
    """
    # Generate downscale steps using the ratio
    # Start at a power of 2 close to upper_bound for nice round numbers
    if downscale_ratio == Decimal('0.25'):
        # Use 512k as starting point for nice round numbers with 1/4 ratio
        current = Decimal('512000')
    else:
        current = upper_bound

    downscale_steps = []
    while current >= lower_bound:
        downscale_steps.append(current)
        current = (current * downscale_ratio).quantize(Decimal('1'))

    # Ensure lower_bound is included
    if downscale_steps[-1] > lower_bound:
        downscale_steps.append(lower_bound)

    print(f"[Strategy: aggressive_downscale] Downscale steps: {[int(s) for s in downscale_steps]}")

    best_maker_gain_max = None
    best_solutions = []
    iteration_count = 0

    # Try each downscale step
    for step_value in downscale_steps:
        if max_iterations and iteration_count >= max_iterations:
            print(f"Reached max_iterations limit ({max_iterations}), returning best solution found")
            break

        print(f"Aggressive downscale iteration {iteration_count + 1}: trying maker_gain_max={step_value}")
        solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, step_value)
        iteration_count += 1

        if solutions:
            # Found a solution! Now do binary search downward to find minimum
            print(f"Found solutions at {step_value}, performing binary search to find minimum...")
            best_maker_gain_max = step_value
            best_solutions = solutions

            # Binary search between lower_bound and current step_value
            low = lower_bound
            high = step_value

            while low < high:
                if max_iterations and iteration_count >= max_iterations:
                    print(f"Reached max_iterations limit ({max_iterations}), returning best solution found")
                    break

                mid = low + (high - low) // 2

                print(f"Binary search iteration {iteration_count + 1}: trying maker_gain_max={mid} (range: {low}-{high})")
                solutions = analyze_and_solve_sudoku_for_tx(tx, tx_map, fee_tol, mid)
                iteration_count += 1

                if solutions:
                    best_maker_gain_max = mid
                    best_solutions = solutions
                    high = mid
                else:
                    low = mid + 1

            print(f"Optimal maker_gain_max found: {best_maker_gain_max} (total iterations: {iteration_count})")
            return best_solutions

    # No solution found at any step
    if best_maker_gain_max is not None:
        print(f"Optimal maker_gain_max found: {best_maker_gain_max} (total iterations: {iteration_count})")
    else:
        print(f"No solutions found in downscale steps (total iterations: {iteration_count})")
    return best_solutions

# ─────────────────────────────────────────────────────────────────────────────
# Batch driver: solve_sudoku_for_coinjoin_set
# ─────────────────────────────────────────────────────────────────────────────

def solve_sudoku_for_coinjoin_set(
    coinjoins: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
    tx_map: Dict[str, Dict[str, Any]],
    search_strategy: str = "start_high_always_search",
    max_iterations: int = 5,
    statistics_collector: Optional[SudokuStatisticsCollector] = None,
    config: AnalysisConfig = DEFAULT_CONFIG,
) -> Tuple[List[CoinJoin], List[Dict[str, Any]]]:
    """
    Run Sudoku assignment for all CoinJoin candidates in the set.
    Returns (coinjoin_objects, coinjoin_results).

    Args:
        coinjoins: List of (txid, tx, block) tuples
        tx_map: Map of all transactions
        search_strategy: Search strategy for binary search:
            - "start_middle": Start at 50k, search up/down (original, achieved 85% taker match)
            - "start_high": Start at 600k, only search down
            - "start_high_always_search": Start at 600k, search down even if fails (binary search)
            - "aggressive_downscale": Aggressive downscale steps (512k→128k→32k→8k), then binary search
        max_iterations: Maximum iterations for binary search
        statistics_collector: Optional statistics collector for performance analysis
        config: Analysis switches (see AnalysisConfig)
    """
    coinjoin_results: List[Dict[str, Any]] = []
    coinjoin_objects: List[CoinJoin] = []

    for txid, tx, block in coinjoins:
        solutions = None
        failure_reason = None
        skipped = False
        stats = None

        try:
            # Prepare inputs/outputs for statistics tracking
            inputs, outputs = prepare_inputs_outputs(tx, tx_map)
            cj_val, cj_outs, ch_outs = classify_outputs(outputs)

            # Start statistics tracking
            if statistics_collector and statistics_collector.enabled:
                stats = statistics_collector.start_transaction(txid, tx, cj_outs, ch_outs)
                if stats:
                    stats.strategy = "matrix_multiplication"  # Default strategy
                    stats.search_strategy = search_strategy

            if len(tx['vin']) > MAX_INPUTS_SWEEP or len(tx['vout']) > MAX_OUTPUTS_SWEEP:
                print(f'solve_sudoku_for_coinjoin_set: skipping {txid} (too big)')
                failure_reason = f"Too large (inputs={len(tx['vin'])}, outputs={len(tx['vout'])}, max={MAX_INPUTS_SWEEP}/{MAX_OUTPUTS_SWEEP})"
                skipped = True
                solutions = None
            else:
                print(f'solve_sudoku_for_coinjoin_set: solving {txid}')
                solutions = analyze_and_solve_sudoku_with_optimal_gain(
                    tx, tx_map,
                    max_iterations=max_iterations,
                    search_strategy=search_strategy
                )
                coinjoin_results.append({'txid': txid, 'solutions': solutions})
                if not solutions:
                    failure_reason = f"No solution found (inputs={len(tx.get('vin', []))}, outputs={len(tx.get('vout', []))})"
                    print(
                        f'solve_sudoku_for_coinjoin_set: no blackbox solutions for {txid} '
                        f'(vin={len(tx.get("vin", []))}, vout={len(tx.get("vout", []))})'
                    )
        except KeyboardInterrupt as e:
            solutions = None
            failure_reason = "Interrupted by user"
            skipped = True
            print(f'solve_sudoku_for_coinjoin_set: skipping {txid} (interrupted)')
        except Exception as e:
            solutions = None
            failure_reason = f"Error: {str(e)}"
            print(f'solve_sudoku_for_coinjoin_set: error solving {txid}: {e}')
        finally:
            # Complete statistics tracking
            if statistics_collector and statistics_collector.enabled and stats:
                # Extract optimal maker_gain_max from solution metadata if available
                maker_gain_max = None
                if solutions and len(solutions) > 0 and len(solutions[0]) > 0:
                    maker_gain_max = solutions[0][0].get('_optimal_maker_gain_max')

                statistics_collector.complete_transaction(
                    stats=stats,
                    solutions=solutions if solutions else [],
                    maker_gain_max=maker_gain_max,
                    failure_reason=failure_reason,
                    skipped=skipped
                )


        # —— modal CJ value (works on BTC values in raw tx) ————————
        if solutions:
            best_solution = solutions[0]
            cj_value = max(set(o['cj']['value'] for o in best_solution), key=lambda x: sum(1 for o in best_solution if o['cj']['value'] == x))
            participants = _build_participants(best_solution, tx, cj_value) if solutions else []
            relabel_roles(participants, config)

            # Extract total valid assignments from the solution metadata
            total_assignments = best_solution[0].get('_total_valid_assignments', 1) if best_solution else 1

            coinjoin_objects.append(
                CoinJoin(
                    txid=txid,
                    block_height=block.get('height', 0),
                    tx=tx,
                    participants=participants,
                    meta={
                        'blackbox_analysis': True,
                        'sudoku_solved': bool(solutions),
                        'num_solutions': total_assignments,
                        'candidate_cj_value': cj_value,  # Decimal (sat)
                        'input_count': len(tx['vin']),
                        'output_count': len(tx['vout']),
                        'block_time': block.get('time'),
                    },
                )
            )
        else:
            # Create a CoinJoin object even for failures to track them in the report
            coinjoin_objects.append(
                CoinJoin(
                    txid=txid,
                    block_height=block.get('height', 0),
                    tx=tx,
                    participants=[],
                    meta={
                        'blackbox_analysis': True,
                        'sudoku_solved': False,
                        'num_solutions': 0,
                        'failure_reason': failure_reason,
                        'skipped': skipped,
                        'input_count': len(tx['vin']),
                        'output_count': len(tx['vout']),
                        'block_time': block.get('time'),
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

            if -1 >= diff >= - maker_gain_max_int * num_makers:
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

    # Store the total number of valid assignments in the solution metadata
    # This allows the caller to know how many alternative solutions were found
    if min_taker_fee_solutions:
        # Add metadata to the best solution about total assignments found
        for participant in min_taker_fee_solutions[0]:
            participant['_total_valid_assignments'] = len(reconstruct_sudoku_solutions)

    return min_taker_fee_solutions