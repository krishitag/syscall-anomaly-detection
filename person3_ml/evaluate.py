"""
Evaluate the trained Autoencoder on a labelled evaluation capture.

Inputs (from Naman's evaluation run):
    data/eval.csv        normal traffic + attacks, 77-column format
    data/attack_log.csv  attack,start_ns,end_ns

Member 2 turns them into features X and labels y (1 = window overlaps an
attack).  The saved scaler and threshold come from normal.csv only, so this
script never fits anything on evaluation data.

Reports everything the paper needs in one run:
    - confusion matrix and metrics at the saved threshold
    - the same at each alternative threshold saved by training
    - precision-recall and ROC curves across all thresholds
    - windows flagged per attack
    - reconstruction error on attack vs normal windows
    - final training / validation loss
    - scoring time per window

Usage:
    python -m person3_ml.evaluate data/eval.csv data/attack_log.csv
    SYSCALL_MODELS_DIR=path/to/models python -m person3_ml.evaluate ...
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from member2.evaluation_labels import (
    AttackInterval,
    prepare_labeled_evaluation,
)
from member2.pipeline import prepare_window
from member2.schema import ALL_COLUMNS, METADATA_COLUMNS

from . import detect
from .detect import anomaly_threshold, reconstruction_errors, score_window


RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class EvaluationMetrics:
    threshold: float
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


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def attack_windows(
    metadata_rows: tuple[tuple[str, ...], ...],
    attacks: tuple[AttackInterval, ...],
) -> list[np.ndarray]:
    """Window indices each attack overlaps.

    Uses the same overlap rule as ``member2.evaluation_labels.label_windows``.
    """

    start_index = METADATA_COLUMNS.index("window_start_ns")
    end_index = METADATA_COLUMNS.index("window_end_ns")
    starts = np.array([int(row[start_index]) for row in metadata_rows])
    ends = np.array([int(row[end_index]) for row in metadata_rows])

    return [
        np.where((attack.start_ns < ends) & (attack.end_ns >= starts))[0]
        for attack in attacks
    ]


def compute_metrics(
    y_true: np.ndarray,
    errors: np.ndarray,
    threshold: float,
    per_attack: list[np.ndarray],
) -> EvaluationMetrics:
    """Window-level confusion matrix plus how many attacks raised an alert."""

    predictions = errors > threshold

    tp = int((predictions & (y_true == 1)).sum())
    fp = int((predictions & (y_true == 0)).sum())
    tn = int((~predictions & (y_true == 0)).sum())
    fn = int((~predictions & (y_true == 1)).sum())

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)

    return EvaluationMetrics(
        threshold=threshold,
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
        attacks_detected=sum(bool(predictions[w].any()) for w in per_attack),
        attacks_total=len(per_attack),
    )


def error_summary(errors: np.ndarray, y_true: np.ndarray) -> dict:
    """Reconstruction error on attack vs normal windows.

    The ratio uses medians: one extreme attack window can dominate a mean.
    """

    summary = {}
    for name, mask in (("attack", y_true == 1), ("normal", y_true == 0)):
        summary[name] = {
            "mean": float(errors[mask].mean()),
            "median": float(np.median(errors[mask])),
            "max": float(errors[mask].max()),
        }
    summary["median_ratio"] = _ratio(
        summary["attack"]["median"],
        summary["normal"]["median"],
    )
    return summary


def curves(errors: np.ndarray, y_true: np.ndarray, results_dir: Path) -> dict:
    """Precision-recall and ROC curves across every threshold; saves a plot."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import (
        average_precision_score,
        precision_recall_curve,
        roc_auc_score,
        roc_curve,
    )

    precision, recall, _ = precision_recall_curve(y_true, errors)
    fpr, tpr, _ = roc_curve(y_true, errors)
    average_precision = float(average_precision_score(y_true, errors))
    roc_auc = float(roc_auc_score(y_true, errors))

    figure, (pr_axis, roc_axis) = plt.subplots(1, 2, figsize=(11, 4.5))

    pr_axis.plot(recall, precision)
    pr_axis.set_xlabel("Recall")
    pr_axis.set_ylabel("Precision")
    pr_axis.set_title(f"Precision-Recall (AP = {average_precision:.3f})")
    pr_axis.grid(True, alpha=0.3)

    roc_axis.plot(fpr, tpr)
    roc_axis.plot([0, 1], [0, 1], linestyle="--", alpha=0.5)
    roc_axis.set_xlabel("False positive rate")
    roc_axis.set_ylabel("True positive rate")
    roc_axis.set_title(f"ROC (AUC = {roc_auc:.3f})")
    roc_axis.grid(True, alpha=0.3)

    figure.tight_layout()
    output = results_dir / "pr_roc_curves.png"
    figure.savefig(output, dpi=300, bbox_inches="tight")
    plt.close(figure)

    return {
        "average_precision": average_precision,
        "roc_auc": roc_auc,
        "plot": str(output),
    }


