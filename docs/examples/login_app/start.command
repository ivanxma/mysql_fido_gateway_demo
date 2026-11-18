#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
"${GATEWAY_PYTHON:-python3}" start.py "$@"
