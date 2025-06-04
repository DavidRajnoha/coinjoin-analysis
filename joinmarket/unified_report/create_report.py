#!/usr/bin/env python3
"""
Functions for generating unified HTML reports comparing blackbox and whitebox CoinJoin analyses.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import json
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import List, Dict, Any, Optional

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from joinmarket.comparison import generate_coinjoin_breakdown, generate_comparison_data, generate_object_comparison, compare_coinjoin_chains
from joinmarket.comparison.chain_visualization import generate_colored_chain_comparison
from joinmarket.common.coinjoin_chain import identify_coinjoin_chains, CoinJoinTree


def convert_frozensets(obj):
    if isinstance(obj, dict):
        return {k: convert_frozensets(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_frozensets(v) for v in obj]
    elif isinstance(obj, tuple):
        return [convert_frozensets(v) for v in obj]
    elif isinstance(obj, frozenset):
        return sorted([convert_frozensets(v) for v in obj])
    elif hasattr(obj, '__dict__'):
        return convert_frozensets(vars(obj))
    else:
        try:
            json.dumps(obj)
            return obj
        except TypeError:
            return str(obj)


def generate_unified_report(
    blackbox_results: List[Dict[str, Any]],
    whitebox_data: List[Dict[str, Any]],
    blackbox_cj_objs: List[Any],
    whitebox_cj_objs: List[Any],
    output_dir: str
):
    """
    Generate a unified HTML report comparing blackbox and whitebox analyses.

    Args:
        blackbox_results: Results from blackbox analysis
        whitebox_data: Results from whitebox analysis
        blackbox_cj_objs: CoinJoin objects from blackbox analysis
        whitebox_cj_objs: CoinJoin objects from whitebox analysis
        output_dir: Directory to write the report to
    """
    # Create environment with template loader
    env = Environment(
        loader=FileSystemLoader(os.path.dirname(__file__) or "."),
        autoescape=select_autoescape()
    )

    # Prepare report_data dictionary
    report_data = {}

    # Generate comparison data for individual CoinJoins (TXID-centric)
    report_data['txid_comparison'] = generate_comparison_data(blackbox_results, whitebox_data)

    # Create additional comparison using CoinJoin objects (with detailed participant breakdown)
    obj_comparison_data = generate_object_comparison(blackbox_cj_objs, whitebox_cj_objs, detailed=True)
    report_data['object_comparison'] = obj_comparison_data

    # Add whitebox taker client information to each transaction
    for tx in obj_comparison_data.get("obj_comparison", []):
        txid = tx["txid"]
        
        # Find the whitebox CoinJoin object for this transaction
        wb_cj = None
        for cj in whitebox_cj_objs:
            if cj.txid == txid:
                wb_cj = cj
                break
        
        # Add taker client name if found
        if wb_cj and hasattr(wb_cj, 'participants'):
            taker_clients = []
            for participant in wb_cj.participants:
                if hasattr(participant, 'role') and participant.role == 'taker':
                    if hasattr(participant, 'client'):
                        taker_clients.append(participant.client)
            tx["wb_taker_clients"] = ", ".join(taker_clients) if taker_clients else "None"
        else:
            tx["wb_taker_clients"] = "Unknown"

    # Aggregate detailed participant breakdowns for unified table
    detailed_participant_breakdown = []
    for tx in obj_comparison_data.get("obj_comparison", []):
        # Find the whitebox CoinJoin object for this transaction to get taker information
        wb_cj = None
        for cj in whitebox_cj_objs:
            if cj.txid == tx["txid"]:
                wb_cj = cj
                break
                
        # Get taker information if available
        taker_client = "Unknown"
        if wb_cj and hasattr(wb_cj, 'participants'):
            for participant in wb_cj.participants:
                if hasattr(participant, 'role') and participant.role == 'taker':
                    if hasattr(participant, 'client'):
                        taker_client = participant.client
                        break
        
        # Process each participant
        for part in tx.get("participant_breakdown", []):
            entry = {
                "txid": tx["txid"],
                "block_height": tx["block_height"],
                "bb_sig": str(part["bb_sig"]),
                "bb_role": part["bb_role"],
                "wb_roles": ", ".join(part["wb_roles"]),
                "role_match": part["role_match"],
                "taker_client": taker_client
            }
            detailed_participant_breakdown.append(entry)
    report_data['detailed_participant_breakdown'] = detailed_participant_breakdown

    # Calculate CoinJoin object statistics
    report_data['blackbox_obj_stats'] = {
        'total_transactions': len(blackbox_cj_objs),
        'total_participants': sum(len(cj.participants) for cj in blackbox_cj_objs),
        'avg_participants': round(sum(len(cj.participants) for cj in blackbox_cj_objs) / max(len(blackbox_cj_objs), 1), 2),
        'avg_fee': round(sum(cj.miner_fee for cj in blackbox_cj_objs if hasattr(cj, 'miner_fee')) / max(len(blackbox_cj_objs), 1), 8),
    }

    report_data['whitebox_obj_stats'] = {
        'total_transactions': len(whitebox_cj_objs),
        'total_participants': sum(len(cj.participants) for cj in whitebox_cj_objs),
        'avg_participants': round(sum(len(cj.participants) for cj in whitebox_cj_objs) / max(len(whitebox_cj_objs), 1), 2),
        'avg_fee': round(sum(cj.miner_fee for cj in whitebox_cj_objs if hasattr(cj, 'miner_fee')) / max(len(whitebox_cj_objs), 1), 8),
    }

    # --- CoinJoin Chain Analysis ---
    blackbox_identified_chains = identify_coinjoin_chains(blackbox_cj_objs, 'blackbox')
    whitebox_identified_chains = identify_coinjoin_chains(whitebox_cj_objs, 'whitebox')
    
    # Create lists of transaction IDs for comparison
    all_plain_txids = [cj.txid for cj in blackbox_cj_objs + whitebox_cj_objs]
    all_plain_txids = sorted(list(set(all_plain_txids)))  # Remove duplicates
    
    blackbox_chain_txids = []
    for chain in blackbox_identified_chains:
        blackbox_chain_txids.extend([node.txid for node in chain.nodes])
    blackbox_chain_txids = sorted(list(set(blackbox_chain_txids)))  # Remove duplicates
    
    whitebox_chain_txids = []
    for chain in whitebox_identified_chains:
        whitebox_chain_txids.extend([node.txid for node in chain.nodes])
    whitebox_chain_txids = sorted(list(set(whitebox_chain_txids)))  # Remove duplicates
    
    # Find transactions that are not attributed in the chains
    unattributed_in_blackbox = sorted(list(set(all_plain_txids) - set(blackbox_chain_txids)))
    unattributed_in_whitebox = sorted(list(set(all_plain_txids) - set(whitebox_chain_txids)))
    
    # Add these lists to the report data
    report_data['txid_lists'] = {
        'all_plain_txids': ', '.join(all_plain_txids),
        'blackbox_chain_txids': ', '.join(blackbox_chain_txids),
        'whitebox_chain_txids': ', '.join(whitebox_chain_txids),
        'unattributed_in_blackbox': ', '.join(unattributed_in_blackbox),
        'unattributed_in_whitebox': ', '.join(unattributed_in_whitebox)
    }

    def serialize_cj_chain_for_report(chain, settings, chain_type):
        """Convert a CoinJoinTree to a format suitable for the report.
        
        Args:
            chain: CoinJoinTree object
            settings: Settings dictionary
            chain_type: Type of chain ('whitebox' or 'blackbox')
            
        Returns:
            Dictionary representation of the chain for the report
        """
        # Use the nodes property to get unique transactions
        unique_transactions = chain.nodes
        
        chain_data = {
            "id": chain.id,
            "analysis_type": chain.analysis_type,
            "chain_type": chain_type,  # To distinguish whitebox/blackbox chains
            "length": chain.length(),
            "transactions": [{
                "txid": node.txid,
                "block_height": node.get_coinjoin().block_height,
                "participants": len(node.get_coinjoin().participants),
                "amount": node.get_coinjoin().cj_amount
            } for node in unique_transactions]
        }
        
        # Include the tree-like representation
        if hasattr(chain, 'tree_representation'):
            chain_data["tree_representation"] = chain.tree_representation
        else:
            chain_data["tree_representation"] = str(chain)
        
        # Add additional chain statistics
        chain_data.update({
            "start_block": chain.start_block(),
            "end_block": chain.end_block(),
            "duration_blocks": chain.duration_blocks(),
            "total_amount": chain.total_cj_amount(),
            "avg_amount": chain.avg_cj_amount()
        })
        
        return chain_data

    report_data['blackbox_identified_chains'] = [
        serialize_cj_chain_for_report(chain, {}, 'blackbox') for chain in blackbox_identified_chains
    ]
    report_data['whitebox_identified_chains'] = [
        serialize_cj_chain_for_report(chain, {}, 'whitebox') for chain in whitebox_identified_chains
    ]

    chain_comparison_summary = compare_coinjoin_chains(blackbox_identified_chains, whitebox_identified_chains)
    report_data['chain_comparison_summary'] = convert_frozensets(chain_comparison_summary) # Ensure serializable
    
    # Add enhanced chain visualization for matched pairs
    chain_map = {chain.id: chain for chain in blackbox_identified_chains + whitebox_identified_chains}
    
    matched_pairs_details = report_data['chain_comparison_summary'].get('matched_chain_pairs', [])
    for pair in matched_pairs_details:
        bb_chain_id = pair['blackbox_chain_id']
        wb_chain_id = pair['whitebox_chain_id']
        
        if bb_chain_id in chain_map and wb_chain_id in chain_map:
            bb_chain = chain_map[bb_chain_id]
            wb_chain = chain_map[wb_chain_id]
            
            # Generate colored tree comparison
            pair['colored_tree_comparison'] = generate_colored_chain_comparison(bb_chain, wb_chain)
    
    # --- End CoinJoin Chain Analysis ---

    # Check if visualizations exist
    blackbox_vis_path = os.path.join(output_dir, "blackbox_visualization.html")
    whitebox_vis_path = os.path.join(output_dir, "whitebox_visualization.html")

    blackbox_iframe = ""
    if os.path.exists(blackbox_vis_path):
        blackbox_iframe = f'''
        <div class="visualization-container">
            <h3>Blackbox Analysis Visualization</h3>
            <iframe src="blackbox_visualization.html"
                    style="width:100%;height:800px;border:none;border-radius:4px;display:block;"
                    loading="lazy"></iframe>
        </div>'''

    whitebox_iframe = ""
    if os.path.exists(whitebox_vis_path):
        whitebox_iframe = f'''
        <div class="visualization-container">
            <h3>Whitebox Analysis Visualization</h3>
            <iframe src="whitebox_visualization.html"
                    style="width:100%;height:800px;border:none;border-radius:4px;display:block;"
                    loading="lazy"></iframe>
        </div>'''

    # Create HTML template
    template_html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Unified CoinJoin Analysis Report</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { 
      font-family: Arial, sans-serif; 
      margin: 0;
      padding: 0;
      line-height: 1.6;
      color: #333;
      max-width: 100%;
      overflow-x: hidden;
      background-color: #f8f9fa;
    }
    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 2em;
      background-color: #fff;
      box-shadow: 0 0 10px rgba(0,0,0,0.1);
      border-radius: 8px;
      margin-top: 20px;
      margin-bottom: 20px;
    }
    .stats-boxes {
      display: flex;
      flex-wrap: wrap;
      gap: 1.5em;
      margin-bottom: 2em;
    }
    .stat-box {
      background: #f1f3f4;
      border-radius: 8px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.04);
      padding: 1.5em 2em;
      min-width: 200px;
      flex: 1;
      text-align: center;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      margin-bottom: 2em;
    }
    th, td {
      border: 1px solid #ddd;
      padding: 0.5em 0.7em;
      text-align: left;
      vertical-align: top;
    }
    th {
      background: #f6f8fa;
    }
    tr:nth-child(even) {
      background: #fafbfc;
    }
    code {
      font-family: monospace;
      background: #f4f4f4;
      padding: 2px 4px;
      border-radius: 3px;
      font-size: 0.95em;
    }
    .visualization-container {
      margin-bottom: 2em;
    }
    pre {
      white-space: pre-wrap;
      max-width: 100%;
      overflow-x: auto;
      margin: 0;
      padding: 10px;
      background: #f9f9f9;
      border-radius: 4px;
      border: 1px solid #eee;
    }
    .tree-comparison {
      margin-bottom: 1em;
    }
    .tree-hierarchy {
      margin-top: 1em;
    }
    .truncated-text {
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .truncated-text:hover {
      white-space: normal;
      overflow: visible;
      max-width: none;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Unified CoinJoin Analysis Report</h1>
    
    <h2>Overall Detection Comparison (TXID-based)</h2>
    <div class="stats-boxes">
      <div class="stat-box"><strong>Total Blackbox TXIDs:</strong> {{ report_data.txid_comparison.total_blackbox }}</div>
      <div class="stat-box"><strong>Total Whitebox TXIDs:</strong> {{ report_data.txid_comparison.total_whitebox }}</div>
      <div class="stat-box"><strong>Common TXIDs:</strong> {{ report_data.txid_comparison.common }}</div>
      <div class="stat-box"><strong>Only in Blackbox:</strong> {{ report_data.txid_comparison.only_blackbox }}</div>
      <div class="stat-box"><strong>Only in Whitebox:</strong> {{ report_data.txid_comparison.only_whitebox }}</div>
      <div class="stat-box"><strong>Detection Agreement:</strong> {{ report_data.txid_comparison.detection_agreement }}%</div>
    </div>

    <h2>Object-Level CoinJoin Comparison</h2>
    <div class="stats-boxes">
        <div class="stat-box"><strong>Compared TXs:</strong> {{ report_data.object_comparison.comparison_tx_count }}</div>
        <div class="stat-box"><strong>Avg. Overall Role Success (all BB):</strong> {{ report_data.object_comparison.overall_role_success_avg }}%</div>
        <div class="stat-box"><strong>Participant Match Rate:</strong> {{ report_data.object_comparison.participant_match_rate }}%</div>
    </div>

    <h3>Blackbox CoinJoin Object Statistics</h3>
    <div class="stats-boxes">
        <div class="stat-box"><strong>Total Transactions:</strong> {{ report_data.blackbox_obj_stats.total_transactions }}</div>
        <div class="stat-box"><strong>Total Participants:</strong> {{ report_data.blackbox_obj_stats.total_participants }}</div>
        <div class="stat-box"><strong>Avg. Participants/TX:</strong> {{ report_data.blackbox_obj_stats.avg_participants }}</div>
        <div class="stat-box"><strong>Avg. Fee/TX:</strong> {{ report_data.blackbox_obj_stats.avg_fee }} BTC</div>
    </div>

    <h3>Whitebox CoinJoin Object Statistics</h3>
    <div class="stats-boxes">
        <div class="stat-box"><strong>Total Transactions:</strong> {{ report_data.whitebox_obj_stats.total_transactions }}</div>
        <div class="stat-box"><strong>Total Participants:</strong> {{ report_data.whitebox_obj_stats.total_participants }}</div>
        <div class="stat-box"><strong>Avg. Participants/TX:</strong> {{ report_data.whitebox_obj_stats.avg_participants }}</div>
        <div class="stat-box"><strong>Avg. Fee/TX:</strong> {{ report_data.whitebox_obj_stats.avg_fee }} BTC</div>
    </div>

    <h3>Detailed Object Comparison per Transaction</h3>
    <table>
      <thead>
        <tr>
          <th>TXID</th>
          <th>Block Height</th>
          <th>BB Participants</th>
          <th>WB Participants</th>
          <th>Matched Participants</th>
          <th>BB CJ Amount</th>
          <th>WB CJ Amount</th>
          <th>WB Taker Client(s)</th>
        </tr>
      </thead>
      <tbody>
        {% for tx in report_data.object_comparison.obj_comparison %}
        <tr{% if tx.participants_bb == 0 %} style="background-color: #ffdddd;"{% endif %}>
          <td><code>{{ tx.txid }}</code></td>
          <td>{{ tx.block_height }}</td>
          <td>{{ tx.participants_bb }}</td>
          <td>{{ tx.participants_wb }}</td>
          <td>{{ tx.matched_participants }}</td>
          <td>{{ "%.8f"|format(tx.blackbox_cj_amount) }} BTC</td>
          <td>{{ "%.8f"|format(tx.whitebox_cj_amount) }} BTC</td>
          <td>{{ tx.wb_taker_clients }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <h3>Detailed Participant Role Breakdown</h3>
    <table>
        <thead>
            <tr>
                <th>TXID</th>
                <th>Taker Client</th>
                <th>BB Participant Signature</th>
                <th>BB Role</th>
                <th>WB Role(s)</th>
            </tr>
        </thead>
        <tbody>
            {% for part_detail in report_data.detailed_participant_breakdown %}
            <tr>
                <td><code>{{ part_detail.txid }}</code></td>
                <td>{{ part_detail.taker_client }}</td>
                <td><code>{{ part_detail.bb_sig }}</code></td>
                <td>{{ part_detail.bb_role }}</td>
                <td {% if not part_detail.role_match %}style="background-color: #ffcccc;"{% endif %}>{{ part_detail.wb_roles }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <!-- CoinJoin Chain Analysis Section -->
    <h2>CoinJoin Chain Analysis</h2>

    <h3>Identified Blackbox Chains ({{ report_data.blackbox_identified_chains | length }})</h3>
    {% if report_data.blackbox_identified_chains %}
    <table>
        <thead>
            <tr>
                <th>Chain ID</th>
                <th>Length</th>
                <th>Start Block</th>
                <th>End Block</th>
                <th>Duration (Blocks)</th>
                <th>Tree Representation</th>
            </tr>
        </thead>
        <tbody>
            {% for chain in report_data.blackbox_identified_chains %}
            <tr>
                <td><code>{{ chain.id }}</code></td>
                <td>{{ chain.length }}</td>
                <td>{{ chain.start_block }}</td>
                <td>{{ chain.end_block }}</td>
                <td>{{ chain.duration_blocks }}</td>
                <td><pre>{{ chain.tree_representation }}</pre></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>No blackbox CoinJoin chains were identified.</p>
    {% endif %}

    <h3>Identified Whitebox Chains ({{ report_data.whitebox_identified_chains | length }})</h3>
    {% if report_data.whitebox_identified_chains %}
    <table>
        <thead>
            <tr>
                <th>Chain ID</th>
                <th>Length</th>
                <th>Start Block</th>
                <th>End Block</th>
                <th>Duration (Blocks)</th>
                <th>Tree Representation</th>
            </tr>
        </thead>
        <tbody>
            {% for chain in report_data.whitebox_identified_chains %}
            <tr>
                <td><code>{{ chain.id }}</code></td>
                <td>{{ chain.length }}</td>
                <td>{{ chain.start_block }}</td>
                <td>{{ chain.end_block }}</td>
                <td>{{ chain.duration_blocks }}</td>
                <td><pre>{{ chain.tree_representation }}</pre></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>No whitebox CoinJoin chains were identified.</p>
    {% endif %}

    <h3>Chain Comparison Summary</h3>
    {% if report_data.chain_comparison_summary %}
    <div class="stats-boxes">
        <div class="stat-box"><strong>Total Blackbox Chains:</strong> {{ report_data.chain_comparison_summary.total_blackbox_chains }}</div>
        <div class="stat-box"><strong>Total Whitebox Chains:</strong> {{ report_data.chain_comparison_summary.total_whitebox_chains }}</div>
        <div class="stat-box"><strong>Matched Pairs:</strong> {{ report_data.chain_comparison_summary.num_matched_pairs }}</div>
        <div class="stat-box"><strong>Fully Matched Pairs:</strong> {{ report_data.chain_comparison_summary.num_fully_matched_pairs }}</div>
        <div class="stat-box"><strong>Partially Matched Pairs:</strong> {{ report_data.chain_comparison_summary.num_partially_matched_pairs }}</div>
    </div>

    <h4>Matched Chain Pairs ({{ report_data.chain_comparison_summary.matched_chain_pairs | length }})</h4>
    {% if report_data.chain_comparison_summary.matched_chain_pairs %}
    <table>
        <thead>
            <tr>
                <th>Blackbox Chain ID</th>
                <th>Whitebox Chain ID</th>
                <th>Similarity Score</th>
                <th>Full Match?</th>
                <th>Chain Comparison</th>
            </tr>
        </thead>
        <tbody>
            {% for pair in report_data.chain_comparison_summary.matched_chain_pairs %}
            <tr>
                <td><code>{{ pair.blackbox_chain_id }}</code></td>
                <td><code>{{ pair.whitebox_chain_id }}</code></td>
                <td>{{ "%.4f"|format(pair.similarity_score) }}</td>
                <td>{{ pair.is_full_match }}</td>
                <td>
                    {% if pair.colored_tree_comparison %}
                        {{ pair.colored_tree_comparison | safe }}
                    {% else %}
                        <details>
                            <summary>Common TXIDs</summary>
                            <div class="truncated-text">{{ pair.common_txids | join(', ') }}</div>
                        </details>
                        <details>
                            <summary>Only in Blackbox</summary>
                            <div class="truncated-text">{{ pair.only_blackbox_txids | join(', ') }}</div>
                        </details>
                        <details>
                            <summary>Only in Whitebox</summary>
                            <div class="truncated-text">{{ pair.only_whitebox_txids | join(', ') }}</div>
                        </details>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>No chain pairs were matched.</p>
    {% endif %}

    <h4>Unmatched Blackbox Chains ({{ report_data.chain_comparison_summary.unmatched_blackbox_chain_ids | length }})</h4>
    {% if report_data.chain_comparison_summary.unmatched_blackbox_chain_ids %}
    <ul>
        {% for chain_id in report_data.chain_comparison_summary.unmatched_blackbox_chain_ids %}
        <li><code>{{ chain_id }}</code></li>
        {% endfor %}
    </ul>
    {% else %}
    <p>All blackbox chains were matched or no blackbox chains were identified.</p>
    {% endif %}

    <h4>Unmatched Whitebox Chains ({{ report_data.chain_comparison_summary.unmatched_whitebox_chain_ids | length }})</h4>
    {% if report_data.chain_comparison_summary.unmatched_whitebox_chain_ids %}
    <ul>
        {% for chain_id in report_data.chain_comparison_summary.unmatched_whitebox_chain_ids %}
        <li><code>{{ chain_id }}</code></li>
        {% endfor %}
    </ul>
    {% else %}
    <p>All whitebox chains were matched or no whitebox chains were identified.</p>
    {% endif %}
    {% else %}
    <p>Chain comparison data is not available.</p>
    {% endif %}
    <!-- End CoinJoin Chain Analysis Section -->

    <h2>TXID Comparison Lists</h2>
    <div class="stats-boxes">
        <div class="stat-box"><strong>All Plain TXIDs:</strong> {{ report_data.txid_lists.all_plain_txids }}</div>
        <div class="stat-box"><strong>Blackbox Chain TXIDs:</strong> {{ report_data.txid_lists.blackbox_chain_txids }}</div>
        <div class="stat-box"><strong>Whitebox Chain TXIDs:</strong> {{ report_data.txid_lists.whitebox_chain_txids }}</div>
        <div class="stat-box"><strong>Unattributed in Blackbox:</strong> {{ report_data.txid_lists.unattributed_in_blackbox }}</div>
        <div class="stat-box"><strong>Unattributed in Whitebox:</strong> {{ report_data.txid_lists.unattributed_in_whitebox }}</div>
    </div>

    {{ blackbox_iframe | safe }}
    {{ whitebox_iframe | safe }}
  </div>
  <script>
    // Optional: Add any JS for interactivity here, e.g., table sorting
  </script>
</body>
</html>
    """

    template = env.from_string(template_html)
    html_content = template.render(report_data=report_data, blackbox_iframe=blackbox_iframe, whitebox_iframe=whitebox_iframe)

    # Write HTML to file
    output_path = os.path.join(output_dir, "unified_coinjoin_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Unified report generated: {os.path.abspath(output_path)}")


