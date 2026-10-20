"""
Preprocessing utilities for the syscall anomaly detection model.

The scaler is fitted only on the training data and then reused
for validation and future inference.

The model sees a subset of the 74 CSV feature columns, chosen from normal
training windows only (see ``select_feature_columns``).  The CSV keeps all
77 columns; the subset is applied after the member2 pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.preprocessing import StandardScaler

from member2.schema import (
    FEATURE_COLUMNS,
    PAIR_COUNT_COLUMNS,
    SYSCALL_COUNT_COLUMNS,
)


FEATURE_COUNT = 74

# stat_04 (distinct families per window) is populated; stat_01-03 are
# always zero (not implemented in the tracer) and are left out.
POPULATED_STAT_COLUMNS = ["stat_04"]


def select_feature_columns(X_normal: np.ndarray) -> list[str]:
    """Model input columns, chosen from normal windows only.

    - all 20 syscall-family counts: the vocabulary is fixed in advance, and
      the security-relevant families are zero in normal traffic by design
    - pair columns that are non-zero in at least one normal window
    - stat_04
    """

    if X_normal.ndim != 2 or X_normal.shape[1] != FEATURE_COUNT:
        raise ValueError(
            f"Expected X shape (N, {FEATURE_COUNT}), got {X_normal.shape}"
        )

    observed_pairs = [
        column
        for column in PAIR_COUNT_COLUMNS
        if (X_normal[:, FEATURE_COLUMNS.index(column)] != 0).any()
    ]

    return SYSCALL_COUNT_COLUMNS + observed_pairs + POPULATED_STAT_COLUMNS


def column_indices(columns: list[str]) -> np.ndarray:
    """Positions of ``columns`` in the 74-column feature matrix."""

    return np.array([FEATURE_COLUMNS.index(column) for column in columns])


@dataclass
class FeatureScaler:
    """Wrapper around sklearn StandardScaler."""

    scaler: StandardScaler
    feature_count: int = FEATURE_COUNT

    @classmethod
    def create(cls, feature_count: int = FEATURE_COUNT) -> "FeatureScaler":
        return cls(StandardScaler(), feature_count)

    def fit(self, X: np.ndarray) -> "FeatureScaler":
        self._validate(X)
        self.scaler.fit(X)
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        self._validate(X)

        transformed = self.scaler.transform(X)

        return transformed.astype(np.float32)

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        self.fit(X)
        return self.transform(X)

    def _validate(self, X: np.ndarray) -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a NumPy array")

        if X.ndim != 2:
            raise ValueError(
                f"Expected 2D array, got shape {X.shape}"
            )

        if X.shape[1] != self.feature_count:
            raise ValueError(
                f"Expected {self.feature_count} features, "
                f"got {X.shape[1]}"
            )

        if not np.isfinite(X).all():
            raise ValueError(
                "Feature matrix contains NaN or infinite values"
            )