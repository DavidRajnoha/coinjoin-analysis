import json

import numpy as np

from joinmarket.common.analysis_config import AnalysisConfig
from joinmarket.unified_report.json_report import build_unified_report_json_from_data


def _minimal_report_data():
    return {
        'analysis_config': AnalysisConfig(maker_sessions=True).to_dict(),
        'txid_comparison': {
            'total_blackbox': 2, 'total_whitebox': 3, 'common': 2,
            'only_blackbox': 0, 'only_whitebox': 1, 'detection_agreement': np.float64(66.67),
        },
        'object_comparison': {'comparison_tx_count': np.int64(2), 'taker_match_avg': 50.0},
        'chain_comparison_summary': {
            'total_blackbox_chains': 1, 'singleton_blackbox_chains': 4,
            'chain_purity_specificity_chains': 100.0,
            'matched_chain_pairs': [{'blackbox_chain_id': 'b', 'whitebox_chain_id': 'w'}],
        },
        'blackbox_identified_chains': [object()],  # tree objects must not leak into JSON
        'whitebox_identified_chains': [object()],
    }


def test_json_export_keeps_config_metrics_and_metadata_and_drops_trees():
    json_str = build_unified_report_json_from_data(_minimal_report_data(), {'report_version': 1})
    parsed = json.loads(json_str)

    assert parsed['metadata'] == {'report_version': 1}
    assert parsed['analysis_config']['label'] == 'maker_sessions'
    assert parsed['txid_comparison_stats']['detection_agreement'] == 66.67
    assert parsed['object_comparison_stats']['comparison_tx_count'] == 2
    assert parsed['chain_comparison_summary']['singleton_blackbox_chains'] == 4
    assert parsed['chain_comparison_summary']['chain_purity_specificity_chains'] == 100.0
    assert 'blackbox_identified_chains' not in parsed
    assert 'whitebox_identified_chains' not in parsed


def test_json_export_without_config_or_metadata():
    data = _minimal_report_data()
    del data['analysis_config']
    parsed = json.loads(build_unified_report_json_from_data(data))
    assert 'analysis_config' not in parsed
    assert 'metadata' not in parsed
