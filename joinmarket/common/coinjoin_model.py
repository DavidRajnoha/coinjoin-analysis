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
    confidence: float = 0
    address: Optional[str] = None  # Source address if known
    client: Optional[str] = None  # Owner client if known


@dataclass
class TxOutput:
    """A single transaction output."""
    n: int  # Output index
    value: float  # BTC value
    confidence: float = 0
    address: Optional[str] = None  # Destination address if known
    output_txid: Optional[str] = None  # Transaction ID if spent
    client: Optional[str] = None  # Owner client if known
    is_change: bool = False  # Whether this is likely a change output

    def __hash__(self):
        return hash(self.address)


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
    # HEURISTIC: set to True if this participant was formed by a heuristic due to missing data mapping
    heuristic: bool = False
    # Fidelity bond information (JoinMarket-specific, whitebox only)
    fidelity_bond_enabled: Optional[bool] = None  # Whether this participant has a fidelity bond
    fidelity_bond_amount: Optional[int] = None  # Bond amount in satoshis
    fidelity_bond_locktime: Optional[str] = None  # Locktime in "YYYY-MM" format
    
    @property
    def input_value(self) -> float:
        """Total value of all inputs."""
        return sum(inp.value for inp in self.inputs)
    
    @property
    def output_value(self) -> float:
        """Total value of all outputs."""
        return self.cj_output.value + (self.change_output.value if self.change_output else 0)


