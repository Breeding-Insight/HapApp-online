from __future__ import annotations

import hashlib
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
    "publishing",
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


def assert_submission_publication_schema_ready(db: DatabaseManager | None = None) -> None:
    manager = db or DatabaseManager()
    rows = manager.execute_query(
        """
        SELECT
            DB_NAME() AS database_name,
            OBJECT_ID('dbo.users', 'U') AS users_object_id,
            OBJECT_ID('hapapp.orcid_profiles', 'U') AS profiles_object_id,
            OBJECT_ID('hapapp.madc_submissions', 'U') AS submissions_object_id,
            (
                SELECT definition
                FROM sys.check_constraints
                WHERE name = 'CK_hapapp_madc_submissions_status'
                  AND parent_object_id = OBJECT_ID('hapapp.madc_submissions')
            ) AS status_constraint_definition;
        """
    )
    state = rows[0] if rows else {}
    database_name = str(state.get("database_name") or "")
    required_objects_exist = all(
        state.get(key) is not None
        for key in ("users_object_id", "profiles_object_id", "submissions_object_id")
    )
    definition = str(state.get("status_constraint_definition") or "")
    if database_name.casefold() != "haplosearch" or not required_objects_exist or "publishing" not in definition:
        raise RuntimeError(
            "The configured SQL Server connection does not have the complete HaploSearch schema. "
            "Run `schema_hapapp.sql` against the server's HaploSearch database "
            "before accepting GitHub submissions."
        )


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
    input_github_commit_sha: str | None
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


