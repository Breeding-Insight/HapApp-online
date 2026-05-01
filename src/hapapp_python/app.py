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
from typing import Iterable

import dash_bootstrap_components as dbc
import dash_uploader as du
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update


def _find_project_root() -> Path:
    editable_root = Path(__file__).resolve().parents[2]
    if (editable_root / "workflows").is_dir() and (editable_root / "vendor" / "HapApp_utils").is_dir():
        return editable_root

    cwd = Path.cwd().resolve()
    if (cwd / "workflows").is_dir() and (cwd / "vendor" / "HapApp_utils").is_dir():
        return cwd

    return editable_root


PROJECT_ROOT = _find_project_root()
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
VENDOR_UTILS_DIR = PROJECT_ROOT / "vendor" / "HapApp_utils"
MADC_WORKFLOW = WORKFLOWS_DIR / "build02_madc_haps.sh"
CORE_WORKFLOW = WORKFLOWS_DIR / "build01_ref_alt_core_db.sh"
MADC_SCRIPTS_DIR = VENDOR_UTILS_DIR / "scripts" / "RefMatch_AltMatch_Other"
CORE_SCRIPTS_DIR = VENDOR_UTILS_DIR / "scripts" / "refAlt_coreDB"
RUN_BASE = Path(tempfile.gettempdir()) / "hapapp_python_runs"
UPLOAD_BASE = RUN_BASE / "uploads"
MAX_UPLOAD_MB = 50 * 1024
UPLOAD_CHUNK_MB = 16
MADC_PREVIEW_EMPTY_MESSAGE = "Upload an MADC file to display a preview."
MADC_CORE_RESULT_PATTERN = re.compile(
    r"_snpID_rename_updatedSeq\.csv$|_snpID_rename\.csv$|_v.*\.csv$|\.readme$|_v.*\.fa$|_matchCnt_lut\.txt$"
)


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


def _missing_commands(commands: Iterable[str]) -> list[str]:
    return [cmd for cmd in commands if shutil.which(cmd) is None]


