#!/usr/bin/env python3
"""
Functions for loading blockchain and client data
"""

import os
import json
import glob
from typing import Dict, List

# Configuration
BTC_NODE_DIR = "btc-node"
JCS_PREFIX = "jcs-"

def load_blockchain(run_path):
    """
    Load all blocks and transactions from btc-node directory.
    Returns tx_map (txid -> {'tx':..., 'block':...}) and block_map (height -> block)
    """
    # support data subdirectory
    data_dir = os.path.join(run_path, "data")
    root = data_dir if os.path.isdir(data_dir) else run_path
    btc_node_path = os.path.join(root, BTC_NODE_DIR)
    tx_map, block_map = {}, {}
    for block_file in find_blocks(btc_node_path):
        block = load_json(block_file)
        block_map[block['height']] = block
        for tx in block['tx']:
            tx_map[tx['txid']] = {'tx': tx, 'block': block}
    return tx_map, block_map


def load_client_addresses(run_path):
    """
    Map each address from keys.json to its client name.
    
    Args:
        run_path: Path to the run data directory
        
    Returns:
        Dictionary mapping addresses to client names
    """
    # support data subdirectory
    data_dir = os.path.join(run_path, "data")
    root = data_dir if os.path.isdir(data_dir) else run_path
    
    if not os.path.exists(root):
        print(f"Warning: Data directory not found at {root}")
        return {}
        
    addr_map = {}
    clients = find_clients(root)
    
    if not clients:
        print(f"Warning: No client directories found in {root}")
        return {}
        
    print(f"Found {len(clients)} client directories")
    
    for client in clients:
        keys_path = os.path.join(root, client, 'keys.json')
        if not os.path.exists(keys_path):
            print(f"Warning: keys.json not found for client {client}")
            continue
            
        keys_data = load_json(keys_path)
        if not keys_data:
            print(f"Warning: Failed to load keys.json for client {client}")
            continue
            
        addresses_found = 0
        for rec in keys_data:
            if 'address' not in rec:
                continue
            addr_map[rec['address']] = client
            addresses_found += 1
            
        print(f"Loaded {addresses_found} addresses for client {client}")
            
    print(f"Total: {len(addr_map)} addresses mapped to {len(set(addr_map.values()))} clients")
    return addr_map


def find_blocks(btc_node_path: str) -> List[str]:
    return sorted(
        glob.glob(os.path.join(btc_node_path, "block_*.json")),
        key=lambda p: int(os.path.basename(p).split("_")[1].split(".")[0]),
    )


def find_clients(run_path: str) -> List[str]:
    """
    Find all client directories in the run path.
    
    Args:
        run_path: Path to the run data directory
        
    Returns:
        List of client directory names
    """
    try:
        return [d for d in os.listdir(run_path) 
                if d.startswith(JCS_PREFIX) and os.path.isdir(os.path.join(run_path, d))]
    except (FileNotFoundError, PermissionError) as e:
        print(f"Error accessing directory {run_path}: {e}")
        return []


def load_json(path: str):
    """
    Load and parse a JSON file with error handling.
    
    Args:
        path: Path to the JSON file
        
    Returns:
        Parsed JSON content as dict/list or None if file couldn't be loaded
    """
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading JSON file {path}: {e}")
        return None


def extract_address(spk: Dict) -> str | None:  # noqa: D401
    """Return a single address string or *None* for exotic scripts."""
    if "address" in spk and spk["address"]:
        return spk["address"]
    if "addresses" in spk and spk["addresses"]:
        return spk["addresses"][0]
    return None