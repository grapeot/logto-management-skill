from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json as json_module
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .client import LogtoClient


def _items(value: Any) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        data = value.get("data", value.get("items", []))
        return data if isinstance(data, list) else []
    return []


def _paginate(client: LogtoClient, path: str, *, params: dict | None = None) -> list[dict]:
    page = 1
    page_size = 100
    result: list[dict] = []
    while True:
        query = {**(params or {}), "page": page, "page_size": page_size}
        batch = _items(client.request("GET", path, params=query))
        result.extend(batch)
        if len(batch) < page_size:
            return result
        page += 1


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def _backup(client: LogtoClient, resource: str, data: Any) -> str:
    directory = Path(client.backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    path = directory / f"{timestamp}-{resource}.json"
    artifact = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "resource": resource,
        "source_fingerprint": hashlib.sha256(
            f"{client._base}|{client._tenant_id or ''}".encode()
        ).hexdigest(),
        "data": data,
    }
    payload = json_module.dumps(artifact, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return str(path)


def _guarded_update(
    client: LogtoClient,
    resource: str,
    read: Callable[[], dict],
    write: Callable[[dict], Any],
    mutate: Callable[[dict], None],
    *,
    expected: Callable[[dict], Any] | None = None,
) -> dict:
    before = read()
    after = deepcopy(before)
    mutate(after)
    backup_path = _backup(client, resource, before)
    write(after)
    verified = read()
    expected_value = expected(after) if expected else after
    verified_value = expected(verified) if expected else verified
    if not _contains(verified_value, expected_value):
        raise RuntimeError(
            f"Verification failed after writing {resource}; backup: {backup_path}"
        )
    return {"updated": True, "backup": backup_path, "data": verified}


@dataclass
class Namespace:
    client: LogtoClient

    def __post_init__(self) -> None:
        pass


class UsersNamespace(Namespace):
    def find(self, email: str) -> dict | None:
        result = self.client.request(
            "GET",
            "/api/users",
            params={
                "search.primaryEmail": email,
                "mode.primaryEmail": "exact",
                "page_size": 1,
            },
        )
        users = _items(result)
        return users[0] if users else None

    def get(self, user_id: str) -> dict:
        result = self.client.request("GET", f"/api/users/{user_id}")
        return result if isinstance(result, dict) else {}

    def create(self, email: str, name: str | None = None) -> dict:
        from .client import LogtoAPIError

        payload: dict[str, Any] = {"primaryEmail": email}
        if name:
            payload["name"] = name
        try:
            result = self.client.request("POST", "/api/users", json=payload)
            return result if isinstance(result, dict) else {}
        except LogtoAPIError as error:
            if error.status_code not in (400, 409, 422):
                raise
            existing = self.find(email)
            if existing:
                return existing
            raise

    def delete(self, email: str, *, execute: bool = False) -> dict:
        from .client import LogtoAPIError

        user = self.find(email)
        if not user:
            raise LogtoAPIError(404, {"message": f"User '{email}' not found"}, "/api/users")
        if not execute:
            return {
                "dry_run": True,
                "action": "delete_user",
                "user": user,
                "warning": (
                    f"This will permanently delete the Logto user {email}. Verify explicit "
                    "human authorization for this deletion before using --execute."
                ),
                "execute_command": f"logto-mgmt user delete {email} --execute",
            }
        self.client.request("DELETE", f"/api/users/{user['id']}")
        return {"deleted": True, "user": user}

    def update(self, user_id: str, patch: dict) -> dict:
        result = self.client.request("PATCH", f"/api/users/{user_id}", json=patch)
        return result if isinstance(result, dict) else {}

    def fetch_all_emails(self) -> set[str]:
        emails: set[str] = set()
        page = 1
        while True:
            users = _items(
                self.client.request(
                    "GET", "/api/users", params={"page": page, "page_size": 100}
                )
            )
            for user in users:
                if user.get("primaryEmail"):
                    emails.add(user["primaryEmail"].strip().lower())
            if len(users) < 100:
                return emails
            page += 1


class RolesNamespace(Namespace):
    def list(self) -> list[dict]:
        return _paginate(self.client, "/api/roles")

    def get(self, name_or_id: str) -> dict:
        for role in self.list():
            if role.get("id") == name_or_id or role.get("name") == name_or_id:
                return role
        from .client import LogtoAPIError

        raise LogtoAPIError(404, {"message": f"Role '{name_or_id}' not found"}, "/api/roles")

    def create(self, name: str, description: str | None = None) -> dict:
        from .client import LogtoAPIError

        payload = {"name": name}
        if description:
            payload["description"] = description
        try:
            result = self.client.request("POST", "/api/roles", json=payload)
            return result if isinstance(result, dict) else {}
        except LogtoAPIError as error:
            if error.status_code != 400:
                raise
            return self.get(name)

    def assign(self, role: str, email: str) -> dict:
        role_obj = self.get(role)
        user = self.client.users.find(email)
        if not user:
            from .client import LogtoAPIError

            raise LogtoAPIError(404, {"message": f"User '{email}' not found"}, "/api/users")
        try:
            self.client.request(
                "POST", f"/api/roles/{role_obj['id']}/users", json={"userIds": [user["id"]]}
            )
        except Exception as error:
            from .client import LogtoAPIError

            if not isinstance(error, LogtoAPIError) or error.status_code != 409:
                raise
            return {"role": role_obj, "user": user, "assigned": True, "already": True}
        return {"role": role_obj, "user": user, "assigned": True}

    def revoke(self, role: str, email: str, *, execute: bool = False) -> dict:
        role_obj = self.get(role)
        user = self.client.users.find(email)
        if not user:
            from .client import LogtoAPIError

            raise LogtoAPIError(404, {"message": f"User '{email}' not found"}, "/api/users")
        if not execute:
            return {
                "dry_run": True,
                "action": "revoke_role",
                "role": role_obj,
                "user": user,
                "warning": "This removes access granted by the role. Confirm the intended user and role before executing.",
                "execute_command": f"logto-mgmt role revoke {role} {email} --execute",
            }
        self.client.request(
            "DELETE", f"/api/roles/{role_obj['id']}/users/{user['id']}"
        )
        return {"role": role_obj, "user": user, "revoked": True}

    def users(self, role: str) -> list[dict]:
        role_obj = self.get(role)
        return _paginate(self.client, f"/api/roles/{role_obj['id']}/users")

    def add_scope(self, role: str, resource: str, scope: str) -> dict:
        role_obj = self.get(role)
        resource_obj = self.client.resources.get(resource)
        scope_obj = self.client.resources.scopes.get(resource_obj, scope)
        self.client.request(
            "POST",
            f"/api/roles/{role_obj['id']}/scopes",
            json={"scopeIds": [scope_obj["id"]]},
        )
        return {"role": role_obj, "resource": resource_obj, "scope": scope_obj, "linked": True}


class AppsNamespace(Namespace):
    def list(self, type: str | None = None) -> list[dict]:
        apps = _paginate(self.client, "/api/applications")
        return [app for app in apps if app.get("type") == type] if type else apps

    def get(self, name_or_id: str) -> dict:
        app = next(
            (item for item in self.list() if item.get("id") == name_or_id or item.get("name") == name_or_id),
            None,
        )
        if not app:
            from .client import LogtoAPIError

            raise LogtoAPIError(404, {"message": f"Application '{name_or_id}' not found"}, "/api/applications")
        metadata = app.get("oidcClientMetadata") or {}
        return {**app, **metadata}

    def create(
        self,
        name: str,
        *,
        type: str,
        redirect_uris: list[str] | None = None,
        post_logout_uris: list[str] | None = None,
        description: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name, "type": type}
        if description:
            payload["description"] = description
        if redirect_uris is not None or post_logout_uris is not None:
            metadata: dict[str, Any] = {
                "redirectUris": redirect_uris or [],
                "postLogoutRedirectUris": post_logout_uris or [],
            }
            payload["oidcClientMetadata"] = metadata
        result = self.client.request("POST", "/api/applications", json=payload)
        return result if isinstance(result, dict) else {}

    def update_uris(
        self,
        name_or_id: str,
        *,
        add_redirect: list[str] | None = None,
        remove_redirect: list[str] | None = None,
        add_post_logout: list[str] | None = None,
        remove_post_logout: list[str] | None = None,
        execute: bool = False,
    ) -> dict:
        app = self.get(name_or_id)
        metadata = deepcopy(app.get("oidcClientMetadata") or {})

        def update(key: str, additions: list[str] | None, removals: list[str] | None) -> None:
            values = list(metadata.get(key) or [])
            for value in additions or []:
                if value not in values:
                    values.append(value)
            metadata[key] = [value for value in values if value not in (removals or [])]

        update("redirectUris", add_redirect, remove_redirect)
        update("postLogoutRedirectUris", add_post_logout, remove_post_logout)
        if not execute:
            return {
                "dry_run": True,
                "action": "update_application_uris",
                "application": app,
                "oidcClientMetadata": metadata,
                "warning": "Changing redirect URIs can break sign-in or logout flows. Review the complete replacement list before executing.",
                "execute_command": f"logto-mgmt app update-uris {name_or_id} [options] --execute",
            }
        result = self.client.request(
            "PATCH", f"/api/applications/{app['id']}", json={"oidcClientMetadata": metadata}
        )
        return result if isinstance(result, dict) else {"updated": True, "id": app["id"]}

    def delete(self, name_or_id: str, *, execute: bool = False) -> dict:
        app = self.get(name_or_id)
        if not execute:
            return {
                "dry_run": True,
                "action": "delete_application",
                "application": app,
                "warning": "This will permanently delete the Logto application. Review dependencies before executing.",
                "execute_command": f"logto-mgmt app delete {name_or_id} --execute",
            }
        self.client.request("DELETE", f"/api/applications/{app['id']}")
        return {"deleted": True, "application": app}


class ResourcesNamespace(Namespace):
    def __post_init__(self) -> None:
        self.scopes = ResourceScopesNamespace(self.client, self)

    def list(self) -> list[dict]:
        return _paginate(self.client, "/api/resources")

    def get(self, name_or_id: str) -> dict:
        for resource in self.list():
            if resource.get("id") == name_or_id or resource.get("name") == name_or_id:
                return resource
        from .client import LogtoAPIError

        raise LogtoAPIError(404, {"message": f"Resource '{name_or_id}' not found"}, "/api/resources")

    def create(self, name: str, indicator: str, ttl: int = 3600) -> dict:
        result = self.client.request(
            "POST",
            "/api/resources",
            json={"name": name, "indicator": indicator, "accessTokenTtl": ttl},
        )
        return result if isinstance(result, dict) else {}


class ResourceScopesNamespace(Namespace):
    def __init__(self, client: LogtoClient, resources: ResourcesNamespace):
        super().__init__(client)
        self.resources = resources

    def list(self, resource: str | dict) -> list[dict]:
        resource_obj = resource if isinstance(resource, dict) else self.resources.get(resource)
        return _paginate(self.client, f"/api/resources/{resource_obj['id']}/scopes")

    def get(self, resource: str | dict, scope: str) -> dict:
        for item in self.list(resource):
            if item.get("id") == scope or item.get("name") == scope:
                return item
        from .client import LogtoAPIError

        raise LogtoAPIError(404, {"message": f"Scope '{scope}' not found"}, "/api/resources")

    def add(self, resource: str, scope: str, description: str | None = None) -> dict:
        resource_obj = self.resources.get(resource)
        payload = {"name": scope}
        if description:
            payload["description"] = description
        result = self.client.request(
            "POST", f"/api/resources/{resource_obj['id']}/scopes", json=payload
        )
        return result if isinstance(result, dict) else {}


class SignInExpNamespace(Namespace):
    POLICIES = {"NoPrompt", "UserControlled", "Mandatory"}

    def _read(self) -> dict:
        result = self.client.request("GET", "/api/sign-in-exp")
        return result if isinstance(result, dict) else {}

    def get(self, section: str = "all", *, full: bool = False) -> dict:
        data = self._read()
        if full:
            return data
        methods = (data.get("signIn") or {}).get("methods") or []
        summary = {
            "signIn": {
                "identifiers": [method.get("identifier") for method in methods],
                "password_primary": any(method.get("isPasswordPrimary") for method in methods),
                "methods": methods,
            },
            "mfa": data.get("mfa"),
            "passkey": data.get("passkeySignIn"),
            "branding": data.get("branding"),
            "password": data.get("passwordPolicy"),
        }
        if section == "all":
            return summary
        if section not in summary:
            raise ValueError(f"Unknown sign-in experience section: {section}")
        return {section: summary[section]}

    def _update(self, mutate: Callable[[dict], None]) -> dict:
        return _guarded_update(
            self.client,
            "sign-in-exp",
            self._read,
            lambda value: self.client._guarded_request(
                "PATCH",
                "/api/sign-in-exp",
                json={key: item for key, item in value.items() if key != "id"},
            ),
            mutate,
        )

    def set_mfa(self, policy: str, factors: list[str] | None = None) -> dict:
        if policy not in self.POLICIES:
            raise ValueError(f"Invalid MFA policy: {policy}")

        def mutate(data: dict) -> None:
            mfa = data.setdefault("mfa", {})
            mfa["policy"] = policy
            if factors is not None:
                mfa["factors"] = factors

        return self._update(mutate)

    def set_passkey(
        self,
        enabled: bool,
        *,
        show_button: bool | None = None,
        allow_autofill: bool | None = None,
    ) -> dict:
        def mutate(data: dict) -> None:
            passkey = data.setdefault("passkeySignIn", {})
            passkey["enabled"] = enabled
            if show_button is not None:
                passkey["showPasskeyButton"] = show_button
            if allow_autofill is not None:
                passkey["allowAutofill"] = allow_autofill

        return self._update(mutate)

    def set_branding(
        self, *, logo_url: str | None = None, favicon_url: str | None = None
    ) -> dict:
        def mutate(data: dict) -> None:
            branding = data.setdefault("branding", {})
            if logo_url is not None:
                branding["logoUrl"] = logo_url
            if favicon_url is not None:
                branding["favicon"] = favicon_url

        return self._update(mutate)


class AccountCenterNamespace(Namespace):
    PERMISSIONS = {"Off", "ReadOnly", "Edit"}

    def _read(self) -> dict:
        result = self.client.request("GET", "/api/account-center")
        return result if isinstance(result, dict) else {}

    def get(self) -> dict:
        return self._read()

    def _update(self, mutate: Callable[[dict], None]) -> dict:
        return _guarded_update(
            self.client,
            "account-center",
            self._read,
            lambda value: self.client._guarded_request(
                "PATCH",
                "/api/account-center",
                json={
                    key: item
                    for key, item in value.items()
                    if key not in {"id", "tenantId"}
                },
            ),
            mutate,
        )

    def enable(self) -> dict:
        return self._update(lambda data: data.__setitem__("enabled", True))

    def disable(self) -> dict:
        return self._update(lambda data: data.__setitem__("enabled", False))

    def set_fields(self, fields: dict[str, str]) -> dict:
        invalid = {key: value for key, value in fields.items() if value not in self.PERMISSIONS}
        if invalid:
            raise ValueError(f"Invalid account-center field permissions: {invalid}")

        def mutate(data: dict) -> None:
            data.setdefault("fields", {}).update(fields)

        return self._update(mutate)

    def set_webauthn_origins(self, origins: list[str]) -> dict:
        return self._update(
            lambda data: data.__setitem__("webauthnRelatedOrigins", origins)
        )


class EmailTemplatesNamespace(Namespace):
    def _connector(self) -> dict:
        connectors = _paginate(self.client, "/api/connectors")
        matches = [
            connector
            for connector in connectors
            if isinstance(connector.get("config"), dict)
            and isinstance(connector["config"].get("templates"), list)
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one email connector with templates, found {len(matches)}")
        return matches[0]

    @staticmethod
    def _template(connector: dict, usage_type: str) -> dict:
        for template in connector["config"]["templates"]:
            if template.get("usageType") == usage_type:
                return template
        raise ValueError(f"Email template '{usage_type}' not found")

    @staticmethod
    def _summary(template: dict) -> dict:
        content = template.get("content") or ""
        return {
            "usageType": template.get("usageType"),
            "subject": template.get("subject"),
            "contentType": template.get("contentType"),
            "content_length": len(content),
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        }

    def list(self) -> list[dict]:
        return [self._summary(item) for item in self._connector()["config"]["templates"]]

    def get(self, usage_type: str) -> dict:
        return deepcopy(self._template(self._connector(), usage_type))

    def backup(self, out: str | None = None) -> dict:
        connector = self._connector()
        if out:
            original = self.client.backup_dir
            self.client.backup_dir = out
            try:
                path = _backup(self.client, "email-template", connector)
            finally:
                self.client.backup_dir = original
        else:
            path = _backup(self.client, "email-template", connector)
        return {"backup": path, "connector_id": connector["id"]}

    def _write_connector(self, connector: dict) -> Any:
        return self.client._guarded_request(
            "PATCH", f"/api/connectors/{connector['id']}", json={"config": connector["config"]}
        )

    def _update(self, mutate: Callable[[dict], None]) -> dict:
        return _guarded_update(
            self.client,
            "email-template",
            self._connector,
            self._write_connector,
            mutate,
            expected=lambda connector: connector["config"],
        )

    def restore(self, backup_file: str, *, execute: bool = False) -> dict:
        artifact = json_module.loads(Path(backup_file).read_text())
        if artifact.get("schema_version") != 1 or artifact.get("resource") != "email-template":
            raise ValueError("Not a supported email-template backup")
        fingerprint = hashlib.sha256(
            f"{self.client._base}|{self.client._tenant_id or ''}".encode()
        ).hexdigest()
        if artifact.get("source_fingerprint") != fingerprint:
            raise ValueError("Backup belongs to a different Logto tenant")
        saved = artifact["data"]
        current = self._connector()
        if saved.get("id") != current.get("id"):
            raise ValueError("Backup connector does not match the current email connector")
        if not execute:
            return {
                "dry_run": True,
                "action": "restore_email_templates",
                "backup": backup_file,
                "connector_id": saved.get("id"),
                "warning": "This restores the entire connector configuration from backup.",
                "execute_command": f"logto-mgmt email-template restore {backup_file} --execute",
            }

        def mutate(current: dict) -> None:
            current["config"] = deepcopy(saved["config"])

        return self._update(mutate)

    def set(
        self,
        usage_type: str,
        *,
        subject: str | None = None,
        content: str | None = None,
        execute: bool = False,
    ) -> dict:
        if subject is None and content is None:
            raise ValueError("At least one of subject or content is required")
        if not execute:
            template = self.get(usage_type)
            return {
                "dry_run": True,
                "action": "set_email_template",
                "template": self._summary(template),
                "changes": {"subject": subject, "content_length": len(content) if content is not None else None},
                "warning": "This replaces fields inside the shared email connector configuration.",
                "execute_command": "Repeat with execute=True or CLI --execute.",
            }
        def mutate(connector: dict) -> None:
            template = self._template(connector, usage_type)
            if subject is not None:
                template["subject"] = subject
            if content is not None:
                template["content"] = content

        return self._update(mutate)

    def replace_text(
        self,
        find: str,
        replace: str,
        *,
        usage_types: list[str] | None = None,
        execute: bool = False,
    ) -> dict:
        if not find:
            raise ValueError("find must not be empty")
        if not execute:
            connector = self._connector()
            selected = set(usage_types or [])
            available = {item.get("usageType") for item in connector["config"]["templates"]}
            missing = selected - available
            if missing:
                raise ValueError(f"Unknown email template usage types: {sorted(missing)}")
            affected = []
            for template in connector["config"]["templates"]:
                if not selected or template.get("usageType") in selected:
                    occurrences = (template.get("subject") or "").count(find) + (template.get("content") or "").count(find)
                    if occurrences:
                        affected.append({"usageType": template.get("usageType"), "occurrences": occurrences})
            return {
                "dry_run": True,
                "action": "replace_email_template_text",
                "affected": affected,
                "warning": "This replaces text inside the shared email connector configuration.",
                "execute_command": "Repeat with execute=True or CLI --execute.",
            }

        def mutate(connector: dict) -> None:
            selected = set(usage_types or [])
            available = {item.get("usageType") for item in connector["config"]["templates"]}
            missing = selected - available
            if missing:
                raise ValueError(f"Unknown email template usage types: {sorted(missing)}")
            for template in connector["config"]["templates"]:
                if not selected or template.get("usageType") in selected:
                    template["subject"] = (template.get("subject") or "").replace(find, replace)
                    template["content"] = (template.get("content") or "").replace(find, replace)

        return self._update(mutate)

    def append_html(
        self,
        html: str,
        after_marker: str,
        *,
        usage_types: list[str],
        execute: bool = False,
    ) -> dict:
        if not after_marker:
            raise ValueError("after_marker must not be empty")
        if len(usage_types) != len(set(usage_types)):
            raise ValueError("usage_types must not contain duplicates")
        if not execute:
            connector = self._connector()
            affected = []
            for usage_type in usage_types:
                template = self._template(connector, usage_type)
                if after_marker not in (template.get("content") or ""):
                    raise ValueError(f"Marker not found in {usage_type}: {after_marker}")
                affected.append(self._summary(template))
            return {
                "dry_run": True,
                "action": "append_email_template_html",
                "affected": affected,
                "warning": "This inserts HTML inside the shared email connector configuration.",
                "execute_command": "Repeat with execute=True or CLI --execute.",
            }

        def mutate(connector: dict) -> None:
            for usage_type in usage_types:
                template = self._template(connector, usage_type)
                content = template.get("content") or ""
                index = content.find(after_marker)
                if index < 0:
                    raise ValueError(f"Marker not found in {usage_type}: {after_marker}")
                end = index + len(after_marker)
                template["content"] = content[:end] + html + content[end:]

        return self._update(mutate)


class UserMfaNamespace(Namespace):
    def list(self, email: str) -> list[dict]:
        user = self.client.users.find(email)
        if not user:
            from .client import LogtoAPIError

            raise LogtoAPIError(404, {"message": f"User '{email}' not found"}, "/api/users")
        return _items(self.client.request("GET", f"/api/users/{user['id']}/mfa-verifications"))

    def delete(self, email: str, verification_id: str, *, execute: bool = False) -> dict:
        user = self.client.users.find(email)
        if not user:
            from .client import LogtoAPIError

            raise LogtoAPIError(404, {"message": f"User '{email}' not found"}, "/api/users")
        verifications = _items(
            self.client.request("GET", f"/api/users/{user['id']}/mfa-verifications")
        )
        verification = next(
            (item for item in verifications if item.get("id") == verification_id), None
        )
        if not verification:
            from .client import LogtoAPIError

            raise LogtoAPIError(404, {"message": f"MFA verification '{verification_id}' not found"}, "/api/users")
        if not execute:
            return {
                "dry_run": True,
                "action": "delete_user_mfa",
                "user": user,
                "verification": verification,
                "warning": "This removes an MFA factor from the user. Confirm the recovery request before executing.",
                "execute_command": f"logto-mgmt user-mfa delete {email} {verification_id} --execute",
            }
        self.client.request(
            "DELETE", f"/api/users/{user['id']}/mfa-verifications/{verification_id}"
        )
        return {"deleted": True, "user": user, "verification": verification}


class OrgsNamespace(Namespace):
    def list(self) -> list[dict]:
        return _paginate(self.client, "/api/organizations")

    def get(self, name_or_id: str) -> dict:
        for org in self.list():
            if org.get("id") == name_or_id or org.get("name") == name_or_id:
                return org
        from .client import LogtoAPIError

        raise LogtoAPIError(404, {"message": f"Organization '{name_or_id}' not found"}, "/api/organizations")

    def create(self, name: str, description: str | None = None) -> dict:
        payload = {"name": name}
        if description:
            payload["description"] = description
        result = self.client.request("POST", "/api/organizations", json=payload)
        return result if isinstance(result, dict) else {}

    def add_member(self, org: str, email: str) -> dict:
        org_obj = self.get(org)
        user = self.client.users.find(email)
        if not user:
            from .client import LogtoAPIError

            raise LogtoAPIError(404, {"message": f"User '{email}' not found"}, "/api/users")
        self.client.request(
            "POST", f"/api/organizations/{org_obj['id']}/users", json={"userIds": [user["id"]]}
        )
        return {"organization": org_obj, "user": user, "added": True}

    def set_mfa_policy(self, org: str, policy: str, *, execute: bool = False) -> dict:
        values = {"Mandatory": True, "NoPrompt": False, "Required": True, "NotRequired": False}
        if policy not in values:
            raise ValueError(f"Invalid organization MFA policy: {policy}")
        org_obj = self.get(org)
        if not execute:
            return {
                "dry_run": True,
                "action": "set_organization_mfa_policy",
                "organization": org_obj,
                "policy": policy,
                "warning": "Requiring MFA can block organization members who have not enrolled a factor.",
                "execute_command": f"logto-mgmt org set-mfa-policy {org} --policy {policy} --execute",
            }
        result = self.client.request(
            "PATCH", f"/api/organizations/{org_obj['id']}", json={"isMfaRequired": values[policy]}
        )
        return result if isinstance(result, dict) else {"updated": True}


class SnapshotNamespace(Namespace):
    def dump(self) -> dict:
        connectors = _paginate(self.client, "/api/connectors")
        connector_summaries = []
        for connector in connectors:
            summary = {key: connector.get(key) for key in ("id", "connectorId", "target", "name", "type")}
            templates = (connector.get("config") or {}).get("templates")
            if isinstance(templates, list):
                summary["templates"] = [EmailTemplatesNamespace._summary(item) for item in templates]
            connector_summaries.append(summary)
        resources = self.client.resources.list()
        for resource in resources:
            resource["scopes"] = self.client.resources.scopes.list(resource)
        user_response = self.client.request(
            "GET", "/api/users", params={"page": 1, "page_size": 1}, raw=True
        )
        total = user_response.headers.get("Total-Number")
        users_body = user_response.json() if user_response.text else []
        return {
            "created_at": datetime.now(UTC).isoformat(),
            "applications": self.client.apps.list(),
            "resources": resources,
            "roles": self.client.roles.list(),
            "sign_in_exp": self.client.sign_in_exp.get(full=True),
            "account_center": self.client.account_center.get(),
            "connectors": connector_summaries,
            "user_count": int(total) if total is not None else len(_items(users_body)),
        }

    def diff(self, old: dict, new: dict | None = None) -> dict:
        current = deepcopy(new if new is not None else self.dump())
        old = deepcopy(old)
        old.pop("created_at", None)
        current.pop("created_at", None)
        changes: list[dict] = []

        def normalize(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()}
            if isinstance(value, list):
                normalized = [normalize(item) for item in value]
                if all(isinstance(item, dict) for item in normalized):
                    return sorted(
                        normalized,
                        key=lambda item: str(
                            item.get("id")
                            or item.get("usageType")
                            or item.get("name")
                            or json_module.dumps(item, sort_keys=True)
                        ),
                    )
                return sorted(normalized, key=lambda item: json_module.dumps(item, sort_keys=True))
            return value

        old = normalize(old)
        current = normalize(current)

        def walk(left: Any, right: Any, path: str = "$") -> None:
            if isinstance(left, dict) and isinstance(right, dict):
                for key in sorted(left.keys() - right.keys()):
                    changes.append({"type": "removed", "path": f"{path}.{key}", "old": left[key]})
                for key in sorted(right.keys() - left.keys()):
                    changes.append({"type": "added", "path": f"{path}.{key}", "new": right[key]})
                for key in sorted(left.keys() & right.keys()):
                    walk(left[key], right[key], f"{path}.{key}")
            elif left != right:
                changes.append({"type": "changed", "path": path, "old": left, "new": right})

        walk(old, current)
        return {"changed": bool(changes), "changes": changes}


class DoctorNamespace(Namespace):
    def run(self) -> dict:
        from .client import LogtoAPIError, _resource

        credentials = (self.client._endpoint, self.client._app_id, self.client._app_secret)
        if any(value.startswith("op://") for value in credentials) or (
            self.client._tenant_id and self.client._tenant_id.startswith("op://")
        ):
            return {
                "ok": False,
                "classification": "unresolved_credentials",
                "fix": "Run through: op run --env-file .env -- logto-mgmt doctor",
            }
        try:
            _resource(self.client._base, self.client._tenant_id)
        except LogtoAPIError:
            return {
                "ok": False,
                "classification": "missing_tenant_id",
                "fix": "Set LOGTO_TENANT_ID from the Management API indicator in Logto Console.",
            }
        try:
            self.client._get_token()
        except LogtoAPIError as error:
            return {
                "ok": False,
                "classification": "wrong_credentials" if error.status_code in (400, 401) else "token_error",
                "status_code": error.status_code,
                "code": error.code,
                "fix": "Verify the M2M App ID and App Secret in Logto Console.",
            }
        probes = {}
        for path in ("/api/applications", "/api/roles", "/api/sign-in-exp", "/api/account-center"):
            try:
                self.client.request("GET", path)
                probes[path] = 200
            except LogtoAPIError as error:
                probes[path] = error.status_code
        if 403 in probes.values():
            return {
                "ok": False,
                "classification": "missing_management_api_role",
                "probes": probes,
                "fix": "Grant the built-in 'Logto Management API access' role to this M2M application.",
            }
        healthy = all(status == 200 for status in probes.values())
        return {
            "ok": healthy,
            "classification": "healthy" if healthy else "permission_probe_failed",
            "probes": probes,
            **({"fix": "Inspect the failing endpoint status and Logto tenant health."} if not healthy else {}),
        }


class ApiNamespace(Namespace):
    def __post_init__(self) -> None:
        self._swagger: dict | None = None

    def swagger(self, *, refresh: bool = False) -> dict:
        if self._swagger is None or refresh:
            result = self.client.request("GET", "/api/swagger.json")
            if not isinstance(result, dict):
                raise ValueError("Logto swagger response is not a JSON object")
            self._swagger = result
        return self._swagger

    def search(self, *keywords: str) -> list[dict]:
        terms = [keyword.lower() for keyword in keywords if keyword]
        matches: list[dict] = []
        for path, path_item in self.swagger().get("paths", {}).items():
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                summary = operation.get("summary", "")
                haystack = f"{method} {path} {summary}".lower()
                if all(term in haystack for term in terms):
                    matches.append(
                        {
                            "method": method.upper(),
                            "path": path,
                            "summary": summary,
                            "operation_id": operation.get("operationId"),
                        }
                    )
        return sorted(matches, key=lambda item: (item["path"], item["method"]))

    def schema(self, method: str, path: str) -> dict:
        method = method.lower()
        operation = self.swagger().get("paths", {}).get(path, {}).get(method)
        if operation is None:
            raise ValueError(f"No {method.upper()} operation found for {path}")
        return {
            "method": method.upper(),
            "path": path,
            "summary": operation.get("summary"),
            "parameters": self._resolve(operation.get("parameters", [])),
            "request_body": self._resolve(operation.get("requestBody")),
            "responses": self._resolve(operation.get("responses", {})),
        }

    def call(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | list | None = None,
        execute: bool = False,
    ) -> Any:
        method = method.upper()
        if method != "GET" and not execute:
            return {
                "dry_run": True,
                "action": "api_call",
                "method": method,
                "path": path,
                "params": params,
                "json": json,
                "warning": "This direct API call can change tenant data. Review the method, path, and body before executing it.",
                "execute_command": "Repeat this command with --execute.",
            }
        return self.client.request(method, path, params=params, json=json)

    def _resolve(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._resolve(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if reference and reference.startswith("#/"):
            resolved: Any = self.swagger()
            for part in reference[2:].split("/"):
                resolved = resolved[part]
            return self._resolve(resolved)
        return {key: self._resolve(item) for key, item in value.items()}
