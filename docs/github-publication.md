# GitHub contribution publication

## Correctness model

HapApp does not use a process-local or global species lock. Locks would be difficult
to coordinate across multiple web workers and could be lost when a worker restarts.
Instead, GitHub's branch reference is the serialization point.

1. At run start, HapApp reads the configured species branch head SHA.
2. Every GitHub panel input is downloaded using that immutable SHA, even though the
   panel URLs name a moving branch such as `main`.
3. HapApp records the SHA with the run and processes only those pinned files.
4. After processing, HapApp checks whether the branch still has the recorded SHA.
   This provides early feedback but is not the correctness boundary.
5. If the workflow reports zero novel alleles, HapApp skips GitHub publication and
   records the run for Breeding Insight review while archiving its finalized MADC,
   metadata, and log. The remaining steps apply only to runs with novel alleles.
6. On confirmation, the database atomically claims a database-changing run by changing its status
   from `awaiting_decision` to `publishing`.
7. HapApp prepares one Git commit containing the fixed-allele-ID MADC, contribution
   metadata, and any new versioned database files. That commit has the run's input
   SHA as its sole parent.
8. HapApp performs a non-forced branch-reference update. If another contribution
   advanced the branch first, this update is non-fast-forward and GitHub rejects it.
   HapApp marks the losing run stale; it cannot overwrite the winning contribution.
9. Only after GitHub accepts the commit does HapApp archive the processed MADC, log,
   and run metadata to Dropbox.

The checks before publication reduce wasted work and provide clearer UI feedback.
The non-forced reference update is the final race-free guarantee.

## Species panel configuration

A GitHub-publishable panel must load all GitHub files from one repository and branch.
Its `allele_db_base` URL identifies the directory for new versioned database files.
Two additional panel settings identify contribution destinations:

```toml
[panels.alfalfa]
allele_db_base = "https://github.com/example/alfalfa/tree/main/data/versions"
matchcnt_lut_base = "https://github.com/example/alfalfa/tree/main/data/versions"
github_madc_dir = "data/madc"
github_metadata_dir = "data/metadata"
```

The fixed MADC and metadata filenames include the HapApp run ID to avoid accidental
replacement. All repository paths are validated as relative POSIX paths.

GitHub rejects individual Git objects larger than 100 MiB. HapApp checks this before
uploading any contribution files and reports a clear publication error. If processed
MADCs can exceed that limit, decide before production rollout whether to add Git LFS
support or keep the full MADC only in Dropbox and commit a checksum/pointer record.

## GitHub credentials and repository policy

Use a fine-grained `HAPAPP_GITHUB_TOKEN` whose resource owner owns the target species
repository. Select every configured species repository under Repository access and set
Repository permissions > Contents to Read and write (Metadata read access is added
automatically). Organization-owned tokens may also require owner approval and SSO
authorization. The token's identity becomes the committer; when the submission has a
public submitter name and email, HapApp also records that person as the commit author.
Commit messages include the HapApp run ID and submitter ORCID.

The target branch must allow this token to update it. If branch protection requires
pull requests, use a dedicated ingestion branch and promote it through a separate
review workflow; a protected branch rejection is reported as a publication failure,
not incorrectly classified as a stale run.

## State and recovery behavior

- `current`: the species head still matches the commit used for processing.
- `stale`: the species head changed; the run must be repeated.
- `publishing`: a durable database claim is held while GitHub objects and the branch
  update are created.
- `incorporated`: GitHub accepted the atomic commit.

Transient API or permission failures release the `publishing` claim back to
`awaiting_decision`, allowing an intentional retry. A concurrency loss changes the
run to `changes_requested` plus `stale`, which prevents retrying invalid output.

At application startup, HapApp reconciles `publishing` claims older than
`HAPAPP_GITHUB_PUBLISHING_RECOVERY_AGE_SECONDS` (one hour by default). It searches
the configured branch for the exact `HapApp-Run-ID` commit trailer. A matching
commit is finalized as `incorporated`. If no matching commit exists and the branch
still equals the run's pinned input SHA, the claim is released for retry. If the
branch advanced without the run's commit, the run becomes `changes_requested` and
`stale`. GitHub or database failures leave the claim untouched for a later recovery
attempt. Set `HAPAPP_GITHUB_PUBLISHING_RECOVERY_ENABLED=false` only when an external
reconciler owns this responsibility.

Git blobs, trees, or commits created before a rejected branch update may remain
temporarily unreachable in GitHub. They do not affect the branch and GitHub prunes
unreachable objects according to its own retention policy.

## Recommended operational follow-ups

Before production rollout:

1. Confirm each species repository's `github_madc_dir` and `github_metadata_dir`.
2. Connect to the deployment's dedicated application database and run
   `schema_hapapp.sql` followed by `permissions_hapapp.sql` with a database-owner
   account. The permissions script uses `hapapp_runtime_user` by default, recognizes
   a `dbo`/`db_owner` connection, and exposes one override for deployments whose
   `MSSQL_USER` has a different name.
3. Add a GitHub App token provider with automatic installation-token refresh, then
   replace the initially configured fine-grained token.
4. Add an external worker/queue if publication latency should be removed from the
   Dash callback. The same database claim and GitHub compare-and-swap must remain.
5. Alert on Dropbox archive failures separately. A Dropbox failure must never revert
   or repeat an already accepted GitHub commit.
