"""
Sudoku Performance Statistics Collector.

Gathers detailed performance and complexity metrics during sudoku solving
to analyze how performance deteriorates with transaction size and complexity.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from decimal import Decimal
import json


@dataclass
class SudokuSolveStatistics:
    """Statistics for a single transaction solve attempt."""

    # Transaction identification
    txid: str

    # Transaction characteristics
    num_inputs: int
    num_outputs: int
    num_cj_outputs: int
    num_change_outputs: int
    is_sweep: bool

    # Timing metrics (seconds)
    total_time: float = 0.0
    subset_generation_time: float = 0.0
    subset_multiplication_time: float = 0.0
    filtering_time: float = 0.0
    dfs_time: float = 0.0
    binary_search_iterations: int = 0

    # Complexity metrics
    total_possible_subsets: int = 0  # 2^num_inputs
    viable_subsets_pre_filter: int = 0
    viable_subsets_post_filter: int = 0
    subset_indicator_size_bytes: int = 0

    # DFS metrics
    dfs_prune_count: int = 0
    viable_subsets_by_change: List[int] = field(default_factory=list)  # Per change output
    viable_taker_subsets_by_change: List[int] = field(default_factory=list)

    # Outcome metrics
    success: bool = False
    num_solutions: int = 0
    optimal_maker_gain_max: Optional[int] = None
    failure_reason: Optional[str] = None
    skipped: bool = False

    # Strategy used
    strategy: str = "unknown"  # matrix_multiplication, dfs_assignment, taker_sweep
    search_strategy: Optional[str] = None  # For binary search

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        # Convert Decimal to int if needed
        if self.optimal_maker_gain_max is not None:
            result['optimal_maker_gain_max'] = int(self.optimal_maker_gain_max)
        return result


class SudokuStatisticsCollector:
    """
    Collects and manages statistics for sudoku solving.

    Usage:
        collector = SudokuStatisticsCollector(enabled=True)

        # Start tracking a transaction
        stats = collector.start_transaction(txid, tx, cj_outs, ch_outs)

        # Record timing for specific operations
        with collector.time_operation(stats, 'subset_generation'):
            # ... generate subsets ...
            pass

        # Update metrics
        stats.viable_subsets_pre_filter = len(valid_indices)
        stats.dfs_prune_count = context.prune_count

        # Mark as complete
        collector.complete_transaction(stats, solutions, maker_gain_max)
    """

    def __init__(self, enabled: bool = False):
        """
        Initialize the statistics collector.

        Args:
            enabled: Whether to collect statistics
        """
        self.enabled = enabled
        self.statistics: List[SudokuSolveStatistics] = []
        self._current_tx_stats: Dict[str, SudokuSolveStatistics] = {}

    def start_transaction(
        self,
        txid: str,
        tx: Dict[str, Any],
        cj_outs: List[Dict[str, Any]],
        ch_outs: List[Dict[str, Any]]
    ) -> Optional[SudokuSolveStatistics]:
        """
        Start tracking statistics for a transaction.

        Args:
            txid: Transaction ID
            tx: Transaction data
            cj_outs: CoinJoin outputs
            ch_outs: Change outputs

        Returns:
            SudokuSolveStatistics object if enabled, None otherwise
        """
        if not self.enabled:
            return None

        stats = SudokuSolveStatistics(
            txid=txid,
            num_inputs=len(tx.get('vin', [])),
            num_outputs=len(tx.get('vout', [])),
            num_cj_outputs=len(cj_outs),
            num_change_outputs=len(ch_outs),
            is_sweep=(len(ch_outs) != len(cj_outs)),
            total_possible_subsets=2 ** len(tx.get('vin', []))
        )

        stats._start_time = time.time()
        self._current_tx_stats[txid] = stats
        return stats

    def complete_transaction(
        self,
        stats: Optional[SudokuSolveStatistics],
        solutions: List[Any],
        maker_gain_max: Optional[Decimal] = None,
        failure_reason: Optional[str] = None,
        skipped: bool = False
    ):
        """
        Mark a transaction as complete and record final metrics.

        Args:
            stats: Statistics object from start_transaction
            solutions: List of solutions found
            maker_gain_max: Optimal maker_gain_max value found
            failure_reason: Reason for failure if no solutions
            skipped: Whether transaction was skipped
        """
        if not self.enabled or stats is None:
            return

        stats.total_time = time.time() - stats._start_time
        stats.success = len(solutions) > 0
        stats.num_solutions = len(solutions)
        stats.failure_reason = failure_reason
        stats.skipped = skipped

        if maker_gain_max is not None:
            stats.optimal_maker_gain_max = int(maker_gain_max)

        self.statistics.append(stats)

        # Clean up current tracking
        if stats.txid in self._current_tx_stats:
            del self._current_tx_stats[stats.txid]

    def record_timing(
        self,
        stats: Optional[SudokuSolveStatistics],
        operation: str,
        duration: float
    ):
        """
        Record timing for a specific operation.

        Args:
            stats: Statistics object
            operation: Name of operation (subset_generation, dfs, etc.)
            duration: Duration in seconds
        """
        if not self.enabled or stats is None:
            return

        if operation == 'subset_generation':
            stats.subset_generation_time = duration
        elif operation == 'subset_multiplication':
            stats.subset_multiplication_time = duration
        elif operation == 'filtering':
            stats.filtering_time = duration
        elif operation == 'dfs':
            stats.dfs_time = duration

    def get_statistics(self) -> List[SudokuSolveStatistics]:
        """Get all collected statistics."""
        return self.statistics

    def export_json(self, filepath: str):
        """
        Export statistics to JSON file.

        Args:
            filepath: Path to output JSON file
        """
        if not self.enabled:
            return

        with open(filepath, 'w') as f:
            json.dump(
                [stats.to_dict() for stats in self.statistics],
                f,
                indent=2
            )

    def export_csv(self, filepath: str):
        """
        Export statistics to CSV file.

        Args:
            filepath: Path to output CSV file
        """
        if not self.enabled or not self.statistics:
            return

        import csv

        # Get all field names
        fieldnames = list(self.statistics[0].to_dict().keys())

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for stats in self.statistics:
                # Convert list fields to strings
                row = stats.to_dict()
                row['viable_subsets_by_change'] = str(row['viable_subsets_by_change'])
                row['viable_taker_subsets_by_change'] = str(row['viable_taker_subsets_by_change'])
                writer.writerow(row)

    def print_summary(self):
        """Print a summary of collected statistics."""
        if not self.enabled or not self.statistics:
            print("No statistics collected")
            return

        print("\n" + "="*80)
        print("SUDOKU SOLVER PERFORMANCE STATISTICS")
        print("="*80)

        total = len(self.statistics)
        successful = sum(1 for s in self.statistics if s.success)
        skipped = sum(1 for s in self.statistics if s.skipped)

        print(f"\nOverall Results:")
        print(f"  Total transactions: {total}")
        print(f"  Successful: {successful} ({100*successful/total:.1f}%)")
        print(f"  Failed: {total - successful - skipped} ({100*(total-successful-skipped)/total:.1f}%)")
        print(f"  Skipped: {skipped} ({100*skipped/total:.1f}%)")

        # Timing statistics
        successful_stats = [s for s in self.statistics if s.success]
        if successful_stats:
            avg_time = sum(s.total_time for s in successful_stats) / len(successful_stats)
            max_time = max(s.total_time for s in successful_stats)
            min_time = min(s.total_time for s in successful_stats)

            print(f"\nTiming (successful solves):")
            print(f"  Average total time: {avg_time:.3f}s")
            print(f"  Min time: {min_time:.3f}s")
            print(f"  Max time: {max_time:.3f}s")

        # Size analysis
        print(f"\nTransaction Size Distribution:")
        size_buckets = {}
        for s in self.statistics:
            bucket = (s.num_inputs // 5) * 5  # Bucket by 5s
            if bucket not in size_buckets:
                size_buckets[bucket] = {'total': 0, 'success': 0}
            size_buckets[bucket]['total'] += 1
            if s.success:
                size_buckets[bucket]['success'] += 1

        for bucket in sorted(size_buckets.keys()):
            data = size_buckets[bucket]
            success_rate = 100 * data['success'] / data['total']
            print(f"  {bucket}-{bucket+4} inputs: {data['total']} txs, "
                  f"{success_rate:.1f}% success")

        # Complexity analysis
        if successful_stats:
            print(f"\nComplexity Metrics (successful solves):")
            avg_subsets = sum(s.viable_subsets_post_filter for s in successful_stats) / len(successful_stats)
            avg_prunes = sum(s.dfs_prune_count for s in successful_stats) / len(successful_stats)

            print(f"  Avg viable subsets: {avg_subsets:.0f}")
            print(f"  Avg DFS prunes: {avg_prunes:.0f}")

        print("="*80 + "\n")
