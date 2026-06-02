from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hapapp_python.madc_validation import MADCValidationError, validate_raw_madc


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
        )

        self.assertEqual(result.header_row_number, 6)
        self.assertGreater(result.n_data_rows, 0)

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


if __name__ == "__main__":
    unittest.main()
