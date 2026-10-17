"""
Compare the Autoencoder with non-deep baselines on identical features.

Isolation Forest and One-Class SVM are fitted on the same normal training
windows (same time-based split, same scaler) as the Autoencoder.  Each
baseline's thresholds come from its scores on the normal validation windows,
using the same rules as training: mean + 3 x std, p95 and p99.  Evaluation
data is only scored, never fitted on.

Usage:
    python -m person3_ml.baselines data/normal.csv data/eval.csv data/attack_log.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.svm import OneClassSVM

from member2.evaluation_labels import prepare_labeled_evaluation
from member2.pipeline import prepare_aggregated_csv

from . import detect
from .evaluate import RESULTS_DIR, attack_windows, compute_metrics
from .train import RANDOM_SEED, THRESHOLD_STD_MULTIPLIER, split_normal_data


def _window_times(prepared) -> tuple[np.ndarray, np.ndarray]:
    start_index = prepared.metadata_columns.index("window_start_ns")
    end_index = prepared.metadata_columns.index("window_end_ns")
    starts = np.array([int(row[start_index]) for row in prepared.metadata_rows])
    ends = np.array([int(row[end_index]) for row in prepared.metadata_rows])
    return starts, ends


def _thresholds(validation_scores: np.ndarray) -> dict[str, float]:
    return {
        "mean+3std": float(
            validation_scores.mean()
            + THRESHOLD_STD_MULTIPLIER * validation_scores.std()
        ),
        "p95": float(np.percentile(validation_scores, 95)),
        "p99": float(np.percentile(validation_scores, 99)),
    }


def run_baselines(normal_csv, eval_csv, attack_log) -> dict:

    normal = prepare_aggregated_csv(normal_csv)
    X_train, X_validation = split_normal_data(normal.X, *_window_times(normal))

    labeled = prepare_labeled_evaluation(eval_csv, attack_log)
    y_true = labeled.y
    per_attack = attack_windows(labeled.prepared.metadata_rows, labeled.attacks)

    # The Autoencoder's scaler, fitted on the same training windows.
    scaler = joblib.load(detect.MODELS_DIR / "scaler.joblib")
    train_scaled = scaler.transform(X_train)
    validation_scaled = scaler.transform(X_validation)
    eval_scaled = scaler.transform(labeled.prepared.X)

    models = {
        "isolation_forest": IsolationForest(
            n_estimators=100,
            random_state=RANDOM_SEED,
        ),
        "one_class_svm": OneClassSVM(
            kernel="rbf",
            nu=0.05,
            gamma="scale",
        ),
    }

    report = {}
    for name, model in models.items():
        model.fit(train_scaled)

        # score_samples is higher for normal points; negate so higher = anomalous.
        validation_scores = -model.score_samples(validation_scaled)
        eval_scores = -model.score_samples(eval_scaled)

        report[name] = {
            "average_precision": float(average_precision_score(y_true, eval_scores)),
            "roc_auc": float(roc_auc_score(y_true, eval_scores)),
            "operating_points": {
                rule: vars(compute_metrics(y_true, eval_scores, value, per_attack))
                for rule, value in _thresholds(validation_scores).items()
            },
        }

    return report


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Isolation Forest and One-Class SVM baselines."
    )
    parser.add_argument("normal_csv", help="Normal training CSV.")
    parser.add_argument("eval_csv", help="Evaluation CSV.")
    parser.add_argument("attack_log", help="Attack log CSV.")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Where to save baseline_metrics.json.",
    )
    args = parser.parse_args()

    report = run_baselines(args.normal_csv, args.eval_csv, args.attack_log)

    print()
    print("=" * 65)
    print("BASELINES (same features, split and scaler as the Autoencoder)")
    print("=" * 65)
    for name, result in report.items():
        print(
            f"\n{name}: AP={result['average_precision']:.4f} "
            f"ROC AUC={result['roc_auc']:.4f}"
        )
        for rule, m in result["operating_points"].items():
            print(
                f"  {rule:<10} TP={m['true_positives']} FP={m['false_positives']} "
                f"TN={m['true_negatives']} FN={m['false_negatives']}  "
                f"P={m['precision']:.4f} R={m['recall']:.4f} F1={m['f1']:.4f} "
                f"FPR={m['false_positive_rate']:.4f}  "
                f"attacks={m['attacks_detected']}/{m['attacks_total']}"
            )

    args.results_dir.mkdir(parents=True, exist_ok=True)
    output = args.results_dir / "baseline_metrics.json"
    with open(output, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4)
    print(f"\nSaved baselines to {output}")


if __name__ == "__main__":
    main()
