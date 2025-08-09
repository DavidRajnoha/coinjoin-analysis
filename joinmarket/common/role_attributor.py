from joinmarket.common.output_attribution import OutputAttribution, Role


class RoleAttributor:
    """Handles probabilistic role attribution based on behavioral patterns."""

    def __init__(self):
        # Define heuristics for role identification
        self.heuristics = {
            'output_amount_uniformity': self._check_amount_uniformity,
            'spending_timing': self._analyze_spending_timing,
            'chain_position': self._analyze_chain_position,
            'input_output_relationship': self._analyze_io_relationship
        }

    def attribute_roles_in_coinjoin(self, coinjoin, chain_context=None):
        """Attribute roles to all outputs in a CoinJoin transaction.

        Args:
            coinjoin: The CoinJoin object to analyze
            chain_context: Optional context about where this CJ sits in a chain
        """
        # First, collect what we know for certain
        known_taker_outputs = set()
        known_maker_outputs = set()

        for participant in coinjoin.participants:
            if participant.role == 'taker' and participant.cj_output:
                known_taker_outputs.add(participant.cj_output.address)
            elif participant.role == 'maker' and participant.cj_output:
                known_maker_outputs.add(participant.cj_output.address)

        # Now analyze unknown outputs
        for participant in coinjoin.participants:
            for output in participant.outputs:
                if not hasattr(output, 'attribution'):
                    output.attribution = OutputAttribution()

                # Skip if we already know the role definitively
                if output.address in known_taker_outputs:
                    output.attribution.update_role_attribution(
                        Role.TAKER, 1.0, "known_participant"
                    )
                    continue
                elif output.address in known_maker_outputs:
                    output.attribution.update_role_attribution(
                        Role.MAKER, 1.0, "known_participant"
                    )
                    continue

                # Apply heuristics to unknown outputs
                self._apply_heuristics(output, coinjoin, chain_context)

    def _apply_heuristics(self, output, coinjoin, chain_context):
        """Apply various heuristics to determine likely role."""
        role_scores = {Role.TAKER: 0.0, Role.MAKER: 0.0}

        # Amount uniformity heuristic
        # CoinJoin outputs typically have uniform amounts for privacy
        uniformity_score = self._check_amount_uniformity(output, coinjoin)
        if uniformity_score > 0.8:
            # Uniform amounts slightly favor maker role (they follow the rules)
            role_scores[Role.MAKER] += 0.3
        else:
            # Non-uniform amounts might be change outputs (often taker)
            role_scores[Role.TAKER] += 0.2

        # Future spending analysis (if available)
        if chain_context and 'future_spends' in chain_context:
            spending_score = self._analyze_spending_timing(
                output, chain_context['future_spends']
            )
            role_scores[Role.TAKER] += spending_score * 0.4
            role_scores[Role.MAKER] += (1 - spending_score) * 0.4

        # Normalize scores to probabilities
        total_score = sum(role_scores.values())
        if total_score > 0:
            best_role = max(role_scores, key=role_scores.get)
            probability = role_scores[best_role] / total_score

            output.attribution.update_role_attribution(
                best_role, probability, "heuristic_analysis"
            )

    def _check_amount_uniformity(self, output, coinjoin):
        """Check if output amount matches common CJ denominations."""
        # Find all output amounts in this CoinJoin
        amounts = [out.amount for p in coinjoin.participants
                   for out in p.outputs]

        # Count occurrences of each amount
        amount_counts = {}
        for amount in amounts:
            amount_counts[amount] = amount_counts.get(amount, 0) + 1

        # Check if this output's amount is common
        output_count = amount_counts.get(output.amount, 0)
        max_count = max(amount_counts.values())

        return output_count / max_count if max_count > 0 else 0.0