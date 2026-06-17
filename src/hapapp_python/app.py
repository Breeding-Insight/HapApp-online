from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import webbrowser
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from hapapp_python.env import load_env

load_env()

import dash_bootstrap_components as dbc
import dash_uploader as du
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update
from dash.dependencies import ClientsideFunction
from dash.exceptions import PreventUpdate
from dash_iconify import DashIconify
from flask import Flask, redirect, request

from hapapp_python import config
from hapapp_python.auth import auth_bp, get_current_user, is_authenticated
from hapapp_python.github_panel_files import madc_panel_github_source, resolve_madc_panel_files, resolve_madc_panel_lut
from hapapp_python.dropbox_archive import archive_madc_review_artifacts
from hapapp_python.madc_submission import (
    MADC_SUBMISSION_METADATA_FILENAME,
    MADCSubmissionMetadata,
    build_madc_submission_metadata,
    get_submission_state,
    infer_genotyping_project_id,
    persist_submission_archive_status,
    persist_submission_decision,
    persist_submission_metadata,
    persist_submission_result_provenance,
    write_submission_metadata,
)
from hapapp_python.madc_workflow import build_madc_command, missing_madc_commands
from hapapp_python.madc_validation import (
    MADCPanelCandidate,
    MADCPanelIdentification,
    MADCPanelIdentificationError,
    MADCValidationError,
    identify_raw_madc_panel,
    validate_madc_filename,
    validate_raw_madc,
)
from hapapp_python.orcid_profiles import get_cached_profile
from hapapp_python.panels import (
    ResolvedMADCPanel,
    get_madc_panel,
    load_madc_panels,
)
from hapapp_python.paths import PROJECT_ROOT, VENDOR_UTILS_DIR

from . import __version__

RUN_BASE = Path(tempfile.gettempdir()) / "hapapp_online_runs"
UPLOAD_BASE = RUN_BASE / "uploads"
MAX_UPLOAD_MB = 1000 * 1024
UPLOAD_CHUNK_MB = 16
MADC_PREVIEW_EMPTY_MESSAGE = "Upload an MADC file to display a preview."
MADC_MAIN_RESULT_PATTERN = re.compile(
    r"_snpID_rename_updatedSeq\.csv$|_snpID_rename\.csv$|_v.*\.csv$|\.readme$|_v.*\.fa$|_matchCnt_lut\.txt$"
)
MADC_DB_VERSION_RE = re.compile(r"v(?P<version>\d{3})")
MADC_LOG_FILENAME = "hapapp_madc_workflow.log"
MADC_RUN_METADATA_FILENAME = "hapapp_madc_run_metadata.json"
APP_NAME = "HapApp"
LOGGER = logging.getLogger(__name__)
TERMINAL_AUTO_SCROLL_SCRIPT = """
window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.hapapp = window.dash_clientside.hapapp || {};

window.dash_clientside.hapapp.terminalAutoScroll = function () {
  var terminal = document.getElementById("madc-terminal");
  if (!terminal) {
    return Date.now();
  }

  var threshold = 24;
  var isNearBottom = function () {
    return terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight <= threshold;
  };
  var scrollToBottomAfterRender = function () {
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        terminal.scrollTop = terminal.scrollHeight;
      });
    });
  };

  if (terminal.dataset.scrollHandlerAttached !== "true") {
    terminal.dataset.autoScroll = "true";
    terminal.dataset.scrollHandlerAttached = "true";
    terminal.addEventListener("scroll", function () {
      terminal.dataset.autoScroll = isNearBottom() ? "true" : "false";
    });
  }

  if (terminal.dataset.autoScroll !== "false") {
    scrollToBottomAfterRender();
  }

  return Date.now();
};
"""


@dataclass
class RunState:
    run_id: str
    kind: str
    work_dir: Path
    input_files: set[str]
    command: list[str]
    owner_orcid_id: str = ""
    main_result_files: set[str] = field(default_factory=set)
    log: list[str] = field(default_factory=list)
    status: str = "running"
    returncode: int | None = None
    files: list[str] = field(default_factory=list)
    fixed_madc_file: str | None = None
    log_file: str | None = None
    metadata_file: str | None = None
    error: str | None = None
    submission_status: str = "awaiting_decision"
    freshness_status: str = "unknown"
    review_feedback: str | None = None
    pull_request_url: str | None = None
    incorporation_commit_url: str | None = None
    archive_status: str = "pending"
    archive_error: str | None = None


RUNS: dict[str, RunState] = {}
RUNS_LOCK = threading.Lock()


def _safe_filename(filename: str | None, fallback: str) -> str:
    name = Path(filename or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 1000):
        next_candidate = directory / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
    raise ValueError(f"Could not allocate a unique filename for {filename}")


def _stage_local_file(source: str, destination: Path, label: str, fallback: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"{label} path not found: {source}")

    destination.mkdir(parents=True, exist_ok=True)
    target = _unique_path(destination, _safe_filename(source_path.name, fallback))
    try:
        os.symlink(source_path, target)
    except OSError:
        shutil.copy2(source_path, target)
    return target


def _normalize_file_list(filenames: list[str] | str | None) -> list[str]:
    if filenames is None:
        return []
    if isinstance(filenames, str):
        return [filenames]
    return [filename for filename in filenames if filename]


def _uploaded_file_path(
    filenames: list[str] | str | None,
    upload_id: str | None,
    is_completed: bool | None,
    label: str,
    required: bool = True,
) -> Path | None:
    names = _normalize_file_list(filenames)
    if not names:
        if required:
            raise ValueError(f"Missing required file: {label}")
        return None
    if not is_completed:
        raise ValueError(f"{label} is still uploading")
    if not upload_id:
        raise ValueError(f"Missing upload session for {label}")

    upload_root = UPLOAD_BASE.resolve()
    source = (upload_root / Path(str(upload_id)).name / Path(names[0]).name).resolve()
    try:
        source.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError(f"Invalid upload path for {label}") from exc
    if not source.is_file():
        raise ValueError(f"Uploaded file not found for {label}: {source.name}")
    return source


def _stage_uploaded_file(
    filenames: list[str] | str | None,
    upload_id: str | None,
    is_completed: bool | None,
    destination: Path,
    label: str,
    fallback: str,
    required: bool = True,
) -> Path | None:
    source = _uploaded_file_path(filenames, upload_id, is_completed, label, required=required)
    if source is None:
        return None
    return _stage_local_file(str(source), destination, label, fallback)


def _relative_to_work_dir(path: Path, work_dir: Path) -> str | None:
    try:
        return path.resolve().relative_to(work_dir.resolve()).as_posix()
    except ValueError:
        return None


def _panel_input_files(panel: ResolvedMADCPanel, work_dir: Path) -> set[str]:
    panel_paths = [
        panel.snpid_lut,
        panel.allele_db_base,
        panel.matchcnt_lut_base,
        panel.allele_db_indel,
        panel.matchcnt_lut_indel,
        panel.dup_tags,
    ]
    return {
        relative
        for panel_path in panel_paths
        if panel_path is not None
        if (relative := _relative_to_work_dir(panel_path, work_dir)) is not None
    }


def _bump_madc_db_version(filename: str) -> str | None:
    if not filename.endswith(".fa"):
        return None

    match = MADC_DB_VERSION_RE.search(filename)
    if not match:
        return None

    next_version = f"v{int(match.group('version')) + 1:03d}"
    return filename[: match.start()] + next_version + filename[match.end() :]


def _expected_new_madc_db_files(panel: ResolvedMADCPanel, work_dir: Path) -> set[str]:
    db_input = panel.allele_db_indel or panel.allele_db_base
    next_db_name = _bump_madc_db_version(db_input.name)
    if next_db_name is None:
        return set()

    next_db = db_input.with_name(next_db_name)
    next_lut = db_input.with_name(f"{next_db.stem}_matchCnt_lut.txt")
    return {
        relative
        for output_path in [next_db, next_lut]
        if (relative := _relative_to_work_dir(output_path, work_dir)) is not None
    }


def _identify_uploaded_madc_panel(report: Path) -> MADCPanelIdentification:
    validate_madc_filename(report.name)
    panels = load_madc_panels()
    candidates: list[MADCPanelCandidate] = []
    unavailable: list[str] = []

    with tempfile.TemporaryDirectory(prefix="hapapp_panel_identification_") as tmp_dir:
        work_dir = Path(tmp_dir)
        for panel in panels.values():
            try:
                panel_lut = resolve_madc_panel_lut(panel, work_dir)
            except ValueError as exc:
                unavailable.append(panel.label)
                LOGGER.warning("Could not load SNP ID LUT for panel %s: %s", panel.panel_id, exc)
                continue
            candidates.append(
                MADCPanelCandidate(
                    panel_id=panel.panel_id,
                    label=panel.label,
                    panel_lut_path=panel_lut,
                    first_sample_col=panel.first_sample_col,
                )
            )

        try:
            return identify_raw_madc_panel(report, candidates)
        except MADCPanelIdentificationError as exc:
            if unavailable:
                raise MADCPanelIdentificationError(
                    f"{exc} Panel(s) unavailable for identification: {', '.join(unavailable)}."
                ) from exc
            raise


