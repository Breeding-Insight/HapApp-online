from __future__ import annotations

import json
import os
import re
import shutil
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlparse

from hapapp_python.panels import MADCPanel, PanelFileRef, ResolvedMADCPanel, is_github_url, validate_madc_panel_files

GITHUB_TOKEN_ENV = "HAPAPP_GITHUB_TOKEN"
GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "HapApp-online"
VERSION_RE = re.compile(r"_v(?P<version>\d+)", flags=re.IGNORECASE)


class PanelFileResolutionError(ValueError):
    """Raised when a configured species panel cannot be prepared for a run."""


@dataclass(frozen=True)
class GitHubContentRef:
    owner: str
    repo: str
    kind: str
    ref: str
    path: str


class GitHubContentClient(Protocol):
    def get_content(self, content_ref: GitHubContentRef) -> Any: ...

    def download_file(self, file_entry: Mapping[str, Any], destination_dir: Path) -> Path: ...


class GitHubContentsClient:
    def __init__(self, token: str):
        if not token.strip():
            raise PanelFileResolutionError(f"{GITHUB_TOKEN_ENV} is required for GitHub-backed species panels.")
        self._token = token.strip()

    def get_content(self, content_ref: GitHubContentRef) -> Any:
        return self._request_json(_github_contents_api_url(content_ref))

    def download_file(self, file_entry: Mapping[str, Any], destination_dir: Path) -> Path:
        name = _entry_name(file_entry)
        download_url = file_entry.get("download_url")
        if not isinstance(download_url, str) or not download_url:
            raise PanelFileResolutionError(f"GitHub file {name!r} does not have a download URL.")

        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / name
        request = urllib.request.Request(download_url, headers=self._headers("application/octet-stream"))
        try:
            with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        except urllib.error.HTTPError as exc:
            raise PanelFileResolutionError(_http_error_message("GitHub file download failed", download_url, exc)) from exc
        except urllib.error.URLError as exc:
            raise PanelFileResolutionError(f"GitHub file download failed for {download_url}: {exc.reason}") from exc
        return destination

    def _request_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self._headers("application/vnd.github+json"))
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PanelFileResolutionError(_http_error_message("GitHub API request failed", url, exc)) from exc
        except urllib.error.URLError as exc:
            raise PanelFileResolutionError(f"GitHub API request failed for {url}: {exc.reason}") from exc

    def _headers(self, accept: str) -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }


def resolve_madc_panel_files(
    panel: MADCPanel,
    work_dir: Path,
    *,
    github_token: str | None = None,
    github_client: GitHubContentClient | None = None,
) -> ResolvedMADCPanel:
    """Copy any GitHub-backed panel files into this run's work directory."""
    if not _panel_uses_github(panel):
        validate_madc_panel_files(panel)
        return _resolved_from_local_panel(panel)

    token = github_token if github_token is not None else os.environ.get(GITHUB_TOKEN_ENV)
    if github_client is None:
        if not token:
            raise PanelFileResolutionError(
                f"Selected species panel {panel.label!r} uses GitHub files, but {GITHUB_TOKEN_ENV} is not set."
            )
        github_client = GitHubContentsClient(token)

    destination_dir = work_dir / "panel_files" / _safe_dir_name(panel.panel_id)
    destination_dir.mkdir(parents=True, exist_ok=True)

    allele_db_base, matchcnt_lut_base = _resolve_base_pair(
        panel.allele_db_base,
        panel.matchcnt_lut_base,
        destination_dir,
        github_client,
    )
    allele_db_indel, matchcnt_lut_indel = _resolve_optional_pair(
        panel.allele_db_indel,
        panel.matchcnt_lut_indel,
        destination_dir,
        github_client,
    )

    resolved = ResolvedMADCPanel(
        panel_id=panel.panel_id,
        label=panel.label,
        snpid_lut=_resolve_single_file(panel.snpid_lut, "SNP ID LUT", destination_dir, github_client),
        allele_db_base=allele_db_base,
        matchcnt_lut_base=matchcnt_lut_base,
        allele_db_indel=allele_db_indel,
        matchcnt_lut_indel=matchcnt_lut_indel,
        dup_tags=_resolve_optional_file(panel.dup_tags, "duplicate-tags file", destination_dir, github_client),
        first_sample_col=panel.first_sample_col,
        design_len=panel.design_len,
        seq_len=panel.seq_len,
        cov=panel.cov,
        iden=panel.iden,
        code_ver=panel.code_ver,
    )
    validate_madc_panel_files(resolved)
    return resolved


