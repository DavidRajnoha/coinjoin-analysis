from __future__ import annotations
from typing import List, Optional, Set, Dict, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

# Assuming CoinJoin and its components are in coinjoin_model.py in the same directory
from .coinjoin_model import CoinJoin, CoinJoinParticipant, TxOutput, TxInput


@dataclass
class CoinjoinChain:
    """
    Represents a chain of CoinJoin transactions linked by taker participants.

    A chain is formed when an output of a CoinJoin transaction (specifically,
    an output attributed to a 'taker' participant) is used as an input
    in a subsequent CoinJoin transaction by a 'taker' participant.

    For 'whitebox' analysis, an additional constraint applies: the client entity
    associated with the linking taker output and subsequent taker input must match.
    For 'blackbox' analysis, this client matching is not performed.
    """
    id: str  # Unique identifier for the chain
    analysis_type: str  # 'blackbox' or 'whitebox', indicating the method of chain identification
    coinjoins: List[CoinJoin] = field(default_factory=list)  # Sequence of CoinJoins in the chain

    def __post_init__(self):
        if not self.id:
            raise ValueError("CoinjoinChain must have an id.")
        # Allow coinjoins list to be empty
        # if not self.coinjoins:
        #     raise ValueError("CoinjoinChain must contain at least one CoinJoin transaction.")
        if self.analysis_type not in ['blackbox', 'whitebox']:
            raise ValueError("analysis_type must be 'blackbox' or 'whitebox'.")
        # Ensure all elements in coinjoins are indeed CoinJoin objects
        for cj in self.coinjoins:
            if not isinstance(cj, CoinJoin):
                raise TypeError(f"All elements in coinjoins list must be CoinJoin objects, got {type(cj)}")

    @property
    def length(self) -> int:
        """Number of CoinJoins in the chain."""
        return len(self.coinjoins)

    @property
    def start_block_height(self) -> Optional[int]:
        """Block height of the first CoinJoin in the chain."""
        if self.coinjoins:
            return self.coinjoins[0].block_height
        return None

    @property
    def end_block_height(self) -> Optional[int]:
        """Block height of the last CoinJoin in the chain."""
        if self.coinjoins:
            return self.coinjoins[-1].block_height
        return None

    @property
    def start_block(self) -> Optional[int]:
        if not self.coinjoins:
            return None
        return min(cj.block_height for cj in self.coinjoins if cj.block_height is not None)

    @property
    def end_block(self) -> Optional[int]:
        if not self.coinjoins:
            return None
        return max(cj.block_height for cj in self.coinjoins if cj.block_height is not None)

    @property
    def duration_blocks(self) -> int:
        if not self.coinjoins or self.start_block is None or self.end_block is None:
            return 0
        # If only one CJ, duration is conventionally 0 or 1. Let's use 0 for simplicity.
        # Or, more accurately, if start == end, duration is 0.
        return self.end_block - self.start_block

    @property
    def total_cj_amount(self) -> float:
        if not self.coinjoins:
            return 0.0
        return sum(cj.cj_amount for cj in self.coinjoins if hasattr(cj, 'cj_amount') and cj.cj_amount is not None)

    @property
    def avg_cj_amount(self) -> float:
        if not self.coinjoins or self.length == 0:
            return 0.0
        total_amount = self.total_cj_amount
        return total_amount / self.length

    @property
    def taker_clients(self) -> Set[str]:
        clients = set()
        if self.analysis_type == 'whitebox':
            for cj in self.coinjoins:
                for participant in cj.participants:
                    if participant.role == 'taker' and participant.client:
                        clients.add(participant.client)
        else:
            for cj in self.coinjoins:
                for p in cj.participants:
                    if p.role == "taker" and hasattr(p, 'client_identifier') and p.client_identifier:
                        clients.add(p.client_identifier)
        return clients

    def __repr__(self) -> str:
        return f"CoinjoinChain(id='{self.id}', count={self.length}, type='{self.analysis_type}', blocks=[{self.start_block_height}...{self.end_block_height}])"


