"""
Preprocessing utilities for the syscall anomaly detection model.

The scaler is fitted only on the training data and then reused
for validation and future inference.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.preprocessing import StandardScaler


FEATURE_COUNT = 74


@dataclass
class FeatureScaler:
    """Wrapper around sklearn StandardScaler."""

    scaler: StandardScaler

    @classmethod
    def create(cls) -> "FeatureScaler":
        return cls(StandardScaler())

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

    @staticmethod
    def _validate(X: np.ndarray) -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a NumPy array")

        if X.ndim != 2:
            raise ValueError(
                f"Expected 2D array, got shape {X.shape}"
            )

        if X.shape[1] != FEATURE_COUNT:
            raise ValueError(
                f"Expected {FEATURE_COUNT} features, "
                f"got {X.shape[1]}"
            )

        if not np.isfinite(X).all():
            raise ValueError(
                "Feature matrix contains NaN or infinite values"
            )