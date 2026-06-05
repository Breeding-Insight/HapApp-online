from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DROPBOX_TOKEN_ENV = "HAPAPP_DROPBOX_ACCESS_TOKEN"
DROPBOX_MADC_FOLDER_ENV = "HAPAPP_DROPBOX_MADC_FOLDER"
DROPBOX_LOG_FOLDER_ENV = "HAPAPP_DROPBOX_LOG_FOLDER"
DEFAULT_MADC_FOLDER = "/HapApp/MADC review"
DEFAULT_LOG_FOLDER = "/HapApp/MADC logs"
DROPBOX_UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"
DROPBOX_SESSION_START_URL = "https://content.dropboxapi.com/2/files/upload_session/start"
DROPBOX_SESSION_APPEND_URL = "https://content.dropboxapi.com/2/files/upload_session/append_v2"
DROPBOX_SESSION_FINISH_URL = "https://content.dropboxapi.com/2/files/upload_session/finish"
DROPBOX_SINGLE_UPLOAD_LIMIT = 140 * 1024 * 1024
DROPBOX_CHUNK_SIZE = 8 * 1024 * 1024


class DropboxArchiveError(RuntimeError):
    pass


class MADCArchiveState(Protocol):
    work_dir: Path
    fixed_madc_file: str | None
    log_file: str | None


@dataclass(frozen=True)
class DropboxConfig:
    access_token: str
    madc_folder: str
    log_folder: str


def dropbox_config_from_env() -> DropboxConfig | None:
    token = os.environ.get(DROPBOX_TOKEN_ENV, "").strip()
    if not token:
        return None
    return DropboxConfig(
        access_token=token,
        madc_folder=_normalize_dropbox_folder(os.environ.get(DROPBOX_MADC_FOLDER_ENV, DEFAULT_MADC_FOLDER)),
        log_folder=_normalize_dropbox_folder(os.environ.get(DROPBOX_LOG_FOLDER_ENV, DEFAULT_LOG_FOLDER)),
    )


def archive_madc_review_artifacts(
    state: MADCArchiveState,
    config: DropboxConfig | None = None,
    *,
    include_fixed_madc: bool = True,
    include_log: bool = True,
) -> list[str]:
    resolved_config = config or dropbox_config_from_env()
    if resolved_config is None:
        return [f"Dropbox archive skipped because {DROPBOX_TOKEN_ENV} is not set."]

    uploads: list[tuple[str, str, str]] = []
    if include_fixed_madc and state.fixed_madc_file:
        uploads.append(("fixed MADC", state.fixed_madc_file, resolved_config.madc_folder))
    if include_log and state.log_file:
        uploads.append(("MADC log", state.log_file, resolved_config.log_folder))
    if not uploads:
        raise DropboxArchiveError("No requested MADC artifact is available to archive.")

    client = DropboxClient(resolved_config.access_token)
    messages: list[str] = []
    for label, relative_file, folder in uploads:
        local_path = (state.work_dir / relative_file).resolve()
        if not local_path.is_file():
            raise DropboxArchiveError(f"{label} file is missing: {relative_file}")
        dropbox_path = f"{folder}/{local_path.name}"
        client.upload(local_path, dropbox_path)
        messages.append(f"Archived {label} to Dropbox: {dropbox_path}")
    return messages


class DropboxClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def upload(self, local_path: Path, dropbox_path: str) -> None:
        dropbox_path = _normalize_dropbox_file_path(dropbox_path)
        if local_path.stat().st_size <= DROPBOX_SINGLE_UPLOAD_LIMIT:
            self._single_upload(local_path, dropbox_path)
            return
        self._chunked_upload(local_path, dropbox_path)

    def _single_upload(self, local_path: Path, dropbox_path: str) -> None:
        args = {
            "path": dropbox_path,
            "mode": "add",
            "autorename": True,
            "mute": False,
            "strict_conflict": False,
        }
        self._content_request(DROPBOX_UPLOAD_URL, args, local_path.read_bytes())

    def _chunked_upload(self, local_path: Path, dropbox_path: str) -> None:
        file_size = local_path.stat().st_size
        with local_path.open("rb") as stream:
            first_chunk = stream.read(DROPBOX_CHUNK_SIZE)
            start_response = self._content_request(DROPBOX_SESSION_START_URL, {"close": False}, first_chunk)
            session_id = start_response.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise DropboxArchiveError("Dropbox did not return an upload session id.")

            offset = len(first_chunk)
            while offset < file_size:
                chunk = stream.read(DROPBOX_CHUNK_SIZE)
                if not chunk:
                    break
                if offset + len(chunk) < file_size:
                    self._content_request(
                        DROPBOX_SESSION_APPEND_URL,
                        {"cursor": {"session_id": session_id, "offset": offset}, "close": False},
                        chunk,
                    )
                    offset += len(chunk)
                    continue

                self._content_request(
                    DROPBOX_SESSION_FINISH_URL,
                    {
                        "cursor": {"session_id": session_id, "offset": offset},
                        "commit": {
                            "path": dropbox_path,
                            "mode": "add",
                            "autorename": True,
                            "mute": False,
                            "strict_conflict": False,
                        },
                    },
                    chunk,
                )
                break

    def _content_request(self, url: str, args: dict[str, object], data: bytes) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Arg": json.dumps(args, separators=(",", ":")),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DropboxArchiveError(f"Dropbox upload failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DropboxArchiveError(f"Dropbox upload failed: {exc.reason}") from exc

        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DropboxArchiveError("Dropbox returned an invalid JSON response.") from exc
        if not isinstance(parsed, dict):
            raise DropboxArchiveError("Dropbox returned an unexpected response.")
        return parsed


def _normalize_dropbox_folder(folder: str) -> str:
    folder = folder.strip().strip("/")
    return f"/{folder}" if folder else ""


def _normalize_dropbox_file_path(path: str) -> str:
    cleaned = "/" + path.strip().strip("/")
    if cleaned == "/":
        raise DropboxArchiveError("Dropbox destination path cannot be empty.")
    return cleaned
