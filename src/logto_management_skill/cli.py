from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
from typing import Any, Callable, List, Optional

from .client import LogtoAPIError, LogtoClient


def _build_client() -> LogtoClient:
    return LogtoClient.from_env()


def _output(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _run(function: Callable[[], Any], *, result_failure: bool = False) -> int:
    try:
        result = function()
        if result_failure and isinstance(result, dict) and not result.get("ok", False):
            print(json.dumps(result, indent=2, default=str), file=sys.stderr)
            return 1
        _output(result)
        return 0
    except LogtoAPIError as error:
        print(
            json.dumps(
                {
                    "error": error.message,
                    "error_type": type(error).__name__,
                    "status_code": error.status_code,
                    "code": error.code,
                }
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "status_code": None,
                    "code": None,
                }
            ),
            file=sys.stderr,
        )
        return 1


def _key_values(values: list[str] | None) -> dict[str, str]:
    result = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"Expected key=value, got: {value}")
        key, item = value.split("=", 1)
        result[key] = item
    return result


def _json_input(args: argparse.Namespace) -> Any:
    if getattr(args, "json_file", None):
        return json.loads(Path(args.json_file).read_text())
    if getattr(args, "json_text", None):
        return json.loads(args.json_text)
    return None


def _dry_write(action: str, command: str, affected: Any = None) -> dict:
    result = {
        "dry_run": True,
        "action": action,
        "warning": "This changes tenant-wide configuration. Review the input before executing.",
        "execute_command": command,
    }
    if affected is not None:
        result["affected"] = affected
    return result


