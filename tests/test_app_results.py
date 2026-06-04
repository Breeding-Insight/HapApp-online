from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hapapp_python.app import (
    RunState,
    _expected_new_madc_db_files,
    _list_files,
    _panel_input_files,
    _split_madc_result_options,
)
from hapapp_python.panels import ResolvedMADCPanel


def _resolved_panel(work_dir: Path, allele_db_name: str = "alfalfa_allele_db_v010.fa") -> ResolvedMADCPanel:
    panel_dir = work_dir / "panel_files" / "alfalfa"
    return ResolvedMADCPanel(
        panel_id="alfalfa",
        label="Alfalfa",
        snpid_lut=panel_dir / "snpid_lut.csv",
        allele_db_base=panel_dir / allele_db_name,
        matchcnt_lut_base=panel_dir / "alfalfa_allele_db_v010_matchCnt_lut.txt",
        allele_db_indel=None,
        matchcnt_lut_indel=None,
        dup_tags=None,
        first_sample_col=17,
        design_len=54,
        seq_len=81,
        cov=90,
        iden=85,
        code_ver="v1",
    )


class AppResultTests(unittest.TestCase):
    def test_lists_new_panel_db_outputs_but_hides_original_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "work"
            panel = _resolved_panel(work_dir)
            files = [
                work_dir / "madc_report.csv",
                panel.snpid_lut,
                panel.allele_db_base,
                panel.matchcnt_lut_base,
                work_dir / "panel_files" / "alfalfa" / "alfalfa_allele_db_v011.fa",
                work_dir / "panel_files" / "alfalfa" / "alfalfa_allele_db_v011_matchCnt_lut.txt",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("demo", encoding="utf-8")

            input_files = {"madc_report.csv"} | _panel_input_files(panel, work_dir)
            listed = _list_files(work_dir, input_files)

        self.assertNotIn("madc_report.csv", listed)
        self.assertNotIn("panel_files/alfalfa/snpid_lut.csv", listed)
        self.assertNotIn("panel_files/alfalfa/alfalfa_allele_db_v010.fa", listed)
        self.assertNotIn("panel_files/alfalfa/alfalfa_allele_db_v010_matchCnt_lut.txt", listed)
        self.assertIn("panel_files/alfalfa/alfalfa_allele_db_v011.fa", listed)
        self.assertIn("panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt", listed)

    def test_expected_new_db_outputs_use_one_version_higher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "work"
            expected = _expected_new_madc_db_files(_resolved_panel(work_dir), work_dir)

        self.assertEqual(
            expected,
            {
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
            },
        )

    def test_expected_new_db_outputs_do_not_accept_fasta_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "work"
            expected = _expected_new_madc_db_files(
                _resolved_panel(work_dir, allele_db_name="alfalfa_allele_db_v010.fasta"),
                work_dir,
            )

        self.assertEqual(expected, set())

    def test_nested_expected_db_outputs_are_main_files(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            main_result_files={
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
            },
            files=[
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
                "panel_files/alfalfa/alfalfa_allele_db_v011.fasta",
                "panel_files/alfalfa/alfalfa_allele_db_v011.nhr",
            ],
            status="completed",
        )

        main_options, diagnostic_options = _split_madc_result_options(state)

        self.assertEqual(
            [option["value"] for option in main_options],
            [
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
            ],
        )
        self.assertEqual(
            [option["value"] for option in diagnostic_options],
            [
                "panel_files/alfalfa/alfalfa_allele_db_v011.fasta",
                "panel_files/alfalfa/alfalfa_allele_db_v011.nhr",
            ],
        )


if __name__ == "__main__":
    unittest.main()
