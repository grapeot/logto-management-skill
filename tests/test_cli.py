from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from logto_management_skill import LogtoAPIError
from logto_management_skill.cli import build_parser, main


def test_parser_covers_every_group():
    parser = build_parser()
    commands = [
        ["api", "search", "mfa"],
        ["sign-in-exp", "get"],
        ["account-center", "get"],
        ["app", "list"],
        ["email-template", "list"],
        ["snapshot", "dump"],
        ["resource", "list"],
        ["role", "list"],
        ["user", "find", "alice@example.com"],
        ["user-mfa", "list", "alice@example.com"],
        ["org", "list"],
        ["doctor"],
    ]
    assert [parser.parse_args(command).command for command in commands] == [command[0] for command in commands]


def test_parser_covers_every_verb():
    parser = build_parser()
    commands = [
        ["api", "schema", "GET", "/api/users"],
        ["api", "call", "GET", "/api/users"],
        ["sign-in-exp", "set-mfa", "--policy", "Mandatory"],
        ["sign-in-exp", "set-passkey", "--enable"],
        ["sign-in-exp", "set-branding", "--logo-url", "https://example.com/logo.png"],
        ["account-center", "enable"], ["account-center", "disable"],
        ["account-center", "set-fields", "--field", "email=ReadOnly"],
        ["account-center", "set-webauthn-origins", "--origin", "https://example.com"],
        ["app", "get", "app-id"], ["app", "create", "Example", "--type", "SPA"],
        ["app", "update-uris", "app-id", "--add-redirect", "https://example.com/callback"],
        ["app", "delete", "app-id"], ["email-template", "get", "SignIn"],
        ["email-template", "backup"], ["email-template", "restore", "backup.json"],
        ["email-template", "set", "SignIn", "--subject", "Welcome"],
        ["email-template", "replace-text", "--find", "old", "--replace", "new"],
        ["email-template", "append-html", "--html-file", "footer.html", "--after-marker", "<hr>", "--usage-type", "SignIn"],
        ["snapshot", "diff", "old.json"], ["resource", "get", "resource-id"],
        ["resource", "create", "API", "--indicator", "https://api.example.com"],
        ["resource", "scope", "add", "API", "read"], ["role", "get", "admin"],
        ["role", "create", "admin"], ["role", "assign", "admin", "alice@example.com"],
        ["role", "revoke", "admin", "alice@example.com"], ["role", "users", "admin"],
        ["role", "add-scope", "admin", "API", "read"],
        ["user", "create", "alice@example.com"], ["user", "delete", "alice@example.com"],
        ["user-mfa", "delete", "alice@example.com", "verification-id"],
        ["org", "create", "Admins"], ["org", "add-member", "Admins", "alice@example.com"],
        ["org", "set-mfa-policy", "Admins", "--policy", "Mandatory"],
    ]
    for command in commands:
        parser.parse_args(command)


@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_cli_outputs_json_and_routes_namespace(from_env, capsys):
    client = MagicMock()
    client.api.search.return_value = [{"method": "GET", "path": "/api/users"}]
    from_env.return_value = client
    assert main(["api", "search", "users"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["path"] == "/api/users"
    client.api.search.assert_called_once_with("users")


@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_cli_error_json_has_stable_fields(from_env, capsys):
    client = MagicMock()
    client.roles.list.side_effect = LogtoAPIError(403, {"code": "forbidden", "message": "Denied"}, "https://example.com/api/roles")
    from_env.return_value = client
    assert main(["role", "list"]) == 1
    error = json.loads(capsys.readouterr().err)
    assert error == {"error": "Denied", "error_type": "LogtoAPIError", "status_code": 403, "code": "forbidden"}


@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_email_write_cli_dry_run_never_calls_namespace(from_env):
    client = MagicMock()
    from_env.return_value = client
    assert main(["email-template", "replace-text", "--find", "old", "--replace", "new"]) == 0
    assert client.email_templates.mock_calls == []


@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_doctor_failure_returns_nonzero(from_env, capsys):
    client = MagicMock()
    client.doctor.run.return_value = {"ok": False, "classification": "missing_management_api_role"}
    from_env.return_value = client
    assert main(["doctor"]) == 1
    assert json.loads(capsys.readouterr().err)["classification"] == "missing_management_api_role"
