from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlparse

from hapapp_python.github_panel_files import GITHUB_API_VERSION, GITHUB_TOKEN_ENV, USER_AGENT

GITHUB_MAX_BLOB_BYTES = 100 * 1024 * 1024


class GitHubPublicationError(RuntimeError):
    """Raised when a contribution cannot be published to GitHub."""


class StaleGitHubBaseError(GitHubPublicationError):
    """Raised when the species branch advanced after a run began."""

    def __init__(self, expected_sha: str, current_sha: str):
        self.expected_sha = expected_sha
        self.current_sha = current_sha
        super().__init__(
            "The species database changed after this run started "
            f"(expected {expected_sha[:12]}, found {current_sha[:12]}). "
            "Rerun against the latest database before submitting."
        )


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    repo: str
    branch: str

    @property
    def web_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass(frozen=True)
class GitHubContributionFile:
    local_path: Path
    repository_path: str


@dataclass(frozen=True)
class GitHubCommitAuthor:
    name: str
    email: str


@dataclass(frozen=True)
class GitHubPublicationResult:
    commit_sha: str
    commit_url: str


@dataclass(frozen=True)
class GitHubBranchCommit:
    sha: str
    message: str


class GitHubGitDataClient(Protocol):
    def branch_head(self, repository: GitHubRepository) -> str: ...

    def branch_commits(self, repository: GitHubRepository, limit: int) -> list[GitHubBranchCommit]: ...

    def commit_tree(self, repository: GitHubRepository, commit_sha: str) -> str: ...

    def create_blob(self, repository: GitHubRepository, content: bytes) -> str: ...

    def create_tree(
        self,
        repository: GitHubRepository,
        base_tree_sha: str,
        entries: list[dict[str, str]],
    ) -> str: ...

    def create_commit(
        self,
        repository: GitHubRepository,
        message: str,
        tree_sha: str,
        parent_sha: str,
        author: GitHubCommitAuthor | None,
    ) -> str: ...

    def update_branch(self, repository: GitHubRepository, commit_sha: str) -> None: ...


