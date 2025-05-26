#!/usr/bin/env python3
"""Enhanced CoinJoin identification & report generator (rev‑2)

*   **Address‑to‑client map** built from *all* client JSON files.
*   **Relaxed heuristic** – any non‑coinbase tx with > 1 output is treated as a CoinJoin (matches your synthetic data set).
*   **Amounts column restored** so the stats plots render.
*   **Flow graph** now includes CJ → output‑stub edges.
*   **HTML template** rewritten: uses Jinja2's `attr` filter instead of the now‑removed `getattr` builtin, fixes crash with Jinja ≥ 3.1.
*   **Unified format** - now uses the same blockchain loading and visualization components as blackbox analysis.
*   **Interactive visualization** - uses pyvis for interactive transaction flow visualization.

Drop‑in replacement for the original `generate_coinjoin_report.py`.
"""

import os
import sys
import argparse
import pandas as pd
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import from our modules
from joinmarket.common.coinjoin_model import CoinJoin, generate_coinjoin_flow_vis_graph
from joinmarket.whitebox.attribute import analyze_coinjoins
from joinmarket.whitebox.visualize import plot_stats
from joinmarket.whitebox.create_report import save_summary, render_html_report
from joinmarket.visualisation.joinmarket_client_provider import CJClientProvider
from joinmarket.whitebox.load_scenario import load_client_roles_from_file, parse_client_roles_from_scenario


# Configuration
REPORT_DIR = "report_whitebox"


def main():
    parser = argparse.ArgumentParser(description="CoinJoin Identification & Report Generator")
    parser.add_argument("run_path", nargs="?", default=".", help="Path to simulation run directory")
    parser.add_argument("--out", help="Output directory name (default: report_whitebox in run_path)")
    args = parser.parse_args()

    data_dir = args.run_path
    
    # Determine output path
    if not args.out:
        output_dir = os.path.join(data_dir, REPORT_DIR)
    else:
        if os.path.isabs(args.out):
            output_dir = args.out
        else:
            output_dir = os.path.join(data_dir, args.out)
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Analyzing CoinJoins in {data_dir}")
    # analyze - now returns cj_objs instead of coinjoins_raw
    cj_data, client_flow, cj_objs = analyze_coinjoins(data_dir)
    print(f"Detected {len(cj_data)} CoinJoins")
    
    print(f"Generating report in {output_dir}")
    df = pd.DataFrame(cj_data)
    save_summary(df, output_dir)
    
    # plots
    print("Creating visualizations...")
    plot_stats(df, output_dir)

    # Get client_roles mapping from scenario.json in project root
    print("Parsing client roles from scenario.json...")
    client_roles = load_client_roles_from_file(project_root=data_dir)

    # Skip visualization if no CoinJoins were found
    if not cj_objs:
        print("No CoinJoins detected, skipping visualization.")
    else:
        # tx-level flow using the unified visualization function with CoinJoin model
        print("Generating transaction flow graph...")
        
        # Use the new utility function for visualization
        vis_graph = generate_coinjoin_flow_vis_graph(
            cj_objs=cj_objs,
            client_roles=client_roles,
            show_changes=False
        )
        
        print("Creating interactive visualization...")
        vis_graph.save_graph(os.path.join(output_dir, "coinjoin_interactive.html"))

    print("Generating HTML report...")
    render_html_report(df, output_dir)
    print(f"Report generated at {os.path.join(output_dir, 'report.html')}")


if __name__ == '__main__':
    main()
