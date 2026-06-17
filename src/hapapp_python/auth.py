from __future__ import annotations

import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import Blueprint, redirect, request, session

from hapapp_python import config
from hapapp_python.database import DatabaseManager
from hapapp_python.orcid_profiles import refresh_profile

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def get_current_user() -> dict[str, str] | None:
    if config.LOCAL_AUTH_BYPASS:
        return {
            "orcid_id": config.LOCAL_USER_ORCID_ID,
            "user_name": config.LOCAL_USER_NAME,
            "user_role": config.LOCAL_USER_ROLE,
        }

    orcid_id = session.get("orcid_id")
    if not orcid_id:
        return None
    return {
        "orcid_id": orcid_id,
        "user_name": session.get("user_name", ""),
        "user_role": session.get("user_role", "user"),
    }


def is_authenticated() -> bool:
    return config.LOCAL_AUTH_BYPASS or session.get("orcid_id") is not None


def require_login(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not is_authenticated():
            return redirect("/")
        return func(*args, **kwargs)

    return wrapped


def lookup_user(orcid_id: str, db: DatabaseManager | None = None) -> dict | None:
    try:
        manager = db or DatabaseManager()
        rows = manager.execute_query("SELECT * FROM dbo.users WHERE orcid_id = ? AND is_active = 1", (orcid_id,))
        return rows[0] if rows else None
    except Exception:
        return None


def _set_user_session(orcid_id: str, user: dict, display_name: str | None = None) -> None:
    session["orcid_id"] = orcid_id
    session["user_name"] = user.get("display_name") or display_name or ""
    session["user_role"] = user.get("role", "user")


def _callback_url() -> str:
    base_url = config.PUBLIC_URL or request.url_root.rstrip("/")
    return f"{base_url}/auth/callback"


@auth_bp.route("/login")
def login():
    if config.LOCAL_AUTH_BYPASS:
        return redirect("/app/")

    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    redirect_uri = _callback_url()
    authorize_url = config.ORCID_AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": config.ORCID_CLIENT_ID,
            "response_type": "code",
            "scope": "/authenticate",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return redirect(authorize_url)


@auth_bp.route("/callback")
def callback():
    state = request.args.get("state")
    if state != session.pop("oauth_state", None):
        return "Invalid state parameter. Please try again.", 400

    code = request.args.get("code")
    if not code:
        return request.args.get("error_description", "Authorization was denied."), 400

    redirect_uri = _callback_url()
    try:
        response = requests.post(
            config.ORCID_TOKEN_URL,
            data={
                "client_id": config.ORCID_CLIENT_ID,
                "client_secret": config.ORCID_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        token_json = response.json()
    except Exception as exc:  # noqa: BLE001 - shown on auth error route.
        return f"Failed to exchange token with ORCID: {exc}", 500

    orcid_id = token_json.get("orcid")
    display_name = token_json.get("name", "")
    if not orcid_id:
        return "Could not retrieve ORCID iD.", 500

    user = lookup_user(orcid_id)
    if not user:
        return "Your ORCID iD is not authorized to access this application. Please contact an administrator.", 403

    profile = refresh_profile(orcid_id)
    _set_user_session(orcid_id, user, (profile or {}).get("display_name") or display_name)
    return redirect("/app/")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")
