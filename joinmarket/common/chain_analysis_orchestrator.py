"""
Chain Analysis Orchestrator.

Coordinates iterative chain analysis: build → attribute → discover → rebuild.
Enables discovering connections missed during initial chain building by leveraging
attribution results to find additional relationships.
"""
from typing import List, Any

from joinmarket.common.coinjoin_chain import identify_coinjoin_chains, rebuild_chains_with_new_connections
from joinmarket.common.chain_based_attributor import ChainBasedAttributor
from joinmarket.common.connection_discoverer import ConnectionDiscoverer


class ChainAnalysisOrchestrator:
    """Orchestrates iterative chain analysis with connection discovery."""

    def __init__(self):
        """Initialize orchestrator with attributor and discoverer."""
        self.attributor = ChainBasedAttributor()
        self.discoverer = ConnectionDiscoverer()

    def _restore_unassigned_outputs(self, coinjoins: List[Any]):
        """
        Restore Sudoku-assigned cj_outputs for participants that weren't attributed via chains.

        This ensures all participants have cj_outputs:
        - Blockchain-validated assignments for participants with chain connections
        - Original Sudoku assignments for other participants

        Called after discovery to ensure comparison phase has all outputs assigned.

        Args:
            coinjoins: List of all CoinJoin objects to restore
        """
        for cj in coinjoins:
            if not hasattr(cj, 'cj_outs') or not cj.cj_outs:
                continue

            # Find assigned outputs
            assigned_outputs = {p.cj_output for p in cj.participants if p.cj_output}

            # Find unassigned participants
            unassigned_participants = [p for p in cj.participants if not p.cj_output]

            # Find remaining outputs
            remaining_outputs = [out for out in cj.cj_outs if out not in assigned_outputs]

            # Assign remaining outputs to unassigned participants
            for participant, output in zip(unassigned_participants, remaining_outputs):
                participant.cj_output = output

    def analyze_with_refinement(self, coinjoins: List[Any], analysis_type: str,
                                max_iterations: int = 2) -> List[Any]:
        """
        Perform iterative chain analysis with connection discovery.

        Flow:
        1. Initial chain building (identify_coinjoin_chains)
        2. Attribution pass (ChainBasedAttributor)
        3. Discovery pass (ConnectionDiscoverer)
        4. If new connections found: rebuild chains, goto step 2
        5. Return refined chains

        Args:
            coinjoins: List of CoinJoin objects to analyze
            analysis_type: 'whitebox' or 'blackbox'
            max_iterations: Maximum number of refinement iterations

        Returns:
            List of refined CoinJoinTree objects
        """
        if not coinjoins:
            return []

        print(f"\n=== Chain Analysis Orchestrator ({analysis_type}) ===")

        # Initial chain building
        print(f"Initial chain identification...")
        chains = identify_coinjoin_chains(coinjoins, analysis_type)
        print(f"  Found {len(chains)} initial chains")

        # Iterative refinement
        for iteration in range(max_iterations):
            print(f"\n--- Iteration {iteration + 1}/{max_iterations} ---")

            # Attribution pass
            print(f"Attribution pass...")
            for chain in chains:
                self.attributor.attribute_chain(chain)

            # Discovery pass
            print(f"Discovery pass...")
            new_connections = self.discoverer.discover(
                all_coinjoins=coinjoins,
                existing_chains=chains,
                strategies=['change_output']
            )

            if not new_connections:
                print(f"  No new connections discovered. Analysis complete.")
                break

            print(f"  Discovered {len(new_connections)} new connections")

            # Maker elimination pass
            print(f"Maker elimination pass...")
            attributions = self.discoverer.attribute_by_maker_elimination(coinjoins)
            if attributions > 0:
                print(f"  Made {attributions} attributions via maker elimination")
            else:
                print(f"  No maker elimination attributions made")


            # Restore unassigned outputs before rebuild
            # This ensures all participants have cj_outputs for next iteration
            self._restore_unassigned_outputs(coinjoins)

            # Rebuild chains with new connections
            print(f"Rebuilding chains with new connections...")
            chains = rebuild_chains_with_new_connections(
                coinjoins=coinjoins,
                old_chains=chains,
                new_connections=new_connections,
                analysis_type=analysis_type
            )
            print(f"  Rebuilt into {len(chains)} chains")

        # Final restoration after all iterations complete
        # Ensures comparison phase has all outputs assigned
        self._restore_unassigned_outputs(coinjoins)

        print(f"\n=== Analysis complete: {len(chains)} final chains ===\n")
        return chains
