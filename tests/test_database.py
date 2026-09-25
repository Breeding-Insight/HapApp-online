from __future__ import annotations

import unittest
from unittest.mock import patch

from hapapp_python.database import DuplicateSubmissionError, FirestoreRepository


class FakeSnapshot:
    def __init__(self, document_id: str, value: dict | None) -> None:
        self.id = document_id
        self._value = value
        self.exists = value is not None

    def to_dict(self):
        return dict(self._value or {})


class FakeDocument:
    def __init__(self, client, collection: str, document_id: str) -> None:
        self.client = client
        self.collection = collection
        self.id = document_id

    @property
    def key(self):
        return self.collection, self.id

    def get(self, transaction=None):
        return FakeSnapshot(self.id, self.client.data.get(self.key))

    def set(self, values, merge=False):
        if merge:
            self.client.data[self.key] = {**self.client.data.get(self.key, {}), **values}
        else:
            self.client.data[self.key] = dict(values)


class FakeQuery:
    def __init__(self, client, collection: str) -> None:
        self.client = client
        self.collection = collection
        self.limit_value = None

    def where(self, *, filter):
        self.filter = filter
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def get(self):
        return list(self.stream())

    def stream(self):
        rows = [
            FakeSnapshot(document_id, value)
            for (collection, document_id), value in self.client.data.items()
            if collection == self.collection
        ]
        return iter(rows[: self.limit_value])

    def document(self, document_id: str):
        return FakeDocument(self.client, self.collection, document_id)


class FakeTransaction:
    def set(self, reference, values, merge=False):
        reference.set(values, merge=merge)

    def update(self, reference, values):
        reference.set(values, merge=True)

    def delete(self, reference):
        reference.client.data.pop(reference.key, None)


class FakeClient:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict] = {}

    def collection(self, name: str):
        return FakeQuery(self, name)

    def transaction(self):
        return FakeTransaction()


def synchronous_transaction(function):
    return lambda transaction: function(transaction)


