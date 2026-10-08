"""Generate the solver's subset-indicator matrices once, in a single process, before workers start.

Workers that find a size missing would otherwise all generate and write the same file at once.
Writes into ./subset_cache (the solver's path, relative to the working directory).
"""
import os
import sys

sys.path.insert(0, '/app')
from joinmarket.blackbox.coinjoin_sudoku import joinmarket_sudoku as js  # noqa: E402

MAX_N = max(js.MAX_INPUTS_SWEEP, js.MAX_INPUTS_NON_SWEEP)
for n in range(1, MAX_N + 1):
    if not os.path.exists(os.path.join('subset_cache', f'subset_indicators_{n}.npy')):
        js.generate_subset_indicators(n)
    js.SUBSET_INDICATORS_CACHE.clear()  # keep this process small
print(f'subset_cache ready up to {MAX_N} inputs')
