"""
Module for producing a unified CoinJoin analysis report as a JSON object.
"""
import json
from decimal import Decimal

import numpy as np


class PreciseDecimalEncoder(json.JSONEncoder):
    """Encoder that tags Decimal objects for precise reconstruction"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            # Create a tagged object that we can identify later
            return {
                "__decimal__": True,
                "value": str(obj)
            }
        return super().default(obj)


class PreciseDecimalDecoder(json.JSONDecoder):
    """Decoder that reconstructs tagged Decimal objects"""

    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, obj):
        """Look for our special decimal tags and convert them back"""
        if isinstance(obj, dict) and obj.get("__decimal__") is True:
            # This is one of our tagged Decimal objects
            return Decimal(obj["value"])
        return obj

def convert_numpy_types(obj):
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_numpy_types(v) for v in obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj

def remove_coinjoin_trees(report_data: dict):
    """
    Extract and convert report data to JSON-serializable format, excluding CoinJoin tree objects.
    Includes all the key metrics that are displayed in the HTML report.
    """
    json_ready_data = dict()

    if report_data.get('analysis_config'):
        json_ready_data['analysis_config'] = report_data['analysis_config']

    # TXID comparison data
    json_ready_data['txid_comparison_stats'] = { 
        'blackbox_txids': report_data['txid_comparison']['total_blackbox'],
        'whitebox_txids': report_data['txid_comparison']['total_whitebox'],
        'common_txids': report_data['txid_comparison']['common'],
        'only_blackbox': report_data['txid_comparison']['only_blackbox'],
        'only_whitebox': report_data['txid_comparison']['only_whitebox'],
        'detection_agreement': report_data['txid_comparison']['detection_agreement'],
    }
    
    # Object comparison stats (aggregate level)
    obj_comparison = report_data.get('object_comparison', {})
    json_ready_data['object_comparison_stats'] = {
        'comparison_tx_count': obj_comparison.get('comparison_tx_count'),
        'role_accuracy_avg': obj_comparison.get('role_accuracy_avg'),
        'overall_role_success_avg': obj_comparison.get('overall_role_success_avg'),
        'participant_match_rate': obj_comparison.get('participant_match_rate'),
        'total_bb_participants': obj_comparison.get('total_bb_participants'),
        'total_matched_participants': obj_comparison.get('total_matched_participants'),
        'taker_match_avg': obj_comparison.get('taker_match_avg'),
        'taker_sensitivity_avg': obj_comparison.get('taker_sensitivity_avg'),
        'taker_specificity_avg': obj_comparison.get('taker_specificity_avg'),
        'utxo_accuracy_avg': obj_comparison.get('utxo_accuracy_avg'),
        # Add taker mapping metrics that are shown in HTML
        'taker_mapping_occurrence_consistency': obj_comparison.get('taker_mapping_occurrence_consistency'),
        'taker_mapping_client_consistency': obj_comparison.get('taker_mapping_client_consistency'),
        'taker_client_wb_bb_ratio': obj_comparison.get('taker_client_wb_bb_ratio'),
    }
    
    # Chain comparison summary with attribution metrics
    chain_summary = report_data.get('chain_comparison_summary', {})
    json_ready_data['chain_comparison_summary'] = {
        'total_blackbox_chains': chain_summary.get('total_blackbox_chains'),
        'total_whitebox_chains': chain_summary.get('total_whitebox_chains'),
        'singleton_blackbox_chains': chain_summary.get('singleton_blackbox_chains'),
        'singleton_whitebox_chains': chain_summary.get('singleton_whitebox_chains'),
        'num_matched_pairs': chain_summary.get('num_matched_pairs'),
        'num_fully_matched_pairs': chain_summary.get('num_fully_matched_pairs'),
        'num_partially_matched_pairs': chain_summary.get('num_partially_matched_pairs'),
        # Add chain identification coverage (sensitivity) metrics
        'chain_identification_coverage_nodes': chain_summary.get('chain_identification_coverage_nodes'),
        'chain_identification_coverage_leaves': chain_summary.get('chain_identification_coverage_leaves'),
        # Add chain identification specificity metrics
        'chain_identification_specificity_nodes': chain_summary.get('chain_identification_specificity_nodes'),
        'chain_identification_specificity_leaves': chain_summary.get('chain_identification_specificity_leaves'),
        'chain_purity_specificity_chains': chain_summary.get('chain_purity_specificity_chains'),
        'chain_purity_specificity_txs': chain_summary.get('chain_purity_specificity_txs'),
        'impure_blackbox_chains': chain_summary.get('impure_blackbox_chains'),
        # Add strict consistency metrics
        'chain_root_mapping_strict_consistency_nodes': chain_summary.get('chain_root_mapping_strict_consistency_nodes'),
        'chain_root_mapping_strict_consistency_leaves': chain_summary.get('chain_root_mapping_strict_consistency_leaves'),
        # Add taker CoinJoin output attribution metrics
        'taker_cj_output_coverage_bb': chain_summary.get('taker_cj_output_coverage_bb'),
        'taker_cj_output_coverage_wb': chain_summary.get('taker_cj_output_coverage_wb'),
        'taker_cj_output_attribution_accuracy': chain_summary.get('taker_cj_output_attribution_accuracy'),
        'taker_cj_output_attribution_specificity': chain_summary.get('taker_cj_output_attribution_specificity'),
        'taker_cj_output_details': chain_summary.get('taker_cj_output_details'),
        # Add sole taker metrics
        'sole_taker_cj_output_attribution_accuracy': chain_summary.get('sole_taker_cj_output_attribution_accuracy'),
        'sole_taker_cj_output_attribution_specificity': chain_summary.get('sole_taker_cj_output_attribution_specificity'),
        'sole_taker_count': chain_summary.get('sole_taker_count'),
        'sole_taker_tx_count': chain_summary.get('sole_taker_tx_count'),
        'sole_taker_details': chain_summary.get('sole_taker_details'),
    }
    
    # Transaction statistics
    json_ready_data['tx_statistics'] = report_data.get('tx_statistics')
    
    # Object stats
    json_ready_data['blackbox_obj_stats'] = report_data.get('blackbox_obj_stats')
    json_ready_data['whitebox_obj_stats'] = report_data.get('whitebox_obj_stats')

    # Fidelity bond stats (JoinMarket-specific)
    fb_stats = report_data.get('fidelity_bond_stats')
    if fb_stats:
        # Convert FidelityBondStats to dictionary if it's not already
        if hasattr(fb_stats, 'to_dict'):
            json_ready_data['fidelity_bond_stats'] = fb_stats.to_dict()
        else:
            json_ready_data['fidelity_bond_stats'] = fb_stats
    else:
        json_ready_data['fidelity_bond_stats'] = None

    return json_ready_data


"""
JSON Report Structure (Draft):
{
  "txid_comparison": {...},
  "object_comparison": {...},
  "detailed_participant_breakdown": [...],
  "txid_lists": {...},
  "blackbox_identified_chains": [...],
  "whitebox_identified_chains": [...],
  "chain_comparison_summary": {...},
  "tx_statistics": {...},
  "tx_stats_list": [...],
  "detailed_cj_objects": [...],
  "metadata": {...}
}
"""

def build_unified_report_json_from_data(report_data: dict, extra_metadata: dict = None) -> str:
    """
    Serialize the given report_data dict as a pretty-printed JSON string.
    Converts NumPy types to native Python types for serialization.
    Skips CoinJoinTree objects.
    """
    # Remove CoinJoinTree objects recursively
    filtered_data = remove_coinjoin_trees(report_data)
    if extra_metadata:
        filtered_data = dict(filtered_data)
        filtered_data["metadata"] = extra_metadata
    filtered_data = convert_numpy_types(filtered_data)
    return json.dumps(filtered_data, indent=2, ensure_ascii=False, sort_keys=True, cls=PreciseDecimalEncoder)
