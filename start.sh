#!/bin/bash
# Start the Flask gateway in the foreground; stop it with Ctrl+C.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

case "${1:-}" in
    ''|--local) START_MODE=local ;;
    --remote) START_MODE=remote ;;
    *) echo "Usage: ./start.sh [--local|--remote]" >&2; exit 2 ;;
esac

# Optional shell configuration. Only source a .env file you control.
if [[ -f .env ]]; then
    set -a
    source ./.env
    set +a
fi

PYTHON_BIN="$PWD/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Missing .venv. Run: python3 -m venv .venv" >&2
    echo 'Then install the wheel with its [flask] extra; see README.md.' >&2
    exit 1
fi

# Check before changing the proxy or displaying a temporary administrator token.
# -I prevents this checkout's package from shadowing the installed wheel.
"$PYTHON_BIN" -I "$PWD/app.py" --check-library

if [[ -z "${DB_HOST:-}" || -z "${DB_PORT:-}" ]]; then
    echo 'Set DB_HOST and DB_PORT explicitly in .env or the environment. No MySQL endpoint is assumed.' >&2
    exit 1
fi
export DB_HOST DB_PORT
export RP_ID="${RP_ID:-localhost}"
export BROWSER_ORIGIN="${BROWSER_ORIGIN:-https://$RP_ID}"
export DB_ACCOUNT_HOST="${DB_ACCOUNT_HOST:-localhost}"

if [[ "$START_MODE" == local ]]; then
    if [[ "$RP_ID" != localhost || "$BROWSER_ORIGIN" != https://localhost ]]; then
        echo "Local mode: replacing RP_ID/BROWSER_ORIGIN with localhost settings."
        echo "Use ./start.sh --remote to use a configured public hostname."
    fi
    export RP_ID=localhost
    export BROWSER_ORIGIN=https://localhost
fi

# TLS/loopback development mode is an operator choice, never inferred.
if [[ -z "${DB_SSL_CA:-}" && "${ALLOW_LOOPBACK_DB_PLAINTEXT:-}" != 1 ]]; then
    echo 'Set DB_SSL_CA for verified TLS, or explicitly set ALLOW_LOOPBACK_DB_PLAINTEXT=1 for loopback development.' >&2
    exit 1
fi

# Enable the administrator form by default for the local browser demo.
# An explicitly empty ADMIN_TOKEN keeps provisioning disabled.
if [[ "$BROWSER_ORIGIN" == "https://localhost" && -z "${ADMIN_TOKEN+x}" ]]; then
    export ADMIN_TOKEN="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
if [[ -n "${ADMIN_TOKEN:-}" ]]; then
    printf 'Administrator token: %s\n' "$ADMIN_TOKEN"
else
    echo "Administrator provisioning is disabled (ADMIN_TOKEN is empty)."
fi

echo "MySQL target: $DB_HOST:$DB_PORT"
echo "Browser origin: $BROWSER_ORIGIN; MySQL WebAuthn RP ID must be $RP_ID."
if [[ "$START_MODE" == local ]]; then
    if ! command -v caddy >/dev/null 2>&1; then
        echo "Caddy is required to serve https://localhost. Install Caddy, then retry." >&2
        exit 1
    fi
    echo "Configuring Caddy for https://localhost ..."
    if ! caddy reload --config "$PWD/Caddyfile.local" --adapter caddyfile; then
        caddy start --config "$PWD/Caddyfile.local" --adapter caddyfile
    fi
fi
echo "Open $BROWSER_ORIGIN in your browser."
echo "Starting Flask on 127.0.0.1:5001. Stop with Ctrl+C."
exec "$PYTHON_BIN" -I "$PWD/app.py"
