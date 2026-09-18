from typing import List, Optional

from joinmarket.common.coinjoin_model import (
    CoinJoin, CoinJoinParticipant, TxInput, TxOutput, ROLE_MAKER, ROLE_TAKER,
)
from joinmarket.common.maker_utxo_reuse import (
    collect_maker_output_records,
    compute_maker_utxo_reuse_metrics,
    _trend,
)


def _inp(txid: str, vout: int, value: float = 1.0) -> TxInput:
    return TxInput(txid=txid, vout=vout, value=value)


def _out(n: int, value: float = 1.0, client: Optional[str] = None) -> TxOutput:
    return TxOutput(n=n, value=value, client=client)


def _part(inputs, cj_output, role, client=None, change_output=None) -> CoinJoinParticipant:
    return CoinJoinParticipant(inputs=inputs, cj_output=cj_output, change_output=change_output,
                               role=role, client=client)


def _cj(txid: str, block_height: int, participants: List[CoinJoinParticipant]) -> CoinJoin:
    return CoinJoin(txid=txid, block_height=block_height, participants=participants,
                    tx={'txid': txid, 'vin': [], 'vout': []})


def test_empty_input():
    metrics = compute_maker_utxo_reuse_metrics([])
    assert metrics['overall']['maker_outputs'] == 0
    assert metrics['overall']['reuse_rate'] == 0.0
    assert metrics['buckets'] == []
    assert metrics['reuse_trend']['verdict'] == 'insufficient_data'


def test_no_reuse_when_outputs_never_respent():
    cj1 = _cj("tx1", 100, [
        _part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1"),
        _part([_inp("prev", 1)], _out(1), ROLE_TAKER, client="t1"),
    ])
    records = collect_maker_output_records([cj1])
    assert len(records) == 1
    assert records[0].reused is False

    metrics = compute_maker_utxo_reuse_metrics([cj1])
    assert metrics['overall']['maker_outputs'] == 1
    assert metrics['overall']['reused'] == 0
    assert metrics['overall']['reuse_rate'] == 0.0


def test_maker_output_reused_by_maker_is_remade():
    # tx1 maker output 0 is spent as a maker input of tx2.
    cj1 = _cj("tx1", 100, [
        _part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1"),
        _part([_inp("prev", 1)], _out(1), ROLE_TAKER, client="t1"),
    ])
    cj2 = _cj("tx2", 101, [
        _part([_inp("tx1", 0)], _out(0), ROLE_MAKER, client="m1"),
        _part([_inp("other", 0)], _out(1), ROLE_TAKER, client="t1"),
    ])

    records = collect_maker_output_records([cj1, cj2])
    reused = [r for r in records if r.reused]
    assert len(reused) == 1
    assert reused[0].txid == "tx1"
    assert reused[0].spent_in_txid == "tx2"
    assert reused[0].spender_role == ROLE_MAKER
    assert reused[0].remade is True
    assert reused[0].blocks_to_reuse == 1

    metrics = compute_maker_utxo_reuse_metrics([cj1, cj2])
    # 2 maker outputs total (tx1 and tx2), 1 reused.
    assert metrics['overall']['maker_outputs'] == 2
    assert metrics['overall']['reused'] == 1
    assert metrics['overall']['reuse_rate'] == 50.0
    assert metrics['overall']['remade'] == 1
    assert metrics['overall']['remade_share_of_reused'] == 100.0
    assert metrics['overall']['avg_blocks_to_reuse'] == 1.0


