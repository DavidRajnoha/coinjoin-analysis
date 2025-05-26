#!/usr/bin/env python3
"""
Functions for detecting and attributing CoinJoin transactions
"""

import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Any, Set
# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from joinmarket.common.coinjoin_model import CoinJoin, CoinJoinParticipant, TxInput, TxOutput
# Import from blackbox modules for unified loading
from joinmarket.blackbox.load_blockchain import load_blocks
from joinmarket.whitebox.load_transactions import load_client_addresses

# Original whitebox detection function
def detect_coinjoin_txs(tx_map, address_to_client):
    """
    Identify potential CoinJoin transactions with improved heuristic.
    Returns list of (txid, output_info, input_addresses).
    """
    cj_txs = []
    for txid, info in tx_map.items():
        tx = info['tx']
        if len(tx['vin']) < 3 or len(tx['vout']) < 3:
            continue
        # count outputs
        vals = [v['value'] for v in tx['vout']]
        repeats = {v: vals.count(v) for v in set(vals) if vals.count(v) > 1}
        if not repeats:
            continue
        mix = next(iter(repeats))
        # collect input addrs
        in_addrs = set()
        for vin in tx['vin']:
            if 'txid' in vin and 'vout' in vin:
                ptx = tx_map.get(vin['txid'], {}).get('tx')
                if ptx:
                    po = next((o for o in ptx['vout'] if o['n']==vin['vout']), {})
                    addr = po.get('scriptPubKey',{}).get('address')
                    if addr:
                        in_addrs.add(addr)
        # assemble outputs
        out_info = []
        for v in tx['vout']:
            addr = v['scriptPubKey'].get('address')
            out_info.append({
                'address': addr,
                'client': address_to_client.get(addr),
                'value': v['value'],
                'is_change': addr in in_addrs
            })
        # require at least 2 mix outputs not change
        if sum(1 for x in out_info if x['value']==mix and not x['is_change'])<2:
            continue
        cj_txs.append((txid, out_info, in_addrs))
    return cj_txs


def build_coinjoin_records(cj_txs, tx_map, address_to_client):
    """
    Build summary records and client-level flow edges.
    Returns cj_data, client_edges.
    """
    records, edges = [], []
    for txid, out_info, in_addrs in cj_txs:
        info = tx_map[txid]
        blk = info['block']['height']
        in_clients = {address_to_client[a] for a in in_addrs if a in address_to_client}
        out_clients = {x['client'] for x in out_info if x['client'] and not x['is_change']}
        records.append({
            'txid': txid, 'block': blk,
            'input_clients': in_clients,
            'output_clients': out_clients,
            'input_count': len(info['tx']['vin']),
            'output_count': sum(not x['is_change'] for x in out_info),
            'amounts': [x['value'] for x in out_info if not x['is_change']]
        })
        for src in in_clients:
            for dst in out_clients:
                edges.append((src, dst))
    return records, edges


