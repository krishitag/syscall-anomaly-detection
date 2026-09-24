"""
Train the syscall anomaly detection Autoencoder.

Training data:
    data/normal.csv

The model learns normal Docker container syscall behavior.
Anomaly detection is based on reconstruction error.
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
from .preprocessing import FeatureScaler


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

RANDOM_SEED = 42

BATCH_SIZE = 32
EPOCHS = 100
LEARNING_RATE = 1e-3

VALIDATION_RATIO = 0.20

THRESHOLD_PERCENTILE = 95.0

MODELS_DIR = Path("person3_ml/models")
RESULTS_DIR = Path("person3_ml/results")


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
    validation_ratio: float = VALIDATION_RATIO,
) -> tuple[np.ndarray, np.ndarray]:

    if X.ndim != 2 or X.shape[1] != 74:
        raise ValueError(
            f"Expected X shape (N, 74), got {X.shape}"
        )

    if len(X) < 10:
        raise ValueError(
            "At least 10 windows are required for training."
        )

    rng = np.random.default_rng(RANDOM_SEED)

    indices = rng.permutation(len(X))

    validation_size = max(
        1,
        int(len(X) * validation_ratio),
    )

    validation_indices = indices[:validation_size]
    training_indices = indices[validation_size:]

    X_train = X[training_indices]
    X_validation = X[validation_indices]

    return X_train, X_validation


# ---------------------------------------------------------
# Training
# ---------------------------------------------------------

def train_model(
    X: np.ndarray,
) -> tuple[
    SyscallAutoencoder,
    FeatureScaler,
    np.ndarray,
    np.ndarray,
    float,
]:

    X_train, X_validation = split_normal_data(X)

    print()
    print("=" * 65)
    print("DATA SPLIT")
    print("=" * 65)
    print(f"Total windows       : {len(X)}")
    print(f"Training windows    : {len(X_train)}")
    print(f"Validation windows  : {len(X_validation)}")

    # -----------------------------------------------------
    # Fit scaler ONLY on training data
    # -----------------------------------------------------

    scaler = FeatureScaler.create()

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
        input_dim=74,
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

    threshold = float(
        np.percentile(
            validation_errors,
            THRESHOLD_PERCENTILE,
        )
    )

    return (
        model,
        scaler,
        np.asarray(train_losses),
        np.asarray(validation_losses),
        threshold,
    )


# ---------------------------------------------------------
# Save artifacts
# ---------------------------------------------------------

def save_artifacts(
    model: SyscallAutoencoder,
    scaler: FeatureScaler,
    train_losses: np.ndarray,
    validation_losses: np.ndarray,
    threshold: float,
) -> None:

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
        MODELS_DIR / "threshold.json",
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            {
                "threshold": threshold,
                "percentile": THRESHOLD_PERCENTILE,
                "description": (
                    "Threshold calculated from "
                    "normal validation reconstruction errors."
                ),
            },
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

    print(f"Input file          : {args.csv_path}")
    print(f"Feature matrix      : {X.shape}")

    # -----------------------------------------------------
    # Train
    # -----------------------------------------------------

    (
        model,
        scaler,
        train_losses,
        validation_losses,
        threshold,
    ) = train_model(X)

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    save_artifacts(
        model,
        scaler,
        train_losses,
        validation_losses,
        threshold,
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print()
    print("=" * 65)
    print("TRAINING COMPLETE")
    print("=" * 65)

    print(f"Threshold           : {threshold:.6f}")

    print()
    print("Saved artifacts:")

    print(
        "  person3_ml/models/autoencoder.pt"
    )

    print(
        "  person3_ml/models/scaler.joblib"
    )

    print(
        "  person3_ml/models/threshold.json"
    )

    print()
    print("Saved training results:")

    print(
        "  person3_ml/results/train_losses.npy"
    )

    print(
        "  person3_ml/results/validation_losses.npy"
    )


if __name__ == "__main__":
    main()