def test_maker_output_reused_by_taker_is_not_remade():
    cj1 = _cj("tx1", 100, [_part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1")])
    cj2 = _cj("tx2", 101, [_part([_inp("tx1", 0)], _out(0), ROLE_TAKER, client="t1")])

    records = collect_maker_output_records([cj1, cj2])
    reused = [r for r in records if r.reused]
    assert len(reused) == 1
    assert reused[0].spender_role == ROLE_TAKER
    assert reused[0].remade is False

    metrics = compute_maker_utxo_reuse_metrics([cj1, cj2])
    assert metrics['overall']['reused'] == 1
    assert metrics['overall']['remade'] == 0
    assert metrics['overall']['remade_share_of_reused'] == 0.0


def test_taker_outputs_are_not_counted():
    cj1 = _cj("tx1", 100, [_part([_inp("prev", 0)], _out(0), ROLE_TAKER, client="t1")])
    cj2 = _cj("tx2", 101, [_part([_inp("tx1", 0)], _out(0), ROLE_TAKER, client="t1")])
    assert collect_maker_output_records([cj1, cj2]) == []


def test_change_outputs_only_counted_when_requested():
    cj1 = _cj("tx1", 100, [
        _part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1", change_output=_out(1, 0.5)),
    ])
    assert len(collect_maker_output_records([cj1], include_change=False)) == 1

    with_change = collect_maker_output_records([cj1], include_change=True)
    assert len(with_change) == 2
    assert sum(1 for r in with_change if r.is_change) == 1


def test_vout_must_match_for_reuse():
    # tx2 spends tx1 vout 1, which is the taker's output - the maker output 0 is untouched.
    cj1 = _cj("tx1", 100, [
        _part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1"),
        _part([_inp("prev", 1)], _out(1), ROLE_TAKER, client="t1"),
    ])
    cj2 = _cj("tx2", 101, [_part([_inp("tx1", 1)], _out(0), ROLE_TAKER, client="t1")])

    records = collect_maker_output_records([cj1, cj2])
    assert [r.reused for r in records] == [False]


def test_censoring_excludes_trailing_outputs_from_uncensored_rate():
    # tx1's output is reused; tx2's output has had no chance to be reused.
    cj1 = _cj("tx1", 100, [_part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1")])
    cj2 = _cj("tx2", 110, [_part([_inp("tx1", 0)], _out(0), ROLE_MAKER, client="m1")])

    metrics = compute_maker_utxo_reuse_metrics([cj1, cj2], censoring_horizon_blocks=5)
    overall = metrics['overall']
    assert overall['maker_outputs'] == 2
    assert overall['uncensored_outputs'] == 1
    # Raw rate is dragged down by the censored trailing output; uncensored is not.
    assert overall['reuse_rate'] == 50.0
    assert overall['uncensored_reuse_rate'] == 100.0


def test_buckets_and_cumulative_cover_all_records():
    cjs = []
    for i in range(10):
        # Every maker output is spent by the next transaction's maker.
        inputs = [_inp(f"tx{i-1}", 0)] if i else [_inp("prev", 0)]
        cjs.append(_cj(f"tx{i}", 100 + i, [_part(inputs, _out(0), ROLE_MAKER, client="m1")]))

    metrics = compute_maker_utxo_reuse_metrics(cjs, num_buckets=5)
    assert len(metrics['buckets']) == 5
    assert sum(b['maker_outputs'] for b in metrics['buckets']) == 10
    # Cumulative is monotone in the number of outputs seen and ends at the total.
    counts = [c['maker_outputs'] for c in metrics['cumulative']]
    assert counts == sorted(counts)
    assert counts[-1] == 10
    assert metrics['cumulative'][-1]['reuse_rate'] == metrics['overall']['reuse_rate']
    # 9 of 10 outputs are respent (the last one has no successor).
    assert metrics['overall']['reused'] == 9


def test_buckets_capped_at_record_count():
    cj1 = _cj("tx1", 100, [_part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1")])
    metrics = compute_maker_utxo_reuse_metrics([cj1], num_buckets=10)
    assert len(metrics['buckets']) == 1


def test_by_client_breakdown():
    cj1 = _cj("tx1", 100, [
        _part([_inp("prev", 0)], _out(0, client="m1"), ROLE_MAKER, client="m1"),
        _part([_inp("prev", 1)], _out(1, client="m2"), ROLE_MAKER, client="m2"),
    ])
    cj2 = _cj("tx2", 101, [_part([_inp("tx1", 0)], _out(0), ROLE_MAKER, client="m1")])

    rows = {row['client']: row for row in compute_maker_utxo_reuse_metrics([cj1, cj2])['by_client']}
    assert rows['m1']['maker_outputs'] == 2
    assert rows['m1']['reused'] == 1
    assert rows['m2']['maker_outputs'] == 1
    assert rows['m2']['reused'] == 0


def test_trend_flat_series_converges():
    result = _trend([40.0, 41.0, 40.5, 40.2, 40.1])
    assert result['verdict'] == 'converging'
    assert abs(result['slope_per_bucket']) < 0.5


def test_trend_rising_series_diverges_upward():
    result = _trend([10.0, 20.0, 30.0, 40.0, 50.0])
    assert result['verdict'] == 'diverging_upward'
    assert result['slope_per_bucket'] > 0.5
    assert result['final_rate'] == 50.0


def test_trend_falling_series_diverges_downward():
    result = _trend([50.0, 40.0, 30.0, 20.0, 10.0])
    assert result['verdict'] == 'diverging_downward'
    assert result['slope_per_bucket'] < -0.5


def test_trend_needs_three_points():
    assert _trend([10.0, 20.0])['verdict'] == 'insufficient_data'


def test_reuse_by_age_empty():
    from joinmarket.common.maker_utxo_reuse import reuse_by_age
    assert reuse_by_age([]) == []


def test_reuse_by_age_denominator_excludes_unobservable_outputs():
    from joinmarket.common.maker_utxo_reuse import reuse_by_age
    # tx0 at block 100 is reused 10 blocks later; tx1 at block 195 sits 5 blocks
    # before the end of the window, so it cannot be judged at age 10.
    cj0 = _cj("tx0", 100, [_part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1")])
    cj1 = _cj("tx1", 110, [_part([_inp("tx0", 0)], _out(0), ROLE_MAKER, client="m1")])
    cj2 = _cj("tx2", 195, [_part([_inp("ext", 0)], _out(0), ROLE_MAKER, client="m1")])

    rows = {r['age_blocks']: r for r in reuse_by_age([cj0, cj1, cj2], ages_blocks=[10])}
    # tx2's output is only 5 blocks old at the end of the window, so it is not at risk.
    assert rows[10]['at_risk'] == 2
    assert rows[10]['reused_within'] == 1
    assert rows[10]['rate'] == 50.0


def test_reuse_by_age_respects_the_age_cutoff():
    from joinmarket.common.maker_utxo_reuse import reuse_by_age
    # Reuse happens 50 blocks later, so it counts at age 50 but not at age 25.
    cj0 = _cj("tx0", 100, [_part([_inp("prev", 0)], _out(0), ROLE_MAKER, client="m1")])
    cj1 = _cj("tx1", 150, [_part([_inp("tx0", 0)], _out(0), ROLE_MAKER, client="m1")])
    cj2 = _cj("tx2", 400, [_part([_inp("ext", 0)], _out(0), ROLE_MAKER, client="m1")])

    rows = {r['age_blocks']: r for r in reuse_by_age([cj0, cj1, cj2], ages_blocks=[25, 50])}
    assert rows[25]['reused_within'] == 0
    assert rows[50]['reused_within'] == 1


def test_reuse_by_age_is_monotone_on_a_reuse_chain():
    from joinmarket.common.maker_utxo_reuse import reuse_by_age
    cjs = []
    for i in range(12):
        inputs = [_inp(f"tx{i-1}", 0)] if i else [_inp("prev", 0)]
        cjs.append(_cj(f"tx{i}", 100 + i * 20, [_part(inputs, _out(0), ROLE_MAKER, client="m1")]))

    rates = [r['rate'] for r in reuse_by_age(cjs, ages_blocks=[20, 40, 80, 160])]
    assert rates == sorted(rates)
