# Working Log

## Changelog

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