def _add_execute(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--execute", action="store_true", help="Perform the write instead of returning a dry-run preview")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logto-mgmt",
        description="Safely inspect and manage a Logto tenant via the Management API.",
    )
    groups = parser.add_subparsers(dest="command", required=True)

    api = groups.add_parser("api", help="Discover and call Management API endpoints")
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_search = api_sub.add_parser("search")
    api_search.add_argument("keywords", nargs="+")
    api_schema = api_sub.add_parser("schema")
    api_schema.add_argument("method")
    api_schema.add_argument("path")
    api_call = api_sub.add_parser("call")
    api_call.add_argument("method")
    api_call.add_argument("path")
    api_call.add_argument("--params", action="append")
    api_json = api_call.add_mutually_exclusive_group()
    api_json.add_argument("--json", dest="json_text")
    api_json.add_argument("--json-file")
    _add_execute(api_call)

    sign = groups.add_parser("sign-in-exp", help="Sign-in experience configuration")
    sign_sub = sign.add_subparsers(dest="sign_command", required=True)
    sign_get = sign_sub.add_parser("get")
    sign_get.add_argument("--section", default="all", choices=["signIn", "mfa", "passkey", "branding", "password", "all"])
    sign_get.add_argument("--full", action="store_true")
    sign_mfa = sign_sub.add_parser("set-mfa")
    sign_mfa.add_argument("--policy", required=True, choices=["NoPrompt", "UserControlled", "Mandatory"])
    sign_mfa.add_argument("--factor", action="append")
    sign_passkey = sign_sub.add_parser("set-passkey")
    passkey_state = sign_passkey.add_mutually_exclusive_group(required=True)
    passkey_state.add_argument("--enable", action="store_true")
    passkey_state.add_argument("--disable", action="store_true")
    sign_passkey.add_argument("--show-button", action="store_true", default=None)
    sign_passkey.add_argument("--allow-autofill", action="store_true", default=None)
    sign_branding = sign_sub.add_parser("set-branding")
    sign_branding.add_argument("--logo-url")
    sign_branding.add_argument("--favicon-url")

    account = groups.add_parser("account-center", help="Account center configuration")
    account_sub = account.add_subparsers(dest="account_command", required=True)
    account_sub.add_parser("get")
    account_sub.add_parser("enable")
    account_sub.add_parser("disable")
    account_fields = account_sub.add_parser("set-fields")
    account_fields.add_argument("--field", action="append", required=True)
    account_origins = account_sub.add_parser("set-webauthn-origins")
    account_origins.add_argument("--origin", action="append", required=True)

    app = groups.add_parser("app", help="Application management")
    app_sub = app.add_subparsers(dest="app_command", required=True)
    app_list = app_sub.add_parser("list")
    app_list.add_argument("--type")
    app_get = app_sub.add_parser("get")
    app_get.add_argument("name_or_id")
    app_create = app_sub.add_parser("create")
    app_create.add_argument("name")
    app_create.add_argument("--type", required=True)
    app_create.add_argument("--redirect-uri", action="append")
    app_create.add_argument("--post-logout-uri", action="append")
    app_create.add_argument("--description")
    _add_execute(app_create)
    app_uris = app_sub.add_parser("update-uris")
    app_uris.add_argument("name_or_id")
    app_uris.add_argument("--add-redirect", action="append")
    app_uris.add_argument("--remove-redirect", action="append")
    app_uris.add_argument("--add-post-logout", action="append")
    app_uris.add_argument("--remove-post-logout", action="append")
    _add_execute(app_uris)
    app_delete = app_sub.add_parser("delete")
    app_delete.add_argument("name_or_id")
    _add_execute(app_delete)
    app_access = app_sub.add_parser("access-control")
    app_access_sub = app_access.add_subparsers(dest="app_access_command", required=True)
    app_access_get = app_access_sub.add_parser("get")
    app_access_get.add_argument("name_or_id")
    app_access_role = app_access_sub.add_parser("set-role")
    app_access_role.add_argument("name_or_id")
    app_access_role.add_argument("role")
    _add_execute(app_access_role)

    email = groups.add_parser("email-template", help="Email template management")
    email_sub = email.add_subparsers(dest="email_command", required=True)
    email_sub.add_parser("list")
    email_get = email_sub.add_parser("get")
    email_get.add_argument("usage_type")
    email_get.add_argument("--out")
    email_backup = email_sub.add_parser("backup")
    email_backup.add_argument("--out")
    email_restore = email_sub.add_parser("restore")
    email_restore.add_argument("backup_file")
    _add_execute(email_restore)
    email_set = email_sub.add_parser("set")
    email_set.add_argument("usage_type")
    email_set.add_argument("--subject")
    email_set.add_argument("--content-file")
    _add_execute(email_set)
    email_replace = email_sub.add_parser("replace-text")
    email_replace.add_argument("--find", required=True)
    email_replace.add_argument("--replace", required=True)
    email_replace.add_argument("--usage-type", action="append")
    _add_execute(email_replace)
    email_append = email_sub.add_parser("append-html")
    email_append.add_argument("--html-file", required=True)
    email_append.add_argument("--after-marker", required=True)
    email_append.add_argument("--usage-type", action="append", required=True)
    _add_execute(email_append)

    snapshot = groups.add_parser("snapshot", help="Tenant snapshots and diffs")
    snapshot_sub = snapshot.add_subparsers(dest="snapshot_command", required=True)
    snapshot_dump = snapshot_sub.add_parser("dump")
    snapshot_dump.add_argument("--out")
    snapshot_dump.add_argument("--markdown")
    snapshot_diff = snapshot_sub.add_parser("diff")
    snapshot_diff.add_argument("old")
    snapshot_diff.add_argument("new", nargs="?")

    resource = groups.add_parser("resource", help="API resources and scopes")
    resource_sub = resource.add_subparsers(dest="resource_command", required=True)
    resource_sub.add_parser("list")
    resource_get = resource_sub.add_parser("get")
    resource_get.add_argument("name_or_id")
    resource_create = resource_sub.add_parser("create")
    resource_create.add_argument("name")
    resource_create.add_argument("--indicator", required=True)
    resource_create.add_argument("--ttl", type=int, default=3600)
    scope = resource_sub.add_parser("scope")
    scope_sub = scope.add_subparsers(dest="scope_command", required=True)
    scope_add = scope_sub.add_parser("add")
    scope_add.add_argument("resource")
    scope_add.add_argument("scope")
    scope_add.add_argument("--description")

    role = groups.add_parser("role", help="Role management")
    role_sub = role.add_subparsers(dest="role_command", required=True)
    role_sub.add_parser("list")
    role_get = role_sub.add_parser("get")
    role_get.add_argument("name_or_id")
    role_create = role_sub.add_parser("create")
    role_create.add_argument("name")
    role_create.add_argument("--description", "-d")
    role_assign = role_sub.add_parser("assign")
    role_assign.add_argument("role")
    role_assign.add_argument("email")
    role_revoke = role_sub.add_parser("revoke")
    role_revoke.add_argument("role")
    role_revoke.add_argument("email")
    _add_execute(role_revoke)
    role_users = role_sub.add_parser("users")
    role_users.add_argument("role")
    role_scope = role_sub.add_parser("add-scope")
    role_scope.add_argument("role")
    role_scope.add_argument("resource")
    role_scope.add_argument("scope")

    user = groups.add_parser("user", help="User management")
    user_sub = user.add_subparsers(dest="user_command", required=True)
    user_find = user_sub.add_parser("find")
    user_find.add_argument("email")
    user_create = user_sub.add_parser("create")
    user_create.add_argument("email")
    user_create.add_argument("--name", "-n")
    user_delete = user_sub.add_parser("delete")
    user_delete.add_argument("email")
    _add_execute(user_delete)

    user_mfa = groups.add_parser("user-mfa", help="Administrator-side user MFA recovery")
    user_mfa_sub = user_mfa.add_subparsers(dest="user_mfa_command", required=True)
    user_mfa_list = user_mfa_sub.add_parser("list")
    user_mfa_list.add_argument("email")
    user_mfa_delete = user_mfa_sub.add_parser("delete")
    user_mfa_delete.add_argument("email")
    user_mfa_delete.add_argument("verification_id")
    _add_execute(user_mfa_delete)

    org = groups.add_parser("org", help="Organization management")
    org_sub = org.add_subparsers(dest="org_command", required=True)
    org_sub.add_parser("list")
    org_create = org_sub.add_parser("create")
    org_create.add_argument("name")
    org_create.add_argument("--description")
    org_member = org_sub.add_parser("add-member")
    org_member.add_argument("org")
    org_member.add_argument("email")
    org_mfa = org_sub.add_parser("set-mfa-policy")
    org_mfa.add_argument("org")
    org_mfa.add_argument("--policy", required=True)
    _add_execute(org_mfa)

    groups.add_parser("doctor", help="Check credentials, tenant ID, and Management API access")
    return parser


