import pytest
from typing import List, Dict, Any, Optional
from uuid import uuid4
from joinmarket.common.coinjoin_model import CoinJoin, CoinJoinParticipant, TxInput, TxOutput
from joinmarket.common.coinjoin_chain import CoinJoinTree, CoinJoinLeafNode, identify_coinjoin_chains
import json

# Helper function to create mock TxInput
def _create_tx_input(txid: str, vout: int, value: float, address: Optional[str] = None, client: Optional[str] = None) -> TxInput:
    return TxInput(txid=txid, vout=vout, value=value, address=address, client=client)

# Helper function to create mock TxOutput
def _create_tx_output(n: int, value: float, address: Optional[str] = None, client: Optional[str] = None) -> TxOutput:
    return TxOutput(n=n, value=value, address=address, client=client)

# Helper function to create mock CoinJoinParticipant
def _create_participant(inputs: List[TxInput], cj_output: TxOutput, change_output: Optional[TxOutput] = None, 
                        role: str = "unknown", client: Optional[str] = None) -> CoinJoinParticipant:
    return CoinJoinParticipant(inputs=inputs, cj_output=cj_output, change_output=change_output, role=role, client=client)

# Helper function to create mock CoinJoin
def _create_coinjoin(txid: str, block_height: int, participants: List[CoinJoinParticipant], 
                     tx_data: Optional[Dict[str, Any]] = None) -> CoinJoin:
    if tx_data is None:
        tx_data = {'txid': txid, 'vin': [], 'vout': []} # Simplified tx_data
    return CoinJoin(txid=txid, block_height=block_height, participants=participants, tx=tx_data)

# Test Cases

def test_identify_chains_empty_input():
    assert identify_coinjoin_chains([], 'blackbox') == []
    assert identify_coinjoin_chains([], 'whitebox') == []

def test_single_coinjoin_with_taker():
    cj1 = _create_coinjoin("tx1", 100, [
        _create_participant([_create_tx_input("prev_tx_a", 0, 1.0)], _create_tx_output(0, 1.0), role="taker")
    ])
    chains_bb = identify_coinjoin_chains([cj1], 'blackbox')
    assert len(chains_bb) == 1
    assert chains_bb[0].length() == 1
    assert chains_bb[0].coinjoins[0].txid == "tx1"

    chains_wb = identify_coinjoin_chains([cj1], 'whitebox')
    assert len(chains_wb) == 1
    assert chains_wb[0].length() == 1
    assert chains_wb[0].coinjoins[0].txid == "tx1"

def test_multiple_unlinked_coinjoins():
    cj1 = _create_coinjoin("tx1", 100, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    cj2 = _create_coinjoin("tx2", 101, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    chains = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert len(chains) == 2
    assert chains[0].length() == 1
    assert chains[1].length() == 1
    assert {chains[0].coinjoins[0].txid, chains[1].coinjoins[0].txid} == {"tx1", "tx2"}

def test_simple_blackbox_chain():
    p1_cj1 = _create_participant([_create_tx_input("prev_a", 0, 1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])
    
    chains = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert len(chains) == 1
    assert chains[0].length() == 2
    assert chains[0].coinjoins[0].txid == "tx1"
    assert chains[0].coinjoins[1].txid == "tx2"

def test_simple_whitebox_chain_matching_clients():
    p1_cj1 = _create_participant([_create_tx_input("prev_a", 0, 1.1)], _create_tx_output(0, 1.0, client="clientA"), role="taker", client="clientA")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0, client="clientA")], _create_tx_output(0, 0.9, client="clientA"), role="taker", client="clientA")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    chains = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    assert len(chains) == 1
    assert chains[0].length() == 2
    assert chains[0].coinjoins[0].txid == "tx1"
    assert chains[0].coinjoins[1].txid == "tx2"
    assert "clientA" in chains[0].tumbler_clients

def test_whitebox_chain_non_matching_clients():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0, client="clientA"), role="taker", client="clientA")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0, client="clientB")], _create_tx_output(0, 0.9, client="clientB"), role="taker", client="clientB")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    chains = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    assert len(chains) == 2 
    assert chains[0].length() == 1
    assert chains[1].length() == 1
    assert {chains[0].coinjoins[0].txid, chains[1].coinjoins[0].txid} == {"tx1", "tx2"}

