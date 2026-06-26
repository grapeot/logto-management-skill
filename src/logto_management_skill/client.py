from __future__ import annotations

import base64
import re
from typing import Any

import requests


class LogtoAPIError(Exception):
    """Preserves HTTP status code and response body for AI agent debugging."""

    def __init__(self, status_code: int, response_body: str, url: str):
        self.status_code = status_code
        self.response_body = response_body
        self.url = url
        super().__init__(
            f"Logto API {status_code} at {url}: {response_body[:200]}"
        )


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _base_url(endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip("/")
    if "://" in endpoint:
        return endpoint
    return f"https://{endpoint}.logto.app"


def _resource(base: str, tenant_id: str | None) -> str:
    if "logto.app" in base:
        return base + "/api"
    if tenant_id:
        return f"https://{tenant_id}.logto.app/api"
    raise LogtoAPIError(
        0,
        "Custom domain requires LOGTO_TENANT_ID. Set it in your .env or pass tenant_id to LogtoClient.",
        "token",
    )


class LogtoClient:
    """Client for the Logto Management API.

    Token is fetched on first use and cached in memory.
    On 401, the token is invalidated and the request is retried once.
    """

    def __init__(
        self,
        endpoint: str,
        app_id: str,
        app_secret: str,
        tenant_id: str | None = None,
    ):
        self._endpoint = endpoint.strip()
        self._app_id = app_id
        self._app_secret = app_secret
        self._tenant_id = tenant_id
        self._base = _base_url(self._endpoint)
        self._token: str | None = None

    # ── Token ──────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token:
            return self._token
        base = self._base
        resource = _resource(base, self._tenant_id)
        token_url = base + "/oidc/token"
        basic = base64.b64encode(
            f"{self._app_id}:{self._app_secret}".encode()
        ).decode()
        resp = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "resource": resource,
                "scope": "all",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
            timeout=30,
        )
        if not resp.ok:
            raise LogtoAPIError(resp.status_code, resp.text, token_url)
        self._token = resp.json()["access_token"]
        return self._token

    def _invalidate_token(self) -> None:
        self._token = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        _retry: bool = True,
    ) -> requests.Response:
        url = self._base.rstrip("/") + path
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = requests.request(
            method, url, params=params, json=json_body, headers=headers, timeout=30
        )
        if resp.status_code == 401 and _retry:
            self._invalidate_token()
            return self._request(
                method, path, params=params, json_body=json_body, _retry=False
            )
        return resp

    # ── Users ──────────────────────────────────────────────

    def create_user(self, email: str, name: str | None = None) -> dict:
        """Create a passwordless user. 409/422 = already exists, return existing user."""
        payload: dict[str, Any] = {"primaryEmail": email}
        if name:
            payload["name"] = name
        resp = self._request("POST", "/api/users", json_body=payload)
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code in (400, 409, 422):
            existing = self.find_user_by_email(email)
            if existing:
                return existing
        raise LogtoAPIError(resp.status_code, resp.text, resp.url)

    def find_user_by_email(self, email: str) -> dict | None:
        """Find a user by exact email match. Returns None if not found."""
        resp = self._request(
            "GET",
            "/api/users",
            params={
                "search.primaryEmail": email,
                "mode.primaryEmail": "exact",
                "page_size": 1,
            },
        )
        if not resp.ok:
            raise LogtoAPIError(resp.status_code, resp.text, resp.url)
        data = resp.json()
        users = data if isinstance(data, list) else data.get("data", data)
        if users:
            return users[0]
        return None

    def delete_user(self, email: str, execute: bool = False) -> dict:
        """Delete a user by email. Dry-run by default; pass execute=True to delete."""
        user = self.find_user_by_email(email)
        if not user:
            raise LogtoAPIError(404, f"User '{email}' not found", "/api/users")

        if not execute:
            return {
                "dry_run": True,
                "action": "delete_user",
                "user": user,
                "warning": (
                    f"This operation will permanently delete the Logto user {email}. "
                    "This cannot be undone. If you are an AI agent, verify that you "
                    "have explicit human authorization for this specific deletion before "
                    "running with --execute."
                ),
                "execute_command": f"logto-mgmt user delete {email} --execute",
            }

        user_id = user["id"]
        resp = self._request("DELETE", f"/api/users/{user_id}")
        if resp.status_code in (200, 204):
            return {"deleted": True, "user": user}
        raise LogtoAPIError(resp.status_code, resp.text, resp.url)

    def update_user(self, user_id: str, patch: dict) -> dict:
        """PATCH a user's fields. Library-only (not CLI-exposed)."""
        resp = self._request("PATCH", f"/api/users/{user_id}", json_body=patch)
        if resp.status_code == 200:
            return resp.json()
        raise LogtoAPIError(resp.status_code, resp.text, resp.url)

    def fetch_all_emails(self) -> set[str]:
        """Fetch all user emails (paginated). Library-only."""
        emails: set[str] = set()
        page = 1
        page_size = 100
        while True:
            resp = self._request(
                "GET", "/api/users", params={"page": page, "page_size": page_size}
            )
            if not resp.ok:
                raise LogtoAPIError(resp.status_code, resp.text, resp.url)
            data = resp.json()
            users = data if isinstance(data, list) else data.get("data", data)
            if not users:
                break
            for u in users:
                email = (u.get("primaryEmail") or "").strip()
                if email:
                    emails.add(email.lower())
            if len(users) < page_size:
                break
            page += 1
        return emails

    # ── Roles ──────────────────────────────────────────────

    def create_role(self, name: str, description: str | None = None) -> dict:
        """Create a Logto role."""
        payload: dict[str, Any] = {"name": name}
        if description:
            payload["description"] = description
        resp = self._request("POST", "/api/roles", json_body=payload)
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 400:
            existing = self._find_role_by_name(name)
            if existing:
                return existing
        raise LogtoAPIError(resp.status_code, resp.text, resp.url)

    def list_roles(self) -> list[dict]:
        """List all roles."""
        resp = self._request("GET", "/api/roles")
        if not resp.ok:
            raise LogtoAPIError(resp.status_code, resp.text, resp.url)
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", data)

    def _find_role_by_name(self, name: str) -> dict | None:
        roles = self.list_roles()
        for r in roles:
            if r.get("name") == name:
                return r
        return None

    def assign_role_to_user(self, role_name: str, email: str) -> dict:
        """Assign a role to a user. Both resolved by name/email."""
        role = self._find_role_by_name(role_name)
        if not role:
            raise LogtoAPIError(404, f"Role '{role_name}' not found", "/api/roles")
        user = self.find_user_by_email(email)
        if not user:
            raise LogtoAPIError(404, f"User '{email}' not found", "/api/users")
        role_id = role["id"]
        user_id = user["id"]
        resp = self._request(
            "POST",
            f"/api/roles/{role_id}/users",
            json_body={"userIds": [user_id]},
        )
        if resp.status_code in (200, 201, 204):
            return {"role": role_name, "user": email, "assigned": True}
        if resp.status_code == 409:
            return {"role": role_name, "user": email, "assigned": True, "already": True}
        raise LogtoAPIError(resp.status_code, resp.text, resp.url)

    def revoke_role_from_user(self, role_name: str, email: str) -> dict:
        """Remove a role from a user."""
        role = self._find_role_by_name(role_name)
        if not role:
            raise LogtoAPIError(404, f"Role '{role_name}' not found", "/api/roles")
        user = self.find_user_by_email(email)
        if not user:
            raise LogtoAPIError(404, f"User '{email}' not found", "/api/users")
        role_id = role["id"]
        user_id = user["id"]
        resp = self._request(
            "DELETE",
            f"/api/roles/{role_id}/users",
            json_body={"userIds": [user_id]},
        )
        if resp.status_code in (200, 204):
            return {"role": role_name, "user": email, "revoked": True}
        raise LogtoAPIError(resp.status_code, resp.text, resp.url)

    def get_role_users(self, role_name: str) -> list[dict]:
        """List users who have a given role."""
        role = self._find_role_by_name(role_name)
        if not role:
            raise LogtoAPIError(404, f"Role '{role_name}' not found", "/api/roles")
        role_id = role["id"]
        resp = self._request("GET", f"/api/roles/{role_id}/users")
        if not resp.ok:
            raise LogtoAPIError(resp.status_code, resp.text, resp.url)
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", data)
