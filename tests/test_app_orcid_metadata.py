from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask, session

from hapapp_python import config
from hapapp_python.app import _orcid_metadata_defaults


class AppORCIDMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.local_auth_bypass = patch.object(config, "LOCAL_AUTH_BYPASS", False)
        self.local_auth_bypass.start()
        self.addCleanup(self.local_auth_bypass.stop)

    def test_defaults_use_current_logged_in_users_public_orcid_info(self) -> None:
        app = Flask(__name__)
        app.secret_key = "test"

        with app.test_request_context("/"):
            session["orcid_id"] = "0000-0001-2345-6789"
            session["user_name"] = "Fallback Name"
            with patch(
                "hapapp_python.app.get_cached_profile",
                return_value={
                    "display_name": "Dr. Jane Doe",
                    "public_email": "jane@example.org",
                    "institution": "Current Institution",
                    "location": "Ithaca, NY, US",
                },
            ) as get_cached:
                defaults = _orcid_metadata_defaults()

        get_cached.assert_called_once_with("0000-0001-2345-6789")
        self.assertEqual(
            defaults,
            ("Dr. Jane Doe", "Current Institution", "Ithaca, NY, US", "jane@example.org"),
        )

    def test_defaults_are_blank_when_no_cached_profile_exists(self) -> None:
        app = Flask(__name__)
        app.secret_key = "test"

        with app.test_request_context("/"):
            session["orcid_id"] = "0000-0001-2345-6789"
            session["user_name"] = "Session Name"
            with patch("hapapp_python.app.get_cached_profile", return_value=None):
                defaults = _orcid_metadata_defaults()

        self.assertEqual(defaults, ("", "", "", ""))


if __name__ == "__main__":
    unittest.main()