def _list_files(work_dir: Path, input_files: set[str]) -> list[str]:
    if not work_dir.exists():
        return []

    ignored_inputs = {input_file.rstrip("/") for input_file in input_files}
    files: list[str] = []
    for path in work_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(work_dir).as_posix()
        under_ignored_dir = any(relative.startswith(f"{input_file}/") for input_file in ignored_inputs)
        if relative in ignored_inputs or under_ignored_dir:
            continue
        files.append(relative)
    return sorted(files)


def _write_run_log_file(state: RunState) -> str:
    log_path = state.work_dir / MADC_LOG_FILENAME
    log_path.write_text("\n".join(state.log).rstrip() + "\n", encoding="utf-8")
    return MADC_LOG_FILENAME


def _is_fixed_madc_result(file_path: str) -> bool:
    if "/" in file_path or not file_path.endswith(".csv"):
        return False
    return "_snpID_rename" in file_path and re.search(r"_v[^/]*\.csv$", file_path) is not None


def _fixed_madc_result_file(files: list[str]) -> str | None:
    fixed_files = [file_path for file_path in files if _is_fixed_madc_result(file_path)]
    if not fixed_files:
        return None
    updated_seq = [file_path for file_path in fixed_files if "_updatedSeq_" in file_path]
    return sorted(updated_seq or fixed_files)[-1]


def _append_log(run_id: str, line: str) -> None:
    with RUNS_LOCK:
        state = RUNS.get(run_id)
        if state:
            state.log.append(line.rstrip("\n"))


def _refresh_run_log_file(run_id: str | None) -> None:
    if not run_id:
        return
    with RUNS_LOCK:
        state = RUNS.get(run_id)
        if state:
            state.log_file = _write_run_log_file(state)


def _submission_package_files(state: RunState) -> list[str]:
    return [
        file_path
        for file_path in dict.fromkeys(
            [
                state.fixed_madc_file,
                MADC_SUBMISSION_METADATA_FILENAME,
                *sorted(state.main_result_files),
            ]
        )
        if file_path
    ]


