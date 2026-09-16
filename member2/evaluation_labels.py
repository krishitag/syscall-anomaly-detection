"""Keep optional evaluation labels separate from the 77-column model contract.

No label column name or label vocabulary has been agreed by the team.  Callers
therefore opt in by explicitly supplying the name of one additional evaluation
label column.  Routine/unlabeled CSV deliveries should skip this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from .csv_loader import LoadedAggregatedCsv
from .schema import ALL_COLUMNS


@dataclass(frozen=True)
class LabeledEvaluationCsv:
    """A raw label vector and its matching unlabelled 77-column CSV content.

    Label ``n`` belongs to data row ``n`` in ``aggregated_csv``.  Label values
    remain raw strings because their permitted values and encoding are pending
    an evaluation-dataset decision.
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
