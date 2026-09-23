"""
Measure P(single identifiable taker | all-but-one pattern) against ground truth.

THE QUESTION
------------
jm_connectivity_analysis.py finds that ~5.7% of mainnet coinjoins have exactly one
unexplained mixed output AND one unexplained input (peaking near 7% in 2017-19). The
tempting inference is that the odd output out belongs to the taker, since yield
generators remix and takers leave. If true, that pattern deanonymises the taker.

Frequency of the pattern says nothing about whether the inference is correct. What
matters is the conditional probability

    P( the unexplained output really is the taker's | all-but-one pattern )

and its complement, the false-attribution rate. Only ground truth can supply this,
which is what the whitebox emulation provides: every wallet and every UTXO is known.

WHY A DEDICATED RUN IS NEEDED
-----------------------------
Existing runs in data/joinmarket/ are unsuitable:
  * They are maker-heavy by design (e.g. 160 makers / 8 takers) to study attribution
    accuracy, so the taker population is too small for a stable conditional estimate.
  * They run ~1000 blocks, but mean maker reuse delay is ~355 blocks, so most outputs
    never get a chance to be respent and almost everything reads as "unexplained".
    That inflates the apparent signal and biases the conditional badly.

The design below fixes both: a longer horizon so remixing saturates, and a taker
population large enough that all-but-one transactions are not rare.

HOW THE ESTIMATE IS COMPUTED
----------------------------
For each emulated coinjoin we compute the same all-but-one predicate used on mainnet,
restricted to transactions in the interior of the run (see BURN_IN / COOL_DOWN below).
Then, using ground truth, we ask whether the single unexplained output actually belongs
to the taker. The four cells of the confusion matrix give precision, and comparing the
pattern's base rate to the taker's share of outputs gives the lift over guessing.

A CRITICAL CONTROL
------------------
Precision must be compared against the naive baseline: picking a uniformly random
mixed output and calling it the taker's, which succeeds with probability 1/n for an
n-output coinjoin. If the pattern's precision is not clearly above that, the signal
carries no information and the mainnet frequencies are not evidence of a leak.

This file is a DESIGN plus a ready analysis harness. `build_scenario()` emits a
scenario.json for the existing emulation environment; `evaluate()` consumes the
resulting whitebox_cj_objs.pkl and produces the estimate. The emulation run itself is
launched by the project's usual tooling.

Usage:
  # 1. emit scenario files
  .venv/bin/python analysis_output/simulate_single_taker_leak.py scenario --out-dir sim/
  # 2. run the emulation with the project's runner (long - see BLOCKS)
  # 3. evaluate ground truth
  .venv/bin/python analysis_output/simulate_single_taker_leak.py evaluate \\
        --pkl <run>/report_unified/whitebox_cj_objs.pkl
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Simulation design parameters
# ---------------------------------------------------------------------------

# Long enough that reuse saturates. Mainnet remix converges by ~90 days and whitebox
# mean reuse delay is ~355 blocks, so 1000 blocks (the current standard) is far too
# short - most outputs there are right-censored. 6000 gives ~17 reuse generations.
BLOCKS = 6000

# Edges of the run are unusable: early transactions have no history and late ones have
# no future, so both produce spurious "unexplained" outputs. Only the interior counts.
BURN_IN_BLOCKS = 800
COOL_DOWN_BLOCKS = 1200

# Population. Mainnet order books run tens of makers; the maker:taker ratio is the key
# variable, so sweep it rather than fixing one value.
MAKER_COUNTS = [20, 40, 80]
TAKER_COUNTS = [4, 8, 16]

# Tumblers are takers that chain many mixes; they produce the deepest chains and so the
# most all-but-one patterns. Kept as a separate arm to see whether the leak is specific
# to them.
TUMBLER_COUNT = 4

MAKER_UTXOS = 10
SATS = 100_000_000


def build_scenario(name: str, n_makers: int, n_takers: int, n_tumblers: int,
                   blocks: int = BLOCKS, seed: int = 0) -> Dict[str, Any]:
    """Emit a scenario.json matching the existing emulation format.

    Maker funds are drawn over a wide range so the order book has realistic depth;
    offers use a small absolute fee, matching the sw0absoffer pattern in the
    project's existing runs.
    """
    rng = random.Random(seed)
    wallets: List[Dict[str, Any]] = []

    for _ in range(n_makers):
        wallets.append({
            'funds': [rng.randint(int(0.05 * SATS), int(12 * SATS))
                      for _ in range(MAKER_UTXOS)],
            'type': 'maker',
            'offers': [{
                'txfee': 0,
                'cjfee_a': rng.choice([500, 1000, 2000, 3000]),
                'cjfee_r': 0,
                'ordertype': 'sw0absoffer',
                'minsize': 100_000,
                'maxsize': 30 * SATS,
            }],
        })

    def taker(is_tumbler: bool) -> Dict[str, Any]:
        return {
            'funds': [rng.randint(int(0.1 * SATS), int(2 * SATS)) for _ in range(3)],
            'type': 'taker',
            'tumbler_options': {
                'addrcount': 3,
                'minmakercount': 4,
                'makercountrange': [9, 1],
                # Tumblers chain more mixes, so they generate the deepest chains.
                'mixdepthcount': 8 if is_tumbler else 3,
                'mintxcount': 2,
                'txcountparams': [3, 1] if is_tumbler else [2, 1],
                'timelambda': 60,
                'stage1_timelambda_increase': 2,
                'liquiditywait': 60,
                'waittime': 20,
                'mixdepthsrc': 0,
                'restart': True,
                # Each taker needs its own schedule file, as in the existing runs.
                'schedulefile': f"TUMBLE.schedule_{uuid.uuid4().hex}",
                'mincjamount': 100_000,
                'amtmixdepths': 8 if is_tumbler else 4,
                'rounding_chance': 0.25,
                'rounding_sigfig_weights': [55, 15, 25, 65, 40],
            },
        }

    wallets.extend(taker(True) for _ in range(n_tumblers))
    wallets.extend(taker(False) for _ in range(n_takers))

    return {
        'name': name,
        'default_version': 'joinmarket',
        'rounds': 0,
        'blocks': blocks,
        'wallets': wallets,
    }


def emit_scenarios(out_dir: str, seed: int = 0) -> List[str]:
    """Write the full sweep: maker count x taker count, plus a no-tumbler control."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for n_makers in MAKER_COUNTS:
        for n_takers in TAKER_COUNTS:
            name = f"leak_m{n_makers}_t{n_takers}_tum{TUMBLER_COUNT}_b{BLOCKS}"
            path = os.path.join(out_dir, name + '.json')
            with open(path, 'w') as fh:
                json.dump(build_scenario(name, n_makers, n_takers,
                                         TUMBLER_COUNT, seed=seed), fh, indent=2)
            written.append(path)
    # Control arm: no tumblers at all, to separate the tumbler effect from the
    # ordinary-taker effect.
    name = f"leak_m40_t8_tum0_b{BLOCKS}"
    path = os.path.join(out_dir, name + '.json')
    with open(path, 'w') as fh:
        json.dump(build_scenario(name, 40, 8, 0, seed=seed), fh, indent=2)
    written.append(path)
    return written


