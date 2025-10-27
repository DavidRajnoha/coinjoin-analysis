from typing import Optional, Any, Dict, List, Tuple

from joinmarket.common.coinjoin_model import TxOutput
from joinmarket.common.output_attribution import OutputAttribution


class ChainBasedAttributor:
    """Traces identities through CoinJoin chains."""

    def __init__(self):
        self.current_child_txids = None
        self.current_parent_cj = None
        self.current_child_cj = None
        self.current_child_participant = None
        self.current_child_tx_in = None
        self.chain = None

    def attribute_chain(self, chain):
        """Main entry point - process all connections in a chain."""
        print(f"\nProcessing chain: {chain.id}")
        self.chain = chain

        for parent_txid, child_txids in chain.connections.items():
            parent_cj = self._get_taker_coinjoin(chain, parent_txid)
            if not parent_cj:
                continue
            self.current_parent_cj = parent_cj
            self.current_child_txids = child_txids

            self._process_parent_cj()

    def _process_parent_cj(self):
        """
        We have: Selected parent coinjoin that we want to attribute.
        We want: Look at each of its childs and try to attribute the pair.
        Assumption: The links in a chain all through the "taker" connections
        """

        self.current_parent_cj.prepare_for_attribution()

        for child_txid in self.current_child_txids:
            child_cj = self._get_taker_coinjoin(self.chain, child_txid)
            if child_cj:
                self.current_child_cj = child_cj
                self._process_taker_connection()

    def _process_taker_connection(self):
        """
        We have: A single parent->child connection.
        We want: Find the output-input connection and process that.
        Assumption: The links in a chain all through the "taker" connections.
        """
        for child_participant in self.current_child_cj.participants:
            for tx_in in child_participant.inputs:
                if tx_in.txid == self.current_parent_cj.txid:
                    # This taker spent from parent - attribute that output
                    self.current_child_participant = child_participant
                    self.current_child_tx_in = tx_in

                    self._attribute_parent_output()
                    self._attribute_change_output()

    def _attribute_parent_output(self):
        """
        We have: Output in parent and input in child that match.
        We want: Find that output in the "deassigned" set in the parent cj and assign it to correct participant
        """
        cj_out_taker = self._get_matching_cj_out()

        if cj_out_taker:
            self._reassign_cj_out(cj_out_taker)

    def _get_matching_cj_out(self):
        cj_out_taker: Optional[TxOutput] = None
        for cj_out in self.current_parent_cj.cj_outs:
            if cj_out.n == self.current_child_tx_in.vout:
                cj_out_taker = cj_out
                cj_out_taker.confidence = self.current_child_tx_in.confidence if self.current_child_tx_in.confidence else 1
        return cj_out_taker

    def _reassign_cj_out(self, cj_out_taker):
        """
        We have: Identified a particular coinjoin output that belongs to the taker participant in the parent coinjoin based on the chain.
        We want: Assign that output to the "emptied" cj_output in the participant with the taker label.
        (We currently strip the cj_outputs of the participants and reassign them here. We can not strip the roles, as
        those are already correctly assigned with the inputs).
        """
        for participant in self.current_parent_cj.participants:
            if participant.role != 'taker':
                continue
            participant.cj_output = cj_out_taker

            # Identity is passed from the parent to the child if connection found
            participant.client = participant.client or f"taker_{self.current_parent_cj.block_height}_{self.current_parent_cj.txid[:4]}"

            self.current_child_participant.client = (
                self.current_child_participant.client) if self.current_child_participant.client else participant.client
            print(f"Connected {self.current_parent_cj.txid[:8]} cj_out {cj_out_taker.n} to "
                  f"child tx {self.current_child_tx_in.txid[:8]} input {self.current_child_tx_in.vout}")

    def _attribute_change_output(self):
        ch_out_taker = self._get_matching_change_output()
        if not ch_out_taker:
            return

        for participant in self.current_parent_cj.participants:
            if participant.role != 'taker':
                continue

            # Only propagate existing identity; do NOT synthesize one
            if getattr(participant, 'client', None) and not getattr(self.current_child_participant, 'client', None):
                self.current_child_participant.client = participant.client
            print(f"Connected {self.current_parent_cj.txid[:8]} cj_out {ch_out_taker.n} to "
                  f"child tx {self.current_child_tx_in.txid[:8]} input {self.current_child_tx_in.vout}")


    def _get_matching_change_output(self):
        ch_out_taker: Optional[TxOutput] = None
        ch_outs = {participant.change_output for participant in self.current_parent_cj.participants}

        for ch_out in ch_outs:
            if ch_out and ch_out.n == self.current_child_tx_in.vout:
                ch_out_taker = ch_out
        return ch_out_taker

    def _get_taker_coinjoin(self, chain, txid):
        """Helper to get CoinJoin from chain."""
        node = chain._nodes_by_txid.get(txid)
        return node.get_coinjoin() if node else None

    def _get_maker_coinjoin(self):
        return self.cj_objects