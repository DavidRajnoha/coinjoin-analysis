from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AnalysisConfig:
    """Switches that select between the legacy attribution and its extensions.

    maker_sessions: account for JoinMarket-NG tumbler maker sessions (sw0absoffer with
        cjfee_abs=0). Participants with delta == 0 are labelled 'zero_fee_maker' and treated
        as tumbler legs when building chains and propagating identities. With the switch off,
        such participants are plain makers and the analysis behaves exactly as before.
    zero_fee_tolerance: max delta (sat) still considered a zero-fee maker; only used when
        maker_sessions is on.
    strict_tumbler_links: chain-based attribution only follows spends by tumbler participants,
        assigns a parent cj output to the participant whose identity matches the child, and
        propagates identity only across the change output's real owner. Legacy attribution
        considered every child participant and always credited the parent's taker. None means
        "same as maker_sessions" (the maker-sessions mode needs it to keep tumblers apart).
    solver: which Sudoku backend recovers participants from a transaction. 'matrix' is the
        in-repo subset-sum/DFS solver; 'ilp' is joinmarket_analyzer's integer-programming
        solver (optional dependency). See coinjoin_sudoku/solvers.py.
    search_strategy / max_iterations: binary search for the smallest maker_gain_max that still
        yields solutions ('matrix' only).
    ilp_max_fee_rel / ilp_max_solutions: maker fee ceiling as a fraction of the equal output,
        and the cap on enumerated solutions ('ilp' only).
    """
    maker_sessions: bool = False
    zero_fee_tolerance: int = 0
    strict_tumbler_links: Optional[bool] = None
    solver: str = "matrix"
    search_strategy: str = "aggressive_downscale"
    max_iterations: int = 5
    ilp_max_fee_rel: float = 0.05
    ilp_max_solutions: int = 100

    @property
    def strict_links(self) -> bool:
        return self.maker_sessions if self.strict_tumbler_links is None else self.strict_tumbler_links

    @property
    def label(self) -> str:
        if self.maker_sessions:
            base = "maker_sessions" if self.strict_links else "maker_sessions_loose"
        else:
            base = "strict_links" if self.strict_links else "legacy"
        return base if self.solver == "matrix" else f"{base}_{self.solver}"

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), 'strict_links': self.strict_links, 'label': self.label}


DEFAULT_CONFIG = AnalysisConfig()
