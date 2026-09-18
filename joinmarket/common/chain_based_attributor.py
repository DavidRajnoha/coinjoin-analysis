from typing import Optional, Any, Dict, List, Tuple

from joinmarket.common.analysis_config import AnalysisConfig, DEFAULT_CONFIG
from joinmarket.common.coinjoin_model import TxOutput
from joinmarket.common.output_attribution import OutputAttribution


class ChainBasedAttributor:
    """Traces identities through CoinJoin chains."""

    def __init__(self, config: AnalysisConfig = DEFAULT_CONFIG):
        self.config = config
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
        Assumption: The links in a chain all go through tumbler connections (taker or zero-fee maker).
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
        Assumption: The links in a chain all go through tumbler connections (taker or zero-fee maker).
        """
        # Legacy mode keeps the original behaviour of considering every child participant.
        links = [(child_participant, tx_in)
                 for child_participant in self.current_child_cj.participants
                 if child_participant.is_tumbler_link or not self.config.strict_links
                 for tx_in in child_participant.inputs
                 if tx_in.txid == self.current_parent_cj.txid]

        # Change outputs are anchored to a specific parent participant, so resolve them first;
        # the identity they establish then disambiguates cj-output links.
        change_vouts = {p.change_output.n for p in self.current_parent_cj.participants if p.change_output}
        links.sort(key=lambda link: link[1].vout not in change_vouts)

        for child_participant, tx_in in links:
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
        We have: Identified a particular coinjoin output that belongs to a tumbler participant in the parent coinjoin based on the chain.
        We want: Assign that output to the "emptied" cj_output of the matching tumbler participant.
        (We currently strip the cj_outputs of the participants and reassign them here. We can not strip the roles, as
        those are already correctly assigned with the inputs).
        """
        participant = self._resolve_parent_tumbler()
        if participant is None:
            return
        participant.cj_output = cj_out_taker

        # Identity is passed from the parent to the child if connection found
        participant.client = participant.client or f"tumbler_{self.current_parent_cj.block_height}_{self.current_parent_cj.txid[:4]}"

        self.current_child_participant.client = (
            self.current_child_participant.client) if self.current_child_participant.client else participant.client
        print(f"Connected {self.current_parent_cj.txid[:8]} cj_out {cj_out_taker.n} to "
              f"child tx {self.current_child_tx_in.txid[:8]} input {self.current_child_tx_in.vout}")

    def _resolve_parent_tumbler(self):
        """
        A parent may hold several tumbler participants (one taker plus zero-fee makers of other tumblers).
        Pick the one that still lacks a cj_output, preferring an identity match with the child participant.
        """
        if not self.config.strict_links:
            return next((p for p in self.current_parent_cj.participants if p.role == 'taker'), None)
        candidates = [p for p in self.current_parent_cj.participants
                      if p.is_tumbler_link and p.cj_output is None]
        child_client = self.current_child_participant.client
        if child_client:
            matched = [p for p in candidates if p.client == child_client]
            if len(matched) == 1:
                return matched[0]
            candidates = [p for p in candidates if not p.client] or candidates
        if len(candidates) == 1:
            return candidates[0]
        print(f"Ambiguous tumbler for {self.current_parent_cj.txid[:8]} cj_out {self.current_child_tx_in.vout} "
              f"spent by child {self.current_child_cj.txid[:8]}: {len(candidates)} candidates, skipping")
        return None

    def _attribute_change_output(self):
        ch_out_taker = self._get_matching_change_output()
        if not ch_out_taker:
            return

        for participant in self.current_parent_cj.participants:
            if not participant.is_tumbler_link:
                continue
            # Legacy mode propagated the taker's identity regardless of who owned the change output.
            if self.config.strict_links and participant.change_output is not ch_out_taker:
                continue

            # Only propagate existing identity; do NOT synthesize one
            if participant.client and not self.current_child_participant.client:
                self.current_child_participant.client = participant.client
            elif self.config.strict_links and self.current_child_participant.client and not participant.client:
                participant.client = self.current_child_participant.client
            print(f"Connected {self.current_parent_cj.txid[:8]} change_out {ch_out_taker.n} to "
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