from __future__ import annotations

import torch
from torch import nn


class SyscallAutoencoder(nn.Module):

    def __init__(
        self,
        input_dim: int = 74,
        latent_dim: int = 8,
    ) -> None:
        super().__init__()

        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),

            nn.Linear(64, 32),
            nn.ReLU(),

            nn.Linear(32, latent_dim),
        )

        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 32),
            nn.ReLU(),

            nn.Linear(32, 64),
            nn.ReLU(),

            nn.Linear(64, input_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        latent = self.encoder(x)
        reconstructed = self.decoder(latent)
        return reconstructed

    def reconstruction_error(
        self,
        x: torch.Tensor,
        reduction: str = "none",
    ) -> torch.Tensor:

        reconstructed = self.forward(x)

        error = torch.mean(
            (x - reconstructed) ** 2,
            dim=1,
        )

        if reduction == "none":
            return error

        if reduction == "mean":
            return error.mean()

        if reduction == "sum":
            return error.sum()

        raise ValueError(
            "reduction must be one of: "
            "'none', 'mean', 'sum'"
        )