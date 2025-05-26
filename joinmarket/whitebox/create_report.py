#!/usr/bin/env python3
"""
Functions for generating HTML reports from CoinJoin data
"""

import os
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape


def save_summary(cj_data, out_dir):
    """
    Save CoinJoin summary data to CSV and JSON files.
    Returns a pandas DataFrame with the data.
    """
    df = pd.DataFrame(cj_data)
    df.to_csv(os.path.join(out_dir, "coinjoin_summary.csv"), index=False)
    df.to_json(os.path.join(out_dir, "coinjoin_summary.json"), orient="records", indent=2)
    return df


def render_html_report(df: pd.DataFrame, out_dir: str):
    """
    Generate an HTML report from CoinJoin data.
    """
    env = Environment(
        loader=FileSystemLoader(os.path.dirname(__file__) or "."),
        autoescape=select_autoescape()
    )

    # Check if the interactive visualization exists
    interactive_vis_path = os.path.join(out_dir, "coinjoin_interactive.html")
    iframe_block = ""
    if os.path.exists(interactive_vis_path):
        iframe_block = '''
        <div class="interactive-container">
            <iframe src="coinjoin_interactive.html"
                    style="width:100%;height:1000px;border:none;border-radius:4px;display:block;"
                    loading="lazy"
                    id="graph-iframe"></iframe>
        </div>'''

    template_html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>CoinJoin Simulation Report</title>
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
    }
    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 2em;
    }
    table { 
      border-collapse: collapse; 
      width: 100%; 
      margin: 1em 0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
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
    img { 
      max-width: 100%; 
      height: auto;
      display: block; 
      margin: 2em 0;
      box-shadow: 0 2px 5px rgba(0,0,0,0.1);
      border-radius: 4px;
    }
    .interactive-container {
      width: 100%;
      margin: 2em 0;
      box-shadow: 0 2px 10px rgba(0,0,0,0.1);
      border-radius: 4px;
      overflow: hidden;
      max-width: 100%;
      padding: 0;
    }
    .vis-controls {
      position: absolute;
      top: 15px;
      right: 15px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.95);
      padding: 8px 12px;
      border-radius: 4px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      display: flex;
      gap: 5px;
    }
    .vis-controls button {
      background: #f8f9fa;
      border: 1px solid #dadce0;
      border-radius: 4px;
      color: #3c4043;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      padding: 6px 12px;
      transition: all 0.2s;
      min-width: 40px;
    }
    .vis-controls button:hover {
      background: #f1f3f4;
      border-color: #d2e3fc;
    }
    .vis-controls button:active {
      background: #e8f0fe;
      transform: translateY(1px);
    }
    h1 {
      color: #1a73e8;
      border-bottom: 1px solid #e0e0e0;
      padding-bottom: 10px;
      margin-bottom: 20px;
    }
    h2 {
      color: #5f6368;
      margin-top: 1.8em;
      padding-bottom: 6px;
      border-bottom: 1px solid #f0f0f0;
    }
    .container {
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 20px;
    }
    @media (max-width: 768px) {
      body {
        margin: 1em;
      }
      .interactive-vis {
        height: 700px;
        min-height: 600px;
      }
    }
  </style>
  <!-- Include required scripts for the interactive visualization -->
  <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.js"></script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.css" rel="stylesheet" type="text/css" />
</head>
<body>
  <div class="container">
    <h1>CoinJoin Simulation Report</h1>
  <h2>Summary</h2>
  <p>Total CoinJoins: {{ df.shape[0] }}</p>
  {% if df.empty %}
    <p><b>No CoinJoins found in this simulation run.</b></p>
  {% endif %}

  {% if not df.empty %}
    <h2>Statistics</h2>
    <img src="cj_output_count.png" alt="Output Count Distribution">
    <img src="cj_input_count.png" alt="Input Count Distribution">
    <img src="cj_output_amounts.png" alt="Output Amounts Distribution">
    
    <h2>Interactive CoinJoin Transaction Flow Graph</h2>
    {{ iframe_block|safe }}

    <h2>CoinJoin Details</h2>
    <table>
      <thead>
        <tr>{% for col in df.columns %}<th>{{ col }}</th>{% endfor %}</tr>
      </thead>
      <tbody>
        {% for row in df.itertuples() %}
          <tr>{% for col in df.columns %}<td>{{ row|attr(col) }}</td>{% endfor %}</tr>
        {% endfor %}
      </tbody>
    </table>
  {% endif %}
  </div>
  
  <script>
    // Make the iframe take full width on window resize
    function resizeIframe() {
      const iframe = document.getElementById('graph-iframe');
      if (iframe) {
        const container = document.querySelector('.interactive-container');
        const containerWidth = container.offsetWidth;
        iframe.style.width = '100%';
        iframe.style.maxWidth = containerWidth + 'px';
      }
    }

    // Initial resize
    window.addEventListener('load', resizeIframe);
    // Resize on window size changes
    window.addEventListener('resize', resizeIframe);
  </script>
</body>
</html>
"""
    template = env.from_string(template_html)
    html = template.render(df=df, iframe_block=iframe_block, has_interactive_vis=bool(iframe_block))
    with open(os.path.join(out_dir, "report.html"), "w") as fh:
        fh.write(html)