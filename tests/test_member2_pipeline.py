"""Automated checks for Member 2's aggregated-CSV handoff pipeline."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from member2.column_mapping import map_to_canonical_order
from member2.csv_loader import LoadedAggregatedCsv, load_aggregated_csv
from member2.evaluation_labels import (
    AttackInterval,
    label_windows,
    load_attack_log,
    prepare_labeled_evaluation,
    separate_evaluation_labels,
)
from member2.feature_separation import separate_metadata_and_features
from member2.mock_aggregated_csv import generate_mock_aggregated_csv
from member2.model_input import build_feature_matrix
from member2.pipeline import prepare_aggregated_csv, prepare_window
from member2.schema import ALL_COLUMNS, FEATURE_COLUMNS, METADATA_COLUMNS
from member2.validation import CsvContractError, validate_aggregated_csv


class Member2PipelineTests(unittest.TestCase):
    def _mock_loaded_csv(self) -> LoadedAggregatedCsv:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        csv_path = Path(temporary_directory.name) / "aggregated.csv"
        generate_mock_aggregated_csv(csv_path, containers=2, windows_per_container=3)
        return load_aggregated_csv(csv_path)

    def test_mock_generator_writes_contract_shaped_aggregated_rows(self) -> None:
        loaded = self._mock_loaded_csv()

        self.assertEqual(loaded.header, tuple(ALL_COLUMNS))
        self.assertEqual(len(loaded.rows), 6)
        self.assertTrue(all(len(row) == 77 for row in loaded.rows))
        validate_aggregated_csv(loaded)

    def test_loader_preserves_incoming_header_and_raw_text(self) -> None:
        loaded = self._mock_loaded_csv()

        self.assertEqual(loaded.rows[0][0], "1000")
        self.assertEqual(loaded.rows[0][1], "1000000000000")
        self.assertIsInstance(loaded.rows[0][3], str)

    def test_validation_rejects_negative_count_and_duplicate_window(self) -> None:
        loaded = self._mock_loaded_csv()
        rows = [list(row) for row in loaded.rows]
        rows[0][3] = "-1"
        rows[1][1] = rows[0][1]
        invalid = LoadedAggregatedCsv(
            source_path=loaded.source_path,
            header=loaded.header,
            rows=tuple(tuple(row) for row in rows),
        )

        with self.assertRaises(CsvContractError) as context:
            validate_aggregated_csv(invalid)

        self.assertTrue(any("syscall_01_count" in error for error in context.exception.errors))
        self.assertTrue(any("duplicate" in error for error in context.exception.errors))

    def test_validation_rejects_schema_drift(self) -> None:
        loaded = self._mock_loaded_csv()
        changed_header = loaded.header[:-1] + ("unexpected_feature",)
        invalid = LoadedAggregatedCsv(loaded.source_path, changed_header, loaded.rows)

        with self.assertRaises(CsvContractError) as context:
            validate_aggregated_csv(invalid)

        self.assertTrue(any("missing expected" in error for error in context.exception.errors))
        self.assertTrue(any("unexpected" in error for error in context.exception.errors))

    def test_mapping_restores_canonical_order_by_name(self) -> None:
        loaded = self._mock_loaded_csv()
        reverse_indexes = tuple(reversed(range(len(loaded.header))))
        shuffled = LoadedAggregatedCsv(
            source_path=loaded.source_path,
            header=tuple(loaded.header[index] for index in reverse_indexes),
            rows=tuple(
                tuple(row[index] for index in reverse_indexes) for row in loaded.rows
            ),
        )

        validate_aggregated_csv(shuffled)
        mapped = map_to_canonical_order(shuffled)

        self.assertEqual(mapped.header, tuple(ALL_COLUMNS))
        self.assertEqual(mapped.rows, loaded.rows)

    def test_separation_and_model_matrix_exclude_metadata(self) -> None:
        loaded = self._mock_loaded_csv()
        validate_aggregated_csv(loaded)
        separated = separate_metadata_and_features(map_to_canonical_order(loaded))
        matrix = build_feature_matrix(separated)

        self.assertEqual(separated.metadata_columns, tuple(METADATA_COLUMNS))
        self.assertEqual(separated.feature_columns, tuple(FEATURE_COLUMNS))
        self.assertEqual(separated.metadata_rows[0], loaded.rows[0][:3])
        self.assertEqual(matrix.X.shape, (6, 74))
        self.assertEqual(matrix.X.dtype, np.float64)
        self.assertEqual(matrix.X[0, 0], 1.0)

    def test_public_pipeline_seam_prepares_mock_or_real_contract_csv(self) -> None:
        loaded = self._mock_loaded_csv()

        prepared = prepare_aggregated_csv(loaded.source_path)

        self.assertEqual(prepared.source_path, loaded.source_path)
        self.assertEqual(prepared.feature_columns, tuple(FEATURE_COLUMNS))
        self.assertEqual(prepared.metadata_columns, tuple(METADATA_COLUMNS))
        self.assertEqual(prepared.X.shape, (6, 74))
        self.assertEqual(len(prepared.metadata_rows), 6)

    def test_evaluation_labels_are_removed_before_contract_validation(self) -> None:
        loaded = self._mock_loaded_csv()
        labelled = LoadedAggregatedCsv(
            source_path=loaded.source_path,
            header=loaded.header + ("evaluation_label",),
            rows=tuple(
                row + (("normal" if index % 2 == 0 else "anomaly"),)
                for index, row in enumerate(loaded.rows)
            ),
        )

        separated_labels = separate_evaluation_labels(
            labelled, label_column="evaluation_label"
        )

        self.assertEqual(
            separated_labels.labels,
            ("normal", "anomaly", "normal", "anomaly", "normal", "anomaly"),
        )
        self.assertEqual(separated_labels.aggregated_csv, loaded)
        validate_aggregated_csv(separated_labels.aggregated_csv)



# Six consecutive 1-second windows from Naman's real data/normal.csv capture:
# two idle windows followed by four with nginx traffic.
REAL_SAMPLE_CSV = Path(__file__).parent / "fixtures" / "real_normal_sample.csv"
WINDOW_STARTS = (
    1790020818328304367,
    1790020819329254617,
    1790020820331274899,
    1790020821336390622,
    1790020822338346478,
    1790020823340440630,
)


class RealDataTests(unittest.TestCase):
    def _real_rows(self) -> list[dict[str, str]]:
        loaded = load_aggregated_csv(REAL_SAMPLE_CSV)
        return [dict(zip(loaded.header, row)) for row in loaded.rows]

    def _with_row_change(self, column: str, value: str) -> LoadedAggregatedCsv:
        loaded = load_aggregated_csv(REAL_SAMPLE_CSV)
        rows = [list(row) for row in loaded.rows]
        rows[0][loaded.header.index(column)] = value
        return LoadedAggregatedCsv(
            loaded.source_path, loaded.header, tuple(tuple(row) for row in rows)
        )

    def test_real_tracer_output_passes_pipeline_unchanged(self) -> None:
        prepared = prepare_aggregated_csv(REAL_SAMPLE_CSV)

        self.assertEqual(prepared.X.shape, (6, 74))
        self.assertEqual(prepared.X[:2].sum(), 0.0)  # idle windows are all zero
        self.assertGreater(prepared.X[2:, :20].sum(), 0.0)

    def test_validation_enforces_resolved_metadata_and_stat_rules(self) -> None:
        invalid_values = {
            "cgroup_id": "nginx",
            "stat_01": "-1.0",
            "stat_02": "inf",
            "stat_03": "0.5",
            "stat_04": "21",
        }
        for column, value in invalid_values.items():
            with self.subTest(column=column):
                with self.assertRaises(CsvContractError) as context:
                    validate_aggregated_csv(self._with_row_change(column, value))
                self.assertTrue(any(column in error for error in context.exception.errors))

    def test_prepare_window_matches_file_pipeline_row(self) -> None:
        prepared = prepare_aggregated_csv(REAL_SAMPLE_CSV)

        for index, row in enumerate(self._real_rows()):
            np.testing.assert_array_equal(prepare_window(row), prepared.X[index])

    def test_prepare_window_accepts_tracer_values_in_any_order(self) -> None:
        # The tracer holds ints and floats, not CSV text.
        row = {column: 0 for column in reversed(ALL_COLUMNS)}
        row.update(cgroup_id=11086, window_start_ns=10, window_end_ns=20)
        row.update(syscall_02_count=7, stat_01=0.0, stat_04=1)

        x = prepare_window(row)

        self.assertEqual(x.shape, (74,))
        self.assertEqual(x[FEATURE_COLUMNS.index("syscall_02_count")], 7.0)
        self.assertEqual(x[FEATURE_COLUMNS.index("stat_04")], 1.0)

    def test_prepare_window_rejects_contract_violations(self) -> None:
        row = self._real_rows()[0]
        missing_column = {k: v for k, v in row.items() if k != "stat_04"}
        negative_count = {**row, "syscall_01_count": "-3"}

        for invalid in (missing_column, negative_count):
            with self.assertRaises(CsvContractError):
                prepare_window(invalid)


class EvaluationLabelTests(unittest.TestCase):
    def _write_attack_log(self, lines: list[str]) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        log_path = Path(temporary_directory.name) / "attack_log.csv"
        log_path.write_text("\n".join(["attack,start_ns,end_ns", *lines]) + "\n")
        return log_path

    def test_attack_straddling_a_boundary_labels_both_windows(self) -> None:
        prepared = prepare_aggregated_csv(REAL_SAMPLE_CSV)
        attack = AttackInterval("shell", WINDOW_STARTS[3] - 1000, WINDOW_STARTS[3] + 1000)

        y = label_windows(prepared, (attack,))

        self.assertEqual(y.tolist(), [0, 0, 1, 1, 0, 0])

    def test_attack_starting_on_a_boundary_labels_only_that_window(self) -> None:
        prepared = prepare_aggregated_csv(REAL_SAMPLE_CSV)
        attack = AttackInterval("unshare", WINDOW_STARTS[1], WINDOW_STARTS[1] + 1000)

        y = label_windows(prepared, (attack,))

        self.assertEqual(y.tolist(), [0, 1, 0, 0, 0, 0])

    def test_attack_outside_capture_is_rejected(self) -> None:
        prepared = prepare_aggregated_csv(REAL_SAMPLE_CSV)
        attack = AttackInterval("wrong_clock", 1_000, 2_000)

        with self.assertRaises(ValueError):
            label_windows(prepared, (attack,))

    def test_prepare_labeled_evaluation_reads_both_files(self) -> None:
        log_path = self._write_attack_log(
            [
                f"shell,{WINDOW_STARTS[0] + 10},{WINDOW_STARTS[0] + 20}",
                f"passwd_read,{WINDOW_STARTS[4] + 10},{WINDOW_STARTS[4] + 20}",
            ]
        )

        labeled = prepare_labeled_evaluation(REAL_SAMPLE_CSV, log_path)

        self.assertEqual(labeled.prepared.X.shape, (6, 74))
        self.assertEqual(labeled.y.tolist(), [1, 0, 0, 0, 1, 0])
        self.assertEqual([a.attack for a in labeled.attacks], ["shell", "passwd_read"])

    def test_malformed_attack_log_is_rejected(self) -> None:
        bad_logs = (
            ["shell,200,100"],  # ends before it starts
            ["shell,abc,100"],  # non-integer time
            ["shell,100"],  # missing field
        )
        for lines in bad_logs:
            with self.subTest(lines=lines):
                with self.assertRaises(ValueError):
                    load_attack_log(self._write_attack_log(lines))


if __name__ == "__main__":
    unittest.main()
