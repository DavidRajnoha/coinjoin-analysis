#!/usr/bin/env python3
"""
Script to compare statistics across multiple CoinJoin experiments.
Reads unified_coinjoin_report.json from experiment directories and generates
a side-by-side comparison HTML report.
"""

import os
import json
import glob
from pathlib import Path
from typing import Dict, List, Any, Optional
import sys

# Add project root to Python path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def find_experiment_reports(data_dir: str) -> List[Dict[str, Any]]:
    """Find all unified_coinjoin_report.json files in experiment directories."""
    reports = []
    
    # Search pattern: data_dir/**/report_unified*/unified_coinjoin_report.json
    # (report_unified for legacy analysis, report_unified_maker_sessions for the JM-NG mode)
    pattern = os.path.join(data_dir, "**/report_unified*/unified_coinjoin_report.json")
    json_files = glob.glob(pattern, recursive=True)
    
    for json_file in sorted(json_files):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Experiment name: run directory, suffixed by analysis mode when it is not the legacy one
            report_dir = os.path.dirname(json_file)
            experiment_name = os.path.basename(os.path.dirname(report_dir))
            mode = os.path.basename(report_dir).removeprefix("report_unified").lstrip("_")
            if mode:
                experiment_name = f"{experiment_name} [{mode}]"
            
            reports.append({
                'name': experiment_name,
                'path': json_file,
                'data': data
            })
            
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Warning: Could not read {json_file}: {e}")
    
    return reports

