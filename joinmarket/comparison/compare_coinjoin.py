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
- ``compare_coinjoin_chains``      – chain-level comparison.

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
    "compare_coinjoin_chains",
]

from joinmarket.common.coinjoin_model import CoinJoin
from joinmarket.common.coinjoin_chain import CoinJoinTree


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

    all_txids = set(bb_map.keys()) | set(wb_map.keys())
    per_tx: List[Dict[str, Any]] = []

    # ──────────────────────────────────────────────────────────────────
    for txid in all_txids:
        bb_obj = bb_map.get(txid)
        wb_obj = wb_map.get(txid)
        comp = compare_coinjoin_objects(bb_obj, wb_obj, detailed=detailed)
        per_tx.append(comp)

    per_tx.sort(key=lambda x: x.get("block_height", 0))

    # ──────────────────────────────────────────────────────────────────
    # aggregated statistics
    tx_cnt                   = len(per_tx)
    role_acc_avg             = round(sum(t["role_accuracy"]        for t in per_tx if t.get("role_accuracy") is not None) / max(tx_cnt, 1), 2)
    overall_role_succ_avg    = round(sum(t["overall_role_success"] for t in per_tx if t.get("overall_role_success") is not None) / max(tx_cnt, 1), 2)
    taker_success_avg        = round(sum(t["taker_success"]       for t in per_tx if t.get("taker_success") is not None) / max(tx_cnt, 1), 2)
    taker_match_avg         = round(sum(t["taker_match"]         for t in per_tx if t.get("taker_match") is not None) / max(tx_cnt, 1) * 100, 2)
    utxo_accuracy_avg       = round(sum(t["utxo_accuracy"]      for t in per_tx if t.get("utxo_accuracy") is not None) / max(tx_cnt, 1), 2)
    taker_sensitivity_avg = taker_match_avg

    # Specificity = True Negatives / (True Negatives + False Positives)
    # True Negatives = total WB makers - false positives
    # False Positives = sum of taker_false_positive across all transactions
    total_false_positives = sum(t["taker_false_positive"] for t in per_tx if t.get("taker_false_positive") is not None)
    total_wb_makers = sum(t["wb_makers_count"] for t in per_tx if t.get("wb_makers_count") is not None)
    taker_specificity_avg = round((total_wb_makers - total_false_positives) / total_wb_makers * 100, 2) if total_wb_makers > 0 else None

    total_bb_parts           = sum(t["participants_bb"]     for t in per_tx if t.get("participants_bb") is not None)
    total_matched_parts      = sum(t["matched_participants"] for t in per_tx if t.get("matched_participants") is not None)
    participant_match_rate   = round(total_matched_parts / max(total_bb_parts, 1) * 100, 2)

    return {
        "obj_comparison":            per_tx,              # per-transaction breakdown
        "comparison_tx_count":       tx_cnt,
        "role_accuracy_avg":         role_acc_avg,        # avg. accuracy within matched participants
        "taker_success_avg":         taker_success_avg,   # avg. success within matched participants
        "overall_role_success_avg":  overall_role_succ_avg,  # avg. success over *all* BB participants
        "participant_match_rate":    participant_match_rate, # % of BB participants we could pair
        "total_bb_participants":     total_bb_parts,
        "total_matched_participants": total_matched_parts,
        "taker_match_avg":           taker_match_avg,
        "taker_sensitivity_avg":     taker_sensitivity_avg,
        "taker_specificity_avg":     taker_specificity_avg,
        "utxo_accuracy_avg":         utxo_accuracy_avg,
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


def attribute_utxo_accuracy(wb, bb):
    wb_input_roles = {}
    for participant in wb.participants:
        for tx_input in participant.inputs:
            wb_input_roles[tx_input.txid] = participant.role

    # Build blackbox input mapping: {txid: role}
    bb_input_roles = {}
    for participant in bb.participants:
        for tx_input in participant.inputs:
            bb_input_roles[tx_input.txid] = participant.role

    # Calculate input attribution accuracy
    correct_attributions = 0
    total_common_inputs = 0

    # Find inputs that exist in both analyses
    for txid, bb_role in bb_input_roles.items():
        if txid in wb_input_roles:
            total_common_inputs += 1
            wb_role = wb_input_roles[txid]
            # Count as correct if roles match and neither is "unknown"
            if bb_role == wb_role and bb_role != "unknown":
                correct_attributions += 1

    input_attribution_accuracy = round(
        (correct_attributions / max(total_common_inputs, 1)) * 100, 2
    ) if total_common_inputs > 0 else None

    return input_attribution_accuracy


def compare_coinjoin_objects(bb, wb, *, detailed: bool = False) -> Dict[str, Any]:
    # Handle cases where one or both objects are None
    if bb is None and wb is None:
        return {
            "txid": None,
            "block_height": None,
            "participants_bb": None,
            "participants_wb": None,
            "matched_participants": None,
            "role_accuracy": None,
            "overall_role_success": None,
            "blackbox_cj_amount": None,
            "whitebox_cj_amount": None,
            "blackbox_fee": None,
            "whitebox_fee": None,
            "participant_breakdown": [] if detailed else None,
        }
    if bb is None:
        return {
            "txid": wb.txid,
            "block_height": wb.block_height,
            "participants_bb": None,
            "participants_wb": len(wb.participants),
            "matched_participants": 0,
            "role_accuracy": None,
            "overall_role_success": None,
            "blackbox_cj_amount": None,
            "whitebox_cj_amount": wb.cj_amount,
            "blackbox_fee": None,
            "whitebox_fee": wb.miner_fee,
            "participant_breakdown": [] if detailed else None,
        }
    if wb is None:
        return {
            "txid": bb.txid,
            "block_height": bb.block_height,
            "participants_bb": len(bb.participants),
            "participants_wb": None,
            "matched_participants": 0,
            "role_accuracy": None,
            "overall_role_success": None,
            "blackbox_cj_amount": bb.cj_amount,
            "whitebox_cj_amount": None,
            "blackbox_fee": bb.miner_fee,
            "whitebox_fee": None,
            "participant_breakdown": [] if detailed else None,
        }

    # ───────── build WB index
    wb_idx: Dict[Tuple[frozenset, str | None], list] = {}
    for p in wb.participants:
        wb_idx.setdefault(_participant_signature(p), []).append(p)

    matched = role_matches = taker_matches = taker_false_positive = 0
    part_details: List[Dict[str, Any]] = []

    for b in bb.participants:
        sig_b      = _participant_signature(b)
        wb_cand    = wb_idx.get(sig_b)

        if not wb_cand:
            for sig_w, lst in wb_idx.items():
                if _possible_match(sig_b, sig_w):
                    wb_cand = lst
                    break

        has_match = bool(wb_cand)
        if has_match:
            matched += 1
            role_ok = any(b.role == w.role and b.role != "unknown" for w in wb_cand)
            role_matches += 1 if role_ok else 0
            taker_matches += 1 if role_ok and wb_cand[0].role == "taker" else 0
            taker_false_positive += 1 if not role_ok and b.role == "taker" else 0
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

    utxo_accuracy        = attribute_utxo_accuracy(bb, wb)
    role_accuracy        = round(role_matches / max(matched, 1)   * 100, 2)
    overall_role_success = round(role_matches / max(len(bb.participants), 1) * 100, 2)
    taker_match          = True if taker_matches == 1 else False

    # Count WB makers for specificity calculation
    wb_makers_count = sum(1 for p in wb.participants if getattr(p, 'role', None) == 'maker')

    result = {
        "txid":                   bb.txid,
        "block_height":           bb.block_height,
        "participants_bb":        len(bb.participants),
        "participants_wb":        len(wb.participants),
        "matched_participants":   matched,
        "role_accuracy":          role_accuracy,
        "utxo_accuracy":          utxo_accuracy,
        "overall_role_success":   overall_role_success,
        "taker_match":            taker_match,
        "taker_false_positive":   taker_false_positive,
        "wb_makers_count":        wb_makers_count,
        "blackbox_cj_amount":     bb.cj_amount,
        "whitebox_cj_amount":     wb.cj_amount,
        "blackbox_fee":           bb.miner_fee,
        "whitebox_fee":           wb.miner_fee,
    }

    if detailed:
        result["participant_breakdown"] = part_details

    return result



# ---------------------------------------------------------------------------
#  Chain-level comparison
# ---------------------------------------------------------------------------

def compare_coinjoin_chains(
    blackbox_chains: List[CoinJoinTree],
    whitebox_chains: List[CoinJoinTree]
) -> Dict[str, Any]:
    """Compare lists of CoinJoinTree objects from blackbox and whitebox analyses.

    Identifies matching chains based on shared CoinJoin TXIDs and provides
    detailed comparison for each matched pair, as well as lists of unmatched chains.

    Returns:
        A dictionary containing:
        - 'total_blackbox_chains': Count of blackbox chains.
        - 'total_whitebox_chains': Count of whitebox chains.
        - 'matched_chain_pairs': List of dicts, each detailing a matched pair:
            - 'blackbox_chain_id': ID of the blackbox chain.
            - 'whitebox_chain_id': ID of the whitebox chain.
            - 'blackbox_txids': List of TXIDs in the blackbox chain.
            - 'whitebox_txids': List of TXIDs in the whitebox chain.
            - 'common_txids': List of TXIDs shared by both chains.
            - 'only_blackbox_txids': TXIDs present only in the blackbox chain.
            - 'only_whitebox_txids': TXIDs present only in the whitebox chain.
            - 'similarity_score': Jaccard index of the TXID sets.
            - 'is_full_match': True if chains are identical in TXID content.
        - 'unmatched_blackbox_chain_ids': List of IDs of blackbox chains with no match.
        - 'unmatched_whitebox_chain_ids': List of IDs of whitebox chains with no match.
        - 'num_matched_pairs': Total number of matched pairs found.
        - 'num_fully_matched_pairs': Number of pairs that are a full match.
        - 'num_partially_matched_pairs': Number of pairs that are a partial match.
    """
    matched_pairs_details: List[Dict[str, Any]] = []
    processed_bb_chain_ids: Set[str] = set()
    processed_wb_chain_ids: Set[str] = set()

    potential_matches: List[Tuple[float, CoinJoinTree, CoinJoinTree, Set[str], Set[str], Set[str]]] = []

    for bb_chain in blackbox_chains:
        bb_txids = {node.txid for node in bb_chain.nodes}
        for wb_chain in whitebox_chains:
            wb_txids = {node.txid for node in wb_chain.nodes}

            intersection = bb_txids.intersection(wb_txids)
            union = bb_txids.union(wb_txids)

            if not union:  # Both chains are empty of coinjoins
                similarity = 1.0 if not bb_txids and not wb_txids else 0.0
            else:
                similarity = len(intersection) / len(union)
            
            if similarity > 0: # Consider any overlap as a potential match
                potential_matches.append((similarity, bb_chain, wb_chain, bb_txids, wb_txids, intersection))

    # Sort by similarity (desc), then by blackbox chain ID (asc) for determinism
    potential_matches.sort(key=lambda x: (-x[0], x[1].id))

    for similarity, bb_chain, wb_chain, bb_txids, wb_txids, intersection_txids in potential_matches:
        if bb_chain.id not in processed_bb_chain_ids and wb_chain.id not in processed_wb_chain_ids:
            only_blackbox_txids = sorted(list(bb_txids - wb_txids))
            only_whitebox_txids = sorted(list(wb_txids - intersection_txids))
            
            is_full_match = not only_blackbox_txids and not only_whitebox_txids

            matched_pairs_details.append({
                'blackbox_chain_id': bb_chain.id,
                'whitebox_chain_id': wb_chain.id,
                'blackbox_txids': sorted(list(bb_txids)),
                'whitebox_txids': sorted(list(wb_txids)),
                'common_txids': sorted(list(intersection_txids)),
                'only_blackbox_txids': only_blackbox_txids,
                'only_whitebox_txids': only_whitebox_txids,
                'similarity_score': round(similarity, 4),
                'is_full_match': is_full_match
            })
            processed_bb_chain_ids.add(bb_chain.id)
            processed_wb_chain_ids.add(wb_chain.id)

    unmatched_bb_ids = sorted([chain.id for chain in blackbox_chains if chain.id not in processed_bb_chain_ids])
    unmatched_wb_ids = sorted([chain.id for chain in whitebox_chains if chain.id not in processed_wb_chain_ids])

    num_fully_matched = sum(1 for p in matched_pairs_details if p['is_full_match'])
    num_partially_matched = len(matched_pairs_details) - num_fully_matched

    return {
        # Single-transaction chains are not chains; they are counted separately.
        'total_blackbox_chains': sum(1 for c in blackbox_chains if c.length() > 1),
        'total_whitebox_chains': sum(1 for c in whitebox_chains if c.length() > 1),
        'singleton_blackbox_chains': sum(1 for c in blackbox_chains if c.length() == 1),
        'singleton_whitebox_chains': sum(1 for c in whitebox_chains if c.length() == 1),
        'matched_chain_pairs': matched_pairs_details,
        'unmatched_blackbox_chain_ids': unmatched_bb_ids,
        'unmatched_whitebox_chain_ids': unmatched_wb_ids,
        'num_matched_pairs': len(matched_pairs_details),
        'num_fully_matched_pairs': num_fully_matched,
        'num_partially_matched_pairs': num_partially_matched
    }


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
