from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from hapapp_python import config
from hapapp_python.database import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ORCIDProfile:
    orcid_id: str
    display_name: str | None = None
    public_email: str | None = None
    institution: str | None = None
    location: str | None = None


def _value(node: Any) -> str | None:
    if isinstance(node, dict):
        value = node.get("value")
        return str(value).strip() if value else None
    if node:
        return str(node).strip()
    return None


def _visibility_is_public(item: dict[str, Any]) -> bool:
    return str(item.get("visibility", "")).lower() == "public"


def _preferred_public_email(emails: list[dict[str, Any]]) -> str | None:
    public_emails = [email for email in emails if _visibility_is_public(email) and email.get("email")]
    if not public_emails:
        return None
    return next((email["email"] for email in public_emails if email.get("primary")), public_emails[0]["email"])


def _date_key(date: dict[str, Any] | None) -> tuple[int, int, int]:
    date = date or {}
    return tuple(int(_value(date.get(part)) or 0) for part in ("year", "month", "day"))


def _most_recent_employment(employments: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not employments:
        return None
    active = [employment for employment in employments if employment.get("end-date") is None]
    if active:
        return max(active, key=lambda employment: _date_key(employment.get("start-date")))
    return max(employments, key=lambda employment: _date_key(employment.get("end-date")))


def _employment_summaries(employments: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = list(employments.get("employment-summary") or [])
    for group in employments.get("affiliation-group") or []:
        for summary in group.get("summaries") or []:
            employment = summary.get("employment-summary")
            if employment:
                summaries.append(employment)
    return summaries


def _employment_location(employment: dict[str, Any] | None) -> str | None:
    organization = (employment or {}).get("organization") or {}
    address = organization.get("address") or {}
    city = _value(address.get("city"))
    region = _value(address.get("region"))
    country = _value(address.get("country"))
    return ", ".join(part for part in (city, region, country) if part) or None


def parse_orcid_record(orcid_id: str, payload: dict[str, Any]) -> ORCIDProfile:
    person = payload.get("person") or payload
    name = person.get("name") or {}
    given_names = _value(name.get("given-names"))
    family_name = _value(name.get("family-name"))
    credit_name = _value(name.get("credit-name"))
    display_name = credit_name or " ".join(part for part in [given_names, family_name] if part) or None

    emails = ((person.get("emails") or {}).get("email") or [])
    public_email = _preferred_public_email(emails)

    activities = payload.get("activities-summary") or {}
    employments = _employment_summaries(activities.get("employments") or {})
    employment = _most_recent_employment(employments)
    institution = ((employment or {}).get("organization") or {}).get("name")
    location = _employment_location(employment)

    return ORCIDProfile(
        orcid_id=orcid_id,
        display_name=display_name,
        public_email=public_email,
        institution=institution,
        location=location,
    )


parse_orcid_person = parse_orcid_record


def _public_api_access_token() -> str:
    response = requests.post(
        config.ORCID_TOKEN_URL,
        data={
            "client_id": config.ORCID_CLIENT_ID,
            "client_secret": config.ORCID_CLIENT_SECRET,
            "grant_type": "client_credentials",
            "scope": "/read-public",
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def fetch_public_orcid_profile(orcid_id: str) -> ORCIDProfile:
    access_token = _public_api_access_token()
    response = requests.get(
        f"{config.ORCID_API_URL}/{orcid_id}/record",
        headers={"Accept": "application/vnd.orcid+json", "Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    response.raise_for_status()
    return parse_orcid_record(orcid_id, response.json())


def get_cached_profile(orcid_id: str, db: DatabaseManager | None = None) -> dict[str, Any] | None:
    manager = db or DatabaseManager()
    rows = manager.execute_query("SELECT * FROM hapapp.orcid_profiles WHERE orcid_id = ?", (orcid_id,))
    return rows[0] if rows else None


def upsert_profile(profile: ORCIDProfile, db: DatabaseManager | None = None) -> None:
    manager = db or DatabaseManager()
    manager.execute_update(
        """
        MERGE hapapp.orcid_profiles AS target
        USING (SELECT ? AS orcid_id) AS source
        ON target.orcid_id = source.orcid_id
        WHEN MATCHED THEN
            UPDATE SET
                display_name = ?, public_email = ?, institution = ?, location = ?,
                last_fetched_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHEN NOT MATCHED THEN
            INSERT (
                orcid_id, display_name, public_email, institution, location, last_fetched_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
        """,
        (
            profile.orcid_id,
            profile.display_name,
            profile.public_email,
            profile.institution,
            profile.location,
            profile.orcid_id,
            profile.display_name,
            profile.public_email,
            profile.institution,
            profile.location,
        ),
    )


def refresh_profile(orcid_id: str, db: DatabaseManager | None = None) -> dict[str, Any] | None:
    manager = db or DatabaseManager()
    cached = get_cached_profile(orcid_id, manager)
    try:
        profile = fetch_public_orcid_profile(orcid_id)
        upsert_profile(profile, manager)
        return get_cached_profile(orcid_id, manager)
    except Exception as exc:  # noqa: BLE001 - profile enrichment must not block login.
        logger.warning("Could not refresh ORCID profile for %s: %s", orcid_id, exc)
        return cached
