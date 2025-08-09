from joinmarket.blackbox.coinjoin_sudoku.strategies.pruning_strategies.pruning import PruningStrategy


class TakerLookAheadPruning(PruningStrategy):
    def would_prevent_valid_solution(self, remaining_changes, taker_assigned,
                                                would_assign_taker, current_assignment,
                                                used_compositions, current_subset_info):
        """
        Optimized lookahead that only checks when it's likely to save significant work.
        """
        new_taker_assigned = taker_assigned or would_assign_taker
        remaining_count = len(remaining_changes) - 1

        if remaining_count <= 1:
            # For 0-1 remaining assignments, let natural recursion handle it
            # The next call will immediately discover any problems
            return False

        # Only do expensive lookahead for the most critical constraint:
        # ensuring we can still assign a taker if we haven't assigned one yet
        if not new_taker_assigned:
            return self._check_taker_still_possible(remaining_changes[1:], current_assignment,
                                                    used_compositions, current_subset_info)

        # If we already have a taker, the remaining constraints are less likely
        # to cause deep failures, so let natural recursion handle them
        return False

    def _check_taker_still_possible(self, future_changes, current_assignment,
                                    used_compositions, current_subset_info):
        """
        Focused check: can we still assign a taker among the remaining changes?
        This is the constraint most likely to cause deep recursive failures.
        """
        temp_used_compositions = used_compositions + [current_subset_info['input_composition']]

        # Quick check: is there ANY future change that could have a taker assignment?
        for future_change in future_changes:
            if future_change not in self.viable_subsets_by_change:
                continue

            for check_subset_idx, check_subset_info in self.viable_subsets_by_change[future_change].items():
                if check_subset_idx in current_assignment:
                    continue

                # Quick overlap check
                check_composition = check_subset_info['input_composition']
                if any(self._subsets_overlap(check_composition, used_comp)
                       for used_comp in temp_used_compositions):
                    continue

                # Quick role check
                delta = self._calculate_delta(check_subset_info, future_change)
                if self._determine_role(delta) == 'taker':
                    # Found at least one possible taker assignment
                    return False

        # No possible taker assignments found
        return True