def test_whitebox_chain_missing_client_info():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0, client="clientA"), role="taker", client="clientA")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker") 
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    chains = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    # tx2 has no attributable client, so it is not linked to clientA but still placed as a singleton
    assert sorted((c.length(), c.coinjoins[0].txid) for c in chains) == [(1, "tx1"), (1, "tx2")]

def test_link_via_non_taker_participant():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="maker")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])
    
    chains = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert len(chains) == 2  # We want to see both chains since one has a taker and one has a maker

def test_longer_chain_three_cjs_blackbox():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(1, 0.9), role="taker")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    p1_cj3 = _create_participant([_create_tx_input("tx2", 1, 0.9)], _create_tx_output(0, 0.8), role="taker")
    cj3 = _create_coinjoin("tx3", 102, [p1_cj3])

    chains = identify_coinjoin_chains([cj1, cj2, cj3], 'blackbox')
    assert len(chains) == 1
    assert chains[0].length() == 3
    assert set(cj.txid for cj in chains[0].coinjoins) == {"tx1", "tx2", "tx3"}

def test_multiple_disjoint_chains():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])
    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    p1_cj3 = _create_participant([_create_tx_input("prev_b",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj3 = _create_coinjoin("tx3", 102, [p1_cj3])
    p1_cj4 = _create_participant([_create_tx_input("tx3", 0, 1.0)], _create_tx_output(0, 0.9), role="taker")
    cj4 = _create_coinjoin("tx4", 103, [p1_cj4])

    cj5 = _create_coinjoin("tx5", 104, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])

    chains = identify_coinjoin_chains([cj1, cj2, cj3, cj4, cj5], 'blackbox')
    assert len(chains) == 3
    
    # Sort chains by length to make the assertions more stable
    chains.sort(key=lambda c: c.length(), reverse=True)
    
    # First two chains should have length 2
    assert chains[0].length() == 2
    assert chains[1].length() == 2
    
    # The last chain should have length 1
    assert chains[2].length() == 1
    assert chains[2].coinjoins[0].txid == "tx5"
    
    # Verify the first two chains have the right transactions
    chain1_txids = {cj.txid for cj in chains[0].coinjoins}
    chain2_txids = {cj.txid for cj in chains[1].coinjoins}
    
    assert (chain1_txids == {"tx1", "tx2"} and chain2_txids == {"tx3", "tx4"}) or \
           (chain1_txids == {"tx3", "tx4"} and chain2_txids == {"tx1", "tx2"})

def test_chain_id_generation():
    cj1 = _create_coinjoin("tx100", 100, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    cj2 = _create_coinjoin("tx200", 101, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    
    chains_bb = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    
    # Check that we have two chains
    assert len(chains_bb) == 2
    
    # Check that IDs start with the right prefix but don't enforce exact format
    assert chains_bb[0].id.startswith("blackbox_chain_")
    assert chains_bb[1].id.startswith("blackbox_chain_")

    chains_wb = identify_coinjoin_chains([cj1, cj2], 'whitebox')

    # No client info: each transaction is placed as its own singleton chain
    assert len(chains_wb) == 2
    assert all(c.length() == 1 and c.id.startswith("whitebox_chain_") for c in chains_wb)

def test_branching_scenario_from_one_cj_output():
    p_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p_cj1])

    p_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker")
    cj2 = _create_coinjoin("tx2", 101, [p_cj2]) 

    p_cj3 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.8), role="taker")
    cj3 = _create_coinjoin("tx3", 102, [p_cj3]) 

    all_cjs = [cj1, cj2, cj3]
    chains = identify_coinjoin_chains(all_cjs, 'blackbox')

    # With tree-based approach, we should have one chain containing all transactions
    assert len(chains) == 1
    assert chains[0].length() == 3
    
    # Verify it contains all 3 txids
    assert {cj.txid for cj in chains[0].coinjoins} == {"tx1", "tx2", "tx3"}
    
    # Check that the connections dictionary correctly shows the branching
    assert sorted(chains[0].connections["tx1"]) == ["tx2", "tx3"]

