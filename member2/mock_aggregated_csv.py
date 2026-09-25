"""Generate contract-compliant mock *aggregated* syscall CSV data.

This is a Task 4 development fixture only.  Each emitted row already
represents one container over one closed window; this module neither accepts
nor derives data from individual syscall events.

Test-fixture conventions (real data comes from ``ebpf/tracer.py``):
  * ``cgroup_id`` is a small int64 (1000, 1001, ...), matching the real type.
  * timestamps are synthetic nanoseconds from an arbitrary fixed origin,
    not real Unix-epoch times.
  * the four statistic columns are emitted as zeroes, which is within every
    statistic's valid range.

Feature column names and ordering always come from :mod:`member2.schema`, so
the generator follows the eventual agreed vocabulary automatically.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Sequence

from .schema import (
    ALL_COLUMNS,
    PAIR_COUNT_COLUMNS,
    STAT_COLUMNS,
    SYSCALL_COUNT_COLUMNS,
)


# Arbitrary synthetic values, deliberately not a claimed real clock/epoch.
_SYNTHETIC_START_NS = 1_000_000_000_000
_WINDOW_DURATION_NS = 1_000_000_000


def _aggregated_row(container_index: int, window_index: int) -> dict[str, int]:
    """Build one complete, already-aggregated observation row."""
    window_start_ns = _SYNTHETIC_START_NS + window_index * _WINDOW_DURATION_NS

    row: dict[str, int] = {
        "cgroup_id": 1000 + container_index,
        "window_start_ns": window_start_ns,
        "window_end_ns": window_start_ns + _WINDOW_DURATION_NS,
    }

    # These values are fixture data for already-computed feature columns, not
    # counts calculated from simulated raw syscall events.
    for feature_index, column in enumerate(SYSCALL_COUNT_COLUMNS, start=1):
        row[column] = (container_index + 1) * (window_index + feature_index)
    for feature_index, column in enumerate(PAIR_COUNT_COLUMNS, start=1):
        row[column] = (container_index + window_index + feature_index) % 11
    for column in STAT_COLUMNS:
        row[column] = 0

    return row


def generate_mock_aggregated_csv(
    output_path: str | Path,
    *,
    containers: int = 2,
    windows_per_container: int = 3,
) -> Path:
    """Write mock rows conforming to the current 77-column CSV contract.

    Args:
        output_path: Destination CSV file. Parent directories are created.
        containers: Number of placeholder containers to include; must be > 0.
        windows_per_container: Closed windows per container; must be > 0.

    Returns:
        The destination path.
    """
    if containers <= 0:
        raise ValueError("containers must be greater than zero")
    if windows_per_container <= 0:
        raise ValueError("windows_per_container must be greater than zero")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ALL_COLUMNS)
        writer.writeheader()
        for container_index in range(containers):
            for window_index in range(windows_per_container):
                writer.writerow(_aggregated_row(container_index, window_index))

    return destination


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate mock already-aggregated syscall CSV observations."
    )
    parser.add_argument("output", type=Path, help="destination CSV path")
    parser.add_argument(
        "--containers", type=int, default=2, help="placeholder containers (default: 2)"
    )
    parser.add_argument(
        "--windows-per-container",
        type=int,
        default=3,
        help="closed windows per container (default: 3)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the generator as ``python -m member2.mock_aggregated_csv``."""
    args = _parse_args(argv)
    output_path = generate_mock_aggregated_csv(
        args.output,
        containers=args.containers,
        windows_per_container=args.windows_per_container,
    )
    print(
        f"Wrote {args.containers * args.windows_per_container} already-aggregated "
        f"rows with {len(ALL_COLUMNS)} columns to {output_path}"
    )


if __name__ == "__main__":
    main()
