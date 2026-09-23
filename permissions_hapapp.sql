-- Optional HapApp runtime permissions.
-- Run after schema_hapapp.sql with a DB owner/admin
-- account. This is separate from schema_hapapp.sql so schema creation can be
-- run by users who cannot manage database roles or grants.

USE [HaploSearch];
GO

IF DB_NAME() <> N'HaploSearch'
    THROW 50000, 'permissions_hapapp.sql must run in the HaploSearch database.', 1;
IF OBJECT_ID('dbo.users', 'U') IS NULL
    THROW 50001, 'dbo.users is missing. Run schema_hapapp.sql first.', 1;
IF OBJECT_ID('hapapp.madc_submissions', 'U') IS NULL
    THROW 50002, 'hapapp.madc_submissions is missing. Run schema_hapapp.sql first.', 1;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'hapapp_runtime' AND type = 'R')
    CREATE ROLE hapapp_runtime;
GO

GRANT SELECT ON OBJECT::dbo.users TO hapapp_runtime;
DENY INSERT, UPDATE, DELETE ON OBJECT::dbo.users TO hapapp_runtime;
GRANT SELECT, INSERT, UPDATE ON SCHEMA::hapapp TO hapapp_runtime;
GO

-- Development and production use this standard database principal by default.
-- Set an explicit override only when MSSQL_USER has a different name, e.g.
-- DECLARE @hapapp_runtime_user_override SYSNAME = N'if-svc_brin-01_webuser_rw';
DECLARE @hapapp_runtime_user_override SYSNAME = NULL;
DECLARE @hapapp_runtime_user SYSNAME = COALESCE(
    @hapapp_runtime_user_override,
    CASE
        WHEN DATABASE_PRINCIPAL_ID(N'hapapp_runtime_user') IS NOT NULL
            THEN N'hapapp_runtime_user'
        ELSE NULL
    END
);
DECLARE @local_sysadmin BIT = CASE
    WHEN IS_SRVROLEMEMBER(N'sysadmin') = 1 AND USER_NAME() = N'dbo' THEN 1
    ELSE 0
END;

-- Local Docker connects as sa, which maps to dbo and already has every database
-- permission. Adding sa/dbo to a lesser database role is neither needed nor valid.
IF @hapapp_runtime_user IS NULL AND @local_sysadmin = 0
    THROW 50003, 'No HapApp runtime principal was found. Set @hapapp_runtime_user_override to match MSSQL_USER.', 1;

IF @hapapp_runtime_user IS NOT NULL
   AND NOT EXISTS (
       SELECT 1
       FROM sys.database_role_members
       WHERE role_principal_id = DATABASE_PRINCIPAL_ID(N'hapapp_runtime')
         AND member_principal_id = DATABASE_PRINCIPAL_ID(@hapapp_runtime_user)
   )
BEGIN
    DECLARE @add_member_sql NVARCHAR(MAX) =
        N'ALTER ROLE hapapp_runtime ADD MEMBER ' + QUOTENAME(@hapapp_runtime_user);
    EXEC sp_executesql @add_member_sql;
END;

IF @hapapp_runtime_user IS NOT NULL
BEGIN
    SELECT
        DB_NAME() AS database_name,
        N'role_membership' AS permission_mode,
        N'hapapp_runtime' AS database_role,
        @hapapp_runtime_user AS runtime_member;
END;
ELSE
BEGIN
    SELECT
        DB_NAME() AS database_name,
        N'local_sysadmin' AS permission_mode,
        CAST(NULL AS SYSNAME) AS database_role,
        SUSER_SNAME() AS runtime_member;
END;
GO
