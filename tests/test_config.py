from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class ConfigTests(unittest.TestCase):
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
