#!/usr/bin/env bash
set -euo pipefail

if [[ -f /opt/data/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /opt/data/.env
  set +a
fi

# Keep the watchdog writable even in a fresh, read-only-root container.
mkdir -p /opt/data/logs /opt/data/watchdog

python3 /opt/data/bin/configure-runtime.py
exec python3 /opt/data/bin/prisma-watchdog.py