def test_identify_chains_whitebox():
    """Test identifying CoinJoin chains in whitebox mode"""
    # Create a simple chain: tx1 -> tx2 -> tx3
    # All transactions have the same client
    
    p1_cj1 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="prev_tx1", vout=0, value=1.0, client="clientA")],
        cj_output=TxOutput(n=0, value=0.9, address="addr1", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr2", client="clientA")
    )
    
    cj1 = CoinJoin(
        txid="tx1",
        block_height=100,
        tx={"version": 1},
        participants=[p1_cj1]
    )
    
    p1_cj2 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx1", vout=0, value=0.9, client="clientA")],
        cj_output=TxOutput(n=0, value=0.8, address="addr3", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr4", client="clientA")
    )
    
    cj2 = CoinJoin(
        txid="tx2",
        block_height=110,
        tx={"version": 1},
        participants=[p1_cj2]
    )
    
    p1_cj3 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx2", vout=0, value=0.8, client="clientA")],
        cj_output=TxOutput(n=0, value=0.7, address="addr5", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr6", client="clientA")
    )
    
    cj3 = CoinJoin(
        txid="tx3",
        block_height=120,
        tx={"version": 1},
        participants=[p1_cj3]
    )
    
    chains = identify_coinjoin_chains([cj1, cj2, cj3], 'whitebox')
    
    assert len(chains) == 1
    assert chains[0].length() == 3
    assert chains[0].analysis_type == 'whitebox'
    assert len(chains[0].coinjoins) == 3
    assert set(cj.txid for cj in chains[0].coinjoins) == {"tx1", "tx2", "tx3"}
    assert chains[0].connections == {"tx1": ["tx2"], "tx2": ["tx3"]}
    assert chains[0].start_block() == 100
    assert chains[0].end_block() == 120
    assert chains[0].duration_blocks() == 20
    assert chains[0].tumbler_clients == {"clientA"}

def test_identify_chains_blackbox():
    """Test identifying CoinJoin chains in blackbox mode"""
    # Create a simple chain: tx1 -> tx2 -> tx3
    
    p1_cj1 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="prev_tx1", vout=0, value=1.0, client="clientA")],
        cj_output=TxOutput(n=0, value=0.9, address="addr1", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr2", client="clientA")
    )
    
    cj1 = CoinJoin(
        txid="tx1",
        block_height=100,
        tx={"version": 1},
        participants=[p1_cj1]
    )
    
    p1_cj2 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx1", vout=0, value=0.9, client="clientA")],
        cj_output=TxOutput(n=0, value=0.8, address="addr3", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr4", client="clientA")
    )
    
    cj2 = CoinJoin(
        txid="tx2",
        block_height=110,
        tx={"version": 1},
        participants=[p1_cj2]
    )
    
    p1_cj3 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx2", vout=0, value=0.8, client="clientA")],
        cj_output=TxOutput(n=0, value=0.7, address="addr5", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr6", client="clientA")
    )
    
    cj3 = CoinJoin(
        txid="tx3",
        block_height=120,
        tx={"version": 1},
        participants=[p1_cj3]
    )
    
    chains = identify_coinjoin_chains([cj1, cj2, cj3], 'blackbox')
    
    assert len(chains) == 1
    assert chains[0].length() == 3
    assert chains[0].analysis_type == 'blackbox'
    assert len(chains[0].coinjoins) == 3
    assert set(cj.txid for cj in chains[0].coinjoins) == {"tx1", "tx2", "tx3"}
    assert chains[0].connections == {"tx1": ["tx2"], "tx2": ["tx3"]}
    assert chains[0].start_block() == 100
    assert chains[0].end_block() == 120
    assert chains[0].duration_blocks() == 20