def _write_run_metadata_file(state: RunState, selected_files: list[str] | None = None) -> str:
    accession_count, new_allele_count = _madc_result_summary(state)
    available_files = set(state.files)
    selected_download_files = [
        file_path for file_path in dict.fromkeys(selected_files or []) if file_path in available_files
    ]
    payload = {
        **_read_submission_metadata(state),
        "run_id": state.run_id,
        "workflow_status": state.status,
        "submission_status": state.submission_status,
        "freshness_status": state.freshness_status,
        "review_feedback": state.review_feedback,
        "pull_request_url": state.pull_request_url,
        "incorporation_commit_url": state.incorporation_commit_url,
        "archive_status": state.archive_status,
        "archive_error": state.archive_error,
        "previous_haplotype_database_version": _madc_previous_db_version(state),
        "proposed_haplotype_database_version": _madc_submission_db_version(state),
        "accessions_recognized": accession_count,
        "new_alleles_found": new_allele_count,
        "fixed_madc_file": state.fixed_madc_file,
        "submission_package_files": _submission_package_files(state),
        "selected_download_files": selected_download_files,
        "result_files": list(state.files),
        "main_result_files": sorted(state.main_result_files),
        "input_files": sorted(state.input_files),
        "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    path = state.work_dir / MADC_RUN_METADATA_FILENAME
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return MADC_RUN_METADATA_FILENAME


def _output_checksums(state: RunState) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for relative in _submission_package_files(state):
        path = state.work_dir / relative
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        checksums[relative] = digest.hexdigest()
    return checksums


def _persist_run_result_provenance(state: RunState) -> None:
    if not state.owner_orcid_id or state.status != "completed":
        return
    persist_submission_result_provenance(
        state.run_id,
        state.owner_orcid_id,
        input_database_version=_madc_previous_db_version(state),
        proposed_database_version=_madc_submission_db_version(state),
        output_checksums_json=json.dumps(_output_checksums(state), sort_keys=True),
    )


def _archive_run_results(
    run_id: str | None,
    owner_orcid_id: str,
    *,
    include_fixed_madc: bool,
    include_log: bool,
    selected_files: list[str] | None = None,
) -> None:
    if _snapshot_for_owner(run_id, owner_orcid_id) is None:
        return
    _refresh_run_log_file(run_id)
    state = _snapshot_for_owner(run_id, owner_orcid_id)
    if state is None or state.status != "completed":
        return
    try:
        state.metadata_file = _write_run_metadata_file(state, selected_files)
        messages = archive_madc_review_artifacts(
            state,
            include_fixed_madc=include_fixed_madc,
            include_log=include_log,
        )
        archive_status = (
            "not_configured" if any("archive skipped" in message.lower() for message in messages) else "archived"
        )
        with RUNS_LOCK:
            current = RUNS.get(run_id)
            if current and current.owner_orcid_id == owner_orcid_id:
                current.archive_status = archive_status
                current.archive_error = None
    except Exception as exc:  # noqa: BLE001 - archival should not block download/close.
        _append_log(run_id, f"Dropbox archive failed: {exc}")
        try:
            persist_submission_archive_status(run_id, owner_orcid_id, "failed", str(exc))
        except Exception as status_exc:  # noqa: BLE001 - preserve the original archive failure.
            LOGGER.warning("Could not record archive failure for run %s: %s", run_id, status_exc)
        with RUNS_LOCK:
            current = RUNS.get(run_id)
            if current and current.owner_orcid_id == owner_orcid_id:
                current.archive_status = "failed"
                current.archive_error = str(exc)
        return
    try:
        persist_submission_archive_status(run_id, owner_orcid_id, archive_status)
    except Exception as exc:  # noqa: BLE001 - archive completed even if its status write failed.
        LOGGER.warning("Could not record archive status for run %s: %s", run_id, exc)


def _record_submission_decision(run_id: str | None, owner_orcid_id: str, decision: str) -> bool:
    if not run_id or not owner_orcid_id or decision not in {"submitted_for_review", "declined"}:
        return False

    with RUNS_LOCK:
        state = RUNS.get(run_id)
        if (
            state is None
            or state.owner_orcid_id != owner_orcid_id
            or state.submission_status != "awaiting_decision"
            or (decision == "submitted_for_review" and state.freshness_status == "stale")
        ):
            return False

    try:
        updated_rows = persist_submission_decision(run_id, owner_orcid_id, decision)
        if updated_rows != 1:
            raise RuntimeError("submission decision did not update exactly one awaiting database record")
    except Exception as exc:  # noqa: BLE001 - the UI keeps the decision pending.
        _append_log(run_id, f"Submission decision database write failed: {exc}")
        return False

    with RUNS_LOCK:
        state = RUNS.get(run_id)
        if (
            state is None
            or state.owner_orcid_id != owner_orcid_id
            or state.submission_status != "awaiting_decision"
        ):
            return False
        state.submission_status = decision
        state.log.append(f"Submission decision recorded: {decision}.")
    return True


def _sync_submission_state(run_id: str | None, owner_orcid_id: str) -> None:
    if not run_id or not owner_orcid_id:
        return
    try:
        submission = get_submission_state(run_id, owner_orcid_id)
    except Exception as exc:  # noqa: BLE001 - polling must survive a temporary database outage.
        LOGGER.debug("Could not refresh submission state for run %s: %s", run_id, exc)
        return
    if submission is None:
        return

    with RUNS_LOCK:
        state = RUNS.get(run_id)
        if state is None or state.owner_orcid_id != owner_orcid_id:
            return
        state.submission_status = submission.submission_status
        state.freshness_status = submission.freshness_status
        state.review_feedback = submission.review_feedback
        state.pull_request_url = submission.pull_request_url
        state.incorporation_commit_url = submission.incorporation_commit_url
        state.archive_status = submission.archive_status
        state.archive_error = submission.archive_error


def _run_process(run_id: str) -> None:
    with RUNS_LOCK:
        state = RUNS[run_id]
        command = state.command
        work_dir = state.work_dir
        input_files = set(state.input_files)

    try:
        with subprocess.Popen(
            command,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                _append_log(run_id, line)
            returncode = proc.wait()

        with RUNS_LOCK:
            state = RUNS[run_id]
            state.returncode = returncode
            state.log_file = _write_run_log_file(state)
            state.files = _list_files(work_dir, input_files)
            state.fixed_madc_file = _fixed_madc_result_file(state.files)
            state.status = "completed" if returncode == 0 else "failed"
            if returncode != 0:
                state.error = f"Workflow exited with status {returncode}"
        completed_state = _snapshot_unchecked(run_id)
        if completed_state is not None and completed_state.status == "completed":
            try:
                _persist_run_result_provenance(completed_state)
            except Exception as exc:  # noqa: BLE001 - workflow results remain usable if provenance persistence fails.
                _append_log(run_id, f"Submission result provenance database write failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - surfaced directly in local UI.
        with RUNS_LOCK:
            state = RUNS[run_id]
            state.status = "failed"
            state.error = str(exc)
            state.log.append(f"[ERROR] {exc}")
            state.log_file = _write_run_log_file(state)
            state.files = _list_files(work_dir, input_files)


def _start_run(
    kind: str,
    command: list[str],
    work_dir: Path,
    input_files: set[str],
    owner_orcid_id: str,
    main_result_files: set[str] | None = None,
    run_id: str | None = None,
) -> str:
    run_id = run_id or uuid.uuid4().hex
    state = RunState(
        run_id=run_id,
        kind=kind,
        work_dir=work_dir,
        input_files=input_files,
        command=command,
        owner_orcid_id=owner_orcid_id,
        main_result_files=set(main_result_files or []),
        log=[f"Starting {kind} workflow...", f"Working directory: {work_dir}"],
    )
    with RUNS_LOCK:
        RUNS[run_id] = state

    thread = threading.Thread(target=_run_process, args=(run_id,), daemon=True)
    thread.start()
    return run_id


def _snapshot_unchecked(run_id: str | None) -> RunState | None:
    """Copy internal run state without applying browser-session authorization."""
    if not run_id:
        return None
    with RUNS_LOCK:
        state = RUNS.get(run_id)
        if not state:
            return None
        return RunState(
            run_id=state.run_id,
            kind=state.kind,
            work_dir=state.work_dir,
            input_files=set(state.input_files),
            command=list(state.command),
            owner_orcid_id=state.owner_orcid_id,
            main_result_files=set(state.main_result_files),
            log=list(state.log),
            status=state.status,
            returncode=state.returncode,
            files=list(state.files),
            fixed_madc_file=state.fixed_madc_file,
            log_file=state.log_file,
            metadata_file=state.metadata_file,
            error=state.error,
            submission_status=state.submission_status,
            freshness_status=state.freshness_status,
            review_feedback=state.review_feedback,
            pull_request_url=state.pull_request_url,
            incorporation_commit_url=state.incorporation_commit_url,
            archive_status=state.archive_status,
            archive_error=state.archive_error,
        )


def _snapshot_for_owner(run_id: str | None, owner_orcid_id: str | None) -> RunState | None:
    state = _snapshot_unchecked(run_id)
    if state is None or not owner_orcid_id or state.owner_orcid_id != owner_orcid_id:
        return None
    return state


def _status_text(state: RunState | None) -> str:
    if state is None:
        return "Idle"
    if state.status == "running":
        return "Running"
    if state.status == "completed":
        details = [_submission_status_label(state.submission_status)]
        if state.freshness_status == "stale":
            details.append("Stale")
        return "Complete - " + " - ".join(details)
    return "Failed"


def _submission_status_label(status: str) -> str:
    return {
        "awaiting_decision": "Awaiting decision",
        "submitted_for_review": "Submitted for review",
        "changes_requested": "Changes requested",
        "accepted": "Accepted",
        "incorporated": "Incorporated",
        "rejected": "Rejected",
        "declined": "Declined",
    }.get(status, status.replace("_", " ").title())


def _submission_review_alert(state: RunState) -> dbc.Alert:
    color = {
        "changes_requested": "warning",
        "accepted": "success",
        "incorporated": "success",
        "rejected": "danger",
        "declined": "secondary",
    }.get(state.submission_status, "info")
    children: list = [html.Strong(_submission_status_label(state.submission_status))]
    if state.freshness_status == "stale":
        children.append(
            html.P("This run is stale and must be rerun against the latest GitHub database.", className="mb-0")
        )
    if state.review_feedback:
        children.append(html.P(state.review_feedback, className="mb-0"))
    if state.pull_request_url:
        children.append(html.A("View pull request", href=state.pull_request_url, target="_blank"))
    if state.incorporation_commit_url:
        children.append(html.A("View incorporation commit", href=state.incorporation_commit_url, target="_blank"))
    return dbc.Alert(children, color=color, className="mb-3")


def _status_key(state: RunState | None) -> str:
    if state is None:
        return "idle"
    if state.status == "running":
        return "running"
    if state.status == "completed":
        return "complete"
    return "failed"


def _status_class(state: RunState | None) -> str:
    return f"status-pill status-pill--{_status_key(state)}"


def _run_button_disabled(state: RunState | None) -> bool:
    return state is not None and state.status == "running"


def _processing_button_children():
    return html.Span(
        [html.Span(className="run-spinner", **{"aria-hidden": "true"}), html.Span("Processing...")],
        className="run-button-content",
    )


def _run_button_children(state: RunState | None):
    if _run_button_disabled(state):
        return _processing_button_children()
    return "Process"


def _preflight_status_children():
    return html.Span(
        [
            html.Span(className="preflight-spinner", **{"aria-hidden": "true"}),
            html.Span("Preparing run: retrieving panel files and validating MADC..."),
        ],
        className="preflight-status-content",
    )


def _terminal_text(state: RunState | None) -> str:
    if state is None:
        return "Ready."

    text = "\n".join(state.log).strip()
    if state.error:
        text = f"{text}\n\n{state.error}".strip()
    return text or "Running..."


def _result_options(state: RunState | None) -> list[dict[str, str]]:
    if state is None or state.submission_status == "declined":
        return []
    return [{"label": file_path, "value": file_path} for file_path in state.files]


def _split_madc_result_options(state: RunState | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    main_files: list[dict[str, str]] = []
    diagnostic_files: list[dict[str, str]] = []
    if state is None:
        return main_files, diagnostic_files

    for file_path in state.files:
        option = {"label": file_path, "value": file_path}
        if file_path in state.main_result_files or ("/" not in file_path and MADC_MAIN_RESULT_PATTERN.search(file_path)):
            main_files.append(option)
        else:
            diagnostic_files.append(option)
    return main_files, diagnostic_files


def _madc_result_summary(state: RunState | None) -> tuple[int | None, int | None]:
    if state is None:
        return None, None

    accession_count = None
    processed_madc_file = state.fixed_madc_file
    if processed_madc_file is None:
        processed_candidates = [
            file_path
            for file_path in state.files
            if "/" not in file_path and file_path.endswith(".csv") and "_snpID_rename" in file_path
        ]
        if processed_candidates:
            preferred_candidates = [path for path in processed_candidates if "_dup" not in path]
            processed_madc_file = sorted(preferred_candidates or processed_candidates)[-1]

    if processed_madc_file:
        processed_madc_path = state.work_dir / processed_madc_file
        try:
            with processed_madc_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
                header = next(csv.reader(stream))
            allele_sequence_index = header.index("AlleleSequence")
            accession_count = max(0, len(header) - allele_sequence_index - 1)
        except (OSError, StopIteration, ValueError, csv.Error):
            accession_count = None

    new_allele_count = None
    pattern = re.compile(r"Number of NEW alleles found in this report:\s*(\d+)")
    for line in reversed(state.log):
        if match := pattern.search(line):
            new_allele_count = int(match.group(1))
            break

    return accession_count, new_allele_count


def _madc_result_summary_cards(state: RunState | None) -> html.Div:
    accession_count, new_allele_count = _madc_result_summary(state)

    def card(label: str, value: int | None) -> html.Div:
        return html.Div(
            [
                html.Div(f"{value:,}" if value is not None else "Not available", className="results-summary-value"),
                html.Div(label, className="results-summary-label"),
            ],
            className="results-summary-card",
        )

    return html.Div(
        [
            card("Accessions recognized", accession_count),
            card("New alleles found", new_allele_count),
        ],
        className="results-summary",
    )


def _madc_submission_db_version(state: RunState | None) -> str | None:
    if state is None:
        return None
    for file_path in sorted(state.main_result_files):
        if file_path.endswith(".fa") and (match := MADC_DB_VERSION_RE.search(Path(file_path).name)):
            return f"v{match.group('version')}"
    return None


def _madc_previous_db_version(state: RunState | None) -> str | None:
    if state is None:
        return None

    versions = [
        int(match.group("version"))
        for file_path in state.input_files
        if file_path.endswith(".fa")
        if (match := MADC_DB_VERSION_RE.search(Path(file_path).name))
    ]
    return f"v{max(versions):03d}" if versions else None


def _selected_submission_summary(state: RunState | None, selected: list[str]) -> html.Div:
    accession_count, new_allele_count = _madc_result_summary(state)
    available = set(state.files if state else [])
    selected_files = [file_path for file_path in selected if file_path in available]
    proposed_db_version = _madc_submission_db_version(state)
    previous_db_version = _madc_previous_db_version(state)
    metadata = _read_submission_metadata(state)
    submitter_name = metadata.get("submitter_display_name")
    submitter_orcid = metadata.get("submitter_orcid_id")
    submitter = (
        f"{submitter_name} (ORCID: {submitter_orcid})"
        if submitter_name and submitter_orcid
        else submitter_name or submitter_orcid or "Not available"
    )
    submission_files = _submission_package_files(state) if state else []

    return html.Div(
        [
            _madc_result_summary_cards(state),
            html.Div(
                html.Button(
                    DashIconify(icon="mdi:pencil", width=16),
                    id="madc-submission-metadata-edit",
                    className="btn btn-outline-secondary btn-sm",
                    title="Edit metadata",
                    type="button",
                    **{"aria-label": "Edit metadata"},
                ),
                className="submission-summary-actions",
            ),
            html.Dl(
                [
                    html.Dt("Run ID"),
                    html.Dd(state.run_id if state else "Not available"),
                    html.Dt("Formal project ID"),
                    html.Dd(metadata.get("inferred_project_id") or "Not available"),
                    html.Dt("Project name"),
                    html.Dd(metadata.get("informal_project_name") or "Not provided"),
                    html.Dt("Species panel"),
                    html.Dd(metadata.get("panel_label") or "Not available"),
                    html.Dt("Submitted by"),
                    html.Dd(submitter),
                    html.Dt("Project Owner/Contact"),
                    html.Dd(metadata.get("submitted_for_name") or "Not available"),
                    html.Dt("Institution"),
                    html.Dd(metadata.get("submitted_for_institution") or "Not available"),
                    html.Dt("Location"),
                    html.Dd(metadata.get("submitted_for_location") or "Not available"),
                    html.Dt("Email"),
                    html.Dd(metadata.get("submitted_for_email") or "Not available"),
                    html.Dt("Previous haplotype database version"),
                    html.Dd(previous_db_version or "Not available"),
                    html.Dt("Proposed haplotype database version"),
                    html.Dd(proposed_db_version or "Not available"),
                    html.Dt("Accessions recognized"),
                    html.Dd(f"{accession_count:,}" if accession_count is not None else "Not available"),
                    html.Dt("New alleles found"),
                    html.Dd(f"{new_allele_count:,}" if new_allele_count is not None else "Not available"),
                ],
                className="submission-confirmation-details",
            ),
            html.H5("Submission package"),
            html.Ul([html.Li(file_path) for file_path in submission_files], className="submission-confirmation-files"),
            html.H5("Files downloaded to your computer after submission"),
            html.Ul([html.Li(file_path) for file_path in selected_files], className="submission-confirmation-files"),
        ]
    )


def _editable_submission_summary(state: RunState | None, selected: list[str]) -> html.Div:
    metadata = _read_submission_metadata(state)

    def editable_value(component_id: str, key: str, *, required: bool = True) -> dbc.Input:
        return dbc.Input(
            id=component_id,
            value=metadata.get(key) or "",
            size="sm",
            required=required,
        )

    accession_count, new_allele_count = _madc_result_summary(state)
    available = set(state.files if state else [])
    selected_files = [file_path for file_path in selected if file_path in available]
    proposed_db_version = _madc_submission_db_version(state)
    previous_db_version = _madc_previous_db_version(state)
    submitter_name = metadata.get("submitter_display_name")
    submitter_orcid = metadata.get("submitter_orcid_id")
    submitter = (
        f"{submitter_name} (ORCID: {submitter_orcid})"
        if submitter_name and submitter_orcid
        else submitter_name or submitter_orcid or "Not available"
    )
    submission_files = _submission_package_files(state) if state else []

    return html.Div(
        [
            _madc_result_summary_cards(state),
            html.Dl(
                [
                    html.Dt("Run ID"),
                    html.Dd(state.run_id if state else "Not available"),
                    html.Dt(_required_label("Formal project ID")),
                    html.Dd(editable_value("madc-summary-formal-project-id", "inferred_project_id")),
                    html.Dt("Project name"),
                    html.Dd(
                        editable_value(
                            "madc-summary-informal-project-name",
                            "informal_project_name",
                            required=False,
                        )
                    ),
                    html.Dt("Species panel"),
                    html.Dd(metadata.get("panel_label") or "Not available"),
                    html.Dt("Submitted by"),
                    html.Dd(submitter),
                    html.Dt(_required_label("Project Owner/Contact")),
                    html.Dd(editable_value("madc-summary-submitted-for-name", "submitted_for_name")),
                    html.Dt(_required_label("Institution")),
                    html.Dd(editable_value("madc-summary-submitted-for-institution", "submitted_for_institution")),
                    html.Dt(_required_label("Location")),
                    html.Dd(editable_value("madc-summary-submitted-for-location", "submitted_for_location")),
                    html.Dt(_required_label("Email")),
                    html.Dd(
                        dbc.Input(
                            id="madc-summary-submitted-for-email",
                            value=metadata.get("submitted_for_email") or "",
                            type="email",
                            size="sm",
                            required=True,
                        )
                    ),
                    html.Dt("Previous haplotype database version"),
                    html.Dd(previous_db_version or "Not available"),
                    html.Dt("Proposed haplotype database version"),
                    html.Dd(proposed_db_version or "Not available"),
                    html.Dt("Accessions recognized"),
                    html.Dd(f"{accession_count:,}" if accession_count is not None else "Not available"),
                    html.Dt("New alleles found"),
                    html.Dd(f"{new_allele_count:,}" if new_allele_count is not None else "Not available"),
                ],
                className="submission-confirmation-details submission-confirmation-details--editable",
            ),
            html.H5("Submission package"),
            html.Ul([html.Li(file_path) for file_path in submission_files], className="submission-confirmation-files"),
            html.H5("Files downloaded to your computer after submission"),
            html.Ul([html.Li(file_path) for file_path in selected_files], className="submission-confirmation-files"),
        ]
    )


def _read_submission_metadata(state: RunState | None) -> dict:
    if state is None:
        return {}
    try:
        payload = json.loads((state.work_dir / MADC_SUBMISSION_METADATA_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_submission_metadata_edits(
    state: RunState | None,
    owner_orcid_id: str,
    *,
    inferred_project_id: str | None,
    informal_project_name: str | None,
    submitted_for_name: str | None,
    submitted_for_institution: str | None,
    submitted_for_location: str | None,
    submitted_for_email: str | None,
) -> None:
    if state is None or state.owner_orcid_id != owner_orcid_id or state.submission_status != "awaiting_decision":
        raise ValueError("This submission metadata can no longer be edited.")

    missing_metadata = _missing_submission_metadata_fields(
        inferred_project_id=inferred_project_id,
        submitted_for_name=submitted_for_name,
        submitted_for_institution=submitted_for_institution,
        submitted_for_location=submitted_for_location,
        submitted_for_email=submitted_for_email,
    )
    if missing_metadata:
        raise ValueError("Complete required submission metadata: " + ", ".join(missing_metadata))

    payload = _read_submission_metadata(state)
    editable_values = {
        "inferred_project_id": inferred_project_id,
        "informal_project_name": informal_project_name,
        "submitted_for_name": submitted_for_name,
        "submitted_for_institution": submitted_for_institution,
        "submitted_for_location": submitted_for_location,
        "submitted_for_email": submitted_for_email,
    }
    payload.update({key: (value or "").strip() or None for key, value in editable_values.items()})
    try:
        metadata = MADCSubmissionMetadata(**payload)
    except TypeError as exc:
        raise ValueError("The stored submission metadata could not be updated.") from exc

    persist_submission_metadata(metadata)
    write_submission_metadata(state.work_dir, metadata)


def _option_values(options: list[dict[str, str]]) -> list[str]:
    return [option["value"] for option in options]


def _zip_selected(
    run_id: str | None,
    owner_orcid_id: str,
    selected: list[str] | None,
    default_all: bool = True,
) -> bytes:
    state = _snapshot_for_owner(run_id, owner_orcid_id)
    if state is None:
        raise ValueError("No run is available for download")
    if state.submission_status == "declined":
        raise ValueError("This run was declined and its results are unavailable")

    available = set(state.files)
    chosen = state.files if default_all and not selected else selected or []
    chosen = [item for item in chosen if item in available]
    if not chosen:
        raise ValueError("No result files are available for download")

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in chosen:
            archive.write(state.work_dir / relative, arcname=relative)
    return payload.getvalue()


def _detect_delimiter(header_line: str) -> str:
    return "\t" if header_line.count("\t") > header_line.count(",") else ","


def _preview_from_text_stream(
    stream,
    max_rows: int = 20,
    max_columns: int = 40,
) -> tuple[list[dict[str, str]], list[dict[str, str]], int]:
    header_line = stream.readline()
    if not header_line:
        return [], [], 0

    delimiter = _detect_delimiter(header_line)
    try:
        header = next(csv.reader([header_line], delimiter=delimiter))
    except csv.Error as exc:
        raise ValueError(f"Could not parse header: {exc}") from exc

    column_ids = [f"col_{index}" for index in range(min(len(header), max_columns))]
    columns = [
        {"name": str(name or f"Column {index + 1}"), "id": column_id}
        for index, (name, column_id) in enumerate(zip(header[:max_columns], column_ids, strict=False))
    ]

    records: list[dict[str, str]] = []
    for line in stream:
        if len(records) >= max_rows:
            break
        try:
            row = next(csv.reader([line], delimiter=delimiter))
        except csv.Error:
            row = [line.rstrip("\n")]
        values = row[: len(column_ids)]
        if len(values) < len(column_ids):
            values.extend([""] * (len(column_ids) - len(values)))
        records.append({column_id: str(value) for column_id, value in zip(column_ids, values, strict=False)})

    return columns, records, len(header)


def _preview_from_path(source_path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], int]:
    with source_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        return _preview_from_text_stream(stream)


def _current_profile_snapshot(orcid_id: str | None) -> dict | None:
    if not orcid_id:
        return None
    try:
        return get_cached_profile(orcid_id)
    except Exception as exc:  # noqa: BLE001 - metadata enrichment should not block processing.
        LOGGER.warning("Could not load cached ORCID profile for %s: %s", orcid_id, exc)
        return None


UPLOAD_STYLE = {
    "backgroundColor": "#fbfcfd",
    "borderColor": "#9aa8b5",
    "borderRadius": "4px",
    "borderStyle": "dashed",
    "borderWidth": "1px",
    "color": "#263746",
    "cursor": "pointer",
    "fontSize": "13px",
    "fontWeight": "600",
    "lineHeight": "1.2",
    "marginBottom": "0",
    "minHeight": "35px",
    "padding": "7px 9px",
    "textAlign": "left",
    "width": "100%",
}


def _uploader_box(component_id: str, label: str, filetypes: list[str] | None = None) -> html.Div:
    return html.Div(
        du.Upload(
            id=component_id,
            text=label,
            text_completed="Selected: ",
            cancel_button=True,
            pause_button=False,
            filetypes=filetypes,
            max_file_size=MAX_UPLOAD_MB,
            chunk_size=UPLOAD_CHUNK_MB,
            default_style=UPLOAD_STYLE,
            max_files=1,
        ),
        className="upload-wrap",
    )


def _madc_results_modal() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Processed Files"), close_button=False),
            dbc.ModalBody(
                [
                    html.Div(id="madc-results-summary"),
                    html.Div(id="madc-results-message", className="results-message"),
                    dcc.Dropdown(id="madc-results-select", multi=True, style={"display": "none"}),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Strong("Choose files to download to your computer."),
                                    " These checkbox selections do not change the files submitted to the "
                                    "haplotype database.",
                                ],
                                className="results-message",
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.H4("Main Files"),
                                            dcc.Checklist(
                                                id="madc-main-files",
                                                options=[],
                                                value=[],
                                                className="results-checklist",
                                            ),
                                        ],
                                        md=6,
                                    ),
                                    dbc.Col(
                                        [
                                            html.H4("Diagnostic Files"),
                                            dcc.Checklist(
                                                id="madc-diagnostic-files",
                                                options=[],
                                                value=[],
                                                className="results-checklist",
                                            ),
                                        ],
                                        md=6,
                                    ),
                                ],
                                className="results-file-row g-3",
                            ),
                        ],
                        id="madc-results-file-groups",
                        style={"display": "none"},
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel Run and Decline Submission",
                        id="madc-results-decline",
                        color="danger",
                        outline=True,
                    ),
                    dbc.Button(
                        "Review Submission and Download",
                        id="madc-download-button",
                        color="success",
                        disabled=True,
                    ),
                ]
            ),
        ],
        id="madc-results-modal",
        centered=True,
        size="lg",
        backdrop="static",
        keyboard=False,
    )


