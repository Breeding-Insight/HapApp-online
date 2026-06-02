from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hapapp_python.madc_validation import MADCValidationError, validate_raw_madc


def _raw_madc_for_clone_ids(clone_ids: list[str]) -> str:
    rows = [
        ",,,,sample-a",
        "AlleleID,CloneID,AlleleSequence,sample-a,sample-b",
    ]
    for clone_id in clone_ids:
        rows.extend(
            [
                f"{clone_id}|Ref,{clone_id},ATCG,1,2",
                f"{clone_id}|Alt,{clone_id},ATCC,3,4",
            ]
        )
    return "\n".join(rows)


def _panel_lut_for_marker_ids(marker_ids: list[str], header: str = "Panel_markerID,Marker_ID") -> str:
    return "\n".join([header, *[f"{marker_id},{marker_id}" for marker_id in marker_ids]])


class MADCValidationTests(unittest.TestCase):
    def test_detects_row_8_raw_header(self) -> None:
        content = "\n".join(
            [
                ",,,,sample-a",
                ",,,,sample-a",
                ",,,,A",
                ",,,,1",
                "*,*,*,*,1",
                "*,*,*,*,1",
                "*,*,*,*,1",
                "AlleleID,CloneID,AlleleSequence,sample-a,sample-b",
                "marker1|Ref,marker1,ATCG,1,2",
                "marker1|Alt,marker1,ATCC,3,4",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "row8_madc.csv"
            path.write_text(content, encoding="utf-8")

            result = validate_raw_madc(path, first_sample_col=4)

        self.assertEqual(result.header_row_number, 8)
        self.assertEqual(result.n_data_rows, 2)
        self.assertEqual(result.n_clone_ids, 1)
        self.assertEqual(result.n_ref_rows, 1)
        self.assertEqual(result.n_alt_rows, 1)

    def test_accepts_bundled_raw_fixture_header_row_6(self) -> None:
        result = validate_raw_madc(
            Path("vendor/HapApp_utils/data/genotyping_report/species_MADC.csv"),
            first_sample_col=17,
            panel_lut_path=Path("vendor/HapApp_utils/data/demo_panel/demo_snpID_lut.csv"),
        )

        self.assertEqual(result.header_row_number, 6)
        self.assertGreater(result.n_data_rows, 0)
        self.assertEqual(result.n_clone_ids_missing_from_panel, 0)

    def test_rejects_fixed_code_version_header(self) -> None:
        content = "\n".join(
            [
                "Code_version,AlleleID,CloneID,AlleleSequence,sample-a",
                "v1,marker1|Ref_0001,marker1,ATCG,1",
                "v1,marker1|Alt_0002,marker1,ATCC,2",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fixed_madc.csv"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(MADCValidationError):
                validate_raw_madc(path, first_sample_col=5)

    def test_rejects_fixed_ids_after_raw_header(self) -> None:
        content = "\n".join(
            [
                ",,,,sample-a",
                "AlleleID,CloneID,AlleleSequence,sample-a,sample-b",
                "marker1|Ref_0001,marker1,ATCG,1,2",
                "marker1|Alt_0002,marker1,ATCC,3,4",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "fixed_ids.csv"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(MADCValidationError):
                validate_raw_madc(path, first_sample_col=4)

    def test_panel_lut_clone_ids_all_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1", "marker2"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1", "marker2"]), encoding="utf-8")

            result = validate_raw_madc(madc, first_sample_col=4, panel_lut_path=lut)

        self.assertEqual(result.n_panel_marker_ids, 2)
        self.assertEqual(result.n_clone_ids_missing_from_panel, 0)

    def test_panel_lut_warns_when_at_missing_clone_id_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1", "marker2", "marker3"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1"]), encoding="utf-8")

            result = validate_raw_madc(madc, first_sample_col=4, panel_lut_path=lut)

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
                validate_raw_madc(madc, first_sample_col=4, panel_lut_path=lut)

        self.assertIn("wrong species panel", str(err.exception))

    def test_panel_lut_requires_panel_marker_id_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            madc = tmp_path / "raw_madc.csv"
            lut = tmp_path / "panel_lut.csv"
            madc.write_text(_raw_madc_for_clone_ids(["marker1"]), encoding="utf-8")
            lut.write_text(_panel_lut_for_marker_ids(["marker1"], header="Marker_ID,Other_ID"), encoding="utf-8")

            with self.assertRaises(MADCValidationError) as err:
                validate_raw_madc(madc, first_sample_col=4, panel_lut_path=lut)

        self.assertIn("Panel_markerID", str(err.exception))


if __name__ == "__main__":
    unittest.main()
