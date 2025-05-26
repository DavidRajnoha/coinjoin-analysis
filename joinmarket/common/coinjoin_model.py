"""
Consolidated CoinJoin data model for both blackbox and whitebox analysis.

This module provides dataclasses for representing CoinJoin transactions in a consistent format,
regardless of whether they were detected via blackbox analysis (sudoku) or whitebox simulation data.
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

# Remove direct imports of visualization modules
# from joinmarket.visualisation.cj_flow_graph_data import CoinJoinGraphBuilder
# from joinmarket.visualisation.tx_output import TxOutputRegistry

@dataclass
class TxInput:
    """A single transaction input with reference to previous output."""
    txid: str  # Previous transaction ID
    vout: int  # Previous output index
    value: float  # BTC value
    address: Optional[str] = None  # Source address if known
    client: Optional[str] = None  # Owner client if known


@dataclass
class TxOutput:
    """A single transaction output."""
    n: int  # Output index
    value: float  # BTC value
    address: Optional[str] = None  # Destination address if known
    output_txid: Optional[str] = None  # Transaction ID if spent
    client: Optional[str] = None  # Owner client if known
    is_change: bool = False  # Whether this is likely a change output


@dataclass
class CoinJoinParticipant:
    """
    A single participant in a CoinJoin transaction.
    
    Each participant contributes inputs and receives outputs (CoinJoin amount and possibly change).
    The role can be 'maker', 'taker', or 'unknown' depending on the information available.
    """
    inputs: List[TxInput]  # List of inputs provided by this participant
    cj_output: TxOutput  # The CoinJoin output belonging to this participant
    change_output: Optional[TxOutput] = None  # Change output if any
    role: str = "unknown"  # 'maker', 'taker', or 'unknown'
    client: Optional[str] = None  # Client ID if known
    delta: float = 0.0  # Difference between outputs and inputs (negative = fee paid)
    
    @property
    def input_value(self) -> float:
        """Total value of all inputs."""
        return sum(inp.value for inp in self.inputs)
    
    @property
    def output_value(self) -> float:
        """Total value of all outputs."""
        return self.cj_output.value + (self.change_output.value if self.change_output else 0)


@dataclass
class CoinJoin:
    """
    A complete CoinJoin transaction with all participants.
    
    Unified model that works for both blackbox and whitebox approaches.
    It preserves all transaction details including indices needed for attribution.
    """
    txid: str  # Transaction ID
    block_height: int  # Block height where this tx was confirmed
    tx: Dict[str, Any]  # Full transaction data
    participants: List[CoinJoinParticipant] = field(default_factory=list)  # All participants
    meta: Dict[str, Any] = field(default_factory=dict)  # Optional metadata
    
    @property
    def input_clients(self) -> Set[str]:
        """Get all client IDs that provided inputs."""
        result = set()
        for p in self.participants:
            if p.client:
                result.add(p.client)
            for inp in p.inputs:
                if inp.client:
                    result.add(inp.client)
        return result
        
    @property
    def output_clients(self) -> Set[str]:
        """Get all client IDs that received outputs."""
        result = set()
        for p in self.participants:
            if p.client:
                result.add(p.client)
            if p.cj_output.client:
                result.add(p.cj_output.client)
            if p.change_output and p.change_output.client:
                result.add(p.change_output.client)
        return result
    
    @property
    def cj_amount(self) -> float:
        """Get the CoinJoin amount (equal outputs)."""
        if not self.participants:
            return 0.0
        return self.participants[0].cj_output.value
    
    @property
    def miner_fee(self) -> float:
        """Calculate the miner fee as sum of all deltas."""
        return -sum(p.delta for p in self.participants)
    
    @classmethod
    def from_whitebox(cls, txid: str, tx: Dict[str, Any], block: Dict[str, Any], 
                     address_to_client: Dict[str, str], tx_map: Optional[Dict[str, Any]] = None) -> CoinJoin:
        """
        Create a CoinJoin instance from whitebox data using address-to-client mapping.
        
        Args:
            txid: Transaction ID
            tx: Transaction data
            block: Block data
            address_to_client: Mapping from addresses to client IDs
            tx_map: Optional map of transaction IDs to transaction data for input lookup
            
        Returns:
            A CoinJoin instance with full attribution
        """
        # Find the CoinJoin denomination (most common output value)
        output_values = [o['value'] for o in tx['vout']]
        value_counts = {}
        for v in output_values:
            value_counts[v] = value_counts.get(v, 0) + 1
        
        # Find the most common value that appears multiple times
        cj_value = max((v for v, c in value_counts.items() if c > 1), 
                       key=lambda v: value_counts[v], default=0)
        
        # Collect input addresses and their values
        input_addrs = set()
        inputs_by_client = defaultdict(list)
        all_inputs = []
        
        for i, vin in enumerate(tx['vin']):
            if 'txid' not in vin or 'vout' not in vin:
                continue
                
            # Try to find the previous transaction
            prev_tx = None
            if tx_map and vin['txid'] in tx_map:
                prev_tx = tx_map[vin['txid']]['tx']
            elif hasattr(tx, 'prev_tx_map') and vin['txid'] in tx.prev_tx_map:
                prev_tx = tx.prev_tx_map[vin['txid']]['tx']
                
            if not prev_tx:
                continue
                
            # Get previous output details
            prev_out = next((o for o in prev_tx['vout'] if o['n'] == vin['vout']), None)
            if not prev_out:
                continue
                
            value = prev_out.get('value', 0.0)
            addr = prev_out.get('scriptPubKey', {}).get('address')
            client = address_to_client.get(addr) if addr else None
            
            if addr:
                input_addrs.add(addr)
            
            # Create the input with all available info
            inp = TxInput(
                txid=vin['txid'],
                vout=vin['vout'],
                value=value,
                address=addr,
                client=client
            )
            
            all_inputs.append(inp)
            if client:
                inputs_by_client[client].append(inp)
        
        # Create output objects and categorize them
        outputs_by_client = defaultdict(list)
        cj_outputs = []
        change_outputs = []
        
        for out in tx['vout']:
            addr = out.get('scriptPubKey', {}).get('address')
            client = address_to_client.get(addr) if addr else None
            is_change = out['value'] != cj_value
            
            output = TxOutput(
                n=out['n'],
                value=out['value'],
                address=addr,
                client=client,
                is_change=is_change
            )
            
            if client:
                outputs_by_client[client].append(output)
                
            if out['value'] == cj_value and not is_change:
                cj_outputs.append(output)
            elif is_change:
                change_outputs.append(output)
        
        # Create participants
        participants = []
        used_inputs = set()
        used_cj_outputs = set()
        used_change_outputs = set()
        
        # First, create participants for clients we can fully attribute
        for client, client_inputs in inputs_by_client.items():
            # Find matching CoinJoin output
            client_cj_out = next((o for o in cj_outputs 
                               if o.client == client and o.n not in used_cj_outputs), None)
            
            if not client_cj_out:
                continue
                
            # Find matching change output if any
            client_change = next((o for o in change_outputs 
                               if o.client == client and o.n not in used_change_outputs), None)
            
            # Mark as used
            used_cj_outputs.add(client_cj_out.n)
            if client_change:
                used_change_outputs.add(client_change.n)
            for inp in client_inputs:
                used_inputs.add((inp.txid, inp.vout))
            
            # Calculate delta
            input_value = sum(inp.value for inp in client_inputs)
            output_value = client_cj_out.value
            if client_change:
                output_value += client_change.value
            delta = output_value - input_value
            
            # Determine role - maker typically has a positive fee
            role = "unknown"
            if delta >= 0:
                role = "maker"
            else:
                role = "taker"
            
            participants.append(CoinJoinParticipant(
                inputs=client_inputs,
                cj_output=client_cj_out,
                change_output=client_change,
                role=role,
                client=client,
                delta=delta
            ))
        
        # For remaining unattributed outputs, create participants with empty inputs
        for cj_out in cj_outputs:
            if cj_out.n in used_cj_outputs:
                continue
                
            # Find matching change output if any
            matching_change = None
            if cj_out.client:
                matching_change = next((ch for ch in change_outputs 
                                      if ch.client == cj_out.client 
                                      and ch.n not in used_change_outputs), None)
                if matching_change:
                    used_change_outputs.add(matching_change.n)
            
            participants.append(CoinJoinParticipant(
                inputs=[],  # We don't have attribution information
                cj_output=cj_out,
                change_output=matching_change,
                client=cj_out.client
            ))
        
        return cls(
            txid=txid,
            block_height=block.get('height', 0),
            tx=tx,
            participants=participants,
            meta={'whitebox_analysis': True}
        )
    
    def enrich_with_client_info(self, address_to_client: Dict[str, str]) -> None:
        """
        Enrich this CoinJoin with client information from address mapping.
        
        Args:
            address_to_client: Mapping from addresses to client IDs
        """
        for p in self.participants:
            # Enrich inputs
            for inp in p.inputs:
                if inp.address and inp.address in address_to_client:
                    inp.client = address_to_client[inp.address]
            
            # Enrich outputs
            if p.cj_output.address and p.cj_output.address in address_to_client:
                p.cj_output.client = address_to_client[p.cj_output.address]
            
            if p.change_output and p.change_output.address and p.change_output.address in address_to_client:
                p.change_output.client = address_to_client[p.change_output.address]
            
            # Determine participant client based on outputs
            if p.cj_output.client:
                p.client = p.cj_output.client
            elif p.change_output and p.change_output.client:
                p.client = p.change_output.client
    
    def get_output_clients_list(self) -> List[Optional[str]]:
        """
        Return a list of client IDs for each output in vout order.
        Used for compatibility with the existing client provider approach.
        
        Returns:
            A list of client IDs or None for each output in the transaction
        """
        # Create a list with None for each output
        result = [None] * len(self.tx.get('vout', []))
        
        # Fill in the client IDs for outputs we know about
        for p in self.participants:
            if p.cj_output.n < len(result):
                result[p.cj_output.n] = p.client
            
            if p.change_output and p.change_output.n < len(result):
                result[p.change_output.n] = p.client
        
        return result

# Visualization utility for CoinJoin model
def generate_coinjoin_flow_vis_graph(cj_objs, client_roles=None, show_changes=True):
    """
    Generate a flow visualization for a set of CoinJoin objects.
    
    Args:
        cj_objs: List of CoinJoin objects
        client_roles: Optional dictionary mapping client names to their roles
        show_changes: Whether to show change outputs in the visualization
        
    Returns:
        A pyvis Network object for visualization
    """
    # Import visualization modules here to avoid circular imports
    from joinmarket.visualisation.cj_flow_graph_data import CoinJoinGraphBuilder
    
    # If no client roles provided, use empty dict
    client_roles = client_roles or {}
    
    # Apply client roles to CoinJoin participants
    for cj in cj_objs:
        for participant in cj.participants:
            if participant.client and participant.client in client_roles:
                participant.role = client_roles[participant.client]
    
    # Create the graph builder
    builder = CoinJoinGraphBuilder(coinjoins=cj_objs, show_changes=show_changes)
    
    # Build the graph
    return builder.generate_vis_network()
