"""Swappable backends for the CoinJoin Sudoku.

A solver answers one question: given a CoinJoin transaction, which subset of inputs paid
for which outputs, and which participant was the taker. Backends differ in method, so they
are kept behind one interface and selected by name (see AnalysisConfig.solver).

A solution is a list of participant dicts in the shape ``_build_participants`` consumes:

    {'inputs':  [{'vin': {'txid','vout',...}, 'value': Decimal(sat)}, ...],
     'cj':      {'n': int, 'value': Decimal(sat)},
     'change':  {'n': int, 'value': Decimal(sat)} | None,
     'delta':   Decimal(sat),   # outputs - inputs; negative = paid, the taker
     'role':    'taker' | 'maker'}

Backends return the solutions they consider valid; roles are re-derived from ``delta`` by
``relabel_roles`` afterwards, so a backend need not know about analysis modes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Dict, List

Solution = List[Dict[str, Any]]
Solver = Callable[..., List[Solution]]

_SOLVERS: Dict[str, Solver] = {}


def register_solver(name: str, solver: Solver) -> None:
    _SOLVERS[name] = solver


def get_solver(name: str) -> Solver:
    if name not in _SOLVERS:
        raise ValueError(f"Unknown solver {name!r}; available: {sorted(_SOLVERS)}")
    return _SOLVERS[name]


def available_solvers() -> List[str]:
    return sorted(_SOLVERS)


# ─────────────────────────────────────────────────────────────────────────────
# matrix: the in-repo solver (subset sums + constrained DFS)
# ─────────────────────────────────────────────────────────────────────────────

def _matrix_solver(tx, tx_map, config, statistics_collector=None, **kwargs) -> List[Solution]:
    from joinmarket.blackbox.coinjoin_sudoku.joinmarket_sudoku import (
        analyze_and_solve_sudoku_with_optimal_gain,
    )
    return analyze_and_solve_sudoku_with_optimal_gain(
        tx, tx_map,
        max_iterations=config.max_iterations,
        search_strategy=config.search_strategy,
    )


register_solver("matrix", _matrix_solver)


# ─────────────────────────────────────────────────────────────────────────────
# ilp: joinmarket_analyzer (github.com/m0wer/joinmarket_analyzer), optional
# ─────────────────────────────────────────────────────────────────────────────

def _to_mempool_tx(tx: Dict[str, Any], tx_map: Dict[str, Any]) -> Dict[str, Any]:
    """Bitcoin Core RPC shape (BTC floats) -> mempool.space shape (satoshi ints)."""
    def sat(value) -> int:
        return int(round(float(value) * 1e8))

    vin = []
    for v in tx["vin"]:
        prev = tx_map[v["txid"]]["tx"]
        prev_out = next(o for o in prev["vout"] if o["n"] == v["vout"])
        vin.append({
            "txid": v["txid"],
            "vout": v["vout"],
            "prevout": {
                "value": sat(prev_out["value"]),
                "scriptpubkey_address": prev_out.get("scriptPubKey", {}).get("address"),
            },
        })

    vout = [
        {
            "value": sat(o["value"]),
            "scriptpubkey_address": o.get("scriptPubKey", {}).get("address"),
        }
        for o in tx["vout"]
    ]
    return {"txid": tx.get("txid", ""), "vin": vin, "vout": vout}


def _ilp_solver(tx, tx_map, config, statistics_collector=None, **kwargs) -> List[Solution]:
    try:
        from joinmarket_analyzer import parse_transaction, solve_all_solutions
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ImportError(
            "The 'ilp' solver needs joinmarket_analyzer "
            "(pip install 'joinmarket-analyzer @ git+https://github.com/m0wer/joinmarket_analyzer')"
        ) from exc

    tx_data = parse_transaction(_to_mempool_tx(tx, tx_map))
    solutions = solve_all_solutions(
        tx_data,
        max_fee_rel=config.ilp_max_fee_rel,
        max_solutions=config.ilp_max_solutions,
        save_incrementally=False,
    )

    # Its UTXO.index numbers inputs by position in vin; map back to the outpoints we carry.
    vin_by_position = tx["vin"]
    equal_value = Decimal(tx_data.equal_amount)

    converted: List[Solution] = []
    for solution in solutions:
        participants: Solution = []
        for participant in solution.participants:
            inputs = [
                {
                    "vin": vin_by_position[utxo.index],
                    "value": Decimal(utxo.amount),
                }
                for utxo in participant.inputs
            ]
            change = participant.change_output
            input_sum = sum((i["value"] for i in inputs), Decimal(0))
            output_sum = equal_value + (Decimal(change.amount) if change else Decimal(0))
            participants.append({
                "inputs": inputs,
                "cj": {"n": None, "value": equal_value},
                "change": {"n": change.index, "value": Decimal(change.amount)} if change else None,
                "delta": output_sum - input_sum,
                "role": participant.role,
            })
        converted.append(participants)

    return converted


register_solver("ilp", _ilp_solver)
