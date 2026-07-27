# Working Log

## Changelog

### 2026-07-27

- Added guarded application access-control get/set-role commands with full dry-run payloads, non-role rule preservation, verification, and enable-last ordering.
- Made application creation dry-run by default with explicit `--execute`.
- Removed Logto's deprecated internal `secret` field from application and snapshot output.
- Blocked direct API writes from bypassing application access-control safeguards.
- Verified the complete offline suite: 43 passed, 2 opt-in live tests skipped.

### 2026-07-25

- Released the v2 clean-slate library contract: public parsed-JSON `request()`, structured `LogtoAPIError.code`, `from_env()`, and CLI-isomorphic namespaces.
- Added tenant Swagger discovery through `api search`, `api schema`, and guarded `api call`.
- Added applications, resources/scopes, sign-in experience, account center, email templates, snapshots, user MFA recovery, organizations, and `doctor`.
- Enforced non-bypassable read/deep-copy/backup/PATCH/re-read verification for sign-in experience, account center, and email connector writes.
- Added versioned owner-only email connector backups with tenant and connector identity checks before restore.
- Added dry-run defaults for destructive operations and tests that inspect the complete mock request call list.
- Expanded the fully mocked suite to cover the five documented safety invariants, pagination, discovery, restore isolation, and doctor failure classes.
- Removed the temporary implementation handoff because it contained tenant-specific context unsuitable for a public repository.
- Updated README, RFC, onboarding routing, and the canonical agent skill for v2.

### 2026-06-26

- Project scaffolded: AGENTS.md, .gitignore, .env.example, pyproject.toml
- PRD, RFC, test.md written
- Core library (LogtoClient) implemented: token management, user ops, role ops
- CLI implemented: 7 subcommands
- Unit tests written and passing
- Privacy review passed

## Lessons Learned

### Logto `lastSignInAt` field semantics (2026-06-26)

Verified with a newly created test user that never logged in:
- `lastSignInAt: null` for users who have never signed in
- `lastSignInAt: <epoch_ms>` for users who have signed in at least once
- Field is a system field on the user object, readable via `GET /api/users/{id}` or `GET /api/users?search.primaryEmail=...`

This makes it a reliable signal for "has this invitee ever logged in" — useful for reputation/invitation quality tracking in downstream systems.

### Delete user exposed with two-phase guard (2026-06-26)

`DELETE /api/users/{id}` works (returns 204). The CLI now exposes `user delete <email>` with dry-run as the default behavior and `--execute` as the explicit deletion path. The dry-run response includes the full user preview, a natural-language AI warning, and the exact execute command.

This preserves CLI ergonomics for cleanup work while keeping destructive behavior explicit. Tests cover dry-run lookup-only behavior, execute behavior, and not-found errors.

### Protected writes must be blocked at the public HTTP boundary (2026-07-25)

A guarded convenience method is insufficient if `client.request()` or `api call --execute` can still PATCH the same whole-object endpoint. v2 blocks direct writes to sign-in experience, account center, and connector endpoints in the public HTTP path. Only the internal guarded flow can reach them.

### Backups are secret-bearing operational artifacts (2026-07-25)

Restoring a connector requires its complete configuration, which may include SMTP credentials. Backups therefore use a gitignored directory, `0700` directory permissions, `0600` file permissions, atomic writes, and tenant/connector identity checks. They are recovery artifacts, not ordinary configuration snapshots.
