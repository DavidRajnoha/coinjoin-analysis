import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from joinmarket.comparison.compare_coinjoin import generate_comparison_data, generate_coinjoin_breakdown, generate_object_comparison, compare_coinjoin_chains