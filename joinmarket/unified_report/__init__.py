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

from joinmarket.common.analysis_config import AnalysisConfig, DEFAULT_CONFIG
from joinmarket.common.coinjoin_model import CoinJoin, generate_coinjoin_flow_vis_graph, relabel_coinjoin_roles
from joinmarket.blackbox.parse_blockchain import detect_coinjoin_txs
from joinmarket.blackbox.coinjoin_sudoku.joinmarket_sudoku import solve_sudoku_for_coinjoin_set
from joinmarket.blackbox.coinjoin_sudoku.sudoku_statistics import SudokuStatisticsCollector
from joinmarket.blackbox.load_blockchain import load_blocks
from joinmarket.whitebox.attribute import analyze_coinjoins
from joinmarket.whitebox.load_scenario import load_client_roles_from_file, parse_client_fidelity_bonds_from_scenario
from joinmarket.unified_report.create_report import generate_unified_report
from joinmarket.unified_report.fidelity_bond_report import (
    enrich_coinjoins_with_fidelity_bonds,
    analyze_fidelity_bonds,
    render_fidelity_bond_html_report,
    save_fidelity_bond_json
)


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


def run_blackbox_analysis(tx_map: Dict[str, Any], statistics_collector: SudokuStatisticsCollector = None,
                          config: AnalysisConfig = DEFAULT_CONFIG) -> Tuple[List[Tuple[str, Dict, Dict]], List[Dict[str, Any]], List[CoinJoin]]:
    """
    Run blackbox analysis on the transaction data.

    Args:
        tx_map: Map of transaction IDs to transaction data
        statistics_collector: Optional statistics collector for performance analysis

    Returns:
        Tuple containing detected CoinJoins, analysis results, and CoinJoin objects
    """
    print("Running blackbox CoinJoin detection...")
    blackbox_coinjoins = detect_coinjoin_txs(tx_map)
    print(f"Found {len(blackbox_coinjoins)} potential CoinJoins using blackbox analysis")

    print("Solving CoinJoin sudoku (blackbox attribution)...")
    # Configure search strategy here:
    # "start_middle" - Start at 50k, search up/down (ORIGINAL, achieved 85% taker match)
    # "start_high" - Start at 600k, only search down
    # "start_high_always_search" - Start at 600k, search down even if fails
    SEARCH_STRATEGY = "aggressive_downscale"  # <-- CHANGE THIS TO TEST DIFFERENT STRATEGIES
    MAX_ITERATIONS = 5
    print(f"Using search strategy: {SEARCH_STRATEGY}, max_iterations: {MAX_ITERATIONS}")

    if statistics_collector and statistics_collector.enabled:
        print("Statistics collection is ENABLED")

    blackbox_cj_objs, blackbox_results = solve_sudoku_for_coinjoin_set(
        blackbox_coinjoins, tx_map,
        search_strategy=SEARCH_STRATEGY,
        max_iterations=MAX_ITERATIONS,
        statistics_collector=statistics_collector,
        config=config,
    )
    print(f"Analyzed {len(blackbox_results)} CoinJoin transactions with blackbox approach")
    print(f"Created {len(blackbox_cj_objs)} CoinJoin objects from blackbox analysis")

    return blackbox_coinjoins, blackbox_results, blackbox_cj_objs


def run_whitebox_analysis(tx_map: Dict[str, Any], data_dir: str,
                          config: AnalysisConfig = DEFAULT_CONFIG) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[CoinJoin]]:
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
    whitebox_data, whitebox_edges, cj_objs = analyze_coinjoins(run_path, tx_map, config)
    
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


"""Generic, parametrized helpers to keep main() concise"""

def load_cache_pair(output_dir: str, results_file: str, objs_file: str, label: str):
    try:
        with open(os.path.join(output_dir, results_file), "rb") as f:
            results = pickle.load(f)
        with open(os.path.join(output_dir, objs_file), "rb") as f:
            objs = pickle.load(f)
        print(f"Loaded {label} intermediate results from cache.")
        return results, objs
    except Exception:
        print(f"{label.capitalize()} cache missing or invalid; will recompute if needed.")
        return None, None


def save_cache_pair(output_dir: str, results_file: str, objs_file: str, results, objs, label: str) -> None:
    try:
        with open(os.path.join(output_dir, results_file), "wb") as f:
            pickle.dump(results, f)
        with open(os.path.join(output_dir, objs_file), "wb") as f:
            pickle.dump(objs, f)
        print(f"Saved {label} intermediate results to cache.")
    except Exception as e:
        print(f"Warning: failed to save {label} cache: {e}")


