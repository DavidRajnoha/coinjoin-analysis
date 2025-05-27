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

from joinmarket.comparison import generate_coinjoin_breakdown, generate_comparison_data, generate_object_comparison


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

    # Generate comparison data
    comparison = generate_comparison_data(blackbox_results, whitebox_data)

    # Create additional comparison using CoinJoin objects (with detailed participant breakdown)
    obj_comparison = generate_object_comparison(blackbox_cj_objs, whitebox_cj_objs, detailed=True)

    # Aggregate detailed participant breakdowns for unified table
    detailed_breakdown = []
    for tx in obj_comparison.get("obj_comparison", []):
        for part in tx.get("participant_breakdown", []):
            entry = {
                "txid": tx["txid"],
                "block_height": tx["block_height"],
                "bb_sig": str(part["bb_sig"]),
                "matched": part["matched"],
                "bb_role": part["bb_role"],
                "wb_roles": ", ".join(part["wb_roles"]),
                "role_match": part["role_match"],
            }
            detailed_breakdown.append(entry)
    comparison.update(obj_comparison)
    comparison['detailed_breakdown'] = detailed_breakdown

    # Calculate CoinJoin object statistics
    blackbox_obj_stats = {
        'total_transactions': len(blackbox_cj_objs),
        'total_participants': sum(len(cj.participants) for cj in blackbox_cj_objs),
        'avg_participants': round(sum(len(cj.participants) for cj in blackbox_cj_objs) / max(len(blackbox_cj_objs), 1), 2),
        'avg_fee': round(sum(cj.miner_fee for cj in blackbox_cj_objs) / max(len(blackbox_cj_objs), 1), 8),
    }

    whitebox_obj_stats = {
        'total_transactions': len(whitebox_cj_objs),
        'total_participants': sum(len(cj.participants) for cj in whitebox_cj_objs),
        'avg_participants': round(sum(len(cj.participants) for cj in whitebox_cj_objs) / max(len(whitebox_cj_objs), 1), 2),
        'avg_fee': round(sum(cj.miner_fee for cj in whitebox_cj_objs) / max(len(whitebox_cj_objs), 1), 8),
    }

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
  </style>
</head>
<body>
  <div class="container">
    <h1>Unified CoinJoin Analysis Report</h1>
    <div class="stats-boxes">
      <div class="stat-box">
        <strong>Total CoinJoins Compared</strong><br>
        {{ comparison.comparison_tx_count }}
      </div>
      <div class="stat-box">
        <strong>Role Accuracy</strong><br>
        {{ (comparison.role_accuracy_avg * 100) | round(2) }}%
      </div>
      <div class="stat-box">
        <strong>Overall Role Success</strong><br>
        {{ (comparison.overall_role_success_avg * 100) | round(2) }}%
      </div>
      <div class="stat-box">
        <strong>Participant Match Rate</strong><br>
        {{ (comparison.participant_match_rate * 100) | round(2) }}%
      </div>
      <div class="stat-box">
        <strong>Matched Participants</strong><br>
        {{ comparison.total_matched_participants }} / {{ comparison.total_bb_participants }}
      </div>
    </div>
    {{ blackbox_iframe | safe }}
    {{ whitebox_iframe | safe }}
    <h2>Object-Level CoinJoin Comparison</h2>
    <table>
      <thead>
        <tr>
          <th>TxID</th>
          <th>Block</th>
          <th>BB Participants</th>
          <th>WB Participants</th>
          <th>Matched</th>
          <th>Role Accuracy (%)</th>
          <th>Overall Role Success (%)</th>
          <th>CJ Amount (BB/WB)</th>
          <th>Miner Fee (BB/WB)</th>
        </tr>
      </thead>
      <tbody>
        {% for tx in comparison.obj_comparison %}
        <tr>
          <td>{{ tx.txid[:8] }}...</td>
          <td>{{ tx.block_height }}</td>
          <td>{{ tx.participants_bb }}</td>
          <td>{{ tx.participants_wb }}</td>
          <td>{{ tx.matched_participants }}</td>
          <td>{{ (tx.role_accuracy * 100) | round(2) }}</td>
          <td>{{ (tx.overall_role_success * 100) | round(2) }}</td>
          <td>{{ tx.blackbox_cj_amount }} / {{ tx.whitebox_cj_amount }}</td>
          <td>{{ tx.blackbox_fee }} / {{ tx.whitebox_fee }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <h2>Detailed Participant Comparison (per CoinJoin)</h2>
    {% if comparison.detailed_breakdown %}
    <table>
      <thead>
        <tr>
          <th>TxID</th>
          <th>Block</th>
          <th>BB Signature</th>
          <th>Matched?</th>
          <th>BB Role</th>
          <th>WB Roles</th>
          <th>Role Match</th>
        </tr>
      </thead>
      <tbody>
        {% for row in comparison.detailed_breakdown %}
        <tr>
          <td>{{ row.txid[:8] }}...</td>
          <td>{{ row.block_height }}</td>
          <td><code>{{ row.bb_sig }}</code></td>
          <td style="text-align:center">{% if row.matched %}✔{% else %}✗{% endif %}</td>
          <td>{{ row.bb_role }}</td>
          <td>{{ row.wb_roles }}</td>
          <td style="text-align:center">{% if row.role_match %}✔{% else %}✗{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p>No detailed breakdown available.</p>
    {% endif %}
  </div>
</body>
</html>
"""

    # Render template with data
    rendered_html = Environment().from_string(template_html).render(
        comparison=comparison,
        blackbox_obj_stats=blackbox_obj_stats,
        whitebox_obj_stats=whitebox_obj_stats,
        blackbox_iframe=blackbox_iframe,
        whitebox_iframe=whitebox_iframe
    )

    # Write HTML report to file
    with open(os.path.join(output_dir, "report.html"), "w") as f:
        f.write(rendered_html)

    # Save comparison data as JSON for reference
    with open(os.path.join(output_dir, "comparison.json"), "w") as f:
        json.dump(convert_frozensets(comparison), f, indent=2)
