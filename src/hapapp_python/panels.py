from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hapapp_python.paths import PROJECT_ROOT

PANEL_CONFIG_PATH = Path(os.environ.get("HAPAPP_PANELS_FILE", Path(__file__).with_name("panels.toml")))


@dataclass(frozen=True)
class MADCPanel:
    panel_id: str
    label: str
    snpid_lut: Path
    allele_db_base: Path
    matchcnt_lut_base: Path
    allele_db_indel: Path | None
    matchcnt_lut_indel: Path | None
    dup_tags: Path | None
    first_sample_col: int
    design_len: int
    seq_len: int
    cov: float
    iden: float
    code_ver: str


def load_madc_panels(config_path: Path | None = None) -> dict[str, MADCPanel]:
    config_path = config_path or PANEL_CONFIG_PATH
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"MADC panels file not found: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Could not parse MADC panels file {config_path}: {exc}") from exc

    raw_panels = data.get("panels")
    if not isinstance(raw_panels, Mapping) or not raw_panels:
        raise ValueError("MADC panels file must define at least one [panels.<panel_id>] entry.")

    panels: dict[str, MADCPanel] = {}
    for panel_id, raw_panel in raw_panels.items():
        if not isinstance(panel_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", panel_id):
            raise ValueError(f"Invalid MADC panel id: {panel_id!r}")
        if not isinstance(raw_panel, Mapping):
            raise ValueError(f"MADC panel {panel_id!r} must be a TOML table.")
        panels[panel_id] = _parse_madc_panel(panel_id, raw_panel)

    return panels


def madc_panel_options(config_path: Path | None = None) -> list[dict[str, object]]:
    try:
        panels = load_madc_panels(config_path)
    except ValueError as exc:
        return [{"label": f"Panel configuration error: {exc}", "value": "__panel_config_error__", "disabled": True}]
    return [{"label": panel.label, "value": panel.panel_id} for panel in panels.values()]


def default_madc_panel_value(config_path: Path | None = None) -> str | None:
    options = madc_panel_options(config_path)
    for option in options:
        if not option.get("disabled"):
            value = option.get("value")
            return str(value) if value else None
    return None


def get_madc_panel(panel_id: str | None, config_path: Path | None = None) -> MADCPanel:
    if not panel_id:
        raise ValueError("Select a species panel before starting the MADC workflow.")

    panels = load_madc_panels(config_path)
    try:
        return panels[panel_id]
    except KeyError as exc:
        raise ValueError(f"Unknown species panel: {panel_id}") from exc


def validate_madc_panel_files(panel: MADCPanel) -> None:
    checks = [
        ("SNP ID LUT", panel.snpid_lut),
        ("base allele DB FASTA", panel.allele_db_base),
        ("base match-count LUT", panel.matchcnt_lut_base),
    ]
    if panel.allele_db_indel:
        checks.append(("indel allele DB FASTA", panel.allele_db_indel))
    if panel.matchcnt_lut_indel:
        checks.append(("indel match-count LUT", panel.matchcnt_lut_indel))
    if panel.dup_tags:
        checks.append(("duplicate-tags file", panel.dup_tags))

    missing = [f"{label}: {path}" for label, path in checks if not path.is_file()]
    if missing:
        raise ValueError(
            f"Selected species panel {panel.label!r} is missing configured file(s): " + "; ".join(missing)
        )


def _parse_madc_panel(panel_id: str, raw_panel: Mapping[str, Any]) -> MADCPanel:
    allele_db_indel = _panel_optional_path(raw_panel, "allele_db_indel", panel_id)
    matchcnt_lut_indel = _panel_optional_path(raw_panel, "matchcnt_lut_indel", panel_id)
    if bool(allele_db_indel) != bool(matchcnt_lut_indel):
        raise ValueError(
            f"MADC panel {panel_id!r} must define both allele_db_indel and matchcnt_lut_indel, or neither."
        )

    return MADCPanel(
        panel_id=panel_id,
        label=_panel_string(raw_panel, "label", panel_id),
        snpid_lut=_panel_path(raw_panel, "snpid_lut", panel_id),
        allele_db_base=_panel_path(raw_panel, "allele_db_base", panel_id),
        matchcnt_lut_base=_panel_path(raw_panel, "matchcnt_lut_base", panel_id),
        allele_db_indel=allele_db_indel,
        matchcnt_lut_indel=matchcnt_lut_indel,
        dup_tags=_panel_optional_path(raw_panel, "dup_tags", panel_id),
        first_sample_col=_panel_positive_int(raw_panel, "first_sample_col", panel_id),
        design_len=_panel_positive_int(raw_panel, "design_len", panel_id),
        seq_len=_panel_positive_int(raw_panel, "seq_len", panel_id),
        cov=_panel_number(raw_panel, "cov", panel_id),
        iden=_panel_number(raw_panel, "iden", panel_id),
        code_ver=_panel_string(raw_panel, "code_ver", panel_id),
    )


def _panel_string(raw_panel: Mapping[str, Any], field_name: str, panel_id: str) -> str:
    value = raw_panel.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MADC panel {panel_id!r} must define non-empty {field_name!r}.")
    return value.strip()


def _panel_path(raw_panel: Mapping[str, Any], field_name: str, panel_id: str) -> Path:
    return _resolve_panel_path(_panel_string(raw_panel, field_name, panel_id))


def _panel_optional_path(raw_panel: Mapping[str, Any], field_name: str, panel_id: str) -> Path | None:
    value = raw_panel.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MADC panel {panel_id!r} has invalid optional path {field_name!r}.")
    return _resolve_panel_path(value.strip())


def _resolve_panel_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _panel_positive_int(raw_panel: Mapping[str, Any], field_name: str, panel_id: str) -> int:
    try:
        value = int(raw_panel[field_name])
    except KeyError as exc:
        raise ValueError(f"MADC panel {panel_id!r} must define {field_name!r}.") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"MADC panel {panel_id!r} has invalid integer value for {field_name!r}.") from exc
    if value <= 0:
        raise ValueError(f"MADC panel {panel_id!r} field {field_name!r} must be greater than zero.")
    return value


def _panel_number(raw_panel: Mapping[str, Any], field_name: str, panel_id: str) -> float:
    try:
        value = float(raw_panel[field_name])
    except KeyError as exc:
        raise ValueError(f"MADC panel {panel_id!r} must define {field_name!r}.") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"MADC panel {panel_id!r} has invalid numeric value for {field_name!r}.") from exc
    if value <= 0:
        raise ValueError(f"MADC panel {panel_id!r} field {field_name!r} must be greater than zero.")
    return value
