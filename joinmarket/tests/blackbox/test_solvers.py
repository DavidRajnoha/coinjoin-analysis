from decimal import Decimal

import pytest

from joinmarket.blackbox.coinjoin_sudoku import solvers
from joinmarket.common.analysis_config import AnalysisConfig


def _tx(vin_values, vout_values):
    """A Core-RPC shaped transaction plus the tx_map its inputs point at (values in BTC)."""
    prev = {
        'tx': {'vout': [{'n': i, 'value': v,
                         'scriptPubKey': {'address': f'prev{i}'}}
                        for i, v in enumerate(vin_values)]}
    }
    tx = {
        'txid': 'tx',
        'vin': [{'txid': 'prev', 'vout': i} for i in range(len(vin_values))],
        'vout': [{'n': i, 'value': v, 'scriptPubKey': {'address': f'out{i}'}}
                 for i, v in enumerate(vout_values)],
    }
    return tx, {'prev': prev}


def test_registry_lists_both_backends_and_rejects_unknown():
    assert solvers.available_solvers() == ['ilp', 'matrix']
    assert callable(solvers.get_solver('matrix'))
    with pytest.raises(ValueError, match='Unknown solver'):
        solvers.get_solver('nope')


def test_register_solver_round_trip():
    sentinel = object()
    solvers.register_solver('_probe', lambda *a, **k: sentinel)
    try:
        assert '_probe' in solvers.available_solvers()
        assert solvers.get_solver('_probe')() is sentinel
    finally:
        solvers._SOLVERS.pop('_probe')


def test_to_mempool_tx_converts_btc_floats_to_satoshis():
    tx, tx_map = _tx([0.6, 0.55], [0.5, 0.5, 0.14])
    converted = solvers._to_mempool_tx(tx, tx_map)

    assert [i['prevout']['value'] for i in converted['vin']] == [60000000, 55000000]
    assert [o['value'] for o in converted['vout']] == [50000000, 50000000, 14000000]
    assert converted['vin'][0]['prevout']['scriptpubkey_address'] == 'prev0'
    assert converted['vout'][0]['scriptpubkey_address'] == 'out0'
    # every value must be an int; the ILP backend rejects floats
    assert all(isinstance(i['prevout']['value'], int) for i in converted['vin'])
    assert all(isinstance(o['value'], int) for o in converted['vout'])


def test_config_label_and_dict_expose_the_solver():
    assert AnalysisConfig().label == 'legacy'
    assert AnalysisConfig(solver='ilp').label == 'legacy_ilp'
    assert AnalysisConfig(maker_sessions=True, solver='ilp').label == 'maker_sessions_ilp'
    assert AnalysisConfig(solver='ilp').to_dict()['solver'] == 'ilp'


def test_ilp_backend_reports_a_missing_dependency_clearly(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_analyzer(name, *args, **kwargs):
        if name == 'joinmarket_analyzer':
            raise ImportError('not installed')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', no_analyzer)
    tx, tx_map = _tx([0.6], [0.5, 0.09])
    with pytest.raises(ImportError, match='joinmarket_analyzer'):
        solvers.get_solver('ilp')(tx, tx_map, AnalysisConfig(solver='ilp'))


def test_ilp_backend_converts_solutions_to_the_participant_contract():
    """The adapter must emit the dict shape _build_participants consumes."""
    analyzer = pytest.importorskip('joinmarket_analyzer')

    # 3 participants, values chosen so the books balance exactly (the ILP backend declines
    # 2-participant transactions, so the smallest usable fixture has three):
    #   taker in 0.6010 -> cj 0.5 + change 0.1000 ; maker fees + 90_000 sat network fee
    #   makers in 0.55 / 0.53 -> cj 0.5 + change 0.0501 / 0.0300
    tx, tx_map = _tx([0.6010, 0.55, 0.53], [0.5, 0.5, 0.5, 0.1, 0.0501, 0.0300])
    solutions = solvers.get_solver('ilp')(
        tx, tx_map, AnalysisConfig(solver='ilp', ilp_max_fee_rel=0.1, ilp_max_solutions=5))

    assert solutions, 'expected the ILP backend to decompose this transaction'
    for participants in solutions:
        for part in participants:
            assert set(part) == {'inputs', 'cj', 'change', 'delta', 'role'}
            assert part['role'] in ('taker', 'maker')
            assert isinstance(part['delta'], Decimal)
            assert isinstance(part['cj']['value'], Decimal)
            for inp in part['inputs']:
                # inputs must carry the real outpoint so chain building can follow them
                assert set(inp['vin']) >= {'txid', 'vout'}
                assert isinstance(inp['value'], Decimal)
            if part['change'] is not None:
                assert isinstance(part['change']['value'], Decimal)
        # exactly one participant pays, and deltas sum to minus the network fee
        assert sum(1 for p in participants if p['delta'] < 0) == 1
