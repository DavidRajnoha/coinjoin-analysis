from __future__ import annotations

from decimal import Decimal, getcontext

# ─────────────────────────────────────────────────────────────────────────────
# Decimal / denomination setup
# ─────────────────────────────────────────────────────────────────────────────
getcontext().prec = 30                        # plenty for 64‑bit ints
SAT_MULT = Decimal('100000000')               # BTC → satoshi
SAT      = Decimal('1')                       # one satoshi (after ×100 M)

# ─────────────────────────────────────────────────────────────────────────────
# Sudoku decomposition helpers
# ─────────────────────────────────────────────────────────────────────────────

def to_sat(value):
    return (Decimal(str(value)) * SAT_MULT).quantize(SAT)

def vin_value(vin, tx_map):
    """Get the value of a transaction input.

    First checks if the value is directly available in the vin (non-standard but useful
    when previous transactions are not in tx_map, e.g., for real blockchain data).
    If not available, looks up the previous transaction.
    """
    # Check if value is directly available (non-standard field added for real blockchain data)
    if 'value' in vin:
        return to_sat(vin['value'])

    # Fall back to looking up the previous transaction
    if vin['txid'] not in tx_map:
        raise KeyError(f"Previous transaction {vin['txid']} not found in tx_map. "
                      f"For real blockchain data, ensure the transformation script includes "
                      f"'value' field in vin entries.")

    prev = tx_map[vin['txid']]['tx']
    return to_sat(next(o['value'] for o in prev['vout'] if o['n'] == vin['vout']))

def prepare_inputs_outputs(tx, tx_map):
    inputs = [{'vin': v, 'value': vin_value(v, tx_map)} for v in tx['vin']]
    outputs = [{'n': o['n'], 'value': to_sat(o['value'])} for o in tx['vout']]
    return inputs, outputs

def classify_outputs(outputs):
    # CoinJoin value is the most common output value
    cj_val = max({o['value'] for o in outputs}, key=lambda x: sum(1 for o in outputs if o['value'] == x))
    cj_outs = [o for o in outputs if o['value'] == cj_val]
    ch_outs = [o for o in outputs if o['value'] != cj_val]
    return cj_val, cj_outs, ch_outs

def is_valid_cj_structure(cj_outs, ch_outs):
    N = len(cj_outs)
    return N != 0 and len(ch_outs) in {N, N - 1}

def calculate_miner_fee(inputs, outputs):
    return sum(i['value'] for i in inputs) - sum(o['value'] for o in outputs)


