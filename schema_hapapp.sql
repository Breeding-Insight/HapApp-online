-- Complete HapApp Microsoft SQL Server schema for a fresh installation.
-- This script deliberately targets HaploSearch so the objects cannot be created
-- in whichever database happens to be selected in the SQL client.

USE [HaploSearch];
GO

IF DB_NAME() <> N'HaploSearch'
    THROW 50000, 'schema_hapapp.sql must run in the HaploSearch database.', 1;
GO

IF OBJECT_ID('dbo.users', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.users (
        orcid_id NVARCHAR(255) NOT NULL PRIMARY KEY,
        display_name NVARCHAR(255),
        role NVARCHAR(32) NOT NULL
            CONSTRAINT DF_hapapp_users_role DEFAULT 'user',
        is_active BIT NOT NULL
            CONSTRAINT DF_hapapp_users_is_active DEFAULT 1,
        created_at DATETIME NOT NULL
            CONSTRAINT DF_hapapp_users_created_at DEFAULT GETDATE(),
        updated_at DATETIME NOT NULL
            CONSTRAINT DF_hapapp_users_updated_at DEFAULT GETDATE()
    );
END;
GO

-- Add at least one authorized ORCID account after installing the schema, e.g.:
-- INSERT INTO dbo.users (orcid_id, display_name, role)
-- VALUES (N'0000-0000-0000-0000', N'Example User', N'admin');

IF SCHEMA_ID('hapapp') IS NULL
    EXEC('CREATE SCHEMA hapapp AUTHORIZATION dbo');
GO

IF OBJECT_ID('hapapp.orcid_profiles', 'U') IS NULL
BEGIN
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
END;
GO

IF OBJECT_ID('hapapp.madc_submissions', 'U') IS NULL
BEGIN
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
END;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_hapapp_madc_submissions_status'
      AND parent_object_id = OBJECT_ID('hapapp.madc_submissions')
      AND definition NOT LIKE '%publishing%'
)
    ALTER TABLE hapapp.madc_submissions DROP CONSTRAINT CK_hapapp_madc_submissions_status;
IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_hapapp_madc_submissions_status'
      AND parent_object_id = OBJECT_ID('hapapp.madc_submissions')
)
    ALTER TABLE hapapp.madc_submissions ADD CONSTRAINT CK_hapapp_madc_submissions_status
        CHECK (submission_status IN (
            'awaiting_decision', 'publishing', 'submitted_for_review', 'changes_requested',
            'accepted', 'incorporated', 'rejected', 'declined'
        ));
IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_hapapp_madc_submissions_freshness'
      AND parent_object_id = OBJECT_ID('hapapp.madc_submissions')
)
    ALTER TABLE hapapp.madc_submissions ADD CONSTRAINT CK_hapapp_madc_submissions_freshness
        CHECK (freshness_status IN ('unknown', 'current', 'stale'));
IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_hapapp_madc_submissions_archive'
      AND parent_object_id = OBJECT_ID('hapapp.madc_submissions')
)
    ALTER TABLE hapapp.madc_submissions ADD CONSTRAINT CK_hapapp_madc_submissions_archive
        CHECK (archive_status IN ('pending', 'archived', 'not_configured', 'failed'));
GO

IF OBJECT_ID('dbo.users', 'U') IS NULL
    THROW 50001, 'HaploSearch bootstrap failed: dbo.users is missing.', 1;
IF OBJECT_ID('hapapp.orcid_profiles', 'U') IS NULL
    THROW 50002, 'HaploSearch bootstrap failed: hapapp.orcid_profiles is missing.', 1;
IF OBJECT_ID('hapapp.madc_submissions', 'U') IS NULL
    THROW 50003, 'HaploSearch bootstrap failed: hapapp.madc_submissions is missing.', 1;
IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_hapapp_madc_submissions_status'
      AND parent_object_id = OBJECT_ID('hapapp.madc_submissions')
      AND definition LIKE '%publishing%'
)
    THROW 50004, 'HaploSearch bootstrap failed: publishing status is missing.', 1;

SELECT
    DB_NAME() AS database_name,
    OBJECT_SCHEMA_NAME(OBJECT_ID('dbo.users')) + N'.' + OBJECT_NAME(OBJECT_ID('dbo.users')) AS users_table,
    OBJECT_SCHEMA_NAME(OBJECT_ID('hapapp.orcid_profiles')) + N'.'
        + OBJECT_NAME(OBJECT_ID('hapapp.orcid_profiles')) AS profiles_table,
    OBJECT_SCHEMA_NAME(OBJECT_ID('hapapp.madc_submissions')) + N'.'
        + OBJECT_NAME(OBJECT_ID('hapapp.madc_submissions')) AS submissions_table,
    N'ready' AS github_publication_schema;
GO
