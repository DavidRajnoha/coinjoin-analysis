#!/usr/bin/env python3
"""
Functions for generating unified HTML reports comparing blackbox and whitebox CoinJoin analyses.
"""

import os
import pandas as pd
import json
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import List, Dict, Any, Optional

def generate_comparison_data(blackbox_results, whitebox_data):
    """
    Generate comparison data between blackbox and whitebox analyses.
    
    Args:
        blackbox_results: Results from blackbox analysis
        whitebox_data: Results from whitebox analysis
        
    Returns:
        A dictionary with comparison metrics
    """
    # Convert to sets of transaction IDs for comparison
    blackbox_txids = {result['txid'] for result in blackbox_results}
    whitebox_txids = {record['txid'] for record in whitebox_data}
    
    # Find transactions that appear in both or only one analysis
    common_txids = blackbox_txids.intersection(whitebox_txids)
    only_blackbox = blackbox_txids - whitebox_txids
    only_whitebox = whitebox_txids - blackbox_txids
    
    # Build detailed comparison for common transactions
    detailed_comparison = []
    for txid in common_txids:
        blackbox_tx = next((tx for tx in blackbox_results if tx['txid'] == txid), None)
        whitebox_tx = next((tx for tx in whitebox_data if tx['txid'] == txid), None)
        
        if blackbox_tx and whitebox_tx:
            # Compare participant counts
            bb_participants = len(blackbox_tx.get('solutions', [{}])[0]) if blackbox_tx.get('solutions') else 0
            wb_participants = whitebox_tx.get('output_count', 0)
            
            # Compare client attribution
            bb_clients = set()
            for solution in blackbox_tx.get('solutions', []):
                for participant in solution:
                    if participant.get('client'):
                        bb_clients.add(participant['client'])
            
            wb_clients = set(whitebox_tx.get('output_clients', []))
            
            common_clients = bb_clients.intersection(wb_clients)
            only_bb_clients = bb_clients - wb_clients
            only_wb_clients = wb_clients - bb_clients
            
            detailed_comparison.append({
                'txid': txid,
                'block_height': whitebox_tx.get('block', 0),
                'blackbox_participants': bb_participants,
                'whitebox_participants': wb_participants,
                'common_clients': sorted(list(common_clients)),
                'only_blackbox_clients': sorted(list(only_bb_clients)),
                'only_whitebox_clients': sorted(list(only_wb_clients)),
                'attribution_match_percentage': (
                    round(len(common_clients) / max(len(bb_clients.union(wb_clients)), 1) * 100, 2)
                )
            })
    
    # Sort by block height
    detailed_comparison.sort(key=lambda x: x['block_height'])
    
    return {
        'total_blackbox': len(blackbox_txids),
        'total_whitebox': len(whitebox_txids),
        'common': len(common_txids),
        'only_blackbox': len(only_blackbox),
        'only_whitebox': len(only_whitebox),
        'detection_agreement': round(
            len(common_txids) / max(len(blackbox_txids.union(whitebox_txids)), 1) * 100, 2
        ),
        'detailed_comparison': detailed_comparison,
        'common_txids': sorted(list(common_txids)),
        'only_blackbox_txids': sorted(list(only_blackbox)),
        'only_whitebox_txids': sorted(list(only_whitebox))
    }

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
    
    # Create additional comparison using CoinJoin objects
    obj_comparison = generate_object_comparison(blackbox_cj_objs, whitebox_cj_objs)
    
    # Generate detailed breakdown of each CoinJoin transaction
    blackbox_breakdown = generate_coinjoin_breakdown(blackbox_cj_objs, "blackbox")
    whitebox_breakdown = generate_coinjoin_breakdown(whitebox_cj_objs, "whitebox")
    
    # Merge the comparisons
    comparison.update(obj_comparison)
    comparison['blackbox_breakdown'] = blackbox_breakdown
    comparison['whitebox_breakdown'] = whitebox_breakdown
    
    # Convert data to DataFrames for easier templating
    blackbox_df = pd.DataFrame(blackbox_results) if blackbox_results else pd.DataFrame()
    whitebox_df = pd.DataFrame(whitebox_data) if whitebox_data else pd.DataFrame()
    
    # Prepare summary statistics
    blackbox_stats = {
        'total_transactions': len(blackbox_results),
        'total_participants': sum(len(result.get('solutions', [{}])[0]) for result in blackbox_results if result.get('solutions')),
        'avg_participants': round(
            sum(len(result.get('solutions', [{}])[0]) for result in blackbox_results if result.get('solutions')) / 
            max(len(blackbox_results), 1), 2
        ),
    }
    
    whitebox_stats = {
        'total_transactions': len(whitebox_data),
        'total_participants': sum(record.get('output_count', 0) for record in whitebox_data),
        'avg_participants': round(
            sum(record.get('output_count', 0) for record in whitebox_data) / 
            max(len(whitebox_data), 1), 2
        ),
    }
    
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
    h1, h2, h3, h4 {
      color: #2c3e50;
      margin-top: 1.5em;
      margin-bottom: 0.5em;
    }
    h1 {
      text-align: center;
      padding-bottom: 15px;
      border-bottom: 2px solid #eee;
    }
    .flex-container {
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      margin: 20px 0;
    }
    .box {
      flex: 1;
      min-width: 300px;
      padding: 20px;
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .box h3 {
      margin-top: 0;
      padding-bottom: 10px;
      border-bottom: 1px solid #eee;
    }
    .stats-container {
      display: flex;
      flex-wrap: wrap;
      gap: 15px;
      margin-bottom: 25px;
    }
    .stat-box {
      flex: 1;
      min-width: 120px;
      text-align: center;
      padding: 15px;
      background: #f8f9fa;
      border-radius: 6px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .stat-value {
      font-size: 2rem;
      font-weight: bold;
      color: #3498db;
      display: block;
      margin-bottom: 5px;
    }
    .stat-label {
      font-size: 0.9rem;
      color: #7f8c8d;
      text-transform: uppercase;
    }
    table { 
      border-collapse: collapse; 
      width: 100%; 
      margin: 1em 0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      background-color: #fff;
    }
    th, td { 
      border: 1px solid #e0e0e0; 
      padding: 8px 12px; 
      text-align: left;
    }
    th { 
      background: #f5f5f5;
      font-weight: 600;
      color: #333;
    }
    tr:nth-child(even) {
      background-color: #f9f9f9;
    }
    tr:hover {
      background-color: #f1f1f1;
    }
    .visualization-container {
      margin: 30px 0;
      border: 1px solid #eee;
      border-radius: 8px;
      overflow: hidden;
      background-color: #fff;
    }
    .chart-container {
      height: 400px;
      margin: 20px 0;
    }
    .progress-bar {
      background-color: #e9ecef;
      border-radius: 8px;
      height: 25px;
      position: relative;
      margin: 15px 0;
    }
    .progress-fill {
      background-color: #4caf50;
      height: 100%;
      border-radius: 8px;
      text-align: center;
      line-height: 25px;
      color: white;
      position: relative;
    }
    .text-center {
      text-align: center;
    }
    .text-right {
      text-align: right;
    }
    .tab {
      overflow: hidden;
      border: 1px solid #ccc;
      background-color: #f1f1f1;
      border-radius: 8px 8px 0 0;
    }
    .tab button {
      background-color: inherit;
      float: left;
      border: none;
      outline: none;
      cursor: pointer;
      padding: 14px 16px;
      transition: 0.3s;
      font-size: 17px;
    }
    .tab button:hover {
      background-color: #ddd;
    }
    .tab button.active {
      background-color: #fff;
      border-bottom: 2px solid #3498db;
    }
    .tabcontent {
      display: none;
      padding: 20px;
      border: 1px solid #ccc;
      border-top: none;
      border-radius: 0 0 8px 8px;
      animation: fadeEffect 1s;
    }
    @keyframes fadeEffect {
      from {opacity: 0;}
      to {opacity: 1;}
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Unified CoinJoin Analysis Report</h1>
    
    <h2>Comparison Overview</h2>
    <div class="stats-container">
      <div class="stat-box">
        <span class="stat-value">{{ comparison.detection_agreement }}%</span>
        <span class="stat-label">Detection Agreement</span>
      </div>
      <div class="stat-box">
        <span class="stat-value">{{ comparison.total_blackbox }}</span>
        <span class="stat-label">Blackbox CoinJoins</span>
      </div>
      <div class="stat-box">
        <span class="stat-value">{{ comparison.total_whitebox }}</span>
        <span class="stat-label">Whitebox CoinJoins</span>
      </div>
      <div class="stat-box">
        <span class="stat-value">{{ comparison.common }}</span>
        <span class="stat-label">Common CoinJoins</span>
      </div>
    </div>
    
    <div class="flex-container">
      <div class="box">
        <h3>Blackbox-Only CoinJoins</h3>
        <p>Transactions detected only by heuristic analysis: <strong>{{ comparison.only_blackbox }}</strong></p>
        {% if comparison.only_blackbox_txids %}
        <details>
          <summary>View Transaction IDs</summary>
          <ul>
            {% for txid in comparison.only_blackbox_txids %}
            <li>{{ txid }}</li>
            {% endfor %}
          </ul>
        </details>
        {% endif %}
      </div>
      <div class="box">
        <h3>Whitebox-Only CoinJoins</h3>
        <p>Transactions detected only with ground truth data: <strong>{{ comparison.only_whitebox }}</strong></p>
        {% if comparison.only_whitebox_txids %}
        <details>
          <summary>View Transaction IDs</summary>
          <ul>
            {% for txid in comparison.only_whitebox_txids %}
            <li>{{ txid }}</li>
            {% endfor %}
          </ul>
        </details>
        {% endif %}
      </div>
    </div>
    
    <h2>Analysis Visualizations</h2>
    <div class="tab">
      <button class="tablinks" onclick="openTab(event, 'BlackboxVis')" id="defaultOpen">Blackbox Analysis</button>
      <button class="tablinks" onclick="openTab(event, 'WhiteboxVis')">Whitebox Analysis</button>
    </div>

    <div id="BlackboxVis" class="tabcontent">
      {{ blackbox_iframe }}
    </div>

    <div id="WhiteboxVis" class="tabcontent">
      {{ whitebox_iframe }}
    </div>
    
    <h2>Detailed Comparison</h2>
    {% if comparison.detailed_comparison %}
    <table>
      <thead>
        <tr>
          <th>Transaction ID</th>
          <th>Block Height</th>
          <th>Blackbox Participants</th>
          <th>Whitebox Participants</th>
          <th>Attribution Match</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {% for tx in comparison.detailed_comparison %}
        <tr>
          <td>{{ tx.txid }}</td>
          <td>{{ tx.block_height }}</td>
          <td>{{ tx.blackbox_participants }}</td>
          <td>{{ tx.whitebox_participants }}</td>
          <td>
            <div class="progress-bar">
              <div class="progress-fill" style="width: {{ tx.attribution_match_percentage }}%;">
                {{ tx.attribution_match_percentage }}%
              </div>
            </div>
          </td>
          <td>
            <details>
              <summary>View Details</summary>
              <p><strong>Common Clients:</strong> {{ tx.common_clients|join(', ') }}</p>
              <p><strong>Only in Blackbox:</strong> {{ tx.only_blackbox_clients|join(', ') }}</p>
              <p><strong>Only in Whitebox:</strong> {{ tx.only_whitebox_clients|join(', ') }}</p>
            </details>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p>No common transactions found for detailed comparison.</p>
    {% endif %}
    
    <h2>Object Comparison</h2>
    {% if comparison.obj_comparison %}
    <table>
      <thead>
        <tr>
          <th>Transaction ID</th>
          <th>Block Height</th>
          <th>Blackbox Participants</th>
          <th>Whitebox Participants</th>
          <th>Client Match</th>
          <th>Role Accuracy</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {% for tx in comparison.obj_comparison %}
        <tr>
          <td>{{ tx.txid }}</td>
          <td>{{ tx.block_height }}</td>
          <td>{{ tx.blackbox_participants }}</td>
          <td>{{ tx.whitebox_participants }}</td>
          <td>
            <div class="progress-bar">
              <div class="progress-fill" style="width: {{ tx.client_match_percentage }}%;">
                {{ tx.client_match_percentage }}%
              </div>
            </div>
          </td>
          <td>
            <div class="progress-bar">
              <div class="progress-fill" style="width: {{ tx.role_accuracy }}%;">
                {{ tx.role_accuracy }}%
              </div>
            </div>
          </td>
          <td>
            <details>
              <summary>View Details</summary>
              <p><strong>Common Clients:</strong> {{ tx.common_clients|join(', ') }}</p>
              <p><strong>Only in Blackbox:</strong> {{ tx.only_blackbox_clients|join(', ') }}</p>
              <p><strong>Only in Whitebox:</strong> {{ tx.only_whitebox_clients|join(', ') }}</p>
            </details>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p>No common transactions found for object comparison.</p>
    {% endif %}
    
    <h2>Analysis Summary</h2>
    <div class="flex-container">
      <div class="box">
        <h3>Blackbox Analysis</h3>
        <div class="stats-container">
          <div class="stat-box">
            <span class="stat-value">{{ blackbox_stats.total_transactions }}</span>
            <span class="stat-label">Total Transactions</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ blackbox_stats.total_participants }}</span>
            <span class="stat-label">Total Participants</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ blackbox_stats.avg_participants }}</span>
            <span class="stat-label">Avg Participants</span>
          </div>
        </div>
      </div>
      <div class="box">
        <h3>Whitebox Analysis</h3>
        <div class="stats-container">
          <div class="stat-box">
            <span class="stat-value">{{ whitebox_stats.total_transactions }}</span>
            <span class="stat-label">Total Transactions</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ whitebox_stats.total_participants }}</span>
            <span class="stat-label">Total Participants</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ whitebox_stats.avg_participants }}</span>
            <span class="stat-label">Avg Participants</span>
          </div>
        </div>
      </div>
      <div class="box">
        <h3>Blackbox Object Analysis</h3>
        <div class="stats-container">
          <div class="stat-box">
            <span class="stat-value">{{ blackbox_obj_stats.total_transactions }}</span>
            <span class="stat-label">Total Transactions</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ blackbox_obj_stats.total_participants }}</span>
            <span class="stat-label">Total Participants</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ blackbox_obj_stats.avg_participants }}</span>
            <span class="stat-label">Avg Participants</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ blackbox_obj_stats.avg_fee }}</span>
            <span class="stat-label">Avg Fee</span>
          </div>
        </div>
      </div>
      <div class="box">
        <h3>Whitebox Object Analysis</h3>
        <div class="stats-container">
          <div class="stat-box">
            <span class="stat-value">{{ whitebox_obj_stats.total_transactions }}</span>
            <span class="stat-label">Total Transactions</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ whitebox_obj_stats.total_participants }}</span>
            <span class="stat-label">Total Participants</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ whitebox_obj_stats.avg_participants }}</span>
            <span class="stat-label">Avg Participants</span>
          </div>
          <div class="stat-box">
            <span class="stat-value">{{ whitebox_obj_stats.avg_fee }}</span>
            <span class="stat-label">Avg Fee</span>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Detailed Breakdown section for Blackbox Analysis -->
    <div class="section">
      <h2 id="blackbox-breakdown">Blackbox Analysis: Detailed CoinJoin Breakdown</h2>
      <p>Detailed analysis of each CoinJoin transaction detected by the blackbox analysis.</p>
      
      <div class="table-container">
        <input type="text" id="blackbox-search" class="search" placeholder="Search...">
        <table id="blackbox-table" class="data-table">
          <thead>
            <tr>
              <th onclick="sortTable('blackbox-table', 0)">TxID ↕</th>
              <th onclick="sortTable('blackbox-table', 1)">Block Height ↕</th>
              <th onclick="sortTable('blackbox-table', 2)">Participants ↕</th>
              <th onclick="sortTable('blackbox-table', 3)">CJ Amount ↕</th>
              <th onclick="sortTable('blackbox-table', 4)">Fee ↕</th>
              <th onclick="sortTable('blackbox-table', 5)">Details ↕</th>
            </tr>
          </thead>
          <tbody>
            {% for cj in comparison.blackbox_breakdown %}
              <tr>
                <td><a href="https://mempool.space/tx/{{cj.txid}}" target="_blank">{{ cj.txid[:8] }}...</a></td>
                <td>{{ cj.block_height }}</td>
                <td>{{ cj.participant_count }}</td>
                <td>{{ cj.cj_amount }}</td>
                <td>{{ cj.miner_fee }}</td>
                <td>
                  <button onclick="toggleDetails('blackbox-details-{{loop.index}}')">Show/Hide</button>
                  <div id="blackbox-details-{{loop.index}}" class="details-container" style="display:none;">
                    <h4>Participants:</h4>
                    <table class="nested-table">
                      <thead>
                        <tr>
                          <th>Role</th>
                          <th>Client</th>
                          <th>Inputs</th>
                          <th>CoinJoin Output</th>
                          <th>Change Output</th>
                          <th>Delta</th>
                        </tr>
                      </thead>
                      <tbody>
                        {% for p in cj.participants %}
                          <tr>
                            <td>{{ p.role }}</td>
                            <td>{{ p.client if p.client else 'Unknown' }}</td>
                            <td>
                              {% if p.inputs %}
                                <ul class="compact-list">
                                  {% for inp in p.inputs %}
                                    <li>{{ inp.txid[:6] }}...{{ inp.txid[-6:] }}:{{ inp.vout }} ({{ inp.value }})</li>
                                  {% endfor %}
                                </ul>
                              {% else %}
                                No inputs
                              {% endif %}
                            </td>
                            <td>{{ p.cj_output.value }} (index: {{ p.cj_output.n }})</td>
                            <td>
                              {% if p.change_output %}
                                {{ p.change_output.value }} (index: {{ p.change_output.n }})
                              {% else %}
                                None
                              {% endif %}
                            </td>
                            <td>{{ p.delta }}</td>
                          </tr>
                        {% endfor %}
                      </tbody>
                    </table>
                  </div>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Detailed Breakdown section for Whitebox Analysis -->
    <div class="section">
      <h2 id="whitebox-breakdown">Whitebox Analysis: Detailed CoinJoin Breakdown</h2>
      <p>Detailed analysis of each CoinJoin transaction detected by the whitebox analysis.</p>
      
      <div class="table-container">
        <input type="text" id="whitebox-search" class="search" placeholder="Search...">
        <table id="whitebox-table" class="data-table">
          <thead>
            <tr>
              <th onclick="sortTable('whitebox-table', 0)">TxID ↕</th>
              <th onclick="sortTable('whitebox-table', 1)">Block Height ↕</th>
              <th onclick="sortTable('whitebox-table', 2)">Participants ↕</th>
              <th onclick="sortTable('whitebox-table', 3)">CJ Amount ↕</th>
              <th onclick="sortTable('whitebox-table', 4)">Fee ↕</th>
              <th onclick="sortTable('whitebox-table', 5)">Details ↕</th>
            </tr>
          </thead>
          <tbody>
            {% for cj in comparison.whitebox_breakdown %}
              <tr>
                <td><a href="https://mempool.space/tx/{{cj.txid}}" target="_blank">{{ cj.txid[:8] }}...</a></td>
                <td>{{ cj.block_height }}</td>
                <td>{{ cj.participant_count }}</td>
                <td>{{ cj.cj_amount }}</td>
                <td>{{ cj.miner_fee }}</td>
                <td>
                  <button onclick="toggleDetails('whitebox-details-{{loop.index}}')">Show/Hide</button>
                  <div id="whitebox-details-{{loop.index}}" class="details-container" style="display:none;">
                    <h4>Participants:</h4>
                    <table class="nested-table">
                      <thead>
                        <tr>
                          <th>Role</th>
                          <th>Client</th>
                          <th>Inputs</th>
                          <th>CoinJoin Output</th>
                          <th>Change Output</th>
                          <th>Delta</th>
                        </tr>
                      </thead>
                      <tbody>
                        {% for p in cj.participants %}
                          <tr>
                            <td>{{ p.role }}</td>
                            <td>{{ p.client if p.client else 'Unknown' }}</td>
                            <td>
                              {% if p.inputs %}
                                <ul class="compact-list">
                                  {% for inp in p.inputs %}
                                    <li>{{ inp.txid[:6] }}...{{ inp.txid[-6:] }}:{{ inp.vout }} ({{ inp.value }})</li>
                                  {% endfor %}
                                </ul>
                              {% else %}
                                No inputs
                              {% endif %}
                            </td>
                            <td>{{ p.cj_output.value }} (index: {{ p.cj_output.n }})</td>
                            <td>
                              {% if p.change_output %}
                                {{ p.change_output.value }} (index: {{ p.change_output.n }})
                              {% else %}
                                None
                              {% endif %}
                            </td>
                            <td>{{ p.delta }}</td>
                          </tr>
                        {% endfor %}
                      </tbody>
                    </table>
                  </div>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
    
    <script>
      function openTab(evt, tabName) {
        var i, tabcontent, tablinks;
        tabcontent = document.getElementsByClassName("tabcontent");
        for (i = 0; i < tabcontent.length; i++) {
          tabcontent[i].style.display = "none";
        }
        tablinks = document.getElementsByClassName("tablinks");
        for (i = 0; i < tablinks.length; i++) {
          tablinks[i].className = tablinks[i].className.replace(" active", "");
        }
        document.getElementById(tabName).style.display = "block";
        evt.currentTarget.className += " active";
      }
      
      // Get the element with id="defaultOpen" and click on it
      document.getElementById("defaultOpen").click();
    </script>
  </div>

  <script>
    function sortTable(tableId, colIndex) {
      var table = document.getElementById(tableId);
      var rows = table.rows;
      var switching = true;
      
      while (switching) {
        switching = false;
        var i = 1;
        while (i < rows.length - 1) {
          var shouldSwitch = false;
          var row1 = rows[i].getElementsByTagName("TD")[colIndex];
          var row2 = rows[i + 1].getElementsByTagName("TD")[colIndex];
          var row1Value = row1.textContent.toLowerCase();
          var row2Value = row2.textContent.toLowerCase();
          
          if (row1Value > row2Value) {
            shouldSwitch = true;
            break;
          }
          i++;
        }
        if (shouldSwitch) {
          rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
          switching = true;
        }
      }
    }
  </script>
  
  <script>
    function toggleDetails(id) {
      var details = document.getElementById(id);
      if (details.style.display === "block") {
        details.style.display = "none";
      } else {
        details.style.display = "block";
      }
    }
  </script>
