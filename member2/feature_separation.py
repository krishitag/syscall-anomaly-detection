"""Separate canonical aggregated rows into metadata context and model features."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .column_mapping import CanonicalAggregatedCsv
from .schema import FEATURE_COLUMNS, METADATA_COLUMNS


@dataclass(frozen=True)
class SeparatedAggregatedData:
    """Parallel metadata and feature rows from one canonical CSV delivery.

    Row ``n`` in ``metadata_rows`` always describes row ``n`` in
    ``feature_rows``.  Values remain strings until Task 9 creates the numeric
    model matrix.
    """

    source_path: Path
    metadata_columns: tuple[str, ...]
    metadata_rows: tuple[tuple[str, ...], ...]
    feature_columns: tuple[str, ...]
    feature_rows: tuple[tuple[str, ...], ...]


def separate_metadata_and_features(
    canonical_csv: CanonicalAggregatedCsv,
) -> SeparatedAggregatedData:
    """Keep the 3 context fields apart from the 74 autoencoder features."""
    header_indexes = {column: index for index, column in enumerate(canonical_csv.header)}
    metadata_indexes = tuple(header_indexes[column] for column in METADATA_COLUMNS)
    feature_indexes = tuple(header_indexes[column] for column in FEATURE_COLUMNS)

    metadata_rows = tuple(
        tuple(row[index] for index in metadata_indexes) for row in canonical_csv.rows
    )
    feature_rows = tuple(
        tuple(row[index] for index in feature_indexes) for row in canonical_csv.rows
    )

    return SeparatedAggregatedData(
        source_path=canonical_csv.source_path,
        metadata_columns=tuple(METADATA_COLUMNS),
        metadata_rows=metadata_rows,
        feature_columns=tuple(FEATURE_COLUMNS),
        feature_rows=feature_rows,
    )
