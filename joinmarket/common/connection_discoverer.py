"""
Connection Discovery for CoinJoin Chain Analysis.

Discovers additional parent→child connections missed during initial chain building
by analyzing attributed outputs and applying elimination heuristics.
"""
from typing import List, Tuple, Set, Dict, Any


class ConnectionDiscoverer:
    """Discovers additional connections between CoinJoin transactions."""

    def discover(self, all_coinjoins: List[Any], existing_chains: List[Any],
                 strategies: List[str] = None) -> List[Tuple[str, str]]:
        """
        Discover new connections using specified strategies.

        Args:
            all_coinjoins: All CoinJoin objects (not just those in chains)
            existing_chains: Currently identified chains
            strategies: List of strategy names to apply (default: ['change_output'])

        Returns:
            List of (parent_txid, child_txid) tuples for new connections
        """
        if strategies is None:
            strategies = ['change_output']

        # Build set of existing connections to avoid duplicates
        existing_connections = self._get_existing_connections(existing_chains)

        new_connections = []

        if 'change_output' in strategies:
            change_connections = self.discover_change_output_connections(
                all_coinjoins, existing_connections
            )
            new_connections.extend(change_connections)

        return new_connections

    def attribute_by_maker_elimination(self, all_coinjoins: List[Any]) -> int:
        """
        Case 2: Attribute taker outputs via maker elimination.

        Logic:
        - For each parent CoinJoin, examine which outputs are spent by makers in children
        - If all outputs except one are spent by participants with role='maker'
        - Then the remaining output must belong to the taker
        - Assign it to the taker participant (only if cj_output is None)

        This catches cases where:
        - Chain connections exist but taker output wasn't correctly attributed
        - We can deduce taker output by elimination (all others are makers)

        Args:
            all_coinjoins: All CoinJoin objects

        Returns:
            Number of attributions made

        Note: Future enhancement could use probabilistic attribution when we have
        partial information (e.g., identified 5 of 8 outputs as makers, remaining 3
        could have probability distribution).
        """
        attributions_made = 0
        debug_stats = {
            'examined': 0,
            'has_outputs': 0,
            'all_but_one': 0,
            'no_taker': 0,
            'already_assigned': 0,
        }

        # Build mapping of txid -> coinjoin for quick lookup
        txid_to_cj = {cj.txid: cj for cj in all_coinjoins}

        # For each potential parent CoinJoin
        for parent_cj in all_coinjoins:
            debug_stats['examined'] += 1

            # Get all CoinJoin outputs for this transaction
            if not hasattr(parent_cj, 'cj_outs') or not parent_cj.cj_outs:
                continue

            cj_outputs = list(parent_cj.cj_outs)
            if len(cj_outputs) == 0:
                continue

            debug_stats['has_outputs'] += 1

            # Track which outputs are identified as belonging to makers
            maker_outputs = set()
            output_spenders = {}  # Track who spends each output

            # Check each child transaction to see if it spends outputs from parent
            for child_cj in all_coinjoins:
                if child_cj.txid == parent_cj.txid:
                    continue

                # Check each participant in child
                for child_participant in child_cj.participants:
                    # Check if this participant spends from parent's CoinJoin outputs
                    for tx_in in child_participant.inputs:
                        if tx_in.txid != parent_cj.txid:
                            continue

                        # Find which output this input references
                        for cj_out in cj_outputs:
                            if cj_out.n == tx_in.vout:
                                # Track who spends this output
                                if cj_out.n not in output_spenders:
                                    output_spenders[cj_out.n] = []
                                output_spenders[cj_out.n].append(child_participant.role)

                                # Add to maker outputs if role is maker
                                if child_participant.role == 'maker':
                                    maker_outputs.add(cj_out)
                                break

            # Debug: show progress for transactions with some maker identification
            if len(maker_outputs) > 0:
                spent_count = len(output_spenders)
                unspent_count = len(cj_outputs) - spent_count
                role_summary = {}
                for roles in output_spenders.values():
                    for role in roles:
                        role_summary[role] = role_summary.get(role, 0) + 1

                print(f"    TX {parent_cj.txid[:8]}: {len(maker_outputs)}/{len(cj_outputs)} outputs as makers, "
                      f"{spent_count} spent, {unspent_count} unspent, "
                      f"roles: {role_summary}")

            # Check if we have all-but-one identification
            if len(maker_outputs) == len(cj_outputs) - 1:
                debug_stats['all_but_one'] += 1

                # Find the remaining output (the taker's output)
                remaining_outputs = [out for out in cj_outputs if out not in maker_outputs]
                if len(remaining_outputs) != 1:
                    continue

                taker_output = remaining_outputs[0]

                # Find the taker participant in parent
                taker_found = False
                for participant in parent_cj.participants:
                    if participant.role == 'taker':
                        taker_found = True
                        if participant.cj_output is None:
                            # Assign the identified taker output
                            participant.cj_output = taker_output
                            attributions_made += 1
                            print(f"  ✓ Maker elimination: {parent_cj.txid[:8]} "
                                  f"output {taker_output.n} → taker "
                                  f"({len(maker_outputs)} makers identified)")
                        else:
                            debug_stats['already_assigned'] += 1
                            print(f"    TX {parent_cj.txid[:8]}: taker output already assigned (has output {participant.cj_output.n})")
                        break

                if not taker_found:
                    debug_stats['no_taker'] += 1
                    print(f"    TX {parent_cj.txid[:8]}: all-but-one met, but no taker participant found")

        # Print summary statistics
        print(f"    Debug stats: examined={debug_stats['examined']}, "
              f"has_outputs={debug_stats['has_outputs']}, "
              f"all_but_one={debug_stats['all_but_one']}, "
              f"already_assigned={debug_stats['already_assigned']}, "
              f"no_taker={debug_stats['no_taker']}")

        return attributions_made

    def _get_existing_connections(self, chains: List[Any]) -> Set[Tuple[str, str]]:
        """Extract all existing connections from chains."""
        existing = set()
        for chain in chains:
            for parent_txid, child_txids in chain.connections.items():
                for child_txid in child_txids:
                    existing.add((parent_txid, child_txid))
        return existing

    def discover_change_output_connections(self, all_coinjoins: List[Any],
                                          existing_connections: Set[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """
        Case 1: Discover connections via attributed change outputs.

        Logic:
        - For each CoinJoin A with attributed change output (has client ID)
        - Find CoinJoins B that spend that change output
        - If A's change owner has a client ID, this validates the connection
        - Return (A.txid, B.txid) pairs not already in existing_connections

        This catches cases where:
        - Initial chain building missed the connection (input not labeled as taker)
        - But we know the change output owner from attribution

        Args:
            all_coinjoins: All CoinJoin objects
            existing_connections: Set of existing (parent, child) pairs

        Returns:
            List of (parent_txid, child_txid) tuples for new connections
        """
        new_connections = []

        # Build mapping of txid -> coinjoin for quick lookup
        txid_to_cj = {cj.txid: cj for cj in all_coinjoins}

        # For each potential parent CoinJoin
        for parent_cj in all_coinjoins:
            # Find participants with attributed change outputs
            for parent_participant in parent_cj.participants:
                # Skip if no change output or no attribution
                if not parent_participant.change_output:
                    continue
                if not parent_participant.client:
                    continue

                change_out = parent_participant.change_output

                # Look for CoinJoins that spend this change output
                for child_cj in all_coinjoins:
                    # Skip same transaction
                    if child_cj.txid == parent_cj.txid:
                        continue

                    # Skip if already connected
                    if (parent_cj.txid, child_cj.txid) in existing_connections:
                        continue

                    # Check if any participant in child spends from this change output
                    connection_found = False
                    for child_participant in child_cj.participants:
                        for tx_in in child_participant.inputs:
                            if (tx_in.txid == parent_cj.txid and
                                tx_in.vout == change_out.n):
                                # Found a connection via change output!
                                connection_found = True
                                print(f"  Discovery: {parent_cj.txid[:8]} -> {child_cj.txid[:8]} "
                                      f"via change_out {change_out.n} "
                                      f"(client={parent_participant.client})")
                                break
                        if connection_found:
                            break

                    if connection_found:
                        new_connections.append((parent_cj.txid, child_cj.txid))

        return new_connections
