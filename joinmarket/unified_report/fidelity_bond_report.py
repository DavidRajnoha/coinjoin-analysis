"""
Fidelity Bond Analysis for JoinMarket CoinJoin transactions.

This module provides analysis of fidelity bond usage in JoinMarket coinjoins,
tracking which makers have fidelity bonds and their participation patterns.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict

from joinmarket.common.coinjoin_model import CoinJoin, CoinJoinParticipant


@dataclass
class MakerInTx:
    """Represents a maker's participation in a single transaction."""
    client_id: str
    has_fidelity_bond: bool
    bond_amount: Optional[int]  # satoshis
    bond_locktime: Optional[str]  # "YYYY-MM"
    delta: float  # fee earned in BTC
    bond_value: Optional[float] = None  # calculated fidelity bond value (future)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'client_id': self.client_id,
            'has_fidelity_bond': self.has_fidelity_bond,
            'bond_amount': self.bond_amount,
            'bond_amount_btc': self.bond_amount / 1e8 if self.bond_amount else None,
            'bond_locktime': self.bond_locktime,
            'delta': self.delta,
            'bond_value': self.bond_value
        }


@dataclass
class TumblerInTx:
    """Represents a tumbler's participation in a transaction (shown separately, not in FB stats)."""
    client_id: str
    delta: float  # fee paid in BTC

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'client_id': self.client_id,
            'delta': self.delta
        }


@dataclass
class TransactionFBDetail:
    """Fidelity bond details for a single transaction."""
    txid: str
    block_height: int
    timestamp: Optional[str] = None
    makers: List[MakerInTx] = field(default_factory=list)
    tumblers: List[TumblerInTx] = field(default_factory=list)
    taker: Optional[str] = None
    cj_amount: float = 0.0  # BTC
    fb_maker_count: int = 0
    non_fb_maker_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'txid': self.txid,
            'block_height': self.block_height,
            'timestamp': self.timestamp,
            'makers': [m.to_dict() for m in self.makers],
            'tumblers': [t.to_dict() for t in self.tumblers],
            'taker': self.taker,
            'cj_amount': self.cj_amount,
            'fb_maker_count': self.fb_maker_count,
            'non_fb_maker_count': self.non_fb_maker_count,
            'total_maker_count': self.fb_maker_count + self.non_fb_maker_count
        }


@dataclass
class MakerProfile:
    """Profile of a single maker across all transactions."""
    client_id: str
    has_fidelity_bond: bool
    bond_amount: Optional[int]  # satoshis
    bond_locktime: Optional[str]  # "YYYY-MM"
    total_participations: int = 0
    total_fees_earned: float = 0.0  # BTC
    transactions: List[str] = field(default_factory=list)  # txids
    bond_value: Optional[float] = None  # calculated fidelity bond value (future)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'client_id': self.client_id,
            'has_fidelity_bond': self.has_fidelity_bond,
            'bond_amount': self.bond_amount,
            'bond_amount_btc': self.bond_amount / 1e8 if self.bond_amount else None,
            'bond_locktime': self.bond_locktime,
            'total_participations': self.total_participations,
            'total_fees_earned': self.total_fees_earned,
            'avg_fee_per_tx': self.total_fees_earned / self.total_participations if self.total_participations > 0 else 0.0,
            'transactions': self.transactions,
            'bond_value': self.bond_value
        }


