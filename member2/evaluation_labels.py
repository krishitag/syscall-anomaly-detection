"""Evaluation labels, kept separate from the 77-column model contract.

Naman's evaluation capture arrives as two files: ``eval.csv`` in the normal
77-column format, and ``attack_log.csv`` (``attack,start_ns,end_ns``) on the
same Unix-epoch nanosecond clock.  :func:`prepare_labeled_evaluation` turns
them into ``X`` plus a 0/1 label per window.  Labels never enter ``X``.

:func:`separate_evaluation_labels` covers the other case: a CSV that already
carries one extra, explicitly named label column.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from .csv_loader import LoadedAggregatedCsv
from .pipeline import PreparedAggregatedInput, prepare_aggregated_csv
from .schema import ALL_COLUMNS, METADATA_COLUMNS

ATTACK_LOG_COLUMNS = ("attack", "start_ns", "end_ns")


@dataclass(frozen=True)
class AttackInterval:
    """One simulated attack from Naman's attack log, in Unix-epoch ns."""

    attack: str
    start_ns: int
    end_ns: int


@dataclass(frozen=True)
class LabeledEvaluationInput:
    """A prepared evaluation CSV and its parallel 0/1 labels.

    ``y[n]`` is the label for ``prepared.X[n]``: 1 if that window overlaps any
    attack in ``attacks``, otherwise 0.
    """

    prepared: PreparedAggregatedInput
    y: NDArray[np.int64]
    attacks: tuple[AttackInterval, ...]


def load_attack_log(input_path: str | Path) -> tuple[AttackInterval, ...]:
    """Read ``attack_log.csv`` and check each interval is well formed."""
    source_path = Path(input_path)
    with source_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file, strict=True)
        header = tuple(next(reader, ()))
        if header != ATTACK_LOG_COLUMNS:
            raise ValueError(
                f"attack log header must be {','.join(ATTACK_LOG_COLUMNS)}; got {','.join(header)}"
            )

        attacks: list[AttackInterval] = []
        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(ATTACK_LOG_COLUMNS):
                raise ValueError(f"attack log row {row_number}: expected 3 fields")
            name, start_text, end_text = row
            try:
                start_ns, end_ns = int(start_text), int(end_text)
            except ValueError as error:
                raise ValueError(
                    f"attack log row {row_number}: start_ns and end_ns must be integers"
                ) from error
            if end_ns <= start_ns:
                raise ValueError(f"attack log row {row_number}: end_ns must be after start_ns")
            attacks.append(AttackInterval(name, start_ns, end_ns))

    return tuple(attacks)


def label_windows(
    prepared: PreparedAggregatedInput,
    attacks: tuple[AttackInterval, ...],
) -> NDArray[np.int64]:
    """Return 1 for each window that overlaps any attack, otherwise 0.

    Consecutive tracer windows share a boundary (one window's end is the next
    one's start), so a window covers ``[start, end)``.  An attack that starts
    exactly on a boundary therefore labels only the window it starts in.  An
    attack that straddles a boundary labels both windows.  The attack log has
    no ``cgroup_id``, so every container's window in that time range is
    labelled.

    Raises ``ValueError`` if an attack overlaps no window at all, which
    usually means the two files come from different captures or clocks.
    """
    start_index = prepared.metadata_columns.index(METADATA_COLUMNS[1])
    end_index = prepared.metadata_columns.index(METADATA_COLUMNS[2])
    starts = np.array([int(row[start_index]) for row in prepared.metadata_rows], dtype=np.int64)
    ends = np.array([int(row[end_index]) for row in prepared.metadata_rows], dtype=np.int64)

    y = np.zeros(len(prepared.metadata_rows), dtype=np.int64)
    for attack in attacks:
        overlaps = (attack.start_ns < ends) & (attack.end_ns >= starts)
        if not overlaps.any():
            raise ValueError(
                f"attack {attack.attack!r} [{attack.start_ns}, {attack.end_ns}] "
                "overlaps no window in the evaluation CSV"
            )
        y[overlaps] = 1
    return y


def prepare_labeled_evaluation(
    eval_csv_path: str | Path,
    attack_log_path: str | Path,
) -> LabeledEvaluationInput:
    """Prepare ``eval.csv`` exactly like training data and label each window.

    ``X`` goes through the same :func:`prepare_aggregated_csv` path as
    ``normal.csv``.  Never use evaluation data to fit the scaler or threshold.
    """
    prepared = prepare_aggregated_csv(eval_csv_path)
    attacks = load_attack_log(attack_log_path)
    return LabeledEvaluationInput(
        prepared=prepared,
        y=label_windows(prepared, attacks),
        attacks=attacks,
    )


@dataclass(frozen=True)
class LabeledEvaluationCsv:
    """A raw label vector and its matching unlabelled 77-column CSV content.

    Label ``n`` belongs to data row ``n`` in ``aggregated_csv``.  Label values
    remain raw strings; this path does not assume a label vocabulary.
    """

    label_column: str
    labels: tuple[str, ...]
    aggregated_csv: LoadedAggregatedCsv


def separate_evaluation_labels(
    loaded_csv: LoadedAggregatedCsv,
    *,
    label_column: str,
) -> LabeledEvaluationCsv:
    """Remove one explicit evaluation label column from a loaded CSV.

    The returned ``aggregated_csv`` can then pass through the normal
    validation, mapping, separation, and model-input stages.  This function
    does not infer a label name, classify labels, or validate their semantics.
    """
    if label_column in ALL_COLUMNS:
        raise ValueError("label_column must be separate from the 77 contract columns")

    label_indexes = [
        index for index, column in enumerate(loaded_csv.header) if column == label_column
    ]
    if not label_indexes:
        raise ValueError(f"evaluation label column {label_column!r} is not present")
    if len(label_indexes) > 1:
        raise ValueError(f"evaluation label column {label_column!r} appears more than once")

    label_index = label_indexes[0]
    expected_width = len(loaded_csv.header)
    labels: list[str] = []
    unlabelled_rows: list[tuple[str, ...]] = []
    for row_number, row in enumerate(loaded_csv.rows, start=2):
        if len(row) != expected_width:
            raise ValueError(
                f"cannot separate labels: row {row_number} has {len(row)} fields; "
                f"expected {expected_width}"
            )
        labels.append(row[label_index])
        unlabelled_rows.append(row[:label_index] + row[label_index + 1 :])

    unlabelled_header = (
        loaded_csv.header[:label_index] + loaded_csv.header[label_index + 1 :]
    )
    return LabeledEvaluationCsv(
        label_column=label_column,
        labels=tuple(labels),
        aggregated_csv=LoadedAggregatedCsv(
            source_path=loaded_csv.source_path,
            header=unlabelled_header,
            rows=tuple(unlabelled_rows),
        ),
    )
