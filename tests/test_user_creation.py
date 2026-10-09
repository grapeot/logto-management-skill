from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from logto_management_skill import LogtoAPIError
from logto_management_skill.cli import main


def test_create_passwordless_user_preserves_payload(client):
    user = {"id": "user-id", "primaryEmail": "alice@example.com"}
    client.request.return_value = user
    assert client.users.create("alice@example.com", "Alice") == user
    client.request.assert_called_once_with(
        "POST", "/api/users", json={"primaryEmail": "alice@example.com", "name": "Alice"}
    )


def test_create_password_user_sends_secret_but_does_not_return_credentials(client):
    password = "Example-password-123!"
    client.request.return_value = {
        "id": "user-id", "hasPassword": True, "password": password,
        "passwordDigest": "example-digest", "passwordAlgorithm": "Argon2i",
    }
    result = client.users.create("alice@example.com", "Alice", password=password)
    client.request.assert_called_once_with(
        "POST", "/api/users",
        json={"primaryEmail": "alice@example.com", "name": "Alice", "password": password},
    )
    assert result == {"id": "user-id", "hasPassword": True}


def test_create_does_not_redact_identifiers_matching_password_substrings(client):
    client.request.return_value = {"id": "user-id", "primaryEmail": "alice@example.com"}
    assert client.users.create("alice@example.com", password="user")["id"] == "user-id"


@pytest.mark.parametrize("password", ["", 123])
def test_invalid_password_does_not_send_request(client, password):
    with pytest.raises(ValueError, match="non-empty string"):
        client.users.create("alice@example.com", password=password)
    client.request.assert_not_called()


@pytest.mark.parametrize("status", [400, 409, 422])
def test_password_creation_failure_never_falls_back_to_existing_user(client, status):
    password = "Example-password-123!"
    client.request.side_effect = LogtoAPIError(
        status, {"code": "user_exists", "message": f"Rejected {password}", "password": password},
        "https://example.com/api/users",
    )
    with pytest.raises(LogtoAPIError) as raised:
        client.users.create("alice@example.com", password=password)
    assert raised.value.status_code == status
    assert raised.value.code == "user_exists"
    assert password not in json.dumps(raised.value.body)
    assert raised.value.message == "Rejected [REDACTED]"
    assert client.request.call_count == 1


def test_passwordless_duplicate_still_returns_existing_user(client):
    user = {"id": "existing-id", "primaryEmail": "alice@example.com"}
    client.request.side_effect = [
        LogtoAPIError(409, {"message": "Exists"}, "https://example.com/api/users"), [user],
    ]
    assert client.users.create("alice@example.com") == user
    assert [call.args[0] for call in client.request.call_args_list] == ["POST", "GET"]


@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_cli_password_file_preserves_whitespace_and_accepts_crlf(from_env, tmp_path, capsys):
    path = tmp_path / "password.txt"
    path.write_bytes(b" Example-password-123! \r\n")
    client = MagicMock()
    client.users.create.return_value = {"id": "user-id", "hasPassword": True}
    from_env.return_value = client
    assert main(["user", "create", "alice@example.com", "--password-file", str(path)]) == 0
    client.users.create.assert_called_once_with(
        "alice@example.com", None, password=" Example-password-123! "
    )
    assert json.loads(capsys.readouterr().out)["hasPassword"] is True


@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_cli_password_env(from_env, monkeypatch, capsys):
    monkeypatch.setenv("EXAMPLE_INITIAL_PASSWORD", "Example-password-123!")
    client = MagicMock()
    client.users.create.return_value = {"id": "user-id"}
    from_env.return_value = client
    assert main(["user", "create", "alice@example.com", "--name", "Alice", "--password-env", "EXAMPLE_INITIAL_PASSWORD"]) == 0
    client.users.create.assert_called_once_with(
        "alice@example.com", "Alice", password="Example-password-123!"
    )
    assert "Example-password-123!" not in capsys.readouterr().out


@pytest.mark.parametrize("contents", ["", "one\ntwo\n"])
@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_cli_rejects_invalid_password_file_before_creation(from_env, tmp_path, contents, capsys):
    path = tmp_path / "password.txt"
    path.write_text(contents)
    client = MagicMock()
    from_env.return_value = client
    assert main(["user", "create", "alice@example.com", "--password-file", str(path)]) == 1
    client.users.create.assert_not_called()
    assert json.loads(capsys.readouterr().err)["error_type"] == "ValueError"


@pytest.mark.parametrize("value", [None, ""])
@patch("logto_management_skill.cli.LogtoClient.from_env")
def test_cli_missing_or_empty_password_env_does_not_create(from_env, monkeypatch, capsys, value):
    if value is None:
        monkeypatch.delenv("EXAMPLE_INITIAL_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("EXAMPLE_INITIAL_PASSWORD", value)
    client = MagicMock()
    from_env.return_value = client
    assert main(["user", "create", "alice@example.com", "--password-env", "EXAMPLE_INITIAL_PASSWORD"]) == 1
    client.users.create.assert_not_called()
    expected = "Password environment variable is not set" if value is None else "Password must be non-empty"
    assert json.loads(capsys.readouterr().err)["error"] == expected


def test_cli_password_sources_are_mutually_exclusive():
    with pytest.raises(SystemExit) as raised:
        main(["user", "create", "alice@example.com", "--password-file", "password.txt", "--password-env", "EXAMPLE_INITIAL_PASSWORD"])
    assert raised.value.code == 2