# def create_coinjoin_objects(cj_txs, tx_map, address_to_client):
#     """
#     Create CoinJoin objects directly from whitebox data.
#
#     Args:
#         cj_txs: List of detected CoinJoin transactions
#         tx_map: Map of transaction IDs to transaction data
#         address_to_client: Mapping from addresses to client IDs
#
#     Returns:
#         List of CoinJoin objects with detailed attribution
#     """
#     cj_objs = []
#
#     for txid, out_info, in_addrs in cj_txs:
#         tx_data = tx_map[txid]['tx']
#         block_data = tx_map[txid]['block']
#
#         # Find the CoinJoin denomination (most common output value)
#         output_values = {}
#         for out in out_info:
#             val = out['value']
#             if val not in output_values:
#                 output_values[val] = []
#             output_values[val].append(out)
#
#         # Find the value that appears most frequently and isn't change
#         cj_value = max(
#             (v for v, outs in output_values.items()
#              if sum(1 for o in outs if not o['is_change']) > 1),
#             key=lambda v: sum(1 for o in output_values[v] if not o['is_change']),
#             default=0
#         )
#
#         if cj_value == 0:
#             continue  # Skip if no CoinJoin amount found
#
#         # Create TxInput objects for all inputs
#         inputs_by_client = defaultdict(list)
#         all_inputs = []
#
#         for i, vin in enumerate(tx_data['vin']):
#             if 'txid' not in vin or 'vout' not in vin:
#                 continue
#
#             # Get previous transaction to find value and address
#             prev_tx = tx_map.get(vin['txid'], {}).get('tx')
#             if not prev_tx:
#                 continue
#
#             prev_out = next((o for o in prev_tx['vout'] if o['n'] == vin['vout']), None)
#             if not prev_out:
#                 continue
#
#             value = prev_out.get('value', 0.0)
#             addr = prev_out.get('scriptPubKey', {}).get('address')
#             client = address_to_client.get(addr) if addr else None
#
#             inp = TxInput(
#                 txid=vin['txid'],
#                 vout=vin['vout'],
#                 value=value,
#                 address=addr,
#                 client=client
#             )
#
#             all_inputs.append(inp)
#             if client:
#                 inputs_by_client[client].append(inp)
#
#         # Create TxOutput objects for all outputs
#         cj_outputs = []
#         change_outputs = []
#         outputs_by_client = defaultdict(list)
#
#         for out in tx_data['vout']:
#             addr = out.get('scriptPubKey', {}).get('address')
#             client = address_to_client.get(addr) if addr else None
#             is_change = addr in in_addrs
#
#             output = TxOutput(
#                 n=out['n'],
#                 value=out['value'],
#                 address=addr,
#                 client=client,
#                 is_change=is_change
#             )
#
#             if client:
#                 outputs_by_client[client].append(output)
#
#             if out['value'] == cj_value and not is_change:
#                 cj_outputs.append(output)
#             elif is_change:
#                 change_outputs.append(output)
#
#         # Create participants
#         participants = []
#         used_inputs = set()
#         used_cj_outputs = set()
#         used_change_outputs = set()
#
#         # First, create participants for clients we can fully attribute
#         for client, client_inputs in inputs_by_client.items():
#             # Find matching CoinJoin output
#             client_cj_out = next((o for o in cj_outputs
#                                 if o.client == client and o.n not in used_cj_outputs), None)
#
#             if not client_cj_out:
#                 continue
#
#             # Find matching change output if any
#             client_change = next((o for o in change_outputs
#                                if o.client == client and o.n not in used_change_outputs), None)
#
#             # Mark as used
#             used_cj_outputs.add(client_cj_out.n)
#             if client_change:
#                 used_change_outputs.add(client_change.n)
#             for inp in client_inputs:
#                 used_inputs.add((inp.txid, inp.vout))
#
#             # Calculate delta
#             input_value = sum(inp.value for inp in client_inputs)
#             output_value = client_cj_out.value
#             if client_change:
#                 output_value += client_change.value
#             delta = output_value - input_value
#
#             # Determine role - maker typically has a small positive delta
#             role = "unknown"
#             if delta >= 0:
#                 role = "maker"
#             else:
#                 role = "taker"
#
#             participants.append(CoinJoinParticipant(
#                 inputs=client_inputs,
#                 cj_output=client_cj_out,
#                 change_output=client_change,
#                 role=role,
#                 client=client,
#                 delta=delta
#             ))
#
#         # For remaining unattributed outputs, create participants with empty inputs
#         for cj_out in cj_outputs:
#             if cj_out.n in used_cj_outputs:
#                 continue
#
#             # Find matching change output if any
#             matching_change = None
#             if cj_out.client:
#                 matching_change = next((ch for ch in change_outputs
#                                       if ch.client == cj_out.client
#                                       and ch.n not in used_change_outputs), None)
#                 if matching_change:
#                     used_change_outputs.add(matching_change.n)
#
#             participants.append(CoinJoinParticipant(
#                 inputs=[],  # We don't have attribution information
#                 cj_output=cj_out,
#                 change_output=matching_change,
#                 client=cj_out.client
#             ))
#
#         # Create the CoinJoin object
#         cj_obj = CoinJoin(
#             txid=txid,
#             block_height=block_data.get('height', 0),
#             tx=tx_data,
#             participants=participants,
#             meta={'whitebox_analysis': True}
#         )
#
#         cj_objs.append(cj_obj)
#
#     return cj_objs


def analyze_coinjoins(run_path, tx_map=None):
    """
    Main analysis function that loads data and detects coinjoins.
    
    Args:
        run_path: Path to the run data directory
        tx_map: Optional map of transaction IDs to transaction data
        
    Returns:
        cj_data: Summary records of coinjoins (for backward compatibility)
        client_flow: Client-level flow edges (for backward compatibility)
        cj_objs: List of CoinJoin objects with detailed attribution
    """
    # Load transaction data if not provided
    if tx_map is None:
        print("Loading blockchain data...")
        block_map, tx_map = load_blocks(run_path)
    else:
        print("Using provided transaction data...")
    
    # Load client address mapping
    print("Loading client addresses...")
    address_to_client = load_client_addresses(run_path)
    
    # Detect CoinJoin transactions
    print("Detecting CoinJoin transactions...")
    cj_txs = detect_coinjoin_txs(tx_map, address_to_client)
    
    # Build coinjoin records and flow edges for summary stats (backward compatibility)
    print("Building CoinJoin flow analysis...")
    cj_data, client_edges = build_coinjoin_records(cj_txs, tx_map, address_to_client)
    
    # Create CoinJoin objects directly using the improved from_whitebox method
    print("Creating detailed CoinJoin objects...")
    cj_objs = []
    for txid, out_info, _ in cj_txs:
        info = tx_map[txid]
        # Create a CoinJoin object using the improved whitebox method
        cj_obj = CoinJoin.from_whitebox(
            txid=txid, 
            tx=info['tx'], 
            block=info['block'], 
            address_to_client=address_to_client,
            tx_map=tx_map
        )
        cj_objs.append(cj_obj)
    
    return cj_data, client_edges, cj_objs
