from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hapapp_python.madc_validation import (
    MADCPanelCandidate,
    MADCPanelIdentificationError,
    MADCValidationError,
    identify_raw_madc_panel,
    validate_madc_filename,
    validate_raw_madc,
)

RAW_MADC_METADATA_COLUMNS = (
    "AlleleID",
    "CloneID",
    "AlleleSequence",
    "ClusterConsensusSequence",
    "CallRate",
    "OneRatioRef",
    "OneRatioSnp",
    "FreqHomRef",
    "FreqHomSnp",
    "FreqHets",
    "PICRef",
    "PICSnp",
    "AvgPIC",
    "AvgCountRef",
    "AvgCountSnp",
    "RatioAvgCountRefAvgCountSnp",
)
SAMPLE_COLUMNS = ("sample-a", "sample-b")


def _preamble_row(first_value: str = "") -> str:
    return ",".join(
        [first_value, *([""] * (len(RAW_MADC_METADATA_COLUMNS) - 1)), *SAMPLE_COLUMNS]
    )


def _raw_madc_header(metadata_columns: tuple[str, ...] | list[str] = RAW_MADC_METADATA_COLUMNS) -> str:
    return ",".join([*metadata_columns, *SAMPLE_COLUMNS])


def _raw_madc_data_row(allele_id: str, clone_id: str, allele_sequence: str = "ATCG") -> str:
    metadata_values = (
        allele_id,
        clone_id,
        allele_sequence,
        allele_sequence,
        "1",
        "1",
        "0",
        "1",
        "0",
        "0",
        "0",
        "0",
        "0",
        "10",
        "5",
        "2",
    )
    return ",".join([*metadata_values, "1", "2"])


def _raw_madc_for_clone_ids(clone_ids: list[str]) -> str:
    rows = [
        _preamble_row(),
        _raw_madc_header(),
    ]
    for clone_id in clone_ids:
        rows.extend(
            [
                _raw_madc_data_row(f"{clone_id}|Ref", clone_id),
                _raw_madc_data_row(f"{clone_id}|Alt", clone_id, "ATCC"),
            ]
        )
    return "\n".join(rows)


def _raw_madc_for_allele_ids(allele_ids: list[str]) -> str:
    rows = [
        _preamble_row(),
        _raw_madc_header(),
    ]
    for index, allele_id in enumerate(allele_ids, start=1):
        clone_id = allele_id.split("|", 1)[0] if "|" in allele_id else f"marker{index}"
        rows.append(_raw_madc_data_row(allele_id, clone_id))
    return "\n".join(rows)


def _raw_madc_with_metadata_columns(metadata_columns: tuple[str, ...] | list[str]) -> str:
    return "\n".join(
        [
            _preamble_row(),
            _raw_madc_header(metadata_columns),
            _raw_madc_data_row("marker1|Ref", "marker1"),
            _raw_madc_data_row("marker1|Alt", "marker1", "ATCC"),
        ]
    )


def _panel_lut_for_marker_ids(marker_ids: list[str], header: str = "Panel_markerID,Marker_ID") -> str:
    return "\n".join([header, *[f"{marker_id},{marker_id}" for marker_id in marker_ids]])


