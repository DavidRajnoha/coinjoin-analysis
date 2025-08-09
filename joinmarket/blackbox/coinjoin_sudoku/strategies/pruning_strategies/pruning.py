class PruningStrategy:
    def __init__(self):
        pass

    def would_prevent_valid_solution(self, remaining_changes, taker_assigned,
                                                would_assign_taker, current_assignment,
                                                used_compositions, current_subset_info):
        raise NotImplementedError()


