"""Create the numeric 74-feature matrix for the autoencoder handoff."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from .feature_separation import SeparatedAggregatedData
from .schema import FEATURE_COLUMNS


@dataclass(frozen=True)
class ModelFeatureMatrix:
    """The feature-only numeric data handed to the autoencoder stage.

    ``X[row_index]`` corresponds to the same row index in the separate
    ``SeparatedAggregatedData.metadata_rows`` output.  Metadata is not stored
    in this object and is never included in ``X``.
    """

    source_path: Path
    feature_columns: tuple[str, ...]
    X: NDArray[np.float64]


def build_feature_matrix(separated_data: SeparatedAggregatedData) -> ModelFeatureMatrix:
    """Convert the 74 validated feature fields into a finite float64 matrix.

    The input must be the output of the earlier separation step.  Features are
    retained in ``schema.FEATURE_COLUMNS`` order, yielding shape ``(n_rows,
    74)``.  This function intentionally has no labels, metadata, aggregation,
    or anomaly-detection logic.
    """
    expected_columns = tuple(FEATURE_COLUMNS)
    if separated_data.feature_columns != expected_columns:
        raise ValueError(
            "cannot build X: feature columns are not in schema.FEATURE_COLUMNS order"
        )
    if any(len(row) != len(expected_columns) for row in separated_data.feature_rows):
        raise ValueError("cannot build X: every feature row must contain exactly 74 fields")

    if separated_data.feature_rows:
        try:
            X = np.asarray(separated_data.feature_rows, dtype=np.float64)
        except ValueError as error:
            raise ValueError("cannot build X: feature values must be numeric") from error
    else:
        X = np.empty((0, len(expected_columns)), dtype=np.float64)

    if not np.isfinite(X).all():
        raise ValueError("cannot build X: feature values must be finite float64 numbers")

    return ModelFeatureMatrix(
        source_path=separated_data.source_path,
        feature_columns=expected_columns,
        X=X,
    )
