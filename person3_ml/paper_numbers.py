"""
Recompute the paper numbers that evaluate.py and baselines.py don't save.

Writes person3_ml/results/paper_numbers.json with:
    - detection delay per attack, with mean and max
    - separation: windows containing security-relevant syscalls vs normal windows
    - the false-positive windows and what is in them
    - pair-selection check: re-score with the pair columns that never occur in
      normal training data set to zero
    - training-capture summary (Table III)
    - per-window transfer counts for per-event export (Table VIII)

Usage:
    python -m person3_ml.paper_numbers data/normal.csv data/eval.csv data/attack_log.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from member2.evaluation_labels import prepare_labeled_evaluation
from member2.pipeline import prepare_aggregated_csv
from member2.schema import FEATURE_COLUMNS, PAIR_COUNT_COLUMNS, SYSCALL_COUNT_COLUMNS

from .detect import anomaly_threshold, reconstruction_errors
from .evaluate import RESULTS_DIR, attack_windows, compute_metrics


# Vocabulary order from docs/VOCAB.md section 4.
FAMILIES = [
    "read", "write", "recvfrom", "openat", "close", "mmap", "munmap", "execve",
    "epoll_wait", "clone", "connect", "accept4", "socket", "setns", "unshare",
    "ptrace", "fchmodat", "fchownat", "kill", "sendfile",
]
SECURITY_FAMILIES = {
    "execve", "clone", "connect", "socket", "setns",
    "unshare", "ptrace", "fchmodat", "fchownat", "kill",
}

SYSCALL_INDEXES = [FEATURE_COLUMNS.index(c) for c in SYSCALL_COUNT_COLUMNS]
PAIR_INDEXES = [FEATURE_COLUMNS.index(c) for c in PAIR_COUNT_COLUMNS]
SECURITY_INDEXES = [
    SYSCALL_INDEXES[i] for i, name in enumerate(FAMILIES) if name in SECURITY_FAMILIES
]


def _times(prepared) -> tuple[np.ndarray, np.ndarray]:
    starts = np.array([int(row[1]) for row in prepared.metadata_rows])
    ends = np.array([int(row[2]) for row in prepared.metadata_rows])
    return starts, ends


def detection_delays(labeled, flagged: np.ndarray) -> dict:
    """Attack start to the end of the first flagged window (same rule as analyze.py)."""

    _, ends = _times(labeled.prepared)
    delays = {}
    for attack in labeled.attacks:
        candidates = np.where((ends >= attack.start_ns) & flagged)[0]
        delays[attack.attack] = (
            float((ends[candidates[0]] - attack.start_ns) / 1e9) if len(candidates) else None
        )
    found = [d for d in delays.values() if d is not None]
    return {
        "per_attack_s": delays,
        "mean_s": float(np.mean(found)) if found else None,
        "max_s": float(np.max(found)) if found else None,
    }


def separation(X: np.ndarray, y: np.ndarray, errors: np.ndarray) -> dict:
    """Windows with any security-relevant syscall vs normal windows."""

    has_security = X[:, SECURITY_INDEXES].sum(axis=1) > 0
    attack_with_calls = has_security & (y == 1)
    normal_max = float(errors[y == 0].max())
    attack_min = float(errors[attack_with_calls].min())
    return {
        "windows_with_security_calls": int(has_security.sum()),
        "of_which_labelled_attack": int(attack_with_calls.sum()),
        "normal_windows_with_security_calls": int((has_security & (y == 0)).sum()),
        "min_error_attack_windows_with_calls": attack_min,
        "max_error_normal_windows": normal_max,
        "ratio": attack_min / normal_max,
    }


def false_positives(X, y, errors, threshold) -> list[dict]:
    """What each false-positive window contains."""

    normal_mean_calls = float(X[y == 0][:, SYSCALL_INDEXES].sum(axis=1).mean())
    windows = []
    for index in np.where((errors > threshold) & (y == 0))[0]:
        nonzero_pairs = [
            PAIR_COUNT_COLUMNS[k] for k, column in enumerate(PAIR_INDEXES)
            if X[index, column] > 0
        ]
        windows.append({
            "window": int(index),
            "error": float(errors[index]),
            "vocab_calls": int(X[index, SYSCALL_INDEXES].sum()),
            "mean_vocab_calls_per_normal_window": normal_mean_calls,
            "nonzero_pair_columns": nonzero_pairs,
        })
    return windows


def pair_selection_check(X_normal, labeled, threshold) -> dict:
    """Re-score eval with every pair column that is zero throughout normal.csv set to 0."""

    dead = [
        column for column in PAIR_INDEXES if X_normal[:, column].max() == 0
    ]
    X = labeled.prepared.X.copy()
    X[:, dead] = 0
    per_attack = attack_windows(labeled.prepared.metadata_rows, labeled.attacks)
    metrics = compute_metrics(labeled.y, reconstruction_errors(X), threshold, per_attack)
    return {
        "zeroed_pair_columns": [FEATURE_COLUMNS[c] for c in dead],
        "metrics": vars(metrics),
    }


def training_summary(X_normal: np.ndarray) -> dict:
    """Table III: family counts in the normal training capture."""

    counts = X_normal[:, SYSCALL_INDEXES]
    per_family = {
        FAMILIES[i]: {"total": int(counts[:, i].sum()), "max_per_window": int(counts[:, i].max())}
        for i in range(len(FAMILIES)) if counts[:, i].sum() > 0
    }
    return {
        "windows": len(X_normal),
        "idle_windows": int((X_normal.sum(axis=1) == 0).sum()),
        "families_ever_nonzero": len(per_family),
        "security_families_ever_nonzero": sum(1 for f in per_family if f in SECURITY_FAMILIES),
        "pair_columns_ever_nonzero": int((X_normal[:, PAIR_INDEXES].sum(axis=0) > 0).sum()),
        "per_family": per_family,
        "vocab_calls_summed_over_windows": int(counts.sum()),
        "max_vocab_calls_per_window": int(counts.sum(axis=1).max()),
        "note": "Windows overlap (2 s span, 1 s step), so sums over windows count each second twice.",
    }


def transfer_counts(X_normal: np.ndarray) -> dict:
    """Table VIII: records per window under per-event export (vocabulary calls only, a lower bound)."""

    per_window = X_normal[:, SYSCALL_INDEXES].sum(axis=1)
    return {
        "per_event_records_per_window": {
            "mean": float(per_window.mean()),
            "median": float(np.median(per_window)),
            "p95": float(np.percentile(per_window, 95)),
            "max": int(per_window.max()),
            "idle_windows": int((per_window == 0).sum()),
        },
        "in_kernel_reads_per_window": 1,
        "note": "Lower bound: counts only the 20 vocabulary families. Per 2 s window.",
    }


def main() -> None:

    parser = argparse.ArgumentParser(description="Recompute the remaining paper numbers.")
    parser.add_argument("normal_csv")
    parser.add_argument("eval_csv")
    parser.add_argument("attack_log")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    X_normal = prepare_aggregated_csv(args.normal_csv).X
    labeled = prepare_labeled_evaluation(args.eval_csv, args.attack_log)
    X, y = labeled.prepared.X, labeled.y
    errors = reconstruction_errors(X)
    threshold = anomaly_threshold()

    report = {
        "threshold": threshold,
        "detection_delay": detection_delays(labeled, errors > threshold),
        "separation": separation(X, y, errors),
        "false_positives": false_positives(X, y, errors, threshold),
        "pair_selection_check": pair_selection_check(X_normal, labeled, threshold),
        "training_capture": training_summary(X_normal),
        "transfer_counts": transfer_counts(X_normal),
    }

    args.results_dir.mkdir(parents=True, exist_ok=True)
    output = args.results_dir / "paper_numbers.json"
    with open(output, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4)

    delay = report["detection_delay"]
    sep = report["separation"]
    check = report["pair_selection_check"]["metrics"]
    print(f"Detection delay     : {delay['per_attack_s']}  mean {delay['mean_s']:.3f} s, max {delay['max_s']:.3f} s")
    print(f"Separation          : attack windows with calls >= {sep['min_error_attack_windows_with_calls']:.4g}, "
          f"normal max {sep['max_error_normal_windows']:.4g} ({sep['ratio']:.0f}x)")
    print(f"False positives     : {[(w['window'], w['vocab_calls'], w['nonzero_pair_columns']) for w in report['false_positives']]}")
    print(f"Pair-selection check: zeroed {len(report['pair_selection_check']['zeroed_pair_columns'])} columns -> "
          f"TP {check['true_positives']} FP {check['false_positives']} attacks {check['attacks_detected']}/5")
    print(f"Training capture    : {report['training_capture']['windows']} windows, "
          f"{report['training_capture']['idle_windows']} idle, max {report['training_capture']['max_vocab_calls_per_window']} calls/window")
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
