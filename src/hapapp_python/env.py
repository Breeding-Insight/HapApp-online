from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_FILES = (
    Path("config") / "local.env",
    Path("config") / "development.env",
    Path("config") / "production.env",
)
HAPAPP_ENV_PREFIX = "HAPAPP_"

_LOADED = False


def load_env() -> None:
    global _LOADED
    if _LOADED:
        return

    env_path = _find_env_file()
    if env_path is None:
        raise RuntimeError(
            "Missing required environment file. Copy config/local.env.example to config/local.env."
        )

    _clear_hapapp_environment()
    load_dotenv(env_path, override=True)
    _LOADED = True


def _find_env_file() -> Path | None:
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        *(Path.cwd() / env_file for env_file in ENV_FILES),
        *(project_root / env_file for env_file in ENV_FILES),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _clear_hapapp_environment() -> None:
    for key in list(os.environ):
        if key.startswith(HAPAPP_ENV_PREFIX):
            del os.environ[key]