@dataclass(frozen=True)
class StrandedPublishingSubmission:
    run_id: str
    submitter_orcid_id: str
    input_github_repository: str | None
    input_github_ref: str | None
    input_github_commit_sha: str | None


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
    input_github_commit_sha: str | None = None,
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
        input_github_commit_sha=_blank_to_none(input_github_commit_sha),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def write_submission_metadata(work_dir: Path, metadata: MADCSubmissionMetadata) -> str:
    path = work_dir / MADC_SUBMISSION_METADATA_FILENAME
    path.write_text(json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return MADC_SUBMISSION_METADATA_FILENAME


def find_duplicate_madc_submission(
    madc_filename: str,
    inferred_project_id: str,
    db: DatabaseManager | None = None,
) -> dict[str, Any] | None:
    """Find a previously tracked run with the same source filename and project ID."""
    filename = Path(madc_filename).name.strip()
    project_id = inferred_project_id.strip()
    if not filename or not project_id:
        return None
    manager = db or DatabaseManager()
    rows = manager.execute_query(
        """
        SELECT TOP (1) run_id, madc_filename, inferred_project_id, submission_status, created_at
        FROM hapapp.madc_submissions
        WHERE LOWER(LTRIM(RTRIM(madc_filename))) = LOWER(?)
          AND LOWER(LTRIM(RTRIM(inferred_project_id))) = LOWER(?)
        ORDER BY created_at DESC;
        """,
        (filename, project_id),
    )
    return rows[0] if rows else None


def persist_submission_metadata(metadata: MADCSubmissionMetadata, db: DatabaseManager | None = None) -> None:
    manager = db or DatabaseManager()
    payload = asdict(metadata)
    normalized_filename = Path(metadata.madc_filename).name.strip()
    normalized_project_id = (metadata.inferred_project_id or "").strip()
    duplicate_lock = "hapapp:madc:" + hashlib.sha256(
        f"{normalized_filename.casefold()}\0{normalized_project_id.casefold()}".encode("utf-8")
    ).hexdigest()
    manager.execute_update(
        """
        DECLARE @new_madc_filename NVARCHAR(512) = ?;
        DECLARE @new_project_id NVARCHAR(255) = ?;
        DECLARE @duplicate_lock_resource NVARCHAR(255) = ?;
        DECLARE @duplicate_lock_result INT;

        EXEC @duplicate_lock_result = sys.sp_getapplock
            @Resource = @duplicate_lock_resource,
            @LockMode = 'Exclusive',
            @LockOwner = 'Transaction',
            @LockTimeout = 10000;
        IF @duplicate_lock_result < 0
            THROW 50020, 'Could not acquire the MADC duplicate-submission lock.', 1;

        IF @new_project_id <> N'' AND EXISTS (
            SELECT 1
            FROM hapapp.madc_submissions
            WHERE LOWER(LTRIM(RTRIM(madc_filename))) = LOWER(@new_madc_filename)
              AND LOWER(LTRIM(RTRIM(inferred_project_id))) = LOWER(@new_project_id)
              AND run_id <> ?
        )
            THROW 50021, 'This MADC filename and formal project ID were already processed.', 1;

        MERGE hapapp.madc_submissions AS target
        USING (SELECT ? AS run_id) AS source
        ON target.run_id = source.run_id
        WHEN MATCHED THEN
            UPDATE SET
                submitter_orcid_id = ?, submitter_display_name = ?, submitter_email = ?,
                submitted_for_name = ?, submitted_for_location = ?, submitted_for_email = ?,
                submitted_for_institution = ?, informal_project_name = ?, inferred_project_id = ?,
                madc_filename = ?, panel_id = ?, panel_label = ?,
                input_github_repository = ?, input_github_ref = ?, input_github_commit_sha = ?, metadata_json = ?,
                updated_at = GETDATE()
        WHEN NOT MATCHED THEN
            INSERT (
                run_id, submitter_orcid_id, submitter_display_name, submitter_email,
                submitted_for_name, submitted_for_location, submitted_for_email,
                submitted_for_institution, informal_project_name, inferred_project_id,
                madc_filename, panel_id, panel_label, input_github_repository, input_github_ref,
                input_github_commit_sha, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            normalized_filename,
            normalized_project_id,
            duplicate_lock,
            metadata.run_id,
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
            metadata.input_github_commit_sha,
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
            metadata.input_github_commit_sha,
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


def claim_submission_for_publication(
    run_id: str,
    submitter_orcid_id: str,
    db: DatabaseManager | None = None,
) -> int:
    """Atomically claim one awaiting run so duplicate callbacks cannot publish it twice."""
    if not submitter_orcid_id:
        raise ValueError("A submitter ORCID iD is required to publish a submission.")
    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET submission_status = 'publishing', decision_at = GETDATE(), updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ?
          AND submission_status = 'awaiting_decision' AND freshness_status <> 'stale';
        """,
        (run_id, submitter_orcid_id),
    )


def release_submission_publication_claim(
    run_id: str,
    submitter_orcid_id: str,
    error: str,
    db: DatabaseManager | None = None,
    *,
    freshness_status: str | None = None,
) -> int:
    """Make a transient publication failure retryable without hiding its cause."""
    if freshness_status is not None and freshness_status not in MADC_FRESHNESS_STATUSES:
        raise ValueError(f"Invalid MADC freshness status: {freshness_status}")
    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET submission_status = 'awaiting_decision',
            review_feedback = CAST(? AS NVARCHAR(MAX)),
            freshness_status = COALESCE(CAST(? AS NVARCHAR(32)), freshness_status),
            updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ? AND submission_status = 'publishing';
        """,
        (_blank_to_none(error), freshness_status, run_id, submitter_orcid_id),
    )


def list_stranded_publishing_submissions(
    minimum_age_seconds: int,
    db: DatabaseManager | None = None,
) -> list[StrandedPublishingSubmission]:
    """Return expired publication claims that need GitHub reconciliation."""
    if minimum_age_seconds <= 0:
        raise ValueError("The stranded publication minimum age must be greater than zero.")
    manager = db or DatabaseManager()
    rows = manager.execute_query(
        """
        SELECT TOP (100)
            run_id, submitter_orcid_id, input_github_repository,
            input_github_ref, input_github_commit_sha
        FROM hapapp.madc_submissions
        WHERE submission_status = 'publishing'
          AND COALESCE(decision_at, updated_at, created_at) <=
              DATEADD(SECOND, -CAST(? AS INT), GETDATE())
        ORDER BY COALESCE(decision_at, updated_at, created_at) ASC;
        """,
        (minimum_age_seconds,),
    )
    return [
        StrandedPublishingSubmission(
            run_id=str(row["run_id"]),
            submitter_orcid_id=str(row["submitter_orcid_id"]),
            input_github_repository=_optional_string(row.get("input_github_repository")),
            input_github_ref=_optional_string(row.get("input_github_ref")),
            input_github_commit_sha=_optional_string(row.get("input_github_commit_sha")),
        )
        for row in rows
    ]


def mark_stranded_publication_stale(
    run_id: str,
    submitter_orcid_id: str,
    review_feedback: str,
    db: DatabaseManager | None = None,
) -> int:
    """Close an expired claim whose source branch advanced without its commit."""
    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET submission_status = 'changes_requested', freshness_status = 'stale',
            review_feedback = CAST(? AS NVARCHAR(MAX)),
            freshness_checked_at = GETDATE(), reviewed_at = GETDATE(), updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ? AND submission_status = 'publishing';
        """,
        (_blank_to_none(review_feedback), run_id, submitter_orcid_id),
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
        SET input_database_version = CAST(? AS NVARCHAR(32)),
            proposed_database_version = CAST(? AS NVARCHAR(32)),
            output_checksums_json = CAST(? AS NVARCHAR(MAX)), updated_at = GETDATE()
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


def persist_submission_freshness(
    run_id: str,
    submitter_orcid_id: str,
    freshness_status: str,
    *,
    review_feedback: str | None = None,
    db: DatabaseManager | None = None,
) -> int:
    if freshness_status not in MADC_FRESHNESS_STATUSES:
        raise ValueError(f"Invalid MADC freshness status: {freshness_status}")
    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET freshness_status = ?, review_feedback = CAST(? AS NVARCHAR(MAX)),
            freshness_checked_at = GETDATE(), updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ?;
        """,
        (freshness_status, _blank_to_none(review_feedback), run_id, submitter_orcid_id),
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
        SET archive_status = ?, archive_error = CAST(? AS NVARCHAR(MAX)),
            archive_at = GETDATE(), updated_at = GETDATE()
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
        SET submission_status = ?, freshness_status = ?,
            review_feedback = CAST(? AS NVARCHAR(MAX)),
            reviewer_orcid_id = CAST(? AS NVARCHAR(255)),
            pull_request_url = CAST(? AS NVARCHAR(1024)),
            incorporation_commit_url = CAST(? AS NVARCHAR(1024)),
            input_github_commit_sha = COALESCE(CAST(? AS NVARCHAR(64)), input_github_commit_sha),
            freshness_checked_at = GETDATE(), reviewed_at = GETDATE(),
            incorporated_at = CASE
                WHEN CAST(? AS NVARCHAR(32)) = 'incorporated' THEN GETDATE()
                ELSE incorporated_at
            END,
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


def persist_github_incorporation(
    run_id: str,
    submitter_orcid_id: str,
    commit_url: str,
    db: DatabaseManager | None = None,
) -> int:
    """Finalize a claimed publication without nullable parameters FreeTDS must infer."""
    if not run_id or not submitter_orcid_id or not commit_url:
        raise ValueError("Run ID, submitter ORCID iD, and GitHub commit URL are required.")
    manager = db or DatabaseManager()
    return manager.execute_update(
        """
        UPDATE hapapp.madc_submissions
        SET submission_status = 'incorporated', freshness_status = 'current',
            review_feedback = NULL, incorporation_commit_url = ?,
            freshness_checked_at = GETDATE(), reviewed_at = GETDATE(),
            incorporated_at = GETDATE(), updated_at = GETDATE()
        WHERE run_id = ? AND submitter_orcid_id = ? AND submission_status = 'publishing';
        """,
        (commit_url, run_id, submitter_orcid_id),
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
