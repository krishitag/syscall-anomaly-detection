from pathlib import Path

import json

import matplotlib.pyplot as plt
import numpy as np
import torch

from member2.pipeline import prepare_aggregated_csv
from person3_ml.autoencoder import SyscallAutoencoder
import joblib


RESULTS_DIR = Path("person3_ml/results")
MODELS_DIR = Path("person3_ml/models")


def plot_training_loss():
    train_losses = np.load(
        RESULTS_DIR / "train_losses.npy"
    )

    validation_losses = np.load(
        RESULTS_DIR / "validation_losses.npy"
    )

    epochs = np.arange(1, len(train_losses) + 1)

    plt.figure(figsize=(9, 5))

    plt.plot(
        epochs,
        train_losses,
        label="Training Loss",
    )

    plt.plot(
        epochs,
        validation_losses,
        label="Validation Loss",
    )

    plt.xlabel("Epoch")
    plt.ylabel("Mean Squared Error")
    plt.title("Autoencoder Training and Validation Loss")
    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.tight_layout()

    output = RESULTS_DIR / "training_loss.png"

    plt.savefig(
        output,
        dpi=300,
        bbox_inches="tight",
    )

    plt.show()

    print(f"Saved: {output}")


def calculate_reconstruction_errors():

    prepared = prepare_aggregated_csv(
        "data/normal.csv"
    )

    X = prepared.X

    scaler = joblib.load(
        MODELS_DIR / "scaler.joblib"
    )

    with open(
        MODELS_DIR / "threshold.json",
        "r",
        encoding="utf-8",
    ) as file:
        threshold = float(
            json.load(file)["threshold"]
        )

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

    X_scaled = scaler.transform(X)

    X_tensor = torch.tensor(
        X_scaled,
        dtype=torch.float32,
    )

    with torch.no_grad():

        errors = (
            model.reconstruction_error(
                X_tensor,
                reduction="none",
            )
            .numpy()
        )

    return errors, threshold


def plot_reconstruction_errors():

    errors, threshold = (
        calculate_reconstruction_errors()
    )

    plt.figure(figsize=(9, 5))

    plt.hist(
        errors,
        bins=30,
        alpha=0.8,
    )

    plt.axvline(
        threshold,
        linestyle="--",
        linewidth=2,
        label=f"Threshold = {threshold:.6f}",
    )

    plt.xlabel("Reconstruction Error")
    plt.ylabel("Number of Windows")
    plt.title(
        "Reconstruction Error Distribution - Normal Data"
    )

    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.tight_layout()

    output = (
        RESULTS_DIR /
        "reconstruction_error_distribution.png"
    )

    plt.savefig(
        output,
        dpi=300,
        bbox_inches="tight",
    )

    plt.show()

    print(f"Saved: {output}")


if __name__ == "__main__":

    plot_training_loss()

    plot_reconstruction_errors()