def test_multiple_chains():
    """Test identifying multiple chains"""
    # Create two separate chains:
    # Chain 1: tx1 -> tx2
    # Chain 2: tx3 -> tx4
    
    p1_cj1 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="prev_tx1", vout=0, value=1.0, client="clientA")],
        cj_output=TxOutput(n=0, value=0.9, address="addr1", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr2", client="clientA")
    )
    
    cj1 = CoinJoin(
        txid="tx1",
        block_height=100,
        tx={"version": 1},
        participants=[p1_cj1]
    )
    
    p1_cj2 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx1", vout=0, value=0.9, client="clientA")],
        cj_output=TxOutput(n=0, value=0.8, address="addr3", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr4", client="clientA")
    )
    
    cj2 = CoinJoin(
        txid="tx2",
        block_height=110,
        tx={"version": 1},
        participants=[p1_cj2]
    )
    
    p1_cj3 = CoinJoinParticipant(
        role="taker", 
        client="clientB",
        inputs=[TxInput(txid="prev_tx2", vout=0, value=1.0, client="clientB")],
        cj_output=TxOutput(n=0, value=0.9, address="addr5", client="clientB"),
        change_output=TxOutput(n=1, value=0.09, address="addr6", client="clientB")
    )
    
    cj3 = CoinJoin(
        txid="tx3",
        block_height=100,
        tx={"version": 1},
        participants=[p1_cj3]
    )
    
    p1_cj4 = CoinJoinParticipant(
        role="taker", 
        client="clientB",
        inputs=[TxInput(txid="tx3", vout=0, value=0.9, client="clientB")],
        cj_output=TxOutput(n=0, value=0.8, address="addr7", client="clientB"),
        change_output=TxOutput(n=1, value=0.09, address="addr8", client="clientB")
    )
    
    cj4 = CoinJoin(
        txid="tx4",
        block_height=110,
        tx={"version": 1},
        participants=[p1_cj4]
    )
    
    # Test in whitebox mode
    wb_chains = identify_coinjoin_chains([cj1, cj2, cj3, cj4], 'whitebox')
    
    assert len(wb_chains) == 2
    
    # Sort chains by client for consistent testing
    wb_chains.sort(key=lambda c: list(c.tumbler_clients)[0] if c.tumbler_clients else "")
    
    assert wb_chains[0].tumbler_clients == {"clientA"}
    assert wb_chains[0].length() == 2
    assert set(cj.txid for cj in wb_chains[0].coinjoins) == {"tx1", "tx2"}
    assert wb_chains[0].connections == {"tx1": ["tx2"]}
    
    assert wb_chains[1].tumbler_clients == {"clientB"}
    assert wb_chains[1].length() == 2
    assert set(cj.txid for cj in wb_chains[1].coinjoins) == {"tx3", "tx4"}
    assert wb_chains[1].connections == {"tx3": ["tx4"]}
    
    # Test in blackbox mode
    bb_chains = identify_coinjoin_chains([cj1, cj2, cj3, cj4], 'blackbox')
    
    assert len(bb_chains) == 2
    
    # Sort chains by first transaction ID for consistent testing
    bb_chains.sort(key=lambda c: c.coinjoins[0].txid)
    
    assert bb_chains[0].length() == 2
    assert set(cj.txid for cj in bb_chains[0].coinjoins) == {"tx1", "tx2"}
    assert bb_chains[0].connections == {"tx1": ["tx2"]}
    
    assert bb_chains[1].length() == 2
    assert set(cj.txid for cj in bb_chains[1].coinjoins) == {"tx3", "tx4"}
    assert bb_chains[1].connections == {"tx3": ["tx4"]}

