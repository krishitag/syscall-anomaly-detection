"""Read Naman's already-aggregated CSV without changing its contents.

This is intentionally only the Task 5 loading boundary.  It preserves the
header names, their incoming order, and every field as text so later tasks can
validate the original delivery and then map it into the canonical schema.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoadedAggregatedCsv:
    """The raw CSV representation passed from loading to validation.

    ``header`` and each row retain incoming CSV order.  In particular, rows
    are tuples rather than dictionaries so a later validator can detect a
    duplicate header name instead of losing one of its values.
    """

    source_path: Path
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def load_aggregated_csv(input_path: str | Path) -> LoadedAggregatedCsv:
    """Load an aggregated CSV file while preserving its raw field values.

    This function only reads RFC 4180-style CSV content.  It does not enforce
    the 77-column contract, coerce numeric types, reorder columns, or prepare
    model features; those responsibilities belong to later pipeline tasks.
    """
    source_path = Path(input_path)
    with source_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file, strict=True)
        try:
            header = tuple(next(reader))
        except StopIteration:
            header = ()
        rows = tuple(tuple(row) for row in reader)

    return LoadedAggregatedCsv(
        source_path=source_path,
        header=header,
        rows=rows,
    )
