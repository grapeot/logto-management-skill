# RFC: Logto Management Skill v2

## Status

Implemented in v0.2.0. The approved command contract is in `interface_design.md`; the evidence behind the design is in `expansion_design.md`.

## Architecture

```text
logto-mgmt <group> <verb>
        -> LogtoClient.<namespace>.<verb>()
        -> LogtoClient.request()
        -> token cache + one 401 retry + structured errors
        -> Logto Management API
```

CLI groups and Python namespaces are isomorphic. For example, `logto-mgmt app create` maps to `client.apps.create()` and `logto-mgmt email-template backup` maps to `client.email_templates.backup()`.

## Credentials And Tenant Resolution

The package does not call 1Password. `op run --env-file .env -- ...` resolves `op://` references before Python starts. `LogtoClient.from_env()` reads:

- `LOGTO_ENDPOINT`
- `LOGTO_APP_ID`
- `LOGTO_APP_SECRET`
- `LOGTO_TENANT_ID`, required only for custom domains

For `*.logto.app` endpoints, the tenant ID and Management API resource indicator are derived from the hostname. A custom domain without a tenant ID fails before the first token request and tells the operator to use the Management API indicator in Logto Console.

Logto exposes only one Management API scope, `all`. Endpoint-level least privilege is unavailable. Isolation therefore depends on dedicated M2M applications, secret references instead of plaintext, independent credential rotation, and this package's write guards.

## HTTP And Errors

`LogtoClient.request()` is the public long-tail HTTP API. It returns decoded JSON, `None` for an empty body, or a raw `requests.Response` when `raw=True`. It caches the M2M token and retries exactly once after a 401.

`LogtoAPIError` preserves:

```text
status_code   HTTP status
code          Logto business error code, when present
message       Logto message or a fallback
body          Complete decoded response body
url           Request URL
```

## Endpoint Discovery

`client.api` caches `GET /api/swagger.json` for the process lifetime. `search()` matches method, path, and summary. `schema()` resolves local OpenAPI references for parameters, request bodies, and responses. `call()` allows GET immediately and returns a dry-run for every other method unless `execute=True`.

The Swagger comes from the tenant itself, not from a bundled API version. This avoids path guessing and follows the tenant's deployed Logto version.

## Protected Configuration Writes

Sign-in experience, account center, and email connector configuration use whole-object or whole-subtree replacement semantics. Every namespace write runs this sequence internally:

1. GET the complete current object.
2. Deep-copy it.
3. Apply the local mutation to the copy.
4. Write a versioned backup before any network mutation.
5. PATCH the complete writable object or connector config.
6. GET again and verify that the expected state is present.

The public `request()` method blocks direct writes to `/api/sign-in-exp`, `/api/account-center`, and `/api/connectors/{id}`. `api call --execute` uses that same public path and cannot bypass the block. Only guarded namespaces can access the private write outlet.

Backups default to `.logto-backups/`, which is gitignored. The directory uses mode `0700`; files use `0600` and are atomically replaced after fsync. An artifact records schema version, resource type, a non-reversible tenant fingerprint, and the complete pre-write object. Email restore rejects malformed artifacts, other resource types, other tenants, and connector ID mismatches before PATCH.

There is intentionally no `--no-backup` option. The final implementation follows the stronger safety invariant rather than offering a bypass.

## Dry-Run Model

The following operations require explicit execution:

- Direct non-GET API calls
- User deletion
- Application deletion and URI replacement
- Email template edits and restore
- User MFA verification deletion
- Role revocation
- Organization MFA policy changes

Dry-run results identify the target, explain the risk, and include an `execute_command`. Create and additive operations execute immediately. Sign-in experience and account center writes execute immediately but are protected by mandatory backup, read-modify-write, and verification.

## Pagination And Resolution

Collection namespaces request pages of 100 until a short page is returned. Name-or-ID resolution scans the complete collection. Snapshot export uses the same paginated methods, preventing silent first-page truncation.

## Snapshots

Snapshot export aggregates applications, resources with scopes, roles, sign-in experience, account center, connector summaries, template content hashes, and user count. It never stores email template content. Diff ignores the volatile snapshot timestamp and normalizes collections by stable identifiers before comparison.

## Doctor

`doctor` distinguishes unresolved `op://` references, missing tenant ID, invalid credentials, missing Management API role, and other probe failures. It obtains a token and probes four read-only endpoints. A failed diagnosis exits non-zero.

## Testing

The default pytest suite replaces all HTTP calls with mocks. Tests assert the five safety invariants directly, including request call lists and operation order. No default test reaches a real tenant. Any opt-in live suite is restricted to read-only operations.

## Non-Goals

- The end-user Account API under `/api/my-account/*` is not wrapped.
- The package is not a Logto Console replacement.
- Long-tail endpoints are discovered and called through `api`; exhaustive wrappers are not a goal.