# noinspection PyTypeChecker
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
    cj_outs: Set[TxOutput] = field(default_factory=set) # Newly added field used in chain attribution.
    # Refactor to populate this when creating the coinjoin and not assigning cj_outs to participants randomly
    # to be considered


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
        if not len(self.cj_outs):
            return self.participants[0].cj_output.value
        return list(self.cj_outs)[0].value
    
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
        # Diagnostics counters (print-based) to understand why inputs fail attribution
        diag = {
            'inputs_total': 0,
            'missing_prev_tx': 0,
            'missing_prev_out': 0,
            'missing_addr': 0,
            'has_addresses_list': 0,
            'unmapped_addr': 0,
            'clients_no_cj_out': 0,
            # Output-side diagnostics
            'outputs_total': 0,
            'outputs_unmapped': 0,
            'cj_outputs_total': 0,
            'clients_mismatch': 0,
            # Heuristic diagnostics
            'heuristic_assignments': 0,
        }
        # Small sample store for readability
        diag_samples: Dict[str, List[Any]] = defaultdict(list)
        def _sample(key: str, value: Any, limit: int = 3):
            arr = diag_samples[key]
            if len(arr) < limit:
                arr.append(value)
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
            diag['inputs_total'] += 1
            if 'txid' not in vin or 'vout' not in vin:
                continue
                
            # Try to find the previous transaction
            prev_tx = None
            if tx_map and vin['txid'] in tx_map:
                prev_tx = tx_map[vin['txid']]['tx']
            elif hasattr(tx, 'prev_tx_map') and vin['txid'] in tx.prev_tx_map:
                prev_tx = tx.prev_tx_map[vin['txid']]['tx']
                
            if not prev_tx:
                diag['missing_prev_tx'] += 1
                _sample('missing_prev_tx', {'txin_txid': vin.get('txid'), 'vout': vin.get('vout')})
                continue
                
            # Get previous output details
            prev_out = next((o for o in prev_tx['vout'] if o['n'] == vin['vout']), None)
            if not prev_out:
                diag['missing_prev_out'] += 1
                _sample('missing_prev_out', {'txin_txid': vin.get('txid'), 'vout': vin.get('vout')})
                continue
                
            value = prev_out.get('value', 0.0)
            spk = prev_out.get('scriptPubKey', {}) or {}
            addr = spk.get('address')
            # If no single address but there is an addresses list, record that for diagnostics
            if not addr:
                addrs = spk.get('addresses')
                if isinstance(addrs, list) and addrs:
                    diag['has_addresses_list'] += 1
                    _sample('has_addresses_list', {'txin_txid': vin.get('txid'), 'addr0': addrs[0]})
                else:
                    diag['missing_addr'] += 1
                    _sample('missing_addr', {'txin_txid': vin.get('txid')})
            client = address_to_client.get(addr) if addr else None
            if addr and client is None:
                diag['unmapped_addr'] += 1
                _sample('unmapped_addr', {'addr': addr})
            
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
        # Output-side diagnostics aggregation
        diag['outputs_total'] = len(tx['vout'])
        diag['outputs_unmapped'] = sum(1 for o in cj_outputs + change_outputs if o.client is None)
        diag['cj_outputs_total'] = len(cj_outputs)
        # Sample summaries only (limit size)
        inputs_counts_sample = {c: len(v) for c, v in list(inputs_by_client.items())[:5]}
        cj_counts_by_client = defaultdict(int)
        for o in cj_outputs:
            if o.client:
                cj_counts_by_client[o.client] += 1
        cj_counts_sample = dict(list(cj_counts_by_client.items())[:5])
        _sample('inputs_by_client_counts', inputs_counts_sample)
        _sample('cj_outputs_by_client', cj_counts_sample)
        # Clients that have inputs but no CJ output mapped
        clients_with_inputs = set(inputs_by_client.keys())
        clients_with_cj_out = set([o.client for o in cj_outputs if o.client])
        mismatch = sorted(list(clients_with_inputs - clients_with_cj_out))
        diag['clients_mismatch'] = len(mismatch)
        for m in mismatch[:5]:
            _sample('clients_mismatch', m)
        
        # Create participants
        participants = []
        used_inputs = set()
        used_cj_outputs = set()
        used_change_outputs = set()
        
        matched_clients = set()
        # First, create participants for clients we can fully attribute
        for client, client_inputs in inputs_by_client.items():
            # Find matching CoinJoin output
            client_cj_out = next((o for o in cj_outputs 
                               if o.client == client and o.n not in used_cj_outputs), None)
            
            if not client_cj_out:
                diag['clients_no_cj_out'] += 1
                _sample('clients_no_cj_out', client)
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
            matched_clients.add(client)

        # HEURISTIC: attribute unmapped CJ outputs to clients with inputs but no CJ output mapping
        # This is a temporary workaround to compensate for missing keys.json entries (data gathering issue).
        # It attaches the first available unmapped CJ output to each such client, without guessing change.
        clients_needing_heuristic = [c for c in inputs_by_client.keys() if c not in matched_clients]
        for client in clients_needing_heuristic:
            # pick an unmapped, unused CJ output
            candidate = next((o for o in cj_outputs if o.client is None and o.n not in used_cj_outputs), None)
            if not candidate:
                break
            client_inputs = inputs_by_client[client]
            for inp in client_inputs:
                used_inputs.add((inp.txid, inp.vout))
            used_cj_outputs.add(candidate.n)

            input_value = sum(inp.value for inp in client_inputs)
            output_value = candidate.value
            delta = output_value - input_value
            role = "maker" if delta >= 0 else "taker"

            participants.append(CoinJoinParticipant(
                inputs=client_inputs,
                cj_output=candidate,
                change_output=None,
                role=role,
                client=client,
                delta=delta,
                heuristic=True,
            ))
            diag['heuristic_assignments'] += 1
            print("HEURISTIC: assigned unmapped CJ output to client due to missing mapping",
                  {'tx': txid, 'client': client, 'cj_out_n': candidate.n, 'value': candidate.value, 'addr': candidate.address})
        
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
        
        cj_obj = cls(
            txid=txid,
            block_height=block.get('height', 0),
            tx=tx,
            participants=participants,
            meta={'whitebox_analysis': True}
        )
        # Emit unmapped CJ outputs for quick inspection
        unmapped_cj = [
            {'n': o.n, 'value': o.value, 'address': o.address}
            for o in cj_outputs if o.client is None
        ]
        if unmapped_cj:
            print(
                "from_whitebox unmapped_cj_outputs:",
                {
                    'tx': txid,
                    'items': unmapped_cj[:10]  # limit noise
                }
            )

        # Emit compact per-tx diagnostic line if any issues observed
        if any(diag[k] for k in diag if k != 'inputs_total'):
            print(
                "from_whitebox diag:",
                {
                    'tx': txid,
                    **diag,
                    'samples': {k: v for k, v in diag_samples.items()}
                }
            )
        return cj_obj
    
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

    def prepare_for_attribution(self):
        """
        Strips randomly assigned CJ outputs of the participants to be redistributed again.
        Returns:
        """
        self.cj_outs: Set[TxOutput] = set()
        for p in self.participants:
            if p.cj_output:
                self.cj_outs.add(p.cj_output)
                p.cj_output = None


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
