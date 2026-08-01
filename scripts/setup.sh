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

normalize_telegram_users() {
  local raw_value="$1"
  python3 - "${raw_value}" <<'PY'
import re
import sys

parts = [part.strip() for part in sys.argv[1].split(",") if part.strip()]
if not parts or any(not re.fullmatch(r"[1-9][0-9]*", part) for part in parts):
    raise SystemExit("Los usuarios de Telegram deben ser IDs numéricos positivos separados por comas")
print(",".join(dict.fromkeys(parts)))
PY
}

valid_email_or_empty() {
  local value="$1"
  [[ -z "${value}" || "${value}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]
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
telegram_allowed_users="${TELEGRAM_ALLOWED_USERS:-$(env_value TELEGRAM_ALLOWED_USERS)}"
telegram_home_channel="${TELEGRAM_HOME_CHANNEL:-$(env_value TELEGRAM_HOME_CHANNEL)}"
telegram_prisma_chat_id="${TELEGRAM_PRISMA_CHAT_ID:-$(env_value TELEGRAM_PRISMA_CHAT_ID)}"
contact_email="${HERMES_CONTACT_EMAIL:-$(env_value HERMES_CONTACT_EMAIL)}"
unpaywall_email="${HERMES_UNPAYWALL_EMAIL:-$(env_value HERMES_UNPAYWALL_EMAIL)}"
semantic_scholar_key="${HERMES_SEMANTIC_SCHOLAR_API_KEY:-$(env_value HERMES_SEMANTIC_SCHOLAR_API_KEY)}"
lens_key="${HERMES_LENS_API_KEY:-$(env_value HERMES_LENS_API_KEY)}"
ncbi_email="${HERMES_NCBI_EMAIL:-$(env_value HERMES_NCBI_EMAIL)}"
ncbi_key="${HERMES_NCBI_API_KEY:-$(env_value HERMES_NCBI_API_KEY)}"
scopus_key="${HERMES_SCOPUS_API_KEY:-$(env_value HERMES_SCOPUS_API_KEY)}"
elsevier_inst_token="${HERMES_ELSEVIER_INST_TOKEN:-$(env_value HERMES_ELSEVIER_INST_TOKEN)}"
wos_key="${HERMES_WOS_API_KEY:-$(env_value HERMES_WOS_API_KEY)}"
embase_key="${HERMES_EMBASE_API_KEY:-$(env_value HERMES_EMBASE_API_KEY)}"
ieee_key="${HERMES_IEEE_API_KEY:-$(env_value HERMES_IEEE_API_KEY)}"
researcher_name="${HERMES_RESEARCHER_NAME:-$(env_value HERMES_RESEARCHER_NAME)}"
researcher_email="${HERMES_RESEARCHER_EMAIL:-$(env_value HERMES_RESEARCHER_EMAIL)}"
researcher_orcid="${HERMES_RESEARCHER_ORCID:-$(env_value HERMES_RESEARCHER_ORCID)}"
adjudication_secret="${HERMES_ADJUDICATION_SECRET:-$(env_value HERMES_ADJUDICATION_SECRET)}"
docling_api_key="${HERMES_DOCLING_API_KEY:-$(env_value HERMES_DOCLING_API_KEY)}"
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

printf '\nFuentes académicas: las credenciales siguientes son opcionales.\n' >&2
contact_email="$(prompt_value "Email técnico de contacto para APIs académicas" "${contact_email}")"
unpaywall_email="$(prompt_value "Email para Unpaywall (opcional)" "${unpaywall_email:-${contact_email}}")"
semantic_scholar_key="$(prompt_secret "API key de Semantic Scholar (opcional)" "${semantic_scholar_key}")"
lens_key="$(prompt_secret "API key de Lens Scholarly (opcional)" "${lens_key}")"
ncbi_email="$(prompt_value "Email para NCBI/PubMed (opcional)" "${ncbi_email:-${contact_email}}")"
ncbi_key="$(prompt_secret "API key de NCBI/PubMed (opcional)" "${ncbi_key}")"
scopus_key="$(prompt_secret "API key institucional de Scopus (opcional)" "${scopus_key}")"
elsevier_inst_token="$(prompt_secret "Token institucional de Elsevier para Scopus/Embase (opcional)" "${elsevier_inst_token}")"
wos_key="$(prompt_secret "API key institucional de Web of Science (opcional)" "${wos_key}")"
embase_key="$(prompt_secret "API key institucional de Embase (opcional)" "${embase_key}")"
ieee_key="$(prompt_secret "API key institucional de IEEE Xplore (opcional)" "${ieee_key}")"

printf '\nIdentidad científica: se usa para contratos y adjudicaciones firmadas.\n' >&2
researcher_name="$(prompt_value "Nombre completo del investigador responsable" "${researcher_name}")"
researcher_email="$(prompt_value "Email del investigador responsable" "${researcher_email:-${contact_email}}")"
researcher_orcid="$(prompt_value "ORCID del investigador (opcional)" "${researcher_orcid}")"

if [[ -z "${adjudication_secret}" ]]; then
  adjudication_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
fi
if [[ -z "${docling_api_key}" ]]; then
  docling_api_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
fi

if [[ "${mode}" == "telegram" || "${mode}" == "both" ]]; then
  telegram_token="$(prompt_secret "Token de Telegram" "${telegram_token}")"
  [[ -n "${telegram_token}" ]] || fail "El modo ${mode} necesita TELEGRAM_BOT_TOKEN"

  bot_identity="$(
    TELEGRAM_BOT_TOKEN="${telegram_token}" \
      python3 "${ROOT_DIR}/scripts/telegram-bootstrap.py" identity
  )" || fail "Telegram no ha podido validar el token"
  pass "Bot de Telegram validado: ${bot_identity}"

  if [[ "${non_interactive}" == "0" && -z "${telegram_allowed_users}" ]]; then
    printf '\nAbre %s en Telegram, envía /start y vuelve aquí.\n' "${bot_identity}" >&2
    read -r -p "Pulsa Intro cuando hayas enviado /start: " _
    discovered_users="$(
      TELEGRAM_BOT_TOKEN="${telegram_token}" \
        python3 "${ROOT_DIR}/scripts/telegram-bootstrap.py" discover-users
    )" || fail "No se pudieron consultar los mensajes iniciales del bot"
    if [[ -n "${discovered_users}" ]]; then
      printf 'Usuarios privados detectados:\n%s\n' "${discovered_users}" >&2
      telegram_allowed_users="$(printf '%s\n' "${discovered_users}" | awk 'NR == 1 {print $1}')"
    else
      warn "No se detectó ningún /start; introduce manualmente tu ID numérico de Telegram"
    fi
  fi

  telegram_allowed_users="$(
    prompt_value "IDs de Telegram autorizados, separados por comas" "${telegram_allowed_users}"
  )"
  telegram_allowed_users="$(normalize_telegram_users "${telegram_allowed_users}")" ||
    fail "TELEGRAM_ALLOWED_USERS no es válido"
  first_allowed_user="${telegram_allowed_users%%,*}"
  telegram_home_channel="$(
    prompt_value "Chat ID privado para avisos" "${telegram_home_channel:-${first_allowed_user}}"
  )"
  [[ "${telegram_home_channel}" =~ ^[1-9][0-9]*$ ]] ||
    fail "El chat de avisos debe ser un ID privado numérico positivo"
  TELEGRAM_BOT_TOKEN="${telegram_token}" \
    python3 "${ROOT_DIR}/scripts/telegram-bootstrap.py" check-chat "${telegram_home_channel}" ||
    fail "El bot no puede acceder al chat de avisos; envíale /start y repite setup"
  telegram_prisma_chat_id="${telegram_home_channel}"
