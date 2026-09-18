import time

import numpy as np


class MatrixSudokuDFSContext:
    def __init__(self, compatibility, change_outputs, cj_outs, maker_gain_max,
                 fee_tol, miner_fee, compatibility_taker):
        self.change_outputs = change_outputs
        self.cj_value = max(int(o['value']) for o in cj_outs)
        self.maker_gain_max = maker_gain_max
        self.fee_tol = fee_tol
        self.miner_fee = miner_fee
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
        start = time.time()

        subset_sizes = [len(self.viable_subsets_by_change[change_idx]) for change_idx in range(len(self.change_outputs))]
        subset_size_takers = [len(self.viable_subsets_by_change_taker[change_idx]) for change_idx in range(len(self.change_outputs))]

        if sum(subset_sizes) > 500 or sum(subset_size_takers) > 1800:
            print(f"Skipping DFS for {sum(subset_sizes)} subsets and {sum(subset_size_takers)} taker subsets")
            # Diagnostic summary for skip
            zero_viable = [i for i, c in enumerate(subset_sizes) if c == 0]
            zero_viable_taker = [i for i, c in enumerate(subset_size_takers) if c == 0]
            print(
                "No blackbox attribution (DFS skipped): "
                f"sweep={self.sweep_tx}, changes={len(self.change_outputs)}, "
                f"subset_sizes={subset_sizes}, taker_subset_sizes={subset_size_takers}, "
                f"zero_viable_changes={zero_viable}, zero_viable_changes_taker={zero_viable_taker}, "
                f"miner_fee={int(self.miner_fee)}, fee_tol={int(self.fee_tol)}, "
                f"maker_gain_max={int(self.maker_gain_max)}, cj_value={int(self.cj_value)}"
            )
            return []

        if self.sweep_tx:
            print(f"Solving sweep (no taker) assignment with {subset_sizes} subsets per change")
            self._search_assignments({}, set(), [],
                                     list(range(len(self.change_outputs))),
                                     False)

        else:
            print(f"Solving for taker change assignment with {subset_size_takers} subsets per taker change"
                  f"and {subset_sizes} subsets per change")
            self._search_taker_first()
        end = time.time()
        print(f"DFS took {end - start} seconds")

        # If no results, print a concise diagnostic summary to aid debugging
        if not self.results:
            zero_viable = [i for i, c in enumerate(subset_sizes) if c == 0]
            zero_viable_taker = [i for i, c in enumerate(subset_size_takers) if c == 0]
            change_values = [int(ch['value']) for ch in self.change_outputs]
            print(
                "No blackbox attribution results (DFS found 0 solutions): "
                f"sweep={self.sweep_tx}, changes={len(self.change_outputs)}, "
                f"subset_sizes={subset_sizes}, taker_subset_sizes={subset_size_takers}, "
                f"zero_viable_changes={zero_viable}, zero_viable_changes_taker={zero_viable_taker}, "
                f"change_values={change_values}, "
                f"miner_fee={int(self.miner_fee)}, fee_tol={int(self.fee_tol)}, "
                f"maker_gain_max={int(self.maker_gain_max)}, cj_value={int(self.cj_value)}, "
                f"pruned_branches={self.prune_count}"
            )

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


    def _search_assignments(self, current_assignment, used_changes,
                            used_compositions, remaining_changes, taker_assigned):
        """Recursive search with pruning - similar structure to your original DFS."""

        # Base case

        if len(remaining_changes) == 0:
            self.results.append(current_assignment.copy())
            return


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


                # Make assignment and recurse
                current_assignment[subset_idx] = next_change
                self._search_assignments(
                    current_assignment,
                    used_changes | {next_change},
                    used_compositions + [subset_info['input_composition']],
                    remaining_changes[1:],
                    taker_assigned or role == 'taker',
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
                        True)
                    del current_assignment[subset_idx]
