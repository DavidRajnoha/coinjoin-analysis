#!/usr/bin/env python3
"""
Transform BlockSci CoinJoin data format to Bitcoin Core block format.

This script converts the BlockSci format (coinjoin_tx_info.json) to the format
expected by the blackbox analysis tools (block_*.json files).

Can split data by month to create smaller datasets for analysis.

BlockSci format structure:
{
  "coinjoins": {
    "txid": {
      "txid": str,
      "block_hash": str,
      "block_index": int,  # Transaction index within the block
      "broadcast_time": str,
      "inputs": {
        "0": {
          "spending_tx": str,  # Format: "vout_<txid>_<index>"
          "value": int,  # In satoshis
          "script": str,
          "script_type": str,
          "sequence": int,
          "address": str
        }
      },
      "outputs": {
        "0": {
          "value": int,  # In satoshis
          "script": str,
          "script_type": str,
          "address": str,
          "spend_by_tx": str  # Optional, format: "vin_<txid>_<index>"
        }
      }
    }
  },
  "premix": {...},
  "postmix": {...}
}

Bitcoin Core block format:
{
  "hash": str,
  "height": int,
  "time": int,
  "tx": [
    {
      "txid": str,
      "vin": [
        {
          "txid": str,
          "vout": int,
          "scriptSig": {...},
          "sequence": int
        }
      ],
      "vout": [
        {
          "value": float,  # In BTC
          "n": int,
          "scriptPubKey": {
            "hex": str,
            "type": str,
            "address": str
          }
        }
      ]
    }
  ]
}
"""

import json
import os
import sys
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Any, Optional


def parse_spending_tx(spending_tx: str) -> tuple:
    """
    Parse spending_tx format "vout_<txid>_<index>" to extract txid and vout index.

    Args:
        spending_tx: String in format "vout_<txid>_<index>"

    Returns:
        Tuple of (txid, vout_index)
    """
    if not spending_tx.startswith("vout_"):
        raise ValueError(f"Invalid spending_tx format: {spending_tx}")

    # Remove "vout_" prefix
    parts = spending_tx[5:]

    # Split from the right to get the last underscore-separated part as index
    last_underscore = parts.rfind("_")
    if last_underscore == -1:
        raise ValueError(f"Invalid spending_tx format: {spending_tx}")

    txid = parts[:last_underscore]
    vout_index = int(parts[last_underscore + 1:])

    return txid, vout_index


def satoshis_to_btc(satoshis: int) -> float:
    """Convert satoshis to BTC."""
    return satoshis / 100000000.0


def parse_broadcast_time(time_str: str) -> int:
    """
    Parse broadcast time string to Unix timestamp.

    Args:
        time_str: Time string in format "YYYY-MM-DD HH:MM:SS.mmm"

    Returns:
        Unix timestamp
    """
    try:
        # Parse the datetime string
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
        return int(dt.timestamp())
    except ValueError:
        # Fallback: try without milliseconds
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())


