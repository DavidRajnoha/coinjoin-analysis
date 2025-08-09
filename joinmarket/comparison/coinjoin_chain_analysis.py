"""
CoinJoin chain analysis utilities: identification, serialization, and summary helpers.
"""
from typing import List, Dict, Any
from joinmarket.common.coinjoin_chain import CoinJoinTree, identify_coinjoin_chains
from joinmarket.comparison.compare_coinjoin import compare_coinjoin_chains


def serialize_cj_chain_for_report(chain: CoinJoinTree, chain_type: str) -> Dict[str, Any]:
    unique_transactions = chain.nodes
    chain_data = {
        "id": chain.id,
        "analysis_type": getattr(chain, 'analysis_type', None),
        "chain_type": chain_type,
        "length": chain.length(),
        "transactions": [{
            "txid": node.txid,
            "block_height": node.get_coinjoin().block_height,
            "participants": len(node.get_coinjoin().participants),
            "amount": node.get_coinjoin().cj_amount
        } for node in unique_transactions]
    }
    if hasattr(chain, 'tree_representation'):
        chain_data["tree_representation"] = chain.tree_representation
    else:
        chain_data["tree_representation"] = str(chain)
    chain_data.update({
        "start_block": chain.start_block(),
        "end_block": chain.end_block(),
        "duration_blocks": chain.duration_blocks(),
        "total_amount": chain.total_cj_amount(),
        "avg_amount": chain.avg_cj_amount()
    })
    return chain_data


def get_identified_chains_and_txids(cj_objs: List[Any], chain_type: str):
    chains = identify_coinjoin_chains(cj_objs, chain_type)
    txids = sorted({node.txid for chain in chains for node in chain.nodes})
    return chains, txids


__all__ = [
    "serialize_cj_chain_for_report",
    "get_identified_chains_and_txids",
    "identify_coinjoin_chains",
    "compare_coinjoin_chains",
    "CoinJoinTree"
]
