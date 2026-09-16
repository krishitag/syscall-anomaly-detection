"""Validate raw aggregated CSV deliveries against the Naman--Krishita contract.

Validation happens before column mapping so errors can be reported against the
CSV as Naman delivered it.  This module does not reorder data, aggregate rows,
or create model input.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import re

from .csv_loader import LoadedAggregatedCsv
from .schema import (
    ALL_COLUMNS,
    METADATA_COLUMNS,
    PAIR_COUNT_COLUMNS,
    STAT_COLUMNS,
    SYSCALL_COUNT_COLUMNS,
)


_INTEGER_PATTERN = re.compile(r"[+-]?\d+\Z")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_COUNT_COLUMNS = SYSCALL_COUNT_COLUMNS + PAIR_COUNT_COLUMNS


class CsvContractError(ValueError):
    """Raised when one or more CSV-contract requirements are violated."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("CSV contract validation failed:\n- " + "\n- ".join(errors))


def _is_missing(value: str) -> bool:
    """Return whether a CSV field represents the contract's forbidden missing data."""
    return value.strip() == "" or value.casefold() == "nan"


def _parse_int64(value: str) -> int | None:
    if not _INTEGER_PATTERN.fullmatch(value):
        return None
    parsed = int(value)
    if not _INT64_MIN <= parsed <= _INT64_MAX:
        return None
    return parsed


def _is_finite_number(value: str) -> bool:
    try:
        return Decimal(value).is_finite()
    except InvalidOperation:
        return False


def _header_errors(header: tuple[str, ...]) -> list[str]:
    """Return all header differences without requiring a canonical input order."""
    errors: list[str] = []
    actual = Counter(header)
    expected = Counter(ALL_COLUMNS)

    duplicates = sorted(column for column, count in actual.items() if count > 1)
    if duplicates:
        errors.append(f"duplicate header column(s): {', '.join(duplicates)}")

    missing = sorted(expected - actual)
    if missing:
        errors.append(f"missing expected header column(s): {', '.join(missing)}")

    unexpected = sorted(actual - expected)
    if unexpected:
        errors.append(f"unexpected header column(s): {', '.join(unexpected)}")

    return errors


def validate_aggregated_csv(loaded_csv: LoadedAggregatedCsv) -> None:
    """Raise :class:`CsvContractError` unless a loaded CSV meets the contract.

    Valid input may use any header order.  Validation deliberately does not
    impose a cgroup representation, timestamp clock/epoch, or statistic range:
    those are documented open team dependencies.
    """
    errors = _header_errors(loaded_csv.header)
    header_is_usable = not errors

    # We can only map fields by their supplied names when the names are a
    # complete, unique version of the expected schema.
    indexes = {column: index for index, column in enumerate(loaded_csv.header)}
    seen_container_windows: set[tuple[str, str]] = set()
    cgroup_value_kinds: set[str] = set()

    for row_index, row in enumerate(loaded_csv.rows, start=2):
        if len(row) != len(loaded_csv.header):
            errors.append(
                f"row {row_index}: has {len(row)} fields; expected {len(loaded_csv.header)}"
            )
            continue

        if not header_is_usable:
            continue

        values = {column: row[index] for column, index in indexes.items()}

        missing_columns = [column for column in ALL_COLUMNS if _is_missing(values[column])]
        if missing_columns:
            errors.append(
                f"row {row_index}: blank or NaN value(s) in {', '.join(missing_columns)}"
            )

        cgroup_id = values[METADATA_COLUMNS[0]]
        if not _is_missing(cgroup_id):
            cgroup_value_kinds.add(
                "integer" if _parse_int64(cgroup_id) is not None else "string"
            )

        start_value = values[METADATA_COLUMNS[1]]
        end_value = values[METADATA_COLUMNS[2]]
        start_ns = _parse_int64(start_value)
        end_ns = _parse_int64(end_value)
        if start_ns is None:
            errors.append(f"row {row_index}: window_start_ns must be an int64")
        if end_ns is None:
            errors.append(f"row {row_index}: window_end_ns must be an int64")
        if start_ns is not None and end_ns is not None and end_ns <= start_ns:
            errors.append(f"row {row_index}: window_end_ns must be greater than window_start_ns")

        if not _is_missing(cgroup_id) and start_ns is not None:
            container_window = (cgroup_id, str(start_ns))
            if container_window in seen_container_windows:
                errors.append(
                    f"row {row_index}: duplicate (cgroup_id, window_start_ns) pair"
                )
            seen_container_windows.add(container_window)

        for column in _COUNT_COLUMNS:
            value = values[column]
            parsed = _parse_int64(value)
            if parsed is None or parsed < 0:
                errors.append(
                    f"row {row_index}: {column} must be a non-negative int64 count"
                )

        for column in STAT_COLUMNS:
            value = values[column]
            if not _is_finite_number(value):
                errors.append(f"row {row_index}: {column} must be a finite numeric value")

    if len(cgroup_value_kinds) > 1:
        errors.append("cgroup_id values must use one consistent type (integer or string)")

    if errors:
        raise CsvContractError(errors)