def _madc_submission_confirmation_modal() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Confirm Haplotype Database Submission"), close_button=False),
            dbc.ModalBody(
                [
                    html.P(
                        "Submitting will send this run for review and archive its processed MADC and workflow log."
                    ),
                    html.Div(id="madc-submission-edit-message"),
                    html.Div(id="madc-submission-confirmation-summary"),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button("Back", id="madc-submission-confirmation-back", color="secondary", outline=True),
                    dbc.Button(
                        "Confirm Submit and Download",
                        id="madc-submission-confirmation-submit",
                        color="success",
                    ),
                ],
                id="madc-submission-confirmation-footer",
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel Edits",
                        id="madc-submission-metadata-cancel",
                        color="secondary",
                        outline=True,
                    ),
                    dbc.Button(
                        "Save Edits",
                        id="madc-submission-metadata-save",
                        color="primary",
                    ),
                ],
                id="madc-submission-edit-footer",
                style={"display": "none"},
            ),
        ],
        id="madc-submission-confirmation-modal",
        centered=True,
        size="lg",
        backdrop="static",
        keyboard=False,
    )


def _madc_verification_details(exc: MADCValidationError) -> list:
    details: list = []
    if exc.errors:
        details.extend(
            [
                html.H5("Errors"),
                html.Ul([html.Li(error) for error in exc.errors], className="verification-list"),
            ]
        )
    if exc.warnings:
        details.extend(
            [
                html.H5("Warnings"),
                html.Ul([html.Li(warning) for warning in exc.warnings], className="verification-list"),
            ]
        )
    details.append(html.P("Please contact Breeding Insight for assistance.", className="verification-contact"))
    return details