# ---------------------------------------------------------------------------
# Ground-truth evaluation
# ---------------------------------------------------------------------------

def evaluate(coinjoins: List[Any],
             burn_in: int = BURN_IN_BLOCKS,
             cool_down: int = COOL_DOWN_BLOCKS) -> Dict[str, Any]:
    """Measure P(unexplained output is the taker's | all-but-one pattern).

    Uses the same predicate as the mainnet analysis, but resolves the answer with
    ground-truth roles instead of guessing.
    """
    if not coinjoins:
        return {}

    jm = {cj.txid for cj in coinjoins}
    lo = min(cj.block_height for cj in coinjoins) + burn_in
    hi = max(cj.block_height for cj in coinjoins) - cool_down

    # Which (txid, vout) pairs are consumed by a later coinjoin?
    spent: Set[Tuple[str, int]] = set()
    for cj in coinjoins:
        for p in cj.participants:
            for inp in p.inputs:
                spent.add((inp.txid, inp.vout))

    stats = collections.Counter()
    random_hits = 0.0
    for cj in coinjoins:
        if not (lo <= cj.block_height <= hi):
            stats['outside_window'] += 1
            continue

        # Mixed (equal-valued CJ) outputs and the participant owning each.
        owned = [(p.cj_output, p) for p in cj.participants if p.cj_output is not None]
        if len(owned) < 3:
            stats['too_small'] += 1
            continue

        unexplained = [(o, p) for o, p in owned if (cj.txid, o.n) not in spent]
        stats['total'] += 1
        # Baseline: a uniform random guess among mixed outputs is right 1/n of the time.
        random_hits += 1.0 / len(owned)

        if len(unexplained) != 1:
            continue
        stats['all_but_one'] += 1

        out, part = unexplained[0]
        if part.role == 'taker':
            stats['true_positive'] += 1
        else:
            stats['false_positive'] += 1

    n_abo = stats['all_but_one']
    precision = stats['true_positive'] / n_abo * 100 if n_abo else None
    baseline = random_hits / stats['total'] * 100 if stats['total'] else None
    return {
        'window_blocks': [lo, hi],
        'evaluated': stats['total'],
        'outside_window': stats['outside_window'],
        'too_small': stats['too_small'],
        'all_but_one': n_abo,
        'pattern_rate': stats['all_but_one'] / stats['total'] * 100 if stats['total'] else None,
        'true_positive': stats['true_positive'],
        'false_positive': stats['false_positive'],
        'precision': precision,
        'random_baseline': baseline,
        'lift': (precision - baseline) if (precision is not None and baseline is not None) else None,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('scenario', help='emit scenario.json sweep')
    s.add_argument('--out-dir', default='analysis_output/sim_scenarios')
    s.add_argument('--seed', type=int, default=0)

    e = sub.add_parser('evaluate', help='evaluate a finished run against ground truth')
    e.add_argument('--pkl', required=True, help='path to whitebox_cj_objs.pkl')
    e.add_argument('--burn-in', type=int, default=BURN_IN_BLOCKS)
    e.add_argument('--cool-down', type=int, default=COOL_DOWN_BLOCKS)

    args = ap.parse_args()

    if args.cmd == 'scenario':
        paths = emit_scenarios(args.out_dir, args.seed)
        print(f"wrote {len(paths)} scenarios to {args.out_dir}:")
        for p in paths:
            print(f"  {os.path.basename(p)}")
        print(f"\nEach runs {BLOCKS} blocks (vs the usual 1000) so remixing saturates;")
        print(f"the first {BURN_IN_BLOCKS} and last {COOL_DOWN_BLOCKS} blocks are")
        print("excluded at evaluation time because their outputs are censored by the")
        print("edges of the run rather than by participant behaviour.")
        return

    import pickle
    # The pickle references joinmarket.* classes, so the repo root must be importable
    # regardless of where this script is invoked from.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    with open(args.pkl, 'rb') as fh:
        coinjoins = pickle.load(fh)
    res = evaluate(coinjoins, args.burn_in, args.cool_down)
    if not res:
        print("no coinjoins in pickle")
        return
    print(f"evaluation window (blocks)   : {res['window_blocks'][0]}..{res['window_blocks'][1]}")
    print(f"coinjoins evaluated          : {res['evaluated']}"
          f"  (excluded: {res['outside_window']} outside window, {res['too_small']} too small)")
    print(f"all-but-one pattern           : {res['all_but_one']}"
          f" ({res['pattern_rate']:.1f}% of evaluated)" if res['pattern_rate'] is not None else "")
    if res['precision'] is None:
        print("no all-but-one transactions in window - cannot estimate precision")
        return
    print(f"  correctly the taker's output: {res['true_positive']}")
    print(f"  actually a maker's output   : {res['false_positive']}")
    print(f"\nPRECISION                     : {res['precision']:.1f}%")
    print(f"random-guess baseline (1/n)   : {res['random_baseline']:.1f}%")
    print(f"LIFT over guessing            : {res['lift']:+.1f} pp")
    print("\nIf the lift is not clearly positive, the mainnet all-but-one frequencies")
    print("are not evidence of a taker leak.")


if __name__ == '__main__':
    main()
