from joinmarket.common.coinjoin_model import CoinJoin, CoinJoinParticipant, TxOutput
from joinmarket.common.coinjoin_chain import CoinJoinTree, CoinJoinLeafNode
from joinmarket.unified_report.unified_report_data import compute_chain_purity


def _chain(cid, txids, kind):
    tree = CoinJoinTree(id=cid, analysis_type=kind)
    for t in txids:
        cj = CoinJoin(txid=t, block_height=1, tx={}, participants=[
            CoinJoinParticipant(inputs=[], cj_output=TxOutput(0, 1.0), role='taker')])
        tree.add_coinjoin(CoinJoinLeafNode(cj))
    return tree


def test_chain_purity_flags_glued_chains_and_skips_singletons():
    wb = [_chain("w1", ["a", "b", "c"], "whitebox"), _chain("w2", ["d", "e"], "whitebox")]
    bb = [_chain("pure", ["a", "b"], "blackbox"),
          _chain("glued", ["c", "d", "e"], "blackbox"),
          _chain("single", ["x"], "blackbox")]
    m = compute_chain_purity(bb, wb)
    assert m['chain_purity_specificity_chains'] == 50.0
    assert m['chain_purity_specificity_txs'] == 40.0
    assert m['impure_blackbox_chains'] == [
        {'blackbox_chain_id': 'glued', 'length': 3, 'whitebox_composition': {'w1': 1, 'w2': 2}}]


def test_chain_purity_none_without_multi_tx_chains():
    m = compute_chain_purity([_chain("s", ["x"], "blackbox")], [])
    assert m['chain_purity_specificity_chains'] is None
