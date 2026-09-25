from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hapapp_python import config

try:
    from google.cloud import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter

    FIRESTORE_AVAILABLE = True
except ImportError:  # pragma: no cover - covered by the container dependency smoke test.
    firestore = None  # type: ignore[assignment]
    FieldFilter = None  # type: ignore[assignment]
    FIRESTORE_AVAILABLE = False


USERS_COLLECTION = "users"
PROFILES_COLLECTION = "orcid_profiles"
SUBMISSIONS_COLLECTION = "madc_submissions"
SUBMISSION_KEYS_COLLECTION = "submission_keys"


class DuplicateSubmissionError(RuntimeError):
    """Raised when another run owns a normalized filename/project identifier."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FirestoreRepository:
    """Server-side Firestore persistence using the Cloud Run service identity."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            if not FIRESTORE_AVAILABLE:
                raise ImportError("google-cloud-firestore is required for Firestore persistence.")
            client = firestore.Client(
                project=config.GOOGLE_CLOUD_PROJECT or None,
                database=config.FIRESTORE_DATABASE,
            )
        self.client = client

    def assert_ready(self) -> None:
        """Perform a minimal authenticated read without requiring seeded data."""
        self.client.collection(USERS_COLLECTION).limit(1).get()

    def get_active_user(self, orcid_id: str) -> dict[str, Any] | None:
        snapshot = self.client.collection(USERS_COLLECTION).document(orcid_id).get()
        if not snapshot.exists:
            return None
        user = snapshot.to_dict() or {}
        if not user.get("is_active", False):
            return None
        user.setdefault("orcid_id", snapshot.id)
        return user

    def get_profile(self, orcid_id: str) -> dict[str, Any] | None:
        snapshot = self.client.collection(PROFILES_COLLECTION).document(orcid_id).get()
        if not snapshot.exists:
            return None
        profile = snapshot.to_dict() or {}
        profile.setdefault("orcid_id", snapshot.id)
        return profile

    def upsert_profile(self, profile: dict[str, Any]) -> None:
        reference = self.client.collection(PROFILES_COLLECTION).document(str(profile["orcid_id"]))
        snapshot = reference.get()
        now = _utcnow()
        values = {**profile, "last_fetched_at": now, "updated_at": now}
        if not snapshot.exists:
            values["created_at"] = now
        reference.set(values, merge=True)

    def find_duplicate_submission(self, duplicate_key_id: str) -> dict[str, Any] | None:
        key_snapshot = self.client.collection(SUBMISSION_KEYS_COLLECTION).document(duplicate_key_id).get()
        if not key_snapshot.exists:
            return None
        run_id = str((key_snapshot.to_dict() or {}).get("run_id") or "")
        return self.get_submission(run_id) if run_id else None

    def upsert_submission(
        self,
        run_id: str,
        values: dict[str, Any],
        *,
        duplicate_key_id: str | None,
        replace_run_id: str | None = None,
        replaceable_statuses: frozenset[str] = frozenset(),
    ) -> None:
        """Store a submission and claim its filename/project key.

        A new submission may take the key only from ``replace_run_id`` (the run the
        user approved replacing), and only while that run's status is in
        ``replaceable_statuses``; that run is marked superseded. Updates to an
        existing submission never take a key from another run.
        """
        transaction = self.client.transaction()

        @firestore.transactional
        def commit(transaction):
            submission_ref = self.client.collection(SUBMISSIONS_COLLECTION).document(run_id)
            submission_snapshot = submission_ref.get(transaction=transaction)
            existing = (submission_snapshot.to_dict() or {}) if submission_snapshot.exists else {}
            old_key_id = existing.get("duplicate_key_id")

            new_key_ref = None
            new_key_snapshot = None
            if duplicate_key_id:
                new_key_ref = self.client.collection(SUBMISSION_KEYS_COLLECTION).document(duplicate_key_id)
                new_key_snapshot = new_key_ref.get(transaction=transaction)

            old_key_ref = None
            old_key_snapshot = None
            if old_key_id and old_key_id != duplicate_key_id:
                old_key_ref = self.client.collection(SUBMISSION_KEYS_COLLECTION).document(str(old_key_id))
                old_key_snapshot = old_key_ref.get(transaction=transaction)

            superseded_ref = None
            if new_key_snapshot is not None and new_key_snapshot.exists:
                key_owner = str((new_key_snapshot.to_dict() or {}).get("run_id") or "")
                if key_owner and key_owner != run_id:
                    owner_ref = self.client.collection(SUBMISSIONS_COLLECTION).document(key_owner)
                    owner_snapshot = owner_ref.get(transaction=transaction)
                    owner_status = (
                        (owner_snapshot.to_dict() or {}).get("submission_status") if owner_snapshot.exists else None
                    )
                    replaceable = key_owner == replace_run_id and (
                        not owner_snapshot.exists or owner_status in replaceable_statuses
                    )
                    if submission_snapshot.exists or not replaceable:
                        raise DuplicateSubmissionError(
                            "This MADC filename and formal project ID were already processed."
                        )
                    if owner_snapshot.exists:
                        superseded_ref = owner_ref

            now = _utcnow()
            document = {
                **values,
                "run_id": run_id,
                "duplicate_key_id": duplicate_key_id,
                "updated_at": now,
            }
            if not submission_snapshot.exists:
                document.update(
                    {
                        "submission_status": "awaiting_decision",
                        "freshness_status": "unknown",
                        "archive_status": "pending",
                        "created_at": now,
                    }
                )
            transaction.set(submission_ref, document, merge=True)

            if superseded_ref is not None:
                transaction.update(
                    superseded_ref,
                    {"submission_status": "superseded", "superseded_by_run_id": run_id, "updated_at": now},
                )

            if new_key_ref is not None:
                transaction.set(
                    new_key_ref,
                    {
                        "run_id": run_id,
                        "madc_filename": values.get("madc_filename"),
                        "inferred_project_id": values.get("inferred_project_id"),
                        "updated_at": now,
                    },
                )

            if old_key_ref is not None and old_key_snapshot is not None and old_key_snapshot.exists:
                old_owner = str((old_key_snapshot.to_dict() or {}).get("run_id") or "")
                if old_owner == run_id:
                    transaction.delete(old_key_ref)

        commit(transaction)

    def get_submission(self, run_id: str) -> dict[str, Any] | None:
        snapshot = self.client.collection(SUBMISSIONS_COLLECTION).document(run_id).get()
        if not snapshot.exists:
            return None
        submission = snapshot.to_dict() or {}
        submission.setdefault("run_id", snapshot.id)
        return submission

    def update_submission(
        self,
        run_id: str,
        updates: dict[str, Any],
        *,
        submitter_orcid_id: str | None = None,
        expected_submission_status: str | None = None,
        require_not_stale: bool = False,
    ) -> int:
        transaction = self.client.transaction()

        @firestore.transactional
        def commit(transaction) -> int:
            reference = self.client.collection(SUBMISSIONS_COLLECTION).document(run_id)
            snapshot = reference.get(transaction=transaction)
            if not snapshot.exists:
                return 0
            submission = snapshot.to_dict() or {}
            if submitter_orcid_id is not None and submission.get("submitter_orcid_id") != submitter_orcid_id:
                return 0
            if (
                expected_submission_status is not None
                and submission.get("submission_status") != expected_submission_status
            ):
                return 0
            if require_not_stale and submission.get("freshness_status") == "stale":
                return 0
            transaction.update(reference, {**updates, "updated_at": _utcnow()})
            return 1

        return int(commit(transaction))

    def list_submissions_by_status(self, status: str, *, limit: int = 100) -> list[dict[str, Any]]:
        query = self.client.collection(SUBMISSIONS_COLLECTION).where(
            filter=FieldFilter("submission_status", "==", status)
        )
        rows: list[dict[str, Any]] = []
        for snapshot in query.limit(limit).stream():
            row = snapshot.to_dict() or {}
            row.setdefault("run_id", snapshot.id)
            rows.append(row)
        return rows


# Keep the former injected dependency name source-compatible for integrations.
DatabaseManager = FirestoreRepository