</body>
</html>
"""
    
    # Render template with data
    rendered_html = Environment().from_string(template_html).render(
        comparison=comparison,
        blackbox_stats=blackbox_stats,
        whitebox_stats=whitebox_stats,
        blackbox_obj_stats=blackbox_obj_stats,
        whitebox_obj_stats=whitebox_obj_stats,
        blackbox_iframe=blackbox_iframe,
        whitebox_iframe=whitebox_iframe
    )
    
    # Write HTML report to file
    with open(os.path.join(output_dir, "report.html"), "w") as f:
        f.write(rendered_html)
    
    # Save comparison data as JSON for reference
    with open(os.path.join(output_dir, "comparison_data.json"), "w") as f:
        json.dump(comparison, f, indent=2)

def generate_object_comparison(blackbox_cj_objs, whitebox_cj_objs):
    """
    Generate comparison data between blackbox and whitebox analyses using CoinJoin objects.
    
    Args:
        blackbox_cj_objs: CoinJoin objects from blackbox analysis
        whitebox_cj_objs: CoinJoin objects from whitebox analysis
        
    Returns:
        A dictionary with additional comparison metrics
    """
    # Map of txids to CoinJoin objects for quick lookup
    blackbox_map = {cj.txid: cj for cj in blackbox_cj_objs}
    whitebox_map = {cj.txid: cj for cj in whitebox_cj_objs}
    
    # Find transactions that appear in both analyses
    common_txids = set(blackbox_map.keys()).intersection(set(whitebox_map.keys()))
    
    # Detailed comparison for each common transaction
    participant_comparison = []
    for txid in common_txids:
        bb_cj = blackbox_map[txid]
        wb_cj = whitebox_map[txid]
        
        # Compare participant counts
        bb_participants = len(bb_cj.participants)
        wb_participants = len(wb_cj.participants)
        
        # Compare CoinJoin amount
        bb_cj_amount = bb_cj.cj_amount
        wb_cj_amount = wb_cj.cj_amount
        
        # Compare miner fee
        bb_fee = bb_cj.miner_fee
        wb_fee = wb_cj.miner_fee
        
        # Compare client attribution
        bb_clients = bb_cj.input_clients.union(bb_cj.output_clients)
        wb_clients = wb_cj.input_clients.union(wb_cj.output_clients)
        
        common_clients = bb_clients.intersection(wb_clients)
        only_bb_clients = bb_clients - wb_clients
        only_wb_clients = wb_clients - bb_clients
        
        # Calculate role accuracy
        role_matches = 0
        total_roles = 0
        
        # Compare roles for common clients
        for client in common_clients:
            # Find participants with this client in both analyses
            bb_participants_with_client = [p for p in bb_cj.participants if p.client == client]
            wb_participants_with_client = [p for p in wb_cj.participants if p.client == client]
            
            # Count matches
            for bb_p in bb_participants_with_client:
                for wb_p in wb_participants_with_client:
                    if bb_p.role == wb_p.role and bb_p.role != "unknown":
                        role_matches += 1
                total_roles += 1
        
        role_accuracy = round(role_matches / max(total_roles, 1) * 100, 2)
        
        participant_comparison.append({
            'txid': txid,
            'block_height': bb_cj.block_height,
            'blackbox_participants': bb_participants,
            'whitebox_participants': wb_participants,
            'blackbox_cj_amount': bb_cj_amount,
            'whitebox_cj_amount': wb_cj_amount,
            'blackbox_fee': bb_fee,
            'whitebox_fee': wb_fee,
            'common_clients': sorted(list(common_clients)),
            'only_blackbox_clients': sorted(list(only_bb_clients)),
            'only_whitebox_clients': sorted(list(only_wb_clients)),
            'client_match_percentage': round(len(common_clients) / max(len(bb_clients.union(wb_clients)), 1) * 100, 2),
            'role_accuracy': role_accuracy
        })
    
    # Sort by block height
    participant_comparison.sort(key=lambda x: x['block_height'])
    
    return {
        'obj_comparison': participant_comparison,
        'participant_comparison_count': len(participant_comparison),
        'role_accuracy_avg': round(
            sum(c['role_accuracy'] for c in participant_comparison) / 
            max(len(participant_comparison), 1), 2
        ),
        'client_match_avg': round(
            sum(c['client_match_percentage'] for c in participant_comparison) / 
            max(len(participant_comparison), 1), 2
        )
    }

def generate_coinjoin_breakdown(cj_objs, analysis_type="blackbox"):
    """
    Generate detailed breakdown information for each CoinJoin transaction.
    
    Args:
        cj_objs: List of CoinJoin objects
        analysis_type: Type of analysis ("blackbox" or "whitebox")
        
    Returns:
        List of dictionaries with breakdown information
    """
    if not cj_objs:
        return []
    
    breakdowns = []
    
    for cj in cj_objs:
        # Basic information
        breakdown = {
            'txid': cj.txid,
            'block_height': cj.block_height,
            'participant_count': len(cj.participants),
            'cj_amount': cj.cj_amount,
            'miner_fee': cj.miner_fee,
            'participants': []
        }
        
        # Participant details
        for p in cj.participants:
            participant_info = {
                'role': p.role,
                'client': p.client,
                'inputs': [
                    {
                        'txid': inp.txid,
                        'vout': inp.vout,
                        'value': inp.value,
                        'address': inp.address
                    } for inp in p.inputs
                ],
                'cj_output': {
                    'n': p.cj_output.n,
                    'value': p.cj_output.value,
                    'address': p.cj_output.address
                },
                'change_output': None,
                'delta': p.delta
            }
            
            if p.change_output:
                participant_info['change_output'] = {
                    'n': p.change_output.n,
                    'value': p.change_output.value,
                    'address': p.change_output.address
                }
                
            breakdown['participants'].append(participant_info)
        
        breakdowns.append(breakdown)
    
    # Sort by block height
    breakdowns.sort(key=lambda x: x['block_height'])
    
    return breakdowns
