#!/usr/bin/env bash
set -euo pipefail

# Interactive, secret-safe setup for a public Hermes Research installation.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
umask 077

non_interactive=0
if [[ "${1:-}" == "--non-interactive" ]]; then
  non_interactive=1
fi

if [[ ! -f "${ROOT_DIR}/runtime/hermes-home/bin/start-gateway.sh" ]]; then
  info "Preparando la estructura runtime por primera vez"
  bash "${ROOT_DIR}/install.sh" >/dev/null
fi

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
fi

prompt_value() {
  local label="$1"
  local current="$2"
  local value=""
  if [[ "${non_interactive}" == "1" ]]; then
    printf '%s' "${current}"
    return
  fi
  read -r -p "${label}${current:+ [${current}]}: " value
  printf '%s' "${value:-${current}}"
}

prompt_secret() {
  local label="$1"
  local current="$2"
  local value=""
  if [[ "${non_interactive}" == "1" ]]; then
    printf '%s' "${current}"
    return
  fi
  if [[ -n "${current}" ]]; then
    read -r -s -p "${label} [conservar valor actual]: " value
  else
    read -r -s -p "${label}: " value
  fi
  printf '\n' >&2
  printf '%s' "${value:-${current}}"
}

env_value() {
  local key="$1"
  awk -F= -v key="${key}" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${ROOT_DIR}/.env"
}

mode="${HERMES_INSTALL_MODE:-$(env_value HERMES_INSTALL_MODE)}"
base_url="${HERMES_INFERENCE_BASE_URL:-$(env_value HERMES_INFERENCE_BASE_URL)}"
api_key="${HERMES_INFERENCE_API_KEY:-$(env_value HERMES_INFERENCE_API_KEY)}"
primary_model="${HERMES_MODEL_PRIMARY:-$(env_value HERMES_MODEL_PRIMARY)}"
vision_model="${HERMES_MODEL_VISION:-$(env_value HERMES_MODEL_VISION)}"
review_model="${HERMES_MODEL_REVIEW:-$(env_value HERMES_MODEL_REVIEW)}"
telegram_token="${TELEGRAM_BOT_TOKEN:-$(env_value TELEGRAM_BOT_TOKEN)}"
runtime_uid="${HERMES_UID:-$(id -u)}"
runtime_gid="${HERMES_GID:-$(id -g)}"

mode="$(prompt_value "Modo (cli, telegram o both)" "${mode:-both}")"
case "${mode}" in
  cli|telegram|both) ;;
  *) fail "El modo debe ser cli, telegram o both" ;;
esac

base_url="$(prompt_value "Endpoint OpenAI-compatible, terminado en /v1" "${base_url}")"
primary_model="$(prompt_value "Modelo principal" "${primary_model}")"
vision_model="$(prompt_value "Modelo con visión" "${vision_model:-${primary_model}}")"
review_model="$(prompt_value "Modelo revisor independiente" "${review_model:-${vision_model:-${primary_model}}}")"
api_key="$(prompt_secret "API key del proveedor" "${api_key}")"

if [[ "${mode}" == "telegram" || "${mode}" == "both" ]]; then
  telegram_token="$(prompt_secret "Token de Telegram" "${telegram_token}")"
else
  telegram_token=""
fi

[[ -n "${base_url}" ]] || fail "Falta HERMES_INFERENCE_BASE_URL"
[[ -n "${api_key}" ]] || fail "Falta HERMES_INFERENCE_API_KEY"
[[ -n "${primary_model}" ]] || fail "Falta HERMES_MODEL_PRIMARY"
if [[ "${mode}" != "cli" && -z "${telegram_token}" ]]; then
  fail "El modo ${mode} necesita TELEGRAM_BOT_TOKEN"
fi

export SETUP_MODE="${mode}"
export SETUP_BASE_URL="${base_url%/}"
export SETUP_API_KEY="${api_key}"
export SETUP_PRIMARY_MODEL="${primary_model}"
export SETUP_VISION_MODEL="${vision_model:-${primary_model}}"
export SETUP_REVIEW_MODEL="${review_model:-${vision_model:-${primary_model}}}"
export SETUP_TELEGRAM_TOKEN="${telegram_token}"
export SETUP_RUNTIME_UID="${runtime_uid}"
export SETUP_RUNTIME_GID="${runtime_gid}"

python3 - "${ROOT_DIR}/.env" <<'PY'
from __future__ import annotations

import os
import pathlib
import shlex
import sys

path = pathlib.Path(sys.argv[1])
updates = {
    "HERMES_INSTALL_MODE": os.environ["SETUP_MODE"],
    "HERMES_INFERENCE_BASE_URL": os.environ["SETUP_BASE_URL"],
    "HERMES_INFERENCE_API_KEY": os.environ["SETUP_API_KEY"],
    "HERMES_MODEL_PRIMARY": os.environ["SETUP_PRIMARY_MODEL"],
    "HERMES_MODEL_VISION": os.environ["SETUP_VISION_MODEL"],
    "HERMES_MODEL_REVIEW": os.environ["SETUP_REVIEW_MODEL"],
    "TELEGRAM_BOT_TOKEN": os.environ["SETUP_TELEGRAM_TOKEN"],
    "HERMES_UID": os.environ["SETUP_RUNTIME_UID"],
    "HERMES_GID": os.environ["SETUP_RUNTIME_GID"],
}

lines = path.read_text(encoding="utf-8").splitlines()
seen: set[str] = set()
rendered: list[str] = []
for line in lines:
    if "=" not in line or line.lstrip().startswith("#"):
        rendered.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in updates:
        rendered.append(f"{key}={shlex.quote(updates[key])}")
        seen.add(key)
    else:
        rendered.append(line)
for key, value in updates.items():
    if key not in seen:
        rendered.append(f"{key}={shlex.quote(value)}")
path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

unset SETUP_API_KEY SETUP_TELEGRAM_TOKEN
pass "Configuración guardada en .env con permisos 600"
printf '\nSiguiente paso: ./hermes-research doctor\n'
