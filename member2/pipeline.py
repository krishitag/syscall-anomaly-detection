"""Stable Member 2 integration seam: aggregated CSV path -> model-ready input."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from numpy.typing import NDArray
import numpy as np

from .column_mapping import map_to_canonical_order
from .csv_loader import load_aggregated_csv
from .feature_separation import separate_metadata_and_features
from .model_input import build_feature_matrix
from .schema import FEATURE_COLUMNS
from .validation import validate_aggregated_csv, validate_window_row


@dataclass(frozen=True)
class PreparedAggregatedInput:
    """The complete Member 2 handoff for one valid, unlabelled CSV delivery.

    ``X`` is the only value intended for Abhiram's autoencoder.  The parallel
    metadata rows remain context for interpreting later results.
    """

    source_path: Path
    X: NDArray[np.float64]
    feature_columns: tuple[str, ...]
    metadata_columns: tuple[str, ...]
    metadata_rows: tuple[tuple[str, ...], ...]


def prepare_aggregated_csv(input_path: str | Path) -> PreparedAggregatedInput:
    """Prepare an unlabelled Naman-format aggregated CSV for the autoencoder.

    This is the stable boundary for both the Task 4 mock file and Naman's
    real eBPF output (``ebpf/tracer.py``).  The source is loaded, contract-validated,
    reordered by name, separated into context/features, then converted into a
    finite ``float64`` matrix.  It does not inspect raw syscalls, aggregate
    rows, use labels, or perform anomaly detection.
    """
    loaded_csv = load_aggregated_csv(input_path)
    validate_aggregated_csv(loaded_csv)
    canonical_csv = map_to_canonical_order(loaded_csv)
    separated_data = separate_metadata_and_features(canonical_csv)
    model_matrix = build_feature_matrix(separated_data)

    return PreparedAggregatedInput(
        source_path=model_matrix.source_path,
        X=model_matrix.X,
        feature_columns=model_matrix.feature_columns,
        metadata_columns=separated_data.metadata_columns,
        metadata_rows=separated_data.metadata_rows,
    )


def prepare_window(row: Mapping[str, object]) -> NDArray[np.float64]:
    """Prepare one live window row into the autoencoder's 74-feature vector.

    ``row`` maps each of the 77 contract column names to its value, e.g.
    ``dict(zip(schema.ALL_COLUMNS, values))`` for a row the tracer just wrote.
    Values may be numbers or CSV text.  The row gets the same contract checks
    and feature order as :func:`prepare_aggregated_csv`, so ``x`` matches one
    row of its ``X``.
    """
    raw_row = {column: str(value) for column, value in row.items()}
    validate_window_row(raw_row)
    return np.array([float(raw_row[column]) for column in FEATURE_COLUMNS], dtype=np.float64)
