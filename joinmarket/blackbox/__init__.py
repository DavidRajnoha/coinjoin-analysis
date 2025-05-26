import sys
from pathlib import Path
import argparse
import os

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from joinmarket.visualisation.cj_flow_graph_data import CoinJoinGraphBuilder
from joinmarket.blackbox.generate_report import write_html_report
from joinmarket.blackbox.parse_blockchain import detect_coinjoin_txs
from joinmarket.blackbox.joinmarket_sudoku import solve_joinmarket_sudoku
from joinmarket.blackbox.load_blockchain import load_blocks

def main():
    parser = argparse.ArgumentParser(description="Blockchain Analyst Report Generator")
    parser.add_argument("run_path", nargs="?", default=".", help="Path to simulation run directory")
    parser.add_argument("--out", help="Output HTML file name (default: report.html in report_blackbox directory)")
    args = parser.parse_args()
    
    # Create report_blackbox directory if it doesn't exist
    report_dir = os.path.join(args.run_path, "report_blackbox")
    os.makedirs(report_dir, exist_ok=True)
    
    # Determine output path
    if not args.out:
        output_path = os.path.join(report_dir, "report.html")
    else:
        # If out is provided but not an absolute path, make it relative to report_dir
        if os.path.isabs(args.out):
            output_path = args.out
        else:
            output_path = os.path.join(report_dir, args.out)
    
    print(f"Loading blockchain data from: {args.run_path}")
    block_map, tx_map = load_blocks(args.run_path)
    print(f"Loaded {len(block_map)} blocks and {len(tx_map)} transactions.")
    
    print("Detecting coinjoin transactions...")
    coinjoins = detect_coinjoin_txs(tx_map)
    print(f"Found {len(coinjoins)} potential coinjoin transactions")
    
    print("Analyzing coinjoins...")
    coinjoin_results = solve_joinmarket_sudoku(coinjoins, tx_map)
    print(f"Analyzed {len(coinjoin_results)} coinjoin transactions")
    
    print("Building visualization...")
    builder = CoinJoinGraphBuilder(coinjoins_raw=coinjoins, coinjoin_results=coinjoin_results)
    cj_flow_graph_data = builder.build()
    
    print(f"Generating report at: {output_path}")
    write_html_report(coinjoin_results, output_path, cj_flow_graph_data)
    print(f"\nHTML report written to {output_path}")


if __name__ == '__main__':
    main()