class FirestoreRepositoryTests(unittest.TestCase):
    def test_reads_only_active_users(self) -> None:
        client = FakeClient()
        client.data[("users", "active")] = {"display_name": "Active", "is_active": True}
        client.data[("users", "inactive")] = {"display_name": "Inactive", "is_active": False}
        repository = FirestoreRepository(client)

        self.assertEqual(repository.get_active_user("active")["orcid_id"], "active")
        self.assertIsNone(repository.get_active_user("inactive"))
        self.assertIsNone(repository.get_active_user("missing"))

    @patch("hapapp_python.database.firestore.transactional", side_effect=synchronous_transaction)
    def test_duplicate_key_is_claimed_transactionally(self, _transactional) -> None:
        client = FakeClient()
        repository = FirestoreRepository(client)

        repository.upsert_submission(
            "run-1",
            {"madc_filename": "report.csv", "inferred_project_id": "DAI-1"},
            duplicate_key_id="key",
        )

        with self.assertRaisesRegex(DuplicateSubmissionError, "already processed"):
            repository.upsert_submission(
                "run-2",
                {"madc_filename": "report.csv", "inferred_project_id": "DAI-1"},
                duplicate_key_id="key",
            )

        self.assertEqual(client.data[("submission_keys", "key")]["run_id"], "run-1")

    @patch("hapapp_python.database.firestore.transactional", side_effect=synchronous_transaction)
    def test_new_run_supersedes_unshared_run_with_same_key(self, _transactional) -> None:
        client = FakeClient()
        repository = FirestoreRepository(client)
        values = {"madc_filename": "report.csv", "inferred_project_id": "DAI-1", "submitter_orcid_id": "a"}
        replaceable = frozenset({"awaiting_decision", "declined", "superseded"})

        repository.upsert_submission("run-1", values, duplicate_key_id="key", replaceable_statuses=replaceable)
        repository.upsert_submission(
            "run-2",
            {**values, "submitter_orcid_id": "b"},
            duplicate_key_id="key",
            replace_run_id="run-1",
            replaceable_statuses=replaceable,
        )

        self.assertEqual(client.data[("submission_keys", "key")]["run_id"], "run-2")
        superseded = client.data[("madc_submissions", "run-1")]
        self.assertEqual(superseded["submission_status"], "superseded")
        self.assertEqual(superseded["superseded_by_run_id"], "run-2")
        self.assertEqual(client.data[("madc_submissions", "run-2")]["submission_status"], "awaiting_decision")
        # The replaced run can no longer be claimed for publication or declined.
        self.assertEqual(
            repository.update_submission(
                "run-1",
                {"submission_status": "publishing"},
                submitter_orcid_id="a",
                expected_submission_status="awaiting_decision",
            ),
            0,
        )

    @patch("hapapp_python.database.firestore.transactional", side_effect=synchronous_transaction)
    def test_unshared_run_is_not_replaced_without_approval(self, _transactional) -> None:
        client = FakeClient()
        repository = FirestoreRepository(client)
        values = {"madc_filename": "report.csv", "inferred_project_id": "DAI-1"}
        replaceable = frozenset({"awaiting_decision", "declined", "superseded"})
        repository.upsert_submission("run-1", values, duplicate_key_id="key", replaceable_statuses=replaceable)

        for approved in (None, "some-other-run"):
            with self.assertRaisesRegex(DuplicateSubmissionError, "already processed"):
                repository.upsert_submission(
                    "run-2",
                    values,
                    duplicate_key_id="key",
                    replace_run_id=approved,
                    replaceable_statuses=replaceable,
                )

        self.assertEqual(client.data[("submission_keys", "key")]["run_id"], "run-1")
        self.assertEqual(client.data[("madc_submissions", "run-1")]["submission_status"], "awaiting_decision")

    @patch("hapapp_python.database.firestore.transactional", side_effect=synchronous_transaction)
    def test_shared_run_is_not_superseded(self, _transactional) -> None:
        client = FakeClient()
        repository = FirestoreRepository(client)
        values = {"madc_filename": "report.csv", "inferred_project_id": "DAI-1"}
        replaceable = frozenset({"awaiting_decision", "declined", "superseded"})
        repository.upsert_submission("run-1", values, duplicate_key_id="key", replaceable_statuses=replaceable)
        client.data[("madc_submissions", "run-1")]["submission_status"] = "submitted_for_review"

        with self.assertRaisesRegex(DuplicateSubmissionError, "already processed"):
            repository.upsert_submission(
                "run-2", values, duplicate_key_id="key", replace_run_id="run-1", replaceable_statuses=replaceable
            )

        self.assertEqual(client.data[("submission_keys", "key")]["run_id"], "run-1")
        self.assertEqual(client.data[("madc_submissions", "run-1")]["submission_status"], "submitted_for_review")
        self.assertNotIn(("madc_submissions", "run-2"), client.data)

    @patch("hapapp_python.database.firestore.transactional", side_effect=synchronous_transaction)
    def test_updating_replaced_run_does_not_reclaim_key(self, _transactional) -> None:
        client = FakeClient()
        repository = FirestoreRepository(client)
        values = {"madc_filename": "report.csv", "inferred_project_id": "DAI-1"}
        replaceable = frozenset({"awaiting_decision", "declined", "superseded"})
        repository.upsert_submission("run-1", values, duplicate_key_id="key", replaceable_statuses=replaceable)
        repository.upsert_submission(
            "run-2", values, duplicate_key_id="key", replace_run_id="run-1", replaceable_statuses=replaceable
        )

        with self.assertRaisesRegex(DuplicateSubmissionError, "already processed"):
            repository.upsert_submission(
                "run-1", values, duplicate_key_id="key", replace_run_id="run-2", replaceable_statuses=replaceable
            )

        self.assertEqual(client.data[("submission_keys", "key")]["run_id"], "run-2")
        self.assertEqual(client.data[("madc_submissions", "run-2")]["submission_status"], "awaiting_decision")

    @patch("hapapp_python.database.firestore.transactional", side_effect=synchronous_transaction)
    def test_publication_claim_conditions_are_atomic(self, _transactional) -> None:
        client = FakeClient()
        client.data[("madc_submissions", "run")] = {
            "submitter_orcid_id": "owner",
            "submission_status": "awaiting_decision",
            "freshness_status": "current",
        }
        repository = FirestoreRepository(client)

        updated = repository.update_submission(
            "run",
            {"submission_status": "publishing"},
            submitter_orcid_id="owner",
            expected_submission_status="awaiting_decision",
            require_not_stale=True,
        )
        duplicate = repository.update_submission(
            "run",
            {"submission_status": "publishing"},
            submitter_orcid_id="owner",
            expected_submission_status="awaiting_decision",
            require_not_stale=True,
        )

        self.assertEqual(updated, 1)
        self.assertEqual(duplicate, 0)


if __name__ == "__main__":
    unittest.main()
