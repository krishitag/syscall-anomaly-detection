"""
Train the syscall anomaly detection Autoencoder.

Training data:
    data/normal.csv

The model learns normal Docker container syscall behavior.
Anomaly detection is based on reconstruction error.

Validation is the most recent part of the capture, not a random sample.
Tracer windows can overlap (2 s span, emitted every 1 s), so a random split
would put near-duplicate rows on both sides.  Training rows that overlap the
validation period are dropped.

The threshold is mean + 3 x std of validation reconstruction error.  The
95th and 99th percentiles are saved alongside it for reference.

The model input is a subset of the 74 columns, chosen from the normal
training windows only (``preprocessing.select_feature_columns``) and saved
to features.json next to the model.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import joblib
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from member2.pipeline import prepare_aggregated_csv

from .autoencoder import SyscallAutoencoder
from .preprocessing import (
    FeatureScaler,
    column_indices,
    select_feature_columns,
)


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

RANDOM_SEED = 42

BATCH_SIZE = 32
EPOCHS = 100
LEARNING_RATE = 1e-3

VALIDATION_RATIO = 0.20

THRESHOLD_STD_MULTIPLIER = 3.0

MODELS_DIR = Path(__file__).resolve().parent / "models"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


# ---------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------

def set_seed(seed: int = RANDOM_SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# ---------------------------------------------------------
# Data split
# ---------------------------------------------------------

def split_normal_data(
    X: np.ndarray,
    window_starts: np.ndarray,
    window_ends: np.ndarray,
    validation_ratio: float = VALIDATION_RATIO,
) -> tuple[np.ndarray, np.ndarray]:
    """Split by time: the latest windows become validation.

    Training windows that end after the first validation window starts are
    dropped, so overlapping windows never appear on both sides.
    """

    if X.ndim != 2 or X.shape[1] != 74:
        raise ValueError(
            f"Expected X shape (N, 74), got {X.shape}"
        )

    if len(X) < 10:
        raise ValueError(
            "At least 10 windows are required for training."
        )

    order = np.argsort(window_starts, kind="stable")

    validation_size = max(
        1,
        int(len(X) * validation_ratio),
    )

    validation_indices = order[-validation_size:]
    validation_start = window_starts[validation_indices].min()

    candidate_indices = order[:-validation_size]
    training_indices = candidate_indices[
        window_ends[candidate_indices] <= validation_start
    ]

    X_train = X[training_indices]
    X_validation = X[validation_indices]

    return X_train, X_validation


# ---------------------------------------------------------
# Training
# ---------------------------------------------------------

def train_model(
    X: np.ndarray,
    window_starts: np.ndarray,
    window_ends: np.ndarray,
) -> tuple[
    SyscallAutoencoder,
    FeatureScaler,
    list[str],
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:

    X_train, X_validation = split_normal_data(
        X,
        window_starts,
        window_ends,
    )

    print()
    print("=" * 65)
    print("DATA SPLIT")
    print("=" * 65)
    print(f"Total windows       : {len(X)}")
    print(f"Dropped (overlap)   : {len(X) - len(X_train) - len(X_validation)}")
    print(f"Training windows    : {len(X_train)}")
    print(f"Validation windows  : {len(X_validation)}")

    # -----------------------------------------------------
    # Choose model input columns from training data ONLY
    # -----------------------------------------------------

    feature_columns = select_feature_columns(X_train)
    selected = column_indices(feature_columns)

    X_train = X_train[:, selected]
    X_validation = X_validation[:, selected]

    print()
    print(f"Model features      : {len(feature_columns)} of 74")
    print(f"  {', '.join(feature_columns)}")

    # -----------------------------------------------------
    # Fit scaler ONLY on training data
    # -----------------------------------------------------

    scaler = FeatureScaler.create(len(feature_columns))

    X_train_scaled = scaler.fit_transform(X_train)
    X_validation_scaled = scaler.transform(X_validation)

    # -----------------------------------------------------
    # Convert to PyTorch tensors
    # -----------------------------------------------------

    X_train_tensor = torch.tensor(
        X_train_scaled,
        dtype=torch.float32,
    )

    X_validation_tensor = torch.tensor(
        X_validation_scaled,
        dtype=torch.float32,
    )

    dataset = TensorDataset(X_train_tensor)

    loader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
    )

    # -----------------------------------------------------
    # Create model
    # -----------------------------------------------------

    model = SyscallAutoencoder(
        input_dim=len(feature_columns),
        latent_dim=8,
    )

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=LEARNING_RATE,
    )

    criterion = nn.MSELoss()

    train_losses = []
    validation_losses = []

    # -----------------------------------------------------
    # Training loop
    # -----------------------------------------------------

    print()
    print("=" * 65)
    print("TRAINING AUTOENCODER")
    print("=" * 65)

    for epoch in range(1, EPOCHS + 1):

        model.train()

        epoch_loss = 0.0

        for (batch,) in loader:

            optimizer.zero_grad()

            reconstructed = model(batch)

            loss = criterion(
                reconstructed,
                batch,
            )

            loss.backward()

            optimizer.step()

            epoch_loss += (
                loss.item() * len(batch)
            )

        train_loss = (
            epoch_loss / len(X_train_tensor)
        )

        # -------------------------------------------------
        # Validation
        # -------------------------------------------------

        model.eval()

        with torch.no_grad():

            validation_reconstructed = model(
                X_validation_tensor
            )

            validation_loss = criterion(
                validation_reconstructed,
                X_validation_tensor,
            ).item()

        train_losses.append(train_loss)
        validation_losses.append(validation_loss)

        if (
            epoch == 1
            or epoch % 10 == 0
            or epoch == EPOCHS
        ):
            print(
                f"Epoch {epoch:3d}/{EPOCHS} | "
                f"Train Loss: {train_loss:.6f} | "
                f"Validation Loss: {validation_loss:.6f}"
            )

    # -----------------------------------------------------
    # Calculate reconstruction errors
    # -----------------------------------------------------

    model.eval()

    with torch.no_grad():

        validation_errors = (
            model.reconstruction_error(
                X_validation_tensor,
                reduction="none",
            )
            .numpy()
        )

    return (
        model,
        scaler,
        feature_columns,
        np.asarray(train_losses),
        np.asarray(validation_losses),
        validation_errors,
    )


def threshold_summary(validation_errors: np.ndarray) -> dict:
    """The mean + 3 x std threshold, plus percentile alternatives for reference."""

    threshold = float(
        validation_errors.mean()
        + THRESHOLD_STD_MULTIPLIER * validation_errors.std()
    )

    return {
        "threshold": threshold,
        "rule": f"mean + {THRESHOLD_STD_MULTIPLIER:g} x std of validation errors",
        "description": (
            "Threshold calculated from normal validation "
            "reconstruction errors (time-based split)."
        ),
        "alternatives": {
            "p95": float(np.percentile(validation_errors, 95)),
            "p99": float(np.percentile(validation_errors, 99)),
            "max": float(validation_errors.max()),
        },
    }


# ---------------------------------------------------------
# Save artifacts
# ---------------------------------------------------------

def save_artifacts(
    model: SyscallAutoencoder,
    scaler: FeatureScaler,
    feature_columns: list[str],
    train_losses: np.ndarray,
    validation_losses: np.ndarray,
    validation_errors: np.ndarray,
    models_dir: Path = MODELS_DIR,
    results_dir: Path = RESULTS_DIR,
) -> dict:

    MODELS_DIR = models_dir
    RESULTS_DIR = results_dir

    MODELS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    torch.save(
        model.state_dict(),
        MODELS_DIR / "autoencoder.pt",
    )

    joblib.dump(
        scaler.scaler,
        MODELS_DIR / "scaler.joblib",
    )

    with open(
        MODELS_DIR / "features.json",
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            {
                "columns": feature_columns,
                "rule": (
                    "all 20 syscall-family counts, pair columns non-zero "
                    "in normal training windows, stat_04"
                ),
            },
            file,
            indent=4,
        )

    with open(
        MODELS_DIR / "threshold.json",
        "w",
        encoding="utf-8",
    ) as file:

        summary = threshold_summary(validation_errors)
        summary["final_train_loss"] = float(train_losses[-1])
        summary["final_validation_loss"] = float(validation_losses[-1])
        summary["epochs"] = len(train_losses)

        json.dump(
            summary,
            file,
            indent=4,
        )

    np.save(
        RESULTS_DIR / "train_losses.npy",
        train_losses,
    )

    np.save(
        RESULTS_DIR / "validation_losses.npy",
        validation_losses,
    )

    np.save(
        RESULTS_DIR / "validation_errors.npy",
        validation_errors,
    )

    return summary


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Train Autoencoder on normal eBPF "
            "syscall behavior."
        )
    )

    parser.add_argument(
        "csv_path",
        help="Path to normal aggregated CSV.",
    )

    parser.add_argument(
        "--models-dir",
        type=Path,
        default=MODELS_DIR,
        help="Where to save the model, scaler and threshold.",
    )

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Where to save losses and validation errors.",
    )

    args = parser.parse_args()

    set_seed()

    # -----------------------------------------------------
    # Load real project data
    # -----------------------------------------------------

    print()
    print("=" * 65)
    print("LOADING NORMAL DATA")
    print("=" * 65)

    prepared = prepare_aggregated_csv(
        args.csv_path
    )

    X = prepared.X

    start_index = prepared.metadata_columns.index("window_start_ns")
    end_index = prepared.metadata_columns.index("window_end_ns")
    window_starts = np.array(
        [int(row[start_index]) for row in prepared.metadata_rows]
    )
    window_ends = np.array(
        [int(row[end_index]) for row in prepared.metadata_rows]
    )

    print(f"Input file          : {args.csv_path}")
    print(f"Feature matrix      : {X.shape}")

    # -----------------------------------------------------
    # Train
    # -----------------------------------------------------

    (
        model,
        scaler,
        feature_columns,
        train_losses,
        validation_losses,
        validation_errors,
    ) = train_model(X, window_starts, window_ends)

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    summary = save_artifacts(
        model,
        scaler,
        feature_columns,
        train_losses,
        validation_losses,
        validation_errors,
        args.models_dir,
        args.results_dir,
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print()
    print("=" * 65)
    print("TRAINING COMPLETE")
    print("=" * 65)

    print(f"Threshold           : {summary['threshold']:.6f}  ({summary['rule']})")
    print(f"  p95 alternative   : {summary['alternatives']['p95']:.6f}")
    print(f"  p99 alternative   : {summary['alternatives']['p99']:.6f}")
    print(f"Final train loss    : {summary['final_train_loss']:.9f}")
    print(f"Final val loss      : {summary['final_validation_loss']:.9f}")

    print()
    print(f"Saved model, scaler, threshold to {args.models_dir}")
    print(f"Saved losses and validation errors to {args.results_dir}")


if __name__ == "__main__":
    main()