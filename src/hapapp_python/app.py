from __future__ import annotations

import argparse
import csv
import io
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
from pathlib import Path

import dash_bootstrap_components as dbc
import dash_uploader as du
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update

from hapapp_python.madc_workflow import build_madc_command, missing_madc_commands
from hapapp_python.madc_validation import MADCValidationError, validate_raw_madc
from hapapp_python.panels import (
    default_madc_panel_value,
    get_madc_panel,
    madc_panel_options,
    validate_madc_panel_files,
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
APP_NAME = "HapApp"


@dataclass
class RunState:
    run_id: str
    kind: str
    work_dir: Path
    input_files: set[str]
    command: list[str]
    log: list[str] = field(default_factory=list)
    status: str = "running"
    returncode: int | None = None
    files: list[str] = field(default_factory=list)
    error: str | None = None


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


def _list_files(work_dir: Path, input_files: set[str]) -> list[str]:
    if not work_dir.exists():
        return []

    files: list[str] = []
    for path in work_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(work_dir).as_posix()
        if relative in input_files:
            continue
        files.append(relative)
    return sorted(files)


def _append_log(run_id: str, line: str) -> None:
    with RUNS_LOCK:
        state = RUNS.get(run_id)
        if state:
            state.log.append(line.rstrip("\n"))


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
            state.files = _list_files(work_dir, input_files)
            state.status = "completed" if returncode == 0 else "failed"
            if returncode != 0:
                state.error = f"Workflow exited with status {returncode}"
    except Exception as exc:  # noqa: BLE001 - surfaced directly in local UI.
        with RUNS_LOCK:
            state = RUNS[run_id]
            state.status = "failed"
            state.error = str(exc)
            state.files = _list_files(work_dir, input_files)
            state.log.append(f"[ERROR] {exc}")


def _start_run(kind: str, command: list[str], work_dir: Path, input_files: set[str]) -> str:
    run_id = uuid.uuid4().hex
    state = RunState(
        run_id=run_id,
        kind=kind,
        work_dir=work_dir,
        input_files=input_files,
        command=command,
        log=[f"Starting {kind} workflow...", f"Working directory: {work_dir}"],
    )
    with RUNS_LOCK:
        RUNS[run_id] = state

    thread = threading.Thread(target=_run_process, args=(run_id,), daemon=True)
    thread.start()
    return run_id


def _snapshot(run_id: str | None) -> RunState | None:
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
            log=list(state.log),
            status=state.status,
            returncode=state.returncode,
            files=list(state.files),
            error=state.error,
        )


def _status_text(state: RunState | None) -> str:
    if state is None:
        return "Idle"
    if state.status == "running":
        return "Running"
    if state.status == "completed":
        return "Complete"
    return "Failed"


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


def _run_button_children(state: RunState | None):
    if _run_button_disabled(state):
        return html.Span(
            [html.Span(className="run-spinner", **{"aria-hidden": "true"}), html.Span("Processing...")],
            className="run-button-content",
        )
    return "Process"


def _terminal_text(state: RunState | None) -> str:
    if state is None:
        return "Ready."

    text = "\n".join(state.log).strip()
    if state.error:
        text = f"{text}\n\n{state.error}".strip()
    return text or "Running..."


def _result_options(state: RunState | None) -> list[dict[str, str]]:
    if state is None:
        return []
    return [{"label": file_path, "value": file_path} for file_path in state.files]


