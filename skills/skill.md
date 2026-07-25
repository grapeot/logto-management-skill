---
name: logto-management
description: Safely discover, inspect, back up, and manage Logto tenant configuration through a JSON CLI and Python library.
---

# Logto Management Skill

Use `logto-mgmt` to manage Logto users, roles, applications, resources, sign-in settings, account center, email templates, MFA recovery, organizations, and tenant snapshots. Prefer the CLI for auditable agent work and the Python namespaces for composition.

## Trigger Rules

Use this skill for requests mentioning Logto Management API, tenant configuration, Logto users or roles, applications, redirect URIs, resources or scopes, sign-in experience, MFA policy, passkeys, account center, email templates, organizations, tenant audit, or Logto Swagger.

When `.env` is absent, any required environment variable is missing, an environment value is still a literal `op://...`, token acquisition fails, a Management API call returns 403, or a custom domain lacks a tenant ID, stop retrying and follow [`docs/onboarding.md`](../docs/onboarding.md).

Creating the first M2M application requires a human with Logto Console access. Never ask the user to paste an App Secret into chat. The Management API has one all-or-nothing scope named `all`; the required built-in role is `Logto Management API access`.

Do not use this administrator skill for `/api/my-account/*`. Those endpoints require an end-user token and belong in the product's account UI.

## Setup

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
cp .env.example .env
op run --env-file .env -- logto-mgmt doctor
```

Run commands through 1Password:

```bash
op run --env-file .env -- logto-mgmt <group> <verb>
```

All successful output is JSON on stdout. Errors are JSON on stderr with `error`, `error_type`, `status_code`, and `code`.

## Discovery First

Do not guess Logto paths. Search the tenant's own Swagger first:

```bash
logto-mgmt api search mfa
logto-mgmt api schema POST /api/users
logto-mgmt api call GET /api/roles
logto-mgmt api call PATCH /api/other-setting --json '{"enabled":true}'
logto-mgmt api call PATCH /api/other-setting --json-file body.json --execute
```

Every non-GET direct call is a dry-run without `--execute`. Direct writes to sign-in experience, account center, and connectors remain blocked even with `--execute`; use their guarded command groups.

## Commands

### Sign-In Experience

```bash
logto-mgmt sign-in-exp get [--section signIn|mfa|passkey|branding|password|all] [--full]
logto-mgmt sign-in-exp set-mfa --policy NoPrompt|UserControlled|Mandatory [--factor Totp]...
logto-mgmt sign-in-exp set-passkey --enable|--disable [--show-button] [--allow-autofill]
logto-mgmt sign-in-exp set-branding [--logo-url URL] [--favicon-url URL]
```

These writes always back up, preserve sibling fields, and verify by re-reading. There is no backup bypass.

### Account Center

```bash
logto-mgmt account-center get
logto-mgmt account-center enable
logto-mgmt account-center disable
logto-mgmt account-center set-fields --field password=Edit --field email=ReadOnly
logto-mgmt account-center set-webauthn-origins --origin https://example.com
```

Field permissions are `Off`, `ReadOnly`, or `Edit`. Invalid values fail locally before network access. Writes use the same mandatory backup and verification path.

### Applications

```bash
logto-mgmt app list [--type SPA|Traditional|MachineToMachine|Native]
logto-mgmt app get <name-or-id>
logto-mgmt app create <name> --type SPA [--redirect-uri URI]... [--post-logout-uri URI]... [--description TEXT]
logto-mgmt app update-uris <name-or-id> [--add-redirect URI]... [--remove-redirect URI]...
logto-mgmt app update-uris <name-or-id> [options] --execute
logto-mgmt app delete <name-or-id>
logto-mgmt app delete <name-or-id> --execute
```

URI replacement and deletion are dry-run by default.

### Email Templates

```bash
logto-mgmt email-template list
logto-mgmt email-template get <usageType> [--out file.html]
logto-mgmt email-template backup [--out directory]
logto-mgmt email-template restore <backup.json>
logto-mgmt email-template restore <backup.json> --execute
logto-mgmt email-template set <usageType> [--subject TEXT] [--content-file file.html] --execute
logto-mgmt email-template replace-text --find TEXT --replace TEXT [--usage-type TYPE]... --execute
logto-mgmt email-template append-html --html-file file.html --after-marker '<hr>' --usage-type TYPE... --execute
```

Email templates are embedded in one connector's `config.templates` array. Never patch that connector manually. Backups contain complete connector configuration, may contain secrets, and belong only in the gitignored owner-readable backup directory.

### Snapshots

```bash
logto-mgmt snapshot dump [--out snapshot.json] [--markdown report.md]
logto-mgmt snapshot diff old.json [new.json]
```

Template content is excluded; only metadata, length, and SHA-256 hash are stored.

### Resources And Roles

```bash
logto-mgmt resource list
logto-mgmt resource get <name-or-id>
logto-mgmt resource create <name> --indicator https://api.example.com [--ttl 3600]
logto-mgmt resource scope add <resource> <scope> [--description TEXT]

logto-mgmt role list
logto-mgmt role get <name-or-id>
logto-mgmt role create <name> [--description TEXT]
logto-mgmt role add-scope <role> <resource> <scope>
logto-mgmt role assign <role> <email>
logto-mgmt role revoke <role> <email>
logto-mgmt role revoke <role> <email> --execute
logto-mgmt role users <role>
```

Role revocation is dry-run by default.

### Users And MFA Recovery

```bash
logto-mgmt user find alice@example.com
logto-mgmt user create alice@example.com [--name Alice]
logto-mgmt user delete alice@example.com
logto-mgmt user delete alice@example.com --execute

logto-mgmt user-mfa list alice@example.com
logto-mgmt user-mfa delete alice@example.com <verification-id>
logto-mgmt user-mfa delete alice@example.com <verification-id> --execute
```

Both deletion commands are dry-run by default. MFA deletion is an administrator recovery action for a user who lost an enrolled factor.

### Organizations And Diagnostics

```bash
logto-mgmt org list
logto-mgmt org create <name> [--description TEXT]
logto-mgmt org add-member <org> alice@example.com
logto-mgmt org set-mfa-policy <org> --policy Mandatory
logto-mgmt org set-mfa-policy <org> --policy Mandatory --execute

logto-mgmt doctor
```

Organization MFA policy changes are dry-run by default because requiring MFA can block unenrolled members.

## Python Library

```python
from logto_management_skill import LogtoClient

client = LogtoClient.from_env()

client.api.search("mfa")
client.users.find("alice@example.com")
client.roles.add_scope("admin", "Example API", "read")
client.sign_in_exp.set_mfa("Mandatory", ["Totp"])
client.email_templates.backup()
client.email_templates.replace_text("Old name", "New name", execute=True)
```

Namespace mapping:

```text
user            client.users
role            client.roles
app             client.apps
resource        client.resources
sign-in-exp     client.sign_in_exp
account-center  client.account_center
email-template  client.email_templates
user-mfa        client.user_mfa
org             client.orgs
snapshot        client.snapshot
api             client.api
doctor          client.doctor
```

`client.request()` returns parsed JSON. `raw=True` returns the response object. `LogtoAPIError` exposes `status_code`, `code`, `message`, `body`, and `url`.

## Safety Rules For Agents

1. Start with read commands or `doctor`.
2. Search Swagger instead of guessing a path.
3. Treat every dry-run warning as a pause point; execute only after authorization for that exact action.
4. Never bypass protected configuration namespaces.
5. Keep `.logto-backups/` private and out of git.
6. Use only read-only operations in live tests.
