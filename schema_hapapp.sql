-- HapApp-owned Microsoft SQL Server schema.
-- Apply during deployment with a schema-owner account, not the HapApp runtime account.

USE HaploSearch;
GO

CREATE SCHEMA hapapp AUTHORIZATION dbo;
GO

CREATE TABLE hapapp.orcid_profiles (
    orcid_id NVARCHAR(255) NOT NULL PRIMARY KEY,
    display_name NVARCHAR(255),
    public_email NVARCHAR(255),
    institution NVARCHAR(255),
    location NVARCHAR(255),
    last_fetched_at DATETIME,
    created_at DATETIME DEFAULT GETDATE(),
    updated_at DATETIME DEFAULT GETDATE()
);
GO

CREATE TABLE hapapp.madc_submissions (
    run_id NVARCHAR(64) NOT NULL PRIMARY KEY,
    submitter_orcid_id NVARCHAR(255) NOT NULL,
    submitter_display_name NVARCHAR(255),
    submitter_email NVARCHAR(255),
    submitted_for_name NVARCHAR(255),
    submitted_for_location NVARCHAR(255),
    submitted_for_email NVARCHAR(255),
    submitted_for_institution NVARCHAR(255),
    informal_project_name NVARCHAR(255),
    inferred_project_id NVARCHAR(255),
    madc_filename NVARCHAR(512),
    panel_id NVARCHAR(255),
    panel_label NVARCHAR(255),
    metadata_json NVARCHAR(MAX),
    submission_status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_hapapp_madc_submissions_status DEFAULT 'awaiting_decision',
    freshness_status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_hapapp_madc_submissions_freshness DEFAULT 'unknown',
    input_github_repository NVARCHAR(512),
    input_github_ref NVARCHAR(255),
    input_github_commit_sha NVARCHAR(64),
    input_database_version NVARCHAR(32),
    proposed_database_version NVARCHAR(32),
    output_checksums_json NVARCHAR(MAX),
    pull_request_url NVARCHAR(1024),
    incorporation_commit_url NVARCHAR(1024),
    review_feedback NVARCHAR(MAX),
    reviewer_orcid_id NVARCHAR(255),
    archive_status NVARCHAR(32) NOT NULL
        CONSTRAINT DF_hapapp_madc_submissions_archive DEFAULT 'pending',
    archive_error NVARCHAR(MAX),
    archive_at DATETIME,
    freshness_checked_at DATETIME,
    reviewed_at DATETIME,
    incorporated_at DATETIME,
    decision_at DATETIME,
    created_at DATETIME DEFAULT GETDATE(),
    updated_at DATETIME DEFAULT GETDATE()
);
GO

ALTER TABLE hapapp.madc_submissions ADD CONSTRAINT CK_hapapp_madc_submissions_status
    CHECK (submission_status IN (
        'awaiting_decision', 'submitted_for_review', 'changes_requested',
        'accepted', 'incorporated', 'rejected', 'declined'
    ));
ALTER TABLE hapapp.madc_submissions ADD CONSTRAINT CK_hapapp_madc_submissions_freshness
    CHECK (freshness_status IN ('unknown', 'current', 'stale'));
ALTER TABLE hapapp.madc_submissions ADD CONSTRAINT CK_hapapp_madc_submissions_archive
    CHECK (archive_status IN ('pending', 'archived', 'not_configured', 'failed'));
GO

CREATE ROLE hapapp_runtime AUTHORIZATION dbo;
GO

GRANT SELECT ON dbo.users TO hapapp_runtime;
GRANT SELECT, INSERT, UPDATE ON SCHEMA::hapapp TO hapapp_runtime;
DENY INSERT, UPDATE, DELETE ON dbo.users TO hapapp_runtime;
GO
