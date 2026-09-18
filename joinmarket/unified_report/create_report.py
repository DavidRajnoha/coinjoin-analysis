#!/usr/bin/env python3
"""
Functions for generating unified HTML reports comparing blackbox and whitebox CoinJoin analyses.
"""

import os
import sys
from pathlib import Path

import json
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import List, Dict, Any, Optional


from joinmarket.common.analysis_config import AnalysisConfig, DEFAULT_CONFIG
from joinmarket.comparison.chain_visualization import generate_colored_chain_comparison
from joinmarket.unified_report.json_report import build_unified_report_json_from_data
from joinmarket.unified_report.unified_report_data import (
    build_unified_report_data
)

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def safe_format_float(value, decimals=8):
    """Safely format a float value, handling None cases."""
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except (ValueError, TypeError):
        return str(value) if value is not None else "N/A"


def format_timestamp(timestamp):
    """Format Unix timestamp to readable date/time string."""
    if timestamp is None:
        return "N/A"
    try:
        from datetime import datetime
        dt = datetime.fromtimestamp(int(timestamp))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError, OSError):
        return str(timestamp)


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


def render_unified_report_html(report_data: Dict[str, Any], output_dir: str) -> None:
    """
    Render and write the HTML report from report_data, loading template from file.
    """
    env = Environment(
        loader=FileSystemLoader(os.path.dirname(__file__) or "."),
        autoescape=select_autoescape()
    )
    env.filters['safe_format_float'] = safe_format_float
    env.filters['format_timestamp'] = format_timestamp
    template_path = "unified_report_template.html"
    template = env.get_template(template_path)
    html_content = template.render(report_data=report_data, blackbox_iframe="", whitebox_iframe="")
    output_path = os.path.join(output_dir, "unified_coinjoin_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Unified report generated: {os.path.abspath(output_path)}")


def render_unified_report_json(report_data: dict, output_dir: str, extra_metadata: dict = None) -> None:
    """
    Write the JSON report to disk using the given report_data dict.
    """
    output_path = os.path.join(output_dir, "unified_coinjoin_report.json")
    json_str = build_unified_report_json_from_data(report_data, extra_metadata=extra_metadata)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json_str + "\n")
    print(f"JSON report written to: {os.path.abspath(output_path)}")


def generate_unified_report(
    blackbox_results: List[Dict[str, Any]],
    whitebox_data: List[Dict[str, Any]],
    blackbox_cj_objs: List[Any],
    whitebox_cj_objs: List[Any],
    output_dir: str,
    fidelity_bond_stats: Optional[Any] = None,
    run_path: Optional[str] = None,
    show_block_timestamps: bool = False,
    config: AnalysisConfig = DEFAULT_CONFIG,
):
    """
    Generate both HTML and JSON unified CoinJoin reports.

    Args:
        blackbox_results: Results from blackbox analysis
        whitebox_data: Results from whitebox analysis
        blackbox_cj_objs: CoinJoin objects from blackbox analysis
        whitebox_cj_objs: CoinJoin objects from whitebox analysis
        output_dir: Output directory for the reports
        fidelity_bond_stats: Optional FidelityBondStats object for JoinMarket
        run_path: Optional path to the run directory (for identifying sole takers)
    """
    report_data = build_unified_report_data(
        blackbox_results=blackbox_results,
        whitebox_data=whitebox_data,
        blackbox_cj_objs=blackbox_cj_objs,
        whitebox_cj_objs=whitebox_cj_objs,
        fidelity_bond_stats=fidelity_bond_stats,
        run_path=run_path,
        show_block_timestamps=show_block_timestamps,
        config=config,
    )
    render_unified_report_json(report_data, output_dir)
    render_unified_report_html(report_data, output_dir)