def extract_statistics(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the requested statistics from a report."""
    stats = {}
    
    # Whitebox object stats (all four fields)
    wb_stats = report_data.get('whitebox_obj_stats', {})
    stats['wb_total_transactions'] = wb_stats.get('total_transactions', 'N/A')
    stats['wb_total_participants'] = wb_stats.get('total_participants', 'N/A')
    stats['wb_avg_participants'] = wb_stats.get('avg_participants', 'N/A')
    stats['wb_avg_fee'] = wb_stats.get('avg_fee', 'N/A')
    
    # Object comparison stats
    obj_stats = report_data.get('object_comparison_stats', {})
    stats['taker_match_avg'] = obj_stats.get('taker_match_avg', 'N/A')
    stats['taker_sensitivity_avg'] = obj_stats.get('taker_sensitivity_avg', 'N/A')
    stats['taker_specificity_avg'] = obj_stats.get('taker_specificity_avg', 'N/A')
    stats['correctly_mapped_identities'] = obj_stats.get('taker_mapping_occurrence_consistency', 'N/A')

    # Chain comparison stats
    chain_stats = report_data.get('chain_comparison_summary', {})
    stats['total_whitebox_chains'] = chain_stats.get('total_whitebox_chains', 'N/A')
    stats['chain_identification_coverage_nodes'] = chain_stats.get('chain_identification_coverage_nodes', 'N/A')
    stats['chain_identification_specificity_nodes'] = chain_stats.get('chain_identification_specificity_nodes', 'N/A')
    stats['chain_identification_coverage_leaves'] = chain_stats.get('chain_identification_coverage_leaves', 'N/A')
    stats['chain_identification_specificity_leaves'] = chain_stats.get('chain_identification_specificity_leaves', 'N/A')
    stats['chain_purity_specificity_chains'] = chain_stats.get('chain_purity_specificity_chains', 'N/A')
    stats['chain_purity_specificity_txs'] = chain_stats.get('chain_purity_specificity_txs', 'N/A')

    # Taker CoinJoin output attribution metrics
    stats['taker_cj_output_coverage_bb'] = chain_stats.get('taker_cj_output_coverage_bb', 'N/A')
    stats['taker_cj_output_coverage_wb'] = chain_stats.get('taker_cj_output_coverage_wb', 'N/A')
    stats['taker_cj_output_attribution_accuracy'] = chain_stats.get('taker_cj_output_attribution_accuracy', 'N/A')
    stats['taker_cj_output_attribution_specificity'] = chain_stats.get('taker_cj_output_attribution_specificity', 'N/A')

    return stats

def format_value(value: Any) -> str:
    """Format a value for display in the HTML table."""
    if value == 'N/A' or value is None:
        return 'N/A'
    
    if isinstance(value, dict) and '__decimal__' in value:
        # Handle decimal objects
        try:
            return f"{float(value['value']):.8f}"
        except (ValueError, KeyError):
            return str(value)
    
    if isinstance(value, float):
        if value >= 1:
            return f"{value:.2f}"
        else:
            return f"{value:.8f}"
    
    return str(value)

def generate_comparison_html(reports: List[Dict[str, Any]], output_file: str) -> None:
    """Generate an HTML comparison report."""
    
    if not reports:
        print("No reports found to compare.")
        return
    
    # Extract statistics from all reports
    all_stats = []
    for report in reports:
        stats = extract_statistics(report['data'])
        stats['experiment_name'] = report['name']
        all_stats.append(stats)
    
    # Define the metrics to display
    metrics = [
        ('wb_total_transactions', 'WB Total Transactions'),
        ('wb_total_participants', 'WB Total Participants'),
        ('wb_avg_participants', 'WB Avg Participants'),
        ('wb_avg_fee', 'WB Avg Fee (BTC)'),
        ('taker_match_avg', 'Taker Match Avg (%)'),
        ('taker_sensitivity_avg', 'Taker Sensitivity (%)'),
        ('taker_specificity_avg', 'Taker Specificity (%)'),
        ('correctly_mapped_identities', 'Correctly Mapped Identities Per-Transaction (%)'),
        ('total_whitebox_chains', 'Total Whitebox Chains'),
        ('chain_identification_coverage_nodes', 'Chain Identification Sensitivity - Nodes (%)'),
        ('chain_identification_specificity_nodes', 'Root Identity Separation (%)'),
        ('chain_purity_specificity_chains', 'Chain Purity Specificity - Chains (%)'),
        ('chain_purity_specificity_txs', 'Chain Purity Specificity - Txs (%)'),
        ('chain_identification_coverage_leaves', 'Chain Identification Sensitivity - Leaves (%)'),
        ('taker_cj_output_coverage_bb', 'Taker CJ Output Coverage BB (%)'),
        ('taker_cj_output_coverage_wb', 'Taker CJ Output Coverage WB (%)'),
        ('taker_cj_output_attribution_accuracy', 'Taker CJ Output Attribution Sensitivity (%)'),
        ('taker_cj_output_attribution_specificity', 'Taker CJ Output Attribution Specificity (%)'),
        ('sole_taker_count', 'Sole Taker Count'),
        ('sole_taker_tx_count', 'Sole Taker Transactions'),
        ('sole_taker_cj_output_attribution_accuracy', 'Sole Taker CJ Output Attribution Sensitivity (%)'),
        ('sole_taker_cj_output_attribution_specificity', 'Sole Taker CJ Output Attribution Specificity (%)')
    ]
    
    # Generate HTML using unified report styling
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CoinJoin Experiment Comparison</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; line-height: 1.6; color: #333; max-width: 100%; overflow-x: auto; background-color: #f8f9fa; }}
        .container {{ max-width: 100%; margin: 0 auto; padding: 2em; background-color: #fff; box-shadow: 0 0 10px rgba(0,0,0,0.1); border-radius: 8px; margin-top: 20px; margin-bottom: 20px; }}
        h1 {{ color: #333; text-align: center; margin-bottom: 30px; }}
        .summary {{ display: flex; flex-wrap: wrap; gap: 1.5em; margin-bottom: 2em; }}
        .summary-box {{ background: #f1f3f4; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.04); padding: 1.5em 2em; min-width: 200px; flex: 1; text-align: center; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 2em; font-size: 13px; }}
        th, td {{ border: 1px solid #ddd; padding: 0.7em 1em; text-align: left; vertical-align: top; }}
        th {{ background: #f6f8fa; font-weight: bold; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #fafbfc; }}
        tr:hover {{ background: #f0f0f0; }}
        .metric-name {{ font-weight: bold; background-color: #e8f5e8; min-width: 300px; }}
        .numeric {{ text-align: right; font-family: monospace; }}
        .na {{ color: #999; font-style: italic; }}
        .experiment-header {{ writing-mode: horizontal-tb; text-align: center; min-width: 150px; max-width: 200px; word-wrap: break-word; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>CoinJoin Experiment Statistics Comparison</h1>
        
        <div class="summary">
            <div class="summary-box"><strong>Compared Experiments:</strong><br>{len(all_stats)}</div>
            <div class="summary-box"><strong>Key Metrics:</strong><br>{len(metrics)} per experiment</div>
            <div class="summary-box"><strong>Generated:</strong><br>{os.path.basename(output_file)}</div>
        </div>

        <table>
            <thead>
                <tr>
                    <th class="metric-name">Metric</th>"""
    
    # Add experiment name headers (full names, no truncation)
    for stats in all_stats:
        experiment_name = stats['experiment_name']
        html_content += f'<th class="experiment-header">{experiment_name}</th>'
    
    html_content += """
                </tr>
            </thead>
            <tbody>"""
    
    # Add metric rows
    for metric_key, metric_name in metrics:
        html_content += f"""
                <tr>
                    <td class="metric-name">{metric_name}</td>"""
        
        for stats in all_stats:
            value = stats.get(metric_key, 'N/A')
            formatted_value = format_value(value)
            css_class = 'numeric na' if formatted_value == 'N/A' else 'numeric'
            html_content += f'<td class="{css_class}">{formatted_value}</td>'
        
        html_content += """
                </tr>"""
    
    html_content += """
            </tbody>
        </table>
        
        <div style="margin-top: 30px; padding: 20px; background: #f1f3f4; border-radius: 8px; font-size: 12px; color: #666;">
            <strong>Notes:</strong>
            <ul style="margin-top: 10px;">
                <li><strong>WB</strong> = Whitebox analysis results; <strong>BB</strong> = Blackbox analysis results</li>
                <li><strong>Sensitivity:</strong> True Positive Rate - ability to correctly identify positive cases</li>
                <li><strong>Specificity:</strong> True Negative Rate - ability to correctly identify negative cases</li>
                <li><strong>Taker Match Avg:</strong> % of transactions where exactly 1 taker was correctly matched</li>
                <li><strong>Taker Sensitivity:</strong> Same as Taker Match Avg (reused for clarity)</li>
                <li><strong>Taker Specificity:</strong> % of WB maker participants correctly NOT identified as takers in BB</li>
                <li><strong>Correctly Mapped Identities Per-Transaction:</strong> Percentage consistency of BB→WB taker mappings</li>
                <li><strong>Chain Identification Sensitivity:</strong> WB chain nodes correctly identified as root identity in BB</li>
                <li><strong>Chain Separation Specificity:</strong> % of WB chains kept separate by BB (not merged with other WB chains)</li>
                <li><strong>Taker CJ Output Coverage:</strong> Percentage of taker participants with cj_output successfully attributed</li>
                <li><strong>Taker CJ Output Attribution Sensitivity:</strong> WB taker outputs correctly attributed as taker in BB</li>
                <li><strong>Taker CJ Output Attribution Specificity:</strong> WB maker outputs correctly NOT attributed as taker in BB</li>
                <li><strong>Sole Taker Count:</strong> Number of standard takers (not tumblers, not makers)</li>
                <li><strong>Sole Taker Transactions:</strong> Number of transactions involving sole takers</li>
                <li><strong>Sole Taker CJ Output Attribution Sensitivity:</strong> % of sole taker CJ outputs correctly attributed as taker in BB</li>
                <li><strong>Sole Taker CJ Output Attribution Specificity:</strong> % of sole taker maker outputs correctly NOT attributed as taker in BB</li>
            </ul>
        </div>
    </div>
</body>
</html>"""
    
    # Write HTML file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Comparison report generated: {os.path.abspath(output_file)}")
    print(f"Compared {len(all_stats)} experiments with {len(metrics)} metrics each.")

def main():
    """Main function to run the comparison script."""
    
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        # Default to the data directory
        script_dir = Path(__file__).parent
        data_dir = script_dir.parent / 'data' / 'joinmarket'
    
    if not os.path.exists(data_dir):
        print(f"Error: Data directory {data_dir} does not exist")
        sys.exit(1)
    
    print(f"Searching for experiment reports in: {data_dir}")
    
    # Find all experiment reports
    reports = find_experiment_reports(str(data_dir))
    
    if not reports:
        print("No experiment reports found!")
        sys.exit(1)
    
    print(f"Found {len(reports)} experiment reports:")
    for report in reports:
        print(f"  - {report['name']}")
    
    # Generate comparison HTML in the analyzed directory
    output_file = os.path.join(data_dir, 'experiment_comparison.html')
    generate_comparison_html(reports, output_file)

if __name__ == '__main__':
    main()