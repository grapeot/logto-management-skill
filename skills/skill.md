# Skill: Logto Management

A CLI for managing Logto users and roles via the Logto Management API. Designed for AI agents and human operators. 1Password-native credential management.

## Metadata

- Type: API Guide
- CLI: `logto-mgmt`
- Python library: `logto_management_skill.LogtoClient`
- Install: `uv pip install -e .` or `pip install logto-management-skill`

## When to Use

Trigger words: "Logto role", "assign Logto role", "Logto user", "create Logto user", "find Logto user", "delete Logto user", "Logto Management API"

Typical scenarios:
- Assigning an admin role to a user in a Logto-backed SSO system
- Looking up a user's `lastSignInAt` for activity tracking
- Creating a passwordless user account programmatically
- Deleting a user after an explicit dry-run review
- Auditing which users have a specific role

## Prerequisites

1. A Logto tenant (Cloud or self-hosted) with a Management API M2M application
2. 1Password CLI (`op`) installed and signed in
3. A `.env` file with `op://` references to your M2M credentials (see `.env.example`)

## Credential Resolution

The CLI uses `op run --env-file .env` to resolve 1Password references before the Python process starts:

```bash
op run --env-file .env -- logto-mgmt role list
```

If `OP_SERVICE_ACCOUNT_TOKEN` is set in the environment, resolution is automatic (no UI prompt). Otherwise, 1Password prompts for Touch ID or password approval. The Python code is agnostic to which path is used.

For convenience, use the wrapper script:

```bash
./scripts/run_cli.sh role list
```

## CLI Reference

All commands output JSON to stdout. Errors go to stderr as JSON.

### Roles

```bash
# Create a role
logto-mgmt role create my-admin-role --description "Admin access"

# List all roles
logto-mgmt role list

# Assign a role to a user (by email lookup)
logto-mgmt role assign my-admin-role alice@example.com

# Remove a role from a user
logto-mgmt role revoke my-admin-role alice@example.com

# List users who have a role
logto-mgmt role users my-admin-role
```

### Users

```bash
# Find a user by email (returns full object including lastSignInAt)
logto-mgmt user find alice@example.com

# Create a passwordless user
logto-mgmt user create alice@example.com --name "Alice"

# Preview a destructive user deletion. This does not delete anything.
logto-mgmt user delete alice@example.com

# Execute the deletion only after explicit authorization.
logto-mgmt user delete alice@example.com --execute
```

`user delete` is dry-run by default. The dry-run output includes a natural-language warning for AI agents and an `execute_command` field. Treat that warning as a required pause point: only run with `--execute` when the human has authorized this exact deletion.

## Python Library

```python
from logto_management_skill import LogtoClient

client = LogtoClient(
    endpoint="https://auth.example.com",
    app_id="...",
    app_secret="...",
    tenant_id="optional-for-custom-domains",
)

# Create a passwordless user
user = client.create_user("alice@example.com", name="Alice")

# Find a user (returns None if not found)
user = client.find_user_by_email("alice@example.com")
# user["lastSignInAt"] is available for activity tracking

# Delete uses dry-run by default
preview = client.delete_user("alice@example.com")
result = client.delete_user("alice@example.com", execute=True)

# Create and assign a role
role = client.create_role("admin", description="Admin access")
client.assign_role_to_user("admin", "alice@example.com")

# List users with a role
users = client.get_role_users("admin")
```

## Output Format

Success: JSON object or array on stdout.

```json
{"id": "abc123", "name": "admin", "description": "Admin access"}
```

Error: JSON object on stderr, exit code 1.

```json
{"error": "Logto API 404 at /api/roles/xxx: role not found", "status_code": 404}
```

## Error Transparency

All HTTP errors preserve the original status code and response body. This is intentional: AI agents need the raw error to diagnose root causes without guessing.

## Installation for AI Agents

If your workspace has `rules/skills/INDEX.md` or a skill discovery file, add an entry pointing to this repo's `skills/skill.md`. The AI agent can then discover and use the CLI by reading the skill file.

To install:

```bash
cd /path/to/workspace
git clone https://github.com/grapeot/logto-management-skill.git adhoc_jobs/logto_management_skill
cd adhoc_jobs/logto_management_skill
uv venv && uv pip install -e '.[dev]'
cp .env.example .env  # Edit with your 1Password references
```

## Known Limitations

- No organization management (roles only in v1)
- No bulk user operations in CLI (use migration scripts for bulk)
- `update_user` and `fetch_all_emails` are library-only (not CLI-exposed)
- Token expiry is 401-driven (no proactive refresh); sufficient for CLI usage patterns
