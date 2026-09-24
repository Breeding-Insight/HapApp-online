from __future__ import annotations

import unittest
from unittest.mock import Mock

from hapapp_python.github_recovery import recover_stranded_github_publications
from hapapp_python.github_submission import GitHubBranchCommit, GitHubPublicationError, GitHubRepository


class RecoveryGitHubClient:
    def __init__(self, *, head: str = "base", commits: list[GitHubBranchCommit] | None = None) -> None:
        self.head = head
        self.commits = commits or []
        self.history_reads = 0
        self.error: Exception | None = None

    def branch_head(self, repository: GitHubRepository) -> str:
        return self.head

    def branch_commits(self, repository: GitHubRepository, limit: int) -> list[GitHubBranchCommit]:
        self.history_reads += 1
        if self.error is not None:
            raise self.error
        return self.commits[:limit]


def publishing_row(**overrides):
    row = {
        "run_id": "run",
        "submitter_orcid_id": "owner",
        "input_github_repository": "https://github.com/example/species",
        "input_github_ref": "main",
        "input_github_commit_sha": "base",
        "updated_at": "2000-01-01T00:00:00Z",
    }
    row.update(overrides)
    return row


class GitHubRecoveryTests(unittest.TestCase):
    def test_finalizes_a_commit_that_github_already_accepted(self) -> None:
        db = Mock()
        db.list_submissions_by_status.return_value = [publishing_row()]
        db.update_submission.return_value = 1
        client = RecoveryGitHubClient(
            head="published",
            commits=[GitHubBranchCommit("published", "Contribution\n\nHapApp-Run-ID: run")],
        )

        report = recover_stranded_github_publications(3600, db=db, client=client)

        self.assertEqual(report.incorporated, 1)
        self.assertEqual(report.released, 0)
        updates = db.update_submission.call_args.args[1]
        self.assertEqual(updates["submission_status"], "incorporated")
        self.assertEqual(updates["incorporation_commit_url"], "https://github.com/example/species/commit/published")

    def test_releases_a_claim_when_the_branch_never_changed(self) -> None:
        db = Mock()
        db.list_submissions_by_status.return_value = [publishing_row()]
        db.update_submission.return_value = 1

        report = recover_stranded_github_publications(
            3600,
            db=db,
            client=RecoveryGitHubClient(head="base"),
        )

        self.assertEqual(report.released, 1)
        args, kwargs = db.update_submission.call_args
        self.assertEqual(args[1]["submission_status"], "awaiting_decision")
        self.assertEqual(kwargs["submitter_orcid_id"], "owner")

    def test_marks_a_claim_stale_when_another_commit_advanced_the_branch(self) -> None:
        db = Mock()
        db.list_submissions_by_status.return_value = [publishing_row()]
        db.update_submission.return_value = 1
        client = RecoveryGitHubClient(head="new-head")

        report = recover_stranded_github_publications(3600, db=db, client=client)

        self.assertEqual(report.stale, 1)
        self.assertEqual(client.history_reads, 2)
        updates = db.update_submission.call_args.args[1]
        self.assertEqual(updates["submission_status"], "changes_requested")
        self.assertIn("expected base, found new-head", updates["review_feedback"])

    def test_defers_recovery_when_github_is_unavailable(self) -> None:
        db = Mock()
        db.list_submissions_by_status.return_value = [publishing_row()]
        client = RecoveryGitHubClient()
        client.error = GitHubPublicationError("unavailable")

        report = recover_stranded_github_publications(3600, db=db, client=client)

        self.assertEqual(report.deferred, 1)
        db.update_submission.assert_not_called()

    def test_releases_an_incomplete_claim_without_contacting_github(self) -> None:
        db = Mock()
        db.list_submissions_by_status.return_value = [publishing_row(input_github_commit_sha=None)]
        db.update_submission.return_value = 1
        client = RecoveryGitHubClient()

        report = recover_stranded_github_publications(3600, db=db, client=client)

        self.assertEqual(report.released, 1)
        self.assertEqual(client.history_reads, 0)

    def test_concurrent_recovery_that_already_changed_the_claim_is_harmless(self) -> None:
        db = Mock()
        db.list_submissions_by_status.return_value = [publishing_row()]
        db.update_submission.return_value = 0

        report = recover_stranded_github_publications(
            3600,
            db=db,
            client=RecoveryGitHubClient(head="base"),
        )

        self.assertEqual(report.unchanged, 1)
        self.assertEqual(report.released, 0)


if __name__ == "__main__":
    unittest.main()