def _madc_verification_modal() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("MADC Verification Failed"), close_button=False),
            dbc.ModalBody(html.Div(id="madc-verification-details", className="verification-details")),
            dbc.ModalFooter(dbc.Button("Close", id="madc-verification-close", color="secondary", outline=True)),
        ],
        id="madc-verification-modal",
        centered=True,
        size="lg",
    )


def _required_label(label: str) -> list:
    return [label, html.Span(" *", className="required-marker", **{"aria-hidden": "true"})]


def _metadata_input(component_id: str, label: str, placeholder: str = "", *, required: bool = True) -> html.Div:
    return html.Div(
        [
            dbc.Label(_required_label(label) if required else label, html_for=component_id),
            dbc.Input(id=component_id, placeholder=placeholder, size="sm", required=required),
        ],
        className="field-group",
    )


def _profile_text(profile: dict | None, *keys: str) -> str:
    profile = profile or {}
    for key in keys:
        value = profile.get(key)
        if value:
            return str(value).strip()
    return ""


def _orcid_metadata_defaults() -> tuple[str, str, str, str]:
    current_user = get_current_user()
    profile = _current_profile_snapshot((current_user or {}).get("orcid_id"))
    return (
        _profile_text(profile, "display_name"),
        _profile_text(profile, "institution"),
        _profile_text(profile, "location"),
        _profile_text(profile, "public_email"),
    )


def _missing_submission_metadata_fields(
    *,
    inferred_project_id: str | None,
    submitted_for_name: str | None,
    submitted_for_institution: str | None,
    submitted_for_location: str | None,
    submitted_for_email: str | None,
) -> list[str]:
    required_fields = [
        ("Formal project ID", inferred_project_id),
        ("Project Owner/Contact", submitted_for_name),
        ("Institution", submitted_for_institution),
        ("Location", submitted_for_location),
        ("Email", submitted_for_email),
    ]
    return [label for label, value in required_fields if not (value or "").strip()]


def _madc_tab() -> html.Div:
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.H2("MADC Hap Assignment"),
                                html.Div(id="madc-alert", className="alert-slot"),
                                html.Div(
                                    id="madc-preflight-status",
                                    className="preflight-status",
                                    **{"aria-live": "polite"},
                                ),
                                html.H3("Inputs"),
                                _uploader_box("madc-report-upload", "MADC report (.csv)", ["csv", "txt"]),
                                html.Div(
                                    [
                                        dbc.Label("Species panel"),
                                        html.Div(
                                            dcc.Loading(
                                                html.Div(
                                                    id="madc-panel-value",
                                                    className="identified-panel-value identified-panel-value--empty",
                                                ),
                                                type="circle",
                                            ),
                                            className="panel-identification-loading",
                                        ),
                                    ],
                                    className="field-group",
                                ),
                                html.Div(
                                    [
                                        html.H3("Submission Metadata"),
                                        html.Div(
                                            [
                                                dbc.Label(
                                                    _required_label("Formal project ID"),
                                                    html_for="madc-formal-project-id",
                                                ),
                                                dbc.Input(
                                                    id="madc-formal-project-id",
                                                    size="sm",
                                                    required=True,
                                                    placeholder="ID number provided by DArT",
                                                ),
                                            ],
                                            className="field-group",
                                        ),
                                        _metadata_input(
                                            "madc-informal-project-name",
                                            "Informal project name (optional)",
                                            "Short description or name of the project",
                                            required=False,
                                        ),
                                        _metadata_input(
                                            "madc-submitted-for-name",
                                            "Project Owner/Contact",
                                            "Project owner or contact name",
                                        ),
                                        _metadata_input(
                                            "madc-submitted-for-institution",
                                            "Institution",
                                            "Institution name",
                                        ),
                                        _metadata_input(
                                            "madc-submitted-for-location",
                                            "Location",
                                            "City, state",
                                        ),
                                        _metadata_input("madc-submitted-for-email", "Email", "contact@example.org"),
                                        dbc.Toast(
                                            (
                                                "Make sure the highlighted Submission Metadata section is accurate "
                                                "before submitting. This information will be associated with the "
                                                "processed MADC."
                                            ),
                                            id="madc-metadata-review-toast",
                                            header="Review Submission Metadata",
                                            is_open=False,
                                            dismissable=True,
                                            duration=None,
                                            className="metadata-review-toast",
                                        ),
                                    ],
                                    id="madc-submission-metadata",
                                    className="submission-metadata",
                                    style={"display": "none"},
                                ),
                                dbc.Button(
                                    "Process",
                                    id="madc-run-button",
                                    color="primary",
                                    className="run-button",
                                    disabled=True,
                                ),
                                html.H3("Results"),
                                dbc.Button(
                                    "View Results",
                                    id="madc-results-button",
                                    color="success",
                                    className="results-button",
                                ),
                            ],
                            className="input-panel",
                        ),
                        lg=4,
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.H3("Terminal"),
                                        html.Span(id="madc-status", className="status-pill"),
                                    ],
                                    className="terminal-header",
                                ),
                                html.Pre(id="madc-terminal", className="terminal"),
                            ],
                            className="output-panel",
                        ),
                        lg=8,
                    ),
                ],
                className="main-row",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H3("MADC Preview"),
                            html.Div(id="madc-preview-message", className="preview-message"),
                        ],
                        className="preview-heading",
                    ),
                    html.Div(MADC_PREVIEW_EMPTY_MESSAGE, id="madc-preview-empty", className="preview-empty"),
                    dash_table.DataTable(
                        id="madc-preview-table",
                        page_size=10,
                        style_as_list_view=True,
                        style_table={"overflowX": "auto"},
                        style_cell={
                            "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                            "fontSize": "12px",
                            "maxWidth": 240,
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                        },
                        style_header={"fontWeight": "600"},
                    ),
                ],
                className="preview-panel",
            ),
            _madc_results_modal(),
            _madc_submission_confirmation_modal(),
            _madc_verification_modal(),
        ]
    )


