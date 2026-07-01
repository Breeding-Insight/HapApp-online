from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from hapapp_python.dropbox_archive import (
    DROPBOX_APP_KEY_ENV,
    DROPBOX_APP_SECRET_ENV,
    DROPBOX_REFRESH_TOKEN_ENV,
    DROPBOX_TOKEN_ENV,
    DropboxConfig,
    DropboxClient,
    archive_madc_review_artifacts,
    dropbox_config_from_env,
)


class FakeDropboxClient:
    uploads: list[tuple[Path, str]] = []

    def __init__(self, access_token: str, **_: str) -> None:
        self.access_token = access_token

    def upload(self, local_path: Path, dropbox_path: str) -> None:
        self.uploads.append((local_path, dropbox_path))


class FakeState:
    def __init__(self, work_dir: Path) -> None:
        self.run_id = "run-123"
        self.work_dir = work_dir
        self.fixed_madc_file = "DAl22-7249_MADC_snpID_rename_updatedSeq_v1.csv"
        self.log_file = "hapapp_madc_workflow.log"
        self.metadata_file = "hapapp_madc_run_metadata.json"


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
                DROPBOX_APP_KEY_ENV: "app-key",
                DROPBOX_APP_SECRET_ENV: "app-secret",
                DROPBOX_REFRESH_TOKEN_ENV: "refresh-token",
                "HAPAPP_DROPBOX_MADC_FOLDER": "review",
                "HAPAPP_DROPBOX_LOG_FOLDER": "/logs/",
            },
        ):
            config = dropbox_config_from_env()

        assert config is not None
        self.assertEqual(config.access_token, "token")
        self.assertEqual(config.app_key, "app-key")
        self.assertEqual(config.app_secret, "app-secret")
        self.assertEqual(config.refresh_token, "refresh-token")
        self.assertEqual(config.madc_folder, "/review")
        self.assertEqual(config.log_folder, "/logs")

    def test_blank_dropbox_token_disables_archive_config(self) -> None:
        with patch.dict(os.environ, {DROPBOX_TOKEN_ENV: "   "}):
            self.assertIsNone(dropbox_config_from_env())

    def test_refresh_token_config_can_replace_static_access_token(self) -> None:
        with patch.dict(
            os.environ,
            {
                DROPBOX_APP_KEY_ENV: "app-key",
                DROPBOX_APP_SECRET_ENV: "app-secret",
                DROPBOX_REFRESH_TOKEN_ENV: "refresh-token",
            },
        ):
            config = dropbox_config_from_env()

        assert config is not None
        self.assertEqual(config.access_token, "")
        self.assertEqual(config.app_key, "app-key")
        self.assertEqual(config.app_secret, "app-secret")
        self.assertEqual(config.refresh_token, "refresh-token")

    def test_partial_refresh_token_config_raises_helpful_error(self) -> None:
        with patch.dict(os.environ, {DROPBOX_APP_KEY_ENV: "app-key"}):
            with self.assertRaisesRegex(Exception, "requires"):
                dropbox_config_from_env()

    def test_archives_fixed_madc_and_log_to_separate_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            (work_dir / "DAl22-7249_MADC_snpID_rename_updatedSeq_v1.csv").write_text("madc", encoding="utf-8")
            (work_dir / "hapapp_madc_workflow.log").write_text("log", encoding="utf-8")
            (work_dir / "hapapp_madc_run_metadata.json").write_text("{}", encoding="utf-8")

            with patch("hapapp_python.dropbox_archive.DropboxClient", FakeDropboxClient):
                messages = archive_madc_review_artifacts(
                    FakeState(work_dir),
                    DropboxConfig("token", "/review", "/logs"),
                )

        self.assertEqual(
            [(path.name, dropbox_path) for path, dropbox_path in FakeDropboxClient.uploads],
            [
                (
                    "DAl22-7249_MADC_snpID_rename_updatedSeq_v1.csv",
                    "/review/DAl22-7249_MADC_snpID_rename_updatedSeq_v1_run-123.csv",
                ),
                ("hapapp_madc_workflow.log", "/logs/hapapp_madc_workflow_run-123.log"),
                ("hapapp_madc_run_metadata.json", "/logs/hapapp_madc_run_metadata_run-123.json"),
            ],
        )
        self.assertEqual(
            messages,
            [
                (
                    "Archived fixed MADC to Dropbox: "
                    "/review/DAl22-7249_MADC_snpID_rename_updatedSeq_v1_run-123.csv"
                ),
                "Archived MADC log to Dropbox: /logs/hapapp_madc_workflow_run-123.log",
                "Archived MADC run metadata to Dropbox: /logs/hapapp_madc_run_metadata_run-123.json",
            ],
        )

    def test_can_archive_only_log_for_cancel_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            (work_dir / "DAl22-7249_MADC_snpID_rename_updatedSeq_v1.csv").write_text("madc", encoding="utf-8")
            (work_dir / "hapapp_madc_workflow.log").write_text("log", encoding="utf-8")
            (work_dir / "hapapp_madc_run_metadata.json").write_text("{}", encoding="utf-8")

            with patch("hapapp_python.dropbox_archive.DropboxClient", FakeDropboxClient):
                messages = archive_madc_review_artifacts(
                    FakeState(work_dir),
                    DropboxConfig("token", "/review", "/logs"),
                    include_fixed_madc=False,
                    include_log=True,
                )

        self.assertEqual(
            [(path.name, dropbox_path) for path, dropbox_path in FakeDropboxClient.uploads],
            [
                ("hapapp_madc_workflow.log", "/logs/hapapp_madc_workflow_run-123.log"),
                ("hapapp_madc_run_metadata.json", "/logs/hapapp_madc_run_metadata_run-123.json"),
            ],
        )
        self.assertEqual(
            messages,
            [
                "Archived MADC log to Dropbox: /logs/hapapp_madc_workflow_run-123.log",
                "Archived MADC run metadata to Dropbox: /logs/hapapp_madc_run_metadata_run-123.json",
            ],
        )

    def test_client_refreshes_access_token_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_path = Path(tmp_dir) / "artifact.txt"
            local_path.write_text("contents", encoding="utf-8")
            token_response = MagicMock()
            token_response.__enter__.return_value.read.return_value = b'{"access_token":"fresh-token"}'
            upload_response = MagicMock()
            upload_response.__enter__.return_value.read.return_value = b"{}"

            with patch("urllib.request.urlopen", side_effect=[token_response, upload_response]) as urlopen:
                client = DropboxClient(
                    app_key="app-key",
                    app_secret="app-secret",
                    refresh_token="refresh-token",
                )
                client.upload(local_path, "/review/artifact.txt")

        self.assertEqual(urlopen.call_count, 2)
        upload_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(upload_request.headers["Authorization"], "Bearer fresh-token")


if __name__ == "__main__":
    unittest.main()
