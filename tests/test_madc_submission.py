from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from hapapp_python.madc_submission import (
    MADC_SUBMISSION_METADATA_FILENAME,
    build_madc_submission_metadata,
    get_submission_state,
    infer_genotyping_project_id,
    persist_submission_archive_status,
    persist_submission_metadata,
    persist_submission_decision,
    persist_submission_result_provenance,
    persist_submission_review_state,
    write_submission_metadata,
)


class MADCSubmissionTests(unittest.TestCase):
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

        sql = db.execute_update.call_args.args[0]
        self.assertIn("MERGE hapapp.madc_submissions AS target", sql)

    def test_rejects_invalid_submission_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid MADC submission decision"):
            persist_submission_decision("run", "0000-0001-2345-6789", "accepted")

    def test_requires_submitter_orcid_for_submission_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "submitter ORCID"):
            persist_submission_decision("run", "", "submitted_for_review")

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
        self.assertEqual(parameters[0:3], ("changes_requested", "stale", "Rerun against the latest database."))


if __name__ == "__main__":
    unittest.main()
