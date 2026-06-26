# AGENTS.md - logto-management-skill

## Project Overview

A CLI and Python library for managing Logto users, roles, and organizations via the Logto Management API. Designed as a reusable skill that any AI agent or human can install and use. Public GitHub repo.

## Project Structure

```
logto_management_skill/
├── AGENTS.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── README.md
├── docs/
│   ├── prd.md
│   ├── rfc.md
│   ├── test.md
│   ├── working.md
│   └── skill.md
├── src/
│   └── logto_management_skill/
│       ├── __init__.py
│       ├── client.py       # LogtoClient core library
│       └── cli.py           # CLI entry point
├── scripts/
│   └── run_cli.sh           # 1Password op run wrapper
└── tests/
```

## Privacy Level

**Public repo.** This repo will be published to GitHub. All files must use fake handles:

- Emails: `alice@example.com`, `bob@example.net`
- 1Password: `op://your-vault/your-item/your-field`
- Domains: `example.com`, `example.org`
- No real tenant IDs, API keys, or internal paths

## Working Language

English for all documentation and code. This is a public-facing tool.

## Environment

- Python: uv-managed, `.venv/` in project root
- Dependencies: `requests` (HTTP), `pytest` (dev)
- CLI entry point: `logto-mgmt`

## Credential Model

1Password-native. The `.env` file uses `op://` references. Two resolution paths:

1. **Service account** (automated): If `OP_SERVICE_ACCOUNT_TOKEN` is set, `op run --env-file .env` resolves all `op://` references automatically.
2. **Interactive** (human at machine): If no service account token, `op run` prompts for Touch ID / password approval per access.

Both paths are transparent to the CLI — it just reads environment variables that `op run` has already resolved.

## Constraints

- Never commit `.env`, real credentials, or real user data
- All test fixtures must use fake emails and fake IDs
- Error messages must preserve HTTP status code and response body for AI agent debugging
- CLI outputs JSON to stdout, errors to stderr