else
  telegram_token=""
  telegram_allowed_users=""
  telegram_home_channel=""
  telegram_prisma_chat_id=""
fi

[[ -n "${base_url}" ]] || fail "Falta HERMES_INFERENCE_BASE_URL"
[[ -n "${api_key}" ]] || fail "Falta HERMES_INFERENCE_API_KEY"
[[ -n "${primary_model}" ]] || fail "Falta HERMES_MODEL_PRIMARY"
[[ -n "${contact_email}" ]] || fail "Falta HERMES_CONTACT_EMAIL"
[[ -n "${researcher_name}" ]] || fail "Falta HERMES_RESEARCHER_NAME"
[[ -n "${researcher_email}" ]] || fail "Falta HERMES_RESEARCHER_EMAIL"
valid_email_or_empty "${contact_email}" || fail "HERMES_CONTACT_EMAIL no parece un email válido"
valid_email_or_empty "${unpaywall_email}" || fail "HERMES_UNPAYWALL_EMAIL no parece un email válido"
valid_email_or_empty "${ncbi_email}" || fail "HERMES_NCBI_EMAIL no parece un email válido"
valid_email_or_empty "${researcher_email}" || fail "HERMES_RESEARCHER_EMAIL no parece un email válido"
[[ "${#adjudication_secret}" -ge 32 ]] || fail "HERMES_ADJUDICATION_SECRET debe tener al menos 32 caracteres"
[[ "${#docling_api_key}" -ge 32 ]] || fail "HERMES_DOCLING_API_KEY debe tener al menos 32 caracteres"