def _resolve_base_pair(
    allele_ref: PanelFileRef,
    matchcnt_ref: PanelFileRef,
    destination_dir: Path,
    github_client: GitHubContentClient,
) -> tuple[Path, Path]:
    if isinstance(allele_ref, Path) and isinstance(matchcnt_ref, Path):
        return allele_ref, matchcnt_ref

    if not (is_github_url(allele_ref) and is_github_url(matchcnt_ref)):
        raise PanelFileResolutionError(
            "Base allele DB and match-count LUT must both be local paths, both GitHub file URLs, "
            "or both GitHub directory URLs."
        )

    allele_gh = _parse_github_url(str(allele_ref))
    matchcnt_gh = _parse_github_url(str(matchcnt_ref))
    if allele_gh.kind == "blob" and matchcnt_gh.kind == "blob":
        return (
            _download_github_file(allele_gh, "base allele DB FASTA", destination_dir, github_client),
            _download_github_file(matchcnt_gh, "base match-count LUT", destination_dir, github_client),
        )
    if allele_gh.kind == "tree" and matchcnt_gh.kind == "tree":
        allele_entries = _directory_entries(github_client.get_content(allele_gh), "base allele DB directory")
        matchcnt_entries = _directory_entries(github_client.get_content(matchcnt_gh), "base match-count LUT directory")
        allele_entry, matchcnt_entry = _choose_latest_base_pair(allele_entries, matchcnt_entries)
        return (
            github_client.download_file(allele_entry, destination_dir),
            github_client.download_file(matchcnt_entry, destination_dir),
        )

    raise PanelFileResolutionError(
        "Base allele DB and match-count LUT GitHub URLs must both point to files or both point to directories."
    )


def _resolve_optional_pair(
    allele_ref: PanelFileRef | None,
    matchcnt_ref: PanelFileRef | None,
    destination_dir: Path,
    github_client: GitHubContentClient,
) -> tuple[Path | None, Path | None]:
    if allele_ref is None and matchcnt_ref is None:
        return None, None
    if allele_ref is None or matchcnt_ref is None:
        raise PanelFileResolutionError("Indel allele DB and match-count LUT must be configured together.")
    return (
        _resolve_single_file(allele_ref, "indel allele DB FASTA", destination_dir, github_client),
        _resolve_single_file(matchcnt_ref, "indel match-count LUT", destination_dir, github_client),
    )


def _resolve_optional_file(
    file_ref: PanelFileRef | None,
    label: str,
    destination_dir: Path,
    github_client: GitHubContentClient,
) -> Path | None:
    if file_ref is None:
        return None
    return _resolve_single_file(file_ref, label, destination_dir, github_client)


def _resolve_single_file(
    file_ref: PanelFileRef,
    label: str,
    destination_dir: Path,
    github_client: GitHubContentClient,
) -> Path:
    if isinstance(file_ref, Path):
        return file_ref
    if not is_github_url(file_ref):
        raise PanelFileResolutionError(f"{label} must be a local path or GitHub file URL.")
    github_ref = _parse_github_url(file_ref)
    if github_ref.kind != "blob":
        raise PanelFileResolutionError(f"{label} must be a GitHub file URL, not a directory URL.")
    return _download_github_file(github_ref, label, destination_dir, github_client)


def _download_github_file(
    github_ref: GitHubContentRef,
    label: str,
    destination_dir: Path,
    github_client: GitHubContentClient,
) -> Path:
    entry = _file_entry(github_client.get_content(github_ref), label)
    return github_client.download_file(entry, destination_dir)


