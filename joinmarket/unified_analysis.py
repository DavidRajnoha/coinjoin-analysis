#!/usr/bin/env python3
"""
Unified CoinJoin analysis script that runs both blackbox and whitebox analysis
and generates a comparative report.
"""

import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from joinmarket.unified_report import main

if __name__ == '__main__':
    main()
