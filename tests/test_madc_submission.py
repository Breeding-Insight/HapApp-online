from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from hapapp_python.madc_submission import (
    MADC_SUBMISSION_METADATA_FILENAME,
    assert_submission_publication_schema_ready,
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
        db.execute_query.return_value = [
            {
                "run_id": "prior-run",
                "madc_filename": "DAl26-11931_MADC.csv",
                "inferred_project_id": "DAl26-11931",
                "submission_status": "submitted_for_review",
            }
        ]

        duplicate = find_duplicate_madc_submission("DAl26-11931_MADC.csv", "DAl26-11931", db)

        self.assertEqual(duplicate["run_id"], "prior-run")
        sql, parameters = db.execute_query.call_args.args
        self.assertIn("madc_filename", sql)
        self.assertIn("inferred_project_id", sql)
        self.assertEqual(parameters, ("DAl26-11931_MADC.csv", "DAl26-11931"))

    def test_duplicate_check_requires_both_tracking_values(self) -> None:
        db = Mock()

        self.assertIsNone(find_duplicate_madc_submission("DAl26-11931_MADC.csv", "", db))
        db.execute_query.assert_not_called()

    def test_infers_dai_project_id_from_filename(self) -> None:
        self.assertEqual(infer_genotyping_project_id("alfalfa_DAI123456_report.csv"), "DAI-123456")
        self.assertEqual(infer_genotyping_project_id("alfalfa_DAI-123456_report.csv"), "DAI-123456")
        self.assertEqual(
            infer_genotyping_project_id("DAl22-7011_MADC_Report_merged_rename_updatedSeq_Hea.csv"),
            "DAl22-7011",
        )
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
        db.execute_update.return_value = 1
        updated_rows = persist_submission_decision("run", "0000-0001-2345-6789", "submitted_for_review", db)

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("UPDATE hapapp.madc_submissions", sql)
        self.assertIn(
            "WHERE run_id = ? AND submitter_orcid_id = ? AND submission_status = 'awaiting_decision'",
            sql,
        )
        self.assertEqual(parameters, ("submitted_for_review", "run", "0000-0001-2345-6789"))
        self.assertEqual(updated_rows, 1)

    def test_persists_submission_metadata_in_hapapp_schema(self) -> None:
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

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("sp_getapplock", sql)
        self.assertIn("MADC filename and formal project ID were already processed", sql)
        self.assertIn("MERGE hapapp.madc_submissions AS target", sql)
        self.assertEqual(parameters[0:2], ("madc.csv", ""))

    def test_rejects_invalid_submission_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid MADC submission decision"):
            persist_submission_decision("run", "0000-0001-2345-6789", "accepted")

    def test_requires_submitter_orcid_for_submission_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "submitter ORCID"):
            persist_submission_decision("run", "", "submitted_for_review")

    def test_atomically_claims_an_awaiting_non_stale_submission_for_publication(self) -> None:
        db = Mock()
        db.execute_update.return_value = 1

        updated_rows = claim_submission_for_publication("run", "owner", db)

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("submission_status = 'publishing'", sql)
        self.assertIn("submission_status = 'awaiting_decision'", sql)
        self.assertIn("freshness_status <> 'stale'", sql)
        self.assertEqual(parameters, ("run", "owner"))
        self.assertEqual(updated_rows, 1)

    def test_releases_a_failed_publication_claim_for_retry(self) -> None:
        db = Mock()

        release_submission_publication_claim("run", "owner", "GitHub unavailable", db)

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("submission_status = 'awaiting_decision'", sql)
        self.assertIn("submission_status = 'publishing'", sql)
        self.assertEqual(parameters, ("GitHub unavailable", None, "run", "owner"))

    def test_releases_a_stale_publication_claim_as_non_retryable(self) -> None:
        db = Mock()

        release_submission_publication_claim(
            "run",
            "owner",
            "Rerun against the latest database",
            db,
            freshness_status="stale",
        )

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("freshness_status = COALESCE(CAST(? AS NVARCHAR(32)), freshness_status)", sql)
        self.assertEqual(
            parameters,
            ("Rerun against the latest database", "stale", "run", "owner"),
        )

    def test_lists_only_expired_publishing_claims(self) -> None:
        db = Mock()
        db.execute_query.return_value = [
            {
                "run_id": "run",
                "submitter_orcid_id": "owner",
                "input_github_repository": "https://github.com/example/species",
                "input_github_ref": "main",
                "input_github_commit_sha": "base",
            }
        ]

        claims = list_stranded_publishing_submissions(3600, db)

        self.assertEqual(claims[0].run_id, "run")
        sql, parameters = db.execute_query.call_args.args
        self.assertIn("submission_status = 'publishing'", sql)
        self.assertIn("DATEADD", sql)
        self.assertEqual(parameters, (3600,))

    def test_marks_only_a_still_publishing_claim_stale(self) -> None:
        db = Mock()
        db.execute_update.return_value = 1

        updated = mark_stranded_publication_stale("run", "owner", "branch advanced", db)

        self.assertEqual(updated, 1)
        sql, parameters = db.execute_update.call_args.args
        self.assertIn("submission_status = 'changes_requested'", sql)
        self.assertIn("freshness_status = 'stale'", sql)
        self.assertIn("submission_status = 'publishing'", sql)
        self.assertEqual(parameters, ("branch advanced", "run", "owner"))

    def test_publication_schema_preflight_accepts_publishing_constraint(self) -> None:
        db = Mock()
        db.execute_query.return_value = [
            {
                "database_name": "HaploSearch",
                "users_object_id": 1,
                "profiles_object_id": 2,
                "submissions_object_id": 3,
                "status_constraint_definition": "([submission_status]='publishing')",
            }
        ]

        assert_submission_publication_schema_ready(db)

        sql = db.execute_query.call_args.args[0]
        self.assertIn("DB_NAME()", sql)
        self.assertIn("OBJECT_ID('dbo.users', 'U')", sql)
        self.assertIn("CK_hapapp_madc_submissions_status", sql)
        self.assertIn("OBJECT_ID('hapapp.madc_submissions')", sql)

    def test_publication_schema_preflight_rejects_old_constraint(self) -> None:
        db = Mock()
        db.execute_query.return_value = [
            {
                "database_name": "HaploSearch",
                "users_object_id": 1,
                "profiles_object_id": 2,
                "submissions_object_id": 3,
                "status_constraint_definition": "([submission_status]='awaiting_decision')",
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "Run `schema_hapapp.sql`"):
            assert_submission_publication_schema_ready(db)

    def test_publication_schema_preflight_rejects_wrong_database(self) -> None:
        db = Mock()
        db.execute_query.return_value = [
            {
                "database_name": "master",
                "users_object_id": 1,
                "profiles_object_id": 2,
                "submissions_object_id": 3,
                "status_constraint_definition": "([submission_status]='publishing')",
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "complete HaploSearch schema"):
            assert_submission_publication_schema_ready(db)

    def test_reads_submission_review_state(self) -> None:
        db = Mock()
        db.execute_query.return_value = [
            {
                "run_id": "run",
                "submission_status": "changes_requested",
                "freshness_status": "stale",
                "review_feedback": "Rerun against the latest database.",
                "pull_request_url": "https://github.com/example/repo/pull/1",
                "incorporation_commit_url": None,
                "archive_status": "archived",
                "archive_error": None,
            }
        ]

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

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("output_checksums_json", sql)
        self.assertEqual(parameters[:3], ("v010", "v011", '{"result.fa": "abc"}'))

    def test_persists_archive_status(self) -> None:
        db = Mock()

        persist_submission_archive_status("run", "0000-0001-2345-6789", "failed", "upload failed", db)

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("archive_status", sql)
        self.assertEqual(parameters, ("failed", "upload failed", "run", "0000-0001-2345-6789"))

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

        sql, parameters = db.execute_update.call_args.args
        self.assertIn("freshness_status", sql)
        self.assertIn("review_feedback", sql)
        self.assertIn("CAST(? AS NVARCHAR(MAX))", sql)
        self.assertEqual(parameters[0:3], ("changes_requested", "stale", "Rerun against the latest database."))

    def test_finalizes_github_incorporation_without_nullable_parameters(self) -> None:
        db = Mock()
        db.execute_update.return_value = 1

        updated_rows = persist_github_incorporation(
            "run",
            "0000-0001-2345-6789",
            "https://github.com/example/repo/commit/abc",
            db,
        )

        sql, parameters = db.execute_update.call_args.args
        self.assertEqual(updated_rows, 1)
        self.assertIn("submission_status = 'incorporated'", sql)
        self.assertIn("submission_status = 'publishing'", sql)
        self.assertNotIn(None, parameters)
        self.assertEqual(
            parameters,
            (
                "https://github.com/example/repo/commit/abc",
                "run",
                "0000-0001-2345-6789",
            ),
        )


if __name__ == "__main__":
    unittest.main()
