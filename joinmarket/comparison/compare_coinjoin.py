"""
comparison.py
========================================
Reusable utilities for comparing results of CoinJoin analyses produced by
independent *black‑box* heuristics and *white‑box* ground‑truth data.  These
functions are intentionally framework‑agnostic so they can be imported from
CLI tools, notebooks, or web back‑ends without pulling in heavy dependencies
beyond the Python standard library.

Functions
---------
- ``generate_comparison_data``     – high‑level, TXID‑centric comparison.
- ``generate_object_comparison``   – deep comparison using ``CoinJoin`` objects.
- ``generate_coinjoin_breakdown``  – rich per‑transaction breakdown helper.

Every function returns plain ``dict`` / ``list`` structures so that callers can
easily serialise the results to JSON, feed them into Pandas, or render them
inside HTML templates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

__all__ = [
    "generate_comparison_data",
    "generate_object_comparison",
    "generate_coinjoin_breakdown",
]

from joinmarket.common.coinjoin_model import CoinJoin


# ---------------------------------------------------------------------------
#  High‑level TXID comparison
# ---------------------------------------------------------------------------

def generate_comparison_data(
    blackbox_results: List[Dict[str, Any]],
    whitebox_data:    List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return aggregated statistics comparing two independent analyses.

    Both *blackbox_results* and *whitebox_data* are assumed to be lists of
    dictionaries that include at least a ``"txid"`` field.  The black‑box side
    may additionally provide a ``"solutions"`` list (JoinMarket Sudoku output);
    the white‑box side may include ``"output_count"`` and ``"output_clients"``.
    Missing optional keys are handled gracefully.
    """
    # Extract unique TXIDs ---------------------------------------------------
    bb_txids: Set[str] = {r["txid"] for r in blackbox_results}
    wb_txids: Set[str] = {r["txid"] for r in whitebox_data}

    common       = bb_txids & wb_txids
    only_bb      = bb_txids - wb_txids
    only_wb      = wb_txids - bb_txids
    union_size   = len(bb_txids | wb_txids) or 1  # avoid division by zero

    # Per‑TXID deep dive ------------------------------------------------------
    detailed: List[Dict[str, Any]] = []
    for txid in common:
        bb_tx = next(r for r in blackbox_results if r["txid"] == txid)
        wb_tx = next(r for r in whitebox_data    if r["txid"] == txid)

        # Participant counts --------------------------------------------------
        bb_part_cnt = len(bb_tx.get("solutions", [{}])[0]) if bb_tx.get("solutions") else 0
        wb_part_cnt = wb_tx.get("output_count", 0)

        # Client attribution --------------------------------------------------
        bb_clients: Set[str] = {
            p["client"]
            for sol in bb_tx.get("solutions", [])
            for p   in sol
            if p.get("client")
        }
        wb_clients: Set[str] = set(wb_tx.get("output_clients", []))

        common_clients = bb_clients & wb_clients
        only_bb_c      = bb_clients - wb_clients
        only_wb_c      = wb_clients - bb_clients

        detailed.append({
            "txid":                       txid,
            "block_height":               wb_tx.get("block", 0),  # default if missing
            "blackbox_participants":      bb_part_cnt,
            "whitebox_participants":      wb_part_cnt,
            "common_clients":             sorted(common_clients),
            "only_blackbox_clients":      sorted(only_bb_c),
            "only_whitebox_clients":      sorted(only_wb_c),
            "attribution_match_percentage": round(
                len(common_clients) / max(len(bb_clients | wb_clients), 1) * 100, 2
            ),
        })

    detailed.sort(key=lambda x: x["block_height"])  # deterministic order

    return {
        "total_blackbox":          len(bb_txids),
        "total_whitebox":          len(wb_txids),
        "common":                  len(common),
        "only_blackbox":           len(only_bb),
        "only_whitebox":           len(only_wb),
        "detection_agreement":     round(len(common) / union_size * 100, 2),
        "detailed_comparison":     detailed,
        "common_txids":            sorted(common),
        "only_blackbox_txids":     sorted(only_bb),
        "only_whitebox_txids":     sorted(only_wb),
    }

# ---------------------------------------------------------------------------
#  Object‑level comparison
# ---------------------------------------------------------------------------

from typing import List, Dict, Any

def generate_object_comparison(
    blackbox_cj_objs: List[Any],
    whitebox_cj_objs: List[Any],
    detailed: bool = False
) -> Dict[str, Any]:
    """
    Compare CoinJoin *objects* produced by black-box and white-box pipelines.

    Relies on the updated `compare_coinjoin_objects`, which now returns:
        txid, block_height, participants_bb, participants_wb,
        matched_participants, role_accuracy, overall_role_success,
        blackbox_cj_amount, whitebox_cj_amount, blackbox_fee, whitebox_fee
    """

    bb_map = {cj.txid: cj for cj in blackbox_cj_objs}
    wb_map = {cj.txid: cj for cj in whitebox_cj_objs}

    common_txids = bb_map.keys() & wb_map.keys()
    per_tx: List[Dict[str, Any]] = []

    # ──────────────────────────────────────────────────────────────────
    for txid in common_txids:
        comp = compare_coinjoin_objects(bb_map[txid], wb_map[txid], detailed=detailed)
        per_tx.append(comp)

    per_tx.sort(key=lambda x: x["block_height"])

    # ──────────────────────────────────────────────────────────────────
    # aggregated statistics
    tx_cnt                   = len(per_tx)
    role_acc_avg             = round(sum(t["role_accuracy"]        for t in per_tx) / max(tx_cnt, 1), 2)
    overall_role_succ_avg    = round(sum(t["overall_role_success"] for t in per_tx) / max(tx_cnt, 1), 2)

    total_bb_parts           = sum(t["participants_bb"]     for t in per_tx)
    total_matched_parts      = sum(t["matched_participants"] for t in per_tx)
    participant_match_rate   = round(total_matched_parts / max(total_bb_parts, 1) * 100, 2)

    return {
        "obj_comparison":            per_tx,              # per-transaction breakdown
        "comparison_tx_count":       tx_cnt,
        "role_accuracy_avg":         role_acc_avg,        # avg. accuracy within matched participants
        "overall_role_success_avg":  overall_role_succ_avg,  # avg. success over *all* BB participants
        "participant_match_rate":    participant_match_rate, # % of BB participants we could pair
        "total_bb_participants":     total_bb_parts,
        "total_matched_participants": total_matched_parts,
    }


