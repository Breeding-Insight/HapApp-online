from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hapapp_python.database import FirestoreRepository

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


def assert_submission_store_ready(db: FirestoreRepository | None = None) -> None:
    repository = db or FirestoreRepository()
    try:
        repository.assert_ready()
    except Exception as exc:
        raise RuntimeError(
            "The configured Firestore database is not accessible. Verify FIRESTORE_DATABASE, "
            "the Google Cloud project, and the Cloud Run service account's roles/datastore.user permission."
        ) from exc


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


def _duplicate_key_id(madc_filename: str, inferred_project_id: str) -> str:
    normalized_filename = Path(madc_filename).name.strip().casefold()
    normalized_project_id = inferred_project_id.strip().casefold()
    return hashlib.sha256(f"{normalized_filename}\0{normalized_project_id}".encode("utf-8")).hexdigest()


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
    db: FirestoreRepository | None = None,
) -> dict[str, Any] | None:
    """Find a previously tracked run with the same source filename and project ID."""
    filename = Path(madc_filename).name.strip()
    project_id = inferred_project_id.strip()
    if not filename or not project_id:
        return None
    repository = db or FirestoreRepository()
    return repository.find_duplicate_submission(_duplicate_key_id(filename, project_id))


def persist_submission_metadata(metadata: MADCSubmissionMetadata, db: FirestoreRepository | None = None) -> None:
    repository = db or FirestoreRepository()
    payload = asdict(metadata)
    normalized_filename = Path(metadata.madc_filename).name.strip()
    normalized_project_id = (metadata.inferred_project_id or "").strip()
    payload["metadata_created_at"] = payload.pop("created_at")
    repository.upsert_submission(
        metadata.run_id,
        payload,
        duplicate_key_id=(
            _duplicate_key_id(normalized_filename, normalized_project_id)
            if normalized_project_id
            else None
        ),
    )


def persist_submission_decision(
    run_id: str,
    submitter_orcid_id: str,
    status: str,
    db: FirestoreRepository | None = None,
) -> int:
    if status not in MADC_SUBMISSION_DECISIONS:
        raise ValueError(f"Invalid MADC submission decision: {status}")
    if not submitter_orcid_id:
        raise ValueError("A submitter ORCID iD is required to record a submission decision.")

    repository = db or FirestoreRepository()
    return repository.update_submission(
        run_id,
        {"submission_status": status, "decision_at": datetime.now(timezone.utc)},
        submitter_orcid_id=submitter_orcid_id,
        expected_submission_status="awaiting_decision",
    )


def claim_submission_for_publication(
    run_id: str,
    submitter_orcid_id: str,
    db: FirestoreRepository | None = None,
) -> int:
    """Atomically claim one awaiting run so duplicate callbacks cannot publish it twice."""
    if not submitter_orcid_id:
        raise ValueError("A submitter ORCID iD is required to publish a submission.")
    repository = db or FirestoreRepository()
    return repository.update_submission(
        run_id,
        {"submission_status": "publishing", "decision_at": datetime.now(timezone.utc)},
        submitter_orcid_id=submitter_orcid_id,
        expected_submission_status="awaiting_decision",
        require_not_stale=True,
    )


def release_submission_publication_claim(
    run_id: str,
    submitter_orcid_id: str,
    error: str,
    db: FirestoreRepository | None = None,
    *,
    freshness_status: str | None = None,
) -> int:
    """Make a transient publication failure retryable without hiding its cause."""
    if freshness_status is not None and freshness_status not in MADC_FRESHNESS_STATUSES:
        raise ValueError(f"Invalid MADC freshness status: {freshness_status}")
    repository = db or FirestoreRepository()
    updates: dict[str, Any] = {
        "submission_status": "awaiting_decision",
        "review_feedback": _blank_to_none(error),
    }
    if freshness_status is not None:
        updates["freshness_status"] = freshness_status
    return repository.update_submission(
        run_id,
        updates,
        submitter_orcid_id=submitter_orcid_id,
        expected_submission_status="publishing",
    )