def _split_madc_result_options(state: RunState | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    main_files: list[dict[str, str]] = []
    diagnostic_files: list[dict[str, str]] = []
    if state is None:
        return main_files, diagnostic_files

    for file_path in state.files:
        option = {"label": file_path, "value": file_path}
        if "/" not in file_path and MADC_MAIN_RESULT_PATTERN.search(file_path):
            main_files.append(option)
        else:
            diagnostic_files.append(option)
    return main_files, diagnostic_files


def _option_values(options: list[dict[str, str]]) -> list[str]:
    return [option["value"] for option in options]


def _zip_selected(run_id: str | None, selected: list[str] | None, default_all: bool = True) -> bytes:
    state = _snapshot(run_id)
    if state is None:
        raise ValueError("No run is available for download")

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
                    html.Div(id="madc-results-message", className="results-message"),
                    dcc.Dropdown(id="madc-results-select", multi=True, style={"display": "none"}),
                    html.Div(
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
                        id="madc-results-file-groups",
                        style={"display": "none"},
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button("Cancel", id="madc-results-close", color="secondary", outline=True),
                    dbc.Button("Download Selected", id="madc-download-button", color="success", disabled=True),
                ]
            ),
        ],
        id="madc-results-modal",
        centered=True,
        size="lg",
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
                                html.H3("Inputs"),
                                _uploader_box("madc-report-upload", "MADC report (.csv)", ["csv", "txt"]),
                                html.Div(
                                    [
                                        dbc.Label("Species panel", html_for="madc-panel-select"),
                                        dcc.Dropdown(
                                            id="madc-panel-select",
                                            options=madc_panel_options(),
                                            value=default_madc_panel_value(),
                                            clearable=False,
                                            className="panel-select",
                                        ),
                                    ],
                                    className="field-group",
                                ),
                                dbc.Button("Process", id="madc-run-button", color="primary", className="run-button"),
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
            _madc_verification_modal(),
        ]
    )