@dataclass
class FidelityBondStats:
    """Statistics about fidelity bond usage in CoinJoins."""

    # Per-transaction data
    transaction_details: List[TransactionFBDetail] = field(default_factory=list)

    # Aggregate statistics
    total_transactions: int = 0
    total_maker_participations: int = 0
    fb_maker_participations: int = 0
    non_fb_maker_participations: int = 0
    fb_participation_rate: float = 0.0  # percentage (0-100)

    # Maker profiles
    maker_profiles: Dict[str, MakerProfile] = field(default_factory=dict)

    # FB Value statistics
    avg_fb_value: float = 0.0  # Average FB value across bonded makers
    median_fb_value: float = 0.0  # Median FB value
    min_fb_value: float = 0.0  # Minimum FB value (non-zero)
    max_fb_value: float = 0.0  # Maximum FB value

    # Participation vs FB Value correlation
    fb_value_participation_correlation: Optional[float] = None  # Pearson correlation coefficient

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'transaction_details': [tx.to_dict() for tx in self.transaction_details],
            'aggregate_statistics': {
                'total_transactions': self.total_transactions,
                'total_maker_participations': self.total_maker_participations,
                'fb_maker_participations': self.fb_maker_participations,
                'non_fb_maker_participations': self.non_fb_maker_participations,
                'fb_participation_rate': self.fb_participation_rate,
                'non_fb_participation_rate': 100.0 - self.fb_participation_rate if self.total_maker_participations > 0 else 0.0
            },
            'fb_value_statistics': {
                'avg_fb_value': self.avg_fb_value,
                'median_fb_value': self.median_fb_value,
                'min_fb_value': self.min_fb_value,
                'max_fb_value': self.max_fb_value,
                'fb_value_participation_correlation': self.fb_value_participation_correlation
            },
            'maker_profiles': {client_id: profile.to_dict() for client_id, profile in self.maker_profiles.items()}
        }


def calculate_fidelity_bond_value(
    amount: Optional[int],
    locktime: Optional[str],
    current_block_height: Optional[int] = None,
    confirmation_time: Optional[int] = None,
    current_time: Optional[int] = None,
    exponent: float = 1.3,
    interest_rate: float = 0.015
) -> Optional[float]:
    """
    Calculate the fidelity bond value using JoinMarket formula.

    Formula: Vfb = (utxo_value · a)^exponent
    where a = max(0, min(1, e^(r·T) - 1) - min(1, e^(r·max(0,t-L)) - 1))

    Args:
        amount: Bond amount in satoshis
        locktime: Locktime in "YYYY-MM" format (e.g., "2026-10")
        current_block_height: Current block height (unused, kept for compatibility)
        confirmation_time: Unix timestamp when bond was created (if None, estimated from locktime)
        current_time: Unix timestamp for analysis time (if None, uses current time)
        exponent: Configurable parameter (default: 1.3)
        interest_rate: Annual interest rate r (default: 0.015)

    Returns:
        Calculated fidelity bond value in satoshis, or None if parameters invalid

    Reference:
        https://github.com/JoinMarket-Org/joinmarket-clientserver/blob/master/jmclient/jmclient/fidelity_bond.py
    """
    import math
    from datetime import datetime
    import time as time_module

    if not amount or not locktime:
        return None

    try:
        # Parse locktime from "YYYY-MM" format
        locktime_parts = locktime.split('-')
        if len(locktime_parts) != 2:
            return None

        year = int(locktime_parts[0])
        month = int(locktime_parts[1])

        # Convert to Unix timestamp (first day of the month)
        locktime_dt = datetime(year, month, 1)
        locktime_timestamp = int(locktime_dt.timestamp())

        # Constants
        YEAR = 60 * 60 * 24 * 365.2425  # Seconds in a Gregorian year

        # Get current time (use provided or actual current time)
        if current_time is None:
            current_time = int(time_module.time())

        # Estimate confirmation time if not provided
        # Assume bond was created 6 months before locktime as a reasonable default
        if confirmation_time is None:
            confirmation_time = locktime_timestamp - int(YEAR / 2)

        # Convert to years
        L = locktime_timestamp / YEAR  # Locktime in years
        t = current_time / YEAR  # Current time in years
        T = (locktime_timestamp - confirmation_time) / YEAR  # Lock duration in years

        # Calculate time value factor 'a'
        r = interest_rate

        # First term: min(1, e^(r·T) - 1)
        term1 = min(1.0, math.exp(r * T) - 1.0)

        # Second term: min(1, e^(r·max(0,t-L)) - 1)
        time_expired = max(0.0, t - L)
        term2 = min(1.0, math.exp(r * time_expired) - 1.0)

        # Calculate 'a'
        a = max(0.0, term1 - term2)

        # Calculate fidelity bond value
        fb_value = math.pow(amount * a, exponent)

        return fb_value

    except (ValueError, OverflowError) as e:
        # Return None if calculation fails
        return None


