from __future__ import annotations

import csv
import re
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, TextIO

MISSING = {"", "NA", "N/A", "NULL", "null", "NaN", "nan"}
RAW_PREAMBLE = {"", "*"}
REQUIRED_PREFIX = ("AlleleID", "CloneID", "AlleleSequence")

RAW_REF_RE = re.compile(r"\|Ref$")
RAW_ALT_RE = re.compile(r"\|Alt$")

# HapApp/fixedAlleleID-style IDs generated downstream from raw MADC rows.
FIXED_REF_RE = re.compile(r"\|Ref_0001$")
FIXED_ALT_RE = re.compile(r"\|Alt_0002$")
FIXED_TMP_RE = re.compile(r"_tmp_\d{4}$")

LOWERCASE_BASE_RE = re.compile(r"[atcg]")
NON_ATCG_DASH_RE = re.compile(r"[^ATCG-]", flags=re.IGNORECASE)


@dataclass(frozen=True)
class MADCCheckResult:
    path: str
    delimiter: str
    header_row_number: int
    n_columns: int
    n_sample_columns: int
    n_data_rows: int
    n_clone_ids: int
    n_ref_rows: int
    n_alt_rows: int
    n_other_rows: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


class MADCValidationError(ValueError):
    """Raised when an uploaded MADC should not be passed to the HapApp workflow."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = tuple(errors)
        self.warnings = tuple(warnings or [])

        message = "MADC validation failed:\n" + "\n".join(f"- {error}" for error in self.errors)
        if self.warnings:
            message += "\nWarnings:\n" + "\n".join(f"- {warning}" for warning in self.warnings)

        super().__init__(message)


def validate_raw_madc(
    path: str | Path,
    *,
    first_sample_col: int = 17,
    expected_header_row: int | None = None,
    max_header_scan_rows: int = 20,
    max_examples: int = 10,
    strict_ref_alt: bool = False,
    raise_on_warnings: bool = False,
) -> MADCCheckResult:
    """
    Validate that `path` is a raw DArT/MADC CSV suitable for HapApp.

    Parameters
    ----------
    path
        Uploaded MADC file path.
    first_sample_col
        1-based index of the first sample/read-count column. This matches the
        HapApp UI/workflow parameter. Default is 17.
    expected_header_row
        Optional 1-based row number containing the raw MADC header. If omitted,
        the header row is detected from the first `max_header_scan_rows` rows.
    max_header_scan_rows
        Number of rows to scan when auto-detecting the raw MADC header.
    strict_ref_alt
        If True, missing Ref/Alt rows per CloneID are errors. If False, they
        are warnings.
    raise_on_warnings
        If True, warnings are promoted to a blocking validation error.

    Returns
    -------
    MADCCheckResult
        Counts and warnings for display in the UI.

    Raises
    ------
    MADCValidationError
        When the file is structurally invalid or appears to be a fixedAlleleID
        MADC rather than a raw MADC.
    """
    path = Path(path)
    errors: list[str] = []
    warnings: list[str] = []

    if first_sample_col < 4:
        raise ValueError("first_sample_col is 1-based and must be at least 4.")

    if not path.is_file():
        raise MADCValidationError([f"File not found: {path}"])

    sample_text = _read_sample_text(path)
    if not sample_text.strip():
        raise MADCValidationError(["The uploaded MADC file is empty."])

    delimiter = _detect_delimiter(sample_text)
    rows_to_read = expected_header_row if expected_header_row is not None else max_header_scan_rows

    first_rows = _read_first_rows(path, delimiter, rows_to_read)
    if expected_header_row is not None and len(first_rows) < expected_header_row:
        looks_fixed, examples = _scan_for_fixed_ids(path, delimiter)
        if looks_fixed:
            raise MADCValidationError([_fixed_file_message(examples)])
        raise MADCValidationError(
            [f"The uploaded file has only {len(first_rows)} rows; expected at least {expected_header_row} rows."]
        )

    header_row_number = expected_header_row or _find_raw_header_row(first_rows)
    if header_row_number is None:
        fixed_header_row = _find_fixed_header_row(first_rows)
        if fixed_header_row is not None:
            raise MADCValidationError(
                [
                    "This looks like a HapApp output/fixedAlleleID MADC because the first column is Code_version. "
                    "Upload the original raw MADC report instead."
                ]
            )

        looks_fixed, examples = _scan_for_fixed_ids(path, delimiter)
        if looks_fixed:
            raise MADCValidationError([_fixed_file_message(examples)])

        raise MADCValidationError(
            [
                "Could not find a raw MADC header row starting with "
                f"{list(REQUIRED_PREFIX)} in the first {len(first_rows)} row(s)."
            ]
        )

    first_col = [_clean(row[0]) if row else "" for row in first_rows[: header_row_number - 1]]
    if header_row_number == 1:
        errors.append(
            "Raw MADC files are expected to include DArT preamble rows before the AlleleID header. "
            "Upload the original raw DArT/MADC report instead."
        )

    if not all(value in RAW_PREAMBLE for value in first_col):
        looks_fixed, examples = _scan_for_fixed_ids(path, delimiter)
        if looks_fixed:
            raise MADCValidationError([_fixed_file_message(examples)])

        errors.append(
            f"Expected the first {header_row_number - 1} first-column values to be blank or '*'. "
            f"Observed: {first_col!r}."
        )

    header = [_clean(value) for value in first_rows[header_row_number - 1]]

    if tuple(header[:3]) != REQUIRED_PREFIX:
        if header[:4] == ["Code_version", *REQUIRED_PREFIX]:
            errors.append(
                "This looks like a HapApp output/fixedAlleleID MADC because the first column is Code_version. "
                "Upload the original raw MADC report instead."
            )
        else:
            errors.append(
                f"Row {header_row_number} must start with {list(REQUIRED_PREFIX)}. "
                f"Observed: {header[:3]!r}."
            )

    if len(header) < first_sample_col:
        errors.append(f"The header has {len(header)} columns, but first_sample_col={first_sample_col}.")

    if errors:
        raise MADCValidationError(errors, warnings)

    n_columns = len(header)
    sample_start_idx = first_sample_col - 1
    sample_headers = header[sample_start_idx:]

    if not sample_headers:
        errors.append("No sample/read-count columns were found after first_sample_col.")

    duplicate_samples = [name for name, count in Counter(sample_headers).items() if name and count > 1]
    if duplicate_samples:
        warnings.append(f"Duplicate sample names found. Examples: {duplicate_samples[:max_examples]}.")

    blank_samples = [i + first_sample_col for i, name in enumerate(sample_headers) if _is_missing(name)]
    if blank_samples:
        warnings.append(
            f"{len(blank_samples)} sample column name(s) are blank. "
            f"First affected 1-based columns: {blank_samples[:max_examples]}."
        )

    scan = _scan_data_rows(
        path=path,
        delimiter=delimiter,
        expected_header_row=header_row_number,
        n_columns=n_columns,
        first_sample_col=first_sample_col,
        sample_start_idx=sample_start_idx,
        max_examples=max_examples,
    )

    errors.extend(scan["errors"])
    warnings.extend(scan["warnings"])

    if scan["n_data_rows"] == 0:
        errors.append("No allele data rows were found after the raw MADC header.")

    looks_fixed = (
        scan["has_ref_0001"] and scan["has_alt_0002"]
    ) or (
        scan["has_tmp"] and (scan["has_ref_0001"] or scan["has_alt_0002"])
    )

    if looks_fixed:
        examples = scan["fixed_examples"]
        errors.append(
            "FixedAlleleID-style AlleleIDs were found after the raw header. "
            f"Examples: {examples}."
        )

    if scan["n_ref_rows"] == 0:
        warnings.append("No raw Ref rows found; expected AlleleID values ending with '|Ref'.")
    if scan["n_alt_rows"] == 0:
        warnings.append("No raw Alt rows found; expected AlleleID values ending with '|Alt'.")

    missing_ref = sorted(scan["clone_ids"] - scan["clones_with_ref"])
    missing_alt = sorted(scan["clone_ids"] - scan["clones_with_alt"])

    for label, missing_set in [("Ref", missing_ref), ("Alt", missing_alt)]:
        if missing_set:
            message = (
                f"{len(missing_set)} CloneID(s) do not have a raw '|{label}' allele row. "
                f"Examples: {missing_set[:max_examples]}."
            )
            if strict_ref_alt:
                errors.append(message)
            else:
                warnings.append(message)

    indel_clones = [
        clone_id
        for clone_id in sorted(set(scan["ref_lengths"]) & set(scan["alt_lengths"]))
        if scan["ref_lengths"][clone_id] != scan["alt_lengths"][clone_id]
    ][:max_examples]

    if indel_clones:
        warnings.append(f"Potential indels: Ref/Alt sequence lengths differ for CloneIDs {indel_clones}.")

    if raise_on_warnings and warnings and not errors:
        errors.append("MADC validation produced warnings and raise_on_warnings=True.")

    if errors:
        raise MADCValidationError(errors, warnings)

    return MADCCheckResult(
        path=str(path),
        delimiter=delimiter,
        header_row_number=header_row_number,
        n_columns=n_columns,
        n_sample_columns=len(sample_headers),
        n_data_rows=scan["n_data_rows"],
        n_clone_ids=len(scan["clone_ids"]),
        n_ref_rows=scan["n_ref_rows"],
        n_alt_rows=scan["n_alt_rows"],
        n_other_rows=scan["n_other_rows"],
        warnings=tuple(warnings),
    )


def _find_raw_header_row(rows: list[list[str]]) -> int | None:
    for row_number, row in enumerate(rows, start=1):
        header = [_clean(value) for value in row]
        if tuple(header[:3]) == REQUIRED_PREFIX:
            return row_number
    return None


def _find_fixed_header_row(rows: list[list[str]]) -> int | None:
    for row_number, row in enumerate(rows, start=1):
        header = [_clean(value) for value in row]
        if header[:4] == ["Code_version", *REQUIRED_PREFIX]:
            return row_number
    return None


def _scan_data_rows(
    *,
    path: Path,
    delimiter: str,
    expected_header_row: int,
    n_columns: int,
    first_sample_col: int,
    sample_start_idx: int,
    max_examples: int,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    clone_ids: set[str] = set()
    clones_with_ref: set[str] = set()
    clones_with_alt: set[str] = set()
    ref_lengths: dict[str, int] = {}
    alt_lengths: dict[str, int] = {}

    malformed: list[str] = []
    missing_required: list[str] = []
    fixed_examples: list[str] = []
    lowercase_examples: list[str] = []
    non_atcg_examples: list[str] = []
    dash_examples: list[str] = []
    nonnumeric_examples: list[str] = []
    empty_rows: list[int] = []

    n_data_rows = 0
    n_ref_rows = 0
    n_alt_rows = 0
    n_other_rows = 0
    has_ref_0001 = False
    has_alt_0002 = False
    has_tmp = False

    try:
        with _open_text(path) as handle:
            reader = csv.reader(handle, delimiter=delimiter)

            for row_num, row in enumerate(reader, start=1):
                if row_num <= expected_header_row:
                    continue

                cleaned = [_clean(value) for value in row]
                if not cleaned or all(_is_missing(value) for value in cleaned):
                    if len(empty_rows) < max_examples:
                        empty_rows.append(row_num)
                    continue

                n_data_rows += 1

                if len(row) != n_columns and len(malformed) < max_examples:
                    malformed.append(f"row {row_num}: expected {n_columns}, found {len(row)}")

                if len(cleaned) < 3 or not cleaned[0] or not cleaned[1] or not cleaned[2]:
                    if len(missing_required) < max_examples:
                        missing_required.append(f"row {row_num}")
                    continue

                allele_id, clone_id, allele_seq = cleaned[0], cleaned[1], cleaned[2]
                clone_ids.add(clone_id)

                if FIXED_REF_RE.search(allele_id):
                    has_ref_0001 = True
                if FIXED_ALT_RE.search(allele_id):
                    has_alt_0002 = True
                if FIXED_TMP_RE.search(allele_id):
                    has_tmp = True
                if _is_fixed_id(allele_id) and len(fixed_examples) < max_examples:
                    fixed_examples.append(allele_id)

                if RAW_REF_RE.search(allele_id):
                    n_ref_rows += 1
                    clones_with_ref.add(clone_id)
                    ref_lengths.setdefault(clone_id, len(allele_seq))
                elif RAW_ALT_RE.search(allele_id):
                    n_alt_rows += 1
                    clones_with_alt.add(clone_id)
                    alt_lengths.setdefault(clone_id, len(allele_seq))
                else:
                    n_other_rows += 1

                if LOWERCASE_BASE_RE.search(allele_seq) and len(lowercase_examples) < max_examples:
                    lowercase_examples.append(f"row {row_num}: {allele_id}")

                if NON_ATCG_DASH_RE.search(allele_seq) and len(non_atcg_examples) < max_examples:
                    non_atcg_examples.append(f"row {row_num}: {allele_id}")

                if "-" in allele_seq and len(dash_examples) < max_examples:
                    dash_examples.append(f"row {row_num}: {allele_id}")

                for col_num, value in enumerate(cleaned[sample_start_idx:], start=first_sample_col):
                    if _is_missing(value):
                        continue
                    try:
                        float(value)
                    except ValueError:
                        if len(nonnumeric_examples) < max_examples:
                            nonnumeric_examples.append(f"row {row_num}, column {col_num}: {value!r}")
                        break

    except csv.Error as exc:
        errors.append(f"Could not parse MADC CSV after the header: {exc}")

    if malformed:
        errors.append("Malformed CSV rows found: " + "; ".join(malformed))

    if missing_required:
        errors.append("Blank/missing AlleleID, CloneID, or AlleleSequence found in " + "; ".join(missing_required))

    if lowercase_examples:
        warnings.append("Lowercase bases found. Examples: " + "; ".join(lowercase_examples))

    if non_atcg_examples:
        warnings.append("Non-ATCG/IUPAC characters found. Examples: " + "; ".join(non_atcg_examples))

    if dash_examples:
        warnings.append("Dash '-' characters found. Examples: " + "; ".join(dash_examples))

    if nonnumeric_examples:
        warnings.append("Nonnumeric sample/read-count cells found. Examples: " + "; ".join(nonnumeric_examples))

    if empty_rows:
        warnings.append(f"All-empty data rows found. Examples: {empty_rows}.")

    return {
        "errors": errors,
        "warnings": warnings,
        "n_data_rows": n_data_rows,
        "n_ref_rows": n_ref_rows,
        "n_alt_rows": n_alt_rows,
        "n_other_rows": n_other_rows,
        "clone_ids": clone_ids,
        "clones_with_ref": clones_with_ref,
        "clones_with_alt": clones_with_alt,
        "ref_lengths": ref_lengths,
        "alt_lengths": alt_lengths,
        "has_ref_0001": has_ref_0001,
        "has_alt_0002": has_alt_0002,
        "has_tmp": has_tmp,
        "fixed_examples": fixed_examples,
    }


def _scan_for_fixed_ids(
    path: str | Path,
    delimiter: str,
    *,
    max_rows: int = 10_000,
    max_examples: int = 5,
) -> tuple[bool, list[str]]:
    has_ref_0001 = False
    has_alt_0002 = False
    has_tmp = False
    examples: list[str] = []

    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        allele_idx: int | None = None

        for row in reader:
            cleaned = [_clean(value) for value in row]
            if "AlleleID" in cleaned:
                allele_idx = cleaned.index("AlleleID")
                break

        if allele_idx is None:
            return False, examples

        for row_count, row in enumerate(reader, start=1):
            if row_count > max_rows:
                break
            if allele_idx >= len(row):
                continue

            allele_id = _clean(row[allele_idx])
            if not allele_id:
                continue

            matched = False
            if FIXED_REF_RE.search(allele_id):
                has_ref_0001 = True
                matched = True
            if FIXED_ALT_RE.search(allele_id):
                has_alt_0002 = True
                matched = True
            if FIXED_TMP_RE.search(allele_id):
                has_tmp = True
                matched = True

            if matched and len(examples) < max_examples:
                examples.append(allele_id)

    looks_fixed = (has_ref_0001 and has_alt_0002) or (has_tmp and (has_ref_0001 or has_alt_0002))
    return looks_fixed, examples


def _fixed_file_message(examples: list[str]) -> str:
    suffix = f" Examples: {', '.join(examples)}." if examples else ""
    return (
        "This looks like a fixedAlleleID/HapApp-processed MADC, not a raw MADC. "
        "Upload the original raw DArT/MADC report instead." + suffix
    )


def _is_fixed_id(allele_id: str) -> bool:
    return bool(
        FIXED_REF_RE.search(allele_id)
        or FIXED_ALT_RE.search(allele_id)
        or FIXED_TMP_RE.search(allele_id)
    )


def _read_first_rows(path: str | Path, delimiter: str, n_rows: int) -> list[list[str]]:
    rows: list[list[str]] = []
    try:
        with _open_text(path) as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            for _ in range(n_rows):
                try:
                    rows.append(next(reader))
                except StopIteration:
                    break
    except csv.Error as exc:
        raise MADCValidationError([f"Could not parse MADC CSV: {exc}"]) from exc
    return rows


def _read_sample_text(path: str | Path, n_bytes: int = 64_000) -> str:
    with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return handle.read(n_bytes)


def _detect_delimiter(sample_text: str) -> str:
    counts = {delimiter: sample_text.count(delimiter) for delimiter in [",", "\t", ";"]}
    return max(counts, key=counts.get) if max(counts.values()) else ","


@contextmanager
def _open_text(path: str | Path) -> Iterator[TextIO]:
    with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        yield handle


def _clean(value: object) -> str:
    return "" if value is None else str(value).replace("\ufeff", "").strip()


def _is_missing(value: object) -> bool:
    return _clean(value) in MISSING
