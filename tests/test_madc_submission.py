from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from hapapp_python.madc_submission import (
    MADC_SUBMISSION_METADATA_FILENAME,
    assert_submission_store_ready,
    build_madc_submission_metadata,
    claim_submission_for_publication,
    find_duplicate_madc_submission,
    get_submission_state,
    infer_genotyping_project_id,
    list_stranded_publishing_submissions,
    mark_stranded_publication_stale,
    persist_github_incorporation,
    persist_submission_archive_status,
    persist_submission_metadata,
    persist_submission_decision,
    persist_submission_result_provenance,
    persist_submission_review_state,
    release_submission_publication_claim,
    write_submission_metadata,
)


class MADCSubmissionTests(unittest.TestCase):
    def test_finds_duplicate_by_filename_and_project_id(self) -> None:
        db = Mock()
        db.find_duplicate_submission.return_value = {
            "run_id": "prior-run",
            "madc_filename": "DAl26-11931_MADC.csv",
            "inferred_project_id": "DAl26-11931",
            "submission_status": "submitted_for_review",
        }

        duplicate = find_duplicate_madc_submission("DAl26-11931_MADC.csv", "DAl26-11931", db)

        self.assertEqual(duplicate["run_id"], "prior-run")
        duplicate_key = db.find_duplicate_submission.call_args.args[0]
        self.assertEqual(len(duplicate_key), 64)

    def test_duplicate_check_requires_both_tracking_values(self) -> None:
        db = Mock()

        self.assertIsNone(find_duplicate_madc_submission("DAl26-11931_MADC.csv", "", db))
        db.find_duplicate_submission.assert_not_called()

    def test_infers_dai_project_id_from_filename(self) -> None:
        self.assertEqual(infer_genotyping_project_id("alfalfa_DAI123456_report.csv"), "DAI-123456")
        self.assertEqual(infer_genotyping_project_id("alfalfa_DAI-123456_report.csv"), "DAI-123456")
        self.assertEqual(
            infer_genotyping_project_id("DAl22-7011_MADC_Report_merged_rename_updatedSeq_Hea.csv"),
            "DAl22-7011",
        )
        self.assertEqual(
            infer_genotyping_project_id("DAl25-10253_MADC_snpID_rename(1).csv"),
            "DAl25-10253",
        )
        self.assertEqual(
            infer_genotyping_project_id("DAl26-11931_MADC_snpID_rename_v1.csv"),
            "DAl26-11931",
        )
        self.assertEqual(
            infer_genotyping_project_id("DWh26-11931_MADC_snpID_rename_v1.csv"),
            "DWh26-11931",
        )
        self.assertEqual(infer_genotyping_project_id("DW26-11931_MADC.csv"), "DW26-11931")
        self.assertEqual(infer_genotyping_project_id("DWht26-11931_MADC.csv"), "DWht26-11931")
        self.assertEqual(
            infer_genotyping_project_id("DAl22_7011_MADC_Report_merged.csv"),
            "DAl22-7011",
        )
        self.assertEqual(
            infer_genotyping_project_id("DAl21-5779_DAl21-6024_madc_all4plates_rename_54bp_uniq_f.csv"),
            "DAl21-5779_DAl21-6024",
        )
        self.assertEqual(
            infer_genotyping_project_id("DAl21-5779_DAl21_5779_madc.csv"),
            "DAl21-5779",
        )
        self.assertEqual(infer_genotyping_project_id("alfalfa_123456_report.csv"), "123456")
        self.assertIsNone(infer_genotyping_project_id("alfalfa_report.csv"))

    def test_builds_and_writes_submission_metadata(self) -> None:
        metadata = build_madc_submission_metadata(
            run_id="run",
            current_user={"orcid_id": "0000-0001-2345-6789", "user_name": "Jane Doe", "user_role": "user"},
            submitter_profile={"display_name": "Dr. Jane Doe", "public_email": "jane@example.org"},
            submitted_for_name="PI Name",
            submitted_for_location="Ithaca, NY",
            submitted_for_email="pi@example.org",
            submitted_for_institution="Example Lab",
            informal_project_name="Spring trial",
            inferred_project_id="DAI-123456",
            madc_filename="madc.csv",
            panel_id="alfalfa",
            panel_label="Alfalfa",
            input_github_repository="https://github.com/example/alfalfa-panel",
            input_github_ref="main",
            input_github_commit_sha="abc123",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            relative = write_submission_metadata(Path(tmp_dir), metadata)
            payload = json.loads((Path(tmp_dir) / relative).read_text(encoding="utf-8"))

        self.assertEqual(relative, MADC_SUBMISSION_METADATA_FILENAME)
        self.assertEqual(payload["submitter_orcid_id"], "0000-0001-2345-6789")
        self.assertEqual(payload["submitter_display_name"], "Dr. Jane Doe")
        self.assertEqual(payload["submitted_for_name"], "PI Name")
        self.assertEqual(payload["informal_project_name"], "Spring trial")
        self.assertEqual(payload["input_github_repository"], "https://github.com/example/alfalfa-panel")
        self.assertEqual(payload["input_github_ref"], "main")
        self.assertEqual(payload["input_github_commit_sha"], "abc123")
        self.assertNotIn("submitter_profile", payload)

    def test_persists_submission_decision_by_run_id(self) -> None:
        db = Mock()
        db.update_submission.return_value = 1
        updated_rows = persist_submission_decision("run", "0000-0001-2345-6789", "submitted_for_review", db)

        args, kwargs = db.update_submission.call_args
        self.assertEqual(args[0], "run")
        self.assertEqual(args[1]["submission_status"], "submitted_for_review")
        self.assertEqual(kwargs["submitter_orcid_id"], "0000-0001-2345-6789")
        self.assertEqual(kwargs["expected_submission_status"], "awaiting_decision")
        self.assertEqual(updated_rows, 1)

    def test_persists_submission_metadata_in_firestore(self) -> None:
        metadata = build_madc_submission_metadata(
            run_id="run",
            current_user={"orcid_id": "0000-0001-2345-6789"},
            submitter_profile=None,
            submitted_for_name=None,
            submitted_for_location=None,
            submitted_for_email=None,
            submitted_for_institution=None,
            informal_project_name=None,
            inferred_project_id=None,
            madc_filename="madc.csv",
            panel_id="alfalfa",
            panel_label="Alfalfa",
        )
        db = Mock()

        persist_submission_metadata(metadata, db)

        args, kwargs = db.upsert_submission.call_args
        self.assertEqual(args[0], "run")
        self.assertEqual(args[1]["madc_filename"], "madc.csv")
        self.assertEqual(args[1]["metadata_created_at"], metadata.created_at)
        self.assertIsNone(kwargs["duplicate_key_id"])

    def test_rejects_invalid_submission_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid MADC submission decision"):
            persist_submission_decision("run", "0000-0001-2345-6789", "accepted")

    def test_requires_submitter_orcid_for_submission_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "submitter ORCID"):
            persist_submission_decision("run", "", "submitted_for_review")

    def test_atomically_claims_an_awaiting_non_stale_submission_for_publication(self) -> None:
        db = Mock()
        db.update_submission.return_value = 1

        updated_rows = claim_submission_for_publication("run", "owner", db)

        args, kwargs = db.update_submission.call_args
        self.assertEqual(args[1]["submission_status"], "publishing")
        self.assertEqual(kwargs["submitter_orcid_id"], "owner")
        self.assertEqual(kwargs["expected_submission_status"], "awaiting_decision")
        self.assertTrue(kwargs["require_not_stale"])
        self.assertEqual(updated_rows, 1)

    def test_releases_a_failed_publication_claim_for_retry(self) -> None:
        db = Mock()

        release_submission_publication_claim("run", "owner", "GitHub unavailable", db)

        args, kwargs = db.update_submission.call_args
        self.assertEqual(args[1]["submission_status"], "awaiting_decision")
        self.assertEqual(args[1]["review_feedback"], "GitHub unavailable")
        self.assertNotIn("freshness_status", args[1])
        self.assertEqual(kwargs["expected_submission_status"], "publishing")

    def test_releases_a_stale_publication_claim_as_non_retryable(self) -> None:
        db = Mock()

        release_submission_publication_claim(
            "run",
            "owner",
            "Rerun against the latest database",
            db,
            freshness_status="stale",
        )

        updates = db.update_submission.call_args.args[1]
        self.assertEqual(updates["freshness_status"], "stale")
        self.assertEqual(updates["review_feedback"], "Rerun against the latest database")

    def test_lists_only_expired_publishing_claims(self) -> None:
        db = Mock()
        db.list_submissions_by_status.return_value = [
            {
                "run_id": "run",
                "submitter_orcid_id": "owner",
                "input_github_repository": "https://github.com/example/species",
                "input_github_ref": "main",
                "input_github_commit_sha": "base",
                "updated_at": "2000-01-01T00:00:00Z",
            }
        ]

        claims = list_stranded_publishing_submissions(3600, db)

        self.assertEqual(claims[0].run_id, "run")
        db.list_submissions_by_status.assert_called_once_with("publishing", limit=100)

    def test_marks_only_a_still_publishing_claim_stale(self) -> None:
        db = Mock()
        db.update_submission.return_value = 1

        updated = mark_stranded_publication_stale("run", "owner", "branch advanced", db)

        self.assertEqual(updated, 1)
        args, kwargs = db.update_submission.call_args
        self.assertEqual(args[1]["submission_status"], "changes_requested")
        self.assertEqual(args[1]["freshness_status"], "stale")
        self.assertEqual(kwargs["expected_submission_status"], "publishing")

    def test_firestore_preflight_accepts_an_accessible_database(self) -> None:
        db = Mock(unsafe=True)
        assert_submission_store_ready(db)
        db.assert_ready.assert_called_once_with()

    def test_firestore_preflight_explains_access_failures(self) -> None:
        db = Mock(unsafe=True)
        db.assert_ready.side_effect = RuntimeError("permission denied")

        with self.assertRaisesRegex(RuntimeError, "roles/datastore.user"):
            assert_submission_store_ready(db)

    def test_reads_submission_review_state(self) -> None:
        db = Mock()
        db.get_submission.return_value = {
            "run_id": "run",
            "submitter_orcid_id": "0000-0001-2345-6789",
            "submission_status": "changes_requested",
            "freshness_status": "stale",
            "review_feedback": "Rerun against the latest database.",
            "pull_request_url": "https://github.com/example/repo/pull/1",
            "incorporation_commit_url": None,
            "archive_status": "archived",
            "archive_error": None,
        }

        state = get_submission_state("run", "0000-0001-2345-6789", db)

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.submission_status, "changes_requested")
        self.assertEqual(state.freshness_status, "stale")
        self.assertEqual(state.review_feedback, "Rerun against the latest database.")

    def test_persists_result_provenance(self) -> None:
        db = Mock()

        persist_submission_result_provenance(
            "run",
            "0000-0001-2345-6789",
            input_database_version="v010",
            proposed_database_version="v011",
            output_checksums_json='{"result.fa": "abc"}',
            db=db,
        )

        updates = db.update_submission.call_args.args[1]
        self.assertEqual(updates["output_checksums_json"], '{"result.fa": "abc"}')

    def test_persists_archive_status(self) -> None:
        db = Mock()

        persist_submission_archive_status("run", "0000-0001-2345-6789", "failed", "upload failed", db)

        args, kwargs = db.update_submission.call_args
        self.assertEqual(args[1]["archive_status"], "failed")
        self.assertEqual(args[1]["archive_error"], "upload failed")
        self.assertEqual(kwargs["submitter_orcid_id"], "0000-0001-2345-6789")

    def test_persists_review_feedback_and_freshness(self) -> None:
        db = Mock()

        persist_submission_review_state(
            "run",
            status="changes_requested",
            freshness_status="stale",
            review_feedback="Rerun against the latest database.",
            reviewer_orcid_id="0000-0002-3456-7890",
            pull_request_url="https://github.com/example/repo/pull/1",
            db=db,
        )

        updates = db.update_submission.call_args.args[1]
        self.assertEqual(updates["submission_status"], "changes_requested")
        self.assertEqual(updates["freshness_status"], "stale")
        self.assertEqual(updates["review_feedback"], "Rerun against the latest database.")

    def test_finalizes_github_incorporation_without_nullable_parameters(self) -> None:
        db = Mock()
        db.update_submission.return_value = 1

        updated_rows = persist_github_incorporation(
            "run",
            "0000-0001-2345-6789",
            "https://github.com/example/repo/commit/abc",
            db,
        )

        self.assertEqual(updated_rows, 1)
        args, kwargs = db.update_submission.call_args
        self.assertEqual(args[1]["submission_status"], "incorporated")
        self.assertEqual(args[1]["incorporation_commit_url"], "https://github.com/example/repo/commit/abc")
        self.assertEqual(kwargs["submitter_orcid_id"], "0000-0001-2345-6789")
        self.assertEqual(kwargs["expected_submission_status"], "publishing")


if __name__ == "__main__":
    unittest.main()
