from __future__ import annotations

from dataclasses import dataclass, field

from hapapp_python.database import FirestoreRepository
from hapapp_python.github_submission import (
    GitHubGitDataClient,
    GitHubPublicationError,
    GitHubRESTClient,
    find_github_commit_for_run,
    parse_github_repository,
)
from hapapp_python.madc_submission import (
    StrandedPublishingSubmission,
    list_stranded_publishing_submissions,
    mark_stranded_publication_stale,
    persist_github_incorporation,
    release_submission_publication_claim,
)


@dataclass
class GitHubRecoveryReport:
    inspected: int = 0
    incorporated: int = 0
    released: int = 0
    stale: int = 0
    unchanged: int = 0
    deferred: int = 0
    messages: list[str] = field(default_factory=list)


def recover_stranded_github_publications(
    minimum_age_seconds: int,
    *,
    db: FirestoreRepository | None = None,
    client: GitHubGitDataClient | None = None,
) -> GitHubRecoveryReport:
    """Reconcile expired durable claims against the authoritative GitHub branch."""
    manager = db or FirestoreRepository()
    submissions = list_stranded_publishing_submissions(minimum_age_seconds, manager)
    report = GitHubRecoveryReport(inspected=len(submissions))

    for submission in submissions:
        try:
            _recover_one(submission, report, manager, client)
        except GitHubPublicationError as exc:
            report.deferred += 1
            report.messages.append(f"Run {submission.run_id}: GitHub recovery deferred: {exc}")
        except Exception as exc:  # noqa: BLE001 - one damaged claim must not block all recovery.
            report.deferred += 1
            report.messages.append(f"Run {submission.run_id}: publication recovery failed: {exc}")

    return report


def _recover_one(
    submission: StrandedPublishingSubmission,
    report: GitHubRecoveryReport,
    db: FirestoreRepository,
    client: GitHubGitDataClient | None,
) -> None:
    repository_url = submission.input_github_repository
    branch = submission.input_github_ref
    expected_sha = submission.input_github_commit_sha
    if not repository_url or not branch or not expected_sha:
        _record_release(
            submission,
            report,
            db,
            "Expired GitHub publication claim had incomplete pinned repository metadata; released for retry.",
        )
        return

    repository = parse_github_repository(repository_url, branch)
    resolved_client = client or GitHubRESTClient()
    published = find_github_commit_for_run(repository, submission.run_id, client=resolved_client)
    current_sha = resolved_client.branch_head(repository)

    # The branch may advance between the first history read and the head read.
    # Search the new history once more before classifying the run as stale.
    if published is None and current_sha != expected_sha:
        published = find_github_commit_for_run(repository, submission.run_id, client=resolved_client)

    if published is not None:
        updated = persist_github_incorporation(
            submission.run_id,
            submission.submitter_orcid_id,
            published.commit_url,
            db,
        )
        if updated == 1:
            report.incorporated += 1
            report.messages.append(
                f"Run {submission.run_id}: recovered incorporated commit {published.commit_sha}."
            )
        else:
            _record_unchanged(submission, report)
        return

    if current_sha == expected_sha:
        _record_release(
            submission,
            report,
            db,
            "Expired GitHub publication claim had no branch commit and was released for retry.",
        )
        return

    feedback = (
        "The species database changed while an interrupted GitHub publication was being recovered "
        f"(expected {expected_sha[:12]}, found {current_sha[:12]}). "
        "Rerun against the latest database before sharing the results."
    )
    updated = mark_stranded_publication_stale(
        submission.run_id,
        submission.submitter_orcid_id,
        feedback,
        db,
    )
    if updated == 1:
        report.stale += 1
        report.messages.append(f"Run {submission.run_id}: marked stale after the branch advanced.")
    else:
        _record_unchanged(submission, report)


def _record_release(
    submission: StrandedPublishingSubmission,
    report: GitHubRecoveryReport,
    db: FirestoreRepository,
    reason: str,
) -> None:
    updated = release_submission_publication_claim(
        submission.run_id,
        submission.submitter_orcid_id,
        reason,
        db,
    )
    if updated == 1:
        report.released += 1
        report.messages.append(f"Run {submission.run_id}: {reason}")
    else:
        _record_unchanged(submission, report)


def _record_unchanged(submission: StrandedPublishingSubmission, report: GitHubRecoveryReport) -> None:
    report.unchanged += 1
    report.messages.append(
        f"Run {submission.run_id}: claim changed during recovery; no additional update was made."
    )
