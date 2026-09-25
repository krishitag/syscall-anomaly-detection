"""
Evaluate the trained Autoencoder on a labelled evaluation capture.

Inputs (from Naman's evaluation run):
    data/eval.csv        normal traffic + attacks, 77-column format
    data/attack_log.csv  attack,start_ns,end_ns

Member 2 turns them into features X and labels y (1 = window overlaps an
attack).  The saved scaler and threshold come from normal.csv only, so this
script never fits anything on evaluation data.

Usage:
    python -m person3_ml.evaluate data/eval.csv data/attack_log.csv
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from member2.evaluation_labels import (
    AttackInterval,
    prepare_labeled_evaluation,
)
from member2.schema import METADATA_COLUMNS

from .detect import anomaly_threshold, reconstruction_errors


RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class EvaluationMetrics:
    windows: int
    attack_windows: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    attacks_detected: int
    attacks_total: int


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def compute_metrics(
    y_true: np.ndarray,
    predictions: np.ndarray,
    attack_detected: list[bool],
) -> EvaluationMetrics:
    """Window-level confusion matrix plus how many attacks raised an alert."""

    tp = int(((predictions == 1) & (y_true == 1)).sum())
    fp = int(((predictions == 1) & (y_true == 0)).sum())
    tn = int(((predictions == 0) & (y_true == 0)).sum())
    fn = int(((predictions == 0) & (y_true == 1)).sum())

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)

    return EvaluationMetrics(
        windows=len(y_true),
        attack_windows=int(y_true.sum()),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall),
        false_positive_rate=_ratio(fp, fp + tn),
        attacks_detected=sum(attack_detected),
        attacks_total=len(attack_detected),
    )


def detected_attacks(
    metadata_rows: tuple[tuple[str, ...], ...],
    predictions: np.ndarray,
    attacks: tuple[AttackInterval, ...],
) -> list[bool]:
    """An attack counts as detected if any window it overlaps is flagged.

    Uses the same overlap rule as ``member2.evaluation_labels.label_windows``.
    """

    start_index = METADATA_COLUMNS.index("window_start_ns")
    end_index = METADATA_COLUMNS.index("window_end_ns")
    starts = np.array([int(row[start_index]) for row in metadata_rows])
    ends = np.array([int(row[end_index]) for row in metadata_rows])

    return [
        bool(
            predictions[
                (attack.start_ns < ends) & (attack.end_ns >= starts)
            ].any()
        )
        for attack in attacks
    ]


def evaluate(eval_csv: str | Path, attack_log: str | Path):

    labeled = prepare_labeled_evaluation(eval_csv, attack_log)

    errors = reconstruction_errors(labeled.prepared.X)
    threshold = anomaly_threshold()
    predictions = (errors > threshold).astype(int)

    attack_detected = detected_attacks(
        labeled.prepared.metadata_rows,
        predictions,
        labeled.attacks,
    )

    metrics = compute_metrics(labeled.y, predictions, attack_detected)

    return metrics, labeled.attacks, attack_detected, threshold


def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the trained Autoencoder against "
            "labelled attack windows."
        )
    )

    parser.add_argument(
        "eval_csv",
        help="Evaluation aggregated CSV (normal traffic + attacks).",
    )

    parser.add_argument(
        "attack_log",
        help="Attack log CSV: attack,start_ns,end_ns.",
    )

    args = parser.parse_args()

    metrics, attacks, attack_detected, threshold = evaluate(
        args.eval_csv,
        args.attack_log,
    )

    print()
    print("=" * 65)
    print("EVALUATION")
    print("=" * 65)
    print(f"Threshold           : {threshold:.6f}")
    print(f"Windows             : {metrics.windows}")
    print(f"Attack windows      : {metrics.attack_windows}")
    print()
    print(f"True positives      : {metrics.true_positives}")
    print(f"False positives     : {metrics.false_positives}")
    print(f"True negatives      : {metrics.true_negatives}")
    print(f"False negatives     : {metrics.false_negatives}")
    print()
    print(f"Precision           : {metrics.precision:.3f}")
    print(f"Recall              : {metrics.recall:.3f}")
    print(f"F1                  : {metrics.f1:.3f}")
    print(f"False positive rate : {metrics.false_positive_rate:.3f}")
    print()
    print(
        f"Attacks detected    : "
        f"{metrics.attacks_detected}/{metrics.attacks_total}"
    )

    for attack, detected in zip(attacks, attack_detected):
        print(
            f"  {attack.attack:<20}"
            f"{'DETECTED' if detected else 'MISSED'}"
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / "evaluation_metrics.json"

    with open(output, "w", encoding="utf-8") as file:
        json.dump(
            {
                "threshold": threshold,
                **asdict(metrics),
                "attacks": [
                    {"attack": attack.attack, "detected": detected}
                    for attack, detected in zip(attacks, attack_detected)
                ],
            },
            file,
            indent=4,
        )

    print()
    print(f"Saved metrics to {output}")


if __name__ == "__main__":
    main()