def _dispatch(client: LogtoClient, args: argparse.Namespace) -> Any:
    if args.command == "api":
        if args.api_command == "search":
            return client.api.search(*args.keywords)
        if args.api_command == "schema":
            return client.api.schema(args.method, args.path)
        params = _key_values(args.params)
        body = _json_input(args)
        if args.method.upper() != "GET" and not args.execute:
            return _dry_write(
                "api_call",
                args._execute_command,
                {"method": args.method.upper(), "path": args.path, "params": params, "json": body},
            )
        return client.api.call(args.method, args.path, params=params, json=body, execute=args.execute)

    if args.command == "sign-in-exp":
        if args.sign_command == "get":
            return client.sign_in_exp.get(args.section, full=args.full)
        if args.sign_command == "set-mfa":
            return client.sign_in_exp.set_mfa(args.policy, args.factor)
        if args.sign_command == "set-passkey":
            return client.sign_in_exp.set_passkey(args.enable, show_button=args.show_button, allow_autofill=args.allow_autofill)
        return client.sign_in_exp.set_branding(logo_url=args.logo_url, favicon_url=args.favicon_url)

    if args.command == "account-center":
        if args.account_command == "get":
            return client.account_center.get()
        if args.account_command == "enable":
            return client.account_center.enable()
        if args.account_command == "disable":
            return client.account_center.disable()
        if args.account_command == "set-fields":
            return client.account_center.set_fields(_key_values(args.field))
        return client.account_center.set_webauthn_origins(args.origin)

    if args.command == "app":
        if args.app_command == "list":
            return client.apps.list(args.type)
        if args.app_command == "get":
            return client.apps.get(args.name_or_id)
        if args.app_command == "create":
            return client.apps.create(args.name, type=args.type, redirect_uris=args.redirect_uri, post_logout_uris=args.post_logout_uri, description=args.description, execute=args.execute)
        if args.app_command == "update-uris":
            return client.apps.update_uris(args.name_or_id, add_redirect=args.add_redirect, remove_redirect=args.remove_redirect, add_post_logout=args.add_post_logout, remove_post_logout=args.remove_post_logout, execute=args.execute)
        if args.app_command == "access-control":
            if args.app_access_command == "get":
                return client.apps.access_control.get(args.name_or_id)
            return client.apps.access_control.set_role(
                args.name_or_id, args.role, execute=args.execute
            )
        return client.apps.delete(args.name_or_id, execute=args.execute)

    if args.command == "email-template":
        if args.email_command == "list":
            return client.email_templates.list()
        if args.email_command == "get":
            template = client.email_templates.get(args.usage_type)
            if args.out:
                Path(args.out).write_text(template.get("content") or "")
                return {"written": args.out, "usageType": args.usage_type}
            return template
        if args.email_command == "backup":
            return client.email_templates.backup(args.out)
        if args.email_command == "restore":
            return client.email_templates.restore(args.backup_file, execute=args.execute)
        if not args.execute:
            affected = {
                "usage_type": getattr(args, "usage_type", None),
                "find": getattr(args, "find", None),
                "after_marker": getattr(args, "after_marker", None),
            }
            return _dry_write(
                f"email_template_{args.email_command.replace('-', '_')}",
                args._execute_command,
                affected,
            )
        if args.email_command == "set":
            content = Path(args.content_file).read_text() if args.content_file else None
            return client.email_templates.set(args.usage_type, subject=args.subject, content=content, execute=True)
        if args.email_command == "replace-text":
            return client.email_templates.replace_text(args.find, args.replace, usage_types=args.usage_type, execute=True)
        return client.email_templates.append_html(Path(args.html_file).read_text(), args.after_marker, usage_types=args.usage_type, execute=True)

    if args.command == "snapshot":
        if args.snapshot_command == "dump":
            data = client.snapshot.dump()
            if args.out:
                Path(args.out).write_text(json.dumps(data, indent=2) + "\n")
            if args.markdown:
                Path(args.markdown).write_text("# Logto Tenant Snapshot\n\n```json\n" + json.dumps(data, indent=2) + "\n```\n")
            return {"snapshot": data, "json_file": args.out, "markdown_file": args.markdown} if args.out or args.markdown else data
        old = json.loads(Path(args.old).read_text())
        new = json.loads(Path(args.new).read_text()) if args.new else None
        return client.snapshot.diff(old, new)

    if args.command == "resource":
        if args.resource_command == "list":
            return client.resources.list()
        if args.resource_command == "get":
            return client.resources.get(args.name_or_id)
        if args.resource_command == "create":
            return client.resources.create(args.name, args.indicator, args.ttl)
        return client.resources.scopes.add(args.resource, args.scope, args.description)

    if args.command == "role":
        if args.role_command == "list":
            return client.roles.list()
        if args.role_command == "get":
            return client.roles.get(args.name_or_id)
        if args.role_command == "create":
            return client.roles.create(args.name, args.description)
        if args.role_command == "assign":
            return client.roles.assign(args.role, args.email)
        if args.role_command == "revoke":
            return client.roles.revoke(args.role, args.email, execute=args.execute)
        if args.role_command == "users":
            return client.roles.users(args.role)
        return client.roles.add_scope(args.role, args.resource, args.scope)

    if args.command == "user":
        if args.user_command == "find":
            return client.users.find(args.email) or {"found": False}
        if args.user_command == "create":
            return client.users.create(args.email, args.name)
        return client.users.delete(args.email, execute=args.execute)

    if args.command == "user-mfa":
        if args.user_mfa_command == "list":
            return client.user_mfa.list(args.email)
        return client.user_mfa.delete(args.email, args.verification_id, execute=args.execute)

    if args.command == "org":
        if args.org_command == "list":
            return client.orgs.list()
        if args.org_command == "create":
            return client.orgs.create(args.name, args.description)
        if args.org_command == "add-member":
            return client.orgs.add_member(args.org, args.email)
        return client.orgs.set_mfa_policy(args.org, args.policy, execute=args.execute)

    return client.doctor.run()


def main(argv: Optional[List[str]] = None) -> int:
    command_args = list(argv) if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(command_args)
    args._execute_command = "logto-mgmt " + shlex.join(command_args + ["--execute"])
    return _run(
        lambda: _dispatch(_build_client(), args),
        result_failure=args.command == "doctor",
    )


if __name__ == "__main__":
    raise SystemExit(main())