def _positive_int(value: object, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return parsed


def _number(value: object, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return parsed


def _validate_output_prefix(value: object) -> str:
    prefix = str(value or "core_allele_db_v001").strip()
    prefix = prefix[:-3] if prefix.endswith(".fa") else prefix
    if "/" in prefix or "\\" in prefix:
        raise ValueError("Output prefix must be a filename prefix, not a path")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", prefix):
        raise ValueError("Output prefix may contain only letters, numbers, dots, underscores, and dashes")
    if not re.search(r"v[0-9]{3}", prefix):
        raise ValueError("Output prefix must contain a version token like v001")
    return prefix


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
    core_files: list[dict[str, str]] = []
    diagnostic_files: list[dict[str, str]] = []
    if state is None:
        return core_files, diagnostic_files

    for file_path in state.files:
        option = {"label": file_path, "value": file_path}
        if MADC_CORE_RESULT_PATTERN.search(file_path):
            core_files.append(option)
        else:
            diagnostic_files.append(option)
    return core_files, diagnostic_files


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


def _number_input(component_id: str, label: str, value: int | float, step: int | float = 1) -> dbc.Col:
    return dbc.Col(
        [
            dbc.Label(label, html_for=component_id),
            dbc.Input(id=component_id, type="number", value=value, step=step, min=0),
        ],
        md=6,
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
                                        html.H4("Core Files"),
                                        dcc.Checklist(
                                            id="madc-core-files",
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


def _core_results_modal() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Core Ref/Alt Results"), close_button=False),
            dbc.ModalBody(
                [
                    html.Div(id="core-results-message", className="results-message"),
                    dcc.Dropdown(
                        id="core-results-select",
                        multi=True,
                        placeholder="All result files",
                        className="result-select",
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button("Cancel", id="core-results-close", color="secondary", outline=True),
                    dbc.Button("Download Selected", id="core-download-button", color="success", disabled=True),
                ]
            ),
        ],
        id="core-results-modal",
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
                                _uploader_box("madc-snpid-lut-upload", "SNP ID LUT (.csv)", ["csv", "txt", "tsv"]),
                                _uploader_box("madc-base-db-upload", "Base allele DB FASTA", ["fa", "fasta", "fna"]),
                                _uploader_box("madc-base-matchcnt-upload", "Base match-count LUT", ["txt", "csv", "tsv"]),
                                dbc.Button(
                                    "Optional inputs",
                                    id="madc-optional-toggle",
                                    color="secondary",
                                    outline=True,
                                    className="section-toggle",
                                ),
                                dbc.Collapse(
                                    [
                                        _uploader_box(
                                            "madc-indel-db-upload",
                                            "Indel-added DB FASTA",
                                            ["fa", "fasta", "fna"],
                                        ),
                                        _uploader_box(
                                            "madc-indel-matchcnt-upload",
                                            "Indel-added match-count LUT",
                                            ["txt", "csv", "tsv"],
                                        ),
                                        _uploader_box("madc-dup-tags-upload", "Duplicate-tags file", ["txt", "csv", "tsv"]),
                                    ],
                                    id="madc-optional-collapse",
                                    is_open=False,
                                ),
                                html.H3("Parameters"),
                                dbc.Row(
                                    [
                                        _number_input("madc-first-sample-col", "First sample column", 17),
                                        _number_input("madc-design-len", "Design length", 81),
                                        _number_input("madc-seq-len", "Sequence length", 109),
                                        _number_input("madc-cov", "Coverage", 90),
                                        _number_input("madc-iden", "Identity", 85),
                                    ],
                                    className="g-2",
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
        ]
    )


def _core_tab() -> html.Div:
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.H2("Core Ref/Alt DB"),
                                html.Div(id="core-alert", className="alert-slot"),
                                html.H3("Inputs"),
                                _uploader_box("core-probe-upload", "Probe design file", ["csv", "txt", "tsv"]),
                                _uploader_box("core-chr-len-upload", "Chromosome length file", ["txt", "len", "csv", "tsv"]),
                                _uploader_box("core-madc-upload", "MADC report (.csv)", ["csv", "txt"]),
                                html.H3("Reference Genome"),
                                _uploader_box("core-ref-upload", "Reference genome FASTA", ["fa", "fasta", "fna"]),
                                html.H3("Parameters"),
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            [
                                                dbc.Label("Output prefix", html_for="core-output-prefix"),
                                                dbc.Input(
                                                    id="core-output-prefix",
                                                    value="core_allele_db_v001",
                                                    type="text",
                                                ),
                                            ],
                                            md=12,
                                        ),
                                        _number_input("core-ref-len", "Ref length", 109),
                                        _number_input("core-flank-len", "Flank length", 150),
                                    ],
                                    className="g-2",
                                ),
                                dbc.Button("Process", id="core-run-button", color="primary", className="run-button"),
                                html.H3("Results"),
                                dbc.Button(
                                    "View Results",
                                    id="core-results-button",
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
                                        html.Span(id="core-status", className="status-pill"),
                                    ],
                                    className="terminal-header",
                                ),
                                html.Pre(id="core-terminal", className="terminal"),
                            ],
                            className="output-panel",
                        ),
                        lg=8,
                    ),
                ],
                className="main-row",
            ),
            _core_results_modal(),
        ]
    )


