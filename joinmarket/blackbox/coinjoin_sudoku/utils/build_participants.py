from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from joinmarket.blackbox.coinjoin_sudoku.utils.decomposition_helpers import to_sat
from joinmarket.common.coinjoin_model import (
    CoinJoinParticipant, TxOutput, TxInput
)
           # BTC → satoshi


# ─────────────────────────────────────────────────────────────────────────────
# Sudoku participant helper
# ─────────────────────────────────────────────────────────────────────────────

def _build_participants(best_solution: List[Dict[str, Any]], tx: Dict[str, Any], cj_value) -> List[CoinJoinParticipant]:
    """Translate one Sudoku solution into ``CoinJoinParticipant`` objects."""
    participants: List[CoinJoinParticipant] = []
    cj_outputs = list(filter(lambda vout: to_sat(vout['value']) == cj_value, tx['vout']))

    for n, part in enumerate(best_solution):
        # —— inputs ——————————————————————————
        inputs = [
            TxInput(
                txid=vin_info['vin']['txid'],
                vout=vin_info['vin']['vout'],
                value=vin_info['value'],              # Decimal (sat)
                address=None,                         # black‑box ⇒ unknown
            )
            for vin_info in part['inputs']
        ]

        # —— outputs —————————————————————————
        cj_out = part['cj']
        cj_output = TxOutput(
            n=cj_outputs[n]['n'],
            value=cj_out['value'],                    # Decimal (sat)
            address=cj_outputs[n].get('scriptPubKey', {}).get('address'),
            is_change=False,
            confidence=1/len(best_solution)
        )

        change_output = None
        if part['change'] is not None:
            ch_out = part['change']
            change_output = TxOutput(
                n=ch_out['n'],
                value=ch_out['value'],
                confidence=1,
                address=tx['vout'][ch_out['n']].get('scriptPubKey', {}).get('address'),
                is_change=True,
            )

        participants.append(
            CoinJoinParticipant(
                inputs=inputs,
                cj_output=cj_output,
                change_output=change_output,
                role=part['role'],
                delta=part['delta'],
            )
        )
    return participants