def test_branching_chain():
    """Test a branching chain where one transaction has multiple children"""
    # Create a tree structure:
    #       tx1
    #      /  \
    #    tx2  tx3
    
    p1_cj1 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="prev_tx1", vout=0, value=1.0, client="clientA")],
        cj_output=TxOutput(n=0, value=0.5, address="addr1", client="clientA"),
        change_output=TxOutput(n=1, value=0.49, address="addr2", client="clientA")
    )
    
    cj1 = CoinJoin(
        txid="tx1",
        block_height=100,
        tx={"version": 1},
        participants=[p1_cj1]
    )
    
    p1_cj2 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx1", vout=0, value=0.5, client="clientA")],
        cj_output=TxOutput(n=0, value=0.4, address="addr3", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr4", client="clientA")
    )
    
    cj2 = CoinJoin(
        txid="tx2",
        block_height=110,
        tx={"version": 1},
        participants=[p1_cj2]
    )
    
    p1_cj3 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx1", vout=1, value=0.49, client="clientA")],
        cj_output=TxOutput(n=0, value=0.4, address="addr5", client="clientA"),
        change_output=TxOutput(n=1, value=0.08, address="addr6", client="clientA")
    )
    
    cj3 = CoinJoin(
        txid="tx3",
        block_height=120,
        tx={"version": 1},
        participants=[p1_cj3]
    )
    
    # Test in whitebox mode
    wb_chains = identify_coinjoin_chains([cj1, cj2, cj3], 'whitebox')
    
    assert len(wb_chains) == 1
    assert wb_chains[0].length() == 3
    assert wb_chains[0].tumbler_clients == {"clientA"}
    assert set(cj.txid for cj in wb_chains[0].coinjoins) == {"tx1", "tx2", "tx3"}
    assert wb_chains[0].connections == {"tx1": ["tx2", "tx3"]}
    
    # Test in blackbox mode
    bb_chains = identify_coinjoin_chains([cj1, cj2, cj3], 'blackbox')
    
    assert len(bb_chains) == 1
    assert bb_chains[0].length() == 3
    assert set(cj.txid for cj in bb_chains[0].coinjoins) == {"tx1", "tx2", "tx3"}
    assert bb_chains[0].connections == {"tx1": ["tx2", "tx3"]}

def test_singleton_chain():
    """Test a chain with a single transaction"""
    
    p1_cj1 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="prev_tx1", vout=0, value=1.0, client="clientA")],
        cj_output=TxOutput(n=0, value=0.9, address="addr1", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr2", client="clientA")
    )
    
    cj1 = CoinJoin(
        txid="tx1",
        block_height=100,
        tx={"version": 1},
        participants=[p1_cj1]
    )
    
    # Test in whitebox mode
    wb_chains = identify_coinjoin_chains([cj1], 'whitebox')
    
    assert len(wb_chains) == 1
    assert wb_chains[0].length() == 1
    assert wb_chains[0].tumbler_clients == {"clientA"}
    assert set(cj.txid for cj in wb_chains[0].coinjoins) == {"tx1"}
    assert wb_chains[0].connections == {}
    
    # Test in blackbox mode
    bb_chains = identify_coinjoin_chains([cj1], 'blackbox')
    
    assert len(bb_chains) == 1
    assert bb_chains[0].length() == 1
    assert set(cj.txid for cj in bb_chains[0].coinjoins) == {"tx1"}
    assert bb_chains[0].connections == {}

def test_single_coinjoin():
    """Test with a single CoinJoin that has no client info"""
    
    p1 = CoinJoinParticipant(
        role="taker", 
        client=None,  # No client info
        inputs=[TxInput(txid="prev_tx1", vout=0, value=1.0, client=None)],
        cj_output=TxOutput(n=0, value=0.9, address="addr1", client=None),
        change_output=TxOutput(n=1, value=0.09, address="addr2", client=None)
    )
    
    cj = CoinJoin(
        txid="tx1",
        block_height=100,
        tx={"version": 1},
        participants=[p1]
    )
    
    # In whitebox mode an unattributable transaction is placed as a singleton chain
    wb_chains = identify_coinjoin_chains([cj], 'whitebox')
    
    assert len(wb_chains) == 1
    assert wb_chains[0].length() == 1
    assert wb_chains[0].tumbler_clients == set()
    assert set(cj.txid for cj in wb_chains[0].coinjoins) == {"tx1"}
    assert wb_chains[0].connections == {}
    
    # In blackbox mode, this would create a chain regardless
    bb_chains = identify_coinjoin_chains([cj], 'blackbox')
    
    assert len(bb_chains) == 1
    assert bb_chains[0].length() == 1
    assert set(cj.txid for cj in bb_chains[0].coinjoins) == {"tx1"}
    assert bb_chains[0].connections == {}

