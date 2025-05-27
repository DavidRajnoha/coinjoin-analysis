import pytest
from typing import List, Optional, Dict, Any
from joinmarket.common.coinjoin_model import CoinJoin, TxInput, TxOutput, CoinJoinParticipant
from joinmarket.common.coinjoin_chain import CoinjoinChain
from joinmarket.comparison.compare_coinjoin import compare_coinjoin_chains

# Helper function to create mock CoinJoin (simplified for chain testing)
def _create_cj(txid: str, block_height: int = 0) -> CoinJoin:
    # Minimal CoinJoin for testing chain comparison based on txid
    return CoinJoin(txid=txid, block_height=block_height, participants=[], tx={})

# Helper function to create mock CoinjoinChain
def _create_chain(id_suffix: str, cjs: List[CoinJoin], analysis_type: str) -> CoinjoinChain:
    return CoinjoinChain(id=f"{analysis_type}_chain_{id_suffix}", coinjoins=cjs, analysis_type=analysis_type)

# Test Cases

def test_compare_chains_empty_inputs():
    result = compare_coinjoin_chains([], [])
    assert result['total_blackbox_chains'] == 0
    assert result['total_whitebox_chains'] == 0
    assert result['matched_chain_pairs'] == []
    assert result['unmatched_blackbox_chain_ids'] == []
    assert result['unmatched_whitebox_chain_ids'] == []
    assert result['num_matched_pairs'] == 0
    assert result['num_fully_matched_pairs'] == 0
    assert result['num_partially_matched_pairs'] == 0

def test_compare_chains_one_side_empty():
    bb_chain1 = _create_chain("bb1", [_create_cj("tx1")], "blackbox")
    result = compare_coinjoin_chains([bb_chain1], [])
    assert result['total_blackbox_chains'] == 1
    assert result['total_whitebox_chains'] == 0
    assert result['matched_chain_pairs'] == []
    assert result['unmatched_blackbox_chain_ids'] == ["blackbox_chain_bb1"]
    assert result['unmatched_whitebox_chain_ids'] == []
    assert result['num_matched_pairs'] == 0

    wb_chain1 = _create_chain("wb1", [_create_cj("tx1")], "whitebox")
    result = compare_coinjoin_chains([], [wb_chain1])
    assert result['total_blackbox_chains'] == 0
    assert result['total_whitebox_chains'] == 1
    assert result['matched_chain_pairs'] == []
    assert result['unmatched_blackbox_chain_ids'] == []
    assert result['unmatched_whitebox_chain_ids'] == ["whitebox_chain_wb1"]

def test_compare_chains_perfect_match():
    cj1, cj2 = _create_cj("tx1"), _create_cj("tx2")
    bb_chain = _create_chain("bb_perfect", [cj1, cj2], "blackbox")
    wb_chain = _create_chain("wb_perfect", [cj1, cj2], "whitebox")
    result = compare_coinjoin_chains([bb_chain], [wb_chain])

    assert result['num_matched_pairs'] == 1
    assert result['num_fully_matched_pairs'] == 1
    assert result['num_partially_matched_pairs'] == 0
    assert result['unmatched_blackbox_chain_ids'] == []
    assert result['unmatched_whitebox_chain_ids'] == []
    
    pair = result['matched_chain_pairs'][0]
    assert pair['blackbox_chain_id'] == "blackbox_chain_bb_perfect"
    assert pair['whitebox_chain_id'] == "whitebox_chain_wb_perfect"
    assert pair['blackbox_txids'] == ["tx1", "tx2"]
    assert pair['whitebox_txids'] == ["tx1", "tx2"]
    assert pair['common_txids'] == ["tx1", "tx2"]
    assert pair['only_blackbox_txids'] == []
    assert pair['only_whitebox_txids'] == []
    assert pair['similarity_score'] == 1.0
    assert pair['is_full_match'] is True

def test_compare_chains_partial_match_bb_supersequence():
    cj1, cj2, cj3 = _create_cj("tx1"), _create_cj("tx2"), _create_cj("tx3")
    bb_chain = _create_chain("bb_super", [cj1, cj2, cj3], "blackbox")
    wb_chain = _create_chain("wb_sub", [cj1, cj2], "whitebox")
    result = compare_coinjoin_chains([bb_chain], [wb_chain])

    assert result['num_matched_pairs'] == 1
    assert result['num_fully_matched_pairs'] == 0
    assert result['num_partially_matched_pairs'] == 1
    pair = result['matched_chain_pairs'][0]
    assert pair['blackbox_txids'] == ["tx1", "tx2", "tx3"]
    assert pair['whitebox_txids'] == ["tx1", "tx2"]
    assert pair['common_txids'] == ["tx1", "tx2"]
    assert pair['only_blackbox_txids'] == ["tx3"]
    assert pair['only_whitebox_txids'] == []
    assert pair['similarity_score'] == round(2/3, 4)
    assert pair['is_full_match'] is False

