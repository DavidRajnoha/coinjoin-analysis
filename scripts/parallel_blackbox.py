#!/usr/bin/env python3
"""
Solve the blackbox CoinJoin Sudoku of one run directory in parallel chunks, then merge.

Each transaction is solved independently (input values are stored on the inputs of real-data
block files), so the block files can be split into chunks solved by separate processes. The
merged pickles are written into the run's analysis cache, so a final

    python joinmarket/unified_analysis.py RUN --analysis blackbox

loads them and builds chains and the report over the whole run, as a single-process run would.

Usage:
  scripts/parallel_blackbox.py split RUN N      # create RUN/_chunks/chunk_XX with symlinked blocks
  scripts/parallel_blackbox.py merge RUN        # merge chunk caches into RUN/analysis_cache

Chunks are assigned round-robin by block height so slow (large) transactions spread evenly.
Solve each chunk with:
  python joinmarket/unified_analysis.py RUN/_chunks/chunk_XX --analysis blackbox --collect-stats
"""
import glob
import os
import pickle
import re
import sys

# The cached coinjoin objects are instances of joinmarket.common.coinjoin_model.CoinJoin.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def split(run, n):
    blocks = sorted(glob.glob(os.path.join(run, 'btc-node', 'block_*.json')),
                    key=lambda p: int(re.search(r'block_(\d+)\.json$', p).group(1)))
    for k in range(n):
        d = os.path.join(run, '_chunks', f'chunk_{k:02d}', 'btc-node')
        os.makedirs(d, exist_ok=True)
        for p in blocks[k::n]:
            link = os.path.join(d, os.path.basename(p))
            if not os.path.exists(link):
                os.symlink(os.path.abspath(p), link)
    print(f'split {len(blocks)} block files into {n} chunks under {run}/_chunks')


def merge(run):
    results, objs = [], []
    chunks = sorted(glob.glob(os.path.join(run, '_chunks', 'chunk_*')))
    for c in chunks:
        cache = os.path.join(c, 'analysis_cache')
        with open(os.path.join(cache, 'blackbox_results.pkl'), 'rb') as fh:
            results.extend(pickle.load(fh))
        with open(os.path.join(cache, 'blackbox_cj_objs.pkl'), 'rb') as fh:
            objs.extend(pickle.load(fh))
    height = {o.txid: o.block_height for o in objs}
    objs.sort(key=lambda o: (o.block_height, o.txid))
    results.sort(key=lambda r: (height.get(r['txid'], 0), r['txid']))
    out = os.path.join(run, 'analysis_cache')
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'blackbox_results.pkl'), 'wb') as fh:
        pickle.dump(results, fh)
    with open(os.path.join(out, 'blackbox_cj_objs.pkl'), 'wb') as fh:
        pickle.dump(objs, fh)
    print(f'merged {len(chunks)} chunks: {len(objs)} coinjoin objects, {len(results)} solved results -> {out}')


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'split':
        split(sys.argv[2], int(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'merge':
        merge(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
