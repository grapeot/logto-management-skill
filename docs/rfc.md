# RFC — Logto Management Skill

## Architecture

```text
User / AI Agent
  -> scripts/run_cli.sh (op run --env-file .env --)
  -> logto-mgmt CLI (argparse, JSON output)
  -> LogtoClient (core library)
      -> token cache + 401 auto-refresh
      -> Logto Management API (REST, Bearer token)
```

## Credential Resolution

The CLI never touches 1Password directly. Credentials are resolved before the Python process starts:

1. `.env` contains `op://your-vault/your-item/field` references
2. `op run --env-file .env -- python -m ...` resolves all references into real env vars
3. If `OP_SERVICE_ACCOUNT_TOKEN` is set → automatic resolution (no UI prompt)
4. If not set → 1Password prompts for Touch ID / password per vault access
5. The Python code just reads `os.environ["LOGTO_ENDPOINT"]` etc.

This means the library code is credential-agnostic. The same code runs in CI (service account) and on a laptop (interactive approval).

## Core Library: LogtoClient

```python
class LogtoClient:
    def __init__(self, endpoint, app_id, app_secret, tenant_id=None): ...

    # Token
    def _get_token(self) -> str: ...
    def _refresh_if_needed(self) -> None: ...  # called on 401

    # Users
    def create_user(self, email, name=None) -> dict: ...
    def find_user_by_email(self, email) -> dict | None: ...
    def update_user(self, user_id, patch: dict) -> dict: ...  # library only
    def fetch_all_emails(self) -> set[str]: ...  # library only

    # Roles
    def create_role(self, name, description=None) -> dict: ...
    def list_roles(self) -> list[dict]: ...
    def assign_role_to_user(self, role_name, email) -> dict: ...
    def revoke_role_from_user(self, role_name, email) -> dict: ...
    def get_role_users(self, role_name) -> list[dict]: ...
```

### Token Management

- Token is fetched on first API call and cached in memory (`_token`, `_token_acquired_at`)
- On any 401 response: invalidate cache, re-fetch token, retry the request once
- If retry also fails, raise the error with full HTTP status + response body
- No proactive expiry tracking (Logto tokens don't expose `expires_in` reliably); 401-driven refresh is sufficient

### Error Handling

All API errors preserve the original HTTP response for AI agent debugging:

```python
class LogtoAPIError(Exception):
    def __init__(self, status_code: int, response_body: str, url: str):
        self.status_code = status_code
        self.response_body = response_body
        self.url = url
        super().__init__(f"Logto API {status_code} at {url}: {response_body[:200]}")
```

Idempotent operations: `create_user` treats 409/422 as "already exists" and returns the existing user. `assign_role_to_user` treats 409 as "already assigned".

### Custom Domain Support

Logto tenants with custom domains (e.g. `auth.example.com`) require a `tenant_id` to construct the correct resource URI for token requests. The library handles this:

- If endpoint contains `logto.app` → resource = `{base}/api`
- If endpoint is a custom domain and `tenant_id` is provided → resource = `https://{tenant_id}.logto.app/api`
- If custom domain without `tenant_id` → raise with a clear message

## CLI Design

```
logto-mgmt <subcommand> [options]
```

All output is JSON to stdout. Errors go to stderr as JSON: `{"error": "...", "status_code": N, "response": "..."}`.

```
logto-mgmt role create <name> [--description <desc>]
logto-mgmt role list
logto-mgmt role assign <role_name> <email>
logto-mgmt role revoke <role_name> <email>
logto-mgmt role users <role_name>
logto-mgmt user find <email>
logto-mgmt user create <email> [--name <name>]
logto-mgmt user delete <email>           # dry-run by default
logto-mgmt user delete <email> --execute # actual deletion
```

`role assign` / `revoke` accept role by name (not ID) and user by email (not ID). The library resolves names to IDs internally. `role users` also accepts role by name.

### Two-phase delete

`user delete` is destructive. Without `--execute`, it returns a preview:

```json
{
  "dry_run": true,
  "action": "delete_user",
  "user": {
    "id": "abc123",
    "primaryEmail": "alice@example.com",
    "name": "Alice"
  },
  "warning": "This operation will permanently delete the Logto user alice@example.com. This cannot be undone. If you are an AI agent, verify that you have explicit human authorization for this specific deletion before running with --execute.",
  "execute_command": "logto-mgmt user delete alice@example.com --execute"
}
```

With `--execute`, the deletion is performed and the result is returned:

```json
{
  "deleted": true,
  "user": {
    "id": "abc123",
    "primaryEmail": "alice@example.com"
  }
}
```

The library method `delete_user(email)` accepts an `execute: bool = False` parameter. When `execute=False`, it looks up the user and returns the preview dict without calling the DELETE endpoint. When `execute=True`, it calls `DELETE /api/users/{id}`.

## Testing Strategy

- All tests mock `requests` via `unittest.mock.patch`
- No live Logto API calls in the test suite
- Coverage targets:
  - Token acquisition and 401 refresh
  - Custom domain resource construction (with and without tenant_id)
  - Role CRUD (create, list, assign, revoke, get users)
  - User operations (create with idempotent 409, find by email, create passwordless, delete dry-run + execute)
  - CLI argument parsing and JSON output
  - Error transparency (status code + body preserved)
- Optional live integration tests behind a flag (`LOGTO_LIVE_TESTS=1`), not run by default