from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE_NAME = ".env"
HAPAPP_ENV_PREFIX = "HAPAPP_"

_LOADED = False


def load_env() -> None:
    global _LOADED
    if _LOADED:
        return

    env_path = _find_env_file()
    if env_path is None:
        raise RuntimeError(
            "Missing required .env file. Copy .env_example to .env and set the server configuration values."
        )

    _clear_hapapp_environment()
    load_dotenv(env_path, override=True)
    _LOADED = True


def _find_env_file() -> Path | None:
    candidates = [
        Path.cwd() / ENV_FILE_NAME,
        Path(__file__).resolve().parents[2] / ENV_FILE_NAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _clear_hapapp_environment() -> None:
    for key in list(os.environ):
        if key.startswith(HAPAPP_ENV_PREFIX):
            del os.environ[key]
