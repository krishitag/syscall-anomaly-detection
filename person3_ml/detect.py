"""
Run the trained Autoencoder on aggregated syscall data.

The detector:
    CSV
      -> Member 2 pipeline
      -> 74 features
      -> trained StandardScaler
      -> trained Autoencoder
      -> reconstruction error
      -> anomaly threshold
      -> NORMAL / ANOMALY

For the live demo, ``score_window`` scores one 74-feature vector from
``member2.pipeline.prepare_window`` and ``anomaly_threshold`` gives the
cut-off.  Both load the saved artifacts once and reuse them.
"""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import torch

from member2.pipeline import prepare_aggregated_csv

from .autoencoder import SyscallAutoencoder


MODELS_DIR = Path(__file__).resolve().parent / "models"


def load_artifacts():
    """Load the trained model, scaler, and threshold."""

    model = SyscallAutoencoder(
        input_dim=74,
        latent_dim=8,
    )

    model.load_state_dict(
        torch.load(
            MODELS_DIR / "autoencoder.pt",
            map_location="cpu",
        )
    )

    model.eval()

    scaler = joblib.load(
        MODELS_DIR / "scaler.joblib"
    )

    with open(
        MODELS_DIR / "threshold.json",
        "r",
        encoding="utf-8",
    ) as file:
        threshold_data = json.load(file)

    threshold = float(
        threshold_data["threshold"]
    )

    return model, scaler, threshold


@lru_cache(maxsize=1)
def _cached_artifacts():
    """Load the artifacts once per process for window-by-window scoring."""

    return load_artifacts()


def reconstruction_errors(X: np.ndarray) -> np.ndarray:
    """Return one reconstruction error per row of an (N, 74) feature matrix."""

    if X.ndim != 2 or X.shape[1] != 74:
        raise ValueError(
            f"Expected feature matrix with shape "
            f"(N, 74), got {X.shape}"
        )

    model, scaler, _ = _cached_artifacts()

    X_scaled = scaler.transform(X)

    X_tensor = torch.tensor(
        X_scaled,
        dtype=torch.float32,
    )

    with torch.no_grad():

        return (
            model.reconstruction_error(
                X_tensor,
                reduction="none",
            )
            .numpy()
        )


def score_window(x: np.ndarray) -> float:
    """Return the reconstruction error for one 74-feature window.

    ``x`` is the vector from ``member2.pipeline.prepare_window``.  The window
    is anomalous when the score is above ``anomaly_threshold()``.
    """

    x = np.asarray(x, dtype=np.float64)

    if x.shape != (74,):
        raise ValueError(
            f"Expected one window with shape (74,), got {x.shape}"
        )

    return float(reconstruction_errors(x.reshape(1, 74))[0])


def anomaly_threshold() -> float:
    """Return the saved reconstruction-error threshold."""

    _, _, threshold = _cached_artifacts()

    return threshold


def detect_anomalies(csv_path: str | Path):

    prepared = prepare_aggregated_csv(
        csv_path
    )

    errors = reconstruction_errors(prepared.X)
    threshold = anomaly_threshold()

    predictions = (
        errors > threshold
    ).astype(int)

    return (
        prepared.metadata_rows,
        errors,
        predictions,
        threshold,
    )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Detect anomalous syscall windows "
            "using the trained Autoencoder."
        )
    )

    parser.add_argument(
        "csv_path",
        help="Path to aggregated syscall CSV.",
    )

    args = parser.parse_args()

    (
        metadata_rows,
        errors,
        predictions,
        threshold,
    ) = detect_anomalies(args.csv_path)

    print()
    print("=" * 70)
    print("SYSCALL ANOMALY DETECTION")
    print("=" * 70)

    print(
        f"Threshold           : {threshold:.6f}"
    )

    print(
        f"Windows analyzed    : {len(errors)}"
    )

    print(
        f"Normal predictions  : "
        f"{(predictions == 0).sum()}"
    )

    print(
        f"Anomaly predictions : "
        f"{(predictions == 1).sum()}"
    )

    print()

    print(
        f"{'Window':<10}"
        f"{'Reconstruction Error':<25}"
        f"{'Prediction':<15}"
    )

    print("-" * 55)

    for index, error in enumerate(errors):

        label = (
            "ANOMALY"
            if predictions[index] == 1
            else "NORMAL"
        )

        print(
            f"{index:<10}"
            f"{error:<25.6f}"
            f"{label:<15}"
        )


if __name__ == "__main__":
    main()