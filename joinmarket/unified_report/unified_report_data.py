"""
Helpers for aggregating and building unified CoinJoin report data.
"""
from typing import List, Dict, Any, Optional
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from joinmarket.common.chain_analysis_orchestrator import ChainAnalysisOrchestrator
from joinmarket.common.coinjoin_chain import identify_coinjoin_chains
from joinmarket.common.chain_based_attributor import ChainBasedAttributor
from joinmarket.comparison import generate_comparison_data, generate_object_comparison
from joinmarket.comparison.coinjoin_chain_analysis import (
    serialize_cj_chain_for_report
)
from joinmarket.comparison.compare_coinjoin import compare_coinjoin_chains
from joinmarket.comparison.chain_visualization import generate_colored_chain_comparison
from joinmarket.whitebox.load_scenario import identify_sole_takers
import os

def aggregate_blackbox_analysis_stats(blackbox_cj_objs):
    """Aggregate detailed statistics about blackbox analysis successes and failures."""
    total = len(blackbox_cj_objs)
    solved = sum(1 for cj in blackbox_cj_objs if cj.meta.get('sudoku_solved', False))
    unsolved = total - solved

    # Count failures by reason
    skipped = sum(1 for cj in blackbox_cj_objs if cj.meta.get('skipped', False))
    no_solution = sum(1 for cj in blackbox_cj_objs
                      if not cj.meta.get('sudoku_solved', False)
                      and not cj.meta.get('skipped', False))

    # Analyze solutions for solved CoinJoins
    solution_counts = []
    for cj in blackbox_cj_objs:
        if cj.meta.get('sudoku_solved', False):
            num_solutions = cj.meta.get('num_solutions', 0)
            solution_counts.append(num_solutions)

    # Collect failure details
    failure_details = []
    for cj in blackbox_cj_objs:
        if not cj.meta.get('sudoku_solved', False):
            failure_details.append({
                'txid': cj.txid,
                'reason': cj.meta.get('failure_reason', 'Unknown'),
                'inputs': cj.meta.get('input_count', 0),
                'outputs': cj.meta.get('output_count', 0),
                'skipped': cj.meta.get('skipped', False)
            })

    return {
        'total_coinjoins': total,
        'solved': solved,
        'unsolved': unsolved,
        'solve_rate': (solved / total * 100) if total > 0 else 0,
        'skipped': skipped,
        'no_solution': no_solution,
        'solution_counts': solution_counts,
        'avg_solutions': sum(solution_counts) / len(solution_counts) if solution_counts else 0,
        'max_solutions': max(solution_counts) if solution_counts else 0,
        'multiple_solutions': sum(1 for c in solution_counts if c > 1),
        'failure_details': failure_details
    }


def compute_solution_count_distribution(blackbox_cj_objs):
    """
    Compute the distribution of solution counts across transactions.

    Returns a table showing how many transactions have ≤N solutions for various N values.
    Example buckets: 1, 2, 4, 10, 100, 1000

    Args:
        blackbox_cj_objs: List of blackbox CoinJoin objects with num_solutions metadata

    Returns:
        List of dicts with keys: bucket, count, cumulative_count, cumulative_pct
    """
    # Extract solution counts from solved transactions
    solution_counts = []
    for cj in blackbox_cj_objs:
        if cj.meta.get('sudoku_solved', False):
            num_solutions = cj.meta.get('num_solutions', 0)
            solution_counts.append(num_solutions)

    if not solution_counts:
        return []

    # Define bucket boundaries
    buckets = [1, 2, 4, 10, 100, 1000, 10000]

    total_txs = len(solution_counts)
    distribution = []

    for bucket in buckets:
        count = sum(1 for s in solution_counts if s <= bucket)
        cumulative_pct = (count / total_txs * 100) if total_txs > 0 else 0

        distribution.append({
            'bucket': bucket,
            'count': count,
            'cumulative_pct': round(cumulative_pct, 2)
        })

    # Add total row
    distribution.append({
        'bucket': 'Total',
        'count': total_txs,
        'cumulative_pct': 100.0
    })

    return distribution


def compute_metrics_by_solution_count(blackbox_cj_objs, whitebox_cj_objs):
    """
    Compute taker matching metrics stratified by solution count.

    Uses the same definition as overall Taker Sensitivity:
    "% of TXs where exactly 1 taker was correctly matched"

    This shows how sudoku solver performance varies based on the number of solutions:
    - Transactions with 1 solution (unambiguous)
    - Transactions with 2-4 solutions (low ambiguity)
    - Transactions with 5-10 solutions (medium ambiguity)
    - Transactions with 11-100 solutions (high ambiguity)
    - Transactions with >100 solutions (very high ambiguity)

    Args:
        blackbox_cj_objs: List of blackbox CoinJoin objects
        whitebox_cj_objs: List of whitebox CoinJoin objects (ground truth)

    Returns:
        List of dicts with keys: bucket, tx_count, taker_match_rate
    """
    # Define solution count buckets
    buckets = [
        (1, 1, "1 solution"),
        (2, 4, "2-4 solutions"),
        (5, 10, "5-10 solutions"),
        (11, 100, "11-100 solutions"),
        (101, float('inf'), ">100 solutions")
    ]

    # Build txid -> num_solutions mapping
    txid_to_solutions = {}
    for cj in blackbox_cj_objs:
        if cj.meta.get('sudoku_solved', False):
            txid_to_solutions[cj.txid] = cj.meta.get('num_solutions', 0)

    # Build txid maps for quick lookup
    bb_txid_map = {cj.txid: cj for cj in blackbox_cj_objs}
    wb_txid_map = {cj.txid: cj for cj in whitebox_cj_objs}

    # Find common transactions
    common_txids = set(bb_txid_map.keys()) & set(wb_txid_map.keys())

    results = []

    for min_sol, max_sol, label in buckets:
        # Filter transactions in this bucket
        bucket_txids = [
            txid for txid in common_txids
            if txid in txid_to_solutions and min_sol <= txid_to_solutions[txid] <= max_sol
        ]

        if not bucket_txids:
            continue

        # For each transaction, check if exactly 1 taker was correctly matched
        # This matches the definition of overall "Taker Sensitivity"
        taker_matched_count = 0

        for txid in bucket_txids:
            bb_cj = bb_txid_map[txid]
            wb_cj = wb_txid_map[txid]

            # Get taker input sets from both analyses
            bb_taker_inputs = set()
            for participant in bb_cj.participants:
                if getattr(participant, 'role', None) == 'taker':
                    for inp in participant.inputs:
                        # Use (txid, vout) tuple to uniquely identify inputs
                        bb_taker_inputs.add((getattr(inp, 'txid', None), getattr(inp, 'vout', None)))

            wb_taker_inputs = set()
            for participant in wb_cj.participants:
                if getattr(participant, 'role', None) == 'taker':
                    for inp in participant.inputs:
                        input_id = (getattr(inp, 'txid', None), getattr(inp, 'vout', None))
                        wb_taker_inputs.add(input_id)

            # Check if taker was correctly matched (all taker inputs match exactly)
            if bb_taker_inputs and wb_taker_inputs and bb_taker_inputs == wb_taker_inputs:
                taker_matched_count += 1

        # Calculate taker match rate (same as taker sensitivity)
        taker_match_rate = round(taker_matched_count / len(bucket_txids) * 100, 2) if bucket_txids else None

        results.append({
            'bucket': label,
            'tx_count': len(bucket_txids),
            'taker_match_rate': taker_match_rate,
            'taker_matched_count': taker_matched_count
        })

    return results

