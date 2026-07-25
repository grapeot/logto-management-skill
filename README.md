# logto-management-skill

A safe CLI and Python library for discovering and managing Logto tenant configuration. It is designed for AI agents, emits JSON, and resolves credentials through 1Password before Python starts.

## Why This Tool Exists

Logto endpoint paths are not reliably guessable. `logto-mgmt api search` reads the tenant's own `/api/swagger.json`, so agents can discover the installed API surface instead of inventing paths.

Tenant-wide writes need stronger protection than ordinary CRUD:

- Email templates, sign-in experience, and account center writes always read the complete object, deep-copy it, modify one part, save a local backup, PATCH, and re-read to verify.
- Direct writes to those protected endpoints are blocked in `client.request()` and `api call`, so callers cannot bypass the guarded namespaces.
- Deletions, access revocation, application URI replacement, organization MFA policy changes, and direct non-GET calls are dry-run by default.
- Email connector backups are gitignored and written with owner-only permissions.

## Quick Start

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
cp .env.example .env

op run --env-file .env -- logto-mgmt doctor
op run --env-file .env -- logto-mgmt api search mfa
```

If credentials are missing, unresolved, or return 403, follow [the onboarding guide](docs/onboarding.md). Do not paste an App Secret into chat.

## Command Groups

```text
api              Search Swagger, inspect schemas, safely call long-tail endpoints
sign-in-exp      Read and update sign-in, MFA, passkey, and branding settings
account-center   Read and update account self-service settings
app              List, inspect, create, update, and delete applications
email-template   List, edit, back up, and restore embedded email templates
snapshot         Export and diff tenant configuration
resource         Manage API resources and scopes
role             Manage roles, users, and scope bindings
user             Find, create, and safely delete users
user-mfa         Inspect and safely remove user MFA verifications
org              Manage organizations, members, and organization MFA policy
doctor           Diagnose credentials, tenant ID, and Management API access
```

Run `logto-mgmt <group> --help` for full arguments. The canonical agent reference is [`skills/skill.md`](skills/skill.md).

## Python Library

CLI groups and library namespaces mirror each other:

```python
from logto_management_skill import LogtoClient

client = LogtoClient.from_env()

endpoints = client.api.search("mfa")
user = client.users.find("alice@example.com")
apps = client.apps.list(type="SPA")
preview = client.apps.delete("Example App")
result = client.apps.delete("Example App", execute=True)
```

`client.request()` returns parsed JSON by default. Pass `raw=True` for response headers or downloads. Non-2xx responses raise `LogtoAPIError` with `status_code`, `code`, `message`, `body`, and `url`.

## Safety And Backups

Automatic backups are stored under `.logto-backups/` by default. The directory is excluded from git. Backups can contain complete connector configuration and must be treated as secrets.

The public direct-call API intentionally rejects writes to `/api/sign-in-exp`, `/api/account-center`, and `/api/connectors/{id}`. Use `client.sign_in_exp`, `client.account_center`, or `client.email_templates` so backup and verification cannot be skipped.

## Development

```bash
source .venv/bin/activate
python -m pytest -v
```

The default suite is fully mocked and never contacts a Logto tenant. Live tests, when added or run, must remain read-only.

## Documentation

- [Interface design](docs/interface_design.md)
- [Onboarding](docs/onboarding.md)
- [Architecture](docs/rfc.md)
- [Test strategy](docs/test.md)
- [Agent skill](skills/skill.md)

## License

MIT
