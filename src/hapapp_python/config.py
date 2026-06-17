from __future__ import annotations

import os
from urllib.parse import urlparse

APP_ENV = os.getenv("APP_ENV", os.getenv("HAPAPP_APP_ENV", "development"))

APP_HOST = os.getenv("HAPAPP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("HAPAPP_PORT", "8050"))
DEBUG_MODE = os.getenv("HAPAPP_DEBUG", "0").lower() in ("true", "1", "yes")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
PUBLIC_URL = os.getenv("HAPAPP_PUBLIC_URL", "").rstrip("/")
PUBLIC_HOST = urlparse(PUBLIC_URL).netloc
LOCAL_AUTH_BYPASS_REQUESTED = os.getenv("HAPAPP_LOCAL_AUTH_BYPASS", "0").lower() in ("true", "1", "yes")
if LOCAL_AUTH_BYPASS_REQUESTED and APP_ENV != "local-dev":
    raise RuntimeError("HAPAPP_LOCAL_AUTH_BYPASS may only be enabled when APP_ENV=local-dev.")
LOCAL_AUTH_BYPASS = LOCAL_AUTH_BYPASS_REQUESTED and APP_ENV == "local-dev"
LOCAL_USER_ORCID_ID = os.getenv("HAPAPP_LOCAL_USER_ORCID_ID", "local-dev-user")
LOCAL_USER_NAME = os.getenv("HAPAPP_LOCAL_USER_NAME", "Local Developer")
LOCAL_USER_ROLE = os.getenv("HAPAPP_LOCAL_USER_ROLE", "user")

DATABASE_SERVER = os.getenv("MSSQL_SERVER", "localhost")
DATABASE_NAME = os.getenv("MSSQL_DATABASE", "HaploSearch")
DATABASE_USER = os.getenv("MSSQL_USER", "hapapp_runtime_user")
DATABASE_PASSWORD = os.getenv("MSSQL_PASSWORD", "")
DATABASE_DRIVER = os.getenv("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")
DATABASE_PORT = os.getenv("MSSQL_PORT", "1433")

if DATABASE_DRIVER == "FreeTDS" or DATABASE_DRIVER.endswith("libtdsodbc.so"):
    _conn_opts = (
        f"DRIVER={{{DATABASE_DRIVER}}};SERVER={DATABASE_SERVER};PORT={DATABASE_PORT};"
        f"DATABASE={DATABASE_NAME};UID={DATABASE_USER};PWD={DATABASE_PASSWORD};TDS_Version=7.4"
    )
else:
    _conn_opts = (
        f"DRIVER={{{DATABASE_DRIVER}}};SERVER={DATABASE_SERVER},{DATABASE_PORT};"
        f"DATABASE={DATABASE_NAME};UID={DATABASE_USER};PWD={DATABASE_PASSWORD}"
    )
    if os.getenv("MSSQL_TRUST_SERVER_CERTIFICATE", "").lower() in ("true", "1", "yes"):
        _conn_opts += ";TrustServerCertificate=yes"
DATABASE_CONNECTION_STRING = os.getenv("MSSQL_CONNECTION_STRING", _conn_opts)

ORCID_CLIENT_ID = os.getenv("ORCID_CLIENT_ID", "")
ORCID_CLIENT_SECRET = os.getenv("ORCID_CLIENT_SECRET", "")

if APP_ENV == "production":
    ORCID_BASE_URL = "https://orcid.org"
    ORCID_API_URL = "https://pub.orcid.org/v3.0"
else:
    ORCID_BASE_URL = "https://sandbox.orcid.org"
    ORCID_API_URL = "https://pub.sandbox.orcid.org/v3.0"

ORCID_AUTHORIZE_URL = f"{ORCID_BASE_URL}/oauth/authorize"
ORCID_TOKEN_URL = f"{ORCID_BASE_URL}/oauth/token"