class GitHubRESTClient:
    def __init__(self, token: str | None = None):
        resolved_token = token if token is not None else os.environ.get(GITHUB_TOKEN_ENV, "")
        if not resolved_token.strip():
            raise GitHubPublicationError(f"{GITHUB_TOKEN_ENV} is required to publish GitHub contributions.")
        self._token = resolved_token.strip()

    def branch_head(self, repository: GitHubRepository) -> str:
        payload = self._request_json(
            "GET",
            self._repo_api_url(repository, f"git/ref/heads/{quote(repository.branch, safe='')}"),
        )
        try:
            sha = payload["object"]["sha"]
        except (KeyError, TypeError) as exc:
            raise GitHubPublicationError("GitHub returned an invalid branch reference response.") from exc
        if not isinstance(sha, str) or not sha:
            raise GitHubPublicationError("GitHub returned an empty branch commit SHA.")
        return sha

    def branch_commits(self, repository: GitHubRepository, limit: int) -> list[GitHubBranchCommit]:
        if limit <= 0 or limit > 100:
            raise ValueError("GitHub branch commit limit must be between 1 and 100.")
        payload = self._request_json(
            "GET",
            self._repo_api_url(
                repository,
                f"commits?sha={quote(repository.branch, safe='')}&per_page={limit}",
            ),
        )
        if not isinstance(payload, list):
            raise GitHubPublicationError("GitHub returned an invalid branch commit history response.")

        commits: list[GitHubBranchCommit] = []
        for item in payload:
            sha = item.get("sha") if isinstance(item, dict) else None
            commit = item.get("commit") if isinstance(item, dict) else None
            message = commit.get("message") if isinstance(commit, dict) else None
            if not isinstance(sha, str) or not sha or not isinstance(message, str):
                raise GitHubPublicationError("GitHub returned an invalid branch commit history entry.")
            commits.append(GitHubBranchCommit(sha=sha, message=message))
        return commits

    def commit_tree(self, repository: GitHubRepository, commit_sha: str) -> str:
        payload = self._request_json(
            "GET",
            self._repo_api_url(repository, f"git/commits/{quote(commit_sha, safe='')}"),
        )
        try:
            sha = payload["tree"]["sha"]
        except (KeyError, TypeError) as exc:
            raise GitHubPublicationError("GitHub returned an invalid commit response.") from exc
        if not isinstance(sha, str) or not sha:
            raise GitHubPublicationError("GitHub returned an empty tree SHA.")
        return sha

    def create_blob(self, repository: GitHubRepository, content: bytes) -> str:
        payload = self._request_json(
            "POST",
            self._repo_api_url(repository, "git/blobs"),
            {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
        )
        return self._response_sha(payload, "blob")

    def create_tree(
        self,
        repository: GitHubRepository,
        base_tree_sha: str,
        entries: list[dict[str, str]],
    ) -> str:
        payload = self._request_json(
            "POST",
            self._repo_api_url(repository, "git/trees"),
            {"base_tree": base_tree_sha, "tree": entries},
        )
        return self._response_sha(payload, "tree")

    def create_commit(
        self,
        repository: GitHubRepository,
        message: str,
        tree_sha: str,
        parent_sha: str,
        author: GitHubCommitAuthor | None,
    ) -> str:
        body: dict[str, Any] = {"message": message, "tree": tree_sha, "parents": [parent_sha]}
        if author is not None:
            body["author"] = {"name": author.name, "email": author.email}
        payload = self._request_json(
            "POST",
            self._repo_api_url(repository, "git/commits"),
            body,
        )
        return self._response_sha(payload, "commit")

    def update_branch(self, repository: GitHubRepository, commit_sha: str) -> None:
        self._request_json(
            "PATCH",
            self._repo_api_url(repository, f"git/refs/heads/{quote(repository.branch, safe='')}"),
            {"sha": commit_sha, "force": False},
        )

    def _repo_api_url(self, repository: GitHubRepository, path: str) -> str:
        return (
            "https://api.github.com/repos/"
            f"{quote(repository.owner, safe='')}/{quote(repository.repo, safe='')}/{path}"
        )

    def _request_json(self, method: str, url: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            permission_hint = ""
            if exc.code == 403:
                accepted_permissions = exc.headers.get("X-Accepted-GitHub-Permissions", "")
                permission_hint = (
                    f" Verify that {GITHUB_TOKEN_ENV} selects this repository and grants "
                    "Repository permissions > Contents: Read and write."
                )
                if accepted_permissions:
                    permission_hint += f" GitHub reports this endpoint accepts: {accepted_permissions}."
            raise GitHubPublicationError(
                f"GitHub API request failed ({exc.code}): {detail}{permission_hint}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubPublicationError(f"GitHub API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise GitHubPublicationError("GitHub returned invalid JSON.") from exc

    @staticmethod
    def _response_sha(payload: Any, label: str) -> str:
        sha = payload.get("sha") if isinstance(payload, dict) else None
        if not isinstance(sha, str) or not sha:
            raise GitHubPublicationError(f"GitHub returned an invalid {label} response.")
        return sha


def parse_github_repository(repository_url: str, branch: str) -> GitHubRepository:
    parsed = urlparse(repository_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise GitHubPublicationError(f"Unsupported GitHub repository URL: {repository_url}")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise GitHubPublicationError("GitHub repository URLs must use the github.com/<owner>/<repo> form.")
    repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    if not branch.strip():
        raise GitHubPublicationError("A GitHub branch is required for publication.")
    return GitHubRepository(owner=parts[0], repo=repo, branch=branch.strip())


def normalized_repository_path(path: str) -> str:
    candidate = PurePosixPath(path.strip())
    if (
        not path.strip()
        or candidate.is_absolute()
        or "\\" in path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise GitHubPublicationError(f"Invalid GitHub repository path: {path!r}")
    return candidate.as_posix()


def github_branch_head(
    repository: GitHubRepository,
    *,
    client: GitHubGitDataClient | None = None,
) -> str:
    return (client or GitHubRESTClient()).branch_head(repository)


def find_github_commit_for_run(
    repository: GitHubRepository,
    run_id: str,
    *,
    limit: int = 100,
    client: GitHubGitDataClient | None = None,
) -> GitHubPublicationResult | None:
    """Find a published HapApp commit by its exact run-id trailer."""
    normalized_run_id = run_id.strip()
    if not normalized_run_id:
        raise ValueError("A HapApp run ID is required to search GitHub commit history.")
    trailer = f"HapApp-Run-ID: {normalized_run_id}"
    resolved_client = client or GitHubRESTClient()
    for commit in resolved_client.branch_commits(repository, limit):
        if any(line.strip() == trailer for line in commit.message.splitlines()):
            return GitHubPublicationResult(
                commit_sha=commit.sha,
                commit_url=f"{repository.web_url}/commit/{commit.sha}",
            )
    return None


def assert_github_base_is_current(
    repository: GitHubRepository,
    expected_sha: str,
    *,
    client: GitHubGitDataClient | None = None,
) -> str:
    current_sha = github_branch_head(repository, client=client)
    if current_sha != expected_sha:
        raise StaleGitHubBaseError(expected_sha, current_sha)
    return current_sha


def publish_github_contribution(
    repository: GitHubRepository,
    expected_head_sha: str,
    files: list[GitHubContributionFile],
    message: str,
    *,
    author: GitHubCommitAuthor | None = None,
    client: GitHubGitDataClient | None = None,
) -> GitHubPublicationResult:
    """Publish all contribution files in one compare-and-swap branch update.

    The branch update is non-forced and the created commit has exactly
    ``expected_head_sha`` as its parent. If another publisher advances the branch,
    the second update is non-fast-forward and cannot overwrite the winner.
    """
    resolved_client = client or GitHubRESTClient()
    if not expected_head_sha.strip():
        raise GitHubPublicationError("The run is missing its input GitHub commit SHA.")
    if not files:
        raise GitHubPublicationError("At least one contribution file is required.")
    if not message.strip():
        raise GitHubPublicationError("A GitHub commit message is required.")

    normalized_files: list[tuple[Path, str]] = []
    seen_paths: set[str] = set()
    for contribution in files:
        local_path = contribution.local_path.resolve()
        if not local_path.is_file():
            raise GitHubPublicationError(f"Contribution file is missing: {contribution.local_path}")
        if local_path.stat().st_size > GITHUB_MAX_BLOB_BYTES:
            raise GitHubPublicationError(
                f"Contribution file exceeds GitHub's 100 MiB file limit: {contribution.local_path.name}"
            )
        repository_path = normalized_repository_path(contribution.repository_path)
        if repository_path in seen_paths:
            raise GitHubPublicationError(f"Duplicate GitHub contribution path: {repository_path}")
        seen_paths.add(repository_path)
        normalized_files.append((local_path, repository_path))

    assert_github_base_is_current(repository, expected_head_sha, client=resolved_client)
    base_tree_sha = resolved_client.commit_tree(repository, expected_head_sha)
    tree_entries: list[dict[str, str]] = []
    for local_path, repository_path in normalized_files:
        blob_sha = resolved_client.create_blob(repository, local_path.read_bytes())
        tree_entries.append({"path": repository_path, "mode": "100644", "type": "blob", "sha": blob_sha})

    # Avoid creating an orphan commit when the branch changed during blob upload.
    assert_github_base_is_current(repository, expected_head_sha, client=resolved_client)
    tree_sha = resolved_client.create_tree(repository, base_tree_sha, tree_entries)
    commit_sha = resolved_client.create_commit(
        repository,
        message.strip(),
        tree_sha,
        expected_head_sha,
        author,
    )
    try:
        resolved_client.update_branch(repository, commit_sha)
    except GitHubPublicationError as exc:
        # A competing publisher can win between the last check and this atomic
        # update. Re-read the head to distinguish that race from permissions or
        # branch-protection failures.
        current_sha = resolved_client.branch_head(repository)
        if current_sha != expected_head_sha:
            raise StaleGitHubBaseError(expected_head_sha, current_sha) from exc
        raise

    return GitHubPublicationResult(
        commit_sha=commit_sha,
        commit_url=f"{repository.web_url}/commit/{commit_sha}",
    )
