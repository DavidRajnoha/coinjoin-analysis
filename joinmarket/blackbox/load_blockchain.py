import os
import json
import glob
from typing import Dict, List

BTC_NODE_DIR = "btc-node"

def find_blocks(btc_node_path: str) -> List[str]:
    return sorted(
        glob.glob(os.path.join(btc_node_path, "block_*.json")),
        key=lambda p: int(os.path.basename(p).split("_")[1].split(".")[0]),
    )

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

def load_blocks(run_path: str):
    """
    Load all blocks and transactions from btc-node directory.
    Returns block_map (height -> block) and tx_map (txid -> {'tx':..., 'block':...})
    
    Args:
        run_path: Path to the run data directory
        
    Returns:
        Tuple of (block_map, tx_map)
    """
    data_dir = os.path.join(run_path, "data")
    root = data_dir if os.path.isdir(data_dir) else run_path
    btc_node_path = os.path.join(root, BTC_NODE_DIR)
    
    if not os.path.exists(btc_node_path):
        print(f"Warning: BTC node directory not found at {btc_node_path}")
        return {}, {}
        
    tx_map = {}
    block_map = {}
    block_files = find_blocks(btc_node_path)
    
    if not block_files:
        print(f"Warning: No block files found in {btc_node_path}")
        return {}, {}
    
    print(f"Loading {len(block_files)} block files from {btc_node_path}")
    
    for block_file in block_files:
        block = load_json(block_file)
        if not block:
            print(f"Skipping invalid block file: {block_file}")
            continue
            
        if 'height' not in block:
            print(f"Block file missing height field: {block_file}")
            continue
            
        block_map[block['height']] = block
        
        if 'tx' not in block:
            print(f"Block file missing tx field: {block_file}")
            continue
            
        for tx in block['tx']:
            if 'txid' not in tx:
                print(f"Transaction missing txid in block {block['height']}")
                continue
            tx_map[tx['txid']] = {'tx': tx, 'block': block}
            
    print(f"Loaded {len(block_map)} blocks and {len(tx_map)} transactions")
    return block_map, tx_map