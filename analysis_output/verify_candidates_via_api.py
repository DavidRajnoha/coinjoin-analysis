"""
Structurally verify the suspicious unlabeled-coinjoin candidates against a public API.

The corpus flags an external transaction as a candidate when it absorbs outputs from
>=3 distinct labeled coinjoins. That is a convergence heuristic, not proof: ordinary
consolidation produces the same pattern. This script fetches each candidate's real
input/output structure and tests it against the JoinMarket shape:

    n equal-valued outputs, n or n-1 change outputs, and at least n inputs

Two comparison groups are used, and they answer different questions:

  * CONTROLS here = external txs fed by exactly ONE corpus coinjoin. These are NOT a
    base rate: every one is a direct descendant of known JoinMarket activity, which is
    exactly where unlabeled coinjoins would concentrate. Measured at 51% conforming,
    which is best read as evidence that the labeling gap extends beyond the >=3-source
    pool - not as a false-positive floor.

  * TRUE BASE RATE = random transactions sampled from the chain at large, era-matched
    to the corpus. See analysis_output/random_chain_baseline.py. Measured 0/100
    conforming (no random tx had even 3 equal-valued outputs), so the structural rule
    essentially never fires on ordinary traffic.

Read the candidate result against the random baseline (0%), not against the 51%.

WHAT THE 51% DOES AND DOES NOT IMPLY
------------------------------------
It does NOT raise the remix-rate estimate. Relabeling those transactions as coinjoins
would not merely move outputs from 'outside' into 'remixed': each newly labeled
coinjoin brings its OWN inputs to attribute and its own outputs into the denominator.
The numerator and denominator grow together, so following the chain outward expands
the set without converging on a higher rate. The ~61% upper bound from
mainnet_remix_analysis.py stands.

What it shows instead is that the corpus is missing JoinMarket transactions
ITERATIVELY, at every depth - not as a single missing slice at the >=3-source
frontier. That filter surfaced one layer; the single-source pool reveals another
behind it. This compounds: every undetected coinjoin also removes its successors from
the labeled set, which is why per-year coverage gaps (e.g. the 2022-23 drop to
13-14%) are better explained as detection loss than as behavioural change.

Run:  .venv/bin/python analysis_output/verify_candidates_via_api.py [--n 100] [--seed 0]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

CORPUS = 'data/joinmarket/real-data/coinjoin_tx_info.json'
CAND = 'analysis_output/suspicious_unlabeled_cj_candidates.txt'
OUT_DIR = 'analysis_output'
SLEEP = 0.6          # polite pacing; these APIs are keyless and unmetered but shared
MAX_RETRIES = 4

# Keyless Esplora-style endpoints, one transaction per request. Blockchair was tried
# first but returns HTTP 430 (blocked/quota) from this network regardless of backoff.
ENDPOINTS = [
    'https://mempool.space/api/tx/{txid}',
    'https://blockstream.info/api/tx/{txid}',
]


def evaluate_tx(inputs_count: int, output_values: list) -> tuple[bool, dict]:
    """Test a transaction against the JoinMarket output shape.

    Requires n equal-valued outputs with n or n-1 change outputs and >= n inputs.

    Two deliberate differences from the naive version:
      * n >= 3, not n >= 2. With n == 2 a plain 2-out payment (one spend, one change)
        satisfies the rule trivially, so almost everything passes and the test tells
        you nothing.
      * 'change' counts only outputs that are NOT the mix value, and each distinct
        mix-value candidate is checked largest-first so the real denomination wins
        rather than an incidental pair of equal change outputs.
    """
    counts = collections.Counter(output_values)
    best = None
    for mix_val, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n < 3 or inputs_count < n:
            continue
        change = len(output_values) - n
        if change in (n, n - 1):
            return True, {
                'status': 'CONFORMS',
                'n': n,
                'mix_value': mix_val,
                'equal_outputs': n,
                'change_outputs': change,
                'inputs': inputs_count,
                'outputs': len(output_values),
            }
        if best is None:
            best = (n, mix_val, change)
    detail = {
        'status': 'NON_CONFORMING',
        'inputs': inputs_count,
        'outputs': len(output_values),
        'largest_equal_group': best[0] if best else max(counts.values()),
        'distribution': dict(collections.Counter(counts.values())),
    }
    return False, detail


def fetch_tx(txid: str) -> dict | None:
    """Fetch one transaction, falling back across endpoints and retrying transients.

    Returns the Esplora JSON, or None if every endpoint failed.
    """
    for attempt in range(MAX_RETRIES):
        url = ENDPOINTS[attempt % len(ENDPOINTS)].format(txid=txid)
        req = urllib.request.Request(url, headers={'User-Agent': 'CJ-Research/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # genuinely unknown tx, do not retry
            time.sleep(SLEEP * (2 ** attempt))
        except Exception:
            time.sleep(SLEEP * (2 ** attempt))
    return None


def shape(tx: dict) -> tuple[int, list]:
    """Extract (input_count, output_values) from an Esplora transaction."""
    return len(tx.get('vin', [])), [o['value'] for o in tx.get('vout', [])]


def classify(txids: list, label: str) -> tuple[list, list, int]:
    """Fetch and structurally classify a group of transactions."""
    conforming, non_conforming, missing = [], [], 0
    for i, txid in enumerate(txids, 1):
        if i % 10 == 1 or i == len(txids):
            print(f"  [{label}] {i}/{len(txids)}", flush=True)
        tx = fetch_tx(txid)
        if tx is None:
            missing += 1
            time.sleep(SLEEP)
            continue
        inputs_count, values = shape(tx)
        ok, detail = evaluate_tx(inputs_count, values)
        detail['txid'] = txid
        (conforming if ok else non_conforming).append(detail)
        time.sleep(SLEEP)
    return conforming, non_conforming, missing


def build_control(n: int, rng: random.Random, exclude: set) -> list:
    """External txs fed by exactly ONE coinjoin - the base-rate comparison group."""
    with open(CORPUS) as fh:
        cjs = json.load(fh)['coinjoins']
    ext = collections.defaultdict(set)
    for txid, cj in cjs.items():
        for o in cj['outputs'].values():
            sb = o.get('spend_by_tx')
            if sb and sb.startswith('vin_'):
                sp = sb.split('_')[1]
                if sp not in cjs:
                    ext[sp].add(txid)
    pool = [k for k, v in ext.items() if len(v) == 1 and k not in exclude]
    return rng.sample(pool, min(n, len(pool)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=100, help='sample size per group')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--no-control', action='store_true')
    args = ap.parse_args()

    rng = random.Random(args.seed)
    with open(CAND) as fh:
        candidates = [l.strip() for l in fh if l.strip()]
    print(f"candidate pool: {len(candidates)}")

    sample = rng.sample(candidates, min(args.n, len(candidates)))
    print(f"\nFetching {len(sample)} CANDIDATES (>=3 source coinjoins)...")
    c_ok, c_bad, c_missing = classify(sample, 'cand')

    ctrl_ok = ctrl_bad = []
    ctrl_missing = 0
    control = []
    if not args.no_control:
        control = build_control(args.n, rng, set(candidates))
        print(f"\nFetching {len(control)} CONTROLS (exactly 1 source coinjoin)...")
        ctrl_ok, ctrl_bad, ctrl_missing = classify(control, 'ctrl')

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, 'candidate_structural_check.json'), 'w') as fh:
        json.dump({
            'seed': args.seed,
            'rule': 'n>=3 equal outputs, n or n-1 change, inputs>=n',
            'candidates': {'sampled': len(sample), 'fetched': len(c_ok) + len(c_bad),
                           'conforming': c_ok, 'non_conforming': c_bad},
            'controls': {'sampled': len(control), 'fetched': len(ctrl_ok) + len(ctrl_bad),
                         'conforming': ctrl_ok, 'non_conforming': ctrl_bad},
        }, fh, indent=2)

    print("\n" + "=" * 66)
    print("STRUCTURAL CHECK  (n>=3 equal outputs, n or n-1 change, inputs>=n)")
    print("=" * 66)
    for label, ok, bad, miss in [('CANDIDATES (>=3 src)', c_ok, c_bad, c_missing),
                                 ('CONTROLS   (1 src)  ', ctrl_ok, ctrl_bad, ctrl_missing)]:
        tot = len(ok) + len(bad)
        if not tot:
            continue
        print(f"  {label}: {len(ok)}/{tot} conform ({len(ok)/tot*100:.0f}%)"
              f"{f', {miss} unfetched' if miss else ''}")
    ct, cn = len(c_ok) + len(c_bad), len(ctrl_ok) + len(ctrl_bad)
    if ct and cn:
        cr, kr = len(c_ok) / ct * 100, len(ctrl_ok) / cn * 100
        print(f"\n  GAP: {cr - kr:+.0f} pp over the control base rate")
        print("  A large positive gap means the convergence heuristic really is")
        print("  selecting coinjoin-shaped transactions, not just consolidation.")
    if c_ok:
        ns = collections.Counter(d['n'] for d in c_ok)
        print(f"\n  conforming candidates by n: {dict(sorted(ns.items()))}")
    print(f"\n  wrote {OUT_DIR}/candidate_structural_check.json")


if __name__ == '__main__':
    main()
