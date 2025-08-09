from typing import Optional

from joinmarket.common.coinjoin_model import TxOutput
from joinmarket.common.output_attribution import OutputAttribution


class ChainBasedAttributor:
    """Traces identities through CoinJoin chains."""

    def attribute_chain(self, chain):
        """Main entry point - process all connections in a chain."""
        print(f"\nProcessing chain: {chain.id}")

        for parent_txid, child_txids in chain.connections.items():
            parent_cj = self._get_coinjoin(chain, parent_txid)
            if not parent_cj:
                continue
            parent_cj.prepare_for_attribution()

            for child_txid in child_txids:
                child_cj = self._get_coinjoin(chain, child_txid)
                if not child_cj:
                    continue

                print(f"  Connection: {parent_txid[:8]} -> {child_txid[:8]}")
                self._process_connection(parent_cj, child_cj, chain.analysis_type)

    def _process_connection(self, parent_cj, child_cj, analysis_type):
        """Process a single parent->child connection."""
        # Find takers in child transaction
        for child_participant in child_cj.participants:
            if child_participant.role != 'taker':
                continue

            # Find what this taker spent from parent
            for tx_in in child_participant.inputs:
                if tx_in.txid == parent_cj.txid:
                    # This taker spent from parent - attribute that output
                    self._attribute_parent_output(
                        parent_cj, tx_in, child_participant
                    )
                if tx_in.txid == parent_cj.txid:
                    self._attribute_change_output(
                        parent_cj, tx_in, child_participant
                    )
        pass

    def _attribute_parent_output(self, parent_cj, tx_in, child_participant):
        """Find and attribute the specific output in parent CJ."""
        # TODO: Find output by index in parent_cj
        # This depends on your data structure
        cj_out_taker: Optional[TxOutput] = None

        for cj_out in parent_cj.cj_outs:
            if cj_out.n == tx_in.vout:
                cj_out_taker = cj_out
                cj_out_taker.confidence = tx_in.confidence if tx_in.confidence else 1

        if not cj_out_taker:
            return

        for participant in parent_cj.participants:
            if participant.role == 'taker':
                participant.cj_output = cj_out_taker

                # Identity is passed from the parent to the child if connection found
                participant.client = participant.client or f"taker_{parent_cj.block_height}_{parent_cj.txid[:4]}"

                child_participant.client = child_participant.client if child_participant.client else participant.client
                print(f"Connected {parent_cj.txid[:8]} cj_out {cj_out_taker.n} to "
                      f"child tx {tx_in.txid[:8]} input {tx_in.vout}")

    def _attribute_change_output(self, parent_cj, tx_in, child_participant):
        ch_out_taker: Optional[TxOutput] = None

        ch_outs = {participant.change_output for participant in parent_cj.participants}

        for ch_out in ch_outs:
            if ch_out and ch_out.n == tx_in.vout:
                ch_out_taker = ch_out

        if not ch_out_taker:
            return

        for participant in parent_cj.participants:
            # Identity is passed from the parent to the child if connection found
            participant.client = participant.client or f"taker_{parent_cj.block_height}_{parent_cj.txid[:4]}"

            child_participant.client = child_participant.client if child_participant.client else participant.client
            print(f"Connected {parent_cj.txid[:8]} cj_out {ch_out_taker.n} to "
                  f"child tx {tx_in.txid[:8]} input {tx_in.vout}")

    def _get_coinjoin(self, chain, txid):
        """Helper to get CoinJoin from chain."""
        node = chain._nodes_by_txid.get(txid)
        return node.get_coinjoin() if node else None