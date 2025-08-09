#!/usr/bin/env python3
"""
Unified reporting module for combining blackbox and whitebox CoinJoin analysis.
"""

import sys
import os
from pathlib import Path
import argparse
import pandas as pd
from typing import Dict, List, Tuple, Any
import pickle

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from joinmarket.common.coinjoin_model import CoinJoin, generate_coinjoin_flow_vis_graph
from joinmarket.blackbox.parse_blockchain import detect_coinjoin_txs
from joinmarket.blackbox.coinjoin_sudoku.joinmarket_sudoku import solve_sudoku_for_coinjoin_set
from joinmarket.blackbox.load_blockchain import load_blocks
from joinmarket.whitebox.attribute import analyze_coinjoins
from joinmarket.whitebox.load_scenario import load_client_roles_from_file
from joinmarket.unified_report.create_report import generate_unified_report


def load_blockchain_data(data_dir: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Load blockchain data from the specified directory.
    
    Args:
        data_dir: Path to the data directory
        
    Returns:
        Tuple containing block_map and tx_map
    """
    print(f"Loading blockchain data from: {data_dir}")
    block_map, tx_map = load_blocks(data_dir)
    print(f"Loaded {len(block_map)} blocks and {len(tx_map)} transactions.")
    return block_map, tx_map


def run_blackbox_analysis(tx_map: Dict[str, Any]) -> Tuple[List[Tuple[str, Dict, Dict]], List[Dict[str, Any]], List[CoinJoin]]:
    """
    Run blackbox analysis on the transaction data.
    
    Args:
        tx_map: Map of transaction IDs to transaction data
        
    Returns:
        Tuple containing detected CoinJoins, analysis results, and CoinJoin objects
    """
    print("Running blackbox CoinJoin detection...")
    blackbox_coinjoins = detect_coinjoin_txs(tx_map)
    print(f"Found {len(blackbox_coinjoins)} potential CoinJoins using blackbox analysis")
    
    print("Solving CoinJoin sudoku (blackbox attribution)...")
    blackbox_cj_objs, blackbox_results = solve_sudoku_for_coinjoin_set(blackbox_coinjoins, tx_map)
    print(f"Analyzed {len(blackbox_results)} CoinJoin transactions with blackbox approach")
    print(f"Created {len(blackbox_cj_objs)} CoinJoin objects from blackbox analysis")
    
    return blackbox_coinjoins, blackbox_results, blackbox_cj_objs


def run_whitebox_analysis(tx_map: Dict[str, Any], data_dir: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[CoinJoin]]:
    """
    Run whitebox analysis on the transaction data.
    
    Args:
        tx_map: Map of transaction IDs to transaction data
        data_dir: Path to the data directory
        
    Returns:
        Tuple containing whitebox data, client flow edges, and CoinJoin objects
    """
    print("Running whitebox CoinJoin analysis...")
    # Use full path to the run data if needed
    run_path = data_dir
    
    # Run whitebox analysis
    whitebox_data, whitebox_edges, cj_objs = analyze_coinjoins(run_path, tx_map)
    
    print(f"Found {len(whitebox_data)} CoinJoin transactions using whitebox analysis")
    print(f"Created {len(cj_objs)} CoinJoin objects from whitebox analysis")
    
    return whitebox_data, whitebox_edges, cj_objs


def generate_visualizations(blackbox_cj_objs, whitebox_cj_objs, client_roles, output_dir):
    """
    Generate visualizations for CoinJoin analysis.
    
    Args:
        blackbox_cj_objs: CoinJoin objects from blackbox analysis
        whitebox_cj_objs: CoinJoin objects from whitebox analysis
        client_roles: Map of client IDs to roles
        output_dir: Directory to save visualizations
    """
    print("Generating visualizations...")
    
    # Blackbox visualization
    if blackbox_cj_objs:
        print("Generating blackbox visualization...")
        try:
            blackbox_graph = generate_coinjoin_flow_vis_graph(
                cj_objs=blackbox_cj_objs,
                client_roles=client_roles,
                show_changes=False
            )
            blackbox_graph.save_graph(os.path.join(output_dir, "blackbox_visualization.html"))
        except Exception as e:
            print(f"Error generating blackbox visualization: {e}")

    # Whitebox visualization
    if whitebox_cj_objs:
        print("Generating whitebox visualization...")
        try:
            whitebox_graph = generate_coinjoin_flow_vis_graph(
                cj_objs=whitebox_cj_objs,
                client_roles=client_roles,
                show_changes=False
            )
            whitebox_graph.save_graph(os.path.join(output_dir, "whitebox_visualization.html"))
        except Exception as e:
            print(f"Error generating whitebox visualization: {e}")


def save_results_to_csv(blackbox_results, whitebox_data, output_dir):
    """
    Save analysis results to CSV files.
    
    Args:
        blackbox_results: Results from blackbox analysis
        whitebox_data: Results from whitebox analysis
        output_dir: Directory to save CSV files
    """
    # Create summary DataFrames
    blackbox_df = pd.DataFrame(blackbox_results) if blackbox_results else pd.DataFrame()
    whitebox_df = pd.DataFrame(whitebox_data) if whitebox_data else pd.DataFrame()
    
    # Save to CSV for reference
    if not blackbox_df.empty:
        blackbox_df.to_csv(os.path.join(output_dir, "blackbox_results.csv"), index=False)
    if not whitebox_df.empty:
        whitebox_df.to_csv(os.path.join(output_dir, "whitebox_results.csv"), index=False)


def save_analysis_cache(blackbox_results, whitebox_data, blackbox_cj_objs, whitebox_cj_objs, output_dir):
    """
    Save all intermediate analysis results (including CoinJoin objects) to pickle files.
    """
    with open(os.path.join(output_dir, "blackbox_results.pkl"), "wb") as f:
        pickle.dump(blackbox_results, f)
    with open(os.path.join(output_dir, "whitebox_data.pkl"), "wb") as f:
        pickle.dump(whitebox_data, f)
    with open(os.path.join(output_dir, "blackbox_cj_objs.pkl"), "wb") as f:
        pickle.dump(blackbox_cj_objs, f)
    with open(os.path.join(output_dir, "whitebox_cj_objs.pkl"), "wb") as f:
        pickle.dump(whitebox_cj_objs, f)


def load_analysis_cache(output_dir):
    """
    Load all intermediate analysis results (including CoinJoin objects) from pickle files if present.
    Returns (blackbox_results, whitebox_data, blackbox_cj_objs, whitebox_cj_objs), or (None, ...)
    """
    try:
        with open(os.path.join(output_dir, "blackbox_results.pkl"), "rb") as f:
            blackbox_results = pickle.load(f)
        with open(os.path.join(output_dir, "whitebox_data.pkl"), "rb") as f:
            whitebox_data = pickle.load(f)
        with open(os.path.join(output_dir, "blackbox_cj_objs.pkl"), "rb") as f:
            blackbox_cj_objs = pickle.load(f)
        with open(os.path.join(output_dir, "whitebox_cj_objs.pkl"), "rb") as f:
            whitebox_cj_objs = pickle.load(f)
        return blackbox_results, whitebox_data, blackbox_cj_objs, whitebox_cj_objs
    except Exception:
        return None, None, None, None


def run_analysis(data_dir: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[CoinJoin], List[CoinJoin]]:
    """
    Run both blackbox and whitebox analysis on the same dataset.
    
    Args:
        data_dir: Path to the data directory
        
    Returns:
        Tuple containing:
        - blackbox_results: Results from blackbox analysis
        - whitebox_data: Results from whitebox analysis
        - whitebox_cj_objs: CoinJoin objects from whitebox analysis
        - blackbox_cj_objs: CoinJoin objects from blackbox analysis
    """
    # Load blockchain data
    block_map, tx_map = load_blockchain_data(data_dir)

    print("Running CoinJoin blackbox analysis...")
    # Run blackbox analysis
    blackbox_coinjoins, blackbox_results, blackbox_cj_objs = run_blackbox_analysis(tx_map)

    print("Running CoinJoin whitebox analysis...")
    # Run whitebox analysis
    whitebox_data, whitebox_edges, whitebox_cj_objs = run_whitebox_analysis(tx_map, data_dir)
    
    return blackbox_results, whitebox_data, whitebox_cj_objs, blackbox_cj_objs


def main():
    parser = argparse.ArgumentParser(description="Unified CoinJoin Analysis Report Generator")
    parser.add_argument("data_dir", help="Path to simulation data directory")
    parser.add_argument("--out-dir", help="Output directory (default: data_dir/report_unified)")
    parser.add_argument("--no-cache", action="store_true", help="Do not use cached results; always recompute")
    args = parser.parse_args()
    
    # Create output directory
    if args.out_dir:
        output_dir = args.out_dir
    else:
        output_dir = os.path.join(args.data_dir, "report_unified")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Analyzing CoinJoins in {args.data_dir}")
    
    # Try loading from full cache if allowed
    blackbox_results = whitebox_data = blackbox_cj_objs = whitebox_cj_objs = None
    if not args.no_cache:
        print(f"Loading analysis results from pickle cache in {output_dir}...")
        bb, wb, bb_objs, wb_objs = load_analysis_cache(output_dir)
        if all(x is not None for x in [bb, wb, bb_objs, wb_objs]):
            print("Loaded all intermediate results from pickle cache.")
            blackbox_results = bb
            whitebox_data = wb
            blackbox_cj_objs = bb_objs
            whitebox_cj_objs = wb_objs
    if not all(x is not None for x in [blackbox_results, whitebox_data, blackbox_cj_objs, whitebox_cj_objs]):
        # Run both analyses if cache not used or missing
        blackbox_results, whitebox_data, whitebox_cj_objs, blackbox_cj_objs = run_analysis(args.data_dir)
        print("Saving analysis results to pickle cache...")
        save_analysis_cache(blackbox_results, whitebox_data, blackbox_cj_objs, whitebox_cj_objs, output_dir)
    # Get client roles from scenario.json if available
    print("Parsing client roles from scenario.json...")
    client_roles = load_client_roles_from_file(project_root=args.data_dir)
    # Generate visualizations
    generate_visualizations(blackbox_cj_objs, whitebox_cj_objs, client_roles, output_dir)
    # Generate unified HTML report
    print(f"Generating unified report in {output_dir}")
    generate_unified_report(
        blackbox_results=blackbox_results,
        whitebox_data=whitebox_data,
        blackbox_cj_objs=blackbox_cj_objs,
        whitebox_cj_objs=whitebox_cj_objs,
        output_dir=output_dir
    )
    print(f"Report generated at {os.path.join(output_dir, 'report.html')}")


if __name__ == '__main__':
    main()
