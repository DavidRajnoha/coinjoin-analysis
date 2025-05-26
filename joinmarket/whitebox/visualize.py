#!/usr/bin/env python3
"""
Functions for visualizing CoinJoin data
"""

import os
import matplotlib.pyplot as plt
import pandas as pd

def plot_stats(df: pd.DataFrame, out_dir: str):
    """
    Generate statistical plots from CoinJoin data.
    """
    if df.empty:
        print("No coinjoin data to plot.")
        return

    for col, title, xlabel in [
        ("output_count", "CoinJoin Output Count Distribution", "# Outputs"),
        ("input_count", "CoinJoin Input Count Distribution", "# Inputs"),
    ]:
        plt.figure(figsize=(8, 4))
        df[col].hist(bins=range(2, int(df[col].max()) + 2))
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel("# CoinJoins")
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, f"cj_{col}.png"))
        plt.close()

    plt.figure(figsize=(8, 4))
    df["amounts"].explode().astype(float).hist(bins=30)
    plt.title("CoinJoin Output Amounts Distribution")
    plt.xlabel("Output Amount (BTC)")
    plt.ylabel("# Outputs")
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "cj_output_amounts.png"))
    plt.close()

