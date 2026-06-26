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

Verified by creating a test user (`test-guestpass@example.com`) that never logged in:
- `lastSignInAt: null` for users who have never signed in
- `lastSignInAt: <epoch_ms>` for users who have signed in at least once
- Field is a system field on the user object, readable via `GET /api/users/{id}` or `GET /api/users?search.primaryEmail=...`

This makes it a reliable signal for "has this invitee ever logged in" — useful for reputation/invitation quality tracking in downstream systems.

### Role name: superlinear_admin (2026-06-26)

The Logto role is named `superlinear_admin` (not `guest_pass_admin`) because it is intended as a general-purpose admin role across Superlinear Academy systems, not specific to guest_pass.

### Delete user not exposed in CLI (2026-06-26)

`DELETE /api/users/{id}` works (returns 204), but delete is not exposed as a CLI subcommand. It's a destructive operation that should be intentional. For testing, we called `client._request("DELETE", ...)` directly. If needed in the future, add `user delete <email>` with a confirmation flag.