def test_compare_chains_partial_match_wb_supersequence():
    cj1, cj2, cj3 = _create_cj("tx1"), _create_cj("tx2"), _create_cj("tx3")
    bb_chain = _create_chain("bb_sub", [cj1, cj2], "blackbox")
    wb_chain = _create_chain("wb_super", [cj1, cj2, cj3], "whitebox")
    result = compare_coinjoin_chains([bb_chain], [wb_chain])

    assert result['num_matched_pairs'] == 1
    assert result['num_fully_matched_pairs'] == 0
    assert result['num_partially_matched_pairs'] == 1
    pair = result['matched_chain_pairs'][0]
    assert pair['blackbox_txids'] == ["tx1", "tx2"]
    assert pair['whitebox_txids'] == ["tx1", "tx2", "tx3"]
    assert pair['common_txids'] == ["tx1", "tx2"]
    assert pair['only_blackbox_txids'] == []
    assert pair['only_whitebox_txids'] == ["tx3"]
    assert pair['similarity_score'] == round(2/3, 4)
    assert pair['is_full_match'] is False

def test_compare_chains_partial_overlap():
    cj1, cj2, cj3, cj4 = _create_cj("tx1"), _create_cj("tx2"), _create_cj("tx3"), _create_cj("tx4")
    bb_chain = _create_chain("bb_overlap", [cj1, cj2, cj3], "blackbox")
    wb_chain = _create_chain("wb_overlap", [cj2, cj3, cj4], "whitebox")
    result = compare_coinjoin_chains([bb_chain], [wb_chain])

    assert result['num_matched_pairs'] == 1
    pair = result['matched_chain_pairs'][0]
    assert pair['blackbox_txids'] == ["tx1", "tx2", "tx3"]
    assert pair['whitebox_txids'] == ["tx2", "tx3", "tx4"]
    assert pair['common_txids'] == ["tx2", "tx3"]
    assert pair['only_blackbox_txids'] == ["tx1"]
    assert pair['only_whitebox_txids'] == ["tx4"]
    assert pair['similarity_score'] == round(2/4, 4)
    assert pair['is_full_match'] is False

def test_compare_chains_no_overlap():
    bb_chain = _create_chain("bb_no_overlap", [_create_cj("tx1"), _create_cj("tx2")], "blackbox")
    wb_chain = _create_chain("wb_no_overlap", [_create_cj("tx3"), _create_cj("tx4")], "whitebox")
    result = compare_coinjoin_chains([bb_chain], [wb_chain])

    assert result['num_matched_pairs'] == 0
    assert result['unmatched_blackbox_chain_ids'] == ["blackbox_chain_bb_no_overlap"]
    assert result['unmatched_whitebox_chain_ids'] == ["whitebox_chain_wb_no_overlap"]

def test_compare_chains_multiple_chains_mixed_matches():
    # Chains
    bb1 = _create_chain("bb1", [_create_cj("txA"), _create_cj("txB")], "blackbox") # Perfect match with wb1
    bb2 = _create_chain("bb2", [_create_cj("txC"), _create_cj("txD"), _create_cj("txE")], "blackbox") # Partial with wb2
    bb3 = _create_chain("bb3", [_create_cj("txF")], "blackbox") # Unmatched

    wb1 = _create_chain("wb1", [_create_cj("txA"), _create_cj("txB")], "whitebox")
    wb2 = _create_chain("wb2", [_create_cj("txD"), _create_cj("txE"), _create_cj("txG")], "whitebox")
    wb3 = _create_chain("wb3", [_create_cj("txH")], "whitebox") # Unmatched

    result = compare_coinjoin_chains([bb1, bb2, bb3], [wb1, wb2, wb3])

    assert result['total_blackbox_chains'] == 3
    assert result['total_whitebox_chains'] == 3
    assert result['num_matched_pairs'] == 2
    assert result['num_fully_matched_pairs'] == 1
    assert result['num_partially_matched_pairs'] == 1
    assert sorted(result['unmatched_blackbox_chain_ids']) == ["blackbox_chain_bb3"]
    assert sorted(result['unmatched_whitebox_chain_ids']) == ["whitebox_chain_wb3"]

    # Check matches (order depends on similarity score, then bb_id)
    # bb1-wb1 (score 1.0)
    # bb2-wb2 (score 2/4 = 0.5)
    match_ids = {(p['blackbox_chain_id'], p['whitebox_chain_id']) for p in result['matched_chain_pairs']}
    assert ("blackbox_chain_bb1", "whitebox_chain_wb1") in match_ids
    assert ("blackbox_chain_bb2", "whitebox_chain_wb2") in match_ids

    for pair in result['matched_chain_pairs']:
        if pair['blackbox_chain_id'] == "blackbox_chain_bb1":
            assert pair['is_full_match'] is True
            assert pair['common_txids'] == ["txA", "txB"]
        elif pair['blackbox_chain_id'] == "blackbox_chain_bb2":
            assert pair['is_full_match'] is False
            assert pair['common_txids'] == ["txD", "txE"]
            assert pair['only_blackbox_txids'] == ["txC"]
            assert pair['only_whitebox_txids'] == ["txG"]

