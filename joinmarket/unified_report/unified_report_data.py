"""
Helpers for aggregating and building unified CoinJoin report data.
"""
from typing import List, Dict, Any, Optional
import pandas as pd

from joinmarket.common.chain_based_attributor import ChainBasedAttributor
from joinmarket.comparison import generate_comparison_data, generate_object_comparison
from joinmarket.comparison.coinjoin_chain_analysis import (
    serialize_cj_chain_for_report,
    get_identified_chains_and_txids
)
from joinmarket.comparison.compare_coinjoin import compare_coinjoin_chains
from joinmarket.comparison.chain_visualization import generate_colored_chain_comparison

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


def attribute_chains(coinjoin_chains):
    attributor = ChainBasedAttributor()
    for coinjoin_chain in coinjoin_chains:
        attributor.attribute_chain(coinjoin_chain)

def aggregate_chain_stats(blackbox_cj_objs, whitebox_cj_objs):
    blackbox_identified_chains, blackbox_chain_txids = get_identified_chains_and_txids(blackbox_cj_objs, 'blackbox')
    whitebox_identified_chains, whitebox_chain_txids = get_identified_chains_and_txids(whitebox_cj_objs, 'whitebox')

    attribute_chains(blackbox_identified_chains)
    attribute_chains(whitebox_identified_chains)

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
        tx_stats = {
            'txid': cj.txid,
            'block_height': cj.block_height,
            'input_count': input_count,
            'output_count': output_count,
            'cj_amount': cj.cj_amount,
            'participant_count': len(cj.participants),
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
        return input_stats, output_stats, all_tx_stats
    else:
        return None, None, []

def aggregate_detailed_cj_objects(whitebox_cj_objs, blackbox_cj_objs):
    detailed_cj_objects = []
    def participant_details(participant):
        part_details = {
            "role": getattr(participant, "role", None),
            "client": getattr(participant, "client", None) or "Unknown",
            "input_value": getattr(participant, "input_value", None),
            "output_value": getattr(participant, "output_value", None),
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
    output_dir
):
    """
    Aggregate and process all data for the unified CoinJoin report.
    Returns the report_data dictionary.
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
    report_data['chain_comparison_summary'] = chain_comparison_summary
    report_data['colored_tree_comparisons'] = aggregate_colored_tree_comparisons(chain_comparison_summary, chain_map)
    input_stats, output_stats, all_tx_stats = aggregate_tx_statistics(whitebox_cj_objs, blackbox_cj_objs)
    if input_stats and output_stats:
        report_data['tx_statistics'] = {
            'input_stats': input_stats,
            'output_stats': output_stats,
            'tx_count': len(all_tx_stats),
            'boxplot_img': '',  # Placeholder for visualization
            'histogram_img': ''
        }
        report_data['tx_stats_list'] = all_tx_stats
    else:
        report_data['tx_statistics'] = None
        report_data['tx_stats_list'] = []
    report_data['detailed_cj_objects'] = aggregate_detailed_cj_objects(whitebox_cj_objs, blackbox_cj_objs)
    # Add object stats for template compatibility
    report_data['blackbox_obj_stats'] = aggregate_coinjoin_object_stats(blackbox_cj_objs)
    report_data['whitebox_obj_stats'] = aggregate_coinjoin_object_stats(whitebox_cj_objs)
    return report_data