def aggregate_txid_comparison(blackbox_results, whitebox_data):
    return generate_comparison_data(blackbox_results, whitebox_data)

def aggregate_object_comparison(blackbox_cj_objs, whitebox_cj_objs):
    obj_comparison_data = generate_object_comparison(blackbox_cj_objs, whitebox_cj_objs, detailed=True)
    for tx in obj_comparison_data.get("obj_comparison", []):
        txid = tx["txid"]
        tx["wb_taker_clients"] = get_taker_identities(whitebox_cj_objs, txid)
        tx["bb_taker_clients"] = get_taker_identities(blackbox_cj_objs, txid)

    # Compute BB↔WB taker client mapping metrics across the entire dataset
    taker_metrics = compute_taker_client_mapping_metrics(obj_comparison_data.get("obj_comparison", []))
    obj_comparison_data.update(taker_metrics)

    return obj_comparison_data


def get_taker_identities(cj_objs, txid):
    # Find the CoinJoin object for this transaction
    cj = next((cj for cj in cj_objs if cj.txid == txid), None)

    if not cj or not hasattr(cj, 'participants'):
        return "Unknown"

    taker_clients = []
    for participant in cj.participants:
        if getattr(participant, 'role', None) == 'taker':
            if hasattr(participant, 'client') and participant.client:
                taker_clients.append(participant.client)

    return ", ".join(taker_clients) if taker_clients else "None"

def _parse_single_client_id(id_str: Optional[str]) -> Optional[str]:
    """Return a single client id if the string represents exactly one client; otherwise None.

    Rules:
    - Accept non-empty single client id (no comma), not equal to "Unknown" or "None".
    - If multiple clients are present (comma-separated), return None (skip occurrence).
    """
    if not id_str:
        return None
    s = id_str.strip()
    if not s or s in ("Unknown", "None"):
        return None
    # If comma present, treat as multiple clients => skip
    if "," in s:
        return None
    return s

