from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dash import no_update
from dash.exceptions import PreventUpdate

from hapapp_python.app import (
    MADC_LOG_FILENAME,
    MADC_RUN_METADATA_FILENAME,
    RUNS,
    RUNS_LOCK,
    RunState,
    create_app,
    _archive_run_results,
    _editable_submission_summary,
    _expected_new_madc_db_files,
    _fixed_madc_result_file,
    _identify_uploaded_madc_panel,
    _list_files,
    _madc_replace_run_details,
    _madc_verification_details,
    _madc_previous_db_version,
    _madc_result_summary,
    _madc_submission_confirmation_modal,
    _madc_submission_db_version,
    _panel_input_files,
    _record_submission_decision,
    _result_options,
    _submission_package_files,
    _selected_submission_summary,
    _save_submission_metadata_edits,
    _snapshot_for_owner,
    _split_madc_result_options,
    _status_text,
    _terminal_text,
    _sync_submission_state,
    _publish_run_to_github,
    _write_run_metadata_file,
    _write_run_log_file,
    _zip_selected,
)
from hapapp_python.github_panel_files import PanelFileResolutionError
from hapapp_python.github_submission import StaleGitHubBaseError
from hapapp_python.madc_submission import (
    MADC_SUBMISSION_METADATA_FILENAME,
    MADCSubmissionState,
    build_madc_submission_metadata,
    write_submission_metadata,
)
from hapapp_python.panels import ResolvedMADCPanel
from hapapp_python.panels import MADCPanel
from hapapp_python.madc_validation import MADCPanelIdentificationError, MADCValidationError


def _resolved_panel(work_dir: Path, allele_db_name: str = "alfalfa_allele_db_v010.fa") -> ResolvedMADCPanel:
    panel_dir = work_dir / "panel_files" / "alfalfa"
    return ResolvedMADCPanel(
        panel_id="alfalfa",
        label="Alfalfa",
        snpid_lut=panel_dir / "snpid_lut.csv",
        allele_db_base=panel_dir / allele_db_name,
        matchcnt_lut_base=panel_dir / "alfalfa_allele_db_v010_matchCnt_lut.txt",
        allele_db_indel=None,
        matchcnt_lut_indel=None,
        dup_tags=None,
        first_sample_col=17,
        design_len=54,
        seq_len=81,
        cov=90,
        iden=85,
        code_ver="v1",
    )


def _madc_for_marker(marker_id: str) -> str:
    metadata_columns = (
        "AlleleID",
        "CloneID",
        "AlleleSequence",
        "ClusterConsensusSequence",
        "CallRate",
        "OneRatioRef",
        "OneRatioSnp",
        "FreqHomRef",
        "FreqHomSnp",
        "FreqHets",
        "PICRef",
        "PICSnp",
        "AvgPIC",
        "AvgCountRef",
        "AvgCountSnp",
        "RatioAvgCountRefAvgCountSnp",
    )
    preamble = ",".join(["*", *(["*"] * 15), "sample-a", "sample-b"])
    header = ",".join([*metadata_columns, "sample-a", "sample-b"])
    ref = ",".join(
        [f"{marker_id}|Ref", marker_id, "ATCG", "ATCG", *["1"] * 12, "10", "12"]
    )
    alt = ",".join(
        [f"{marker_id}|Alt", marker_id, "ATCC", "ATCC", *["1"] * 12, "11", "13"]
    )
    return "\n".join([preamble, header, ref, alt])


def _madc_panel(panel_id: str, label: str, snpid_lut: Path | str) -> MADCPanel:
    return MADCPanel(
        panel_id=panel_id,
        label=label,
        snpid_lut=snpid_lut,
        allele_db_base=Path("/panel/allele_db.fa"),
        matchcnt_lut_base=Path("/panel/matchcnt_lut.txt"),
        allele_db_indel=None,
        matchcnt_lut_indel=None,
        dup_tags=None,
        first_sample_col=17,
        design_len=54,
        seq_len=81,
        cov=90,
        iden=85,
        code_ver="v1",
    )


