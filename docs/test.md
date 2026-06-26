# Test Strategy

## Unit Tests (default, no live API)

All tests mock `requests.post` and `requests.get` via `unittest.mock`. No Logto tenant needed.

| Module | What's tested |
|--------|---------------|
| `test_client_token` | Token acquisition, custom domain resource construction, 401 auto-refresh + retry |
| `test_client_users` | create_user (success + 409 idempotent), find_user_by_email (found + not found), create passwordless, delete dry-run, delete execute, delete not found |
| `test_client_roles` | create_role, list_roles, assign (success + 409), revoke, get_role_users |
| `test_client_errors` | LogtoAPIError preserves status_code + response_body + url |
| `test_cli` | Argument parsing for all subcommands, JSON output format, stderr on error |

## Live Integration Tests (opt-in)

Set `LOGTO_LIVE_TESTS=1` and provide real credentials via `.env`. These hit a real Logto tenant. Not run by default.

## What counts as "done"

- `pytest` exits 0
- No `requests.post` or `requests.get` call reaches a real server in the default suite
- `user delete` without `--execute` only performs lookup and never calls the DELETE endpoint
