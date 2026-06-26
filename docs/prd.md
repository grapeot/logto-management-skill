# PRD — Logto Management Skill

## Goal

A CLI and Python library that lets AI agents and humans manage Logto users and roles via the Logto Management API. Public, installable, 1Password-native.

## Users

1. **AI agents** (primary): receive the skill file, install via `uv pip install`, run CLI commands or import the library. JSON output for machine consumption.
2. **Human operators** (secondary): run CLI commands from a terminal with 1Password interactive approval (Touch ID).

## Features

### CLI-exposed (user-facing)

| Command | Purpose |
|---------|---------|
| `logto-mgmt role create <name> [--description <desc>]` | Create a Logto role |
| `logto-mgmt role list` | List all roles |
| `logto-mgmt role assign <role> <email>` | Assign a role to a user (by email lookup) |
| `logto-mgmt role revoke <role> <email>` | Remove a role from a user |
| `logto-mgmt role users <role>` | List users who have a given role |
| `logto-mgmt user find <email>` | Look up a user by email, return full object (including `lastSignInAt`) |
| `logto-mgmt user create <email> [--name <name>]` | Create a passwordless user |

### Library-only (not in CLI)

| Function | Why not in CLI |
|----------|----------------|
| `update_user(user_id, patch)` | Internal use by migration scripts; many context-specific fields |
| `fetch_all_emails()` | Bulk operation; 10k+ emails make terminal output useless |
| `get_access_token()` | Infrastructure; token is a means, not a user goal |
| Token 401 auto-refresh | Internal robustness logic |

### Scripts (preserved from existing logto_management)

| Script | Purpose |
|--------|---------|
| `migrate.py` | Bulk migrate users from CSV to Logto |
| `sync_plan.py` | Incremental sync: diff two CSV exports, plan + execute |

## Success Criteria

1. `logto-mgmt role create/assign/revoke` works against a real Logto tenant
2. `logto-mgmt user find` returns `lastSignInAt` field for reputation tracking
3. Token management handles 401 expiry transparently (auto-refresh + retry once)
4. Credentials resolve via 1Password `op run` (service account or interactive)
5. All public files contain zero real emails, keys, or tenant IDs
6. `pytest` passes with mocked HTTP (no live Logto calls required)

## Non-goals

- Not an SSO provider or OIDC client (Logto itself handles that)
- Not a user migration platform (migration scripts are utilities, not the core product)
- Not a Logto Console replacement (admin UI stays in Logto's web console)
- No organization management in v1 (roles are sufficient for guest_pass admin auth)