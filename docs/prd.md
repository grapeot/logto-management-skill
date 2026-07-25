# PRD — Logto Management Skill

## Goal

A CLI and Python library that lets AI agents (and humans) **safely read and change any configuration in a Logto tenant, with recovery when something goes wrong**. Public, installable, 1Password-native credential handling.

v1 covered only users and roles. v2 widens the scope to *configuring a tenant* — because real-world use showed that for every configuration task (applications, sign-in experience, MFA policy, account center, email templates) the skill was no help at all, and the operator had to bypass the wrapper with ad-hoc inline scripts. Evidence: `expansion_design.md`. Interface: `interface_design.md`.

## Users

1. **AI agents (primary)**: receive the skill file → install → run CLI or import the library. JSON output for machine consumption.
2. **Human operators (secondary)**: run commands in a terminal with 1Password interactive approval (Touch ID).

## Why breaking changes are acceptable

Consumers are almost exclusively agents, and usage is described by the skill doc — **change the interface, update the doc, and callers follow automatically**. So v2 makes no backward-compatibility compromises (`_request` → `request`, `json_body` → `json`; no aliases retained).

## Features

### First-run onboarding

The skill doc carries a trigger rule: when credentials are missing or permissions are insufficient, follow `docs/onboarding.md` to walk the user through creating an M2M application and granting it access — rather than retrying blindly.

**Creating the M2M application requires Console access, so the agent cannot bootstrap itself**; a human must do it. That human-in-the-loop sequence is written down so every agent handles it the same way — in particular, so no agent asks the user to paste the App Secret into the chat.

One verified fact the guide must state plainly: **the Logto Management API resource exposes exactly one scope, `all`** — access is all-or-nothing, with no per-endpoint granularity. "Least privilege" therefore has to be achieved by other means: credential hygiene (references, never plaintext), one dedicated M2M app per consumer (so it can be revoked independently), and the skill's own guardrails.

### Command groups

| Group | Purpose | Priority |
|---|---|---|
| `api` | Endpoint discovery (swagger search) and safe direct calls | P0 |
| `sign-in-exp` | Sign-in experience, MFA policy, passkey, branding | P0 |
| `account-center` | Account self-service config (field permissions, WebAuthn origins) | P0 |
| `app` | Application CRUD, redirect URI management | P0 |
| `email-template` | Template read/write, bulk text replacement, backup/restore | P0 (highest risk) |
| `doctor` | Credential/permission self-check (verification step for onboarding) | P0 |
| `snapshot` | Config snapshot export and diff | P1 |
| `resource` / `role` | API resources, scopes, role-to-scope binding | P1 |
| `user` / `user-mfa` | User CRUD, admin-side MFA operations | P1 |
| `org` | Organizations and organization-level MFA policy | P1 |

Full command signatures: `interface_design.md` §4.

### Cross-cutting conventions (identical across groups)

- Success → JSON on stdout. Failure → JSON on stderr (`error`, `error_type`, `status_code`, `code`) with non-zero exit.
- Objects are addressable by **name or id**; resolution happens internally.
- **Destructive operations are dry-run by default**: they print the affected objects, an AI-facing warning, and an `execute_command` field. Only `--execute` performs the action.
- **Configuration writes auto-backup → read-modify-write → verify by re-reading.** Endpoints with whole-object replacement semantics (connectors, sign-in-exp) can lose unrelated data when patched carelessly, so this guardrail is mandatory.
- Large objects print a summary by default; `--full` prints everything.

### Library

- `client.request(...)` is the single HTTP egress and **returns parsed JSON** (not a `Response`); `raw=True` is the escape hatch.
- `LogtoAPIError` gains a `code` field (Logto's business error code) so agents can branch on codes instead of string-matching messages.
- `LogtoClient.from_env()` convenience constructor.
- Namespaces mirror CLI groups exactly: `logto-mgmt app create` ⇄ `client.apps.create()`.

### Scripts (retained)

| Script | Purpose |
|---|---|
| `migrate.py` | Bulk-import users from CSV |
| `sync_plan.py` | Diff two CSV exports → produce an add/update plan |

## Success Criteria

1. `api search <keyword>` finds endpoints from the tenant's own swagger; `api call` can safely invoke any endpoint (non-GET requires `--execute`).
2. `sign-in-exp get` and `account-center get` print a readable summary by default, not a wall of JSON.
3. `email-template replace-text` edits text across multiple templates, **backing up first and verifying afterwards**; `restore` rolls back completely.
4. `snapshot dump` produces a full tenant configuration picture in one command (previously a hand-written audit doc); `snapshot diff` surfaces what changed between two runs.
5. `doctor` distinguishes four failure classes — unresolved credential references, wrong credentials, missing Management API role (403), and missing tenant id — and states the fix for each.
6. Destructive operations **never issue a real write request** without `--execute`.
7. No public file contains a real email, key, tenant id, or domain.
8. `pytest` passes fully mocked by default, touching no real Logto tenant.

## Non-goals

- **Do not wrap the Account API (`/api/my-account/*`).** That surface is called by end users with their own token; folding it into an admin skill would invite using admin credentials to mutate user data.
- No interactive TUI — output must be directly consumable by agents.
- No attempt at exhaustive endpoint coverage; the long tail is served by `api search` + `api call`.
- Not an SSO provider or OIDC client (Logto handles that).
- Not a Logto Console replacement (visual administration stays in the Console).
- Not a user-migration platform (migration scripts are utilities, not the product).
