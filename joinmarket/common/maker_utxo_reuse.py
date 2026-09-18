"""
Maker (yield generator) UTXO reuse metrics.

A yield generator earns by re-offering the coins it receives. Every maker CJ output
of a CoinJoin is therefore a candidate input for a later CoinJoin. This module measures
how often that actually happens within the analysed transaction set, and whether the
rate settles at a stable value over the course of the run or keeps drifting.

Terminology used throughout:
  * maker output   -- a cj_output (or change_output, when included) belonging to a
                      participant whose role is 'maker'
  * reused output  -- a maker output that is spent as an input of another CoinJoin in
                      the same set
  * remade output  -- a reused output whose spending participant is again a maker
                      (the yield generator re-offered the coin rather than the coin
                      being swept up by a taker)

Outputs produced near the end of the observation window have had little chance to be
respent, so raw rates are biased downwards. `censoring_horizon_blocks` marks such
outputs as censored and the uncensored rate excludes them; both are reported. By
default the horizon is derived from the observed reuse-delay distribution, because
this bias alone can make a perfectly stable reuse rate look like it is collapsing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from joinmarket.common.coinjoin_model import ROLE_MAKER

# Passing this as censoring_horizon_blocks derives the horizon from the observed data
# (see _auto_censoring_horizon). Pass an explicit int to override, or 0 to disable.
AUTO_CENSORING_HORIZON = -1

# Quantile of the observed reuse-delay distribution used for the automatic horizon:
# outputs within this many blocks of the end have not had a representative chance to
# be respent.
CENSORING_HORIZON_QUANTILE = 0.9


@dataclass
class MakerOutputRecord:
    """One maker CJ output and what became of it."""
    txid: str
    vout: int
    value: float
    block_height: int
    address: Optional[str] = None
    client: Optional[str] = None
    is_change: bool = False
    # Reuse outcome
    spent_in_txid: Optional[str] = None
    spent_in_block_height: Optional[int] = None
    spender_role: Optional[str] = None
    censored: bool = False

    @property
    def reused(self) -> bool:
        return self.spent_in_txid is not None

    @property
    def remade(self) -> bool:
        """Reused by a participant that is again a maker."""
        return self.spender_role == ROLE_MAKER

    @property
    def blocks_to_reuse(self) -> Optional[int]:
        if self.spent_in_block_height is None:
            return None
        return self.spent_in_block_height - self.block_height

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result.update({
            'reused': self.reused,
            'remade': self.remade,
            'blocks_to_reuse': self.blocks_to_reuse,
        })
        return result


def _spend_index(coinjoins: Iterable[Any]) -> Dict[Tuple[str, int], Tuple[Any, Optional[str]]]:
    """Map each (prev_txid, prev_vout) spent by a CoinJoin to (spending_cj, spender_role).

    Only inputs that carry the previous outpoint are indexed; participants without
    attributed inputs contribute nothing.
    """
    index: Dict[Tuple[str, int], Tuple[Any, Optional[str]]] = {}
    for cj in coinjoins:
        for participant in cj.participants:
            for inp in participant.inputs:
                if inp.txid is None or inp.vout is None:
                    continue
                # A later duplicate would be a double spend; keep the first seen.
                index.setdefault((inp.txid, inp.vout), (cj, participant.role))
    return index


def _maker_outputs(cj, include_change: bool):
    """Yield (output, participant) pairs for the maker outputs of a CoinJoin."""
    for participant in cj.participants:
        if participant.role != ROLE_MAKER:
            continue
        if participant.cj_output is not None:
            yield participant.cj_output, participant, False
        if include_change and participant.change_output is not None:
            yield participant.change_output, participant, True


def _auto_censoring_horizon(
    coinjoins: List[Any],
    spends: Dict[Tuple[str, int], Tuple[Any, Optional[str]]],
    include_change: bool,
) -> int:
    """Derive the right-censoring horizon from how long reuse actually takes.

    A maker output near the end of the window looks unused simply because its
    successor would fall outside the observation window - not because the yield
    generator declined to respend it. Left uncorrected this drags the late buckets
    down and makes a perfectly stable reuse rate look like it is collapsing.

    The horizon is the CENSORING_HORIZON_QUANTILE quantile of observed reuse delays:
    the age by which most reuse has already happened, so outputs younger than that
    cannot yet be judged. Returns 0 when no reuse is observed at all.
    """
    delays = []
    for cj in coinjoins:
        for output, _participant, _is_change in _maker_outputs(cj, include_change):
            spender = spends.get((cj.txid, output.n))
            if spender is not None:
                delays.append(spender[0].block_height - cj.block_height)

    if not delays:
        return 0

    delays.sort()
    idx = min(len(delays) - 1, int(CENSORING_HORIZON_QUANTILE * (len(delays) - 1)))
    return max(0, delays[idx])


def collect_maker_output_records(
    coinjoins: List[Any],
    include_change: bool = False,
    censoring_horizon_blocks: int = AUTO_CENSORING_HORIZON,
) -> List[MakerOutputRecord]:
    """Build a MakerOutputRecord for every maker output in the CoinJoin set.

    Args:
        coinjoins: CoinJoin objects to analyse (a single analysis type at a time).
        include_change: Also track maker change outputs, not just CJ outputs.
        censoring_horizon_blocks: Maker outputs produced within this many blocks of the
            last observed block are flagged as right-censored. Defaults to
            AUTO_CENSORING_HORIZON, which derives it from observed reuse delays; pass
            0 to disable censoring.

    Returns:
        Records sorted by (block_height, txid, vout).
    """
    if not coinjoins:
        return []

    spends = _spend_index(coinjoins)
    if censoring_horizon_blocks == AUTO_CENSORING_HORIZON:
        censoring_horizon_blocks = _auto_censoring_horizon(coinjoins, spends, include_change)
    last_block = max(cj.block_height for cj in coinjoins)
    censor_from = last_block - censoring_horizon_blocks

    records: List[MakerOutputRecord] = []
    for cj in coinjoins:
        for output, participant, is_change in _maker_outputs(cj, include_change):
            record = MakerOutputRecord(
                txid=cj.txid,
                vout=output.n,
                value=output.value,
                block_height=cj.block_height,
                address=output.address,
                client=output.client or participant.client,
                is_change=is_change,
                censored=cj.block_height > censor_from if censoring_horizon_blocks else False,
            )
            spender = spends.get((cj.txid, output.n))
            if spender is not None:
                spending_cj, spender_role = spender
                record.spent_in_txid = spending_cj.txid
                record.spent_in_block_height = spending_cj.block_height
                record.spender_role = spender_role
            records.append(record)

    records.sort(key=lambda r: (r.block_height, r.txid, r.vout))
    return records


def _rate(numerator: int, denominator: int) -> float:
    return (numerator / denominator * 100) if denominator else 0.0


def _summarize(records: List[MakerOutputRecord]) -> Dict[str, Any]:
    """Reuse counts and rates for a bucket of records."""
    total = len(records)
    uncensored = [r for r in records if not r.censored]
    reused = [r for r in records if r.reused]
    remade = [r for r in records if r.remade]
    delays = [r.blocks_to_reuse for r in reused if r.blocks_to_reuse is not None]
    return {
        'maker_outputs': total,
        'uncensored_outputs': len(uncensored),
        'reused': len(reused),
        'remade': len(remade),
        'reuse_rate': _rate(len(reused), total),
        'uncensored_reuse_rate': _rate(
            sum(1 for r in uncensored if r.reused), len(uncensored)),
        'remade_rate': _rate(len(remade), total),
        'uncensored_remade_rate': _rate(
            sum(1 for r in uncensored if r.remade), len(uncensored)),
        'remade_share_of_reused': _rate(len(remade), len(reused)),
        'avg_blocks_to_reuse': (sum(delays) / len(delays)) if delays else None,
        'total_value': sum(r.value for r in records),
        'reused_value': sum(r.value for r in reused),
        'value_reuse_rate': _rate_float(
            sum(r.value for r in reused), sum(r.value for r in records)),
    }


def _rate_float(numerator: float, denominator: float) -> float:
    return (numerator / denominator * 100) if denominator else 0.0


def _bucket_records(records: List[MakerOutputRecord], num_buckets: int
                    ) -> List[Tuple[int, int, List[MakerOutputRecord]]]:
    """Split records into equal-count buckets in block order.

    Equal-count (rather than equal-width) buckets keep each point statistically
    comparable when CoinJoin activity is unevenly spread over blocks.

    Returns:
        List of (start_block, end_block, records) tuples.
    """
    if not records or num_buckets < 1:
        return []

    num_buckets = min(num_buckets, len(records))
    size, remainder = divmod(len(records), num_buckets)

    buckets = []
    start = 0
    for i in range(num_buckets):
        length = size + (1 if i < remainder else 0)
        chunk = records[start:start + length]
        start += length
        if chunk:
            buckets.append((chunk[0].block_height, chunk[-1].block_height, chunk))
    return buckets


def _trend(series: List[Optional[float]], tail_fraction: float = 0.5) -> Dict[str, Any]:
    """Describe whether a rate series is settling down or still moving.

    Uses two cheap, interpretable signals rather than a model fit:
      * `slope_per_bucket` -- least-squares slope over the bucket index, in percentage
        points per bucket; the direction the rate is still travelling.
      * `tail_spread` -- max-min of the trailing `tail_fraction` of buckets; how much
        room the rate still has left to move.

    Converging means the tail has flattened (small spread) while the running rate has
    stopped drifting (small slope). With fewer than three buckets there is nothing to
    say, and the verdict is 'insufficient_data'.
    """
    values = [v for v in series if v is not None]
    n = len(values)
    if n < 3:
        return {
            'verdict': 'insufficient_data',
            'slope_per_bucket': None,
            'tail_spread': None,
            'final_rate': values[-1] if values else None,
        }

    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    denom = sum((i - mean_x) ** 2 for i in range(n))
    slope = (sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values)) / denom) if denom else 0.0

    tail_start = max(1, int(n * (1 - tail_fraction)))
    tail = values[tail_start:] or values[-1:]
    tail_spread = max(tail) - min(tail)

    # Thresholds are in percentage points; a rate moving less than half a point per
    # bucket with a tail spanning under five points is treated as settled.
    if abs(slope) < 0.5 and tail_spread < 5.0:
        verdict = 'converging'
    elif slope > 0.5:
        verdict = 'diverging_upward'
    elif slope < -0.5:
        verdict = 'diverging_downward'
    else:
        verdict = 'unstable'

    return {
        'verdict': verdict,
        'slope_per_bucket': slope,
        'tail_spread': tail_spread,
        'final_rate': values[-1],
        'mean_rate': mean_y,
    }


def compute_maker_utxo_reuse_metrics(
    coinjoins: List[Any],
    include_change: bool = False,
    num_buckets: int = 10,
    censoring_horizon_blocks: int = AUTO_CENSORING_HORIZON,
) -> Dict[str, Any]:
    """Measure how many maker (yield generator) CJ outputs are reused in later CoinJoins.

    Reports the overall reuse rate, the same rate bucketed over time (so the trajectory
    is visible), a running cumulative rate, a per-client breakdown, and a trend verdict
    stating whether the rate is converging or still drifting.

    Args:
        coinjoins: CoinJoin objects of a single analysis type.
        include_change: Also count maker change outputs.
        num_buckets: Number of equal-count time buckets for the trajectory.
        censoring_horizon_blocks: Trailing blocks whose outputs are right-censored.
            Defaults to AUTO_CENSORING_HORIZON (derived from observed reuse delays);
            pass 0 to disable. Prefer the uncensored rates and trend when judging
            convergence, since the raw series carries end-of-window bias.

    Returns:
        Dict of metrics; 'overall' is None-safe and all rates are percentages.
    """
    resolved_horizon = censoring_horizon_blocks
    if censoring_horizon_blocks == AUTO_CENSORING_HORIZON and coinjoins:
        resolved_horizon = _auto_censoring_horizon(
            coinjoins, _spend_index(coinjoins), include_change)
    elif censoring_horizon_blocks == AUTO_CENSORING_HORIZON:
        resolved_horizon = 0

    records = collect_maker_output_records(
        coinjoins, include_change, resolved_horizon)

    if not records:
        return {
            'overall': _summarize([]),
            'buckets': [],
            'cumulative': [],
            'by_client': [],
            'reuse_trend': _trend([]),
            'remade_trend': _trend([]),
            'raw_reuse_trend': _trend([]),
            'config': {
                'include_change': include_change,
                'num_buckets': num_buckets,
                'censoring_horizon_blocks': resolved_horizon,
            },
            'records': [],
        }

    raw_buckets = _bucket_records(records, num_buckets)

    buckets = []
    cumulative = []
    seen: List[MakerOutputRecord] = []
    # Running rate over all outputs seen so far - this is the series that visibly
    # settles (or does not) as the run progresses.
    for idx, (start_block, end_block, chunk) in enumerate(raw_buckets):
        buckets.append({
            'bucket': idx,
            'start_block': start_block,
            'end_block': end_block,
            **_summarize(chunk),
        })
        seen.extend(chunk)
        cumulative.append({
            'bucket': idx,
            'end_block': end_block,
            **_summarize(seen),
        })

    by_client: Dict[str, List[MakerOutputRecord]] = defaultdict(list)
    for record in records:
        if record.client:
            by_client[record.client].append(record)

    client_rows = sorted(
        ({'client': client, **_summarize(client_records)}
         for client, client_records in by_client.items()),
        key=lambda row: row['maker_outputs'],
        reverse=True,
    )

    return {
        'overall': _summarize(records),
        'buckets': buckets,
        'cumulative': cumulative,
        'by_client': client_rows,
        # Judge convergence on the uncensored series: the raw one slides downward purely
        # because late outputs have no successors left inside the window.
        'reuse_trend': _trend([b['uncensored_reuse_rate'] for b in cumulative]),
        'remade_trend': _trend([b['uncensored_remade_rate'] for b in cumulative]),
        'raw_reuse_trend': _trend([b['reuse_rate'] for b in cumulative]),
        'config': {
            'include_change': include_change,
            'num_buckets': num_buckets,
            'censoring_horizon_blocks': resolved_horizon,
        },
        'records': [r.to_dict() for r in records],
    }


def reuse_by_age(
    coinjoins: List[Any],
    ages_blocks: Optional[List[int]] = None,
    include_change: bool = False,
) -> List[Dict[str, Any]]:
    """Fraction of maker outputs reused within A blocks, per age A.

    This is the estimator to trust when judging the reuse level. Unlike a censored
    overall rate, each row has a denominator fixed by construction: only outputs that
    were actually observable for the full A blocks are at risk, so rows are comparable
    to each other and to other runs regardless of how long the run happened to be.

    The censored `reuse_rate` from compute_maker_utxo_reuse_metrics does not have this
    property - it rises monotonically as the censoring horizon grows, because each
    increase preferentially drops never-reused outputs, so it has no stable value to
    report. Prefer this curve, and read the overall rate as a lower bound.

    Args:
        coinjoins: CoinJoin objects of a single analysis type.
        ages_blocks: Ages to evaluate, in blocks. Defaults to a spread up to 800.
        include_change: Also count maker change outputs.

    Returns:
        One dict per age with 'age_blocks', 'at_risk', 'reused_within', 'rate'.
        Ages leaving nothing at risk are omitted.
    """
    if not coinjoins:
        return []
    if ages_blocks is None:
        ages_blocks = [25, 50, 100, 150, 200, 300, 400, 500, 600, 700, 800]

    records = collect_maker_output_records(coinjoins, include_change, censoring_horizon_blocks=0)
    if not records:
        return []

    last_block = max(cj.block_height for cj in coinjoins)

    rows = []
    for age in ages_blocks:
        at_risk = [r for r in records if last_block - r.block_height >= age]
        if not at_risk:
            continue
        within = sum(1 for r in at_risk
                     if r.blocks_to_reuse is not None and r.blocks_to_reuse <= age)
        rows.append({
            'age_blocks': age,
            'at_risk': len(at_risk),
            'reused_within': within,
            'rate': _rate(within, len(at_risk)),
        })
    return rows