def analyze_fidelity_bonds(
    coinjoins: List[CoinJoin],
    client_roles: Optional[Dict[str, str]] = None
) -> FidelityBondStats:
    """
    Analyze fidelity bond usage across CoinJoin transactions.

    Args:
        coinjoins: List of CoinJoin objects to analyze
        client_roles: Optional mapping of client_id to role ('maker', 'taker', 'tumbler')

    Returns:
        FidelityBondStats containing comprehensive fidelity bond analysis

    Note:
        - Tumblers are excluded from maker statistics but shown separately in transaction details
        - Only participants with explicit role information are included
    """
    stats = FidelityBondStats()
    maker_data = defaultdict(lambda: {
        'has_bond': False,
        'bond_amount': None,
        'bond_locktime': None,
        'participations': 0,
        'fees_earned': 0.0,
        'transactions': []
    })

    # Process each transaction
    for cj in coinjoins:
        tx_detail = TransactionFBDetail(
            txid=cj.txid,
            block_height=cj.block_height,
            cj_amount=cj.cj_amount
        )

        # Add timestamp if available
        if 'time' in cj.tx:
            from datetime import datetime
            tx_detail.timestamp = datetime.fromtimestamp(cj.tx['time']).strftime('%Y-%m-%d %H:%M:%S')

        # Process participants
        for participant in cj.participants:
            if not participant.client:
                continue

            # Get role from client_roles or participant.role
            role = participant.role
            if client_roles and participant.client in client_roles:
                role = client_roles[participant.client]

            # Handle tumblers separately (shown but not in FB stats)
            if role == 'tumbler':
                tumbler = TumblerInTx(
                    client_id=participant.client,
                    delta=participant.delta
                )
                tx_detail.tumblers.append(tumbler)
                continue

            # Handle takers
            if role == 'taker':
                tx_detail.taker = participant.client
                continue

            # Handle makers (main FB analysis)
            if role == 'maker':
                has_bond = participant.fidelity_bond_enabled or False
                bond_amount = participant.fidelity_bond_amount
                bond_locktime = participant.fidelity_bond_locktime

                # Create maker in transaction record
                maker_in_tx = MakerInTx(
                    client_id=participant.client,
                    has_fidelity_bond=has_bond,
                    bond_amount=bond_amount,
                    bond_locktime=bond_locktime,
                    delta=participant.delta,
                    bond_value=calculate_fidelity_bond_value(bond_amount, bond_locktime, cj.block_height)
                )
                tx_detail.makers.append(maker_in_tx)

                # Update transaction-level counts
                if has_bond:
                    tx_detail.fb_maker_count += 1
                else:
                    tx_detail.non_fb_maker_count += 1

                # Update maker profile data
                maker_profile = maker_data[participant.client]
                maker_profile['has_bond'] = has_bond
                maker_profile['bond_amount'] = bond_amount
                maker_profile['bond_locktime'] = bond_locktime
                maker_profile['participations'] += 1
                maker_profile['fees_earned'] += participant.delta
                maker_profile['transactions'].append(cj.txid)

        stats.transaction_details.append(tx_detail)

    # Build maker profiles
    for client_id, data in maker_data.items():
        profile = MakerProfile(
            client_id=client_id,
            has_fidelity_bond=data['has_bond'],
            bond_amount=data['bond_amount'],
            bond_locktime=data['bond_locktime'],
            total_participations=data['participations'],
            total_fees_earned=data['fees_earned'],
            transactions=data['transactions'],
            bond_value=calculate_fidelity_bond_value(data['bond_amount'], data['bond_locktime'])
        )
        stats.maker_profiles[client_id] = profile

    # Calculate aggregate statistics
    stats.total_transactions = len(coinjoins)
    stats.total_maker_participations = sum(
        tx.fb_maker_count + tx.non_fb_maker_count
        for tx in stats.transaction_details
    )
    stats.fb_maker_participations = sum(
        tx.fb_maker_count
        for tx in stats.transaction_details
    )
    stats.non_fb_maker_participations = sum(
        tx.non_fb_maker_count
        for tx in stats.transaction_details
    )

    # Calculate participation rate
    if stats.total_maker_participations > 0:
        stats.fb_participation_rate = (
            stats.fb_maker_participations / stats.total_maker_participations * 100.0
        )
    else:
        stats.fb_participation_rate = 0.0

    # Calculate FB value statistics
    fb_values = []
    participations = []

    for profile in stats.maker_profiles.values():
        if profile.has_fidelity_bond and profile.bond_value is not None and profile.bond_value > 0:
            fb_values.append(profile.bond_value)
            participations.append(profile.total_participations)

    if fb_values:
        stats.avg_fb_value = sum(fb_values) / len(fb_values)
        sorted_values = sorted(fb_values)
        n = len(sorted_values)
        if n % 2 == 0:
            stats.median_fb_value = (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2.0
        else:
            stats.median_fb_value = sorted_values[n//2]
        stats.min_fb_value = min(fb_values)
        stats.max_fb_value = max(fb_values)

        # Calculate correlation between FB value and participation count
        if len(fb_values) >= 2:
            # Pearson correlation coefficient
            mean_value = sum(fb_values) / len(fb_values)
            mean_participation = sum(participations) / len(participations)

            numerator = sum((v - mean_value) * (p - mean_participation)
                          for v, p in zip(fb_values, participations))
            denominator_v = sum((v - mean_value) ** 2 for v in fb_values) ** 0.5
            denominator_p = sum((p - mean_participation) ** 2 for p in participations) ** 0.5

            if denominator_v > 0 and denominator_p > 0:
                stats.fb_value_participation_correlation = numerator / (denominator_v * denominator_p)

    return stats


def enrich_coinjoins_with_fidelity_bonds(
    coinjoins: List[CoinJoin],
    client_bonds: Dict[str, dict]
) -> None:
    """
    Enrich CoinJoin participants with fidelity bond information.

    Args:
        coinjoins: List of CoinJoin objects to enrich (modified in-place)
        client_bonds: Dictionary mapping client_id to bond info from scenario

    Note:
        This function modifies the CoinJoin objects in-place by populating
        the fidelity bond fields in each participant.
    """
    for cj in coinjoins:
        for participant in cj.participants:
            if not participant.client:
                continue

            # Look up fidelity bond info for this client
            bond_info = client_bonds.get(participant.client)
            if bond_info:
                participant.fidelity_bond_enabled = bond_info.get('enabled', False)
                participant.fidelity_bond_amount = bond_info.get('amount')
                participant.fidelity_bond_locktime = bond_info.get('locktime')


def render_fidelity_bond_html_report(
    fidelity_bond_stats: FidelityBondStats,
    output_path: str,
    metadata: Optional[Dict[str, str]] = None
) -> None:
    """
    Render a standalone HTML report for fidelity bond analysis.

    Args:
        fidelity_bond_stats: FidelityBondStats object with analysis results
        output_path: Path where the HTML file should be saved
        metadata: Optional metadata dict (data_dir, timestamp, scenario_name)
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    import os

    env = Environment(
        loader=FileSystemLoader(os.path.dirname(__file__) or "."),
        autoescape=select_autoescape()
    )

    template = env.get_template("fidelity_bond_standalone_template.html")
    html_content = template.render(fb_stats=fidelity_bond_stats, metadata=metadata)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Fidelity bond HTML report saved: {os.path.abspath(output_path)}")


def save_fidelity_bond_json(
    fidelity_bond_stats: FidelityBondStats,
    output_path: str,
    metadata: Optional[Dict[str, str]] = None
) -> None:
    """
    Save fidelity bond statistics to a JSON file.

    Args:
        fidelity_bond_stats: FidelityBondStats object with analysis results
        output_path: Path where the JSON file should be saved
        metadata: Optional metadata dict to include in the output
    """
    import json
    import os

    # Convert to dictionary
    data = fidelity_bond_stats.to_dict()

    # Add metadata if provided
    if metadata:
        data['metadata'] = metadata

    # Write to file with pretty printing
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Fidelity bond JSON data saved: {os.path.abspath(output_path)}")
