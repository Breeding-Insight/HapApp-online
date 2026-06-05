from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hapapp_python.dropbox_archive import (
    DROPBOX_TOKEN_ENV,
    DropboxConfig,
    archive_madc_review_artifacts,
    dropbox_config_from_env,
)


class FakeDropboxClient:
    uploads: list[tuple[Path, str]] = []

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def upload(self, local_path: Path, dropbox_path: str) -> None:
        self.uploads.append((local_path, dropbox_path))


class FakeState:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.fixed_madc_file = "run_snpID_rename_v1.csv"
        self.log_file = "hapapp_madc_workflow.log"


class DropboxArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeDropboxClient.uploads = []

    def test_skips_archive_when_dropbox_token_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(os.environ, {DROPBOX_TOKEN_ENV: ""}, clear=False):
            messages = archive_madc_review_artifacts(FakeState(Path(tmp_dir)))

        self.assertEqual(messages, [f"Dropbox archive skipped because {DROPBOX_TOKEN_ENV} is not set."])

    def test_reads_dropbox_config_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                DROPBOX_TOKEN_ENV: "token",
                "HAPAPP_DROPBOX_MADC_FOLDER": "review",
                "HAPAPP_DROPBOX_LOG_FOLDER": "/logs/",
            },
        ):
            config = dropbox_config_from_env()

        assert config is not None
        self.assertEqual(config.access_token, "token")
        self.assertEqual(config.madc_folder, "/review")
        self.assertEqual(config.log_folder, "/logs")

    def test_blank_dropbox_token_disables_archive_config(self) -> None:
        with patch.dict(os.environ, {DROPBOX_TOKEN_ENV: "   "}):
            self.assertIsNone(dropbox_config_from_env())

    def test_archives_fixed_madc_and_log_to_separate_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            (work_dir / "run_snpID_rename_v1.csv").write_text("madc", encoding="utf-8")
            (work_dir / "hapapp_madc_workflow.log").write_text("log", encoding="utf-8")

            with patch("hapapp_python.dropbox_archive.DropboxClient", FakeDropboxClient):
                messages = archive_madc_review_artifacts(
                    FakeState(work_dir),
                    DropboxConfig("token", "/review", "/logs"),
                )

        self.assertEqual(
            [(path.name, dropbox_path) for path, dropbox_path in FakeDropboxClient.uploads],
            [
                ("run_snpID_rename_v1.csv", "/review/run_snpID_rename_v1.csv"),
                ("hapapp_madc_workflow.log", "/logs/hapapp_madc_workflow.log"),
            ],
        )
        self.assertEqual(
            messages,
            [
                "Archived fixed MADC to Dropbox: /review/run_snpID_rename_v1.csv",
                "Archived MADC log to Dropbox: /logs/hapapp_madc_workflow.log",
            ],
        )

    def test_can_archive_only_log_for_cancel_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            (work_dir / "run_snpID_rename_v1.csv").write_text("madc", encoding="utf-8")
            (work_dir / "hapapp_madc_workflow.log").write_text("log", encoding="utf-8")

            with patch("hapapp_python.dropbox_archive.DropboxClient", FakeDropboxClient):
                messages = archive_madc_review_artifacts(
                    FakeState(work_dir),
                    DropboxConfig("token", "/review", "/logs"),
                    include_fixed_madc=False,
                    include_log=True,
                )

        self.assertEqual(
            [(path.name, dropbox_path) for path, dropbox_path in FakeDropboxClient.uploads],
            [("hapapp_madc_workflow.log", "/logs/hapapp_madc_workflow.log")],
        )
        self.assertEqual(messages, ["Archived MADC log to Dropbox: /logs/hapapp_madc_workflow.log"])


if __name__ == "__main__":
    unittest.main()