def _choose_latest_base_pair(
    allele_entries: Sequence[Mapping[str, Any]],
    matchcnt_entries: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    allele_by_version = {
        version: entry
        for entry in allele_entries
        if (version := _base_allele_db_version(_entry_name(entry))) is not None
    }
    matchcnt_by_version = {
        version: entry
        for entry in matchcnt_entries
        if (version := _matchcnt_lut_version(_entry_name(entry))) is not None
    }
    versions = sorted(set(allele_by_version) & set(matchcnt_by_version))
    if not versions:
        raise PanelFileResolutionError(
            "Could not find matching versioned allele DB FASTA and match-count LUT files in the GitHub panel directory."
        )
    latest_version = versions[-1]
    return allele_by_version[latest_version], matchcnt_by_version[latest_version]


def _base_allele_db_version(name: str) -> int | None:
    lower_name = name.lower()
    if "allele_db" not in lower_name or "matchcnt" in lower_name or "indel" in lower_name:
        return None
    if not lower_name.endswith((".fa", ".fasta")):
        return None
    return _version_number(lower_name)


def _matchcnt_lut_version(name: str) -> int | None:
    lower_name = name.lower()
    if "matchcnt" not in lower_name or "indel" in lower_name or not lower_name.endswith(".txt"):
        return None
    return _version_number(lower_name)


def _version_number(name: str) -> int | None:
    match = VERSION_RE.search(name)
    return int(match.group("version")) if match else None


def _panel_uses_github(panel: MADCPanel) -> bool:
    return any(
        is_github_url(file_ref)
        for file_ref in [
            panel.snpid_lut,
            panel.allele_db_base,
            panel.matchcnt_lut_base,
            panel.allele_db_indel,
            panel.matchcnt_lut_indel,
            panel.dup_tags,
        ]
        if file_ref is not None
    )


def _resolved_from_local_panel(panel: MADCPanel) -> ResolvedMADCPanel:
    return ResolvedMADCPanel(
        panel_id=panel.panel_id,
        label=panel.label,
        snpid_lut=_local_path(panel.snpid_lut, "SNP ID LUT"),
        allele_db_base=_local_path(panel.allele_db_base, "base allele DB FASTA"),
        matchcnt_lut_base=_local_path(panel.matchcnt_lut_base, "base match-count LUT"),
        allele_db_indel=_local_optional_path(panel.allele_db_indel, "indel allele DB FASTA"),
        matchcnt_lut_indel=_local_optional_path(panel.matchcnt_lut_indel, "indel match-count LUT"),
        dup_tags=_local_optional_path(panel.dup_tags, "duplicate-tags file"),
        first_sample_col=panel.first_sample_col,
        design_len=panel.design_len,
        seq_len=panel.seq_len,
        cov=panel.cov,
        iden=panel.iden,
        code_ver=panel.code_ver,
    )


def _local_path(file_ref: PanelFileRef, label: str) -> Path:
    if not isinstance(file_ref, Path):
        raise PanelFileResolutionError(f"{label} must resolve to a local path before running the workflow.")
    return file_ref


def _local_optional_path(file_ref: PanelFileRef | None, label: str) -> Path | None:
    if file_ref is None:
        return None
    return _local_path(file_ref, label)


def _parse_github_url(url: str) -> GitHubContentRef:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise PanelFileResolutionError(f"Unsupported GitHub URL: {url}")

    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 5 or parts[2] not in {"blob", "tree"}:
        raise PanelFileResolutionError(
            "GitHub panel URLs must use the github.com/<owner>/<repo>/blob/<branch>/<path> "
            "or github.com/<owner>/<repo>/tree/<branch>/<path> form."
        )
    return GitHubContentRef(
        owner=parts[0],
        repo=parts[1],
        kind=parts[2],
        ref=parts[3],
        path="/".join(parts[4:]),
    )


def _github_contents_api_url(content_ref: GitHubContentRef) -> str:
    return (
        "https://api.github.com/repos/"
        f"{quote(content_ref.owner, safe='')}/{quote(content_ref.repo, safe='')}/contents/"
        f"{quote(content_ref.path, safe='/')}?ref={quote(content_ref.ref, safe='')}"
    )


def _file_entry(content: Any, label: str) -> Mapping[str, Any]:
    if isinstance(content, Mapping) and content.get("type") == "file":
        return content
    raise PanelFileResolutionError(f"GitHub {label} URL did not resolve to a file.")


def _directory_entries(content: Any, label: str) -> list[Mapping[str, Any]]:
    if isinstance(content, list):
        return [entry for entry in content if isinstance(entry, Mapping) and entry.get("type") == "file"]
    raise PanelFileResolutionError(f"GitHub {label} URL did not resolve to a directory.")


def _entry_name(file_entry: Mapping[str, Any]) -> str:
    name = file_entry.get("name")
    if not isinstance(name, str) or not name:
        raise PanelFileResolutionError("GitHub file entry is missing a name.")
    return Path(name).name


def _safe_dir_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "panel"


def _http_error_message(prefix: str, url: str, exc: urllib.error.HTTPError) -> str:
    detail = exc.read().decode("utf-8", errors="replace")[:300]
    return f"{prefix} for {url} ({exc.code}): {detail}"
