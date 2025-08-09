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
    """
    json_ready_data = dict()

    json_ready_data['txid_comparison_stats'] = { 'blackbox_txids': report_data['txid_comparison']['total_blackbox'],
      'whitebox_txids': report_data['txid_comparison']['total_whitebox'],
      'common_txids': report_data['txid_comparison']['common'],
      'only_blackbox': report_data['txid_comparison']['only_blackbox'],
      'only_whitebox': report_data['txid_comparison']['only_whitebox'],
      'detection_agreement': report_data['txid_comparison']['detection_agreement'],
    }
    json_ready_data['object_comparison_stats'] = {
        'comparison_tx_count': report_data['object_comparison']['comparison_tx_count'],
        'role_accuracy_avg': report_data['object_comparison']['role_accuracy_avg'],
        'overall_role_success_avg': report_data['object_comparison']['overall_role_success_avg'],
        'participant_match_rate': report_data['object_comparison']['participant_match_rate'],
        'total_bb_participants': report_data['object_comparison']['total_bb_participants'],
        'total_matched_participants': report_data['object_comparison']['total_matched_participants'],
        'taker_match_avg': report_data['object_comparison']['taker_match_avg'],
        'utxo_accuracy_avg': report_data['object_comparison']['utxo_accuracy_avg'],
    }
    json_ready_data['chain_comparison_summary'] = {
        'total_blackbox_chains': report_data['chain_comparison_summary']['total_blackbox_chains'],
        'total_whitebox_chains': report_data['chain_comparison_summary']['total_whitebox_chains'],
        'num_matched_pairs': report_data['chain_comparison_summary']['num_matched_pairs'],
        'num_fully_matched_pairs': report_data['chain_comparison_summary']['num_fully_matched_pairs'],
        'num_partially_matched_pairs': report_data['chain_comparison_summary']['num_partially_matched_pairs'],
    }
    json_ready_data['tx_statistics'] = report_data['tx_statistics']
    json_ready_data['blackbox_obj_stats'] = report_data['blackbox_obj_stats']
    json_ready_data['whitebox_obj_stats'] = report_data['whitebox_obj_stats']

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
