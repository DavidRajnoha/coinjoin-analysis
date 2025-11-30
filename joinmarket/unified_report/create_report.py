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
    client_roles: Optional[Dict[str, str]] = None,
    fidelity_bond_stats: Optional[Any] = None,
    run_path: Optional[str] = None
):
    """
    Generate both HTML and JSON unified CoinJoin reports.

    Args:
        blackbox_results: Results from blackbox analysis
        whitebox_data: Results from whitebox analysis
        blackbox_cj_objs: CoinJoin objects from blackbox analysis
        whitebox_cj_objs: CoinJoin objects from whitebox analysis
        output_dir: Output directory for the reports
        client_roles: Optional mapping of client_id to role
        fidelity_bond_stats: Optional FidelityBondStats object for JoinMarket
        run_path: Optional path to the run directory (for identifying sole takers)
    """
    report_data = build_unified_report_data(
        blackbox_results=blackbox_results,
        whitebox_data=whitebox_data,
        blackbox_cj_objs=blackbox_cj_objs,
        whitebox_cj_objs=whitebox_cj_objs,
        output_dir=output_dir,
        client_roles=client_roles,
        fidelity_bond_stats=fidelity_bond_stats,
        run_path=run_path
    )
    render_unified_report_json(report_data, output_dir)
    render_unified_report_html(report_data, output_dir)


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
