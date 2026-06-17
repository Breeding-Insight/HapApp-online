from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from flask import Flask

from hapapp_python import config
from hapapp_python.auth import auth_bp, get_current_user, lookup_user
from hapapp_python.app import create_server


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.local_auth_bypass = patch.object(config, "LOCAL_AUTH_BYPASS", False)
        self.local_auth_bypass.start()
        self.addCleanup(self.local_auth_bypass.stop)

    def _auth_client(self):
        app = Flask(__name__)
        app.secret_key = "test"
        app.register_blueprint(auth_bp)
        return app.test_client()

    def test_login_uses_orcid_authenticate_scope(self) -> None:
        client = self._auth_client()

        with patch.object(config, "ORCID_CLIENT_ID", "client"), patch.object(
            config, "PUBLIC_URL", "https://hapapp.example"
        ):
            response = client.get("/auth/login")

        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("scope=%2Fauthenticate", location)
        self.assertIn("client_id=client", location)
        self.assertIn(
            "redirect_uri=https%3A%2F%2Fhapapp.example%2Fauth%2Fcallback",
            location,
        )

    def test_callback_rejects_invalid_state(self) -> None:
        client = self._auth_client()

        response = client.get("/auth/callback?state=bad&code=abc")

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Invalid state", response.data)

    def test_callback_rejects_unwhitelisted_user(self) -> None:
        client = self._auth_client()
        with client.session_transaction() as session:
            session["oauth_state"] = "state"

        token_response = Mock()
        token_response.json.return_value = {"orcid": "0000-0001-2345-6789", "name": "Jane Doe"}
        token_response.raise_for_status.return_value = None

        with patch.object(config, "PUBLIC_URL", "https://hapapp.example"), patch(
            "hapapp_python.auth.requests.post", return_value=token_response
        ) as post, patch("hapapp_python.auth.lookup_user", return_value=None):
            response = client.get("/auth/callback?state=state&code=abc")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            post.call_args.kwargs["data"]["redirect_uri"],
            "https://hapapp.example/auth/callback",
        )

    def test_callback_sets_hapsearch_compatible_session_for_active_user(self) -> None:
        client = self._auth_client()
        with client.session_transaction() as session:
            session["oauth_state"] = "state"

        token_response = Mock()
        token_response.json.return_value = {"orcid": "0000-0001-2345-6789", "name": "Jane Doe"}
        token_response.raise_for_status.return_value = None

        with patch("hapapp_python.auth.requests.post", return_value=token_response), patch(
            "hapapp_python.auth.lookup_user",
            return_value={"orcid_id": "0000-0001-2345-6789", "display_name": None, "role": "user"},
        ), patch("hapapp_python.auth.refresh_profile", return_value={"display_name": "Dr. Jane Doe"}) as refresh:
            response = client.get("/auth/callback?state=state&code=abc")

        refresh.assert_called_once_with("0000-0001-2345-6789")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/app/")
        with client.session_transaction() as session:
            self.assertEqual(session["orcid_id"], "0000-0001-2345-6789")
            self.assertEqual(session["user_name"], "Dr. Jane Doe")
            self.assertEqual(session["user_role"], "user")

    def test_user_lookup_is_read_only_and_uses_hapsearch_owned_table(self) -> None:
        db = Mock()
        db.execute_query.return_value = [{"orcid_id": "0000-0001-2345-6789"}]

        user = lookup_user("0000-0001-2345-6789", db)

        self.assertEqual(user, {"orcid_id": "0000-0001-2345-6789"})
        self.assertEqual(
            db.execute_query.call_args.args,
            (
                "SELECT * FROM dbo.users WHERE orcid_id = ? AND is_active = 1",
                ("0000-0001-2345-6789",),
            ),
        )
        db.execute_update.assert_not_called()

    def test_app_redirects_unauthenticated_app_post_but_allows_assets_get(self) -> None:
        server = create_server()
        client = server.test_client()

        with patch.object(config, "LOCAL_AUTH_BYPASS", False), patch.object(
            config, "PUBLIC_URL", ""
        ), patch.object(config, "PUBLIC_HOST", ""):
            app_response = client.get("/app/")
            asset_response = client.get("/app/assets/style.css")
            post_response = client.post("/app/_dash-update-component")

        self.assertEqual(app_response.status_code, 302)
        self.assertEqual(asset_response.status_code, 404)
        self.assertEqual(post_response.status_code, 302)

    def test_local_auth_bypass_provides_stable_identity(self) -> None:
        server = create_server()
        server.route("/current-user")(lambda: get_current_user())
        client = server.test_client()

        with patch.object(config, "LOCAL_AUTH_BYPASS", True), patch.object(
            config, "LOCAL_USER_ORCID_ID", "local-test-user"
        ), patch.object(config, "LOCAL_USER_NAME", "Local Tester"), patch.object(
            config, "LOCAL_USER_ROLE", "admin"
        ):
            root_response = client.get("/")
            user_response = client.get("/current-user")
            login_response = client.get("/auth/login")

        self.assertEqual(root_response.headers["Location"], "/app/")
        self.assertEqual(
            user_response.json,
            {
                "orcid_id": "local-test-user",
                "user_name": "Local Tester",
                "user_role": "admin",
            },
        )
        self.assertEqual(login_response.headers["Location"], "/app/")

    def test_local_request_redirects_to_configured_public_origin(self) -> None:
        with patch.object(config, "PUBLIC_URL", "https://hapapp.example"), patch.object(
            config, "PUBLIC_HOST", "hapapp.example"
        ):
            client = create_server().test_client()
            response = client.get("/auth/login?next=app")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "https://hapapp.example/auth/login?next=app",
        )


if __name__ == "__main__":
    unittest.main()
