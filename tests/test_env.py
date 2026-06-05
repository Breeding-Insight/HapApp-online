from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hapapp_python.env as app_env


class EnvTests(unittest.TestCase):
    def test_loads_dotenv_file_from_current_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "HAPAPP_DROPBOX_ACCESS_TOKEN=test-token",
                        "HAPAPP_DROPBOX_MADC_FOLDER='/review folder'",
                        "HAPAPP_DROPBOX_LOG_FOLDER=\"/log folder\"",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.object(app_env, "_LOADED", False), patch.dict(os.environ, {}, clear=True), patch(
                "os.getcwd", return_value=tmp_dir
            ):
                app_env.load_env()

                self.assertEqual(os.environ["HAPAPP_DROPBOX_ACCESS_TOKEN"], "test-token")
                self.assertEqual(os.environ["HAPAPP_DROPBOX_MADC_FOLDER"], "/review folder")
                self.assertEqual(os.environ["HAPAPP_DROPBOX_LOG_FOLDER"], "/log folder")

    def test_dotenv_values_replace_existing_hapapp_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / ".env").write_text("HAPAPP_PORT=9999\n", encoding="utf-8")

            with patch.object(app_env, "_LOADED", False), patch.dict(
                os.environ,
                {
                    "HAPAPP_PORT": "8050",
                    "HAPAPP_DROPBOX_ACCESS_TOKEN": "ambient-token",
                    "PATH": "/usr/bin",
                },
                clear=True,
            ), patch("os.getcwd", return_value=tmp_dir):
                app_env.load_env()

                self.assertEqual(os.environ["HAPAPP_PORT"], "9999")
                self.assertNotIn("HAPAPP_DROPBOX_ACCESS_TOKEN", os.environ)
                self.assertEqual(os.environ["PATH"], "/usr/bin")

    def test_raises_when_dotenv_file_is_missing(self) -> None:
        with patch.object(app_env, "_LOADED", False), patch("hapapp_python.env._find_env_file", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Missing required .env file"):
                app_env.load_env()


if __name__ == "__main__":
    unittest.main()