if __name__ == '__main__':
    # This is a placeholder for actual data loading and function call
    # In a real scenario, you would load your blackbox_results, whitebox_data,
    # blackbox_cj_objs, and whitebox_cj_objs from files or other sources.
    
    # Example Usage (requires dummy data):
    print("This script is intended to be imported and used with actual analysis data.")
    print("To run a test, you would need to populate dummy data structures.")

    # Dummy CoinJoin objects (replace with actual loading)
    from joinmarket.common.coinjoin_model import CoinJoin as CJ_obj # Alias for clarity
    
    # Minimal CJ objects for chain identification testing
    bb_cj1 = CJ_obj(txid="bb_tx1", block_height=100, participants=[], tx={})
    bb_cj2 = CJ_obj(txid="bb_tx2", block_height=101, participants=[], tx={})
    bb_cj3 = CJ_obj(txid="bb_tx3", block_height=102, participants=[], tx={})
    wb_cj1 = CJ_obj(txid="wb_tx1", block_height=100, participants=[], tx={})
    wb_cj2 = CJ_obj(txid="bb_tx2", block_height=101, participants=[], tx={}) # Common with bb_cj2
    wb_cj4 = CJ_obj(txid="wb_tx4", block_height=103, participants=[], tx={})

    dummy_blackbox_cj_objs = [bb_cj1, bb_cj2, bb_cj3]
    dummy_whitebox_cj_objs = [wb_cj1, wb_cj2, wb_cj4]

    # Dummy results (simplified)
    dummy_blackbox_results = [
        {"txid": "bb_tx1"}, {"txid": "bb_tx2"}, {"txid": "bb_tx3"}
    ]
    dummy_whitebox_data = [
        {"txid": "wb_tx1"}, {"txid": "bb_tx2"}, {"txid": "wb_tx4"}
    ]

    # Create a temporary output directory
    current_script_dir = Path(__file__).parent
    temp_output_dir = current_script_dir / "temp_report_output"
    temp_output_dir.mkdir(exist_ok=True)

    print(f"Generating dummy report in: {temp_output_dir.resolve()}")
    generate_unified_report(
        blackbox_results=dummy_blackbox_results,
        whitebox_data=dummy_whitebox_data,
        blackbox_cj_objs=dummy_blackbox_cj_objs,
        whitebox_cj_objs=dummy_whitebox_cj_objs,
        output_dir=str(temp_output_dir)
    )
    print("Dummy report generation attempt finished.")
