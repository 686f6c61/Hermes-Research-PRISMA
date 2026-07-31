#!/usr/bin/env bash
set -euo pipefail

# Resolve the package root once so every generated path stays predictable,
# even when the script is invoked through a symlink or from another folder.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ensure_research_plugin_enabled() {
  local config_path="$1"
  python3 - <<'PY' "${config_path}"
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
if "hermes_research" in text:
    raise SystemExit(0)

plugins_block = re.search(r"(?ms)^plugins:\n(?P<body>(?:^[ \t].*\n)*)", text)
if not plugins_block:
    suffix = "" if not text or text.endswith("\n") else "\n"
    config_path.write_text(
        text + suffix + "plugins:\n  enabled:\n    - hermes_research\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

body = plugins_block.group("body")
if re.search(r"(?m)^[ \t]+enabled:\s*$", body):
    new_body = re.sub(
        r"(?m)^([ \t]+enabled:\s*$)",
        r"\1\n    - hermes_research",
        body,
        count=1,
    )
else:
    insertion = "  enabled:\n    - hermes_research\n"
    new_body = insertion + body

start, end = plugins_block.span("body")
updated = text[:start] + new_body + text[end:]
config_path.write_text(updated, encoding="utf-8")
PY
}

# Create the host-side directories expected by docker-compose. Keeping these
# paths stable makes the public package easier to reason about and support.
mkdir -p \
  "${ROOT_DIR}/runtime/hermes-home" \
  "${ROOT_DIR}/runtime/workspace" \
  "${ROOT_DIR}/runtime/obsidian"

ensure_runtime_state_dirs() {
  local runtime_home="$1"
  mkdir -p \
    "${runtime_home}/cron" \
    "${runtime_home}/logs" \
    "${runtime_home}/kanban/boards" \
    "${runtime_home}/kanban/logs" \
    "${runtime_home}/kanban/workspaces" \
    "${runtime_home}/sessions" \
    "${runtime_home}/watchdog" \
    "${runtime_home}/home/default/tmp"
}

# Seed the runtime Hermes home with the minimum executable payload needed by
# the public package. This avoids a common failure mode where the runtime data
# directory exists but is functionally empty.
SEED_HOME_SRC="${ROOT_DIR}/seed/hermes-home"
SEED_HOME_DST="${ROOT_DIR}/runtime/hermes-home"
if [[ -d "${SEED_HOME_SRC}" ]]; then
  if [[ ! -f "${SEED_HOME_DST}/bin/start-gateway.sh" || "${HERMES_REFRESH_RUNTIME_HOME:-0}" == "1" ]]; then
    rm -rf "${SEED_HOME_DST}"
    mkdir -p "${SEED_HOME_DST}"
    cp -R "${SEED_HOME_SRC}/." "${SEED_HOME_DST}/"
    echo "Se ha sembrado el runtime Hermes home en ${SEED_HOME_DST}"
  else
    echo "El runtime Hermes home ya existe; no se sobreescribe"
    mkdir -p "${SEED_HOME_DST}/plugins"
    if [[ -d "${SEED_HOME_SRC}/plugins/hermes_research" && ! -d "${SEED_HOME_DST}/plugins/hermes_research" ]]; then
      cp -R "${SEED_HOME_SRC}/plugins/hermes_research" "${SEED_HOME_DST}/plugins/hermes_research"
      echo "Se ha añadido el plugin hermes_research al runtime existente"
    fi
  fi
  if [[ -f "${SEED_HOME_DST}/config.yaml" ]]; then
    ensure_research_plugin_enabled "${SEED_HOME_DST}/config.yaml"
  fi
fi

ensure_runtime_state_dirs "${SEED_HOME_DST}"

# Materialize the bundled review template inside the runtime workspace. Public
# bootstrap commands expect this directory to exist before the first review is
# created. We only copy it on first install unless the maintainer explicitly
# asks for a refresh.
TEMPLATE_SRC="${ROOT_DIR}/templates/systematic-review-template"
TEMPLATE_DST="${ROOT_DIR}/runtime/workspace/systematic-review-template"
if [[ -d "${TEMPLATE_SRC}" ]]; then
  if [[ ! -d "${TEMPLATE_DST}" || "${HERMES_REFRESH_TEMPLATE:-0}" == "1" ]]; then
    rm -rf "${TEMPLATE_DST}"
    cp -R "${TEMPLATE_SRC}" "${TEMPLATE_DST}"
    echo "Se ha sincronizado la plantilla en ${TEMPLATE_DST}"
  else
    echo "La plantilla runtime ya existe; no se sobreescribe"
  fi
fi

# Seed a local .env file only on first install. We never overwrite an
# existing file because user-supplied tokens and local paths live there.
if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
  echo "Se ha creado ${ROOT_DIR}/.env a partir de .env.example"
else
  echo ".env ya existe; no se sobreescribe"
fi

chmod +x \
  "${ROOT_DIR}/install.sh" \
  "${ROOT_DIR}/hermes-research" \
  "${ROOT_DIR}/scripts/"*.sh \
  "${ROOT_DIR}/examples/cli-init-example.sh"

cat <<EOF
Hermes Research Pack ha preparado la estructura base.

Siguientes pasos:
1. Configura el proveedor y el modo de acceso:
   ${ROOT_DIR}/hermes-research setup
2. Valida y arranca:
   ${ROOT_DIR}/hermes-research up
3. Comprueba el ciclo público:
   ${ROOT_DIR}/hermes-research smoke-test
4. Revisa ${ROOT_DIR}/docs/quickstart.md
5. Si mantienes el paquete y actualizas la plantilla o el manifiesto, ejecuta:
   ${ROOT_DIR}/scripts/sync-bundle-assets.sh
EOF