def create_app() -> Dash:
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.FLATLY],
        assets_folder=str(PROJECT_ROOT / "assets"),
        suppress_callback_exceptions=True,
        title=APP_NAME,
    )
    du.configure_upload(app, str(UPLOAD_BASE))

    app.layout = dbc.Container(
        [
            dcc.Store(id="madc-run-id"),
            dcc.Interval(id="run-poller", interval=1000, n_intervals=0),
            dcc.Download(id="madc-download"),
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
        """
        function(children) {
            const terminal = document.getElementById("madc-terminal");
            if (terminal) {
                terminal.scrollTop = terminal.scrollHeight;
            }
            return Date.now();
        }
        """,
        Output("madc-terminal-scroll", "data"),
        Input("madc-terminal", "children"),
    )

    @app.callback(
        Output("madc-results-modal", "is_open"),
        Output("madc-results-message", "children"),
        Output("madc-results-file-groups", "style"),
        Output("madc-main-files", "options"),
        Output("madc-main-files", "value"),
        Output("madc-diagnostic-files", "options"),
        Output("madc-diagnostic-files", "value"),
        Input("madc-results-button", "n_clicks"),
        Input("madc-results-close", "n_clicks"),
        State("madc-run-id", "data"),
        State("madc-results-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_madc_results_modal(_open_clicks, _close_clicks, run_id, _is_open):
        if ctx.triggered_id == "madc-results-close":
            return False, no_update, no_update, no_update, no_update, no_update, no_update

        state = _snapshot(run_id)
        if not state or not state.files:
            return (
                True,
                "No output files found yet. Please run the process first.",
                {"display": "none"},
                [],
                [],
                [],
                [],
            )

        main_options, diagnostic_options = _split_madc_result_options(state)
        return (
            True,
            "Select files to include in the ZIP archive.",
            {"display": "block"},
            main_options,
            _option_values(main_options),
            diagnostic_options,
            [],
        )

    @app.callback(
        Output("madc-preview-table", "columns"),
        Output("madc-preview-table", "data"),
        Output("madc-preview-message", "children"),
        Output("madc-preview-empty", "children"),
        Output("madc-preview-empty", "style"),
        Input("madc-report-upload", "fileNames"),
        Input("madc-report-upload", "isCompleted"),
        State("madc-report-upload", "upload_id"),
    )
    def preview_madc(filenames: list[str] | None, is_completed: bool | None, upload_id: str | None):
        if not _normalize_file_list(filenames):
            return [], [], "", MADC_PREVIEW_EMPTY_MESSAGE, {"display": "flex"}
        if not is_completed:
            return [], [], "", "Upload in progress...", {"display": "flex"}

        try:
            source_path = _uploaded_file_path(filenames, upload_id, is_completed, "MADC report", required=False)
            if source_path is None:
                return [], [], "", MADC_PREVIEW_EMPTY_MESSAGE, {"display": "flex"}
            source = source_path.name
            columns, records, total_columns = _preview_from_path(source_path)
        except Exception as exc:  # noqa: BLE001 - shown in UI.
            return [], [], "", f"Could not read MADC report: {exc}", {"display": "flex"}

        visible_columns = len(columns)
        column_note = f" and {visible_columns} of {total_columns} columns" if total_columns > visible_columns else ""
        return columns, records, f"Showing first {len(records)} rows{column_note} from {source}", "", {"display": "none"}

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
        State("madc-panel-select", "value"),
        prevent_initial_call=True,
    )
    def start_madc(
        _clicks,
        _close_clicks,
        report_files,
        report_upload_id,
        report_completed,
        panel_id,
    ):
        if ctx.triggered_id == "madc-verification-close":
            return no_update, no_update, False, no_update

        try:
            # User-facing MADC parameters live on the selected species panel.
            panel = get_madc_panel(panel_id)
            validate_madc_panel_files(panel)

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

            # Gate the upload here; build02 should only see raw, panel-matched MADC files.
            madc_check = validate_raw_madc(
                report,
                first_sample_col=panel.first_sample_col,
                panel_lut_path=panel.snpid_lut,
                strict_ref_alt=False,
            )

            # After validation passes, hand the selected panel files to the shell workflow.
            command = build_madc_command(panel, report, work_dir)

            run_id = _start_run("MADC hap assignment", command, work_dir, input_files)
            if madc_check.warnings:
                alert = dbc.Alert(
                    [
                        html.Strong(f"Run started for {panel.label}, but the MADC pre-check found warnings."),
                        html.Ul([html.Li(warning) for warning in madc_check.warnings[:8]]),
                    ],
                    color="warning",
                    className="run-alert",
                )
            else:
                alert = dbc.Alert(
                    (
                        f"Run started for {panel.label}. MADC pre-check passed: "
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
        Input("run-poller", "n_intervals"),
        Input("madc-run-id", "data"),
    )
    def poll_madc(_ticks, run_id):
        state = _snapshot(run_id)
        options = _result_options(state)
        return (
            _terminal_text(state),
            _status_text(state),
            options,
            len(options) == 0,
        )

    @app.callback(
        Output("madc-status", "className"),
        Output("madc-run-button", "disabled"),
        Output("madc-run-button", "children"),
        Input("run-poller", "n_intervals"),
        Input("madc-run-id", "data"),
    )
    def update_madc_run_state(_ticks, run_id):
        state = _snapshot(run_id)
        return _status_class(state), _run_button_disabled(state), _run_button_children(state)

    @app.callback(
        Output("madc-download", "data"),
        Input("madc-download-button", "n_clicks"),
        State("madc-run-id", "data"),
        State("madc-main-files", "value"),
        State("madc-diagnostic-files", "value"),
        prevent_initial_call=True,
    )
    def download_madc(_clicks, run_id, main_selected, diagnostic_selected):
        selected = list(dict.fromkeys((main_selected or []) + (diagnostic_selected or [])))
        try:
            return dcc.send_bytes(
                _zip_selected(run_id, selected, default_all=False),
                f"madc_results_{str(run_id)[:8]}.zip",
            )
        except Exception:
            return no_update

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HapApp Dash app")
    parser.add_argument("--host", default=os.environ.get("HAPAPP_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.environ.get("HAPAPP_PORT", "8050")), type=int)
    parser.add_argument("--debug", action="store_true", default=os.environ.get("HAPAPP_DEBUG") == "1")
    parser.add_argument("--no-open", action="store_true", help="Do not open the app in the default browser")
    args = parser.parse_args()

    RUN_BASE.mkdir(parents=True, exist_ok=True)
    app = create_app()
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=[f"http://{args.host}:{args.port}/"]).start()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
