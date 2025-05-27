import pytest
from typing import List, Optional, Dict, Any
from joinmarket.common.coinjoin_model import CoinJoin, TxInput, TxOutput, CoinJoinParticipant
from joinmarket.common.coinjoin_chain import identify_coinjoin_chains, CoinjoinChain

# Helper function to create mock TxInput
def _create_tx_input(txid: str, vout: int, value: float, address: Optional[str] = None, client: Optional[str] = None) -> TxInput:
    return TxInput(txid=txid, vout=vout, value=value, address=address, client=client)

# Helper function to create mock TxOutput
def _create_tx_output(n: int, value: float, address: Optional[str] = None, client: Optional[str] = None, is_change: bool = False) -> TxOutput:
    return TxOutput(n=n, value=value, address=address, client=client, is_change=is_change)

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

def test_single_coinjoin():
    cj1 = _create_coinjoin("tx1", 100, [
        _create_participant([_create_tx_input("prev_tx_a", 0, 1.0)], _create_tx_output(0, 1.0), role="taker")
    ])
    chains_bb = identify_coinjoin_chains([cj1], 'blackbox')
    assert len(chains_bb) == 1
    assert chains_bb[0].length == 1
    assert chains_bb[0].coinjoins[0].txid == "tx1"

    chains_wb = identify_coinjoin_chains([cj1], 'whitebox')
    assert len(chains_wb) == 1
    assert chains_wb[0].length == 1
    assert chains_wb[0].coinjoins[0].txid == "tx1"

def test_multiple_unlinked_coinjoins():
    cj1 = _create_coinjoin("tx1", 100, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    cj2 = _create_coinjoin("tx2", 101, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    chains = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert len(chains) == 2
    assert chains[0].length == 1
    assert chains[1].length == 1
    assert chains[0].coinjoins[0].txid == "tx1"
    assert chains[1].coinjoins[0].txid == "tx2"

def test_simple_blackbox_chain():
    p1_cj1 = _create_participant([_create_tx_input("prev_a", 0, 1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])
    
    chains = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert len(chains) == 1
    assert chains[0].length == 2
    assert chains[0].coinjoins[0].txid == "tx1"
    assert chains[0].coinjoins[1].txid == "tx2"

def test_simple_whitebox_chain_matching_clients():
    p1_cj1 = _create_participant([_create_tx_input("prev_a", 0, 1.1)], _create_tx_output(0, 1.0, client="clientA"), role="taker", client="clientA")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0, client="clientA")], _create_tx_output(0, 0.9, client="clientA"), role="taker", client="clientA")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    chains = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    assert len(chains) == 1
    assert chains[0].length == 2
    assert chains[0].coinjoins[0].txid == "tx1"
    assert chains[0].coinjoins[1].txid == "tx2"
    assert chains[0].taker_clients == {"clientA"}

def test_whitebox_chain_non_matching_clients():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0, client="clientA"), role="taker", client="clientA")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0, client="clientB")], _create_tx_output(0, 0.9, client="clientB"), role="taker", client="clientB")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    chains = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    assert len(chains) == 2 
    assert chains[0].length == 1
    assert chains[0].coinjoins[0].txid == "tx1"
    assert chains[1].length == 1
    assert chains[1].coinjoins[0].txid == "tx2"

def test_whitebox_chain_missing_client_info():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0, client="clientA"), role="taker", client="clientA")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker") 
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    chains = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    assert len(chains) == 2

def test_link_via_non_taker_participant():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="maker")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])
    
    chains = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert len(chains) == 2

def test_longer_chain_three_cjs_blackbox():
    p1_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p1_cj1])

    p1_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(1, 0.9), role="taker")
    cj2 = _create_coinjoin("tx2", 101, [p1_cj2])

    p1_cj3 = _create_participant([_create_tx_input("tx2", 1, 0.9)], _create_tx_output(0, 0.8), role="taker")
    cj3 = _create_coinjoin("tx3", 102, [p1_cj3])

    chains = identify_coinjoin_chains([cj1, cj2, cj3], 'blackbox')
    assert len(chains) == 1
    assert chains[0].length == 3
    assert [cj.txid for cj in chains[0].coinjoins] == ["tx1", "tx2", "tx3"]

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
    
    chain_txids = sorted(['-'.join(cj.txid for cj in chain.coinjoins) for chain in chains])
    assert "tx1-tx2" in chain_txids
    assert "tx3-tx4" in chain_txids
    assert "tx5" in chain_txids
    assert len(chain_txids) == 3


def test_chain_id_generation():
    cj1 = _create_coinjoin("tx100", 100, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    cj2 = _create_coinjoin("tx200", 101, [_create_participant([], _create_tx_output(0, 1.0), role="taker")])
    
    chains_bb = identify_coinjoin_chains([cj1, cj2], 'blackbox')
    assert chains_bb[0].id == "blackbox_chain_0_tx100" 
    assert chains_bb[1].id == "blackbox_chain_1_tx200"

    chains_wb = identify_coinjoin_chains([cj1, cj2], 'whitebox')
    assert chains_wb[0].id == "whitebox_chain_0_tx100"
    assert chains_wb[1].id == "whitebox_chain_1_tx200"

def test_branching_scenario_from_one_cj_output():
    p_cj1 = _create_participant([_create_tx_input("prev_a",0,1.1)], _create_tx_output(0, 1.0), role="taker")
    cj1 = _create_coinjoin("tx1", 100, [p_cj1])

    p_cj2 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.9), role="taker")
    cj2 = _create_coinjoin("tx2", 101, [p_cj2]) 

    p_cj3 = _create_participant([_create_tx_input("tx1", 0, 1.0)], _create_tx_output(0, 0.8), role="taker")
    cj3 = _create_coinjoin("tx3", 102, [p_cj3]) 

    all_cjs = [cj1, cj2, cj3]
    chains = identify_coinjoin_chains(all_cjs, 'blackbox')

    assert len(chains) == 2 
    chain_txids_set = {'-'.join(cj.txid for cj in chain.coinjoins) for chain in chains}
    
    assert "tx1-tx2" in chain_txids_set
    assert "tx3" in chain_txids_set
