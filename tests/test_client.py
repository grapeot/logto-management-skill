from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from logto_management_skill.client import LogtoAPIError, LogtoClient


# ── Helpers ─────────────────────────────────────────────


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.text = text or (json.dumps(json_data) if json_data else "")
    resp.url = "https://auth.example.com/api/test"
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def _mock_token_response():
    return _mock_response(200, {"access_token": "fake-token-123"})


# ── Token tests ─────────────────────────────────────────


class TestToken:
    @patch("logto_management_skill.client.requests")
    def test_get_token_caches(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        mock_requests.request.return_value = _mock_response(200, [])

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        client._get_token()
        client._get_token()

        assert mock_requests.post.call_count == 1  # token fetched once

    @patch("logto_management_skill.client.requests")
    def test_401_triggers_refresh(self, mock_requests):
        # Token POST is always called via requests.post (not requests.request)
        mock_requests.post.return_value = _mock_token_response()

        # requests.request is called in this order:
        # 1. list_roles -> 401
        # 2. retry list_roles after token refresh -> 200
        mock_requests.request.side_effect = [
            _mock_response(401, text="expired"),
            _mock_response(200, [{"id": "1"}]),
        ]

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.list_roles()

        assert result == [{"id": "1"}]
        # Token fetched twice: initial + refresh after 401
        assert mock_requests.post.call_count == 2

    def test_custom_domain_without_tenant_id_raises(self):
        client = LogtoClient("https://auth.example.com", "id", "secret")
        with pytest.raises(LogtoAPIError, match="Custom domain requires"):
            client._get_token()

    @patch("logto_management_skill.client.requests")
    def test_logto_app_domain_resource(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        client = LogtoClient("mytenant", "id", "secret")
        client._get_token()

        call_args = mock_requests.post.call_args
        data = call_args[1]["data"]
        assert data["resource"] == "https://mytenant.logto.app/api"


# ── User tests ──────────────────────────────────────────


class TestUsers:
    @patch("logto_management_skill.client.requests")
    def test_create_user_success(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        user_data = {"id": "u1", "primaryEmail": "alice@example.com", "name": "Alice"}
        mock_requests.request.return_value = _mock_response(201, user_data)

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.create_user("alice@example.com", name="Alice")

        assert result["id"] == "u1"
        assert result["primaryEmail"] == "alice@example.com"

    @patch("logto_management_skill.client.requests")
    def test_create_user_already_exists_returns_existing(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        existing = {"id": "u1", "primaryEmail": "alice@example.com"}

        # create returns 409, then find_user_by_email returns existing
        mock_requests.request.side_effect = [
            _mock_response(409, text="conflict"),
            _mock_response(200, [existing]),  # find_user_by_email
        ]

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.create_user("alice@example.com")

        assert result["id"] == "u1"

    @patch("logto_management_skill.client.requests")
    def test_find_user_by_email_found(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        user = {"id": "u1", "primaryEmail": "alice@example.com", "lastSignInAt": "2026-06-26T00:00:00Z"}
        mock_requests.request.return_value = _mock_response(200, [user])

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.find_user_by_email("alice@example.com")

        assert result is not None
        assert result["lastSignInAt"] == "2026-06-26T00:00:00Z"

    @patch("logto_management_skill.client.requests")
    def test_find_user_by_email_not_found(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        mock_requests.request.return_value = _mock_response(200, [])

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.find_user_by_email("nobody@example.com")

        assert result is None

    @patch("logto_management_skill.client.requests")
    def test_delete_user_dry_run_does_not_call_delete(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        user = {"id": "u1", "primaryEmail": "alice@example.com", "name": "Alice"}
        mock_requests.request.return_value = _mock_response(200, [user])

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.delete_user("alice@example.com")

        assert result["dry_run"] is True
        assert result["action"] == "delete_user"
        assert result["user"] == user
        assert "--execute" in result["execute_command"]
        assert mock_requests.request.call_count == 1
        assert mock_requests.request.call_args[0][0] == "GET"

    @patch("logto_management_skill.client.requests")
    def test_delete_user_execute_calls_delete(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        user = {"id": "u1", "primaryEmail": "alice@example.com"}
        mock_requests.request.side_effect = [
            _mock_response(200, [user]),
            _mock_response(204, text=""),
        ]

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.delete_user("alice@example.com", execute=True)

        assert result["deleted"] is True
        assert result["user"] == user
        delete_call = mock_requests.request.call_args_list[1]
        assert delete_call[0][0] == "DELETE"
        assert delete_call[0][1] == "https://auth.example.com/api/users/u1"

    @patch("logto_management_skill.client.requests")
    def test_delete_user_not_found(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        mock_requests.request.return_value = _mock_response(200, [])

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        with pytest.raises(LogtoAPIError, match="User 'nobody@example.com' not found"):
            client.delete_user("nobody@example.com", execute=True)


# ── Role tests ──────────────────────────────────────────


class TestRoles:
    @patch("logto_management_skill.client.requests")
    def test_create_role_success(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        role = {"id": "r1", "name": "admin", "description": "Admin access"}
        mock_requests.request.return_value = _mock_response(201, role)

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.create_role("admin", description="Admin access")

        assert result["id"] == "r1"

    @patch("logto_management_skill.client.requests")
    def test_list_roles(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        roles = [{"id": "r1", "name": "admin"}, {"id": "r2", "name": "user"}]
        mock_requests.request.return_value = _mock_response(200, roles)

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.list_roles()

        assert len(result) == 2

    @patch("logto_management_skill.client.requests")
    def test_assign_role_success(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        roles = [{"id": "r1", "name": "admin"}]
        user = {"id": "u1", "primaryEmail": "alice@example.com"}

        mock_requests.request.side_effect = [
            _mock_response(200, roles),    # list_roles (find by name)
            _mock_response(200, [user]),   # find_user_by_email
            _mock_response(201, {"assigned": True}),  # assign
        ]

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.assign_role_to_user("admin", "alice@example.com")

        assert result["assigned"] is True

    @patch("logto_management_skill.client.requests")
    def test_assign_role_already_assigned(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        roles = [{"id": "r1", "name": "admin"}]
        user = {"id": "u1", "primaryEmail": "alice@example.com"}

        mock_requests.request.side_effect = [
            _mock_response(200, roles),
            _mock_response(200, [user]),
            _mock_response(409, text="already assigned"),
        ]

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.assign_role_to_user("admin", "alice@example.com")

        assert result["assigned"] is True
        assert result.get("already") is True

    @patch("logto_management_skill.client.requests")
    def test_assign_role_not_found(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        mock_requests.request.return_value = _mock_response(200, [])

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        with pytest.raises(LogtoAPIError, match="Role 'nonexistent' not found"):
            client.assign_role_to_user("nonexistent", "alice@example.com")

    @patch("logto_management_skill.client.requests")
    def test_revoke_role(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        roles = [{"id": "r1", "name": "admin"}]
        user = {"id": "u1", "primaryEmail": "alice@example.com"}

        mock_requests.request.side_effect = [
            _mock_response(200, roles),
            _mock_response(200, [user]),
            _mock_response(204, text=""),
        ]

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.revoke_role_from_user("admin", "alice@example.com")

        assert result["revoked"] is True

    @patch("logto_management_skill.client.requests")
    def test_get_role_users(self, mock_requests):
        mock_requests.post.return_value = _mock_token_response()
        roles = [{"id": "r1", "name": "admin"}]
        users = [{"id": "u1", "primaryEmail": "alice@example.com"}]

        mock_requests.request.side_effect = [
            _mock_response(200, roles),
            _mock_response(200, users),
        ]

        client = LogtoClient("https://auth.example.com", "id", "secret", tenant_id="t1")
        result = client.get_role_users("admin")

        assert len(result) == 1
        assert result[0]["primaryEmail"] == "alice@example.com"


# ── Error transparency ─────────────────────────────────


class TestErrors:
    def test_error_preserves_status_and_body(self):
        err = LogtoAPIError(404, "role not found", "/api/roles/xxx")
        assert err.status_code == 404
        assert err.response_body == "role not found"
        assert err.url == "/api/roles/xxx"
        assert "404" in str(err)
        assert "role not found" in str(err)
