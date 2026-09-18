import numpy as np

from joinmarket.common.analysis_config import AnalysisConfig, DEFAULT_CONFIG
from joinmarket.common.coinjoin_model import CoinJoinParticipant, TxOutput, role_from_delta, relabel_roles
from joinmarket.blackbox.coinjoin_sudoku.joinmarket_sudoku import build_compatibility_matrix

MAKER_SESSIONS = AnalysisConfig(maker_sessions=True)


def test_legacy_config_keeps_two_way_split():
    assert role_from_delta(-1, DEFAULT_CONFIG) == 'taker'
    assert role_from_delta(0, DEFAULT_CONFIG) == 'maker'
    assert role_from_delta(1, DEFAULT_CONFIG) == 'maker'


def test_maker_sessions_config_three_way_split():
    assert role_from_delta(-1, MAKER_SESSIONS) == 'taker'
    assert role_from_delta(0, MAKER_SESSIONS) == 'zero_fee_maker'
    assert role_from_delta(1, MAKER_SESSIONS) == 'maker'
    assert role_from_delta(5, AnalysisConfig(maker_sessions=True, zero_fee_tolerance=5)) == 'zero_fee_maker'


def test_relabel_roles_switches_modes_on_same_participants():
    parts = [CoinJoinParticipant(inputs=[], cj_output=TxOutput(0, 1), role='maker', delta=d) for d in (-5, 0, 3)]
    relabel_roles(parts, MAKER_SESSIONS)
    assert [p.role for p in parts] == ['taker', 'zero_fee_maker', 'maker']
    assert [p.is_tumbler_link for p in parts] == [True, True, False]
    relabel_roles(parts, DEFAULT_CONFIG)
    assert [p.role for p in parts] == ['taker', 'maker', 'maker']
    assert [p.is_tumbler_link for p in parts] == [True, False, False]


def test_zero_delta_subset_is_never_a_taker_candidate():
    cj_outs = [{'n': 0, 'value': 100}, {'n': 1, 'value': 100}]
    ch_outs = [{'n': 2, 'value': 10}, {'n': 3, 'value': 20}]
    # subset sums: 110 (delta 0 vs change 10), 130 (delta -10 vs change 20)
    valid_indices = np.array([1, 2])
    valid_sums = np.array([110, 130])
    indicators = np.array([[1, 0], [0, 1]])
    compat, compat_taker = build_compatibility_matrix(
        valid_indices, valid_sums, indicators, ch_outs, cj_outs, maker_gain_max=50)
    assert 0 in compat[1]['compatible_changes']
    assert compat_taker[1]['compatible_changes'] == []
    assert 1 in compat_taker[2]['compatible_changes']
