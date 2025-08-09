import time

import numpy as np


class MatrixSudokuDFSContext:
    def __init__(self, compatibility, change_outputs, cj_outs, maker_gain_max,
                 fee_tol, miner_fee, subset_indicators, compatibility_taker):
        self.compatibility = compatibility
        self.change_outputs = change_outputs
        self.cj_value = max(int(o['value']) for o in cj_outs)
        self.maker_gain_max = maker_gain_max
        self.fee_tol = fee_tol
        self.miner_fee = miner_fee
        self.subset_indicators = subset_indicators
        self.sweep_tx = len(change_outputs) != len(cj_outs)

        # Pre-compute constraints (borrowed from your original implementation)
        self.max_taker_overspend = int(miner_fee + (len(change_outputs) - 1) * maker_gain_max + fee_tol)

        self.viable_subsets_by_change = self._subsets_by_change(compatibility)
        self.viable_subsets_by_change_taker = self._subsets_by_change(compatibility_taker)

        self.results = []
        self.prune_count = 0

    def _subsets_by_change(self, compatibility):
        viable_subsets = {
            subset_idx: info for subset_idx, info in compatibility.items()
            if len(info['compatible_changes']) > 0
        }
        viable_subsets_by_change = {}
        for n in range(len(self.change_outputs)):
            viable_idxs = [subset_idx for subset_idx, info in viable_subsets.items() if
                           n in info['compatible_changes']]
            viable_subsets_by_change[n] = {}
            for subset_idx in viable_idxs:
                viable_subsets_by_change[n][subset_idx] = viable_subsets[subset_idx]
        return viable_subsets_by_change


    def run(self):
        """Main entry point - mirrors your original algorithm's interface."""
        # if len(self.viable_subsets) < len(self.change_outputs):
        #     return []
        start = time.time()

        subset_sizes = [len(self.viable_subsets_by_change[change_idx]) for change_idx in range(len(self.change_outputs))]
        subset_size_takers = [len(self.viable_subsets_by_change_taker[change_idx]) for change_idx in range(len(self.change_outputs))]

        if sum(subset_sizes) > 300 or sum(subset_size_takers) > 1800:
            print(f"Skipping DFS for {sum(subset_sizes)} subsets and {sum(subset_size_takers)} taker subsets")
            return []

        if self.sweep_tx:
            print(f"Solving sweep (no taker) assignment with {subset_sizes} subsets per change")
            self._search_assignments({}, set(), [],
                                     list(range(len(self.change_outputs))),
                                     False,
                                 not self.sweep_tx)

        else:
            print(f"Solving for taker change assignment with {subset_size_takers} subsets per taker change"
                  f"and {subset_sizes} subsets per change")
            self._search_taker_first()
        end = time.time()
        print(f"DFS took {end - start} seconds")


        return self.results

    def _calculate_delta(self, subset_info, change_idx):
        """Calculate delta for a subset-change assignment."""
        subset_sum = subset_info['subset_sum']
        change_value = int(self.change_outputs[change_idx]['value'])
        return int(self.cj_value) + change_value - subset_sum

    def _determine_role(self, delta):
        """Determine role based on delta - borrowed from your original logic."""
        if -1 <= delta <= self.maker_gain_max:
            return 'maker'
        elif -self.max_taker_overspend <= delta <= -1:
            return 'taker'
        else:
            return 'invalid'

    def _subsets_overlap(self, composition_a, composition_b):
        """Check if two input compositions overlap."""
        return np.any(composition_a & composition_b)


    def _can_assign_subset(self, subset_idx, subset_info, change_idx,
                           current_assignment, used_compositions, remaining_changes):
        """
        Check if a subset can be assigned to a change output.
        Validates compatibility and overlap constraints.
        """
        # Check if subset is already assigned
        if subset_idx in current_assignment:
            return False

        # Check if change output is compatible with this subset
        if change_idx not in subset_info['compatible_changes']:
            return False

        # Check for input overlap with already assigned subsets
        current_composition = subset_info['input_composition']
        if any(self._subsets_overlap(current_composition, used_comp)
               for used_comp in used_compositions):
            return False

        # Check if there are enough inputs left
        unassigned_inputs = sum(np.logical_not(np.logical_or.reduce(used_compositions))) if used_compositions \
            else len(current_composition)
        if unassigned_inputs - len(remaining_changes) < 0:
            return False

        return True

    # def _would_prevent_valid_solution(self, remaining_changes, taker_assigned,
    #                                   would_assign_taker, current_assignment,
    #                                   used_compositions, current_subset_info):
    #     """
    #     Lookahead pruning: check if making this assignment would prevent
    #     finding a valid complete solution.
    #
    #     Key insights:
    #     1. If we haven't assigned a taker and this isn't a taker, ensure
    #        remaining assignments can still produce a taker
    #     2. If this is a taker, ensure remaining assignments can all be makers
    #     """
    #     new_taker_assigned = taker_assigned or would_assign_taker
    #     remaining_count = len(remaining_changes) - 1  # -1 because we're about to assign one
    #
    #     if remaining_count == 0:
    #         # This is the last assignment, no lookahead needed
    #         return False
    #
    #     # Simulate the current assignment for lookahead analysis
    #     temp_used_compositions = used_compositions + [current_subset_info['input_composition']]
    #     temp_assignment = current_assignment.copy()
    #     temp_assignment[list(current_subset_info.keys())[0]] = remaining_changes[0]  # Temporary assignment
    #
    #     # Check each remaining change output
    #     for i, future_change in enumerate(remaining_changes[1:], 1):
    #         can_assign_any = False
    #         can_assign_taker = False
    #         can_assign_maker = False
    #
    #
    #         # Look for viable assignments for this future change output
    #         for check_subset_idx, check_subset_info in self.viable_subsets_by_change[future_change].items():
    #             if (check_subset_idx in temp_assignment):
    #                 continue
    #
    #             # Check overlap constraints
    #             check_composition = check_subset_info['input_composition']
    #             if any(self._subsets_overlap(check_composition, used_comp)
    #                    for used_comp in temp_used_compositions):
    #                 continue
    #
    #             # Calculate what role this assignment would have
    #             delta = self._calculate_delta(check_subset_info, future_change)
    #             role = self._determine_role(delta)
    #
    #             if role == 'invalid':
    #                 continue
    #
    #             can_assign_any = True
    #
    #             if role == 'taker':
    #                 can_assign_taker = True
    #             elif role == 'maker':
    #                 can_assign_maker = True
    #
    #         # If we can't assign anything to this future change, this branch is doomed
    #         if not can_assign_any:
    #             return True
    #
    #         # Role-based pruning logic
    #         if not new_taker_assigned:
    #             # We still need to assign a taker somewhere
    #             if i == remaining_count - 1:  # This is the last future change
    #                 # The last assignment MUST be able to be a taker
    #                 if not can_assign_taker:
    #                     return True
    #             else:
    #                 # For non-final future changes, we need either:
    #                 # 1. This change can be a taker, OR
    #                 # 2. This change can be a maker AND later changes can be takers
    #                 if not (can_assign_taker or can_assign_maker):
    #                     return True
    #         else:
    #             # We already have a taker, all remaining must be makers
    #             if not can_assign_maker:
    #                 return True
    #
    #     return False



    def _search_assignments(self, current_assignment, used_changes,
                            used_compositions, remaining_changes, taker_assigned, looking_for_taker):
        """Recursive search with pruning - similar structure to your original DFS."""

        # Base case
        # if len(remaining_changes) == 0 and looking_for_taker and not taker_assigned:
        #     return

        if len(remaining_changes) == 0:
            self.results.append(current_assignment.copy())
            return


        # Pruning logic (similar to your original implementation)
        # if not taker_assigned and len(remaining_changes) == 1:
        #     # Last assignment must be a taker
        #     self._try_final_taker_assignment(current_assignment, used_compositions, remaining_changes[0])
        #     return

        # Try assignments for next change output
        next_change = remaining_changes[0]

        for subset_idx in self.viable_subsets_by_change[next_change]:
            subset_info = self.viable_subsets_by_change[next_change][subset_idx]

            if self._can_assign_subset(subset_idx, subset_info, next_change,
                                       current_assignment, used_compositions, remaining_changes):

                delta = self._calculate_delta(subset_info, next_change)
                role = self._determine_role(delta)

                if role == 'invalid' or (role == 'taker' and taker_assigned):
                    self.prune_count += 1
                    continue

                # Lookahead pruning for taker constraint
                # if self._would_prevent_valid_solution(remaining_changes, taker_assigned,
                #                                       role == 'taker', current_assignment,
                #                                       used_compositions, subset_info):
                #     self.prune_count += 1
                #     continue

                # Make assignment and recurse
                current_assignment[subset_idx] = next_change
                self._search_assignments(
                    current_assignment,
                    used_changes | {next_change},
                    used_compositions + [subset_info['input_composition']],
                    remaining_changes[1:],
                    taker_assigned or role == 'taker',
                    looking_for_taker
                )
                del current_assignment[subset_idx]

    def _search_taker_first(self):
        """Recursive search with pruning - similar structure to your original DFS."""
        remaining_changes = list(range(len(self.change_outputs)))
        used_compositions = []
        used_changes = set()

        # Base case, should not occur
        if len(remaining_changes) == 0:
            return

        # Assign taker to all changes and solve for each taker-change assignment
        for change_idx in range(len(remaining_changes)):
            taker_change = remaining_changes[change_idx]
            current_assignment = {}
            # Try all possible taker-change subsets
            for subset_idx in self.viable_subsets_by_change_taker[taker_change]:
                subset_info = self.viable_subsets_by_change_taker[taker_change][subset_idx]
                if self._can_assign_subset(subset_idx, subset_info, taker_change,
                                           current_assignment, used_compositions, remaining_changes):

                    delta = self._calculate_delta(subset_info, taker_change)
                    role = self._determine_role(delta)

                    if role != 'taker':
                        self.prune_count += 1
                        continue

                    # Make assignment and recurse, now looking for maker with much smaller viable subset space
                    current_assignment[subset_idx] = taker_change
                    self._search_assignments(
                        current_assignment,
                        used_changes | {taker_change},
                        used_compositions + [subset_info['input_composition']],
                        remaining_changes[:change_idx] + remaining_changes[change_idx + 1:],
                        True,
                    True)
                    del current_assignment[subset_idx]
