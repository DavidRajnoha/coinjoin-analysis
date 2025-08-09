"""
Sudoku solver (DFS) with pruning for the taker.

"""

from __future__ import annotations

from decimal import Decimal, getcontext
from itertools import combinations
from typing import Any, Dict, List, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Decimal / denomination setup
# ─────────────────────────────────────────────────────────────────────────────
getcontext().prec = 30                        # plenty for 64‑bit ints
SAT_MULT = Decimal('100000000')               # BTC → satoshi
SAT      = Decimal('1')                       # one satoshi (after ×100 M)

MAX_INPUTS_SWEEP = 40
MAX_OUTPUTS_SWEEP = 20

MAX_INPUTS_NON_SWEEP = 20
MAX_OUTPUTS_NON_SWEEP = 30


# ─────────────────────────────────────────────────────────────────────────────
# DFS/backtracking context for Sudoku search
# ─────────────────────────────────────────────────────────────────────────────

class SudokuDFSContext:
    def __init__(self, parts, inputs, N, miner_fee, maker_gain_max, fee_tol, target_sum, canonical_key_func):
        self.parts = parts
        self.inputs = inputs
        self.N = N
        self.maker_gain_max = maker_gain_max
        self.fee_tol = fee_tol
        self.miner_fee = miner_fee
        self.target_sum = target_sum
        self.canonical_key = canonical_key_func
        self.results = []
        self.seen = set()
        self.prune_count = 0

    def run(self):
        self.inputs.sort(key=lambda i: i['value'], reverse=True)
        self._dfs(0, self.inputs, Decimal(0), False)
        return self.results

    def _dfs(self, idx: int, remaining: List[Dict[str, Any]], delta_sum: Decimal, taker_seen: bool):
        parts_left = len(self.parts) - idx
        makers_left = parts_left - (0 if taker_seen else 1)
        max_taker_overspend = self.miner_fee + (self.N - 1) * self.maker_gain_max + self.fee_tol

        # largest delta we could still reach
        max_possible = (
            delta_sum
            + makers_left * self.maker_gain_max
            + (Decimal(0) if taker_seen else -SAT)
        )
        # smallest delta we could still reach
        min_possible = (
            delta_sum
            - makers_left * SAT
            - (Decimal(0) if taker_seen else max_taker_overspend)
        )
        if max_possible < self.target_sum - self.fee_tol:
            self.prune_count += 1
            return
        if min_possible > self.target_sum + self.fee_tol:
            self.prune_count += 1
            return

        if idx == len(self.parts):
            if taker_seen and abs(delta_sum - self.target_sum) <= self.fee_tol:
                key = self.canonical_key(self.parts)
                if key not in self.seen:
                    self.seen.add(key)
                    self.results.append([dict(p) for p in self.parts])
            return

        part = self.parts[idx]
        outsum = part['cj']['value'] + (part['change']['value'] if part['change'] else Decimal(0))
        min_left = len(self.parts) - idx - 1

        # Try all non-empty subsets of remaining inputs (greedy, could optimize)
        for k in range(1, len(remaining) - min_left + 1):
            for combo in combinations(remaining, k):
                combo_sum = sum(i['value'] for i in combo)
                delta = outsum - combo_sum
                # Prune by role
                if part['role'] == 'maker':
                    if not (-SAT <= delta <= self.maker_gain_max):
                        continue
                else:  # taker
                    if not (-max_taker_overspend <= delta <= -SAT):
                        continue
                # Assign
                part['inputs'] = list(combo)
                part['delta'] = delta
                # Recurse
                next_remaining = [i for i in remaining if i not in combo]
                self._dfs(idx + 1, next_remaining, delta_sum + delta, taker_seen or part['role'] == 'taker')
                # Clean up for next iteration
                part.pop('inputs', None)
                part.pop('delta', None)
