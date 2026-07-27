from __future__ import annotations

from copy import deepcopy
import stat
from unittest.mock import call

import pytest


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _methods(mock):
    return [item.args[0] for item in mock.call_args_list]


def test_destructive_dry_runs_never_write(client):
    user = {"id": "user-id", "primaryEmail": "alice@example.com"}
    app = {"id": "app-id", "name": "Example App", "oidcClientMetadata": {}}
    verification = {"id": "verification-id", "type": "TOTP"}

    client.request.return_value = [user]
    assert client.users.delete("alice@example.com")["dry_run"]
    assert not WRITE_METHODS.intersection(_methods(client.request))

    client.request.reset_mock()
    client.request.return_value = [app]
    assert client.apps.delete("Example App")["dry_run"]
    assert not WRITE_METHODS.intersection(_methods(client.request))

    client.request.reset_mock()
    assert client.apps.create("Example App", type="SPA")["dry_run"]
    assert not WRITE_METHODS.intersection(_methods(client.request))

    client.request.reset_mock()
    client.request.side_effect = [[user], [verification]]
    assert client.user_mfa.delete("alice@example.com", "verification-id")["dry_run"]
    assert not WRITE_METHODS.intersection(_methods(client.request))

    client.request.reset_mock()
    client.request.side_effect = [[{"id": "role-id", "name": "admin"}], [user]]
    assert client.roles.revoke("admin", "alice@example.com")["dry_run"]
    assert not WRITE_METHODS.intersection(_methods(client.request))

    client.request.reset_mock()
    client.request.side_effect = None
    client.request.return_value = [{"id": "org-id", "name": "Admins"}]
    assert client.orgs.set_mfa_policy("Admins", "Mandatory")["dry_run"]
    assert not WRITE_METHODS.intersection(_methods(client.request))


@pytest.mark.parametrize("resource", ["sign-in-exp", "account-center", "email-template"])
def test_config_writes_create_backup_before_patch(client, connector, resource):
    backup_dir = client.backup_dir

    def side_effect(method, path, **kwargs):
        if method == "PATCH":
            assert list(__import__("pathlib").Path(backup_dir).glob("*.json"))
            if resource == "email-template":
                return connector
        if resource == "sign-in-exp":
            return {"id": "sign-id", "mfa": {"policy": "Mandatory", "factors": ["Totp"], "organizationRequiredMfaPolicy": "Mandatory"}}
        if resource == "account-center":
            return {"id": "account-id", "enabled": True, "fields": {"email": "ReadOnly"}}
        return [connector]

    client.request.side_effect = side_effect
    if resource == "sign-in-exp":
        client.sign_in_exp.set_mfa("Mandatory", ["Totp"])
    elif resource == "account-center":
        client.account_center.enable()
    else:
        client.email_templates.set("SignIn", subject="Welcome to Example", execute=True)
    patch_calls = [item for item in client.request.call_args_list if item.args[0] == "PATCH"]
    assert len(patch_calls) == 1
    backup = next(__import__("pathlib").Path(backup_dir).glob("*.json"))
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_email_write_preserves_sibling_templates_byte_identical(client, connector):
    before = deepcopy(connector)
    written = None

    def side_effect(method, path, **kwargs):
        nonlocal written
        if method == "GET":
            return [before] if written is None else [{**before, "config": deepcopy(written)}]
        written = deepcopy(kwargs["json"]["config"])
        return {**before, "config": written}

    client.request.side_effect = side_effect
    client.email_templates.set("SignIn", subject="New subject", execute=True)
    assert written["templates"][1:] == before["config"]["templates"][1:]


def test_verify_after_write_rereads_and_fails_on_mismatch(client):
    before = {"enabled": False, "fields": {"email": "ReadOnly"}}
    expected_write = {"enabled": True, "fields": {"email": "ReadOnly"}}
    client.request.side_effect = [before, {}, before]
    with pytest.raises(RuntimeError, match="Verification failed"):
        client.account_center.enable()
    assert client.request.call_args_list == [
        call("GET", "/api/account-center"),
        call("PATCH", "/api/account-center", json=expected_write),
        call("GET", "/api/account-center"),
    ]


def test_local_validation_precedes_network(client):
    with pytest.raises(ValueError, match="Invalid account-center"):
        client.account_center.set_fields({"email": "Owner"})
    with pytest.raises(ValueError, match="Invalid MFA policy"):
        client.sign_in_exp.set_mfa("Sometimes")
    assert client.request.call_args_list == []


def test_public_request_and_api_cannot_bypass_protected_writes():
    from logto_management_skill import LogtoClient

    client = LogtoClient("tenant", "app-id", "app-secret")
    for path in (
        "/api/sign-in-exp",
        "/api/sign-in-exp/",
        "/api/sign-in-exp?probe=1",
        "/api/account-center",
        "/api/account-center/",
        "/api/account-center?probe=1",
        "/api/connectors/connector-id",
        "/api/applications/app-id/access-control",
    ):
        with pytest.raises(ValueError, match="Direct writes"):
            client.request("PATCH", path, json={})
        with pytest.raises(ValueError, match="Direct writes"):
            client.api.call("PATCH", path, json={}, execute=True)

    with pytest.raises(ValueError, match="Direct writes"):
        client.api.call(
            "PATCH",
            "/api/applications/app-id",
            json={"appLevelAccessControlEnabled": True},
            execute=True,
        )


def test_access_control_mismatch_does_not_enable_gate(client):
    app = {"id": "app-id", "name": "Example App", "oidcClientMetadata": {}}
    role = {"id": "role-id", "name": "admin", "type": "User"}
    before = {
        "userIds": [],
        "userRoleIds": [],
        "organizationIds": [],
        "organizationRoleRules": [],
    }
    client.request.side_effect = [[app], [role], before, {}, before]

    with pytest.raises(RuntimeError, match="gate was not enabled"):
        client.apps.access_control.set_role("Example App", "admin", execute=True)

    assert not any(
        item.args[:2] == ("PATCH", "/api/applications/app-id")
        for item in client.request.call_args_list
    )


def test_restore_rejects_backup_from_another_tenant(client, connector, tmp_path):
    artifact = {
        "schema_version": 1,
        "resource": "email-template",
        "source_fingerprint": "not-this-tenant",
        "data": connector,
    }
    path = tmp_path / "backup.json"
    path.write_text(__import__("json").dumps(artifact))
    with pytest.raises(ValueError, match="different Logto tenant"):
        client.email_templates.restore(str(path), execute=True)
    assert client.request.call_args_list == []


def test_email_library_edits_are_dry_run_by_default(client, connector):
    client.request.return_value = [connector]
    assert client.email_templates.set("SignIn", subject="New")["dry_run"]
    assert client.email_templates.replace_text("Example", "Sample")["dry_run"]
    assert client.email_templates.append_html("<footer />", "<hr>", usage_types=["SignIn"])["dry_run"]
    assert not WRITE_METHODS.intersection(_methods(client.request))