def compute_taker_client_mapping_metrics(per_tx_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute mapping consistency metrics using obj_comparison per-tx entries.

    Primary metric (occurrence-level): For each BB client, after establishing the first
    BB→WB mapping (by first valid occurrence), count subsequent valid occurrences as
    consistent if they map to the same WB client, inconsistent otherwise.

    Secondary metric (client-level): Percentage of BB clients that never remap after
    the first mapping.

    Also compute the ratio of unique WB to unique BB taker clients over valid occurrences.
    """
    # Ensure deterministic order (by block height then txid if available)
    txs = sorted(per_tx_list, key=lambda x: (x.get("block_height", 0), x.get("txid", "")))

    bb_first_map: dict[str, str] = {}
    bb_inconsistent: set[str] = set()
    clients_mapped: set[str] = set()

    occ_total = 0
    occ_consistent = 0

    unique_bb: set[str] = set()
    unique_wb: set[str] = set()

    for tx in txs:
        bb_id = _parse_single_client_id(tx.get("bb_taker_clients"))
        wb_id = _parse_single_client_id(tx.get("wb_taker_clients"))
        # Skip ambiguous or unmapped cases per requirements
        if not bb_id or not wb_id:
            continue

        unique_bb.add(bb_id)
        unique_wb.add(wb_id)

        if bb_id not in bb_first_map:
            bb_first_map[bb_id] = wb_id
            clients_mapped.add(bb_id)
        else:
            occ_total += 1
            if wb_id == bb_first_map[bb_id]:
                occ_consistent += 1
            else:
                bb_inconsistent.add(bb_id)

    client_total = len(clients_mapped)
    client_consistent_count = client_total - len(bb_inconsistent)

    # Occurrence-level percentage: if there were no post-first occurrences but at least
    # one client mapped, treat as perfectly consistent (100.0). If no clients, None.
    if occ_total > 0:
        occ_pct = round(occ_consistent / max(occ_total, 1) * 100, 2)
    else:
        occ_pct = 100.0 if client_total > 0 else None

    client_pct = round(client_consistent_count / max(client_total, 1) * 100, 2) if client_total > 0 else None

    ratio = round(len(unique_wb) / max(len(unique_bb), 1), 4) if (unique_bb or unique_wb) else None

    return {
        "taker_mapping_occurrence_consistency": occ_pct,
        "taker_mapping_client_consistency": client_pct,
        "taker_client_wb_bb_ratio": ratio,
    }

def aggregate_participant_breakdown(obj_comparison_data, whitebox_cj_objs):
    detailed_participant_breakdown = []
    for tx in obj_comparison_data.get("obj_comparison", []):
        wb_cj = next((cj for cj in whitebox_cj_objs if cj.txid == tx["txid"]), None)
        taker_client = "Unknown"
        if wb_cj and hasattr(wb_cj, 'participants'):
            for participant in wb_cj.participants:
                if getattr(participant, 'role', None) == 'taker':
                    if hasattr(participant, 'client'):
                        taker_client = participant.client
                        break
        for part in tx.get("participant_breakdown", []):
            entry = {
                "txid": tx["txid"],
                "block_height": tx["block_height"],
                "bb_sig": str(part["bb_sig"]),
                "bb_role": part["bb_role"],
                "wb_roles": ", ".join(part["wb_roles"]),
                "role_match": part["role_match"],
                "taker_client": taker_client
            }
            detailed_participant_breakdown.append(entry)
    return detailed_participant_breakdown


def aggregate_chain_stats(blackbox_cj_objs, whitebox_cj_objs):
    """
    Aggregate chain statistics.

    For blackbox: Use orchestrator for iterative refinement (connection discovery).
    For whitebox: Use traditional flow (already has ground truth, no discovery needed).
    """
    orchestrator = ChainAnalysisOrchestrator()

    # Blackbox: Run iterative chain analysis with refinement
    # This discovers additional connections missed during initial chain building
    blackbox_identified_chains = orchestrator.analyze_with_refinement(
        blackbox_cj_objs, 'blackbox'
    )

    # Whitebox: Use traditional flow (identify + attribute)
    # Whitebox already has ground truth, orchestrator would incorrectly merge independent chains
    print(f"\n=== Chain Analysis (whitebox) ===")
    print(f"Chain identification and attribution...")
    whitebox_identified_chains = identify_coinjoin_chains(whitebox_cj_objs, 'whitebox')
    print(f"  Found {len(whitebox_identified_chains)} chains")

    attributor = ChainBasedAttributor()
    for chain in whitebox_identified_chains:
        attributor.attribute_chain(chain)

    # Restore unassigned outputs for comparison phase
    orchestrator._restore_unassigned_outputs(whitebox_cj_objs)
    print(f"=== Analysis complete ===\n")

    # Extract transaction IDs from chains (filter out single-transaction chains for blackbox)
    blackbox_chain_txids = sorted({
        node.txid
        for chain in blackbox_identified_chains
        if chain.length() > 1  # Only include chains with more than 1 transaction
        for node in chain.nodes
    })
    whitebox_chain_txids = sorted({node.txid for chain in whitebox_identified_chains for node in chain.nodes})

    all_plain_txids = sorted({cj.txid for cj in blackbox_cj_objs + whitebox_cj_objs})
    unattributed_in_blackbox = sorted(set(all_plain_txids) - set(blackbox_chain_txids))
    unattributed_in_whitebox = sorted(set(all_plain_txids) - set(whitebox_chain_txids))
    txid_lists = {
        'all_plain_txids': ', '.join(all_plain_txids),
        'blackbox_chain_txids': ', '.join(blackbox_chain_txids),
        'whitebox_chain_txids': ', '.join(whitebox_chain_txids),
        'unattributed_in_blackbox': ', '.join(unattributed_in_blackbox),
        'unattributed_in_whitebox': ', '.join(unattributed_in_whitebox)
    }
    return blackbox_identified_chains, whitebox_identified_chains, txid_lists

def aggregate_chain_comparison_summary(blackbox_identified_chains, whitebox_identified_chains):
    chain_comparison_summary = compare_coinjoin_chains(blackbox_identified_chains, whitebox_identified_chains)
    return convert_frozensets(chain_comparison_summary)

def aggregate_colored_tree_comparisons(chain_comparison_summary, chain_map):
    matched_pairs_details = chain_comparison_summary.get('matched_chain_pairs', [])
    for pair in matched_pairs_details:
        bb_chain_id = pair['blackbox_chain_id']
        wb_chain_id = pair['whitebox_chain_id']
        if bb_chain_id in chain_map and wb_chain_id in chain_map:
            bb_chain = chain_map[bb_chain_id]
            wb_chain = chain_map[wb_chain_id]
            pair['colored_tree_comparison'] = generate_colored_chain_comparison(bb_chain, wb_chain)
    return matched_pairs_details

def _single_taker_for_txid(cj_objs, txid: str) -> Optional[str]:
    return _parse_single_client_id(get_taker_identities(cj_objs, txid))

def compute_chain_root_mapping_consistency(
    chain_comparison_summary: Dict[str, Any],
    chain_map: Dict[str, Any],
    blackbox_cj_objs: List[Any],
    whitebox_cj_objs: List[Any],
) -> Dict[str, Any]:
    """Compute chain-based taker root-mapping metrics using BFS traversal.

    Process per matched chain pair (WB↔BB):
    - Traverse the WB chain in BFS order.
    - Establish wb_root_identity from the WB chain's ultimate root (pick among WB root_nodes by
      earliest WB block height). Use the WB taker at that root txid; if missing, set
      wb_root_identity = 'UNATTRIBUTABLE'.
    - Establish bb_root_identity when first WB↔BB mapping is encountered during traversal; if BB taker
      exists at the ultimate WB root txid, use that immediately as bb_root_identity.
    - Count all visited WB nodes (and leaves) into totals regardless of BB mapping availability.
    - When encountering the first node with both WB and BB single takers, set bb_root_identity.
    - Compute two metric families (for nodes and leaves):
      a) identification coverage: fraction of WB nodes whose BB taker matches the
         established bb_root_identity (i.e., identified as part of the same chain taker).
      b) strict consistency: fraction of WB nodes where both takers are present AND equal to their roots
         (bb_id == bb_root AND wb_id == wb_root). If bb_root was never established, strict consistency
         cannot be evaluated and such nodes are ignored.
    """
    matched = chain_comparison_summary.get('matched_chain_pairs', []) or []
    if not matched:
        return {
            'chain_identification_coverage_nodes': None,
            'chain_identification_coverage_leaves': None,
            'chain_identification_specificity_nodes': None,
            'chain_identification_specificity_leaves': None,
            'chain_root_mapping_strict_consistency_nodes': None,
            'chain_root_mapping_strict_consistency_leaves': None,
        }

    # Global aggregates across all matched pairs
    node_total = 0                 # total WB nodes visited
    leaf_total = 0                 # total WB leaf nodes visited
    node_identified = 0            # WB nodes with any BB taker identified
    leaf_identified = 0            # WB leaf nodes with any BB taker identified
    node_strict_consistent = 0     # WB nodes strictly consistent with roots
    leaf_strict_consistent = 0     # WB leaves strictly consistent with roots

    # Cross-chain specificity: track BB root identities and which WB chains they map to
    # This will detect if BB merges multiple distinct WB chains into one BB identity
    bb_to_wb_chains = {}           # {bb_root_identity: [list of wb_chain_ids]}
    wb_chain_has_bb_root = {}      # {wb_chain_id: bb_root_identity or None}

    for pair in matched:
        bb_chain_id = pair.get('blackbox_chain_id')
        wb_chain_id = pair.get('whitebox_chain_id')
        if not bb_chain_id or not wb_chain_id:
            continue

        bb_chain = chain_map.get(bb_chain_id)
        wb_chain = chain_map.get(wb_chain_id)
        if not bb_chain or not wb_chain:
            continue

        wb_root_bb_identity: Optional[str] = None
        wb_root_identity: Optional[str] = None
        bb_root_identity: Optional[str] = None

        # Determine the WB ultimate root txid (by earliest WB block height among WB root nodes)
        wb_roots = list(getattr(wb_chain, 'root_nodes', []) or [])
        if wb_roots:
            # Build quick lookup once for WB heights if not already
            # Note: outside map may not exist anymore; rebuild lightweight here
            wb_height_local = {cj.txid: getattr(cj, 'block_height', 0) for cj in whitebox_cj_objs}
            wb_root_node = min(wb_roots, key=lambda n: (wb_height_local.get(getattr(n, 'txid', None), 0), getattr(n, 'txid', '')))
            root_txid = getattr(wb_root_node, 'txid', None)
            if root_txid:
                # Get the WB root identity (ground truth)
                wb_root_identity = _single_taker_for_txid(whitebox_cj_objs, root_txid)
                wb_root_bb_identity = _single_taker_for_txid(blackbox_cj_objs, root_txid) or 'UNATTRIBUTABLE'
                # If BB taker exists at this root, we can set bb_root immediately
                bb_root_candidate = _single_taker_for_txid(blackbox_cj_objs, root_txid)
                if bb_root_candidate:
                    bb_root_identity = bb_root_candidate

        # BFS over WB chain
        for node in getattr(wb_chain, 'bfs_traverse', lambda: [])():
            txid = getattr(node, 'txid', None)
            if not txid:
                continue

            # WB taker identity for this node
            wb_id = _single_taker_for_txid(whitebox_cj_objs, txid)

            # Count totals regardless of BB mapping
            node_total += 1
            if getattr(node, 'is_leaf', False):
                leaf_total += 1

            # Try to get BB taker
            bb_id = _single_taker_for_txid(blackbox_cj_objs, txid)

            # Set BB root when first BB↔WB mapping encountered (both sides present)
            if bb_root_identity is None and bb_id and wb_id:
                bb_root_identity = bb_id

            # Coverage (Sensitivity): BB taker aligns with established bb_root_identity
            if bb_root_identity and bb_id == bb_root_identity:
                node_identified += 1
                if getattr(node, 'is_leaf', False):
                    leaf_identified += 1

            # Strict consistency check requires both roots established and both sides present
            if wb_root_bb_identity and bb_id:
                if bb_id == wb_root_bb_identity:
                    node_strict_consistent += 1
                    if getattr(node, 'is_leaf', False):
                        leaf_strict_consistent += 1

        # After BFS traversal, store the bb_root_identity for this chain
        if bb_root_identity:
            wb_chain_has_bb_root[wb_chain_id] = bb_root_identity
            bb_to_wb_chains.setdefault(bb_root_identity, []).append(wb_chain_id)

    # Compute cross-chain specificity at chain level
    # Specificity: % of WB chains that BB keeps separate (not merged with other WB chains)
    # False Positive: WB chain that was merged into a BB identity with other WB chains
    # True Negative: WB chain that BB kept separate (1-to-1 mapping)

    total_wb_chains = len(matched)
    true_negatives = 0  # WB chains kept separate by BB
    false_positives = 0 # WB chains merged by BB

    for bb_id, wb_chain_list in bb_to_wb_chains.items():
        if len(wb_chain_list) == 1:
            # BB kept this WB chain separate (1-to-1 mapping)
            true_negatives += 1
        else:
            # BB merged multiple WB chains into one BB identity
            # ALL chains in this group are false positives
            false_positives += len(wb_chain_list)

    # Specificity = True Negatives / Total WB Chains
    # Note: This is the same for nodes and leaves since it's chain-level
    if total_wb_chains > 0:
        chain_specificity = round(true_negatives / total_wb_chains * 100, 2)
    else:
        chain_specificity = None

    # Compute percentages
    coverage_nodes = round(node_identified / max(node_total, 1) * 100, 2) if node_total > 0 else None
    coverage_leaves = round(leaf_identified / max(leaf_total, 1) * 100, 2) if leaf_total > 0 else None
    strict_nodes = round(node_strict_consistent / max(node_total, 1) * 100, 2) if node_total > 0 else None
    strict_leaves = round(leaf_strict_consistent / max(leaf_total, 1) * 100, 2) if leaf_total > 0 else None

    # Cross-chain specificity is the same for nodes and leaves (chain-level metric)
    specificity_nodes = chain_specificity
    specificity_leaves = chain_specificity

    return {
        'chain_identification_coverage_nodes': coverage_nodes,
        'chain_identification_coverage_leaves': coverage_leaves,
        'chain_identification_specificity_nodes': specificity_nodes,
        'chain_identification_specificity_leaves': specificity_leaves,
        'chain_root_mapping_strict_consistency_nodes': strict_nodes,
        'chain_root_mapping_strict_consistency_leaves': strict_leaves,
    }

def compute_taker_cj_output_attribution_metrics(
    blackbox_cj_objs: List[Any],
    whitebox_cj_objs: List[Any],
    blackbox_chains: List[Any],
    whitebox_chains: List[Any],
) -> Dict[str, Any]:
    """Compute metrics for taker CoinJoin output attribution after chain attribution.

    Measures two aspects:
    1. Coverage: What percentage of taker participants have their cj_output successfully attributed?
    2. Accuracy: How well does blackbox attribution match whitebox ground truth?

    Args:
        blackbox_cj_objs: CoinJoin objects from blackbox analysis (after chain attribution)
        whitebox_cj_objs: CoinJoin objects from whitebox analysis (after chain attribution)
        blackbox_chains: Identified chains from blackbox analysis
        whitebox_chains: Identified chains from whitebox analysis

    Returns:
        Dictionary with coverage and accuracy metrics
    """

    # Coverage metrics for blackbox
    bb_total_takers = 0
    bb_attributed_takers = 0

    for cj in blackbox_cj_objs:
        for participant in getattr(cj, 'participants', []) or []:
            if getattr(participant, 'role', None) == 'taker':
                bb_total_takers += 1
                if getattr(participant, 'cj_output', None) is not None:
                    bb_attributed_takers += 1

    # Coverage metrics for whitebox
    wb_total_takers = 0
    wb_attributed_takers = 0

    for cj in whitebox_cj_objs:
        for participant in getattr(cj, 'participants', []) or []:
            if getattr(participant, 'role', None) == 'taker':
                wb_total_takers += 1
                if getattr(participant, 'cj_output', None) is not None:
                    wb_attributed_takers += 1

    # Calculate coverage percentages
    bb_coverage = round(bb_attributed_takers / max(bb_total_takers, 1) * 100, 2) if bb_total_takers > 0 else None
    wb_coverage = round(wb_attributed_takers / max(wb_total_takers, 1) * 100, 2) if wb_total_takers > 0 else None

    # Accuracy metrics: compare BB vs WB for common transactions
    common_txids = {getattr(cj, 'txid', None) for cj in blackbox_cj_objs} & \
                   {getattr(cj, 'txid', None) for cj in whitebox_cj_objs}
    common_txids.discard(None)

    bb_txid_map = {getattr(cj, 'txid', None): cj for cj in blackbox_cj_objs}
    wb_txid_map = {getattr(cj, 'txid', None): cj for cj in whitebox_cj_objs}

    attribution_matches = 0
    attribution_total = 0

    # Specificity tracking: maker outputs (negative class)
    attribution_negatives_total = 0
    attribution_true_negatives = 0

    for txid in common_txids:
        bb_cj = bb_txid_map.get(txid)
        wb_cj = wb_txid_map.get(txid)

        if not bb_cj or not wb_cj:
            continue

        # Get taker cj_output attributions from both analyses
        bb_taker_outputs = set()
        wb_taker_outputs = set()
        wb_maker_outputs = set()

        for participant in getattr(bb_cj, 'participants', []) or []:
            if getattr(participant, 'role', None) == 'taker':
                cj_out = getattr(participant, 'cj_output', None)
                if cj_out is not None:
                    output_n = getattr(cj_out, 'n', None)
                    if output_n is not None:
                        bb_taker_outputs.add(output_n)

        for participant in getattr(wb_cj, 'participants', []) or []:
            if getattr(participant, 'role', None) == 'taker':
                cj_out = getattr(participant, 'cj_output', None)
                if cj_out is not None:
                    output_n = getattr(cj_out, 'n', None)
                    if output_n is not None:
                        wb_taker_outputs.add(output_n)
            elif getattr(participant, 'role', None) == 'maker':
                # Track maker outputs (negative class)
                cj_out = getattr(participant, 'cj_output', None)
                if cj_out is not None:
                    output_n = getattr(cj_out, 'n', None)
                    if output_n is not None:
                        wb_maker_outputs.add(output_n)

        # Count matches: outputs attributed as taker in both BB and WB (Sensitivity)
        if wb_taker_outputs:  # Only count if WB has attributions (ground truth)
            for output_n in wb_taker_outputs:
                attribution_total += 1
                if output_n in bb_taker_outputs:
                    attribution_matches += 1

        # Count true negatives: maker outputs correctly NOT labeled as taker in BB (Specificity)
        if wb_maker_outputs:
            for output_n in wb_maker_outputs:
                attribution_negatives_total += 1
                if output_n not in bb_taker_outputs:
                    # BB correctly did NOT label this maker output as taker
                    attribution_true_negatives += 1

    # Calculate accuracy (sensitivity) percentage
    attribution_accuracy = round(attribution_matches / max(attribution_total, 1) * 100, 2) \
                          if attribution_total > 0 else None

    # Calculate specificity percentage
    attribution_specificity = round(attribution_true_negatives / max(attribution_negatives_total, 1) * 100, 2) \
                             if attribution_negatives_total > 0 else None

    return {
        'taker_cj_output_coverage_bb': bb_coverage,
        'taker_cj_output_coverage_wb': wb_coverage,
        'taker_cj_output_attribution_accuracy': attribution_accuracy,
        'taker_cj_output_attribution_specificity': attribution_specificity,
        'taker_cj_output_details': {
            'bb_attributed_count': bb_attributed_takers,
            'bb_total_takers': bb_total_takers,
            'wb_attributed_count': wb_attributed_takers,
            'wb_total_takers': wb_total_takers,
            'common_tx_attribution_matches': attribution_matches,
            'common_tx_attribution_total': attribution_total,
            'common_tx_attribution_true_negatives': attribution_true_negatives,
            'common_tx_attribution_negatives_total': attribution_negatives_total,
        }
    }


def compute_sole_taker_cj_output_attribution_metrics(
    blackbox_cj_objs: List[Any],
    whitebox_cj_objs: List[Any],
    sole_taker_clients: set[str],
) -> Dict[str, Any] | None:
    """Compute CJ output attribution metrics for sole takers only.

    Sole takers are takers that are:
    - NOT tumblers (no TUMBLE.log in logs/)
    - NOT makers (no yigen-statement.csv in logs/)

    This metric helps evaluate blackbox performance on standard single-transaction takers.

    Args:
        blackbox_cj_objs: CoinJoin objects from blackbox analysis (after chain attribution)
        whitebox_cj_objs: CoinJoin objects from whitebox analysis (after chain attribution)
        sole_taker_clients: Set of client IDs identified as sole takers

    Returns:
        Dictionary with sensitivity and specificity metrics, or None if no sole takers found
    """
    # Return None if no sole takers present
    if not sole_taker_clients:
        return None

    # Find transactions involving sole takers
    common_txids = {getattr(cj, 'txid', None) for cj in blackbox_cj_objs} & \
                   {getattr(cj, 'txid', None) for cj in whitebox_cj_objs}
    common_txids.discard(None)

    bb_txid_map = {getattr(cj, 'txid', None): cj for cj in blackbox_cj_objs}
    wb_txid_map = {getattr(cj, 'txid', None): cj for cj in whitebox_cj_objs}

    attribution_matches = 0
    attribution_total = 0

    # Specificity tracking: maker outputs (negative class)
    attribution_negatives_total = 0
    attribution_true_negatives = 0

    # Track sole taker participation count
    sole_taker_tx_count = 0

    for txid in common_txids:
        bb_cj = bb_txid_map.get(txid)
        wb_cj = wb_txid_map.get(txid)

        if not bb_cj or not wb_cj:
            continue

        # Check if this transaction has any sole taker participants
        has_sole_taker = False
        for participant in getattr(wb_cj, 'participants', []) or []:
            client_id = getattr(participant, 'client', None)
            if client_id in sole_taker_clients:
                has_sole_taker = True
                break

        # Skip this transaction if no sole takers involved
        if not has_sole_taker:
            continue

        sole_taker_tx_count += 1

        # Get taker cj_output attributions from both analyses
        # BB: Get ALL taker outputs (don't filter by client - BB might not have reliable client IDs)
        # WB: Get sole taker outputs AND all maker outputs for specificity
        bb_taker_outputs = set()
        wb_sole_taker_outputs = set()
        wb_all_maker_outputs = set()

        # BB: Collect all taker outputs without filtering by client
        for participant in getattr(bb_cj, 'participants', []) or []:
            if getattr(participant, 'role', None) == 'taker':
                cj_out = getattr(participant, 'cj_output', None)
                if cj_out is not None:
                    output_n = getattr(cj_out, 'n', None)
                    if output_n is not None:
                        bb_taker_outputs.add(output_n)

        # WB: Collect sole taker outputs and ALL maker outputs
        for participant in getattr(wb_cj, 'participants', []) or []:
            client_id = getattr(participant, 'client', None)
            role = getattr(participant, 'role', None)
            cj_out = getattr(participant, 'cj_output', None)

            if cj_out is not None:
                output_n = getattr(cj_out, 'n', None)
                if output_n is not None:
                    # Collect sole taker outputs (for sensitivity)
                    if client_id in sole_taker_clients and role == 'taker':
                        wb_sole_taker_outputs.add(output_n)

                    # Collect ALL maker outputs (for specificity)
                    if role == 'maker':
                        wb_all_maker_outputs.add(output_n)

        # Count matches: sole taker outputs attributed as taker in both BB and WB (Sensitivity)
        if wb_sole_taker_outputs:  # Only count if WB has sole taker attributions (ground truth)
            for output_n in wb_sole_taker_outputs:
                attribution_total += 1
                if output_n in bb_taker_outputs:
                    attribution_matches += 1

        # Count true negatives: maker outputs correctly NOT labeled as taker in BB (Specificity)
        # In transactions with sole takers, check if BB correctly avoided labeling makers as takers
        if wb_all_maker_outputs:
            for output_n in wb_all_maker_outputs:
                attribution_negatives_total += 1
                if output_n not in bb_taker_outputs:
                    # BB correctly did NOT label this maker output as taker
                    attribution_true_negatives += 1

    # Handle case where no transactions involved sole takers
    if attribution_total == 0 and attribution_negatives_total == 0:
        return None

    # Calculate accuracy (sensitivity) percentage
    attribution_accuracy = round(attribution_matches / max(attribution_total, 1) * 100, 2) \
                          if attribution_total > 0 else None

    # Calculate specificity percentage
    attribution_specificity = round(attribution_true_negatives / max(attribution_negatives_total, 1) * 100, 2) \
                             if attribution_negatives_total > 0 else None

    return {
        'sole_taker_cj_output_attribution_accuracy': attribution_accuracy,
        'sole_taker_cj_output_attribution_specificity': attribution_specificity,
        'sole_taker_count': len(sole_taker_clients),
        'sole_taker_tx_count': sole_taker_tx_count,
        'sole_taker_details': {
            'attribution_matches': attribution_matches,
            'attribution_total': attribution_total,
            'attribution_true_negatives': attribution_true_negatives,
            'attribution_negatives_total': attribution_negatives_total,
        }
    }


def aggregate_tx_statistics(whitebox_cj_objs, blackbox_cj_objs):
    all_tx_stats = []
    seen_txids = set()
    def count_tx_inputs(tx_data):
        return len(tx_data.get('vin', []))
    def count_tx_outputs(tx_data):
        return len(tx_data.get('vout', []))
    for cj in whitebox_cj_objs + blackbox_cj_objs:
        if cj.txid in seen_txids:
            continue
        seen_txids.add(cj.txid)
        input_count = count_tx_inputs(cj.tx)
        output_count = count_tx_outputs(cj.tx)

        # Determine solve status (for blackbox only)
        is_blackbox = cj in blackbox_cj_objs
        solve_status = None
        num_solutions = None
        if is_blackbox:
            if cj.meta.get('skipped', False):
                solve_status = 'Skipped'
            elif cj.meta.get('sudoku_solved', False):
                solve_status = 'Solved'
                num_solutions = cj.meta.get('num_solutions', 1)
            else:
                solve_status = 'Unsolved'
                num_solutions = 0

        # Estimate participant count for unsolved (output_count // 2)
        participant_count = len(cj.participants) if cj.participants else (output_count // 2)
        inputs_per_participant = input_count / participant_count if participant_count > 0 else 0

        # Check if taker CJ output attribution was attempted via chain analysis
        # Only count as "attributed" if confidence is high (>0.5), indicating chain-based attribution
        # Low confidence (<0.5) means it was just arbitrarily restored after prepare_for_attribution
        taker_cj_output_attributed = False
        if cj.participants:
            # Check if any taker has cj_output with high confidence (chain-attributed)
            takers = [p for p in cj.participants if getattr(p, 'role', None) == 'taker']
            if takers:
                taker_cj_output_attributed = any(
                    hasattr(p, 'cj_output') and p.cj_output is not None
                    and getattr(p.cj_output, 'confidence', 0) > 0.5
                    for p in takers
                )

        tx_stats = {
            'txid': cj.txid,
            'block_height': cj.block_height,
            'input_count': input_count,
            'output_count': output_count,
            'cj_amount': cj.cj_amount,
            'participant_count': participant_count,
            'inputs_per_participant': inputs_per_participant,
            'solve_status': solve_status,
            'num_solutions': num_solutions,
            'taker_cj_output_attributed': taker_cj_output_attributed,
            'analysis_type': 'whitebox' if cj in whitebox_cj_objs else 'blackbox'
        }
        all_tx_stats.append(tx_stats)
    if all_tx_stats:
        tx_stats_df = pd.DataFrame(all_tx_stats)
        input_stats = {
            'total': tx_stats_df['input_count'].sum(),
            'mean': tx_stats_df['input_count'].mean(),
            'median': tx_stats_df['input_count'].median(),
            'min': tx_stats_df['input_count'].min(),
            'max': tx_stats_df['input_count'].max(),
            'std': tx_stats_df['input_count'].std()
        }
        output_stats = {
            'total': tx_stats_df['output_count'].sum(),
            'mean': tx_stats_df['output_count'].mean(),
            'median': tx_stats_df['output_count'].median(),
            'min': tx_stats_df['output_count'].min(),
            'max': tx_stats_df['output_count'].max(),
            'std': tx_stats_df['output_count'].std()
        }

        # Compute stats by solve status (for blackbox only)
        blackbox_stats = tx_stats_df[tx_stats_df['analysis_type'] == 'blackbox']
        solve_status_stats = {}
        if len(blackbox_stats) > 0:
            for status in ['Solved', 'Skipped', 'Unsolved']:
                status_df = blackbox_stats[blackbox_stats['solve_status'] == status]
                if len(status_df) > 0:
                    taker_attributed_count = status_df['taker_cj_output_attributed'].sum()
                    solve_status_stats[status] = {
                        'count': len(status_df),
                        'avg_inputs': status_df['input_count'].mean(),
                        'avg_participants': status_df['participant_count'].mean(),
                        'avg_inputs_per_participant': status_df['inputs_per_participant'].mean(),
                        'taker_cj_output_attributed_count': int(taker_attributed_count),
                        'taker_cj_output_attribution_rate': (taker_attributed_count / len(status_df) * 100) if len(status_df) > 0 else 0
                    }

        return input_stats, output_stats, all_tx_stats, solve_status_stats
    else:
        return None, None, [], {}

def aggregate_detailed_cj_objects(whitebox_cj_objs, blackbox_cj_objs, show_block_timestamps=False):
    detailed_cj_objects = []
    def participant_details(participant):
        # Safely compute output totals without assuming cj_output is always present
        cj_val = None
        cj_obj = getattr(participant, "cj_output", None)
        if cj_obj is not None:
            cj_val = getattr(cj_obj, "value", None)

        ch_val = None
        ch_obj = getattr(participant, "change_output", None)
        if ch_obj is not None:
            ch_val = getattr(ch_obj, "value", None)

        # Preferred: sum of known outputs when cj_output is available
        output_total = None
        if cj_val is not None:
            output_total = (cj_val or 0) + ((ch_val or 0) if ch_val is not None else 0)
        else:
            # Fallback: derive from inputs and delta if available
            try:
                input_total = getattr(participant, "input_value", None)
            except Exception:
                input_total = None
            delta_val = getattr(participant, "delta", None)
            if input_total is not None and delta_val is not None:
                output_total = input_total + delta_val

        part_details = {
            "role": getattr(participant, "role", None),
            "client": getattr(participant, "client", None) or "Unknown",
            "input_value": getattr(participant, "input_value", None),
            # Use our safe total; template will format None as N/A
            "output_value": output_total,
            "delta": getattr(participant, "delta", None),
            "inputs": [
                {
                    "txid": getattr(inp, "txid", None),
                    "vout": getattr(inp, "vout", None),
                    "value": getattr(inp, "value", None),
                    "address": getattr(inp, "address", None) or "Unknown",
                    "client": getattr(inp, "client", None) or "Unknown"
                }
                for inp in getattr(participant, "inputs", [])
            ],
            "cj_output": {
                "n": getattr(getattr(participant, "cj_output", None), "n", None),
                "value": getattr(getattr(participant, "cj_output", None), "value", None),
                "address": getattr(getattr(participant, "cj_output", None), "address", None) or "Unknown",
                "client": getattr(getattr(participant, "cj_output", None), "client", None) or "Unknown"
            }
        }
        if getattr(participant, "change_output", None):
            part_details["change_output"] = {
                "n": getattr(participant.change_output, "n", None),
                "value": getattr(participant.change_output, "value", None),
                "address": getattr(participant.change_output, "address", None) or "Unknown",
                "client": getattr(participant.change_output, "client", None) or "Unknown"
            }
        return part_details
    def cj_details(cj, analysis_type):
        details = {
            "txid": getattr(cj, "txid", None),
            "block_height": getattr(cj, "block_height", None),
            "cj_amount": getattr(cj, "cj_amount", None),
            "miner_fee": getattr(cj, "miner_fee", None),
            "analysis_type": analysis_type,
            "participants": [participant_details(p) for p in getattr(cj, "participants", [])]
        }
        # Add block timestamp if enabled and available in the transaction data
        if show_block_timestamps:
            tx_data = getattr(cj, "tx", {})
            # The block data should be available through the tx_map structure
            # Try to get the timestamp from the transaction's block reference
            if isinstance(tx_data, dict):
                # Check if we have access to block data through the CoinJoin object
                # The timestamp might be in cj.tx or we need to look at the block
                block_time = None
                # Try to extract from metadata first
                if hasattr(cj, 'meta') and isinstance(cj.meta, dict):
                    block_time = cj.meta.get('block_time')
                # If not in meta, try to get from tx structure (if it has block reference)
                if block_time is None and 'block' in tx_data:
                    block_time = tx_data.get('block', {}).get('time')
                details["block_timestamp"] = block_time
        return details
    for cj in whitebox_cj_objs:
        detailed_cj_objects.append(cj_details(cj, "whitebox"))
    for cj in blackbox_cj_objs:
        detailed_cj_objects.append(cj_details(cj, "blackbox"))
    detailed_cj_objects.sort(key=lambda x: x["block_height"])
    return detailed_cj_objects

def convert_frozensets(obj):
    if isinstance(obj, dict):
        return {k: convert_frozensets(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_frozensets(v) for v in obj]
    elif isinstance(obj, tuple):
        return [convert_frozensets(v) for v in obj]
    elif isinstance(obj, frozenset):
        return sorted([convert_frozensets(v) for v in obj])
    elif hasattr(obj, '__dict__'):
        return convert_frozensets(vars(obj))
    else:
        try:
            import json
            json.dumps(obj)
            return obj
        except TypeError:
            return str(obj)

def avg_maker_fee(cj_objs):
    maker_fees = [
        sum(p.delta for p in getattr(cj, 'participants', []) if getattr(p, 'delta', 0) > 0)
        for cj in cj_objs
    ]
    return round(sum(maker_fees) / max(len(cj_objs), 1), 8)

def aggregate_coinjoin_object_stats(cj_objs):
    total_transactions = len(cj_objs)
    total_participants = sum(len(cj.participants) for cj in cj_objs)
    avg_participants = round(total_participants / max(total_transactions, 1), 2)
    avg_fee = avg_maker_fee(cj_objs)
    return {
        'total_transactions': total_transactions,
        'total_participants': total_participants,
        'avg_participants': avg_participants,
        'avg_fee': avg_fee
    }

from jinja2 import Environment, FileSystemLoader, select_autoescape
import os

def build_unified_report_data(
    blackbox_results,
    whitebox_data,
    blackbox_cj_objs,
    whitebox_cj_objs,
    output_dir,
    client_roles=None,
    fidelity_bond_stats=None,
    run_path=None,
    show_block_timestamps=False
):
    """
    Aggregate and process all data for the unified CoinJoin report.
    Returns the report_data dictionary.

    Args:
        blackbox_results: Results from blackbox analysis
        whitebox_data: Results from whitebox analysis
        blackbox_cj_objs: CoinJoin objects from blackbox analysis
        whitebox_cj_objs: CoinJoin objects from whitebox analysis
        output_dir: Output directory for the report
        client_roles: Optional mapping of client_id to role
        fidelity_bond_stats: Optional FidelityBondStats object for JoinMarket FB analysis
        run_path: Optional path to the run directory (for identifying sole takers)
    """
    env = Environment(
        loader=FileSystemLoader(os.path.dirname(__file__) or "."),
        autoescape=select_autoescape()
    )
    report_data = {}
    blackbox_identified_chains, whitebox_identified_chains, txid_lists = aggregate_chain_stats(blackbox_cj_objs, whitebox_cj_objs)

    report_data['txid_comparison'] = aggregate_txid_comparison(blackbox_results, whitebox_data)
    obj_comparison_data = aggregate_object_comparison(blackbox_cj_objs, whitebox_cj_objs)

    report_data['object_comparison'] = obj_comparison_data
    report_data['detailed_participant_breakdown'] = aggregate_participant_breakdown(obj_comparison_data, whitebox_cj_objs)
    chain_map = {chain.id: chain for chain in blackbox_identified_chains + whitebox_identified_chains}
    report_data['blackbox_identified_chains'] = blackbox_identified_chains
    report_data['whitebox_identified_chains'] = whitebox_identified_chains
    report_data['txid_lists'] = txid_lists
    chain_comparison_summary = aggregate_chain_comparison_summary(blackbox_identified_chains, whitebox_identified_chains)
    # Compute chain-based root mapping consistency metrics
    chain_mapping_metrics = compute_chain_root_mapping_consistency(
        chain_comparison_summary=chain_comparison_summary,
        chain_map=chain_map,
        blackbox_cj_objs=blackbox_cj_objs,
        whitebox_cj_objs=whitebox_cj_objs,
    )
    chain_comparison_summary.update(chain_mapping_metrics)
    report_data['chain_comparison_summary'] = chain_comparison_summary

    # Compute taker CoinJoin output attribution metrics
    taker_attribution_metrics = compute_taker_cj_output_attribution_metrics(
        blackbox_cj_objs=blackbox_cj_objs,
        whitebox_cj_objs=whitebox_cj_objs,
        blackbox_chains=blackbox_identified_chains,
        whitebox_chains=whitebox_identified_chains,
    )
    chain_comparison_summary.update(taker_attribution_metrics)

    # Identify sole takers and compute sole taker metrics
    sole_taker_clients = set()
    if run_path:
        sole_taker_clients = identify_sole_takers(run_path)

    if sole_taker_clients:
        sole_taker_metrics = compute_sole_taker_cj_output_attribution_metrics(
            blackbox_cj_objs=blackbox_cj_objs,
            whitebox_cj_objs=whitebox_cj_objs,
            sole_taker_clients=sole_taker_clients,
        )
        if sole_taker_metrics:
            chain_comparison_summary.update(sole_taker_metrics)

    report_data['colored_tree_comparisons'] = aggregate_colored_tree_comparisons(chain_comparison_summary, chain_map)

    # Add detailed blackbox analysis statistics
    report_data['blackbox_analysis_stats'] = aggregate_blackbox_analysis_stats(blackbox_cj_objs)

    # Compute solution count distribution
    report_data['solution_count_distribution'] = compute_solution_count_distribution(blackbox_cj_objs)

    # Compute metrics stratified by solution count
    report_data['metrics_by_solution_count'] = compute_metrics_by_solution_count(blackbox_cj_objs, whitebox_cj_objs)

    input_stats, output_stats, all_tx_stats, solve_status_stats = aggregate_tx_statistics(whitebox_cj_objs, blackbox_cj_objs)
    if input_stats and output_stats:
        report_data['tx_statistics'] = {
            'input_stats': input_stats,
            'output_stats': output_stats,
            'solve_status_stats': solve_status_stats,
            'tx_count': len(all_tx_stats),
            'boxplot_img': '',  # Placeholder for visualization
            'histogram_img': ''
        }
        report_data['tx_stats_list'] = all_tx_stats
    else:
        report_data['tx_statistics'] = None
        report_data['tx_stats_list'] = []
    report_data['detailed_cj_objects'] = aggregate_detailed_cj_objects(whitebox_cj_objs, blackbox_cj_objs, show_block_timestamps)
    report_data['show_block_timestamps'] = show_block_timestamps
    # Add object stats for template compatibility
    report_data['blackbox_obj_stats'] = aggregate_coinjoin_object_stats(blackbox_cj_objs)
    report_data['whitebox_obj_stats'] = aggregate_coinjoin_object_stats(whitebox_cj_objs)

    # Add fidelity bond stats if available (JoinMarket-specific, whitebox only)
    report_data['fidelity_bond_stats'] = fidelity_bond_stats

    return report_data
