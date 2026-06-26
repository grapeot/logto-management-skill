from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from .client import LogtoAPIError, LogtoClient


def _build_client() -> LogtoClient:
    endpoint = os.environ.get("LOGTO_ENDPOINT")
    app_id = os.environ.get("LOGTO_APP_ID")
    app_secret = os.environ.get("LOGTO_APP_SECRET")
    tenant_id = os.environ.get("LOGTO_TENANT_ID")

    missing = []
    if not endpoint:
        missing.append("LOGTO_ENDPOINT")
    if not app_id:
        missing.append("LOGTO_APP_ID")
    if not app_secret:
        missing.append("LOGTO_APP_SECRET")
    if missing:
        print(
            json.dumps(
                {
                    "error": f"Missing env vars: {', '.join(missing)}. "
                    "Set them in .env and run via: op run --env-file .env -- logto-mgmt ..."
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    return LogtoClient(endpoint, app_id, app_secret, tenant_id)


def _output(data) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, default=str))
    else:
        print(json.dumps({"result": str(data)}, indent=2))


def _run(func) -> int:
    try:
        result = func()
        _output(result)
        return 0
    except LogtoAPIError as e:
        print(
            json.dumps(
                {
                    "error": str(e),
                    "status_code": e.status_code,
                    "response": e.response_body[:500],
                }
            ),
            file=sys.stderr,
        )
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logto-mgmt",
        description="Manage Logto users and roles via the Management API.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── role ───────────────────────────────────────────────
    role = sub.add_parser("role", help="Role management")
    role_sub = role.add_subparsers(dest="role_command", required=True)

    role_create = role_sub.add_parser("create", help="Create a role")
    role_create.add_argument("name", help="Role name")
    role_create.add_argument("--description", "-d", default=None, help="Role description")

    role_sub.add_parser("list", help="List all roles")

    role_assign = role_sub.add_parser("assign", help="Assign a role to a user")
    role_assign.add_argument("role_name", help="Role name")
    role_assign.add_argument("email", help="User email")

    role_revoke = role_sub.add_parser("revoke", help="Remove a role from a user")
    role_revoke.add_argument("role_name", help="Role name")
    role_revoke.add_argument("email", help="User email")

    role_users = role_sub.add_parser("users", help="List users with a role")
    role_users.add_argument("role_name", help="Role name")

    # ── user ───────────────────────────────────────────────
    user = sub.add_parser("user", help="User management")
    user_sub = user.add_subparsers(dest="user_command", required=True)

    user_find = user_sub.add_parser("find", help="Find a user by email")
    user_find.add_argument("email", help="User email")

    user_create = user_sub.add_parser("create", help="Create a passwordless user")
    user_create.add_argument("email", help="User email")
    user_create.add_argument("--name", "-n", default=None, help="User display name")

    user_delete = user_sub.add_parser(
        "delete", help="Delete a user by email; dry-run by default"
    )
    user_delete.add_argument("email", help="User email")
    user_delete.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete the user. Without this flag, only returns a dry-run preview.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = _build_client()

    if args.command == "role":
        if args.role_command == "create":
            return _run(lambda: client.create_role(args.name, args.description))
        elif args.role_command == "list":
            return _run(lambda: client.list_roles())
        elif args.role_command == "assign":
            return _run(lambda: client.assign_role_to_user(args.role_name, args.email))
        elif args.role_command == "revoke":
            return _run(lambda: client.revoke_role_from_user(args.role_name, args.email))
        elif args.role_command == "users":
            return _run(lambda: client.get_role_users(args.role_name))

    elif args.command == "user":
        if args.user_command == "find":
            return _run(lambda: client.find_user_by_email(args.email) or {"found": False})
        elif args.user_command == "create":
            return _run(lambda: client.create_user(args.email, args.name))
        elif args.user_command == "delete":
            return _run(lambda: client.delete_user(args.email, execute=args.execute))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