def transform_transaction(tx_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform a single transaction from BlockSci format to Bitcoin Core format.

    Args:
        tx_data: Transaction data in BlockSci format

    Returns:
        Transaction in Bitcoin Core format
    """
    txid = tx_data["txid"]

    # Transform inputs
    vin = []
    for input_idx, input_data in sorted(tx_data["inputs"].items(), key=lambda x: int(x[0])):
        prev_txid, prev_vout = parse_spending_tx(input_data["spending_tx"])

        vin_entry = {
            "txid": prev_txid,
            "vout": prev_vout,
            "scriptSig": {
                "asm": "",  # Not available in BlockSci format
                "hex": ""
            },
            "sequence": input_data["sequence"],
            # Add value directly to vin (non-standard but necessary for blackbox analysis
            # when previous transactions are not available)
            "value": satoshis_to_btc(input_data["value"])
        }
        vin.append(vin_entry)

    # Transform outputs
    vout = []
    for output_idx, output_data in sorted(tx_data["outputs"].items(), key=lambda x: int(x[0])):
        vout_entry = {
            "value": satoshis_to_btc(output_data["value"]),
            "n": int(output_idx),
            "scriptPubKey": {
                "hex": output_data["script"],
                "type": output_data.get("script_type", "unknown"),
                "address": output_data.get("address", "")
            }
        }
        vout.append(vout_entry)

    return {
        "txid": txid,
        "vin": vin,
        "vout": vout,
        "version": 2,  # Default version
        "locktime": 0  # Not available in BlockSci format
    }


def get_month_key(timestamp: int) -> str:
    """
    Get YYYY-MM key for a timestamp.

    Args:
        timestamp: Unix timestamp

    Returns:
        String in format YYYY-MM
    """
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m")


def group_transactions_by_block(blocksci_data: Dict[str, Any], month_filter: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group transactions by block hash.

    Args:
        blocksci_data: Full BlockSci data structure
        month_filter: Optional month filter in format "YYYY-MM". If provided, only include transactions from this month.

    Returns:
        Dictionary mapping block_hash to list of transactions
    """
    blocks = defaultdict(list)
    filtered_count = 0
    included_count = 0

    # Process coinjoins
    for txid, tx_data in blocksci_data.get("coinjoins", {}).items():
        block_hash = tx_data["block_hash"]
        block_index = tx_data.get("block_index", 0)
        timestamp = parse_broadcast_time(tx_data["broadcast_time"])

        # Filter by month if specified
        if month_filter:
            month_key = get_month_key(timestamp)
            if month_key != month_filter:
                filtered_count += 1
                continue

        included_count += 1
        tx_core_format = transform_transaction(tx_data)

        blocks[block_hash].append({
            "tx": tx_core_format,
            "block_index": block_index,
            "time": timestamp
        })

    # Note: premix and postmix transactions could also be added here if needed
    # For now, focusing on coinjoins as they are the main CoinJoin transactions

    if month_filter:
        print(f"  Filtered {filtered_count} transactions, included {included_count} for month {month_filter}")

    return blocks


def create_block_file(block_hash: str, transactions: List[Dict[str, Any]], height: int) -> Dict[str, Any]:
    """
    Create a block file in Bitcoin Core format.

    Args:
        block_hash: Block hash
        transactions: List of transactions with metadata
        height: Block height

    Returns:
        Block data in Bitcoin Core format
    """
    # Sort transactions by block_index
    sorted_txs = sorted(transactions, key=lambda x: x["block_index"])

    # Use the timestamp from the first transaction (they should all be similar)
    block_time = sorted_txs[0]["time"] if sorted_txs else 0

    block_data = {
        "hash": block_hash,
        "height": height,
        "time": block_time,
        "nTx": len(sorted_txs),
        "tx": [tx_entry["tx"] for tx_entry in sorted_txs],
        # The following fields are not available from BlockSci data
        # but are included for compatibility
        "version": 0,
        "merkleroot": "",
        "bits": "",
        "difficulty": 0,
        "chainwork": "",
        "previousblockhash": "",
        "nextblockhash": ""
    }

    return block_data


def get_all_months(blocksci_data: Dict[str, Any]) -> List[str]:
    """
    Get all unique months present in the data.

    Args:
        blocksci_data: Full BlockSci data structure

    Returns:
        Sorted list of month strings in format YYYY-MM
    """
    months = set()

    for txid, tx_data in blocksci_data.get("coinjoins", {}).items():
        timestamp = parse_broadcast_time(tx_data["broadcast_time"])
        month_key = get_month_key(timestamp)
        months.add(month_key)

    return sorted(list(months))


def transform_blocksci_to_blocks(input_file: str, output_dir: str, split_by_month: bool = False):
    """
    Main transformation function.

    Args:
        input_file: Path to BlockSci coinjoin_tx_info.json file
        output_dir: Directory to write block_*.json files (or parent directory if split_by_month=True)
        split_by_month: If True, create separate subdirectories for each month
    """
    print(f"Loading BlockSci data from {input_file}...")
    with open(input_file, 'r') as f:
        blocksci_data = json.load(f)

    print(f"Found {len(blocksci_data.get('coinjoins', {}))} CoinJoin transactions")
    print(f"Found {len(blocksci_data.get('premix', {}))} premix transactions")
    print(f"Found {len(blocksci_data.get('postmix', {}))} postmix transactions")

    if split_by_month:
        # Get all months in the data
        months = get_all_months(blocksci_data)
        print(f"\nFound data spanning {len(months)} months: {months[0]} to {months[-1]}")
        print(f"Creating separate directories for each month...\n")

        total_blocks_written = 0

        for month in months:
            print(f"Processing month {month}...")

            # Group transactions by block for this month
            blocks = group_transactions_by_block(blocksci_data, month_filter=month)

            if len(blocks) == 0:
                print(f"  No blocks for {month}, skipping...")
                continue

            # Create month-specific output directory
            month_dir = os.path.join(output_dir, f"real-data-{month}")
            btc_node_dir = os.path.join(month_dir, "btc-node")
            os.makedirs(btc_node_dir, exist_ok=True)

            # Write block files
            print(f"  Writing {len(blocks)} blocks to {btc_node_dir}...")
            for height, (block_hash, transactions) in enumerate(blocks.items()):
                block_data = create_block_file(block_hash, transactions, height)

                output_file = os.path.join(btc_node_dir, f"block_{height}.json")
                with open(output_file, 'w') as f:
                    json.dump(block_data, f, indent=2)

            total_blocks_written += len(blocks)

            # Write summary for this month
            summary = {
                "month": month,
                "total_blocks": len(blocks),
                "total_coinjoins": sum(len(txs) for txs in blocks.values()),
                "source_file": input_file,
                "transformation_date": datetime.now().isoformat()
            }

            summary_file = os.path.join(month_dir, "transformation_summary.json")
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)

            print(f"  Summary: {summary['total_coinjoins']} transactions in {len(blocks)} blocks")
            print()

        print(f"\nTransformation complete!")
        print(f"Created {len(months)} month directories with {total_blocks_written} total blocks in {output_dir}")

    else:
        # Original behavior: single output directory
        # Group transactions by block
        print("\nGrouping transactions by block...")
        blocks = group_transactions_by_block(blocksci_data)
        print(f"Grouped into {len(blocks)} blocks")

        # Create output directory
        btc_node_dir = os.path.join(output_dir, "btc-node")
        os.makedirs(btc_node_dir, exist_ok=True)

        # Write block files
        print(f"\nWriting block files to {btc_node_dir}...")
        for height, (block_hash, transactions) in enumerate(blocks.items()):
            block_data = create_block_file(block_hash, transactions, height)

            output_file = os.path.join(btc_node_dir, f"block_{height}.json")
            with open(output_file, 'w') as f:
                json.dump(block_data, f, indent=2)

            if (height + 1) % 100 == 0:
                print(f"  Wrote {height + 1} blocks...")

        print(f"\nTransformation complete!")
        print(f"Wrote {len(blocks)} block files to {btc_node_dir}")

        # Write summary
        summary = {
            "total_blocks": len(blocks),
            "total_coinjoins": len(blocksci_data.get("coinjoins", {})),
            "source_file": input_file,
            "transformation_date": datetime.now().isoformat()
        }

        summary_file = os.path.join(output_dir, "transformation_summary.json")
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"Summary written to {summary_file}")


