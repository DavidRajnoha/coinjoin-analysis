#!/usr/bin/env python3
"""
Functions for loading blockchain and client data
"""

import os
import json
import glob
import re
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
            
        # Augment from logs (monkeypatch for missing keys.json entries)
        augmented = augment_addresses_from_logs(root, client, addr_map)
        if augmented > 0:
            print(f"Augmented {augmented} addresses from logs for client {client} (keys.json had {addresses_found})")
        else:
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


def augment_addresses_from_logs(root: str, client: str, addr_map: Dict[str, str]) -> int:
    """Heuristically add addresses from per-client logs when keys.json misses entries.

    This scans logs for lines containing "Added utxos" and extracts any "address: <addr>" tokens
    in the subsequent lines (or anywhere in the file as a fallback). It merges newly found
    addresses into addr_map, preferring existing mappings to avoid collisions.

    Note: This is a temporary workaround to compensate for data-gathering issues.
    """
    logs_dir = os.path.join(root, client, 'logs')
    if not os.path.isdir(logs_dir):
        return 0

    added = 0
    # Regex: capture token following 'address:' up to comma/space
    addr_re = re.compile(r"address:\s*([^,\s]+)")
    files = sorted(glob.glob(os.path.join(logs_dir, "*.log")))
    for path in files:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                capture_block = False
                for line in f:
                    # Start of added utxos section
                    if 'Added utxos' in line:
                        capture_block = True
                        continue
                    # Heuristic: capture addresses on following lines until a non-data line resets
                    if capture_block:
                        # If the line looks like a typical log header, stop capture
                        if line.startswith('20') or '[INFO' in line or '[DEBUG' in line:
                            capture_block = False
                            # continue scanning outside block as well
                        # Extract address token if present
                    m = addr_re.search(line)
                    if m:
                        addr = m.group(1)
                        # Merge if not present; prefer existing mapping to avoid cross-client collisions
                        if addr not in addr_map:
                            addr_map[addr] = client
                            added += 1
                        else:
                            if addr_map[addr] != client:
                                print(f"Warning: address {addr} appears in logs of {client} but is owned by {addr_map[addr]} per mapping; keeping existing mapping")
        except (IOError, OSError) as e:
            print(f"Warning: failed reading log {path}: {e}")
            continue

    return added


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