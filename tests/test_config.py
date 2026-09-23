from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class ConfigTests(unittest.TestCase):
    def test_cloud_run_port_takes_precedence(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "PORT": "8080",
            "HAPAPP_PORT": "8050",
            "PYTHONPATH": str(project_root / "src"),
        }

        result = subprocess.run(
            [sys.executable, "-c", "from hapapp_python import config; print(config.APP_PORT)"],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "8080")

    def test_cloud_run_configuration_fails_closed_without_orcid_and_secrets(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "K_SERVICE": "hapapp",
            "APP_ENV": "production",
            "HAPAPP_LOCAL_AUTH_BYPASS": "0",
            "HAPAPP_PUBLIC_URL": "https://hapapp.example",
            "SECRET_KEY": "change-me",
            "TLS_ENABLED": "false",
            "ORCID_CLIENT_ID": "",
            "ORCID_CLIENT_SECRET": "",
            "PYTHONPATH": str(project_root / "src"),
        }

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from hapapp_python import config; config.assert_cloud_run_configuration_ready()",
            ],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ORCID_CLIENT_ID", result.stderr)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_cloud_run_can_derive_public_url_from_proxy_headers(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "K_SERVICE": "hapapp",
            "APP_ENV": "production",
            "HAPAPP_LOCAL_AUTH_BYPASS": "0",
            "HAPAPP_PUBLIC_URL": "",
            "SECRET_KEY": "0123456789abcdef0123456789abcdef",
            "TLS_ENABLED": "false",
            "ORCID_CLIENT_ID": "client",
            "ORCID_CLIENT_SECRET": "secret",
            "MSSQL_DATABASE": "HapApp",
            "PYTHONPATH": str(project_root / "src"),
        }

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from hapapp_python import config; config.assert_cloud_run_configuration_ready()",
            ],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tls_enabled_sets_ssl_context(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "TLS_ENABLED": "1",
            "TLS_CERT_PATH": "/example/cert.pem",
            "TLS_KEY_PATH": "/example/key.pem",
            "PYTHONPATH": str(project_root / "src"),
        }

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from hapapp_python import config; print(config.SSL_CONTEXT)",
            ],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("('/example/cert.pem', '/example/key.pem')", result.stdout)

    def test_local_auth_bypass_fails_closed_outside_local_dev(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ,
            "APP_ENV": "production",
            "HAPAPP_LOCAL_AUTH_BYPASS": "1",
            "PYTHONPATH": str(project_root / "src"),
        }

        result = subprocess.run(
            [sys.executable, "-c", "import hapapp_python.config"],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("may only be enabled when APP_ENV=local-dev", result.stderr)


if __name__ == "__main__":
    unittest.main()
