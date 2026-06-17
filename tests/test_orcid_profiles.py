from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from hapapp_python.orcid_profiles import (
    ORCIDProfile,
    fetch_public_orcid_profile,
    get_cached_profile,
    parse_orcid_record,
    refresh_profile,
    upsert_profile,
)


class ORCIDProfileTests(unittest.TestCase):
    def test_parses_public_person_profile_fields(self) -> None:
        profile = parse_orcid_record(
            "0000-0001-2345-6789",
            {
                "person": {
                    "name": {
                        "given-names": {"value": "Jane"},
                        "family-name": {"value": "Doe"},
                        "credit-name": {"value": "Dr. Jane Doe"},
                    },
                    "emails": {
                        "email": [
                            {"email": "private@example.org", "visibility": "limited", "primary": True},
                            {"email": "public@example.org", "visibility": "public", "primary": False},
                            {"email": "jane@example.org", "visibility": "public", "primary": True},
                        ]
                    },
                    "addresses": {"address": [{"country": {"value": "CA"}}]},
                },
                "activities-summary": {
                    "employments": {
                        "affiliation-group": [
                            {
                                "summaries": [
                                    {
                                        "employment-summary": {
                                            "start-date": {"year": {"value": "2020"}},
                                            "end-date": {"year": {"value": "2022"}},
                                            "organization": {"name": "Previous Institution"},
                                        }
                                    },
                                    {
                                        "employment-summary": {
                                            "start-date": {"year": {"value": "2023"}},
                                            "end-date": None,
                                            "organization": {
                                                "name": "Current Institution",
                                                "address": {
                                                    "city": "Ithaca",
                                                    "region": "NY",
                                                    "country": "US",
                                                },
                                            },
                                        }
                                    },
                                ]
                            },
                        ]
                    }
                },
            },
        )

        self.assertEqual(profile.display_name, "Dr. Jane Doe")
        self.assertEqual(profile.public_email, "jane@example.org")
        self.assertEqual(profile.institution, "Current Institution")
        self.assertEqual(profile.location, "Ithaca, NY, US")
        self.assertEqual(
            set(profile.__dataclass_fields__),
            {"orcid_id", "display_name", "public_email", "institution", "location"},
        )

    def test_parses_profile_with_missing_optional_fields(self) -> None:
        profile = parse_orcid_record("0000-0001-2345-6789", {"person": {"name": {"given-names": {"value": "Jane"}}}})

        self.assertEqual(profile.display_name, "Jane")
        self.assertIsNone(profile.public_email)
        self.assertIsNone(profile.institution)

    def test_selects_latest_completed_employment_when_none_are_active(self) -> None:
        profile = parse_orcid_record(
            "0000-0001-2345-6789",
            {
                "activities-summary": {
                    "employments": {
                        "employment-summary": [
                            {
                                "start-date": {"year": {"value": "2020"}},
                                "end-date": {"year": {"value": "2024"}},
                                "organization": {"name": "Latest"},
                            },
                            {
                                "start-date": {"year": {"value": "2021"}},
                                "end-date": {"year": {"value": "2023"}},
                                "organization": {"name": "Older"},
                            },
                        ]
                    }
                }
            },
        )

        self.assertEqual(profile.institution, "Latest")

    def test_fetches_full_record_with_read_public_token(self) -> None:
        token_response = Mock()
        token_response.json.return_value = {"access_token": "token"}
        token_response.raise_for_status.return_value = None
        record_response = Mock()
        record_response.json.return_value = {"person": {"name": {"given-names": {"value": "Jane"}}}}
        record_response.raise_for_status.return_value = None

        with patch("hapapp_python.orcid_profiles.requests.post", return_value=token_response) as post, patch(
            "hapapp_python.orcid_profiles.requests.get", return_value=record_response
        ) as get:
            profile = fetch_public_orcid_profile("0000-0001-2345-6789")

        self.assertEqual(profile.display_name, "Jane")
        self.assertEqual(post.call_args.kwargs["data"]["scope"], "/read-public")
        self.assertTrue(get.call_args.args[0].endswith("/0000-0001-2345-6789/record"))
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer token")

    def test_refresh_fetches_profile_even_when_cache_exists(self) -> None:
        cached = {"orcid_id": "0000-0001-2345-6789"}
        refreshed = {"orcid_id": "0000-0001-2345-6789", "display_name": "Jane"}

        with patch("hapapp_python.orcid_profiles.get_cached_profile", side_effect=[cached, refreshed]), patch(
            "hapapp_python.orcid_profiles.fetch_public_orcid_profile"
        ) as fetch, patch(
            "hapapp_python.orcid_profiles.upsert_profile"
        ):
            self.assertEqual(
                refresh_profile("0000-0001-2345-6789", db=object()),
                refreshed,
            )

        fetch.assert_called_once_with("0000-0001-2345-6789")

    def test_refresh_returns_cached_profile_when_fetch_fails(self) -> None:
        cached = {
            "orcid_id": "0000-0001-2345-6789",
        }

        with patch("hapapp_python.orcid_profiles.get_cached_profile", return_value=cached), patch(
            "hapapp_python.orcid_profiles.fetch_public_orcid_profile", side_effect=RuntimeError("offline")
        ):
            self.assertEqual(refresh_profile("0000-0001-2345-6789", db=object()), cached)

    def test_refresh_returns_none_when_fetch_fails_without_cached_profile(self) -> None:
        with patch("hapapp_python.orcid_profiles.get_cached_profile", return_value=None), patch(
            "hapapp_python.orcid_profiles.fetch_public_orcid_profile", side_effect=RuntimeError("offline")
        ):
            self.assertIsNone(refresh_profile("0000-0001-2345-6789", db=object()))

    def test_reads_cached_profile_from_hapapp_schema(self) -> None:
        db = Mock()
        db.execute_query.return_value = []

        get_cached_profile("0000-0001-2345-6789", db)

        self.assertEqual(
            db.execute_query.call_args.args,
            ("SELECT * FROM hapapp.orcid_profiles WHERE orcid_id = ?", ("0000-0001-2345-6789",)),
        )

    def test_upserts_profile_in_hapapp_schema(self) -> None:
        db = Mock()

        upsert_profile(ORCIDProfile(orcid_id="0000-0001-2345-6789"), db)

        sql = db.execute_update.call_args.args[0]
        self.assertIn("MERGE hapapp.orcid_profiles AS target", sql)


if __name__ == "__main__":
    unittest.main()
