"""
Plot reconstruction error over an evaluation capture (the paper's Fig. 3).

Each point is one window, placed at its end time (when the tracer emits it).
Attack intervals are shaded and numbered, the saved threshold is dashed, and
the largest normal validation error is dotted.

Usage:
    python -m person3_ml.plot_timeline data/eval.csv data/attack_log.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from member2.evaluation_labels import prepare_labeled_evaluation

from . import detect
from .detect import anomaly_threshold, reconstruction_errors


RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Short attacks are shaded at least this wide so they stay visible.
MIN_SHADE_SECONDS = 1.0


def plot_timeline(eval_csv, attack_log, output: Path) -> Path:

    labeled = prepare_labeled_evaluation(eval_csv, attack_log)
    errors = reconstruction_errors(labeled.prepared.X)
    threshold = anomaly_threshold()

    with open(detect.MODELS_DIR / "threshold.json", "r", encoding="utf-8") as file:
        saved = json.load(file)
    rule = saved.get("rule", "saved threshold")
    validation_max = saved.get("alternatives", {}).get("max")

    starts = np.array([int(row[1]) for row in labeled.prepared.metadata_rows])
    ends = np.array([int(row[2]) for row in labeled.prepared.metadata_rows])
    origin = starts.min()
    seconds = (ends - origin) / 1e9

    figure, axis = plt.subplots(figsize=(10, 4.5))

    for number, attack in enumerate(labeled.attacks, start=1):
        left = (attack.start_ns - origin) / 1e9
        right = max((attack.end_ns - origin) / 1e9, left + MIN_SHADE_SECONDS)
        axis.axvspan(left, right, color="tab:red", alpha=0.2, linewidth=0)
        axis.text(
            left,
            1.02,
            str(number),
            transform=axis.get_xaxis_transform(),
            color="tab:red",
            fontweight="bold",
        )

    axis.plot(seconds, errors, marker="o", markersize=2.5, linewidth=1)

    flagged = errors > threshold
    axis.scatter(
        seconds[flagged],
        errors[flagged],
        s=18,
        color="tab:red",
        zorder=3,
        label="flagged",
    )

    axis.axhline(
        threshold,
        linestyle="--",
        color="black",
        linewidth=1,
        label=f"threshold ({rule})",
    )
    if validation_max is not None:
        axis.axhline(
            validation_max,
            linestyle=":",
            color="gray",
            linewidth=1,
            label="max validation error",
        )

    axis.set_yscale("log")
    axis.set_xlabel("Time into evaluation capture (s)")
    axis.set_ylabel("Reconstruction error")
    axis.legend(loc="upper right", fontsize=8)
    axis.grid(True, alpha=0.3)

    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=300, bbox_inches="tight")
    plt.close(figure)

    return output


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Plot reconstruction error over an evaluation capture."
    )
    parser.add_argument("eval_csv", help="Evaluation CSV.")
    parser.add_argument("attack_log", help="Attack log CSV.")
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_DIR / "eval_error_timeline.png",
        help="Where to save the plot.",
    )
    args = parser.parse_args()

    print(f"Saved: {plot_timeline(args.eval_csv, args.attack_log, args.output)}")
    print("Shaded bands are numbered in attack-log order; name them in the caption.")


if __name__ == "__main__":
    main()