def identify_coinjoin_chains(
    all_coinjoins: List[CoinJoin],
    analysis_type: str
) -> List[CoinjoinChain]:
    """
    Identifies and constructs CoinjoinChain objects from a list of CoinJoin transactions.

    Args:
        all_coinjoins: A list of all CoinJoin objects.
        analysis_type: Either 'blackbox' or 'whitebox'.

    Returns:
        A list of identified CoinjoinChain objects.
    """
    if analysis_type not in ['blackbox', 'whitebox']:
        raise ValueError("analysis_type must be 'blackbox' or 'whitebox'.")

    # Sort CJs to ensure deterministic chain formation and process earlier transactions first.
    sorted_cjs = sorted(all_coinjoins, key=lambda cj: (cj.block_height, cj.txid))
    
    # Map outputs to the CJs and participants that consume them as inputs
    # Key: (source_tx_id_of_output, output_index_n)
    # Value: List of {'consumer_cj': CoinJoin, 'consumer_participant': CoinJoinParticipant}
    output_consumers_map: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for cj_obj in sorted_cjs: # Renamed cj to cj_obj to avoid conflict with CoinJoin type hint if used locally
        for participant in cj_obj.participants:
            for inp in participant.inputs:
                output_consumers_map[(inp.txid, inp.vout)].append({
                    'consumer_cj': cj_obj,
                    'consumer_participant': participant
                })

    identified_chains: List[CoinjoinChain] = []
    # Keep track of CJ txids that have already been incorporated into a chain
    cjs_in_a_chain: Set[str] = set()
    chain_counter = 0

    for start_cj in sorted_cjs:
        if start_cj.txid in cjs_in_a_chain:
            continue  # This CJ is already part of another chain

        current_chain_cjs: List[CoinJoin] = [start_cj]
        # temp_chain_txids tracks CJs in the current chain being built to prevent cycles within it.
        temp_chain_txids: Set[str] = {start_cj.txid}
        
        current_cj_in_chain = start_cj
        can_extend_chain = True

        while can_extend_chain:
            found_next_link = False
            # Iterate through participants of the current last CJ in the chain
            for p_current in current_cj_in_chain.participants:
                if p_current.role != 'taker':
                    continue

                # Consider the main cj_output for linking by takers.
                # If change outputs or other outputs should also be considered, this list would expand.
                potential_linking_outputs = [p_current.cj_output]
                # if p_current.change_output: # Example if change outputs were also considered
                #     potential_linking_outputs.append(p_current.change_output)

                for linking_output in potential_linking_outputs:
                    if linking_output is None: 
                        continue
                    
                    output_key = (current_cj_in_chain.txid, linking_output.n)
                    
                    if output_key in output_consumers_map:
                        # Consumers are already sorted by virtue of iterating sorted_cjs earlier
                        for consumer_info in output_consumers_map[output_key]:
                            next_potential_cj = consumer_info['consumer_cj']
                            p_next = consumer_info['consumer_participant']

                            # Avoid cycles within the current chain attempt
                            if next_potential_cj.txid in temp_chain_txids:
                                continue
                            # Avoid using a CJ already part of a *confirmed* chain
                            if next_potential_cj.txid in cjs_in_a_chain:
                                continue

                            if p_next.role == 'taker':
                                is_valid_link = True
                                if analysis_type == 'whitebox':
                                    if not (p_current.client and p_next.client and \
                                            p_current.client == p_next.client):
                                        is_valid_link = False
                                
                                if is_valid_link:
                                    current_chain_cjs.append(next_potential_cj)
                                    temp_chain_txids.add(next_potential_cj.txid)
                                    current_cj_in_chain = next_potential_cj
                                    found_next_link = True
                                    break  # Move to extend from the new end of the chain
                        if found_next_link:
                            break  # Exit participant loop for p_current
                if found_next_link:
                    break # Restart search (while can_extend_chain) from the new current_cj_in_chain
            
            if not found_next_link:
                can_extend_chain = False # No further extension possible for this chain

        # Chain construction for this starting_cj is complete.
        if current_chain_cjs: # A chain must have at least one CJ.
            # Add all CJs in this valid chain to the global set of processed CJs.
            for cj_in_chain in current_chain_cjs:
                cjs_in_a_chain.add(cj_in_chain.txid)
            
            chain_id = f"{analysis_type}_chain_{chain_counter}_{current_chain_cjs[0].txid}"
            chain_counter += 1
            identified_chains.append(
                CoinjoinChain(id=chain_id, coinjoins=current_chain_cjs, analysis_type=analysis_type)
            )
            
    return identified_chains