def test_empty_input():
    """Test with empty input"""
    
    chains = identify_coinjoin_chains([], 'whitebox')
    assert len(chains) == 0
    
    chains = identify_coinjoin_chains([], 'blackbox')
    assert len(chains) == 0

def test_tree_representation_with_repeated_nodes():
    """Test that the string representation correctly shows and handles repeated nodes."""
    # Create a test structure with repeated nodes
    # tx1 -> tx2 -> tx3
    #  |      \
    #  |       \-> tx4
    #  |            |
    #  +------------+

    # Create CoinJoin objects
    cj1 = _create_coinjoin("tx1", 100, [_create_participant([_create_tx_input("prev", 0, 1.0)], _create_tx_output(0, 0.9))])
    cj2 = _create_coinjoin("tx2", 110, [_create_participant([_create_tx_input("tx1", 0, 0.9)], _create_tx_output(0, 0.8))])
    cj3 = _create_coinjoin("tx3", 120, [_create_participant([_create_tx_input("tx2", 0, 0.8)], _create_tx_output(0, 0.7))])
    cj4 = _create_coinjoin("tx4", 130, [_create_participant([_create_tx_input("tx2", 1, 0.5), _create_tx_input("tx1", 1, 0.5)], _create_tx_output(0, 0.9))])

    # Create a tree and add nodes
    tree = CoinJoinTree(analysis_type="test")
    
    # Add CoinJoins
    node1 = CoinJoinLeafNode(cj1)
    node2 = CoinJoinLeafNode(cj2)
    node3 = CoinJoinLeafNode(cj3)
    node4 = CoinJoinLeafNode(cj4)
    
    tree.add_coinjoin(node1)
    tree.add_coinjoin(node2)
    tree.add_coinjoin(node3)
    tree.add_coinjoin(node4)
    
    # Add connections to create the DAG structure
    tree.add_connection("tx1", "tx2")
    tree.add_connection("tx2", "tx3")
    tree.add_connection("tx2", "tx4")
    tree.add_connection("tx1", "tx4")  # This creates a repeated node situation
    
    # Get the string representation
    tree_str = str(tree)
    
    # Verify the representation contains the expected elements
    assert "CoinJoinTree" in tree_str
    assert "tx1" in tree_str
    assert "tx2" in tree_str
    assert "tx3" in tree_str
    assert "tx4" in tree_str
    assert "[REPEATED - not expanded]" in tree_str  # This should be present for the repeated node
    
    # Check if tx4 is marked as repeated when accessed from tx1 (second time)
    # We can do this by analyzing the structure of the tree string
    lines = tree_str.strip().split("\n")
    
    # Find the line where tx4 is repeated
    repeated_line = None
    for line in lines:
        if "tx4" in line and "[REPEATED - not expanded]" in line:
            repeated_line = line
            break
            
    assert repeated_line is not None, "No repeated node found in the representation"
    
    # The representation should only show tx3 being expanded once
    tx3_count = sum(1 for line in lines if "tx3" in line)
    assert tx3_count == 1, f"tx3 should appear exactly once, found {tx3_count} times"
    
    # The node tx4 should appear twice (once as normal, once as repeated)
    tx4_count = sum(1 for line in lines if "tx4" in line)
    assert tx4_count == 2, f"tx4 should appear twice (once normal, once repeated), found {tx4_count} times"


# ── JoinMarket-NG maker sessions (zero-fee maker legs of a tumbler) ──────────

def test_blackbox_chain_follows_zero_fee_maker_hop():
    cj1 = _create_coinjoin("tx1", 100, [
        _create_participant([_create_tx_input("prev_a", 0, 1.1)], _create_tx_output(0, 1.0), role="taker")
    ])
    # Tumbler now in a maker session: spends tx1 output as a zero-fee maker
    cj2 = _create_coinjoin("tx2", 101, [
        _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.5),
                            _create_tx_output(2, 0.5), role="zero_fee_maker"),
        _create_participant([_create_tx_input("prev_b", 0, 0.6)], _create_tx_output(1, 0.5), role="taker"),
    ])
    # Back to taking, spending the zero-fee maker's change
    cj3 = _create_coinjoin("tx3", 102, [
        _create_participant([_create_tx_input("tx2", 2, 0.5)], _create_tx_output(0, 0.4), role="taker")
    ])
    chains = identify_coinjoin_chains([cj1, cj2, cj3], 'blackbox')
    assert len(chains) == 1
    assert [cj.txid for cj in chains[0].coinjoins] == ["tx1", "tx2", "tx3"]
    assert chains[0].connections == {"tx1": ["tx2"], "tx2": ["tx3"]}