def _participant_signature(p) -> Tuple[frozenset[Tuple[str, int]], str | None]:
    """
    A stable identifier for a participant, built from
      • complete set of input (txid, vout) pairs
      • cj_output address (may be None)
    """
    inputs: Set[Tuple[str, int]] = {(i.txid, i.vout) for i in p.inputs}
    addr = getattr(p.change_output, "address", None)
    return frozenset(inputs), addr


def _possible_match(sig_bb, sig_wb) -> bool:
    """Loose check used when an exact signature key is missing."""
    in_bb, addr_bb = sig_bb
    in_wb, addr_wb = sig_wb
    # same output address OR any common input
    return (addr_bb is not None and addr_bb == addr_wb) or bool(in_bb & in_wb)


def compare_coinjoin_objects(bb, wb, *, detailed: bool = False) -> Dict[str, Any]:
    # ───────── build WB index
    wb_idx: Dict[Tuple[frozenset, str | None], list] = {}
    for p in wb.participants:
        wb_idx.setdefault(_participant_signature(p), []).append(p)

    matched = role_matches = 0
    part_details: List[Dict[str, Any]] = []

    for b in bb.participants:
        sig_b      = _participant_signature(b)
        wb_cand    = wb_idx.get(sig_b)

        if not wb_cand:
            # fuzzy fallback
            for sig_w, lst in wb_idx.items():
                if _possible_match(sig_b, sig_w):
                    wb_cand = lst
                    break

        has_match = bool(wb_cand)
        if has_match:
            matched += 1
            role_ok = any(b.role == w.role and b.role != "unknown" for w in wb_cand)
            if role_ok:
                role_matches += 1
        else:
            role_ok = False

        if detailed:
            part_details.append({
                "bb_sig":   sig_b,
                "wb_sig":   [_participant_signature(w) for w in wb_cand] if wb_cand else [],
                "matched":  has_match,
                "bb_role":  b.role,
                "wb_roles": [w.role for w in wb_cand] if wb_cand else [],
                "role_match": role_ok,
            })

    role_accuracy        = round(role_matches / max(matched, 1)   * 100, 2)
    overall_role_success = round(role_matches / max(len(bb.participants), 1) * 100, 2)

    result = {
        "txid":                   bb.txid,
        "block_height":           bb.block_height,
        "participants_bb":        len(bb.participants),
        "participants_wb":        len(wb.participants),
        "matched_participants":   matched,
        "role_accuracy":          role_accuracy,
        "overall_role_success":   overall_role_success,
        "blackbox_cj_amount":     bb.cj_amount,
        "whitebox_cj_amount":     wb.cj_amount,
        "blackbox_fee":           bb.miner_fee,
        "whitebox_fee":           wb.miner_fee,
    }

    if detailed:
        result["participant_breakdown"] = part_details

    return result



# ---------------------------------------------------------------------------
#  Breakdown helper
# ---------------------------------------------------------------------------

def generate_coinjoin_breakdown(
    cj_objs:       List[Any],
    analysis_type: str = "blackbox",
) -> List[Dict[str, Any]]:
    """Return a rich, serialisable structure for each *CoinJoin* object."""
    if not cj_objs:
        return []

    breakdowns: List[Dict[str, Any]] = []
    for cj in cj_objs:
        cj_info: Dict[str, Any] = {
            "txid":             cj.txid,
            "block_height":     cj.block_height,
            "participant_count": len(cj.participants),
            "cj_amount":        cj.cj_amount,
            "miner_fee":        cj.miner_fee,
            "participants":     [],
        }

        for p in cj.participants:
            entry: Dict[str, Any] = {
                "role":         p.role,
                "client":       p.client,
                "inputs":       [{
                    "txid":    i.txid,
                    "vout":    i.vout,
                    "value":   i.value,
                    "address": i.address,
                } for i in p.inputs],
                "cj_output":    {
                    "n":       p.cj_output.n,
                    "value":   p.cj_output.value,
                    "address": p.cj_output.address,
                },
                "change_output": None,
                "delta":        p.delta,
            }
            if p.change_output:
                entry["change_output"] = {
                    "n":       p.change_output.n,
                    "value":   p.change_output.value,
                    "address": p.change_output.address,
                }
            cj_info["participants"].append(entry)

        breakdowns.append(cj_info)

    breakdowns.sort(key=lambda x: x["block_height"])
    return breakdowns