def run_and_cache(run_callable, output_dir: str, results_file: str, objs_file: str, label: str):
    results, objs = run_callable()
    save_cache_pair(output_dir, results_file, objs_file, results, objs, label)
    return results, objs


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
    parser.add_argument("--analysis",
                        choices=["both", "blackbox", "whitebox"],
                        default="both",
                        help="Which analysis to run: both (default), blackbox only, or whitebox only")
    parser.add_argument("--show-block-timestamps", action="store_true",
                        help="Show block timestamps in the detailed CoinJoin table of the HTML report")
    parser.add_argument("--cache-dir",
                        help="Where Sudoku/whitebox pickles are cached (default: data_dir/analysis_cache). "
                             "The cache is analysis-mode independent; roles are relabelled on load.")
    parser.add_argument("--collect-stats", action="store_true",
                        help="Collect performance statistics during sudoku solving")
    parser.add_argument("--maker-sessions", action="store_true",
                        help="Account for JoinMarket-NG tumbler maker sessions (zero-fee makers are tumbler legs). "
                             "Default output dir becomes data_dir/report_unified_maker_sessions so caches of the "
                             "two modes never mix.")
    parser.add_argument("--zero-fee-tolerance", type=int, default=0,
                        help="Max delta (sat) still treated as a zero-fee maker (with --maker-sessions)")
    parser.add_argument("--strict-links", dest="strict_links", action="store_true", default=None,
                        help="Chain attribution follows only tumbler spends and identity-matched outputs "
                             "(default: on with --maker-sessions, off otherwise)")
    parser.add_argument("--no-strict-links", dest="strict_links", action="store_false",
                        help="Force legacy chain attribution linking even with --maker-sessions")
    args = parser.parse_args()

    config = AnalysisConfig(maker_sessions=args.maker_sessions, zero_fee_tolerance=args.zero_fee_tolerance,
                            strict_tumbler_links=args.strict_links)
    print(f"Analysis mode: {config.label}")

    # Create output directory; each mode gets its own so pickle caches never mix
    if args.out_dir:
        output_dir = args.out_dir
    else:
        suffix = "" if config.label == "legacy" else f"_{config.label}"
        output_dir = os.path.join(args.data_dir, f"report_unified{suffix}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Analyzing CoinJoins in {args.data_dir}")

    # Initialize statistics collector if requested
    stats_collector = None
    if args.collect_stats:
        print("Initializing performance statistics collector...")
        stats_collector = SudokuStatisticsCollector(enabled=True)
    
    # Cache is shared by all analysis modes of this run. Falls back to pickles an older
    # version left next to the legacy report so they need not be recomputed.
    cache_dir = args.cache_dir or os.path.join(args.data_dir, "analysis_cache")
    os.makedirs(cache_dir, exist_ok=True)
    legacy_cache_dir = os.path.join(args.data_dir, "report_unified")

    def cache_source(*files):
        for d in (cache_dir, legacy_cache_dir):
            if all(os.path.exists(os.path.join(d, f)) for f in files):
                return d
        return cache_dir

    # Load caches independently to avoid redoing long-running steps unnecessarily
    blackbox_results = whitebox_data = blackbox_cj_objs = whitebox_cj_objs = None

    # Determine which analyses to run
    run_blackbox = args.analysis in ["both", "blackbox"]
    run_whitebox = args.analysis in ["both", "whitebox"]

    if not args.no_cache:
        print(f"Loading analysis results from pickle cache in {cache_dir}...")
        def load_shared(results_file, objs_file, label):
            src = cache_source(results_file, objs_file)
            results, objs = load_cache_pair(src, results_file, objs_file, label=label)
            if src != cache_dir and results is not None and objs is not None:
                print(f"Adopting {label} pickles from {src} into {cache_dir}")
                save_cache_pair(cache_dir, results_file, objs_file, results, objs, label=label)
            return results, objs

        if run_blackbox:
            blackbox_results, blackbox_cj_objs = load_shared(
                "blackbox_results.pkl", "blackbox_cj_objs.pkl", label="blackbox")
        if run_whitebox:
            whitebox_data, whitebox_cj_objs = load_shared(
                "whitebox_data.pkl", "whitebox_cj_objs.pkl", label="whitebox")
    else:
        print(f"--no-cache specified; will recompute {args.analysis} analysis.")

    need_run_bb = run_blackbox and (args.no_cache or (blackbox_results is None or blackbox_cj_objs is None))
    need_run_wb = run_whitebox and (args.no_cache or (whitebox_data is None or whitebox_cj_objs is None))

    # Load blockchain once if any analysis needs recomputation
    tx_map = None
    if need_run_bb or need_run_wb:
        _, tx_map = load_blockchain_data(args.data_dir)

    # Recompute selectively and save corresponding caches
    if need_run_bb:
        print("Running blackbox (sudoku) analysis...")
        def _run_bb():
            _, res, objs = run_blackbox_analysis(tx_map, statistics_collector=stats_collector, config=config)
            return res, objs
        blackbox_results, blackbox_cj_objs = run_and_cache(
            _run_bb, cache_dir, "blackbox_results.pkl", "blackbox_cj_objs.pkl", label="blackbox"
        )

    if need_run_wb:
        print("Running whitebox analysis...")
        def _run_wb():
            data, _, objs = run_whitebox_analysis(tx_map, args.data_dir, config)
            return data, objs
        whitebox_data, whitebox_cj_objs = run_and_cache(
            _run_wb, cache_dir, "whitebox_data.pkl", "whitebox_cj_objs.pkl", label="whitebox"
        )

    # Cached objects may have been labelled under another mode; roles derive from deltas
    for objs in (blackbox_cj_objs, whitebox_cj_objs):
        if objs:
            relabel_coinjoin_roles(objs, config)

    # Initialize empty data for skipped analyses
    if not run_blackbox:
        print("Skipping blackbox analysis (--analysis whitebox)")
        blackbox_results = []
        blackbox_cj_objs = []
    if not run_whitebox:
        print("Skipping whitebox analysis (--analysis blackbox)")
        whitebox_data = []
        whitebox_cj_objs = []

    # Get client roles from scenario.json if available
    print("Parsing client roles from scenario.json...")
    client_roles = load_client_roles_from_file(project_root=args.data_dir)

    # Load fidelity bond information from scenario.json if available (whitebox only)
    fidelity_bond_stats = None
    if run_whitebox and whitebox_cj_objs:
        try:
            import json
            scenario_path = os.path.join(args.data_dir, 'scenario.json')
            if os.path.exists(scenario_path):
                print("Loading fidelity bond information from scenario.json...")
                with open(scenario_path, 'r') as f:
                    scenario = json.load(f)

                # Parse fidelity bond info from scenario
                client_bonds = parse_client_fidelity_bonds_from_scenario(scenario)

                if any(bond['enabled'] for bond in client_bonds.values()):
                    print(f"Found {sum(1 for b in client_bonds.values() if b['enabled'])} clients with fidelity bonds")

                    # Enrich whitebox CoinJoin objects with fidelity bond data
                    enrich_coinjoins_with_fidelity_bonds(whitebox_cj_objs, client_bonds)

                    # Analyze fidelity bond usage
                    fidelity_bond_stats = analyze_fidelity_bonds(whitebox_cj_objs, client_roles)
                    print(f"FB participation rate: {fidelity_bond_stats.fb_participation_rate:.2f}%")

                    # Save separate fidelity bond reports
                    from datetime import datetime
                    metadata = {
                        'data_dir': args.data_dir,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'scenario_name': scenario.get('name', 'Unknown')
                    }

                    # Save standalone HTML report
                    fb_html_path = os.path.join(output_dir, "fidelity_bond_report.html")
                    render_fidelity_bond_html_report(fidelity_bond_stats, fb_html_path, metadata)

                    # Save standalone JSON data
                    fb_json_path = os.path.join(output_dir, "fidelity_bond_data.json")
                    save_fidelity_bond_json(fidelity_bond_stats, fb_json_path, metadata)
                else:
                    print("No fidelity bonds enabled in scenario")
            else:
                print("No scenario.json found; skipping fidelity bond analysis")
        except Exception as e:
            print(f"Warning: Failed to load fidelity bond information: {e}")
            fidelity_bond_stats = None
    elif not run_whitebox:
        print("Skipping fidelity bond analysis (requires whitebox analysis)")

    # Generate visualizations
    generate_visualizations(blackbox_cj_objs, whitebox_cj_objs, client_roles, output_dir)

    # Generate unified HTML report
    print(f"Generating unified report in {output_dir}")
    generate_unified_report(
        blackbox_results=blackbox_results,
        whitebox_data=whitebox_data,
        blackbox_cj_objs=blackbox_cj_objs,
        whitebox_cj_objs=whitebox_cj_objs,
        output_dir=output_dir,
        client_roles=client_roles,
        fidelity_bond_stats=fidelity_bond_stats,
        run_path=args.data_dir,
        show_block_timestamps=args.show_block_timestamps,
        config=config,
    )

    # Export statistics if collected
    if stats_collector and stats_collector.enabled:
        print("\nExporting performance statistics...")
        stats_collector.print_summary()
        stats_collector.export_csv(os.path.join(output_dir, "sudoku_performance_stats.csv"))
        stats_collector.export_json(os.path.join(output_dir, "sudoku_performance_stats.json"))
        print(f"Statistics exported to:")
        print(f"  - {os.path.join(output_dir, 'sudoku_performance_stats.csv')}")
        print(f"  - {os.path.join(output_dir, 'sudoku_performance_stats.json')}")

    # Summary message
    analysis_type = args.analysis if args.analysis != "both" else "blackbox and whitebox"
    print(f"\n{'='*60}")
    print(f"Analysis complete: {analysis_type}")
    print(f"Reports generated in: {output_dir}")
    if run_blackbox and blackbox_cj_objs:
        print(f"  - Blackbox CoinJoins detected: {len(blackbox_cj_objs)}")
    if run_whitebox and whitebox_cj_objs:
        print(f"  - Whitebox CoinJoins analyzed: {len(whitebox_cj_objs)}")
    if fidelity_bond_stats:
        print(f"  - Fidelity bond participation: {fidelity_bond_stats.fb_participation_rate:.1f}%")
    if stats_collector and stats_collector.enabled:
        stats = stats_collector.get_statistics()
        successful = sum(1 for s in stats if s.success)
        print(f"  - Sudoku statistics: {len(stats)} transactions, {successful} successful ({100*successful/len(stats):.1f}%)")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