def list_stranded_publishing_submissions(
    minimum_age_seconds: int,
    db: FirestoreRepository | None = None,
) -> list[StrandedPublishingSubmission]:
    """Return expired publication claims that need GitHub reconciliation."""
    if minimum_age_seconds <= 0:
        raise ValueError("The stranded publication minimum age must be greater than zero.")
    repository = db or FirestoreRepository()
    cutoff = datetime.now(timezone.utc).timestamp() - minimum_age_seconds
    expired: list[tuple[datetime, dict[str, Any]]] = []
    for row in repository.list_submissions_by_status("publishing", limit=100):
        changed_at = row.get("decision_at") or row.get("updated_at") or row.get("created_at")
        if isinstance(changed_at, str):
            changed_at = datetime.fromisoformat(changed_at.replace("Z", "+00:00"))
        if isinstance(changed_at, datetime):
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=timezone.utc)
            if changed_at.timestamp() <= cutoff:
                expired.append((changed_at, row))
    rows = [row for _, row in sorted(expired, key=lambda item: item[0])]
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
    db: FirestoreRepository | None = None,
) -> int:
    """Close an expired claim whose source branch advanced without its commit."""
    repository = db or FirestoreRepository()
    now = datetime.now(timezone.utc)
    return repository.update_submission(
        run_id,
        {
            "submission_status": "changes_requested",
            "freshness_status": "stale",
            "review_feedback": _blank_to_none(review_feedback),
            "freshness_checked_at": now,
            "reviewed_at": now,
        },
        submitter_orcid_id=submitter_orcid_id,
        expected_submission_status="publishing",
    )


def get_submission_state(
    run_id: str,
    submitter_orcid_id: str,
    db: FirestoreRepository | None = None,
) -> MADCSubmissionState | None:
    if not run_id or not submitter_orcid_id:
        return None

    repository = db or FirestoreRepository()
    row = repository.get_submission(run_id)
    if not row or row.get("submitter_orcid_id") != submitter_orcid_id:
        return None
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
    db: FirestoreRepository | None = None,
) -> int:
    repository = db or FirestoreRepository()
    return repository.update_submission(
        run_id,
        {
            "input_database_version": input_database_version,
            "proposed_database_version": proposed_database_version,
            "output_checksums_json": output_checksums_json,
        },
        submitter_orcid_id=submitter_orcid_id,
    )


def persist_submission_freshness(
    run_id: str,
    submitter_orcid_id: str,
    freshness_status: str,
    *,
    review_feedback: str | None = None,
    db: FirestoreRepository | None = None,
) -> int:
    if freshness_status not in MADC_FRESHNESS_STATUSES:
        raise ValueError(f"Invalid MADC freshness status: {freshness_status}")
    repository = db or FirestoreRepository()
    return repository.update_submission(
        run_id,
        {
            "freshness_status": freshness_status,
            "review_feedback": _blank_to_none(review_feedback),
            "freshness_checked_at": datetime.now(timezone.utc),
        },
        submitter_orcid_id=submitter_orcid_id,
    )


def persist_submission_archive_status(
    run_id: str,
    submitter_orcid_id: str,
    status: str,
    error: str | None = None,
    db: FirestoreRepository | None = None,
) -> int:
    if status not in MADC_ARCHIVE_STATUSES - {"pending"}:
        raise ValueError(f"Invalid MADC archive status: {status}")

    repository = db or FirestoreRepository()
    return repository.update_submission(
        run_id,
        {
            "archive_status": status,
            "archive_error": _blank_to_none(error),
            "archive_at": datetime.now(timezone.utc),
        },
        submitter_orcid_id=submitter_orcid_id,
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
    db: FirestoreRepository | None = None,
) -> int:
    if status not in MADC_REVIEW_STATUSES:
        raise ValueError(f"Invalid MADC review status: {status}")
    if freshness_status not in MADC_FRESHNESS_STATUSES:
        raise ValueError(f"Invalid MADC freshness status: {freshness_status}")

    repository = db or FirestoreRepository()
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {
        "submission_status": status,
        "freshness_status": freshness_status,
        "review_feedback": _blank_to_none(review_feedback),
        "reviewer_orcid_id": _blank_to_none(reviewer_orcid_id),
        "pull_request_url": _blank_to_none(pull_request_url),
        "incorporation_commit_url": _blank_to_none(incorporation_commit_url),
        "freshness_checked_at": now,
        "reviewed_at": now,
    }
    if input_github_commit_sha is not None:
        updates["input_github_commit_sha"] = _blank_to_none(input_github_commit_sha)
    if status == "incorporated":
        updates["incorporated_at"] = now
    return repository.update_submission(run_id, updates)


def persist_github_incorporation(
    run_id: str,
    submitter_orcid_id: str,
    commit_url: str,
    db: FirestoreRepository | None = None,
) -> int:
    """Finalize a publication only while the caller still owns its durable claim."""
    if not run_id or not submitter_orcid_id or not commit_url:
        raise ValueError("Run ID, submitter ORCID iD, and GitHub commit URL are required.")
    repository = db or FirestoreRepository()
    now = datetime.now(timezone.utc)
    return repository.update_submission(
        run_id,
        {
            "submission_status": "incorporated",
            "freshness_status": "current",
            "review_feedback": None,
            "incorporation_commit_url": commit_url,
            "freshness_checked_at": now,
            "reviewed_at": now,
            "incorporated_at": now,
        },
        submitter_orcid_id=submitter_orcid_id,
        expected_submission_status="publishing",
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