export SETUP_MODE="${mode}"
export SETUP_BASE_URL="${base_url%/}"
export SETUP_API_KEY="${api_key}"
export SETUP_PRIMARY_MODEL="${primary_model}"
export SETUP_VISION_MODEL="${vision_model:-${primary_model}}"
export SETUP_REVIEW_MODEL="${review_model:-${vision_model:-${primary_model}}}"
export SETUP_TELEGRAM_TOKEN="${telegram_token}"
export SETUP_TELEGRAM_ALLOWED_USERS="${telegram_allowed_users}"
export SETUP_TELEGRAM_HOME_CHANNEL="${telegram_home_channel}"
export SETUP_TELEGRAM_PRISMA_CHAT_ID="${telegram_prisma_chat_id}"
export SETUP_CONTACT_EMAIL="${contact_email}"
export SETUP_UNPAYWALL_EMAIL="${unpaywall_email}"
export SETUP_SEMANTIC_SCHOLAR_KEY="${semantic_scholar_key}"
export SETUP_LENS_KEY="${lens_key}"
export SETUP_NCBI_EMAIL="${ncbi_email}"
export SETUP_NCBI_KEY="${ncbi_key}"
export SETUP_SCOPUS_KEY="${scopus_key}"
export SETUP_ELSEVIER_INST_TOKEN="${elsevier_inst_token}"
export SETUP_WOS_KEY="${wos_key}"
export SETUP_EMBASE_KEY="${embase_key}"
export SETUP_IEEE_KEY="${ieee_key}"
export SETUP_RESEARCHER_NAME="${researcher_name}"
export SETUP_RESEARCHER_EMAIL="${researcher_email}"
export SETUP_RESEARCHER_ORCID="${researcher_orcid}"
export SETUP_ADJUDICATION_SECRET="${adjudication_secret}"
export SETUP_ADJUDICATION_ALLOWED_USERS="${telegram_allowed_users}"
export SETUP_DOCLING_API_KEY="${docling_api_key}"
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
    "TELEGRAM_ALLOWED_USERS": os.environ["SETUP_TELEGRAM_ALLOWED_USERS"],
    "TELEGRAM_HOME_CHANNEL": os.environ["SETUP_TELEGRAM_HOME_CHANNEL"],
    "TELEGRAM_PRISMA_CHAT_ID": os.environ["SETUP_TELEGRAM_PRISMA_CHAT_ID"],
    "HERMES_CONTACT_EMAIL": os.environ["SETUP_CONTACT_EMAIL"],
    "HERMES_UNPAYWALL_EMAIL": os.environ["SETUP_UNPAYWALL_EMAIL"],
    "HERMES_ENABLE_SEMANTIC_SCHOLAR": "1",
    "HERMES_SEMANTIC_SCHOLAR_API_KEY": os.environ["SETUP_SEMANTIC_SCHOLAR_KEY"],
    "HERMES_LENS_API_KEY": os.environ["SETUP_LENS_KEY"],
    "HERMES_NCBI_EMAIL": os.environ["SETUP_NCBI_EMAIL"],
    "HERMES_NCBI_API_KEY": os.environ["SETUP_NCBI_KEY"],
    "HERMES_SCOPUS_API_KEY": os.environ["SETUP_SCOPUS_KEY"],
    "HERMES_ELSEVIER_INST_TOKEN": os.environ["SETUP_ELSEVIER_INST_TOKEN"],
    "HERMES_WOS_API_KEY": os.environ["SETUP_WOS_KEY"],
    "HERMES_EMBASE_API_KEY": os.environ["SETUP_EMBASE_KEY"],
    "HERMES_IEEE_API_KEY": os.environ["SETUP_IEEE_KEY"],
    "HERMES_RESEARCHER_NAME": os.environ["SETUP_RESEARCHER_NAME"],
    "HERMES_RESEARCHER_EMAIL": os.environ["SETUP_RESEARCHER_EMAIL"],
    "HERMES_RESEARCHER_ORCID": os.environ["SETUP_RESEARCHER_ORCID"],
    "HERMES_ADJUDICATION_SECRET": os.environ["SETUP_ADJUDICATION_SECRET"],
    "HERMES_ADJUDICATION_ALLOWED_USERS": os.environ["SETUP_ADJUDICATION_ALLOWED_USERS"],
    "HERMES_DOCLING_API_KEY": os.environ["SETUP_DOCLING_API_KEY"],
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

unset SETUP_API_KEY SETUP_TELEGRAM_TOKEN SETUP_SEMANTIC_SCHOLAR_KEY SETUP_LENS_KEY SETUP_NCBI_KEY
unset SETUP_SCOPUS_KEY SETUP_ELSEVIER_INST_TOKEN SETUP_WOS_KEY SETUP_EMBASE_KEY SETUP_IEEE_KEY
unset SETUP_ADJUDICATION_SECRET SETUP_DOCLING_API_KEY
pass "Configuración guardada en .env con permisos 600"
printf '\nSiguientes pasos:\n'
printf '  ./hermes-research doctor\n'
printf '  ./hermes-research up\n'
printf '  ./hermes-research capability-test\n'
printf '  ./hermes-research multimodal-test\n'
printf '  ./hermes-research smoke-test\n'
