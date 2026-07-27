from __future__ import annotations

from copy import deepcopy
import json


def test_users_roles_resources_and_scope_binding(client):
    user = {"id": "user-id", "primaryEmail": "alice@example.com"}
    role = {"id": "role-id", "name": "admin"}
    resource = {"id": "resource-id", "name": "Example API"}
    scope = {"id": "scope-id", "name": "read"}
    client.request.side_effect = [[role], [resource], [scope], None]
    result = client.roles.add_scope("admin", "Example API", "read")
    assert result["linked"] is True
    assert client.request.call_args_list[-1].kwargs["json"] == {"scopeIds": ["scope-id"]}

    client.request.reset_mock()
    client.request.side_effect = [[user], None]
    assert client.users.delete("alice@example.com", execute=True)["deleted"] is True


def test_apps_filter_create_update_and_delete(client):
    apps = [
        {"id": "spa-id", "name": "Web", "type": "SPA", "secret": "internal-value", "oidcClientMetadata": {"redirectUris": ["https://example.com/old"]}},
        {"id": "m2m-id", "name": "Worker", "type": "MachineToMachine", "oidcClientMetadata": {}},
    ]
    client.request.return_value = apps
    listed = client.apps.list("SPA")
    assert [item["id"] for item in listed] == ["spa-id"]
    assert "secret" not in listed[0]

    client.request.reset_mock()
    preview = client.apps.create(
        "Example",
        type="SPA",
        redirect_uris=["https://example.com/callback"],
    )
    assert preview["dry_run"] is True
    assert client.request.call_args_list == []

    client.request.return_value = {"id": "new-id", "name": "Example", "secret": "internal-value"}
    created = client.apps.create("Example", type="SPA", execute=True)
    assert created == {"id": "new-id", "name": "Example"}

    client.request.reset_mock()
    client.request.side_effect = [apps, {"id": "spa-id"}]
    client.apps.update_uris("Web", add_redirect=["https://example.com/new"], remove_redirect=["https://example.com/old"], execute=True)
    payload = client.request.call_args_list[-1].kwargs["json"]
    assert payload["oidcClientMetadata"]["redirectUris"] == ["https://example.com/new"]


def test_application_access_control_preserves_non_role_rules_and_enables_last(client):
    app = {
        "id": "spa-id",
        "name": "Web",
        "type": "SPA",
        "appLevelAccessControlEnabled": False,
        "oidcClientMetadata": {},
    }
    enabled_app = {**app, "appLevelAccessControlEnabled": True}
    role = {"id": "role-id", "name": "admin", "type": "User"}
    before = {
        "userIds": ["user-id"],
        "userRoleIds": ["old-role-id"],
        "organizationIds": ["organization-id"],
        "organizationRoleRules": [
            {"organizationId": "organization-id", "organizationRoleIds": ["organization-role-id"]}
        ],
    }
    replacement = {**before, "userRoleIds": ["role-id"]}
    client.request.side_effect = [
        [app],
        [role],
        before,
        replacement,
        replacement,
        enabled_app,
        [enabled_app],
    ]

    result = client.apps.access_control.set_role("Web", "admin", execute=True)

    assert result["updated"] is True
    calls = client.request.call_args_list
    assert calls[3].args == ("PUT", "/api/applications/spa-id/access-control")
    assert calls[3].kwargs["json"] == replacement
    assert calls[4].args == ("GET", "/api/applications/spa-id/access-control")
    assert calls[5].args == ("PATCH", "/api/applications/spa-id")
    assert calls[5].kwargs["json"] == {"appLevelAccessControlEnabled": True}
    assert calls[6].args == ("GET", "/api/applications")


def test_application_access_control_dry_run_never_writes(client):
    app = {"id": "spa-id", "name": "Web", "type": "SPA", "oidcClientMetadata": {}}
    role = {"id": "role-id", "name": "admin", "type": "User"}
    before = {
        "userIds": ["user-id"],
        "userRoleIds": [],
        "organizationIds": [],
        "organizationRoleRules": [],
    }
    client.request.side_effect = [[app], [role], before]

    result = client.apps.access_control.set_role("Web", "admin")

    assert result["dry_run"] is True
    assert result["replacement"]["userIds"] == ["user-id"]
    assert result["replacement"]["userRoleIds"] == ["role-id"]
    assert all(item.args[0] == "GET" for item in client.request.call_args_list)


def test_email_template_summary_replace_append_backup_restore(client, connector, tmp_path):
    current = deepcopy(connector)

    def side_effect(method, path, **kwargs):
        nonlocal current
        if method == "GET":
            return [deepcopy(current)]
        current["config"] = deepcopy(kwargs["json"]["config"])
        return deepcopy(current)

    client.request.side_effect = side_effect
    summaries = client.email_templates.list()
    assert summaries[0]["content_length"] > 0
    assert len(summaries[0]["content_sha256"]) == 64

    backup = client.email_templates.backup()
    original = json.loads(__import__("pathlib").Path(backup["backup"]).read_text())["data"]
    client.email_templates.replace_text("Example", "Sample", usage_types=["SignIn", "BindMfa"], execute=True)
    assert "Sample" in current["config"]["templates"][0]["content"]
    client.email_templates.append_html("<footer>Footer</footer>", "<hr>", usage_types=["SignIn"], execute=True)
    assert "<hr><footer>" in current["config"]["templates"][0]["content"]
    client.email_templates.restore(backup["backup"], execute=True)
    assert current["config"] == original["config"]


def test_snapshot_diff_detects_added_removed_changed(client):
    result = client.snapshot.diff(
        {"removed": 1, "changed": "old"},
        {"added": 2, "changed": "new"},
    )
    assert {item["type"] for item in result["changes"]} == {"added", "removed", "changed"}


def test_snapshot_diff_ignores_timestamp_and_collection_order(client):
    old = {"created_at": "2026-01-01T00:00:00Z", "roles": [{"id": "b"}, {"id": "a"}]}
    new = {"created_at": "2026-01-02T00:00:00Z", "roles": [{"id": "a"}, {"id": "b"}]}
    assert client.snapshot.diff(old, new) == {"changed": False, "changes": []}


def test_lists_paginate_until_short_page(client):
    first = [{"id": f"role-{index}", "name": f"role-{index}"} for index in range(100)]
    client.request.side_effect = [first, [{"id": "role-last", "name": "last"}]]
    roles = client.roles.list()
    assert len(roles) == 101
    assert client.request.call_args_list[-1].kwargs["params"]["page"] == 2


def test_org_and_user_mfa(client):
    org = {"id": "org-id", "name": "Admins", "isMfaRequired": False}
    user = {"id": "user-id", "primaryEmail": "alice@example.com"}
    client.request.side_effect = [[org], {**org, "isMfaRequired": True}]
    assert client.orgs.set_mfa_policy("Admins", "Mandatory", execute=True)["isMfaRequired"] is True

    client.request.reset_mock()
    client.request.side_effect = [[user], [{"id": "verification-id", "type": "TOTP"}], None]
    assert client.user_mfa.delete("alice@example.com", "verification-id", execute=True)["deleted"] is True
