from __future__ import annotations

import io
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from hapapp_python.github_submission import (
    GitHubBranchCommit,
    GitHubCommitAuthor,
    GitHubContributionFile,
    GitHubPublicationError,
    GitHubRepository,
    GitHubRESTClient,
    StaleGitHubBaseError,
    find_github_commit_for_run,
    normalized_repository_path,
    parse_github_repository,
    publish_github_contribution,
)


class FakeGitDataClient:
    def __init__(self, head: str = "base-sha") -> None:
        self.head = head
        self.branch_reads = 0
        self.created_blobs: list[bytes] = []
        self.created_tree: tuple[str, list[dict[str, str]]] | None = None
        self.created_commit: tuple[str, str, str, GitHubCommitAuthor | None] | None = None
        self.fail_update = False
        self.advance_during_update = False
        self.commits: list[GitHubBranchCommit] = []

    def branch_head(self, repository: GitHubRepository) -> str:
        self.branch_reads += 1
        return self.head

    def branch_commits(self, repository: GitHubRepository, limit: int) -> list[GitHubBranchCommit]:
        return self.commits[:limit]

    def commit_tree(self, repository: GitHubRepository, commit_sha: str) -> str:
        return "base-tree-sha"

    def create_blob(self, repository: GitHubRepository, content: bytes) -> str:
        self.created_blobs.append(content)
        return f"blob-{len(self.created_blobs)}"

    def create_tree(
        self,
        repository: GitHubRepository,
        base_tree_sha: str,
        entries: list[dict[str, str]],
    ) -> str:
        self.created_tree = (base_tree_sha, entries)
        return "new-tree-sha"

    def create_commit(
        self,
        repository: GitHubRepository,
        message: str,
        tree_sha: str,
        parent_sha: str,
        author: GitHubCommitAuthor | None,
    ) -> str:
        self.created_commit = (message, tree_sha, parent_sha, author)
        return "new-commit-sha"

    def update_branch(self, repository: GitHubRepository, commit_sha: str) -> None:
        if self.advance_during_update:
            self.head = "winning-commit-sha"
            raise GitHubPublicationError("non-fast-forward")
        if self.fail_update:
            raise GitHubPublicationError("branch protection")
        self.head = commit_sha


class GitHubSubmissionTests(unittest.TestCase):
    def test_finds_commit_by_exact_hapapp_run_trailer(self) -> None:
        client = FakeGitDataClient()
        client.commits = [
            GitHubBranchCommit("wrong", "Add contribution\n\nHapApp-Run-ID: run-extra"),
            GitHubBranchCommit("match", "Add contribution\n\nHapApp-Run-ID: run\nSubmitter-ORCID: owner"),
        ]

        result = find_github_commit_for_run(
            GitHubRepository("example", "species", "main"),
            "run",
            client=client,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.commit_sha, "match")
        self.assertEqual(result.commit_url, "https://github.com/example/species/commit/match")

    def test_permission_failure_explains_required_token_scope(self) -> None:
        headers = Message()
        headers["X-Accepted-GitHub-Permissions"] = "contents=write"
        error = urllib.error.HTTPError(
            "https://api.github.com/repos/example/species/git/blobs",
            403,
            "Forbidden",
            headers,
            io.BytesIO(b'{"message":"Resource not accessible by personal access token"}'),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(GitHubPublicationError) as caught:
                GitHubRESTClient("token").create_blob(GitHubRepository("example", "species", "main"), b"data")

        message = str(caught.exception)
        self.assertIn("selects this repository", message)
        self.assertIn("Contents: Read and write", message)
        self.assertIn("contents=write", message)

    def test_parses_repository_and_branch(self) -> None:
        self.assertEqual(
            parse_github_repository("https://github.com/example/species.git", "main"),
            GitHubRepository("example", "species", "main"),
        )

    def test_rejects_unsafe_repository_paths(self) -> None:
        for path in ["", "/data/file.csv", "../file.csv", "data/../file.csv", "data\\file.csv"]:
            with self.subTest(path=path), self.assertRaises(GitHubPublicationError):
                normalized_repository_path(path)

    def test_publishes_all_files_in_one_commit_based_on_expected_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            madc = root / "fixed.csv"
            metadata = root / "metadata.json"
            madc.write_bytes(b"madc")
            metadata.write_bytes(b"metadata")
            client = FakeGitDataClient()
            author = GitHubCommitAuthor("Jane Doe", "jane@example.org")

            result = publish_github_contribution(
                GitHubRepository("example", "species", "main"),
                "base-sha",
                [
                    GitHubContributionFile(madc, "data/madc/fixed.csv"),
                    GitHubContributionFile(metadata, "data/metadata/run.json"),
                ],
                "Add run",
                author=author,
                client=client,
            )

        self.assertEqual(result.commit_sha, "new-commit-sha")
        self.assertEqual(result.commit_url, "https://github.com/example/species/commit/new-commit-sha")
        self.assertEqual(client.created_blobs, [b"madc", b"metadata"])
        self.assertEqual(client.created_tree[0], "base-tree-sha")
        self.assertEqual(
            [entry["path"] for entry in client.created_tree[1]],
            ["data/madc/fixed.csv", "data/metadata/run.json"],
        )
        self.assertEqual(client.created_commit, ("Add run", "new-tree-sha", "base-sha", author))

    def test_rejects_a_run_that_is_already_stale_before_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "fixed.csv"
            source.write_text("data", encoding="utf-8")
            client = FakeGitDataClient(head="newer-sha")

            with self.assertRaises(StaleGitHubBaseError) as error:
                publish_github_contribution(
                    GitHubRepository("example", "species", "main"),
                    "base-sha",
                    [GitHubContributionFile(source, "data/fixed.csv")],
                    "Add run",
                    client=client,
                )

        self.assertEqual(error.exception.expected_sha, "base-sha")
        self.assertEqual(error.exception.current_sha, "newer-sha")
        self.assertEqual(client.created_blobs, [])

    def test_rejects_files_over_githubs_blob_limit_before_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "fixed.csv"
            source.write_bytes(b"four")
            client = FakeGitDataClient()

            with patch("hapapp_python.github_submission.GITHUB_MAX_BLOB_BYTES", 3):
                with self.assertRaisesRegex(GitHubPublicationError, "100 MiB"):
                    publish_github_contribution(
                        GitHubRepository("example", "species", "main"),
                        "base-sha",
                        [GitHubContributionFile(source, "data/fixed.csv")],
                        "Add run",
                        client=client,
                    )

        self.assertEqual(client.branch_reads, 0)

    def test_concurrent_winner_turns_non_fast_forward_update_into_stale_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "fixed.csv"
            source.write_text("data", encoding="utf-8")
            client = FakeGitDataClient()
            client.advance_during_update = True

            with self.assertRaises(StaleGitHubBaseError) as error:
                publish_github_contribution(
                    GitHubRepository("example", "species", "main"),
                    "base-sha",
                    [GitHubContributionFile(source, "data/fixed.csv")],
                    "Add run",
                    client=client,
                )

        self.assertEqual(error.exception.current_sha, "winning-commit-sha")

    def test_preserves_non_concurrency_update_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "fixed.csv"
            source.write_text("data", encoding="utf-8")
            client = FakeGitDataClient()
            client.fail_update = True

            with self.assertRaisesRegex(GitHubPublicationError, "branch protection"):
                publish_github_contribution(
                    GitHubRepository("example", "species", "main"),
                    "base-sha",
                    [GitHubContributionFile(source, "data/fixed.csv")],
                    "Add run",
                    client=client,
                )


if __name__ == "__main__":
    unittest.main()