def scoring_time_ms(eval_csv: str | Path, repeats: int = 5) -> dict:
    """Time prepare_window + score_window for single windows, as the live demo does."""

    import csv

    with open(eval_csv, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = [{column: row[column] for column in ALL_COLUMNS} for row in reader]

    score_window(prepare_window(rows[0]))  # load the model before timing

    timings = []
    for _ in range(repeats):
        for row in rows:
            start = time.perf_counter()
            score_window(prepare_window(row))
            timings.append((time.perf_counter() - start) * 1000)

    timings = np.array(timings)
    return {
        "calls": len(timings),
        "median_ms": float(np.median(timings)),
        "p99_ms": float(np.percentile(timings, 99)),
        "max_ms": float(timings.max()),
    }


def load_training_summary() -> dict:
    """Threshold rule, alternatives and final losses saved by training."""

    with open(detect.MODELS_DIR / "threshold.json", "r", encoding="utf-8") as file:
        return json.load(file)


def evaluate(eval_csv: str | Path, attack_log: str | Path, results_dir: Path):

    labeled = prepare_labeled_evaluation(eval_csv, attack_log)
    y_true = labeled.y

    errors = reconstruction_errors(labeled.prepared.X)
    threshold = anomaly_threshold()
    per_attack = attack_windows(labeled.prepared.metadata_rows, labeled.attacks)
    training = load_training_summary()

    predictions = errors > threshold
    operating_points = {"saved": compute_metrics(y_true, errors, threshold, per_attack)}
    for name, value in training.get("alternatives", {}).items():
        operating_points[name] = compute_metrics(y_true, errors, value, per_attack)

    return {
        "model_dir": str(detect.MODELS_DIR),
        "threshold_rule": training.get("rule", "95th percentile of validation errors"),
        "operating_points": {k: asdict(v) for k, v in operating_points.items()},
        "per_attack": [
            {
                "attack": attack.attack,
                "windows": windows.tolist(),
                "flagged": int(predictions[windows].sum()),
                "detected": bool(predictions[windows].any()),
            }
            for attack, windows in zip(labeled.attacks, per_attack)
        ],
        "reconstruction_error": error_summary(errors, y_true),
        "curves": curves(errors, y_true, results_dir),
        "training": {
            key: training[key]
            for key in ("epochs", "final_train_loss", "final_validation_loss")
            if key in training
        },
        "scoring_time": scoring_time_ms(eval_csv),
    }


def _print_metrics(name: str, m: dict) -> None:
    print(
        f"  {name:<8} threshold={m['threshold']:.6g}  "
        f"TP={m['true_positives']} FP={m['false_positives']} "
        f"TN={m['true_negatives']} FN={m['false_negatives']}  "
        f"P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1']:.4f} "
        f"FPR={m['false_positive_rate']:.4f}  "
        f"attacks={m['attacks_detected']}/{m['attacks_total']}"
    )


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

    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Where to save evaluation_metrics.json and the curve plot.",
    )

    args = parser.parse_args()
    args.results_dir.mkdir(parents=True, exist_ok=True)

    report = evaluate(args.eval_csv, args.attack_log, args.results_dir)
    saved = report["operating_points"]["saved"]

    print()
    print("=" * 65)
    print("EVALUATION")
    print("=" * 65)
    print(f"Model               : {report['model_dir']}")
    print(f"Threshold rule      : {report['threshold_rule']}")
    print(f"Windows             : {saved['windows']}")
    print(f"Attack windows      : {saved['attack_windows']}")

    print()
    print("Operating points:")
    for name, metrics in report["operating_points"].items():
        _print_metrics(name, metrics)

    curve = report["curves"]
    print()
    print(f"Average precision   : {curve['average_precision']:.4f}")
    print(f"ROC AUC             : {curve['roc_auc']:.4f}")
    print(f"Curve plot          : {curve['plot']}")

    print()
    print("Per attack (saved threshold):")
    for attack in report["per_attack"]:
        print(
            f"  {attack['attack']:<16}"
            f"{attack['flagged']}/{len(attack['windows'])} windows flagged  "
            f"{'DETECTED' if attack['detected'] else 'MISSED'}"
        )

    errors = report["reconstruction_error"]
    print()
    print("Reconstruction error:")
    for name in ("attack", "normal"):
        e = errors[name]
        print(
            f"  {name:<7} mean={e['mean']:.6g} "
            f"median={e['median']:.6g} max={e['max']:.6g}"
        )
    print(f"  median attack / median normal = {errors['median_ratio']:.6g}")

    training = report["training"]
    if training:
        print()
        print(
            f"Training            : {training.get('epochs')} epochs, "
            f"final train loss {training.get('final_train_loss'):.9f}, "
            f"final val loss {training.get('final_validation_loss'):.9f}"
        )

    timing = report["scoring_time"]
    print(
        f"Scoring time        : median {timing['median_ms']:.4f} ms, "
        f"p99 {timing['p99_ms']:.4f} ms per window ({timing['calls']} calls)"
    )

    output = args.results_dir / "evaluation_metrics.json"
    with open(output, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4)

    print()
    print(f"Saved metrics to {output}")


if __name__ == "__main__":
    main()
