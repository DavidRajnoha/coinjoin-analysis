import pytest
import pandas as pd
from joinmarket.unified_report.unified_report_data import (
    aggregate_txid_comparison,
    aggregate_object_comparison,
    aggregate_participant_breakdown,
    aggregate_chain_stats,
    aggregate_chain_comparison_summary,
    aggregate_colored_tree_comparisons,
    aggregate_tx_statistics,
    aggregate_detailed_cj_objects
)

def test_aggregate_txid_comparison():
    # Should call generate_comparison_data, here just check passthrough
    result = aggregate_txid_comparison([{"txid":"a"}], [{"txid":"b"}])
    assert isinstance(result, dict) or result is not None

def test_aggregate_object_comparison():
    # Should call generate_object_comparison, here just check output type
    result = aggregate_object_comparison([], [],)
    assert isinstance(result, dict)

def test_aggregate_participant_breakdown():
    obj_comparison_data = {"obj_comparison": [{
        "txid": "t1",
        "block_height": 100,
        "participant_breakdown": [
            {"bb_sig": True, "bb_role": "maker", "wb_roles": ["maker"], "role_match": True}
        ]
    }]}
    class DummyCJ:
        def __init__(self, txid):
            self.txid = txid
            self.participants = []
    result = aggregate_participant_breakdown(obj_comparison_data, [DummyCJ("t1")])
    assert isinstance(result, list)
    assert result[0]["txid"] == "t1"

def test_aggregate_chain_stats():
    # Patch get_identified_chains_and_txids to return dummy chains/txids
    from joinmarket.comparison.coinjoin_chain_analysis import get_identified_chains_and_txids
    orig_func = get_identified_chains_and_txids
    def dummy_func(cj_objs, chain_type):
        class DummyChain:
            id = "c1"
            def __init__(self):
                self.nodes = []
        return [DummyChain()], ["txid1"]
    import joinmarket.unified_report.unified_report_data as urd
    urd.get_identified_chains_and_txids = dummy_func
    chains1, chains2, txid_lists = urd.aggregate_chain_stats([], [])
    assert isinstance(chains1, list)
    assert isinstance(chains2, list)
    assert isinstance(txid_lists, dict)
    urd.get_identified_chains_and_txids = orig_func

def test_aggregate_chain_comparison_summary():
    # Should call compare_coinjoin_chains, just check dict output
    result = aggregate_chain_comparison_summary([], [])
    assert isinstance(result, dict)
    assert result['total_blackbox_chains'] == 0

def test_aggregate_colored_tree_comparisons():
    class DummyNode:
        def __init__(self, txid):
            self.txid = txid
            self.children = []
    class DummyChain:
        def __init__(self, txids):
            self.nodes = [DummyNode(txid) for txid in txids]
            self.root_nodes = self.nodes  # Provide root_nodes as required
    chain_map = {
        "c1": DummyChain(["a", "b"]),
        "c2": DummyChain(["b", "c"])
    }
    summary = {"matched_chain_pairs": [
        {"blackbox_chain_id": "c1", "whitebox_chain_id": "c2"}
    ]}
    # Should not error and should add 'colored_tree_comparison' key
    aggregate_colored_tree_comparisons(summary, chain_map)
    assert 'colored_tree_comparison' in summary['matched_chain_pairs'][0]

def test_aggregate_tx_statistics():
    class DummyCJ:
        def __init__(self, txid, block_height, vin, vout, cj_amount, participants):
            self.txid = txid
            self.block_height = block_height
            self.tx = {"vin": vin, "vout": vout}
            self.cj_amount = cj_amount
            self.participants = [None]*participants
            self.meta = {}
    cj1 = DummyCJ("t1", 100, [1,2], [1], 0.5, 2)
    cj2 = DummyCJ("t2", 101, [1], [1,2,3], 1.0, 3)
    input_stats, output_stats, all_tx_stats, solve_status_stats = aggregate_tx_statistics([cj1], [cj2])
    assert isinstance(input_stats, dict)
    assert isinstance(output_stats, dict)
    assert len(all_tx_stats) == 2
    assert isinstance(solve_status_stats, dict)

    assert aggregate_tx_statistics([], []) == (None, None, [], {})

def test_aggregate_detailed_cj_objects():
    class DummyInput:
        def __init__(self, txid, vout, value, address=None, client=None):
            self.txid = txid
            self.vout = vout
            self.value = value
            self.address = address
            self.client = client
    class DummyOutput:
        def __init__(self, n, value, address=None, client=None):
            self.n = n
            self.value = value
            self.address = address
            self.client = client
    class DummyParticipant:
        def __init__(self, role, client, input_value, output_value, delta, inputs, cj_output, change_output=None):
            self.role = role
            self.client = client
            self.input_value = input_value
            self.output_value = output_value
            self.delta = delta
            self.inputs = inputs
            self.cj_output = cj_output
            self.change_output = change_output
    class DummyCJ:
        def __init__(self, txid, block_height, cj_amount, miner_fee, participants):
            self.txid = txid
            self.block_height = block_height
            self.cj_amount = cj_amount
            self.miner_fee = miner_fee
            self.participants = participants
    # Compose a whitebox and blackbox CJ object
    inp = DummyInput("txid1", 0, 0.5, "addr1", "cli1")
    out = DummyOutput(0, 0.5, "addr2", "cli1")
    change = DummyOutput(1, 0.1, "addr3", "cli1")
    part = DummyParticipant("maker", "cli1", 0.5, 0.5, 0.0, [inp], out, change)
    cj_white = DummyCJ("wtxid", 100, 0.5, 0.001, [part])
    cj_black = DummyCJ("btxid", 101, 0.6, 0.0012, [part])
    from joinmarket.unified_report.unified_report_data import aggregate_detailed_cj_objects
    result = aggregate_detailed_cj_objects([cj_white], [cj_black])
    assert isinstance(result, list)
    assert result[0]["txid"] == "wtxid"
    assert result[1]["txid"] == "btxid"
    assert result[0]["participants"][0]["role"] == "maker"
    assert result[0]["participants"][0]["inputs"][0]["txid"] == "txid1"
    assert result[0]["participants"][0]["cj_output"]["n"] == 0
    assert result[0]["participants"][0]["change_output"]["n"] == 1
