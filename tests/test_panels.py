from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hapapp_python.panels import MADCPanel, load_madc_panels, validate_madc_panel_files
from hapapp_python.paths import PROJECT_ROOT


def _panel_toml(
    *,
    panel_id: str = "demo",
    extra_fields: str = "",
    omit_label: bool = False,
) -> str:
    label = "" if omit_label else 'label = "Demo"\n'
    return f"""
[panels.{panel_id}]
{label}snpid_lut = "relative/demo_snpID_lut.csv"
allele_db_base = "relative/demo_allele_db.fa"
matchcnt_lut_base = "relative/demo_matchCnt_lut.txt"
first_sample_col = 17
design_len = 59
seq_len = 59
cov = 90
iden = 85
code_ver = "v1"
{extra_fields}
""".strip()


class MADCPanelTests(unittest.TestCase):
    def test_loads_bundled_demo_panel(self) -> None:
        panels = load_madc_panels()

        self.assertIn("demo", panels)
        self.assertEqual(panels["demo"].label, "Demo panel (bundled example)")

    def test_resolves_relative_paths_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "panels.toml"
            config_path.write_text(_panel_toml(), encoding="utf-8")

            panel = load_madc_panels(config_path)["demo"]

        self.assertEqual(panel.snpid_lut, PROJECT_ROOT / "relative/demo_snpID_lut.csv")
        self.assertEqual(panel.allele_db_base, PROJECT_ROOT / "relative/demo_allele_db.fa")
        self.assertEqual(panel.matchcnt_lut_base, PROJECT_ROOT / "relative/demo_matchCnt_lut.txt")

    def test_rejects_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "panels.toml"
            config_path.write_text(_panel_toml(omit_label=True), encoding="utf-8")

            with self.assertRaises(ValueError) as err:
                load_madc_panels(config_path)

        self.assertIn("label", str(err.exception))

    def test_rejects_invalid_panel_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "panels.toml"
            config_path.write_text(_panel_toml(panel_id='"bad id"'), encoding="utf-8")

            with self.assertRaises(ValueError) as err:
                load_madc_panels(config_path)

        self.assertIn("Invalid MADC panel id", str(err.exception))

    def test_rejects_incomplete_indel_file_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "panels.toml"
            config_path.write_text(
                _panel_toml(extra_fields='allele_db_indel = "relative/indel.fa"'),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as err:
                load_madc_panels(config_path)

        self.assertIn("must define both allele_db_indel and matchcnt_lut_indel", str(err.exception))

    def test_reports_missing_configured_files(self) -> None:
        panel = MADCPanel(
            panel_id="demo",
            label="Demo",
            snpid_lut=Path("/missing/snpid_lut.csv"),
            allele_db_base=Path("/missing/allele_db.fa"),
            matchcnt_lut_base=Path("/missing/matchcnt_lut.txt"),
            allele_db_indel=None,
            matchcnt_lut_indel=None,
            dup_tags=None,
            first_sample_col=17,
            design_len=59,
            seq_len=59,
            cov=90,
            iden=85,
            code_ver="v1",
        )

        with self.assertRaises(ValueError) as err:
            validate_madc_panel_files(panel)

        message = str(err.exception)
        self.assertIn("SNP ID LUT", message)
        self.assertIn("base allele DB FASTA", message)
        self.assertIn("base match-count LUT", message)


if __name__ == "__main__":
    unittest.main()
