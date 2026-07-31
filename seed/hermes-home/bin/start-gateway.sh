#!/usr/bin/env bash
set -euo pipefail

if [[ -f /opt/data/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /opt/data/.env
  set +a
fi

# Hermes 0.19 starts cron, logging, and Kanban workers with the gateway.
# Create their writable state roots before any background thread can use them.
mkdir -p \
  /opt/data/cron \
  /opt/data/logs \
  /opt/data/kanban/boards \
  /opt/data/kanban/logs \
  /opt/data/kanban/workspaces \
  /opt/data/sessions \
  /opt/data/home/default/tmp

export HERMES_TELEGRAM_PUBLIC_MENU_ONLY="${HERMES_TELEGRAM_PUBLIC_MENU_ONLY:-1}"

python3 /opt/data/bin/configure-runtime.py

ensure_tirith_ready() {
  if [[ "${TIRITH_ENABLED:-true}" == "false" ]]; then
    return 0
  fi

  python3 - <<'PY'
import pathlib
import time

from hermes_constants import get_hermes_home
from tools.tirith_security import ensure_installed

deadline = time.monotonic() + 90
ensure_installed()
tirith_path = pathlib.Path(get_hermes_home()) / "bin" / "tirith"
while time.monotonic() < deadline:
    if tirith_path.is_file() and tirith_path.stat().st_mode & 0o111:
        raise SystemExit(0)
    ensure_installed()
    time.sleep(1)
raise SystemExit(
    "Tirith could not be installed for this platform. "
    "Set TIRITH_ENABLED=false only after documenting the accepted risk."
)
PY
}

configure_telegram_bot() {
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    return 0
  fi

  local api="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"

  curl -fsS -X POST "${api}/setMyDescription" \
    -d 'description=Hermes crea revisiones científicas PRISMA de principio a fin. Usa /start para empezar, /nueva_revision para abrir una revisión nueva y /estado para seguir su avance.' >/dev/null

  curl -fsS -X POST "${api}/setMyShortDescription" \
    -d 'short_description=Revisiones PRISMA guiadas en Telegram.' >/dev/null

  curl -fsS -X POST "${api}/setChatMenuButton" \
    -d 'menu_button={"type":"commands"}' >/dev/null

  curl -fsS -X POST "${api}/setMyCommands" \
    -H 'Content-Type: application/json' \
    -d @- >/dev/null <<'JSON'
{
  "commands": [
    { "command": "start", "description": "Abrir el menú principal y la guía de inicio" },
    { "command": "nueva_revision", "description": "Iniciar una revisión nueva paso a paso" },
    { "command": "estado", "description": "Ver el estado de la revisión activa" },
    { "command": "reanudar", "description": "Retomar una revisión en curso" },
    { "command": "cancelar", "description": "Cancelar el intake guiado actual" },
    { "command": "ayuda", "description": "Ver ejemplos y uso rápido" }
  ]
}
JSON
}

ensure_tirith_ready
if [[ "${HERMES_INSTALL_MODE:-both}" == "cli" ]]; then
  exec sleep infinity
fi
hermes gateway &
gateway_pid=$!

# Hermes publica primero su propio menú; después lo dejamos en castellano.
for _ in 1 2 3 4 5; do
  sleep 2
  if configure_telegram_bot; then
    break
  fi
done

wait "${gateway_pid}"