def test_blackbox_chain_does_not_follow_honest_maker_hop():
    cj1 = _create_coinjoin("tx1", 100, [
        _create_participant([_create_tx_input("prev_a", 0, 1.1)], _create_tx_output(0, 1.0), role="taker")
    ])
    cj2 = _create_coinjoin("tx2", 101, [
        _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.5), role="maker"),
        _create_participant([_create_tx_input("prev_b", 0, 0.6)], _create_tx_output(1, 0.5), role="taker"),
    ])
    chains = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert len(chains) == 2


def test_whitebox_zero_fee_maker_counts_only_for_taking_clients():
    # clientA tumbles (takes in tx1, zero-fee makes in tx2); clientM is an ordinary maker with delta 0
    cj1 = _create_coinjoin("tx1", 100, [
        _create_participant([_create_tx_input("prev_a", 0, 1.1, client="clientA")],
                            _create_tx_output(0, 1.0, client="clientA"), role="taker", client="clientA")
    ])
    cj2 = _create_coinjoin("tx2", 101, [
        _create_participant([_create_tx_input("tx1", 0, 1.0, client="clientA")],
                            _create_tx_output(0, 0.5, client="clientA"), role="zero_fee_maker", client="clientA"),
        _create_participant([_create_tx_input("prev_m", 0, 0.5, client="clientM")],
                            _create_tx_output(1, 0.5, client="clientM"), role="zero_fee_maker", client="clientM"),
        _create_participant([_create_tx_input("prev_b", 0, 0.6, client="clientB")],
                            _create_tx_output(2, 0.5, client="clientB"), role="taker", client="clientB"),
    ])
    chains = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    assert len(chains) == 1
    assert chains[0].connections == {"tx1": ["tx2"]}
    assert chains[0].tumbler_clients == {"clientA", "clientB"}


def test_chain_attributor_keeps_two_tumblers_apart():
    from joinmarket.common.analysis_config import AnalysisConfig
    from joinmarket.common.chain_based_attributor import ChainBasedAttributor

    # Parent: taker T and zero-fee maker Z (another tumbler) share tx1
    t_change = _create_tx_output(2, 0.1)
    z_change = _create_tx_output(3, 0.2)
    cj1 = _create_coinjoin("tx1", 100, [
        _create_participant([_create_tx_input("prev_t", 0, 1.2)], _create_tx_output(0, 1.0), t_change, role="taker"),
        _create_participant([_create_tx_input("prev_z", 0, 1.2)], _create_tx_output(1, 1.0), z_change, role="zero_fee_maker"),
    ])
    # Child 1: Z takes, spending its change and its cj output from tx1
    cj2 = _create_coinjoin("tx2", 101, [
        _create_participant([_create_tx_input("tx1", 3, 0.2), _create_tx_input("tx1", 1, 1.0)],
                            _create_tx_output(0, 0.9), role="taker", client="Z"),
    ])
    # Child 2: T takes, spending only its cj output from tx1
    cj3 = _create_coinjoin("tx3", 102, [
        _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker"),
    ])
    chains = identify_coinjoin_chains([cj1, cj2, cj3], 'blackbox')
    assert len(chains) == 1
    ChainBasedAttributor(AnalysisConfig(maker_sessions=True)).attribute_chain(chains[0])

    t, z = cj1.participants
    assert z.client == "Z"
    assert z.cj_output is not None and z.cj_output.n == 1
    assert t.cj_output is not None and t.cj_output.n == 0
    assert t.client != "Z"
    assert cj3.participants[0].client == t.client
