"""Automated checks for Member 2's aggregated-CSV handoff pipeline."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from member2.column_mapping import map_to_canonical_order
from member2.csv_loader import LoadedAggregatedCsv, load_aggregated_csv
from member2.evaluation_labels import separate_evaluation_labels
from member2.feature_separation import separate_metadata_and_features
from member2.mock_aggregated_csv import generate_mock_aggregated_csv
from member2.model_input import build_feature_matrix
from member2.pipeline import prepare_aggregated_csv
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


if __name__ == "__main__":
    unittest.main()