class AppResultTests(unittest.TestCase):
    def tearDown(self) -> None:
        with RUNS_LOCK:
            RUNS.clear()

    def test_lists_new_panel_db_outputs_but_hides_original_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "work"
            panel = _resolved_panel(work_dir)
            files = [
                work_dir / "madc_report.csv",
                panel.snpid_lut,
                panel.allele_db_base,
                panel.matchcnt_lut_base,
                work_dir / "panel_files" / "alfalfa" / "alfalfa_allele_db_v011.fa",
                work_dir / "panel_files" / "alfalfa" / "alfalfa_allele_db_v011_matchCnt_lut.txt",
            ]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("demo", encoding="utf-8")

            input_files = {"madc_report.csv"} | _panel_input_files(panel, work_dir)
            listed = _list_files(work_dir, input_files)

        self.assertNotIn("madc_report.csv", listed)
        self.assertNotIn("panel_files/alfalfa/snpid_lut.csv", listed)
        self.assertNotIn("panel_files/alfalfa/alfalfa_allele_db_v010.fa", listed)
        self.assertNotIn("panel_files/alfalfa/alfalfa_allele_db_v010_matchCnt_lut.txt", listed)
        self.assertIn("panel_files/alfalfa/alfalfa_allele_db_v011.fa", listed)
        self.assertIn("panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt", listed)

    def test_expected_new_db_outputs_use_one_version_higher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "work"
            expected = _expected_new_madc_db_files(_resolved_panel(work_dir), work_dir)

        self.assertEqual(
            expected,
            {
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
            },
        )

    def test_expected_new_db_outputs_do_not_accept_fasta_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir) / "work"
            expected = _expected_new_madc_db_files(
                _resolved_panel(work_dir, allele_db_name="alfalfa_allele_db_v010.fasta"),
                work_dir,
            )

        self.assertEqual(expected, set())

    def test_uploaded_madc_panel_identification_reports_unavailable_panel_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            report = tmp_path / "DAl26-11931_MADC.csv"
            demo_lut = tmp_path / "demo_lut.csv"
            report.write_text(_madc_for_marker("alfalfa-marker"), encoding="utf-8")
            demo_lut.write_text("Panel_markerID\nchestnut-marker\n", encoding="utf-8")

            panels = {
                "demo": _madc_panel("demo", "Demo panel", demo_lut),
                "alfalfa": _madc_panel(
                    "alfalfa",
                    "Alfalfa 3k DArTag (v1.0)",
                    "https://github.com/example/alfalfa/blob/main/snpid_lut.csv",
                ),
            }

            def resolve_lut(panel: MADCPanel, work_dir: Path) -> Path:
                if panel.panel_id == "alfalfa":
                    raise PanelFileResolutionError("HAPAPP_GITHUB_TOKEN is not set")
                return Path(panel.snpid_lut)

            with (
                patch("hapapp_python.app.load_madc_panels", return_value=panels),
                patch("hapapp_python.app.resolve_madc_panel_lut", side_effect=resolve_lut),
                self.assertRaises(MADCPanelIdentificationError) as err,
            ):
                _identify_uploaded_madc_panel(report)

        message = str(err.exception)
        self.assertIn("does not match any available species panel", message)
        self.assertIn("Alfalfa 3k DArTag (v1.0)", message)
        self.assertIn("HAPAPP_GITHUB_TOKEN is not set", message)

    def test_reads_proposed_database_version_from_main_fasta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            database = work_dir / "panel_files/alfalfa/alfalfa_allele_db_v011.fa"
            database.parent.mkdir(parents=True)
            database.write_text(">allele\nACGT\n", encoding="utf-8")
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                main_result_files={
                    "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                    "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
                },
            )

            self.assertEqual(_madc_submission_db_version(state), "v011")

    def test_verification_details_offer_science_team_contact(self) -> None:
        details = str(_madc_verification_details(MADCValidationError(["Bad header"])))

        self.assertIn("If you can't resolve these errors, contact the Breeding Insight Science team", details)
        self.assertIn("mailto:bi-science-team@ufl.edu", details)

    def test_failed_run_terminal_text_includes_assistance_and_run_id(self) -> None:
        state = RunState(
            run_id="run-123",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            status="failed",
            error="Workflow exited with status 1",
        )

        text = _terminal_text(state)

        self.assertIn("Workflow exited with status 1", text)
        self.assertIn(
            "If you need assistance, contact the Breeding Insight Science team at bi-science-team@ufl.edu "
            "and include run ID run-123.",
            text,
        )

    def test_replace_run_details_show_owner_start_and_live_state(self) -> None:
        duplicate = {
            "run_id": "run-old",
            "submission_status": "awaiting_decision",
            "submitter_display_name": "Jane Doe",
            "submitter_orcid_id": "0000-0001-2345-6789",
            "metadata_created_at": "2026-09-25T10:42:00+00:00",
        }
        running = RunState(
            run_id="run-old",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            status="running",
        )
        with RUNS_LOCK:
            RUNS["run-old"] = running
        try:
            details = str(_madc_replace_run_details(duplicate))
        finally:
            with RUNS_LOCK:
                RUNS.pop("run-old", None)

        self.assertIn("Jane Doe (ORCID: 0000-0001-2345-6789)", details)
        self.assertIn("Sep 25, 2026 at 10:42 UTC", details)
        self.assertIn("Still processing", details)
        self.assertIn("run-old", details)

    def test_replace_run_details_use_stored_results_when_run_is_not_in_memory(self) -> None:
        finished = str(_madc_replace_run_details({"run_id": "gone", "output_checksums_json": "{}"}))
        unknown = str(_madc_replace_run_details({"run_id": "gone"}))
        declined = str(_madc_replace_run_details({"run_id": "gone", "submission_status": "declined"}))

        self.assertIn("Finished; results not yet shared with Breeding Insight", finished)
        self.assertIn("Processing, or stopped before it finished", unknown)
        self.assertIn("Declined by the person who ran it", declined)

    def test_superseded_run_hides_results_and_explains_why(self) -> None:
        state = RunState(
            run_id="run-old",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            status="completed",
            files=["report_fixed.csv"],
            submission_status="superseded",
        )

        self.assertEqual(_result_options(state), [])
        self.assertIn("replaced by a newer run of the same MADC file", _terminal_text(state))

    def test_submission_summary_hides_internal_status_and_freshness(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            submission_status="awaiting_decision",
            freshness_status="stale",
        )

        summary = str(_selected_submission_summary(state, []))

        self.assertNotIn("Submission status", summary)
        self.assertNotIn("Freshness", summary)
        self.assertNotIn("This run is stale", summary)

    def test_submission_summary_offers_editable_user_entered_metadata(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
        )

        summary = str(_editable_submission_summary(state, []))

        self.assertIn("madc-summary-formal-project-id", summary)
        self.assertIn("madc-summary-informal-project-name", summary)
        self.assertIn("madc-summary-submitted-for-name", summary)
        self.assertIn("madc-summary-submitted-for-institution", summary)
        self.assertIn("madc-summary-submitted-for-location", summary)
        self.assertIn("madc-summary-submitted-for-email", summary)
        self.assertNotIn("madc-summary-panel", summary)
        self.assertNotIn("madc-summary-submitter", summary)
        self.assertNotIn("Edit the submission metadata below", summary)

    def test_submission_metadata_edit_icon_follows_result_cards(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
        )

        summary = str(_selected_submission_summary(state, []))

        self.assertIn("aria-label='Edit metadata'", summary)
        self.assertIn("icon='mdi:pencil'", summary)
        self.assertLess(summary.index("results-summary"), summary.index("madc-submission-metadata-edit"))

    def test_dynamic_metadata_actions_ignore_synthetic_initial_calls(self) -> None:
        app = create_app()
        callbacks = {
            callback.__wrapped__.__name__: callback.__wrapped__
            for callback_data in app.callback_map.values()
            if (callback := callback_data.get("callback")) is not None and hasattr(callback, "__wrapped__")
        }

        with self.assertRaises(PreventUpdate):
            callbacks["edit_madc_submission_metadata"](None, None, [], [])
        with self.assertRaises(PreventUpdate):
            callbacks["cancel_madc_submission_metadata_edits"](None, None, [], [])
        with self.assertRaises(PreventUpdate):
            callbacks["save_madc_submission_metadata"](None, None, [], [], None, None, None, None, None, None)

    def test_confirmation_explains_sharing_and_review(self) -> None:
        modal = str(_madc_submission_confirmation_modal())

        self.assertIn("agree to share the processed MADC", modal)
        self.assertIn("Breeding Insight will review", modal)
        self.assertIn("Agree, Share, and Download", modal)

    def test_download_callback_waits_while_github_publication_is_in_flight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result_file = Path(tmp_dir) / "result.csv"
            result_file.write_text("result", encoding="utf-8")
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=Path(tmp_dir),
                input_files=set(),
                command=[],
                owner_orcid_id="owner",
                files=[result_file.name],
                log=["Number of NEW alleles found in this report: 1"],
                status="completed",
                submission_status="publishing",
            )
            with RUNS_LOCK:
                RUNS[state.run_id] = state

            app = create_app()
            callback = next(
                callback.__wrapped__
                for callback_data in app.callback_map.values()
                if (callback := callback_data.get("callback")) is not None
                and hasattr(callback, "__wrapped__")
                and callback.__wrapped__.__name__ == "submit_and_download_madc"
            )
            with (
                patch("hapapp_python.app.get_current_user", return_value={"orcid_id": "owner"}),
                patch("hapapp_python.app._sync_submission_state"),
                patch("hapapp_python.app._publish_run_to_github") as publish,
                patch("hapapp_python.app.dcc.send_bytes") as send_bytes,
            ):
                result = callback({"run_id": "run", "selected": [result_file.name]})

        self.assertIs(result, no_update)
        publish.assert_not_called()
        send_bytes.assert_not_called()

    def test_local_panel_uses_review_submission_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            result_file = work_dir / "result.csv"
            result_file.write_text("result", encoding="utf-8")
            metadata = build_madc_submission_metadata(
                run_id="run",
                current_user={"orcid_id": "owner"},
                submitter_profile=None,
                submitted_for_name="Owner",
                submitted_for_location="Location",
                submitted_for_email="owner@example.org",
                submitted_for_institution="Institution",
                informal_project_name=None,
                inferred_project_id="DAI-123456",
                madc_filename="madc.csv",
                panel_id="demo",
                panel_label="Demo",
            )
            write_submission_metadata(work_dir, metadata)
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                owner_orcid_id="owner",
                files=[result_file.name],
                log=["Number of NEW alleles found in this report: 1"],
                status="completed",
            )
            with RUNS_LOCK:
                RUNS[state.run_id] = state

            app = create_app()
            callback = next(
                callback.__wrapped__
                for callback_data in app.callback_map.values()
                if (callback := callback_data.get("callback")) is not None
                and hasattr(callback, "__wrapped__")
                and callback.__wrapped__.__name__ == "submit_and_download_madc"
            )
            with (
                patch("hapapp_python.app.get_current_user", return_value={"orcid_id": "owner"}),
                patch("hapapp_python.app._sync_submission_state"),
                patch("hapapp_python.app.get_madc_panel", return_value=object()),
                patch("hapapp_python.app.madc_panel_github_source", return_value=(None, None)),
                patch("hapapp_python.app._record_submission_decision", return_value=True) as record,
                patch("hapapp_python.app._publish_run_to_github") as publish,
                patch("hapapp_python.app._archive_run_results") as archive,
                patch("hapapp_python.app._zip_selected", return_value="zip-writer"),
                patch("hapapp_python.app.dcc.send_bytes", return_value="download") as send_bytes,
            ):
                result = callback({"run_id": "run", "selected": [result_file.name]})

        self.assertEqual(result, "download")
        record.assert_called_once_with("run", "owner", "submitted_for_review")
        publish.assert_not_called()
        archive.assert_called_once()
        send_bytes.assert_called_once()

    def test_zero_new_alleles_are_shared_without_github_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            fixed_madc = work_dir / "DAl26-11931_MADC_snpID_rename_v1.csv"
            fixed_madc.write_text("Code_version,AlleleID\nv1,marker|Ref_001\n", encoding="utf-8")
            metadata = build_madc_submission_metadata(
                run_id="run",
                current_user={"orcid_id": "owner"},
                submitter_profile=None,
                submitted_for_name="Owner",
                submitted_for_location="Location",
                submitted_for_email="owner@example.org",
                submitted_for_institution="Institution",
                informal_project_name=None,
                inferred_project_id="DAl26-11931",
                madc_filename="DAl26-11931_MADC.csv",
                panel_id="alfalfa",
                panel_label="Alfalfa",
                input_github_repository="https://github.com/example/alfalfa",
                input_github_ref="main",
                input_github_commit_sha="base-sha",
            )
            write_submission_metadata(work_dir, metadata)
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files={"panel_files/alfalfa/alfalfa_allele_db_v055.fa"},
                command=[],
                owner_orcid_id="owner",
                main_result_files={
                    "panel_files/alfalfa/alfalfa_allele_db_v056.fa",
                    "panel_files/alfalfa/alfalfa_allele_db_v056_matchCnt_lut.txt",
                },
                files=[fixed_madc.name, MADC_SUBMISSION_METADATA_FILENAME],
                fixed_madc_file=fixed_madc.name,
                log=["Number of NEW alleles found in this report: 0"],
                status="completed",
            )
            with RUNS_LOCK:
                RUNS[state.run_id] = state

            app = create_app()
            callback = next(
                callback.__wrapped__
                for callback_data in app.callback_map.values()
                if (callback := callback_data.get("callback")) is not None
                and hasattr(callback, "__wrapped__")
                and callback.__wrapped__.__name__ == "submit_and_download_madc"
            )
            with (
                patch("hapapp_python.app.get_current_user", return_value={"orcid_id": "owner"}),
                patch("hapapp_python.app._sync_submission_state"),
                patch("hapapp_python.app._record_submission_decision", return_value=True) as record,
                patch("hapapp_python.app._submission_uses_github_publication") as publication_mode,
                patch("hapapp_python.app._publish_run_to_github") as publish,
                patch("hapapp_python.app._archive_run_results") as archive,
                patch("hapapp_python.app._zip_selected", return_value="zip-writer"),
                patch("hapapp_python.app.dcc.send_bytes", return_value="download"),
            ):
                result = callback({"run_id": "run", "selected": [fixed_madc.name]})

        self.assertEqual(result, "download")
        record.assert_called_once_with("run", "owner", "submitted_for_review")
        publication_mode.assert_not_called()
        publish.assert_not_called()
        archive.assert_called_once()

    def test_zero_new_allele_package_excludes_missing_database_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            fixed_madc = work_dir / "DAl26-11931_MADC_snpID_rename_v1.csv"
            fixed_madc.write_text("Code_version,AlleleID\nv1,marker|Ref_001\n", encoding="utf-8")
            (work_dir / MADC_SUBMISSION_METADATA_FILENAME).write_text("{}\n", encoding="utf-8")
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files={"panel_files/alfalfa/alfalfa_allele_db_v055.fa"},
                command=[],
                main_result_files={
                    "panel_files/alfalfa/alfalfa_allele_db_v056.fa",
                    "panel_files/alfalfa/alfalfa_allele_db_v056_matchCnt_lut.txt",
                },
                files=[fixed_madc.name, MADC_SUBMISSION_METADATA_FILENAME],
                fixed_madc_file=fixed_madc.name,
                log=["Number of NEW alleles found in this report: 0"],
                status="completed",
            )

            package = _submission_package_files(state)
            summary = str(_selected_submission_summary(state, [fixed_madc.name]))

        self.assertEqual(package, [fixed_madc.name, MADC_SUBMISSION_METADATA_FILENAME])
        self.assertIsNone(_madc_submission_db_version(state))
        self.assertIn("No novel alleles were found", summary)
        self.assertIn("No GitHub commit", summary)
        self.assertIn("No change (v055)", summary)

    def test_stale_status_write_failure_releases_the_publication_claim(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
            log=["Number of NEW alleles found in this report: 1"],
            status="completed",
        )
        with RUNS_LOCK:
            RUNS[state.run_id] = state

        stale_error = StaleGitHubBaseError("expected-sha", "current-sha")
        with (
            patch("hapapp_python.app.claim_submission_for_publication", return_value=1),
            patch("hapapp_python.app._github_source_from_state", side_effect=stale_error),
            patch("hapapp_python.app.persist_submission_review_state", side_effect=RuntimeError("db unavailable")),
            patch("hapapp_python.app.release_submission_publication_claim", return_value=1) as release,
        ):
            self.assertFalse(_publish_run_to_github("run", "owner"))

        self.assertEqual(state.submission_status, "awaiting_decision")
        self.assertEqual(state.freshness_status, "stale")
        release.assert_called_once_with(
            "run",
            "owner",
            str(stale_error),
            freshness_status="stale",
        )

    def test_saves_summary_metadata_edits_to_file_and_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            metadata = build_madc_submission_metadata(
                run_id="run",
                current_user={"orcid_id": "owner", "user_name": "Submitter"},
                submitter_profile=None,
                submitted_for_name="Original Owner",
                submitted_for_location="Original Location",
                submitted_for_email="original@example.org",
                submitted_for_institution="Original Institution",
                informal_project_name=None,
                inferred_project_id="DAI-111111",
                madc_filename="madc.csv",
                panel_id="alfalfa",
                panel_label="Alfalfa",
            )
            write_submission_metadata(work_dir, metadata)
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                owner_orcid_id="owner",
                status="completed",
            )

            with patch("hapapp_python.app.persist_submission_metadata") as persist:
                _save_submission_metadata_edits(
                    state,
                    "owner",
                    inferred_project_id=" DAI-222222 ",
                    informal_project_name=" Spring trial ",
                    submitted_for_name=" Updated Owner ",
                    submitted_for_institution=" Updated Institution ",
                    submitted_for_location=" Ithaca, NY ",
                    submitted_for_email=" updated@example.org ",
                )

            payload = json.loads((work_dir / MADC_SUBMISSION_METADATA_FILENAME).read_text(encoding="utf-8"))

        self.assertEqual(payload["inferred_project_id"], "DAI-222222")
        self.assertEqual(payload["informal_project_name"], "Spring trial")
        self.assertEqual(payload["submitted_for_name"], "Updated Owner")
        self.assertEqual(payload["submitted_for_institution"], "Updated Institution")
        self.assertEqual(payload["submitted_for_location"], "Ithaca, NY")
        self.assertEqual(payload["submitted_for_email"], "updated@example.org")
        persist.assert_called_once()

    def test_summary_metadata_edits_require_all_required_fields(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
            status="completed",
        )

        with self.assertRaisesRegex(ValueError, "Formal project ID"):
            _save_submission_metadata_edits(
                state,
                "owner",
                inferred_project_id="",
                informal_project_name="Project",
                submitted_for_name="Owner",
                submitted_for_institution="Institution",
                submitted_for_location="Location",
                submitted_for_email="owner@example.org",
            )

    def test_reads_previous_database_version_from_panel_input(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files={
                "madc_report.csv",
                "panel_files/alfalfa/alfalfa_allele_db_v010.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v010_matchCnt_lut.txt",
            },
            command=[],
        )

        self.assertEqual(_madc_previous_db_version(state), "v010")

    def test_nested_expected_db_outputs_are_main_files(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            main_result_files={
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
            },
            files=[
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
                "panel_files/alfalfa/alfalfa_allele_db_v011.fasta",
                "panel_files/alfalfa/alfalfa_allele_db_v011.nhr",
            ],
            status="completed",
        )

        main_options, diagnostic_options = _split_madc_result_options(state)

        self.assertEqual(
            [option["value"] for option in main_options],
            [
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
                "panel_files/alfalfa/alfalfa_allele_db_v011_matchCnt_lut.txt",
            ],
        )
        self.assertEqual(
            [option["value"] for option in diagnostic_options],
            [
                "panel_files/alfalfa/alfalfa_allele_db_v011.fasta",
                "panel_files/alfalfa/alfalfa_allele_db_v011.nhr",
            ],
        )

    def test_finds_final_fixed_madc_file_for_review_archive(self) -> None:
        fixed_file = _fixed_madc_result_file(
            [
                "sample_snpID_rename.csv",
                "sample_snpID_rename_v1.csv",
                "sample_snpID_rename_updatedSeq.csv",
                "sample_snpID_rename_updatedSeq_v1.csv",
                "panel_files/alfalfa/alfalfa_allele_db_v011.fa",
            ]
        )

        self.assertEqual(fixed_file, "sample_snpID_rename_updatedSeq_v1.csv")

    def test_writes_run_log_file_for_review_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                log=["one", "two"],
            )

            relative_log = _write_run_log_file(state)

            self.assertEqual(relative_log, MADC_LOG_FILENAME)
            self.assertEqual((work_dir / MADC_LOG_FILENAME).read_text(encoding="utf-8"), "one\ntwo\n")

    def test_writes_completed_run_metadata_for_review_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            fixed_madc = work_dir / "sample_snpID_rename_v1.csv"
            fixed_madc.write_text(
                "AlleleID,CloneID,AlleleSequence,accession-a\n"
                "marker|Ref_0001,marker,ACGT,1\n",
                encoding="utf-8",
            )
            (work_dir / MADC_SUBMISSION_METADATA_FILENAME).write_text(
                '{"panel_label": "Alfalfa", "submitted_for_name": "Project Owner"}',
                encoding="utf-8",
            )
            database = work_dir / "panel_files/alfalfa/alfalfa_allele_db_v011.fa"
            database.parent.mkdir(parents=True)
            database.write_text(">allele\nACGT\n", encoding="utf-8")
            state = RunState(
                run_id="run-123",
                kind="MADC hap assignment",
                work_dir=work_dir,
                input_files={"panel_files/alfalfa/alfalfa_allele_db_v010.fa"},
                command=[],
                main_result_files={"panel_files/alfalfa/alfalfa_allele_db_v011.fa"},
                files=[fixed_madc.name, "diagnostic.txt"],
                fixed_madc_file=fixed_madc.name,
                log=["Number of NEW alleles found in this report: 2"],
                status="completed",
                returncode=0,
                submission_status="submitted_for_review",
            )

            relative_metadata = _write_run_metadata_file(state, [fixed_madc.name, "not-a-result.txt"])
            payload = json.loads((work_dir / relative_metadata).read_text(encoding="utf-8"))

        self.assertEqual(relative_metadata, MADC_RUN_METADATA_FILENAME)
        self.assertEqual(payload["run_id"], "run-123")
        self.assertEqual(payload["panel_label"], "Alfalfa")
        self.assertEqual(payload["submitted_for_name"], "Project Owner")
        self.assertEqual(payload["submission_status"], "submitted_for_review")
        self.assertNotIn("workflow_kind", payload)
        self.assertNotIn("returncode", payload)
        self.assertNotIn("error", payload)
        self.assertEqual(payload["previous_haplotype_database_version"], "v010")
        self.assertEqual(payload["proposed_haplotype_database_version"], "v011")
        self.assertEqual(payload["accessions_recognized"], 1)
        self.assertEqual(payload["new_alleles_found"], 2)
        self.assertEqual(payload["selected_download_files"], [fixed_madc.name])
        self.assertIn(MADC_SUBMISSION_METADATA_FILENAME, payload["submission_package_files"])

    def test_successful_dropbox_archive_is_not_added_to_user_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=Path(tmp_dir),
                input_files=set(),
                command=[],
                owner_orcid_id="owner",
                log=["workflow complete"],
                status="completed",
            )
            with RUNS_LOCK:
                RUNS[state.run_id] = state

            with patch(
                "hapapp_python.app.archive_madc_review_artifacts",
                return_value=["Archived fixed MADC to Dropbox: /review/result.csv"],
            ):
                _archive_run_results("run", "owner", include_fixed_madc=True, include_log=True)

            self.assertEqual(RUNS["run"].log, ["workflow complete"])

    def test_dropbox_archive_failure_is_added_to_user_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=Path(tmp_dir),
                input_files=set(),
                command=[],
                owner_orcid_id="owner",
                log=["workflow complete"],
                status="completed",
            )
            with RUNS_LOCK:
                RUNS[state.run_id] = state

            with patch(
                "hapapp_python.app.archive_madc_review_artifacts",
                side_effect=RuntimeError("upload unavailable"),
            ):
                _archive_run_results("run", "owner", include_fixed_madc=True, include_log=True)

            self.assertEqual(
                RUNS["run"].log,
                ["workflow complete", "Dropbox archive failed: upload unavailable"],
            )

    def test_summarizes_accessions_and_new_alleles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            fixed_madc = work_dir / "sample_snpID_rename_v1.csv"
            fixed_madc.write_text(
                "Code_version,AlleleID,CloneID,AlleleSequence,accession-a,accession-b\n"
                "v1,marker|Ref_0001,marker,ACGT,1,2\n",
                encoding="utf-8",
            )
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                fixed_madc_file=fixed_madc.name,
                log=["    - Number of NEW alleles found in this report: 7"],
                status="completed",
            )

            summary = _madc_result_summary(state)

        self.assertEqual(summary, (2, 7))

    def test_summary_values_are_unavailable_without_completed_result_data(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
        )

        self.assertEqual(_madc_result_summary(state), (None, None))

    def test_summarizes_accessions_from_unversioned_processed_madc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            processed_madc = work_dir / "sample_snpID_rename.csv"
            processed_madc.write_text(
                "AlleleID,CloneID,AlleleSequence,accession-a\n"
                "marker|Ref_0001,marker,ACGT,1\n",
                encoding="utf-8",
            )
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                files=[processed_madc.name],
                log=["    - Number of NEW alleles found in this report: 0"],
                status="completed",
            )

            summary = _madc_result_summary(state)

        self.assertEqual(summary, (1, 0))

    def test_submission_decision_is_recorded_only_once(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
            status="completed",
        )
        with RUNS_LOCK:
            RUNS[state.run_id] = state

        with patch("hapapp_python.app.persist_submission_decision", return_value=1) as persist:
            self.assertTrue(_record_submission_decision("run", "owner", "declined"))
            self.assertFalse(_record_submission_decision("run", "owner", "submitted_for_review"))

        self.assertEqual(state.submission_status, "declined")
        persist.assert_called_once_with("run", "owner", "declined")

    def test_submission_decision_remains_pending_when_database_write_fails(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
            status="completed",
        )
        with RUNS_LOCK:
            RUNS[state.run_id] = state

        with patch("hapapp_python.app.persist_submission_decision", return_value=0):
            self.assertFalse(_record_submission_decision("run", "owner", "submitted_for_review"))

        self.assertEqual(state.submission_status, "awaiting_decision")

    def test_stale_run_cannot_be_submitted_for_review(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
            status="completed",
            freshness_status="stale",
        )
        with RUNS_LOCK:
            RUNS[state.run_id] = state

        with patch("hapapp_python.app.persist_submission_decision") as persist:
            self.assertFalse(_record_submission_decision("run", "owner", "submitted_for_review"))

        persist.assert_not_called()
        self.assertEqual(state.submission_status, "awaiting_decision")

    def test_syncs_review_feedback_and_freshness_from_database(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
            status="completed",
        )
        with RUNS_LOCK:
            RUNS[state.run_id] = state

        submission = MADCSubmissionState(
            run_id="run",
            submission_status="changes_requested",
            freshness_status="stale",
            review_feedback="Rerun against the latest database.",
            pull_request_url="https://github.com/example/repo/pull/1",
            incorporation_commit_url=None,
            archive_status="archived",
            archive_error=None,
        )
        with patch("hapapp_python.app.get_submission_state", return_value=submission):
            _sync_submission_state("run", "owner")

        snapshot = _snapshot_for_owner("run", "owner")
        assert snapshot is not None
        self.assertEqual(snapshot.submission_status, "changes_requested")
        self.assertEqual(snapshot.freshness_status, "stale")
        self.assertEqual(snapshot.review_feedback, "Rerun against the latest database.")
        self.assertIn("Changes requested", _status_text(snapshot))
        self.assertIn("Stale", _status_text(snapshot))

    def test_run_snapshot_is_available_only_to_owner(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
        )
        with RUNS_LOCK:
            RUNS[state.run_id] = state

        self.assertIsNotNone(_snapshot_for_owner("run", "owner"))
        self.assertIsNone(_snapshot_for_owner("run", "other-user"))

    def test_another_user_cannot_record_submission_decision(self) -> None:
        state = RunState(
            run_id="run",
            kind="MADC",
            work_dir=Path("/work"),
            input_files=set(),
            command=[],
            owner_orcid_id="owner",
            status="completed",
        )
        with RUNS_LOCK:
            RUNS[state.run_id] = state

        with patch("hapapp_python.app.persist_submission_decision") as persist:
            self.assertFalse(_record_submission_decision("run", "other-user", "declined"))

        self.assertEqual(state.submission_status, "awaiting_decision")
        persist.assert_not_called()

    def test_declined_run_cannot_list_or_download_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            result = work_dir / "result.csv"
            result.write_text("result", encoding="utf-8")
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                owner_orcid_id="owner",
                files=[result.name],
                status="completed",
                submission_status="declined",
            )
            with RUNS_LOCK:
                RUNS[state.run_id] = state

            self.assertEqual(_result_options(state), [])
            with self.assertRaisesRegex(ValueError, "declined"):
                _zip_selected("run", "owner", [result.name])

    def test_run_results_cannot_be_downloaded_by_another_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            result = work_dir / "result.csv"
            result.write_text("result", encoding="utf-8")
            state = RunState(
                run_id="run",
                kind="MADC",
                work_dir=work_dir,
                input_files=set(),
                command=[],
                owner_orcid_id="owner",
                files=[result.name],
                status="completed",
            )
            with RUNS_LOCK:
                RUNS[state.run_id] = state

            with self.assertRaisesRegex(ValueError, "No run"):
                _zip_selected("run", "other-user", [result.name])


if __name__ == "__main__":
    unittest.main()