def test_compare_chains_empty_coinjoin_lists_in_chains():
    # Chains with no coinjoins (e.g. identified but empty)
    bb_empty_chain = _create_chain("bb_empty", [], "blackbox")
    wb_empty_chain = _create_chain("wb_empty", [], "whitebox")
    bb_non_empty = _create_chain("bb_non_empty", [_create_cj("tx1")], "blackbox")
    wb_non_empty = _create_chain("wb_non_empty", [_create_cj("tx1")], "whitebox")

    # Case 1: Both chains are empty of coinjoins
    result1 = compare_coinjoin_chains([bb_empty_chain], [wb_empty_chain])
    assert result1['num_matched_pairs'] == 1
    assert result1['matched_chain_pairs'][0]['is_full_match'] is True
    assert result1['matched_chain_pairs'][0]['similarity_score'] == 1.0 # Jaccard of empty sets is debatable, current impl: 1.0 if both empty

    # Case 2: One empty, one not (no match)
    result2 = compare_coinjoin_chains([bb_empty_chain], [wb_non_empty])
    assert result2['num_matched_pairs'] == 0
    assert "blackbox_chain_bb_empty" in result2['unmatched_blackbox_chain_ids']
    assert "whitebox_chain_wb_non_empty" in result2['unmatched_whitebox_chain_ids']

    # Case 3: Mix of empty and non-empty
    result3 = compare_coinjoin_chains([bb_empty_chain, bb_non_empty], [wb_empty_chain, wb_non_empty])
    assert result3['num_matched_pairs'] == 2
    match_ids = {(p['blackbox_chain_id'], p['whitebox_chain_id']) for p in result3['matched_chain_pairs']}
    assert ("blackbox_chain_bb_empty", "whitebox_chain_wb_empty") in match_ids
    assert ("blackbox_chain_bb_non_empty", "whitebox_chain_wb_non_empty") in match_ids


def test_greedy_matching_priority():
    # wb_chain1 can match bb_chain1 (perfectly) or bb_chain2 (partially)
    # wb_chain2 can match bb_chain2 (perfectly)
    # Greedy should pick (bb1,wb1) and (bb2,wb2)
    bb1 = _create_chain("bb1", [_create_cj("txA")], "blackbox") # score 1.0 with wb1
    bb2 = _create_chain("bb2", [_create_cj("txB"), _create_cj("txC")], "blackbox") # score 1.0 with wb2, score 0.5 with wb1 (if txB in wb1)

    wb1 = _create_chain("wb1", [_create_cj("txA"), _create_cj("txB")], "whitebox") # score 1.0 with bb1 (A), score 0.5 with bb2 (B)
    wb2 = _create_chain("wb2", [_create_cj("txB"), _create_cj("txC")], "whitebox") # score 1.0 with bb2

    # Scenario 1: wb1 has txA, txB. bb1 has txA. bb2 has txB, txC.
    # Potential: (bb1,wb1) score for A = 1/2=0.5. (bb2,wb1) score for B = 1/3. (bb2,wb2) score for B,C = 1.0
    # Expected: (bb2,wb2) is best. Then (bb1,wb1) is processed.
    bb_chain1 = _create_chain("b1", [_create_cj("txA")], "blackbox")
    bb_chain2 = _create_chain("b2", [_create_cj("txB"), _create_cj("txC")], "blackbox")

    wb_chain1 = _create_chain("w1", [_create_cj("txA"), _create_cj("txB")], "whitebox")
    wb_chain2 = _create_chain("w2", [_create_cj("txB"), _create_cj("txC")], "whitebox")

    result = compare_coinjoin_chains([bb_chain1, bb_chain2], [wb_chain1, wb_chain2])
    assert result['num_matched_pairs'] == 2
    
    matched_bb_ids = {p['blackbox_chain_id'] for p in result['matched_chain_pairs']}
    matched_wb_ids = {p['whitebox_chain_id'] for p in result['matched_chain_pairs']}

    # (bb_chain2, wb_chain2) should be a perfect match (score 1.0)
    # (bb_chain1, wb_chain1) should be a partial match (score 1/2 = 0.5)
    # The sort order in compare_coinjoin_chains is (-score, bb_chain.id)
    # So (bb_chain2, wb_chain2) will be picked first if its bb_chain.id is smaller or score is higher.
    # If scores are 1.0 and 0.5, (bb_chain2, wb_chain2) is picked first.
    # Then (bb_chain1, wb_chain1) is picked.

    pair1_found = False
    pair2_found = False
    for pair in result['matched_chain_pairs']:
        if pair['blackbox_chain_id'] == "blackbox_chain_b2" and pair['whitebox_chain_id'] == "whitebox_chain_w2":
            assert pair['is_full_match'] is True
            assert pair['similarity_score'] == 1.0
            pair1_found = True
        elif pair['blackbox_chain_id'] == "blackbox_chain_b1" and pair['whitebox_chain_id'] == "whitebox_chain_w1":
            assert pair['is_full_match'] is False # bb_chain1 is [txA], wb_chain1 is [txA, txB]
            assert pair['similarity_score'] == round(1/2, 4)
            assert pair['common_txids'] == ['txA']
            assert pair['only_whitebox_txids'] == ['txB']
            pair2_found = True
            
    assert pair1_found and pair2_found
