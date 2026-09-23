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
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import torch

from member2.pipeline import prepare_aggregated_csv

from .autoencoder import SyscallAutoencoder


MODELS_DIR = Path("person3_ml/models")


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


def detect_anomalies(csv_path: str | Path):

    prepared = prepare_aggregated_csv(
        csv_path
    )

    X = prepared.X

    if X.ndim != 2 or X.shape[1] != 74:
        raise ValueError(
            f"Expected feature matrix with shape "
            f"(N, 74), got {X.shape}"
        )

    model, scaler, threshold = load_artifacts()

    X_scaled = scaler.transform(X)

    X_tensor = torch.tensor(
        X_scaled,
        dtype=torch.float32,
    )

    with torch.no_grad():

        reconstruction_errors = (
            model.reconstruction_error(
                X_tensor,
                reduction="none",
            )
            .numpy()
        )

    predictions = (
        reconstruction_errors > threshold
    ).astype(int)

    return (
        prepared.metadata_rows,
        reconstruction_errors,
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