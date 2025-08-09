import json
from joinmarket.unified_report.json_report import build_unified_report_json, build_unified_report_json_obj

def test_build_unified_report_json_and_obj():
    # Minimal dummy data
    blackbox_results = [{"txid": "bb1"}]
    whitebox_data = [{"txid": "wb1"}]
    class DummyCJ:
        def __init__(self, txid):
            self.txid = txid
            self.block_height = 100
            self.cj_amount = 1.0
            self.miner_fee = 0.001
            self.participants = []
            self.tx = {'vin': [], 'vout': []}
    blackbox_cj_objs = [DummyCJ("bb1")]
    whitebox_cj_objs = [DummyCJ("wb1")]
    output_dir = "."
    meta = {"report_version": 1}
    json_str = build_unified_report_json(blackbox_results, whitebox_data, blackbox_cj_objs, whitebox_cj_objs, output_dir, meta)
    json_obj = build_unified_report_json_obj(blackbox_results, whitebox_data, blackbox_cj_objs, whitebox_cj_objs, output_dir, meta)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["metadata"]["report_version"] == 1
    assert "object_comparison" in parsed
    assert isinstance(json_obj, dict)
    assert json_obj["metadata"]["report_version"] == 1
