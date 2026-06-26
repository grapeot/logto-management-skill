from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest

from logto_management_skill.cli import build_parser, main


class TestCLIParsing:
    def test_role_create(self):
        parser = build_parser()
        args = parser.parse_args(["role", "create", "admin", "--description", "Admin"])
        assert args.command == "role"
        assert args.role_command == "create"
        assert args.name == "admin"
        assert args.description == "Admin"

    def test_role_list(self):
        parser = build_parser()
        args = parser.parse_args(["role", "list"])
        assert args.role_command == "list"

    def test_role_assign(self):
        parser = build_parser()
        args = parser.parse_args(["role", "assign", "admin", "alice@example.com"])
        assert args.role_command == "assign"
        assert args.role_name == "admin"
        assert args.email == "alice@example.com"

    def test_role_revoke(self):
        parser = build_parser()
        args = parser.parse_args(["role", "revoke", "admin", "alice@example.com"])
        assert args.role_command == "revoke"

    def test_role_users(self):
        parser = build_parser()
        args = parser.parse_args(["role", "users", "admin"])
        assert args.role_command == "users"
        assert args.role_name == "admin"

    def test_user_find(self):
        parser = build_parser()
        args = parser.parse_args(["user", "find", "alice@example.com"])
        assert args.command == "user"
        assert args.user_command == "find"
        assert args.email == "alice@example.com"

    def test_user_create(self):
        parser = build_parser()
        args = parser.parse_args(["user", "create", "alice@example.com", "--name", "Alice"])
        assert args.user_command == "create"
        assert args.name == "Alice"


class TestCLIRun:
    @patch("logto_management_skill.cli.LogtoClient")
    @patch.dict("os.environ", {
        "LOGTO_ENDPOINT": "https://auth.example.com",
        "LOGTO_APP_ID": "id",
        "LOGTO_APP_SECRET": "secret",
        "LOGTO_TENANT_ID": "t1",
    })
    def test_role_list_outputs_json(self, mock_client_class):
        mock_client = mock_client_class.return_value
        mock_client.list_roles.return_value = [{"id": "r1", "name": "admin"}]

        exit_code = main(["role", "list"])

        assert exit_code == 0

    @patch("logto_management_skill.cli.LogtoClient")
    @patch.dict("os.environ", {
        "LOGTO_ENDPOINT": "https://auth.example.com",
        "LOGTO_APP_ID": "id",
        "LOGTO_APP_SECRET": "secret",
        "LOGTO_TENANT_ID": "t1",
    })
    def test_user_find_outputs_json(self, mock_client_class):
        mock_client = mock_client_class.return_value
        mock_client.find_user_by_email.return_value = {
            "id": "u1",
            "primaryEmail": "alice@example.com",
            "lastSignInAt": "2026-06-26T00:00:00Z",
        }

        exit_code = main(["user", "find", "alice@example.com"])

        assert exit_code == 0

    @patch("logto_management_skill.cli.LogtoClient")
    @patch.dict("os.environ", {
        "LOGTO_ENDPOINT": "https://auth.example.com",
        "LOGTO_APP_ID": "id",
        "LOGTO_APP_SECRET": "secret",
        "LOGTO_TENANT_ID": "t1",
    })
    def test_error_outputs_stderr(self, mock_client_class):
        from logto_management_skill.client import LogtoAPIError

        mock_client = mock_client_class.return_value
        mock_client.list_roles.side_effect = LogtoAPIError(500, "server error", "/api/roles")

        exit_code = main(["role", "list"])

        assert exit_code == 1

    def test_missing_env_vars_exits_1(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main(["role", "list"])
            assert exc_info.value.code == 1