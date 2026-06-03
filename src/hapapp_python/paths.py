from __future__ import annotations

from pathlib import Path


def find_project_root() -> Path:
    editable_root = Path(__file__).resolve().parents[2]
    if (editable_root / "workflows").is_dir() and (editable_root / "vendor" / "HapApp_utils").is_dir():
        return editable_root

    cwd = Path.cwd().resolve()
    if (cwd / "workflows").is_dir() and (cwd / "vendor" / "HapApp_utils").is_dir():
        return cwd

    return editable_root


PROJECT_ROOT = find_project_root()
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
VENDOR_UTILS_DIR = PROJECT_ROOT / "vendor" / "HapApp_utils"
