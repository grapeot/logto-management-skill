# logto-management-skill

A CLI and Python library for managing Logto users and roles via the Logto Management API. Designed for AI agents and human operators. 1Password-native credential management.

## Features

- **Role management**: create, list, assign, revoke, and audit roles
- **User management**: find users by email, create passwordless users, delete users with a dry-run guard
- **Token management**: automatic M2M token acquisition with 401 auto-refresh
- **1Password integration**: credentials resolved via `op run` (service account or interactive Touch ID)
- **AI-agent friendly**: JSON output, transparent error messages with HTTP status codes

## Quick Start

```bash
# Install
uv venv && uv pip install -e '.[dev]'

# Configure credentials
cp .env.example .env
# Edit .env with your 1Password op:// references

# Use via wrapper script (handles op run)
./scripts/run_cli.sh role list

# Or directly with op run
op run --env-file .env -- logto-mgmt role list
```

## CLI

```
logto-mgmt role create <name> [--description <desc>]
logto-mgmt role list
logto-mgmt role assign <role_name> <email>
logto-mgmt role revoke <role_name> <email>
logto-mgmt role users <role_name>
logto-mgmt user find <email>
logto-mgmt user create <email> [--name <name>]
logto-mgmt user delete <email>           # dry-run preview
logto-mgmt user delete <email> --execute # actual deletion
```

`user delete` is destructive and uses a two-phase flow. Without `--execute`, it returns a JSON preview and an AI-facing warning. Re-run with `--execute` only after explicit authorization for that specific deletion.

## Python Library

```python
from logto_management_skill import LogtoClient

client = LogtoClient(
    endpoint="https://auth.example.com",
    app_id="...",
    app_secret="...",
)

user = client.find_user_by_email("alice@example.com")
print(user["lastSignInAt"])
```

## Documentation

- [PRD](docs/prd.md) — goals, features, success criteria
- [RFC](docs/rfc.md) — architecture, API design, testing strategy
- [Skill doc](skills/skill.md) — installation and usage guide for AI agents

## License

MIT