def main():
    """Main entry point."""
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python transform_blocksci_to_blocks.py <input_file> <output_dir> [--split-by-month]")
        print()
        print("Arguments:")
        print("  input_file        - Path to BlockSci coinjoin_tx_info.json file")
        print("  output_dir        - Directory where block_*.json files will be written")
        print("  --split-by-month  - Optional flag to create separate directories for each month")
        print()
        print("Examples:")
        print("  # Single directory with all data:")
        print("  python transform_blocksci_to_blocks.py \\")
        print("    data/joinmarket/real-data/coinjoin_tx_info.json \\")
        print("    data/joinmarket/real-data")
        print()
        print("  # Split into monthly directories:")
        print("  python transform_blocksci_to_blocks.py \\")
        print("    data/joinmarket/real-data/coinjoin_tx_info.json \\")
        print("    data/joinmarket \\")
        print("    --split-by-month")
        print()
        print("  When using --split-by-month, directories will be created like:")
        print("    data/joinmarket/real-data-2015-01/btc-node/block_*.json")
        print("    data/joinmarket/real-data-2015-02/btc-node/block_*.json")
        print("    ...")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2]
    split_by_month = len(sys.argv) == 4 and sys.argv[3] == "--split-by-month"

    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    transform_blocksci_to_blocks(input_file, output_dir, split_by_month=split_by_month)


if __name__ == "__main__":
    main()
