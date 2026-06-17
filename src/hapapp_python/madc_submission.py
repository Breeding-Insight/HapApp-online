from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hapapp_python.database import DatabaseManager

MADC_SUBMISSION_METADATA_FILENAME = "hapapp_madc_submission_metadata.json"
MADC_SUBMISSION_STATUSES = {
    "awaiting_decision",
    "submitted_for_review",
    "changes_requested",
    "accepted",
    "incorporated",
    "rejected",
    "declined",
}
MADC_SUBMISSION_DECISIONS = {"submitted_for_review", "declined"}
MADC_REVIEW_STATUSES = {"submitted_for_review", "changes_requested", "accepted", "incorporated", "rejected"}
MADC_FRESHNESS_STATUSES = {"unknown", "current", "stale"}
MADC_ARCHIVE_STATUSES = {"pending", "archived", "not_configured", "failed"}
DAL_PROJECT_RE = re.compile(r"(?<![A-Za-z0-9])DA[LI]\d{2}[-_]\d{4}(?![A-Za-z0-9])", re.IGNORECASE)
DAI_PROJECT_RE = re.compile(r"(?<![A-Za-z0-9])(?:DAI[-_]?)?\d{5,}(?![A-Za-z0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class MADCSubmissionMetadata:
    run_id: str
    submitter_orcid_id: str
    submitter_display_name: str | None
    submitter_email: str | None
    submitted_for_name: str | None
    submitted_for_location: str | None
    submitted_for_email: str | None
    submitted_for_institution: str | None
    informal_project_name: str | None
    inferred_project_id: str | None
    madc_filename: str
    panel_id: str
    panel_label: str
    input_github_repository: str | None
    input_github_ref: str | None
    created_at: str


@dataclass(frozen=True)
class MADCSubmissionState:
    run_id: str
    submission_status: str
    freshness_status: str
    review_feedback: str | None
    pull_request_url: str | None
    incorporation_commit_url: str | None
    archive_status: str
    archive_error: str | None


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def infer_genotyping_project_id(filename: str | None) -> str | None:
    name = Path(filename or "").name
    project_ids: list[str] = []

    for match in DAL_PROJECT_RE.finditer(name):
        project_ids.append(match.group(0).replace("_", "-"))

    if project_ids:
        return "_".join(dict.fromkeys(project_ids))

    match = DAI_PROJECT_RE.search(name)
    if not match:
        return None
    token = match.group(0).replace("_", "-")
    if token.upper().startswith("DAI") and not token.upper().startswith("DAI-"):
        token = "DAI-" + token[3:].lstrip("-")
    return token


def build_madc_submission_metadata(
    *,
    run_id: str,
    current_user: dict[str, str] | None,
    submitter_profile: dict[str, Any] | None,
    submitted_for_name: str | None,
    submitted_for_location: str | None,
    submitted_for_email: str | None,
    submitted_for_institution: str | None,
    informal_project_name: str | None,
    inferred_project_id: str | None,
    madc_filename: str,
    panel_id: str,
    panel_label: str,
    input_github_repository: str | None = None,
    input_github_ref: str | None = None,
) -> MADCSubmissionMetadata:
    profile = submitter_profile or {}
    return MADCSubmissionMetadata(
        run_id=run_id,
        submitter_orcid_id=(current_user or {}).get("orcid_id", ""),
        submitter_display_name=profile.get("display_name") or (current_user or {}).get("user_name"),
        submitter_email=profile.get("public_email"),
        submitted_for_name=_blank_to_none(submitted_for_name),
        submitted_for_location=_blank_to_none(submitted_for_location),
        submitted_for_email=_blank_to_none(submitted_for_email),
        submitted_for_institution=_blank_to_none(submitted_for_institution),
        informal_project_name=_blank_to_none(informal_project_name),
        inferred_project_id=_blank_to_none(inferred_project_id),
        madc_filename=madc_filename,
        panel_id=panel_id,
        panel_label=panel_label,
        input_github_repository=_blank_to_none(input_github_repository),
        input_github_ref=_blank_to_none(input_github_ref),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def write_submission_metadata(work_dir: Path, metadata: MADCSubmissionMetadata) -> str:
    path = work_dir / MADC_SUBMISSION_METADATA_FILENAME
    path.write_text(json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return MADC_SUBMISSION_METADATA_FILENAME


def persist_submission_metadata(metadata: MADCSubmissionMetadata, db: DatabaseManager | None = None) -> None:
    manager = db or DatabaseManager()
    payload = asdict(metadata)
    manager.execute_update(
        """
        MERGE hapapp.madc_submissions AS target
        USING (SELECT ? AS run_id) AS source
        ON target.run_id = source.run_id
        WHEN MATCHED THEN
            UPDATE SET
                submitter_orcid_id = ?, submitter_display_name = ?, submitter_email = ?,
                submitted_for_name = ?, submitted_for_location = ?, submitted_for_email = ?,
                submitted_for_institution = ?, informal_project_name = ?, inferred_project_id = ?,
                madc_filename = ?, panel_id = ?, panel_label = ?,
                input_github_repository = ?, input_github_ref = ?, metadata_json = ?,
                updated_at = GETDATE()
        WHEN NOT MATCHED THEN
            INSERT (
                run_id, submitter_orcid_id, submitter_display_name, submitter_email,
                submitted_for_name, submitted_for_location, submitted_for_email,
                submitted_for_institution, informal_project_name, inferred_project_id,
                madc_filename, panel_id, panel_label, input_github_repository, input_github_ref, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            metadata.run_id,
            metadata.submitter_orcid_id,
            metadata.submitter_display_name,
            metadata.submitter_email,
            metadata.submitted_for_name,
            metadata.submitted_for_location,
            metadata.submitted_for_email,
            metadata.submitted_for_institution,
            metadata.informal_project_name,
            metadata.inferred_project_id,
            metadata.madc_filename,
            metadata.panel_id,
            metadata.panel_label,
            metadata.input_github_repository,
            metadata.input_github_ref,
            json.dumps(payload, sort_keys=True),
            metadata.run_id,
            metadata.submitter_orcid_id,
            metadata.submitter_display_name,
            metadata.submitter_email,
            metadata.submitted_for_name,
            metadata.submitted_for_location,
            metadata.submitted_for_email,
            metadata.submitted_for_institution,
            metadata.informal_project_name,
            metadata.inferred_project_id,
            metadata.madc_filename,
            metadata.panel_id,
            metadata.panel_label,
            metadata.input_github_repository,
            metadata.input_github_ref,
            json.dumps(payload, sort_keys=True),
        ),
    )


def persist_submission_decision(
    run_id: str,
    submitter_orcid_id: str,
    status: str,
    db: DatabaseManager | None = None,
) -> int:
    if status not in MADC_SUBMISSION_DECISIONS:
        raise ValueError(f"Invalid MADC submission decision: {status}")
    if not submitter_orcid_id:
        raise ValueError("A submitter ORCID iD is required to record a submission decision.")

    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET submission_status = ?, decision_at = GETDATE(), updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ? AND submission_status = 'awaiting_decision';
        """,
        (status, run_id, submitter_orcid_id),
    )


def get_submission_state(
    run_id: str,
    submitter_orcid_id: str,
    db: DatabaseManager | None = None,
) -> MADCSubmissionState | None:
    if not run_id or not submitter_orcid_id:
        return None

    manager = db or DatabaseManager()
    rows = manager.execute_query(
        """
        SELECT
            run_id, submission_status, freshness_status, review_feedback,
            pull_request_url, incorporation_commit_url, archive_status, archive_error
        FROM hapapp.madc_submissions
        WHERE run_id = ? AND submitter_orcid_id = ?;
        """,
        (run_id, submitter_orcid_id),
    )
    if not rows:
        return None

    row = rows[0]
    submission_status = str(row.get("submission_status") or "")
    if submission_status == "submitted":
        submission_status = "submitted_for_review"
    freshness_status = str(row.get("freshness_status") or "unknown")
    archive_status = str(row.get("archive_status") or "pending")
    if submission_status not in MADC_SUBMISSION_STATUSES:
        raise ValueError(f"Invalid stored MADC submission status: {submission_status}")
    if freshness_status not in MADC_FRESHNESS_STATUSES:
        raise ValueError(f"Invalid stored MADC freshness status: {freshness_status}")
    if archive_status not in MADC_ARCHIVE_STATUSES:
        raise ValueError(f"Invalid stored MADC archive status: {archive_status}")

    return MADCSubmissionState(
        run_id=str(row["run_id"]),
        submission_status=submission_status,
        freshness_status=freshness_status,
        review_feedback=_optional_string(row.get("review_feedback")),
        pull_request_url=_optional_string(row.get("pull_request_url")),
        incorporation_commit_url=_optional_string(row.get("incorporation_commit_url")),
        archive_status=archive_status,
        archive_error=_optional_string(row.get("archive_error")),
    )


def persist_submission_result_provenance(
    run_id: str,
    submitter_orcid_id: str,
    *,
    input_database_version: str | None,
    proposed_database_version: str | None,
    output_checksums_json: str | None,
    db: DatabaseManager | None = None,
) -> int:
    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET input_database_version = ?, proposed_database_version = ?,
            output_checksums_json = ?, updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ?;
        """,
        (
            input_database_version,
            proposed_database_version,
            output_checksums_json,
            run_id,
            submitter_orcid_id,
        ),
    )


def persist_submission_archive_status(
    run_id: str,
    submitter_orcid_id: str,
    status: str,
    error: str | None = None,
    db: DatabaseManager | None = None,
) -> int:
    if status not in MADC_ARCHIVE_STATUSES - {"pending"}:
        raise ValueError(f"Invalid MADC archive status: {status}")

    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET archive_status = ?, archive_error = ?, archive_at = GETDATE(), updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ?;
        """,
        (status, _blank_to_none(error), run_id, submitter_orcid_id),
    )


def persist_submission_review_state(
    run_id: str,
    *,
    status: str,
    freshness_status: str,
    review_feedback: str | None = None,
    reviewer_orcid_id: str | None = None,
    pull_request_url: str | None = None,
    incorporation_commit_url: str | None = None,
    input_github_commit_sha: str | None = None,
    db: DatabaseManager | None = None,
) -> int:
    if status not in MADC_REVIEW_STATUSES:
        raise ValueError(f"Invalid MADC review status: {status}")
    if freshness_status not in MADC_FRESHNESS_STATUSES:
        raise ValueError(f"Invalid MADC freshness status: {freshness_status}")

    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET submission_status = ?, freshness_status = ?, review_feedback = ?,
            reviewer_orcid_id = ?, pull_request_url = ?, incorporation_commit_url = ?,
            input_github_commit_sha = COALESCE(?, input_github_commit_sha),
            freshness_checked_at = GETDATE(), reviewed_at = GETDATE(),
            incorporated_at = CASE WHEN ? = 'incorporated' THEN GETDATE() ELSE incorporated_at END,
            updated_at = GETDATE()
        WHERE run_id = ?;
        """,
        (
            status,
            freshness_status,
            _blank_to_none(review_feedback),
            _blank_to_none(reviewer_orcid_id),
            _blank_to_none(pull_request_url),
            _blank_to_none(incorporation_commit_url),
            _blank_to_none(input_github_commit_sha),
            status,
            run_id,
        ),
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