def _landing_page() -> str:
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>HapApp</title>
        <style>
          body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; }
          main { min-height: 100vh; display: grid; place-items: center; background: #f5f8fa; color: #263746; }
          section { width: min(520px, calc(100vw - 32px)); }
          h1 { margin: 0 0 8px; font-size: 40px; }
          p { margin: 0 0 24px; color: #52606d; }
          a { display: inline-block; background: #A6CE39; color: #1f2d1f; padding: 10px 14px; border-radius: 4px;
              text-decoration: none; font-weight: 700; }
        </style>
      </head>
      <body>
        <main>
          <section>
            <h1>HapApp</h1>
            <p>Microhaplotype assignment workflow</p>
            <a href="/auth/login">Sign in with ORCID iD</a>
          </section>
        </main>
      </body>
    </html>
    """


def create_server() -> Flask:
    server = Flask(__name__)
    server.secret_key = config.SECRET_KEY
    server.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.PUBLIC_URL.startswith("https://"),
    )
    server.register_blueprint(auth_bp)

    @server.before_request
    def use_public_origin():
        if config.PUBLIC_URL and request.host != config.PUBLIC_HOST:
            return redirect(f"{config.PUBLIC_URL}{request.full_path.rstrip('?')}", code=302)
        return None

    @server.route("/")
    def landing_page():
        if is_authenticated():
            return redirect("/app/")
        return _landing_page()

    @server.before_request
    def require_auth_for_app():
        if request.path.startswith("/auth/") or request.path == "/":
            return None
        if request.path.startswith("/app") and not is_authenticated():
            dash_internal = (
                request.path.startswith("/app/_dash-")
                or request.path.startswith("/app/_favicon")
                or request.path.startswith("/app/assets/")
                or request.path.startswith("/app/_dash-component-suites/")
            )
            if not dash_internal or request.method != "GET":
                return redirect("/")
        return None

    return server


def create_app() -> Dash:
    server = create_server()
    app = Dash(
        __name__,
        server=server,
        url_base_pathname="/app/",
        external_stylesheets=[dbc.themes.FLATLY],
        assets_folder=str(PROJECT_ROOT / "assets"),
        suppress_callback_exceptions=True,
        title=APP_NAME,
    )
    du.configure_upload(app, str(UPLOAD_BASE))
    app.index_string = f"""
    <!DOCTYPE html>
    <html>
      <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
      </head>
      <body>
        {{%app_entry%}}
        <footer>
          <script>{TERMINAL_AUTO_SCROLL_SCRIPT}</script>
          {{%config%}}
          {{%scripts%}}
          {{%renderer%}}
        </footer>
      </body>
    </html>
    """

    app.layout = dbc.Container(
        [
            dcc.Store(id="madc-run-id"),
            dcc.Store(id="madc-panel-id"),
            dcc.Interval(id="run-poller", interval=1000, n_intervals=0),
            dcc.Download(id="madc-download"),
            dcc.Store(id="madc-submission-request"),
            dcc.Store(id="madc-terminal-scroll"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H1(APP_NAME),
                                    html.Span(f"v{__version__}", className="app-version"),
                                ],
                                className="app-title-line",
                            ),
                            html.P("Microhaplotype assignment workflow"),
                        ],
                        className="app-title",
                    ),
                    html.Div(
                        [
                            html.Span("Utilities"),
                            html.Code(str(VENDOR_UTILS_DIR.relative_to(PROJECT_ROOT))),
                            html.A("Logout", href="/auth/logout", className="logout-link"),
                        ],
                        className="vendor-path",
                    ),
                ],
                className="app-header",
            ),
            _madc_tab(),
        ],
        fluid=True,
        className="app-shell",
    )

    register_callbacks(app)
    return app


def register_callbacks(app: Dash) -> None:
    app.clientside_callback(
        ClientsideFunction(namespace="hapapp", function_name="terminalAutoScroll"),
        Output("madc-terminal-scroll", "data"),
        Input("madc-terminal", "children"),
    )

    @app.callback(
        Output("madc-submission-confirmation-summary", "children", allow_duplicate=True),
        Output("madc-submission-confirmation-footer", "style"),
        Output("madc-submission-edit-footer", "style"),
        Output("madc-submission-edit-message", "children"),
        Input("madc-submission-metadata-edit", "n_clicks"),
        State("madc-run-id", "data"),
        State("madc-main-files", "value"),
        State("madc-diagnostic-files", "value"),
        prevent_initial_call=True,
    )
    def edit_madc_submission_metadata(
        _edit_clicks,
        run_id,
        main_selected,
        diagnostic_selected,
    ):
        if not _edit_clicks:
            raise PreventUpdate

        owner_orcid_id = (get_current_user() or {}).get("orcid_id", "")
        state = _snapshot_for_owner(run_id, owner_orcid_id)
        selected = list(dict.fromkeys((main_selected or []) + (diagnostic_selected or [])))

        return _editable_submission_summary(state, selected), {"display": "none"}, {}, []

    @app.callback(
        Output("madc-submission-confirmation-summary", "children", allow_duplicate=True),
        Output("madc-submission-confirmation-footer", "style", allow_duplicate=True),
        Output("madc-submission-edit-footer", "style", allow_duplicate=True),
        Output("madc-submission-edit-message", "children", allow_duplicate=True),
        Input("madc-submission-metadata-cancel", "n_clicks"),
        State("madc-run-id", "data"),
        State("madc-main-files", "value"),
        State("madc-diagnostic-files", "value"),
        prevent_initial_call=True,
    )
    def cancel_madc_submission_metadata_edits(
        _cancel_clicks,
        run_id,
        main_selected,
        diagnostic_selected,
    ):
        if not _cancel_clicks:
            raise PreventUpdate

        owner_orcid_id = (get_current_user() or {}).get("orcid_id", "")
        state = _snapshot_for_owner(run_id, owner_orcid_id)
        selected = list(dict.fromkeys((main_selected or []) + (diagnostic_selected or [])))
        return _selected_submission_summary(state, selected), {}, {"display": "none"}, []

    @app.callback(
        Output("madc-submission-confirmation-summary", "children", allow_duplicate=True),
        Output("madc-submission-confirmation-footer", "style", allow_duplicate=True),
        Output("madc-submission-edit-footer", "style", allow_duplicate=True),
        Output("madc-submission-edit-message", "children", allow_duplicate=True),
        Input("madc-submission-metadata-save", "n_clicks"),
        State("madc-run-id", "data"),
        State("madc-main-files", "value"),
        State("madc-diagnostic-files", "value"),
        State("madc-summary-formal-project-id", "value"),
        State("madc-summary-informal-project-name", "value"),
        State("madc-summary-submitted-for-name", "value"),
        State("madc-summary-submitted-for-institution", "value"),
        State("madc-summary-submitted-for-location", "value"),
        State("madc-summary-submitted-for-email", "value"),
        prevent_initial_call=True,
    )
    def save_madc_submission_metadata(
        _save_clicks,
        run_id,
        main_selected,
        diagnostic_selected,
        inferred_project_id,
        informal_project_name,
        submitted_for_name,
        submitted_for_institution,
        submitted_for_location,
        submitted_for_email,
    ):
        if not _save_clicks:
            raise PreventUpdate

        owner_orcid_id = (get_current_user() or {}).get("orcid_id", "")
        state = _snapshot_for_owner(run_id, owner_orcid_id)
        selected = list(dict.fromkeys((main_selected or []) + (diagnostic_selected or [])))
        try:
            _save_submission_metadata_edits(
                state,
                owner_orcid_id,
                inferred_project_id=inferred_project_id,
                informal_project_name=informal_project_name,
                submitted_for_name=submitted_for_name,
                submitted_for_institution=submitted_for_institution,
                submitted_for_location=submitted_for_location,
                submitted_for_email=submitted_for_email,
            )
        except Exception as exc:  # noqa: BLE001 - shown in UI.
            return (
                no_update,
                {"display": "none"},
                {},
                dbc.Alert(str(exc), color="danger", className="submission-edit-alert"),
            )
        return (
            _selected_submission_summary(state, selected),
            {},
            {"display": "none"},
            dbc.Alert("Submission metadata updated.", color="success", className="submission-edit-alert"),
        )

    @app.callback(
        Output("madc-run-id", "data", allow_duplicate=True),
        Output("madc-alert", "children", allow_duplicate=True),
        Output("madc-preflight-status", "children", allow_duplicate=True),
        Output("madc-preflight-status", "className", allow_duplicate=True),
        Output("madc-verification-modal", "is_open", allow_duplicate=True),
        Output("madc-verification-details", "children", allow_duplicate=True),
        Input("madc-report-upload", "fileNames"),
        Input("madc-report-upload", "isCompleted"),
        prevent_initial_call=True,
    )
    def reset_madc_run_for_new_input(_filenames, _is_completed):
        return None, [], [], "preflight-status", False, []

    @app.callback(
        Output("madc-results-modal", "is_open"),
        Output("madc-results-summary", "children"),
        Output("madc-results-message", "children"),
        Output("madc-results-file-groups", "style"),
        Output("madc-main-files", "options"),
        Output("madc-main-files", "value"),
        Output("madc-diagnostic-files", "options"),
        Output("madc-diagnostic-files", "value"),
        Output("madc-results-decline", "style"),
        Output("madc-results-decline", "children"),
        Output("madc-results-decline", "color"),
        Output("madc-download-button", "children"),
        Output("madc-submission-request", "data"),
        Output("madc-submission-confirmation-modal", "is_open"),
        Output("madc-submission-confirmation-summary", "children"),
        Input("madc-results-button", "n_clicks"),
        Input("madc-results-decline", "n_clicks"),
        Input("madc-download-button", "n_clicks"),
        Input("madc-submission-confirmation-back", "n_clicks"),
        Input("madc-submission-confirmation-submit", "n_clicks"),
        State("madc-run-id", "data"),
        State("madc-main-files", "value"),
        State("madc-diagnostic-files", "value"),
        prevent_initial_call=True,
    )
    def toggle_madc_results_modal(
        _open_clicks,
        _decline_clicks,
        _download_clicks,
        _confirmation_back_clicks,
        _confirmation_submit_clicks,
        run_id,
        main_selected,
        diagnostic_selected,
    ):
        owner_orcid_id = (get_current_user() or {}).get("orcid_id", "")
        _sync_submission_state(run_id, owner_orcid_id)
        if ctx.triggered_id == "madc-results-decline":
            state = _snapshot_for_owner(run_id, owner_orcid_id)
            if state and state.submission_status == "awaiting_decision":
                if _record_submission_decision(run_id, owner_orcid_id, "declined"):
                    _archive_run_results(
                        run_id,
                        owner_orcid_id,
                        include_fixed_madc=False,
                        include_log=True,
                    )
                else:
                    return (
                        True,
                        no_update,
                        dbc.Alert(
                            "The decline decision could not be recorded. The run remains awaiting a decision.",
                            color="danger",
                        ),
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                        no_update,
                        False,
                        no_update,
                    )
            return (
                False,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                False,
                no_update,
            )

        if ctx.triggered_id == "madc-submission-confirmation-back":
            return (True,) + (no_update,) * 12 + (False, no_update)

        if ctx.triggered_id in {"madc-download-button", "madc-submission-confirmation-submit"}:
            selected = list(dict.fromkeys((main_selected or []) + (diagnostic_selected or [])))
            state = _snapshot_for_owner(run_id, owner_orcid_id)
            if state is None or state.submission_status == "declined":
                return (False,) + (no_update,) * 12 + (False, no_update)

            if ctx.triggered_id == "madc-download-button" and state.submission_status == "awaiting_decision":
                return (
                    False,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    True,
                    _selected_submission_summary(state, selected),
                )

            request_data = {"request_id": uuid.uuid4().hex, "run_id": run_id, "selected": selected}
            return (False,) + (no_update,) * 11 + (request_data, False, no_update)

        state = _snapshot_for_owner(run_id, owner_orcid_id)
        if not state or not state.files or state.submission_status == "declined":
            return (
                False,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                False,
                no_update,
            )

        main_options, diagnostic_options = _split_madc_result_options(state)
        awaiting_decision = state.submission_status == "awaiting_decision"
        stale_awaiting_decision = awaiting_decision and state.freshness_status == "stale"
        return (
            True,
            _madc_result_summary_cards(state),
            (
                dbc.Alert(
                    "This run is stale because GitHub has advanced since it started. "
                    "Rerun it against the latest database before submitting.",
                    color="danger",
                )
                if stale_awaiting_decision
                else "Review the run summary and choose whether to submit it to the haplotype database."
                if awaiting_decision
                else _submission_review_alert(state)
            ),
            {"display": "block"},
            main_options,
            _option_values(main_options),
            diagnostic_options,
            [],
            {},
            "Cancel Run and Decline Submission" if awaiting_decision else "Cancel",
            "danger" if awaiting_decision else "secondary",
            "Rerun Required"
            if stale_awaiting_decision
            else "Review Submission and Download"
            if awaiting_decision
            else "Download Selected",
            no_update,
            False,
            no_update,
        )

    @app.callback(
        Output("madc-download", "data"),
        Input("madc-submission-request", "data"),
        prevent_initial_call=True,
    )
    def submit_and_download_madc(request_data):
        if not isinstance(request_data, dict):
            return no_update

        run_id = request_data.get("run_id")
        selected = request_data.get("selected")
        owner_orcid_id = (get_current_user() or {}).get("orcid_id", "")
        _sync_submission_state(run_id, owner_orcid_id)
        state = _snapshot_for_owner(run_id, owner_orcid_id)
        if state is None or state.submission_status == "declined":
            return no_update

        if state.submission_status == "awaiting_decision":
            if not _record_submission_decision(run_id, owner_orcid_id, "submitted_for_review"):
                return no_update
            _archive_run_results(
                run_id,
                owner_orcid_id,
                include_fixed_madc=True,
                include_log=True,
                selected_files=selected if isinstance(selected, list) else None,
            )
        try:
            return dcc.send_bytes(
                _zip_selected(run_id, owner_orcid_id, selected, default_all=False),
                f"madc_results_{str(run_id)[:8]}.zip",
            )
        except Exception:
            return no_update

    @app.callback(
        Output("madc-preview-table", "columns"),
        Output("madc-preview-table", "data"),
        Output("madc-preview-message", "children"),
        Output("madc-preview-empty", "children"),
        Output("madc-preview-empty", "style"),
        Output("madc-formal-project-id", "value"),
        Output("madc-submission-metadata", "style"),
        Output("madc-submitted-for-name", "value"),
        Output("madc-submitted-for-institution", "value"),
        Output("madc-submitted-for-location", "value"),
        Output("madc-submitted-for-email", "value"),
        Output("madc-panel-id", "data"),
        Output("madc-panel-value", "children"),
        Output("madc-panel-value", "className"),
        Input("madc-report-upload", "fileNames"),
        Input("madc-report-upload", "isCompleted"),
        State("madc-report-upload", "upload_id"),
    )
    def preview_madc(filenames: list[str] | None, is_completed: bool | None, upload_id: str | None):
        normalized_filenames = _normalize_file_list(filenames)
        if not normalized_filenames:
            return [], [], "", MADC_PREVIEW_EMPTY_MESSAGE, {"display": "flex"}, "", {"display": "none"}, "", "", "", "", None, "", (
                "identified-panel-value identified-panel-value--empty"
            )
        if not is_completed:
            return [], [], "", "Upload in progress...", {"display": "flex"}, "", {"display": "none"}, "", "", "", "", None, "", (
                "identified-panel-value identified-panel-value--empty"
            )

        project_id = infer_genotyping_project_id(normalized_filenames[0]) or ""
        owner_name, institution, location, email = _orcid_metadata_defaults()
        try:
            source_path = _uploaded_file_path(filenames, upload_id, is_completed, "MADC report", required=False)
            if source_path is None:
                return (
                    [],
                    [],
                    "",
                    MADC_PREVIEW_EMPTY_MESSAGE,
                    {"display": "flex"},
                    "",
                    {"display": "none"},
                    "",
                    "",
                    "",
                    "",
                    None,
                    "",
                    "identified-panel-value identified-panel-value--empty",
                )
            source = source_path.name
            project_id = infer_genotyping_project_id(source) or project_id
            columns, records, total_columns = _preview_from_path(source_path)
            identification = _identify_uploaded_madc_panel(source_path)
        except Exception as exc:  # noqa: BLE001 - shown in UI.
            return (
                [],
                [],
                "",
                f"MADC upload validation failed: {exc}",
                {"display": "flex"},
                project_id,
                {"display": "block"},
                owner_name,
                institution,
                location,
                email,
                None,
                dbc.Alert(str(exc), color="danger", className="panel-identification-alert"),
                "identified-panel-value identified-panel-value--error",
            )

        visible_columns = len(columns)
        column_note = f" and {visible_columns} of {total_columns} columns" if total_columns > visible_columns else ""
        return (
            columns,
            records,
            f"Showing first {len(records)} rows{column_note} from {source}",
            "",
            {"display": "none"},
            project_id,
            {"display": "block"},
            owner_name,
            institution,
            location,
            email,
            identification.panel_id,
            identification.label,
            "identified-panel-value",
        )

    @app.callback(
        Output("madc-submission-metadata", "className"),
        Output("madc-metadata-review-toast", "is_open"),
        Input("madc-run-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_madc_metadata_review(process_clicks):
        if process_clicks % 2 == 0:
            return "submission-metadata", False
        return "submission-metadata submission-metadata--review", True

    @app.callback(
        Output("madc-run-id", "data"),
        Output("madc-alert", "children"),
        Output("madc-verification-modal", "is_open"),
        Output("madc-verification-details", "children"),
        Input("madc-run-button", "n_clicks"),
        Input("madc-verification-close", "n_clicks"),
        State("madc-report-upload", "fileNames"),
        State("madc-report-upload", "upload_id"),
        State("madc-report-upload", "isCompleted"),
        State("madc-panel-id", "data"),
        State("madc-formal-project-id", "value"),
        State("madc-informal-project-name", "value"),
        State("madc-submitted-for-name", "value"),
        State("madc-submitted-for-location", "value"),
        State("madc-submitted-for-email", "value"),
        State("madc-submitted-for-institution", "value"),
        prevent_initial_call=True,
        running=[
            (Output("madc-preflight-status", "children"), _preflight_status_children(), []),
            (
                Output("madc-preflight-status", "className"),
                "preflight-status preflight-status--active",
                "preflight-status",
            ),
            (Output("madc-run-button", "disabled", allow_duplicate=True), True, False),
            (Output("madc-run-button", "children", allow_duplicate=True), _processing_button_children(), "Process"),
        ],
    )
    def start_madc(
        _process_clicks,
        _close_clicks,
        report_files,
        report_upload_id,
        report_completed,
        panel_id,
        inferred_project_id,
        informal_project_name,
        submitted_for_name,
        submitted_for_location,
        submitted_for_email,
        submitted_for_institution,
    ):
        if ctx.triggered_id == "madc-verification-close":
            return no_update, no_update, False, no_update
        if _process_clicks % 2 != 0:
            return no_update, no_update, False, no_update

        try:
            report_source = _uploaded_file_path(
                report_files, report_upload_id, report_completed, "MADC report"
            )
            assert report_source
            validate_madc_filename(report_source.name)

            missing_metadata = _missing_submission_metadata_fields(
                inferred_project_id=inferred_project_id,
                submitted_for_name=submitted_for_name,
                submitted_for_institution=submitted_for_institution,
                submitted_for_location=submitted_for_location,
                submitted_for_email=submitted_for_email,
            )
            if missing_metadata:
                raise ValueError("Complete required submission metadata: " + ", ".join(missing_metadata))

            # User-facing MADC parameters live on the selected species panel.
            panel = get_madc_panel(panel_id)

            # Check local tools before creating a run that cannot execute.
            missing = missing_madc_commands(panel)
            if missing:
                raise ValueError("Missing required commands: " + ", ".join(missing))

            run_root = RUN_BASE / "madc" / uuid.uuid4().hex
            work_dir = run_root / "work"
            work_dir.mkdir(parents=True, exist_ok=True)

            # Stage the uploaded raw report inside the run directory.
            report = _stage_uploaded_file(
                report_files, report_upload_id, report_completed, work_dir, "MADC report", "madc_report.csv"
            )

            assert report
            input_files = {report.relative_to(work_dir).as_posix()}

            # GitHub-backed panels are copied into this run so every run starts clean.
            input_github_repository, input_github_ref = madc_panel_github_source(panel)
            resolved_panel = resolve_madc_panel_files(panel, work_dir)
            input_files.update(_panel_input_files(resolved_panel, work_dir))
            main_result_files = _expected_new_madc_db_files(resolved_panel, work_dir)

            # Gate the upload here; build02 should only see raw, panel-matched MADC files.
            madc_check = validate_raw_madc(
                report,
                first_sample_col=resolved_panel.first_sample_col,
                panel_lut_path=resolved_panel.snpid_lut,
                strict_ref_alt=False,
            )

            # After validation passes, hand the selected panel files to the shell workflow.
            command = build_madc_command(resolved_panel, report, work_dir)

            run_id = uuid.uuid4().hex
            current_user = get_current_user()
            owner_orcid_id = (current_user or {}).get("orcid_id", "")
            if not owner_orcid_id:
                raise ValueError("An authenticated ORCID user is required to start a run.")
            submitter_profile = _current_profile_snapshot(owner_orcid_id)
            metadata = build_madc_submission_metadata(
                run_id=run_id,
                current_user=current_user,
                submitter_profile=submitter_profile,
                submitted_for_name=submitted_for_name,
                submitted_for_location=submitted_for_location,
                submitted_for_email=submitted_for_email,
                submitted_for_institution=submitted_for_institution,
                informal_project_name=informal_project_name,
                inferred_project_id=inferred_project_id,
                madc_filename=report.name,
                panel_id=resolved_panel.panel_id,
                panel_label=resolved_panel.label,
                input_github_repository=input_github_repository,
                input_github_ref=input_github_ref,
            )
            write_submission_metadata(work_dir, metadata)
            persist_submission_metadata(metadata)
            run_id = _start_run(
                "MADC hap assignment",
                command,
                work_dir,
                input_files,
                owner_orcid_id,
                main_result_files,
                run_id=run_id,
            )
            _append_log(run_id, "Submission metadata recorded in database.")
            if madc_check.warnings:
                alert = dbc.Alert(
                    [
                        html.Strong(f"Run started for {resolved_panel.label}, but the MADC pre-check found warnings."),
                        html.Ul([html.Li(warning) for warning in madc_check.warnings[:8]]),
                    ],
                    color="warning",
                    className="run-alert",
                )
            else:
                alert = dbc.Alert(
                    (
                        f"Run started for {resolved_panel.label}. MADC pre-check passed: "
                        f"{madc_check.n_data_rows:,} allele rows, "
                        f"{madc_check.n_clone_ids:,} CloneIDs."
                    ),
                    color="info",
                    className="run-alert",
                )

            return run_id, alert, False, []
        except MADCValidationError as exc:
            return (
                no_update,
                dbc.Alert("MADC verification failed", color="danger", className="run-alert"),
                True,
                _madc_verification_details(exc),
            )
        except Exception as exc:  # noqa: BLE001 - shown in UI.
            return no_update, dbc.Alert(str(exc), color="danger", className="run-alert"), False, []

    @app.callback(
        Output("madc-terminal", "children"),
        Output("madc-status", "children"),
        Output("madc-results-select", "options"),
        Output("madc-download-button", "disabled"),
        Output("madc-results-button", "disabled"),
        Output("madc-results-button", "children"),
        Input("run-poller", "n_intervals"),
        Input("madc-run-id", "data"),
    )
    def poll_madc(_ticks, run_id):
        owner_orcid_id = (get_current_user() or {}).get("orcid_id", "")
        state = _snapshot_for_owner(run_id, owner_orcid_id)
        if state is not None and state.status != "running":
            _sync_submission_state(run_id, owner_orcid_id)
            state = _snapshot_for_owner(run_id, owner_orcid_id)
        options = _result_options(state)
        stale_awaiting_decision = bool(
            state and state.submission_status == "awaiting_decision" and state.freshness_status == "stale"
        )
        return (
            _terminal_text(state),
            _status_text(state),
            options,
            len(options) == 0 or stale_awaiting_decision,
            len(options) == 0,
            "Results Declined" if state and state.submission_status == "declined" else "View Results",
        )

    @app.callback(
        Output("madc-status", "className"),
        Output("madc-run-button", "disabled"),
        Output("madc-run-button", "children"),
        Input("run-poller", "n_intervals"),
        Input("madc-run-id", "data"),
        Input("madc-panel-id", "data"),
    )
    def update_madc_run_state(_ticks, run_id, panel_id):
        owner_orcid_id = (get_current_user() or {}).get("orcid_id", "")
        state = _snapshot_for_owner(run_id, owner_orcid_id)
        return _status_class(state), not panel_id or _run_button_disabled(state), _run_button_children(state)

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HapApp Dash app")
    parser.add_argument("--host", default=config.APP_HOST)
    parser.add_argument("--port", default=config.APP_PORT, type=int)
    parser.add_argument("--debug", action="store_true", default=config.DEBUG_MODE)
    parser.add_argument("--no-open", action="store_true", help="Do not open the app in the default browser")
    args = parser.parse_args()

    RUN_BASE.mkdir(parents=True, exist_ok=True)
    app = create_app()
    if not args.no_open:
        app_url = f"{config.PUBLIC_URL}/app/" if config.PUBLIC_URL else f"http://{args.host}:{args.port}/app/"
        threading.Timer(1.0, webbrowser.open, args=[app_url]).start()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