class MADCValidationTests(unittest.TestCase):
    def test_accepts_dart_formal_id_variations_in_madc_filename(self) -> None:
        scenarios = {
            "DAl22-7249_MADC.csv": "DAl22-7249",
            "prefix_DWh23_123_suffix.csv": "DWh23_123",
            "project_DSoy24-123456_raw_MADC.csv": "DSoy24-123456",
            "DCnut25-10895_MADC.csv": "DCnut25-10895",
            "DVeryLongSpeciesCode26-4567_MADC.csv": "DVeryLongSpeciesCode26-4567",
            "D26_4567_MADC.csv": "D26_4567",
        }

        for filename, expected_id in scenarios.items():
            with self.subTest(filename=filename):
                self.assertEqual(validate_madc_filename(filename), expected_id)

    def test_rejects_madc_filename_without_correct_dart_formal_id(self) -> None:
        invalid_filenames = [
            "raw_MADC.csv",
            "DAl2-7249_MADC.csv",
            "DAl22.7249_MADC.csv",
            "DAl22-72_MADC.csv",
            "DAl22-1234567_MADC.csv",
        ]

        for filename in invalid_filenames:
            with self.subTest(filename=filename), self.assertRaises(MADCValidationError) as err:
                validate_madc_filename(filename)

            message = str(err.exception)
            self.assertIn("DArT formal ID", message)
            self.assertIn("DAl22-7249_MADC.csv", message)

    def test_detects_row_8_raw_header(self) -> None:
        content = "\n".join(
            [
                _preamble_row(),
                _preamble_row(),
                _preamble_row(),
                _preamble_row(),
                _preamble_row("*"),
                _preamble_row("*"),
                _preamble_row("*"),
                _raw_madc_header(),
                _raw_madc_data_row("marker1|Ref", "marker1"),
                _raw_madc_data_row("marker1|Alt", "marker1", "ATCC"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "row8_madc.csv"
            path.write_text(content, encoding="utf-8")

            result = validate_raw_madc(path, first_sample_col=17)

        self.assertEqual(result.header_row_number, 8)
        self.assertEqual(result.n_data_rows, 2)
        self.assertEqual(result.n_clone_ids, 1)
        self.assertEqual(result.n_ref_rows, 1)
        self.assertEqual(result.n_alt_rows, 1)

    def test_accepts_bundled_demo_raw_madc_with_demo_panel(self) -> None:
        result = validate_raw_madc(
            Path("vendor/HapApp_utils/data/demo_panel/demo_raw_MADC.csv"),
            first_sample_col=17,
            panel_lut_path=Path("vendor/HapApp_utils/data/demo_panel/demo_snpID_lut.csv"),
        )

        self.assertEqual(result.header_row_number, 6)
        self.assertGreater(result.n_data_rows, 0)
        self.assertEqual(result.n_clone_ids_missing_from_panel, 0)

    def test_rejects_fixed_code_version_header(self) -> None:
        content = "\n".join(
            [
                ",".join(["Code_version", *RAW_MADC_METADATA_COLUMNS, *SAMPLE_COLUMNS]),
                f"v1,{_raw_madc_data_row('marker1|Ref_0001', 'marker1')}",
                f"v1,{_raw_madc_data_row('marker1|Alt_0002', 'marker1', 'ATCC')}",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fixed_madc.csv"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(MADCValidationError):
                validate_raw_madc(path, first_sample_col=17)

    def test_rejects_fixed_ids_after_raw_header(self) -> None:
        content = "\n".join(
            [
                _preamble_row(),
                _raw_madc_header(),
                _raw_madc_data_row("marker1|Ref_0001", "marker1"),
                _raw_madc_data_row("marker1|Alt_0002", "marker1", "ATCC"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fixed_ids.csv"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(MADCValidationError):
                validate_raw_madc(path, first_sample_col=17)

    def test_rejects_first_sample_col_before_raw_metadata_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "raw_madc.csv"
            path.write_text(_raw_madc_for_clone_ids(["marker1"]), encoding="utf-8")

            with self.assertRaises(ValueError) as err:
                validate_raw_madc(path, first_sample_col=16)

        self.assertIn("at least 17", str(err.exception))

    def test_rejects_missing_renamed_or_reordered_metadata_columns(self) -> None:
        missing_column = list(RAW_MADC_METADATA_COLUMNS)
        missing_column.remove("ClusterConsensusSequence")

        renamed_column = list(RAW_MADC_METADATA_COLUMNS)
        renamed_column[4] = "CallRateRenamed"

        reordered_columns = list(RAW_MADC_METADATA_COLUMNS)
        reordered_columns[3], reordered_columns[4] = reordered_columns[4], reordered_columns[3]

        scenarios = {
            "missing": missing_column,
            "renamed": renamed_column,
            "reordered": reordered_columns,
        }

        for scenario, metadata_columns in scenarios.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp_dir:
                path = Path(tmp_dir) / "bad_header.csv"
                path.write_text(_raw_madc_with_metadata_columns(metadata_columns), encoding="utf-8")

                with self.assertRaises(MADCValidationError) as err:
                    validate_raw_madc(path, first_sample_col=17)

                self.assertIn("must start with the raw MADC metadata columns", str(err.exception))

    def test_accepts_raw_allele_id_suffixes(self) -> None:
        content = _raw_madc_for_allele_ids(
            [
                "marker1|Ref",
                "marker1|Alt",
                "marker1|RefMatch",
                "marker1|AltMatch",
                "marker1|Other",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "raw_suffixes.csv"
            path.write_text(content, encoding="utf-8")

            result = validate_raw_madc(path, first_sample_col=17)

        self.assertEqual(result.n_data_rows, 5)
        self.assertEqual(result.n_ref_rows, 1)
        self.assertEqual(result.n_alt_rows, 1)
        self.assertEqual(result.n_other_rows, 3)

    def test_rejects_numeric_or_processed_allele_id_suffixes(self) -> None:
        content = _raw_madc_for_allele_ids(
            [
                "marker1|Ref",
                "marker1|Alt",
                "marker1|Ref_0001",
                "marker1|Alt_0002",
                "marker1|RefMatch_0001",
                "marker1|AltMatch_0012",
                "marker1|Other_0003",
                "marker1|RefMatch_tmp_0001",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "processed_suffixes.csv"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(MADCValidationError) as err:
                validate_raw_madc(path, first_sample_col=17)

        message = str(err.exception)
        self.assertIn("Invalid raw MADC AlleleID suffixes", message)
        self.assertIn("marker1|RefMatch_0001", message)
        self.assertIn("marker1|Other_0003", message)

    def test_panel_lut_clone_ids_all_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1", "marker2"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1", "marker2"]), encoding="utf-8")

            result = validate_raw_madc(madc, first_sample_col=17, panel_lut_path=lut)

        self.assertEqual(result.n_panel_marker_ids, 2)
        self.assertEqual(result.n_clone_ids_missing_from_panel, 0)

    def test_panel_lut_warns_when_at_missing_clone_id_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1", "marker2", "marker3"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")

            result = validate_raw_madc(madc, first_sample_col=17, panel_lut_path=lut)

        self.assertEqual(result.n_panel_marker_ids, 1)
        self.assertEqual(result.n_clone_ids_missing_from_panel, 2)
        self.assertTrue(any("missing from the selected panel LUT" in warning for warning in result.warnings))

    def test_panel_lut_errors_when_more_than_two_clone_ids_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1", "marker2", "marker3", "marker4"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")

            with self.assertRaises(MADCValidationError) as err:
                validate_raw_madc(madc, first_sample_col=17, panel_lut_path=lut)

        self.assertIn("wrong species panel", str(err.exception))

    def test_panel_lut_requires_panel_marker_id_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1"], header="Marker_ID,Other_ID"), encoding="utf-8")

            with self.assertRaises(MADCValidationError) as err:
                validate_raw_madc(madc, first_sample_col=17, panel_lut_path=lut)

        self.assertIn("Panel_markerID", str(err.exception))

    def test_identifies_unique_best_panel_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            exact_lut = tmp_path / "exact_lut.csv"
            partial_lut = tmp_path / "partial_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1", "marker2", "marker3"]), encoding="utf-8")
            exact_lut.write_text(_panel_lut_for_marker_ids(["marker1", "marker2", "marker3"]), encoding="utf-8")
            partial_lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")

            result = identify_raw_madc_panel(
                madc,
                [
                    MADCPanelCandidate("exact", "Exact panel", exact_lut),
                    MADCPanelCandidate("partial", "Partial panel", partial_lut),
                ],
            )

        self.assertEqual(result.panel_id, "exact")
        self.assertEqual(result.check.n_clone_ids_missing_from_panel, 0)

    def test_panel_identification_prefers_smallest_containing_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            small_lut = tmp_path / "small_lut.csv"
            large_lut = tmp_path / "large_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1"]), encoding="utf-8")
            small_lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")
            large_lut.write_text(_panel_lut_for_marker_ids(["marker1", "marker2", "marker3"]), encoding="utf-8")

            result = identify_raw_madc_panel(
                madc,
                [
                    MADCPanelCandidate("small", "Small panel", small_lut),
                    MADCPanelCandidate("large", "Large panel", large_lut),
                ],
            )

        self.assertEqual(result.panel_id, "small")

    def test_panel_identification_rejects_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1", "marker2"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")

            with self.assertRaises(MADCPanelIdentificationError) as err:
                identify_raw_madc_panel(
                    madc,
                    [MADCPanelCandidate("other", "Other panel", lut)],
                )

        self.assertIn("does not match any available species panel", str(err.exception))

    def test_panel_identification_rejects_ambiguous_best_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            first_lut = tmp_path / "first_lut.csv"
            second_lut = tmp_path / "second_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1"]), encoding="utf-8")
            first_lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")
            second_lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")

            with self.assertRaises(MADCPanelIdentificationError) as err:
                identify_raw_madc_panel(
                    madc,
                    [
                        MADCPanelCandidate("first", "First panel", first_lut),
                        MADCPanelCandidate("second", "Second panel", second_lut),
                    ],
                )

        self.assertIn("matches multiple species panels equally", str(err.exception))


if __name__ == "__main__":
    unittest.main()
