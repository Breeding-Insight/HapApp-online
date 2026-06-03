from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from hapapp_python.madc_workflow import build_madc_command, missing_madc_commands
from hapapp_python.panels import ResolvedMADCPanel


def _panel(**overrides) -> ResolvedMADCPanel:
    values = {
        "panel_id": "demo",
        "label": "Demo",
        "snpid_lut": Path("/panel/snpid_lut.csv"),
        "allele_db_base": Path("/panel/allele_db.fa"),
        "matchcnt_lut_base": Path("/panel/matchcnt_lut.txt"),
        "allele_db_indel": None,
        "matchcnt_lut_indel": None,
        "dup_tags": None,
        "first_sample_col": 17,
        "design_len": 59,
        "seq_len": 59,
        "cov": 90,
        "iden": 85,
        "code_ver": "v1",
    }
    values.update(overrides)
    return ResolvedMADCPanel(**values)


class MADCWorkflowTests(unittest.TestCase):
    def test_builds_base_madc_command(self) -> None:
        command = build_madc_command(_panel(), Path("/work/report.csv"), Path("/work"))

        self.assertEqual(command[0], "bash")
        self.assertEqual(command[command.index("--work-dir") + 1], "/work")
        self.assertEqual(command[command.index("--report") + 1], "/work/report.csv")
        self.assertEqual(command[command.index("--snpid-lut") + 1], "/panel/snpid_lut.csv")
        self.assertEqual(command[command.index("--first-sample-col") + 1], "17")
        self.assertNotIn("--allele-db-indel", command)
        self.assertNotIn("--dup-tags", command)

    def test_builds_optional_indel_and_duplicate_tag_args(self) -> None:
        panel = _panel(
            allele_db_indel=Path("/panel/indel.fa"),
            matchcnt_lut_indel=Path("/panel/indel_matchcnt.txt"),
            dup_tags=Path("/panel/dup_tags.txt"),
        )

        command = build_madc_command(panel, Path("/work/report.csv"), Path("/work"))

        self.assertEqual(command[command.index("--allele-db-indel") + 1], "/panel/indel.fa")
        self.assertEqual(command[command.index("--matchcnt-lut-indel") + 1], "/panel/indel_matchcnt.txt")
        self.assertEqual(command[command.index("--dup-tags") + 1], "/panel/dup_tags.txt")

    def test_cutadapt_is_required_only_when_sequence_is_longer_than_design(self) -> None:
        with patch("hapapp_python.madc_workflow.shutil.which", return_value="/usr/bin/tool") as which:
            self.assertEqual(missing_madc_commands(_panel(seq_len=59, design_len=59)), [])

        self.assertNotIn("cutadapt", [call.args[0] for call in which.call_args_list])

        def which_side_effect(command: str) -> str | None:
            return None if command == "cutadapt" else f"/usr/bin/{command}"

        with patch("hapapp_python.madc_workflow.shutil.which", side_effect=which_side_effect):
            self.assertEqual(missing_madc_commands(_panel(seq_len=109, design_len=81)), ["cutadapt"])


if __name__ == "__main__":
    unittest.main()
