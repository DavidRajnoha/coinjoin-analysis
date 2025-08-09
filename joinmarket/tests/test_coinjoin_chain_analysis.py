import pytest
from joinmarket.comparison.coinjoin_chain_analysis import (
    serialize_cj_chain_for_report,
    get_identified_chains_and_txids
)
from joinmarket.common.coinjoin_chain import CoinJoinTree

class DummyNode:
    def __init__(self, txid, block_height, participants, cj_amount):
        self.txid = txid
        self._coinjoin = type('CJ', (), {
            'block_height': block_height,
            'participants': [None] * participants,
            'cj_amount': cj_amount
        })()
    def get_coinjoin(self):
        return self._coinjoin

class DummyChain:
    def __init__(self, id, nodes):
        self.id = id
        self.analysis_type = 'blackbox'
        self.nodes = nodes
        self.tree_representation = f"Chain {id}"
    def length(self):
        return len(self.nodes)
    def start_block(self):
        return min(node.get_coinjoin().block_height for node in self.nodes)
    def end_block(self):
        return max(node.get_coinjoin().block_height for node in self.nodes)
    def duration_blocks(self):
        return self.end_block() - self.start_block()
    def total_cj_amount(self):
        return sum(node.get_coinjoin().cj_amount for node in self.nodes)
    def avg_cj_amount(self):
        return self.total_cj_amount() / max(1, self.length())


def test_serialize_cj_chain_for_report():
    nodes = [DummyNode(f"txid{i}", 100+i, 2, 0.1*i) for i in range(3)]
    chain = DummyChain("chain1", nodes)
    result = serialize_cj_chain_for_report(chain, "blackbox")
    assert result["id"] == "chain1"
    assert result["chain_type"] == "blackbox"
    assert result["length"] == 3
    assert result["transactions"][0]["txid"] == "txid0"
    assert result["transactions"][1]["block_height"] == 101
    assert result["tree_representation"] == "Chain chain1"
    assert result["start_block"] == 100
    assert result["end_block"] == 102
    assert result["duration_blocks"] == 2
    assert abs(result["total_amount"] - 0.3) < 1e-8
    assert abs(result["avg_amount"] - 0.1) < 1e-8

def test_get_identified_chains_and_txids():
    # This test assumes identify_coinjoin_chains returns input chains as is
    # (actual logic is more complex, but we just check passthrough here)
    dummy_chains = [DummyChain("c1", [DummyNode("txid1", 1, 1, 0.5)]), DummyChain("c2", [DummyNode("txid2", 2, 2, 1.0)])]
    # Patch identify_coinjoin_chains to return dummy_chains
    import joinmarket.comparison.coinjoin_chain_analysis as cca
    orig_func = cca.identify_coinjoin_chains
    cca.identify_coinjoin_chains = lambda objs, t: dummy_chains
    chains, txids = get_identified_chains_and_txids([None], 'blackbox')
    assert chains == dummy_chains
    assert set(txids) == {"txid1", "txid2"}
    cca.identify_coinjoin_chains = orig_func
