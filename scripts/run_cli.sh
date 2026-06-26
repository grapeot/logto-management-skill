#!/usr/bin/env bash
# Wrapper script: resolves 1Password op:// references via op run, then runs logto-mgmt.
# Usage: ./scripts/run_cli.sh role list
#        ./scripts/run_cli.sh user find alice@example.com

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

if [ ! -f .env ]; then
  echo "Error: .env not found. Copy .env.example and fill in your 1Password references." >&2
  exit 1
fi

# Activate venv if present
if [ -d .venv ]; then
  source .venv/bin/activate
fi

if command -v op &>/dev/null; then
  op run --env-file .env -- python -m logto_management_skill.cli "$@"
else
  echo "Warning: 1Password CLI (op) not found. Running with env vars as-is." >&2
  python -m logto_management_skill.cli "$@"
fi