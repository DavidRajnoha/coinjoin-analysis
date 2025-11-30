# CoinJoin Sudoku: Algorithm Overview

## Problem Statement

Given **n** inputs and **m** outputs in a CoinJoin transaction, determine which inputs belong to which participant.

**Approach:** Three-phase pipeline that narrows 2^n possibilities to a small set of valid solutions.

---

## The Three Phases

### Phase 1: Precomputation

**KEY INSIGHT:** Don't enumerate subsets one-by-one. Compute ALL 2^n subset sums in a single matrix multiplication.

**Input:** n inputs with values [v₁, v₂, ..., vₙ]
**Output:** All 2^n subset sums

**Algorithm** (lines 562-714):

1. **Generate binary indicator matrix M** (size 2^n × n)
   - Row i represents subset i using binary representation
   - Example: row 5 = [1,0,1,0,...] means subset {input₀, input₂}

2. **Single matrix operation:**
   ```
   subset_sums = M @ input_values
   ```

**Optimization:** Cache matrix M on disk (it grows exponentially but is reusable)

---

### Phase 2: Filtering Pipeline

**KEY INSIGHT:** Apply cascading filters to reduce 2^n subsets to only economically viable (subset, change_output) pairs.

**Input:** 2^n subsets
**Output:** Small set of compatible (subset, change) pairs

**Three-Stage Filter** (lines 597-726):

#### Stage 1: VALUE RANGE FILTER
Keep only subsets whose sum is in plausible range:
```
[cj_value + min_change - tolerance, cj_value + max_change + tolerance]
```
**Result:** 2^n subsets → ~thousands of subsets

#### Stage 2: INPUT COUNT FILTER
Remove subsets with too many inputs:
```
max_inputs_per_participant = total_inputs - num_participants + 1
```
**Result:** ~thousands → hundreds of subsets

#### Stage 3: COMPATIBILITY MATRIX
For each surviving subset, identify which change outputs satisfy economic constraints:

- **Maker:** `0 ≤ (cj + change - subset) ≤ maker_gain_max`
- **Taker:** negative delta (pays fees)

**Result:** Map of `{subset → [compatible_changes]}`
**Reduction:** hundreds → tens to hundreds of (subset, change) pairs

---

### Phase 3: Constrained DFS

**KEY INSIGHT:** Search only pre-filtered pairs using taker-first strategy.

**Input:** Compatible (subset, change) pairs from Phase 2
**Output:** Valid complete assignments

**Constraints** (lines 664-679):
1. Each participant gets exactly one subset + one change output
2. No input overlap between participants
3. Exactly one taker (negative delta)
4. Sum of deltas = miner_fee

**Search Strategy** (dfs_matrix_sudoku.py):

For non-sweep transactions:
- Fix taker assignment first (try all taker-compatible pairs)
- Then solve for remaining makers via backtracking
- Dramatically reduces branching factor

**Backtracking with pruning:**
- Check overlap before recursing
- Verify role constraints (only one taker)
- Ensure enough inputs remain for unassigned participants

---

## Simplified Pseudo Code

```python
function COINJOIN_SUDOKU(inputs, coinjoin_outputs, change_outputs,
                         miner_fee, constraints):

    # ─────────── PHASE 1: PRECOMPUTATION ───────────

    binary_matrix = generate_binary_matrix(len(inputs))  # 2^n × n matrix
    all_subset_sums = binary_matrix @ input_values       # Single operation!


    # ─────────── PHASE 2: FILTERING ───────────

    # Stage 1: Broad value range
    viable_subsets = filter_by_value_range(all_subset_sums)

    # Stage 2: Input count
    viable_subsets = filter_by_input_count(viable_subsets)

    # Stage 3: Economic compatibility
    compatible_pairs = build_compatibility_map(viable_subsets,
                                               change_outputs,
                                               constraints)
    # Result: {subset_id → [compatible_change_indices]}


    # ─────────── PHASE 3: CONSTRAINED DFS ───────────

    solutions = []

    # Strategy: Fix taker first, then solve for makers
    for each taker_compatible_pair in compatible_pairs:
        assignment = {taker: taker_compatible_pair}

        if DFS_search(assignment, remaining_participants, compatible_pairs):
            solutions.append(assignment)

    return solutions


function DFS_search(current_assignment, remaining, compatible_pairs):

    if no_more_remaining:
        if satisfies_all_constraints(current_assignment):
            return True
        return False

    next_participant = pick_next_unassigned()

    for each (subset, change) in compatible_pairs[next_participant]:

        # Pruning: Check constraints before recursing
        if has_input_overlap(subset, current_assignment):
            continue
        if violates_role_constraints(subset, change):
            continue

        # Try this assignment
        current_assignment[next_participant] = (subset, change)

        if DFS_search(current_assignment, remaining - 1, compatible_pairs):
            return True

        # Backtrack
        remove current_assignment[next_participant]

    return False
```

---

## Key Implementation Details

*Show these only if audience asks for specifics*

### Binary Matrix Generation
- Row i of matrix represents subset using binary: `bit j = (i >> j) & 1`
- Cached to disk since it's reusable across transactions
- Example: For 3 inputs, row 5 (binary 101) = [1,0,1] → {input₀, input₂}

### Economic Constraint Definitions
```
delta = cj_value + change_value - subset_sum
```
- **Maker role:** `0 ≤ delta ≤ maker_gain_max` (small positive gain)
- **Taker role:** `delta < 0` (pays fees to makers and miner)

### Overlap Detection
- Use binary representation: `overlap = (subset_a & subset_b) ≠ 0`
- Or use NumPy: `np.any(composition_a & composition_b)`

### Taker-First Optimization
- **Normal DFS:** Try all m^m assignments → exponential
- **Taker-first:** Fix 1 of m takers → Try (m-1)^(m-1) maker assignments
- Reduces branching factor significantly

---

## Presentation Guide

### For High-Level Audience (5-10 minutes)
- Show only the "Three Phases" section
- Emphasize the key insights in each phase
- Skip the pseudo code entirely

### For Technical Audience (15-20 minutes)
- Three Phases section (explain the pipeline concept)
- Simplified Pseudo Code (show the structure)
- Mention key implementation details exist but don't show unless asked

### For Deep-Dive (30+ minutes)
- All sections
- Walk through an example with small numbers (3-4 inputs)
- Show actual code snippets for the matrix multiplication

---

## What's Abstracted vs. Specific

### Abstracted Away
- Caching mechanisms (implementation detail)
- Exact bit manipulation operations
- Detailed pruning conditions
- Index reorganization logic
- Delta calculation specifics

### Kept Specific
- Matrix multiplication approach (THE key innovation)
- Three-stage filtering structure (the algorithm's backbone)
- The four DFS constraints (define the problem)
- Taker-first strategy (major optimization)

---

## Code References

- **Main algorithm:** `joinmarket/blackbox/coinjoin_sudoku/joinmarket_sudoku.py`
  - Lines 562-714: Precomputation and matrix multiplication
  - Lines 597-721: Filtering pipeline
  - Lines 700-746: Main orchestration function

- **DFS implementation:** `joinmarket/blackbox/coinjoin_sudoku/strategies/dfs_matrix_sudoku.py`
  - Lines 6-319: Complete DFS search with backtracking