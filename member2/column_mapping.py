"""Map validated aggregated CSV fields into the schema's canonical order."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .csv_loader import LoadedAggregatedCsv
from .schema import ALL_COLUMNS


@dataclass(frozen=True)
class CanonicalAggregatedCsv:
    """An aggregated CSV with fields ordered exactly as ``schema.ALL_COLUMNS``.

    Values remain raw strings.  Numeric conversion and separation into model
    features versus metadata are intentionally handled by later tasks.
    """

    source_path: Path
    rows: tuple[tuple[str, ...], ...]

    @property
    def header(self) -> tuple[str, ...]:
        """Return the canonical 77-column header."""
        return tuple(ALL_COLUMNS)


def map_to_canonical_order(loaded_csv: LoadedAggregatedCsv) -> CanonicalAggregatedCsv:
    """Reorder validated CSV fields by name into ``schema.ALL_COLUMNS`` order.

    Call :func:`member2.validation.validate_aggregated_csv` first.  This
    function only performs the name-based mapping and gives a clear error if
    its basic validated-input precondition is not met.
    """
    incoming_header = loaded_csv.header
    if len(incoming_header) != len(set(incoming_header)) or set(incoming_header) != set(
        ALL_COLUMNS
    ):
        raise ValueError(
            "cannot map CSV: header must contain each schema column exactly once; "
            "run validate_aggregated_csv first"
        )
    if any(len(row) != len(incoming_header) for row in loaded_csv.rows):
        raise ValueError(
            "cannot map CSV: every row must have the same field count as the header; "
            "run validate_aggregated_csv first"
        )

    indexes = {column: index for index, column in enumerate(incoming_header)}
    canonical_rows = tuple(
        tuple(row[indexes[column]] for column in ALL_COLUMNS) for row in loaded_csv.rows
    )
    return CanonicalAggregatedCsv(
        source_path=loaded_csv.source_path,
        rows=canonical_rows,
    )
