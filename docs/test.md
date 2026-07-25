# Test Strategy

## Principles

**The default suite is fully mocked.** No test in the default run may reach a real server. This matters more in v2 than v1: the new command groups mutate tenant-wide configuration, so an accidental live call could wipe email templates or flip an MFA policy.

**Safety invariants are tested as first-class behaviour.** The guardrails (dry-run defaults, auto-backup, read-modify-write) are the reason this tool is safe to hand to an agent, so each one gets an explicit test rather than being assumed.

## Unit Tests (default, no live API)

All tests mock `requests` via `unittest.mock`. No Logto tenant needed.

| Module | What's tested |
|---|---|
| `test_client_core` | Token acquisition; custom-domain resource construction; tenant-id derivation from `*.logto.app`; the explicit error when a custom domain lacks a tenant id; 401 auto-refresh + single retry |
| `test_client_request` | `request()` returns parsed JSON for dict and list bodies; returns `None` for an empty body; `raw=True` returns the `Response`; non-2xx raises |
| `test_client_errors` | `LogtoAPIError` preserves `status_code`, `code`, `message`, `body`, `url`; `code` is extracted from the Logto error payload and is `None` when absent |
| `test_client_users` | create (success + 409 idempotent), find by email (found + missing), passwordless create, delete dry-run, delete execute, delete missing |
| `test_client_roles` | create, list, assign (success + 409), revoke, list users of a role, bind scope to role |
| `test_client_apps` | list with type filter; get by name and by id; create per type with redirect URIs; add/remove redirect URIs while preserving the rest |
| `test_client_sign_in_exp` | summary projection contains the fields we care about; setting MFA policy and factors; passkey sub-flags; invalid policy values rejected before any request is sent |
| `test_client_account_center` | get; enable/disable; `set-fields` rejects values outside `Off`/`ReadOnly`/`Edit` **locally** (no request issued); WebAuthn origins replaced as a whole list |
| `test_client_email_templates` | list summary (usage type, subject, length, hash); get one; set one; `replace_text` across selected usage types; append-html at a marker; backup → restore round-trips byte-for-byte |
| `test_client_user_mfa` | list a user's factors; delete dry-run vs execute |
| `test_client_snapshot` | dump aggregates every section; templates recorded as summary+hash rather than full text; diff detects added, removed and changed values |
| `test_client_api_discovery` | `search` matches on method, path and summary against a fixture swagger; `schema` returns request/response schema; `call` refuses non-GET without confirmation |
| `test_doctor` | classifies the four failure modes: unresolved `op://` reference, bad credentials (401), missing Management API role (403), missing tenant id |
| `test_cli` | argument parsing for every group and verb; JSON on stdout; error JSON on stderr; non-zero exit on failure |

### Safety invariants (explicit tests)

These assert the guardrails hold, independent of any particular command:

1. **Dry-run never writes.** For every destructive verb, invoking it without `--execute` issues no `DELETE`/`POST`/`PATCH` — asserted by inspecting the mock's call list, not merely the return value.
2. **Config writes back up first.** Every write in `email-template` / `sign-in-exp` / `account-center` produces a backup artifact *before* the write request is issued; the ordering is asserted.
3. **Read-modify-write preserves siblings.** Editing one email template and PATCHing the connector leaves the other templates byte-identical. This is the exact failure mode the guardrail exists for.
4. **Verify-after-write.** A config write is followed by a re-read; if the re-read does not reflect the change, the command exits non-zero.
5. **Local validation precedes the network.** Invalid enum values (account-center field permissions, MFA policy) fail before any request is issued.

## Live Integration Tests (opt-in)

Set `LOGTO_LIVE_TESTS=1` with real credentials in `.env`. Never part of the default run.

Scope is deliberately limited to **read-only** verbs against a real tenant (`api search`, `sign-in-exp get`, `snapshot dump`, `doctor`). Live tests do not mutate configuration: the blast radius of a bad write is the entire tenant, and there is no staging tenant to absorb mistakes.

## Fixtures

- A trimmed `swagger.json` fixture drives the `api` group tests, so discovery is tested without a network call.
- A connector fixture containing several email templates drives the read-modify-write and sibling-preservation tests.
- All fixtures use placeholder values (`https://example.com`, `your-tenant-id`, `alice@example.com`). No real tenant id, app id, domain, or email appears anywhere in the repo.

## What counts as "done"

- `pytest` exits 0.
- No `requests` call in the default suite reaches a real server.
- The five safety invariants above have passing tests.
- A privacy scan finds no real emails, domains, tenant ids, or `op://` paths pointing at a real vault.