def create_app() -> Dash:
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.FLATLY],
        assets_folder=str(PROJECT_ROOT / "assets"),
        suppress_callback_exceptions=True,
        title="HapApp Python",
    )
    du.configure_upload(app, str(UPLOAD_BASE))

    app.layout = dbc.Container(
        [
            dcc.Store(id="madc-run-id"),
            dcc.Store(id="core-run-id"),
            dcc.Interval(id="run-poller", interval=1000, n_intervals=0),
            dcc.Download(id="madc-download"),
            dcc.Download(id="core-download"),
            dcc.Store(id="madc-terminal-scroll"),
            dcc.Store(id="core-terminal-scroll"),
            html.Div(
                [
                    html.Div(
                        [
                            html.H1("HapApp Python"),
                            html.P("Microhaplotype assignment and Ref/Alt database workflows"),
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
            dbc.Tabs(
                [
                    dbc.Tab(_madc_tab(), label="MADC Hap Assignment", tab_id="madc"),
                    dbc.Tab(_core_tab(), label="Core Ref/Alt DB", tab_id="core"),
                ],
                id="workflow-tabs",
                active_tab="madc",
                className="workflow-tabs",
            ),
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

    app.clientside_callback(
        """
        function(children) {
            const terminal = document.getElementById("core-terminal");
            if (terminal) {
                terminal.scrollTop = terminal.scrollHeight;
            }
            return Date.now();
        }
        """,
        Output("core-terminal-scroll", "data"),
        Input("core-terminal", "children"),
    )

    @app.callback(
        Output("madc-results-modal", "is_open"),
        Output("madc-results-message", "children"),
        Output("madc-results-file-groups", "style"),
        Output("madc-core-files", "options"),
        Output("madc-core-files", "value"),
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

        core_options, diagnostic_options = _split_madc_result_options(state)
        return (
            True,
            "Select files to include in the ZIP archive.",
            {"display": "block"},
            core_options,
            _option_values(core_options),
            diagnostic_options,
            [],
        )

    @app.callback(
        Output("core-results-modal", "is_open"),
        Output("core-results-message", "children"),
        Output("core-results-select", "style"),
        Input("core-results-button", "n_clicks"),
        Input("core-results-close", "n_clicks"),
        State("core-run-id", "data"),
        State("core-results-modal", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_core_results_modal(_open_clicks, _close_clicks, run_id, _is_open):
        if ctx.triggered_id == "core-results-close":
            return False, no_update, no_update

        state = _snapshot(run_id)
        if not _result_options(state):
            return True, "No output files found yet. Run the workflow first.", {"display": "none"}

        return (
            True,
            "Select files to include in the ZIP archive. Leave blank to download all result files.",
            {"display": "block"},
        )

    @app.callback(
        Output("madc-optional-collapse", "is_open"),
        Input("madc-optional-toggle", "n_clicks"),
        State("madc-optional-collapse", "is_open"),
    )
    def toggle_madc_optional(n_clicks, is_open):
        if n_clicks:
            return not is_open
        return is_open

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
        Input("madc-run-button", "n_clicks"),
        State("madc-report-upload", "fileNames"),
        State("madc-report-upload", "upload_id"),
        State("madc-report-upload", "isCompleted"),
        State("madc-snpid-lut-upload", "fileNames"),
        State("madc-snpid-lut-upload", "upload_id"),
        State("madc-snpid-lut-upload", "isCompleted"),
        State("madc-base-db-upload", "fileNames"),
        State("madc-base-db-upload", "upload_id"),
        State("madc-base-db-upload", "isCompleted"),
        State("madc-base-matchcnt-upload", "fileNames"),
        State("madc-base-matchcnt-upload", "upload_id"),
        State("madc-base-matchcnt-upload", "isCompleted"),
        State("madc-indel-db-upload", "fileNames"),
        State("madc-indel-db-upload", "upload_id"),
        State("madc-indel-db-upload", "isCompleted"),
        State("madc-indel-matchcnt-upload", "fileNames"),
        State("madc-indel-matchcnt-upload", "upload_id"),
        State("madc-indel-matchcnt-upload", "isCompleted"),
        State("madc-dup-tags-upload", "fileNames"),
        State("madc-dup-tags-upload", "upload_id"),
        State("madc-dup-tags-upload", "isCompleted"),
        State("madc-first-sample-col", "value"),
        State("madc-design-len", "value"),
        State("madc-seq-len", "value"),
        State("madc-cov", "value"),
        State("madc-iden", "value"),
        prevent_initial_call=True,
    )
    def start_madc(
        _clicks,
        report_files,
        report_upload_id,
        report_completed,
        snpid_files,
        snpid_upload_id,
        snpid_completed,
        base_db_files,
        base_db_upload_id,
        base_db_completed,
        base_matchcnt_files,
        base_matchcnt_upload_id,
        base_matchcnt_completed,
        indel_db_files,
        indel_db_upload_id,
        indel_db_completed,
        indel_matchcnt_files,
        indel_matchcnt_upload_id,
        indel_matchcnt_completed,
        dup_tags_files,
        dup_tags_upload_id,
        dup_tags_completed,
        first_sample_col,
        design_len,
        seq_len,
        cov,
        iden,
    ):
        try:
            first_sample_col = _positive_int(first_sample_col, "First sample column")
            design_len = _positive_int(design_len, "Design length")
            seq_len = _positive_int(seq_len, "Sequence length")
            cov = _number(cov, "Coverage")
            iden = _number(iden, "Identity")
            code_version = "v1"

            required_commands = ["python3", "blastn", "makeblastdb"]
            if seq_len > design_len:
                required_commands.append("cutadapt")
            missing = _missing_commands(required_commands)
            if missing:
                raise ValueError("Missing required commands: " + ", ".join(missing))

            has_indel_db = bool(_normalize_file_list(indel_db_files))
            has_indel_matchcnt = bool(_normalize_file_list(indel_matchcnt_files))
            if has_indel_db != has_indel_matchcnt:
                raise ValueError("Provide both indel-added DB FASTA and indel-added match-count LUT, or neither")

            run_root = RUN_BASE / "madc" / uuid.uuid4().hex
            work_dir = run_root / "work"
            work_dir.mkdir(parents=True, exist_ok=True)

            report = _stage_uploaded_file(
                report_files, report_upload_id, report_completed, work_dir, "MADC report", "madc_report.csv"
            )
            snpid = _stage_uploaded_file(
                snpid_files, snpid_upload_id, snpid_completed, work_dir, "SNP ID LUT", "snpid_lut.csv"
            )
            base_db = _stage_uploaded_file(
                base_db_files, base_db_upload_id, base_db_completed, work_dir, "Base allele DB FASTA", "base_allele_db.fa"
            )
            base_matchcnt = _stage_uploaded_file(
                base_matchcnt_files,
                base_matchcnt_upload_id,
                base_matchcnt_completed,
                work_dir,
                "Base match-count LUT",
                "base_matchcnt_lut.txt",
            )
            indel_db = _stage_uploaded_file(
                indel_db_files,
                indel_db_upload_id,
                indel_db_completed,
                work_dir,
                "Indel-added DB FASTA",
                "indel_allele_db.fa",
                required=False,
            )
            indel_matchcnt = _stage_uploaded_file(
                indel_matchcnt_files,
                indel_matchcnt_upload_id,
                indel_matchcnt_completed,
                work_dir,
                "Indel-added match-count LUT",
                "indel_matchcnt_lut.txt",
                required=False,
            )
            dup_tags = _stage_uploaded_file(
                dup_tags_files,
                dup_tags_upload_id,
                dup_tags_completed,
                work_dir,
                "Duplicate-tags file",
                "duplicate_tags.txt",
                required=False,
            )

            assert report and snpid and base_db and base_matchcnt
            input_files = {path.relative_to(work_dir).as_posix() for path in [report, snpid, base_db, base_matchcnt]}
            optional_paths = [path for path in [indel_db, indel_matchcnt, dup_tags] if path is not None]
            input_files.update(path.relative_to(work_dir).as_posix() for path in optional_paths)

            command = [
                "bash",
                str(MADC_WORKFLOW),
                "--work-dir",
                str(work_dir),
                "--scripts-dir",
                str(MADC_SCRIPTS_DIR),
                "--report",
                str(report),
                "--snpid-lut",
                str(snpid),
                "--allele-db-base",
                str(base_db),
                "--matchcnt-lut-base",
                str(base_matchcnt),
                "--first-sample-col",
                str(first_sample_col),
                "--design-len",
                str(design_len),
                "--seq-len",
                str(seq_len),
                "--cov",
                str(cov),
                "--iden",
                str(iden),
                "--code-ver",
                code_version,
            ]
            if indel_db and indel_matchcnt:
                command.extend(["--allele-db-indel", str(indel_db), "--matchcnt-lut-indel", str(indel_matchcnt)])
            if dup_tags:
                command.extend(["--dup-tags", str(dup_tags)])

            run_id = _start_run("MADC hap assignment", command, work_dir, input_files)
            return run_id, dbc.Alert("Run started.", color="info", className="run-alert")
        except Exception as exc:  # noqa: BLE001 - shown in UI.
            return no_update, dbc.Alert(str(exc), color="danger", className="run-alert")

    @app.callback(
        Output("core-run-id", "data"),
        Output("core-alert", "children"),
        Input("core-run-button", "n_clicks"),
        State("core-probe-upload", "fileNames"),
        State("core-probe-upload", "upload_id"),
        State("core-probe-upload", "isCompleted"),
        State("core-chr-len-upload", "fileNames"),
        State("core-chr-len-upload", "upload_id"),
        State("core-chr-len-upload", "isCompleted"),
        State("core-madc-upload", "fileNames"),
        State("core-madc-upload", "upload_id"),
        State("core-madc-upload", "isCompleted"),
        State("core-ref-upload", "fileNames"),
        State("core-ref-upload", "upload_id"),
        State("core-ref-upload", "isCompleted"),
        State("core-output-prefix", "value"),
        State("core-ref-len", "value"),
        State("core-flank-len", "value"),
        prevent_initial_call=True,
    )
    def start_core(
        _clicks,
        probe_files,
        probe_upload_id,
        probe_completed,
        chr_len_files,
        chr_len_upload_id,
        chr_len_completed,
        madc_files,
        madc_upload_id,
        madc_completed,
        ref_files,
        ref_upload_id,
        ref_completed,
        output_prefix,
        ref_len,
        flank_len,
    ):
        try:
            ref_len = _positive_int(ref_len, "Ref length")
            flank_len = _positive_int(flank_len, "Flank length")
            output_prefix = _validate_output_prefix(output_prefix)

            missing = _missing_commands(["python3", "blastn", "makeblastdb", "esl-sfetch", "seqkit", "mmseqs"])
            if missing:
                raise ValueError("Missing required commands: " + ", ".join(missing))

            run_root = RUN_BASE / "core" / uuid.uuid4().hex
            work_dir = run_root / "work"
            work_dir.mkdir(parents=True, exist_ok=True)

            probe = _stage_uploaded_file(
                probe_files, probe_upload_id, probe_completed, work_dir, "Probe design file", "probe_design.csv"
            )
            chr_len = _stage_uploaded_file(
                chr_len_files,
                chr_len_upload_id,
                chr_len_completed,
                work_dir,
                "Chromosome length file",
                "chromosome_lengths.txt",
            )
            madc = _stage_uploaded_file(
                madc_files, madc_upload_id, madc_completed, work_dir, "MADC report", "madc_report.csv"
            )
            reference = _stage_uploaded_file(
                ref_files, ref_upload_id, ref_completed, work_dir, "Reference genome FASTA", "reference_genome.fa"
            )

            assert probe and chr_len and madc and reference
            input_files = {path.relative_to(work_dir).as_posix() for path in [probe, chr_len, madc, reference]}

            command = [
                "bash",
                str(CORE_WORKFLOW),
                "--work-dir",
                str(work_dir),
                "--scripts-dir",
                str(CORE_SCRIPTS_DIR),
                "--probe-file",
                str(probe),
                "--chr-len",
                str(chr_len),
                "--ref-genome",
                str(reference),
                "--report",
                str(madc),
                "--output-prefix",
                output_prefix,
                "--ref-len",
                str(ref_len),
                "--flank-len",
                str(flank_len),
            ]

            run_id = _start_run("Core Ref/Alt DB", command, work_dir, input_files)
            return run_id, dbc.Alert("Run started.", color="info", className="run-alert")
        except Exception as exc:  # noqa: BLE001 - shown in UI.
            return no_update, dbc.Alert(str(exc), color="danger", className="run-alert")

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
        Output("core-terminal", "children"),
        Output("core-status", "children"),
        Output("core-results-select", "options"),
        Output("core-download-button", "disabled"),
        Input("run-poller", "n_intervals"),
        Input("core-run-id", "data"),
    )
    def poll_core(_ticks, run_id):
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
        Output("core-status", "className"),
        Output("core-run-button", "disabled"),
        Output("core-run-button", "children"),
        Input("run-poller", "n_intervals"),
        Input("core-run-id", "data"),
    )
    def update_core_run_state(_ticks, run_id):
        state = _snapshot(run_id)
        return _status_class(state), _run_button_disabled(state), _run_button_children(state)

    @app.callback(
        Output("madc-download", "data"),
        Input("madc-download-button", "n_clicks"),
        State("madc-run-id", "data"),
        State("madc-core-files", "value"),
        State("madc-diagnostic-files", "value"),
        prevent_initial_call=True,
    )
    def download_madc(_clicks, run_id, core_selected, diagnostic_selected):
        selected = list(dict.fromkeys((core_selected or []) + (diagnostic_selected or [])))
        try:
            return dcc.send_bytes(
                _zip_selected(run_id, selected, default_all=False),
                f"madc_results_{str(run_id)[:8]}.zip",
            )
        except Exception:
            return no_update

    @app.callback(
        Output("core-download", "data"),
        Input("core-download-button", "n_clicks"),
        State("core-run-id", "data"),
        State("core-results-select", "value"),
        prevent_initial_call=True,
    )
    def download_core(_clicks, run_id, selected):
        try:
            return dcc.send_bytes(_zip_selected(run_id, selected), f"core_db_results_{str(run_id)[:8]}.zip")
        except Exception:
            return no_update


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HapApp Python Dash app")
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
