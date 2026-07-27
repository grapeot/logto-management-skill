from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import urlparse, urlsplit

import requests


class LogtoAPIError(Exception):
    """A Logto API error with both HTTP and business-level details."""

    def __init__(self, status_code: int, body: Any, url: str):
        self.status_code = status_code
        self.body = body
        self.url = url
        self.code = body.get("code") if isinstance(body, dict) else None
        if isinstance(body, dict):
            self.message = str(body.get("message") or body.get("error_description") or body.get("error") or f"HTTP {status_code}")
        else:
            self.message = str(body or f"HTTP {status_code}")
        super().__init__(f"Logto API {status_code} at {url}: {self.message[:200]}")


def _base_url(endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip("/")
    if "://" in endpoint:
        return endpoint
    return f"https://{endpoint}.logto.app"


def _tenant_from_base(base: str) -> str | None:
    hostname = urlparse(base).hostname or ""
    suffix = ".logto.app"
    if hostname.endswith(suffix):
        tenant_id = hostname[: -len(suffix)]
        return tenant_id or None
    return None


def _resource(base: str, tenant_id: str | None) -> str:
    derived = _tenant_from_base(base)
    if derived:
        return f"https://{derived}.logto.app/api"
    if tenant_id:
        return f"https://{tenant_id}.logto.app/api"
    raise LogtoAPIError(
        0,
        {
            "code": "tenant_id.required",
            "message": (
                "A custom Logto domain requires LOGTO_TENANT_ID. Find the tenant ID "
                "in Logto Console under the Logto Management API indicator, then set "
                "LOGTO_TENANT_ID or pass tenant_id to LogtoClient."
            ),
        },
        "token",
    )


def _response_body(response: requests.Response) -> Any:
    if not response.text:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


class LogtoClient:
    """Client for the Logto Management API.

    Tokens are fetched lazily, cached in memory, and refreshed once after a 401.
    Resource namespaces mirror the CLI command groups.
    """

    def __init__(
        self,
        endpoint: str,
        app_id: str,
        app_secret: str,
        tenant_id: str | None = None,
        *,
        backup_dir: str = ".logto-backups",
    ):
        if not endpoint or not app_id or not app_secret:
            raise ValueError("endpoint, app_id, and app_secret are required")
        self._endpoint = endpoint.strip()
        self._app_id = app_id
        self._app_secret = app_secret
        self._tenant_id = tenant_id
        self._base = _base_url(self._endpoint)
        self._token: str | None = None
        self.backup_dir = backup_dir

        from .namespaces import (
            AccountCenterNamespace,
            ApiNamespace,
            AppsNamespace,
            DoctorNamespace,
            EmailTemplatesNamespace,
            OrgsNamespace,
            ResourcesNamespace,
            RolesNamespace,
            SignInExpNamespace,
            SnapshotNamespace,
            UserMfaNamespace,
            UsersNamespace,
        )

        self.users = UsersNamespace(self)
        self.roles = RolesNamespace(self)
        self.apps = AppsNamespace(self)
        self.resources = ResourcesNamespace(self)
        self.sign_in_exp = SignInExpNamespace(self)
        self.account_center = AccountCenterNamespace(self)
        self.email_templates = EmailTemplatesNamespace(self)
        self.user_mfa = UserMfaNamespace(self)
        self.orgs = OrgsNamespace(self)
        self.snapshot = SnapshotNamespace(self)
        self.api = ApiNamespace(self)
        self.doctor = DoctorNamespace(self)

    @classmethod
    def from_env(cls, **kwargs: Any) -> LogtoClient:
        names = ("LOGTO_ENDPOINT", "LOGTO_APP_ID", "LOGTO_APP_SECRET")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError(
                f"Missing env vars: {', '.join(missing)}. Set them in .env and run "
                "through 'op run --env-file .env -- ...'."
            )
        return cls(
            os.environ["LOGTO_ENDPOINT"],
            os.environ["LOGTO_APP_ID"],
            os.environ["LOGTO_APP_SECRET"],
            os.environ.get("LOGTO_TENANT_ID"),
            **kwargs,
        )

    def _get_token(self) -> str:
        if self._token:
            return self._token
        resource = _resource(self._base, self._tenant_id)
        token_url = self._base + "/oidc/token"
        basic = base64.b64encode(f"{self._app_id}:{self._app_secret}".encode()).decode()
        response = requests.post(
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
        body = _response_body(response)
        if not response.ok:
            raise LogtoAPIError(response.status_code, body, token_url)
        if not isinstance(body, dict) or not body.get("access_token"):
            raise LogtoAPIError(502, {"message": "Token endpoint returned no access_token", "response": body}, token_url)
        self._token = str(body["access_token"])
        return self._token

    def _invalidate_token(self) -> None:
        self._token = None

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | list | None = None,
        headers: dict | None = None,
        raw: bool = False,
        _retry: bool = True,
    ) -> dict | list | str | None | requests.Response:
        """Call a Management API endpoint and return its parsed response body."""
        return self._send(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
            raw=raw,
            _retry=_retry,
            allow_protected_write=False,
        )

    def _guarded_request(
        self,
        method: str,
        path: str,
        *,
        json: dict | list,
    ) -> dict | list | str | None | requests.Response:
        return self._send(method, path, json=json, allow_protected_write=True)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | list | None = None,
        headers: dict | None = None,
        raw: bool = False,
        _retry: bool = True,
        allow_protected_write: bool = False,
    ) -> dict | list | str | None | requests.Response:
        method = method.upper()
        path = path if path.startswith("/") else f"/{path}"
        canonical_path = urlsplit(path).path.rstrip("/") or "/"
        protected = canonical_path in {"/api/sign-in-exp", "/api/account-center"} or canonical_path.startswith(
            "/api/connectors/"
        )
        application_access_control = canonical_path.startswith("/api/applications/") and (
            canonical_path.endswith("/access-control")
            or (
                isinstance(json, dict)
                and "appLevelAccessControlEnabled" in json
            )
        )
        protected = protected or application_access_control
        if method in {"POST", "PUT", "PATCH", "DELETE"} and protected and not allow_protected_write:
            raise ValueError(
                f"Direct writes to {path} are blocked. Use the matching guarded "
                "configuration namespace."
            )
        url = self._base + path
        request_headers = {"Authorization": f"Bearer {self._get_token()}"}
        if json is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        response = requests.request(
            method,
            url,
            params=params,
            json=json,
            headers=request_headers,
            timeout=30,
        )
        if response.status_code == 401 and _retry:
            self._invalidate_token()
            return self._send(
                method,
                path,
                params=params,
                json=json,
                headers=headers,
                raw=raw,
                _retry=False,
                allow_protected_write=allow_protected_write,
            )
        if not response.ok:
            raise LogtoAPIError(response.status_code, _response_body(response), response.url)
        if raw:
            return response
        return _response_body(response)
