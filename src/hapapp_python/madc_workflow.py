from __future__ import annotations

import shutil
from pathlib import Path

from hapapp_python.panels import MADCPanel
from hapapp_python.paths import VENDOR_UTILS_DIR, WORKFLOWS_DIR

MADC_WORKFLOW = WORKFLOWS_DIR / "build02_madc_haps.sh"
MADC_SCRIPTS_DIR = VENDOR_UTILS_DIR / "scripts" / "RefMatch_AltMatch_Other"


def missing_madc_commands(panel: MADCPanel) -> list[str]:
    required_commands = ["python3", "blastn", "makeblastdb"]
    if panel.seq_len > panel.design_len:
        required_commands.append("cutadapt")
    return [cmd for cmd in required_commands if shutil.which(cmd) is None]


def build_madc_command(panel: MADCPanel, report: Path, work_dir: Path) -> list[str]:
    command = [
        "bash",
        str(MADC_WORKFLOW),
        "--work-dir",
        str(work_dir),
        "--scripts-dir",
        str(MADC_SCRIPTS_DIR),
        "--report",
        str(report),
        "--snpid-lut",
        str(panel.snpid_lut),
        "--allele-db-base",
        str(panel.allele_db_base),
        "--matchcnt-lut-base",
        str(panel.matchcnt_lut_base),
        "--first-sample-col",
        str(panel.first_sample_col),
        "--design-len",
        str(panel.design_len),
        "--seq-len",
        str(panel.seq_len),
        "--cov",
        str(panel.cov),
        "--iden",
        str(panel.iden),
        "--code-ver",
        panel.code_ver,
    ]
    if panel.allele_db_indel and panel.matchcnt_lut_indel:
        command.extend(
            [
                "--allele-db-indel",
                str(panel.allele_db_indel),
                "--matchcnt-lut-indel",
                str(panel.matchcnt_lut_indel),
            ]
        )
    if panel.dup_tags:
        command.extend(["--dup-tags", str(panel.dup_tags)])
    return command
