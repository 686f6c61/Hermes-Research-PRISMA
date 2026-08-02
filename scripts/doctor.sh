#!/usr/bin/env bash
set -euo pipefail

# Hermes Research Pack doctor.
# This script answers one question before a user launches a real review:
# "Is this installation structurally healthy enough to start?"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

section "Shell prerequisites"
require_command docker
require_command python3
pass "Docker and Python are available"

section "Package structure"
ensure_file "${ROOT_DIR}/docker-compose.research.yml"
ensure_file "${ROOT_DIR}/Dockerfile.research"
ensure_file "${ROOT_DIR}/.env.example"
ensure_file "${ROOT_DIR}/install.sh"
ensure_file "${ROOT_DIR}/scripts/capability-test.sh"
ensure_file "${ROOT_DIR}/scripts/docling-test.sh"
ensure_file "${ROOT_DIR}/scripts/telegram-bootstrap.py"
ensure_file "${ROOT_DIR}/Setup_Hermes.txt"
pass "Core package files are present"

section "Environment file"
load_env
pass ".env loaded successfully"

INSTALL_MODE="${HERMES_INSTALL_MODE:-both}"
case "${INSTALL_MODE}" in
  cli|telegram|both) ;;
  *) fail "HERMES_INSTALL_MODE must be cli, telegram, or both" ;;
esac
if [[ "${INSTALL_MODE}" != "cli" && -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  fail "TELEGRAM_BOT_TOKEN is required for ${INSTALL_MODE} mode"
fi
if [[ "${INSTALL_MODE}" != "cli" ]]; then
  [[ -n "${TELEGRAM_ALLOWED_USERS:-}" ]] ||
    fail "TELEGRAM_ALLOWED_USERS is required for ${INSTALL_MODE} mode"
  [[ "${TELEGRAM_ALLOWED_USERS}" =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ ]] ||
    fail "TELEGRAM_ALLOWED_USERS must contain positive numeric IDs separated by commas"
  [[ -n "${TELEGRAM_HOME_CHANNEL:-}" ]] ||
    fail "TELEGRAM_HOME_CHANNEL is required so the watchdog can deliver notifications"
  [[ "${TELEGRAM_HOME_CHANNEL}" =~ ^[1-9][0-9]*$ ]] ||
    fail "TELEGRAM_HOME_CHANNEL must be a positive private-chat ID"
  [[ "${TELEGRAM_PRISMA_CHAT_ID:-${TELEGRAM_HOME_CHANNEL}}" =~ ^[1-9][0-9]*$ ]] ||
    fail "TELEGRAM_PRISMA_CHAT_ID must be a positive private-chat ID"
fi
[[ -n "${HERMES_INFERENCE_API_KEY:-}" ]] || fail "HERMES_INFERENCE_API_KEY is empty in .env"
[[ -n "${HERMES_INFERENCE_BASE_URL:-}" ]] || fail "HERMES_INFERENCE_BASE_URL is empty in .env"
[[ -n "${HERMES_MODEL_PRIMARY:-}" ]] || fail "HERMES_MODEL_PRIMARY is empty in .env"
[[ -n "${HERMES_MODEL_VISION:-}" ]] || fail "HERMES_MODEL_VISION is empty in .env"
[[ -n "${HERMES_MODEL_REVIEW:-}" ]] || fail "HERMES_MODEL_REVIEW is empty in .env"
[[ -n "${HERMES_RESEARCHER_NAME:-}" ]] || fail "HERMES_RESEARCHER_NAME is empty in .env"
[[ -n "${HERMES_RESEARCHER_EMAIL:-}" ]] || fail "HERMES_RESEARCHER_EMAIL is empty in .env"
[[ "${HERMES_RESEARCHER_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] ||
  fail "HERMES_RESEARCHER_EMAIL is not a valid email address"
[[ -n "${HERMES_ADJUDICATION_SECRET:-}" ]] || fail "HERMES_ADJUDICATION_SECRET is empty in .env"
[[ -n "${HERMES_DOCLING_API_KEY:-}" ]] || fail "HERMES_DOCLING_API_KEY is empty in .env"
[[ "${#HERMES_ADJUDICATION_SECRET}" -ge 32 ]] ||
  fail "HERMES_ADJUDICATION_SECRET must contain at least 32 characters"
[[ "${#HERMES_DOCLING_API_KEY}" -ge 32 ]] ||
  fail "HERMES_DOCLING_API_KEY must contain at least 32 characters"
pass "Mode, provider, researcher identity, models, and required secrets are configured"

section "Scholarly source configuration"
[[ -n "${HERMES_CONTACT_EMAIL:-}" ]] ||
  fail "HERMES_CONTACT_EMAIL is required for scholarly API identification"
[[ "${HERMES_CONTACT_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] ||
  fail "HERMES_CONTACT_EMAIL is not a valid email address"
pass "A private contact email is configured for polite scholarly API access"
if [[ -n "${HERMES_UNPAYWALL_EMAIL:-}" ]]; then
  [[ "${HERMES_UNPAYWALL_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] ||
    fail "HERMES_UNPAYWALL_EMAIL is not a valid email address"
  pass "Unpaywall full-text resolution is configured"
else
  warn "Unpaywall is disabled because HERMES_UNPAYWALL_EMAIL is empty"
fi
if [[ -n "${HERMES_OPENALEX_API_KEY:-}" ]]; then
  pass "OpenAlex authenticated access is configured"
else
  warn "OpenAlex will use its small anonymous daily budget; configure HERMES_OPENALEX_API_KEY for full reviews"
fi
if [[ -n "${HERMES_SEMANTIC_SCHOLAR_API_KEY:-}" ]]; then
  pass "Semantic Scholar authenticated access is configured"
elif [[ "${HERMES_ENABLE_SEMANTIC_SCHOLAR:-0}" == "1" ]]; then
  warn "Semantic Scholar is enabled without an API key and may be rate limited"
else
  warn "Semantic Scholar is disabled"
fi
if [[ -n "${HERMES_LENS_API_KEY:-}" ]]; then
  pass "Lens Scholarly API access is configured"
else
  warn "Lens will be skipped because HERMES_LENS_API_KEY is empty"
fi
if [[ -n "${HERMES_NCBI_EMAIL:-}" ]]; then
  [[ "${HERMES_NCBI_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] ||
    fail "HERMES_NCBI_EMAIL is not a valid email address"
  if [[ -n "${HERMES_NCBI_API_KEY:-}" ]]; then
    pass "NCBI/PubMed contact and authenticated access are configured"
  else
    pass "NCBI/PubMed contact is configured without an optional API key"
  fi
else
  warn "NCBI/PubMed will use unauthenticated access"
fi
for institutional_source in \
  "Scopus:HERMES_SCOPUS_API_KEY" \
  "Web of Science:HERMES_WOS_API_KEY" \
  "Embase:HERMES_EMBASE_API_KEY" \
  "IEEE Xplore:HERMES_IEEE_API_KEY"
do
  source_name="${institutional_source%%:*}"
  variable_name="${institutional_source##*:}"
  if [[ -n "${!variable_name:-}" ]]; then
    pass "${source_name} institutional adapter is configured"
  else
    warn "${source_name} is not configured; the open-source search plan remains available"
  fi
done
if [[ -n "${HERMES_ELSEVIER_INST_TOKEN:-}" ]]; then
  pass "Elsevier institutional entitlement token is configured for Scopus/Embase"
else
  warn "No Elsevier institutional token is configured; API-key entitlements alone will be used"
fi

section "Host directories"
DATA_DIR="$(resolve_package_path "${HERMES_DATA_DIR:-./runtime/hermes-home}")"
WORKSPACE_DIR="$(resolve_package_path "${HERMES_WORKSPACE_DIR:-./runtime/workspace}")"
OBSIDIAN_DIR="$(resolve_package_path "${OBSIDIAN_VAULT_HOST_PATH:-./runtime/obsidian}")"
HERMES_CONTAINER="$(hermes_container_name)"
WATCHDOG_CONTAINER="$(hermes_watchdog_container_name)"
DOCLING_CONTAINER="$(docling_container_name)"

ensure_dir "${DATA_DIR}"
ensure_dir "${WORKSPACE_DIR}"
ensure_dir "${OBSIDIAN_DIR}"
pass "Runtime directories exist"

section "Writable runtime state"
for state_dir in \
  cron \
  logs \
  kanban/boards \
  kanban/logs \
  kanban/workspaces \
  sessions \
  watchdog \
  home/default/tmp
do
  ensure_dir "${DATA_DIR}/${state_dir}"
done
pass "Cron, logging, Kanban, sessions, watchdog, and temporary state directories exist"

section "Runtime seed"
ensure_dir "${ROOT_DIR}/seed/hermes-home"
ensure_file "${DATA_DIR}/bin/start-gateway.sh"
ensure_file "${DATA_DIR}/bin/start-watchdog.sh"
ensure_file "${DATA_DIR}/bin/prisma-watchdog.py"
ensure_file "${DATA_DIR}/config.yaml"
ensure_dir "${DATA_DIR}/skills/research"
ensure_dir "${DATA_DIR}/plugins/hermes_research"
pass "Runtime Hermes home is seeded with the minimum public payload"

section "Research plugin contract"
grep -q 'hermes_research' "${DATA_DIR}/config.yaml" || fail "hermes_research is not enabled in runtime config"
pass "hermes_research is enabled in runtime config"

section "Bundled template"
ensure_dir "${ROOT_DIR}/templates/systematic-review-template"
ensure_template_dir "${WORKSPACE_DIR}"
pass "The packaged review template is available and materialized in runtime/workspace"

section "Compose configuration"
if docker compose -f "${ROOT_DIR}/docker-compose.research.yml" config >/dev/null; then
  pass "docker-compose.research.yml renders correctly"
else
  fail "docker-compose.research.yml does not render cleanly"
fi

section "Container health"
if docker ps --format '{{.Names}}' | grep -qx "${HERMES_CONTAINER}"; then
  if container_mount_matches "${HERMES_CONTAINER}" /opt/data "${DATA_DIR}" && container_mount_matches "${HERMES_CONTAINER}" /workspace "${WORKSPACE_DIR}"; then
    pass "${HERMES_CONTAINER} container is running with this bundle's mounts"
    if docker exec "${HERMES_CONTAINER}" sh -c 'test -w /opt/data && test -d /opt/data/cron && test -d /opt/data/logs && test -d /opt/data/kanban' >/dev/null 2>&1; then
      pass "${HERMES_CONTAINER} can write required runtime state"
    else
      fail "${HERMES_CONTAINER} cannot access required writable state under /opt/data; recreate the container"
    fi
  else
    warn "${HERMES_CONTAINER} is running, but it is mounted from another runtime or compose project"
  fi
else
  warn "${HERMES_CONTAINER} is not running yet"
fi

if docker ps --format '{{.Names}}' | grep -qx "${WATCHDOG_CONTAINER}"; then
  if container_mount_matches "${WATCHDOG_CONTAINER}" /opt/data "${DATA_DIR}" && container_mount_matches "${WATCHDOG_CONTAINER}" /workspace "${WORKSPACE_DIR}"; then
    pass "${WATCHDOG_CONTAINER} container is running with this bundle's mounts"
  else
    warn "${WATCHDOG_CONTAINER} is running, but it is mounted from another runtime or compose project"
  fi
else
  warn "${WATCHDOG_CONTAINER} is not running yet"
fi

if docker ps --format '{{.Names}}' | grep -qx "${DOCLING_CONTAINER}"; then
  docling_health="$(docker inspect "${DOCLING_CONTAINER}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
  if [[ "${docling_health}" == "healthy" ]]; then
    pass "${DOCLING_CONTAINER} structured-document worker is healthy"
  else
    warn "${DOCLING_CONTAINER} is running with health state: ${docling_health}"
  fi
else
  warn "${DOCLING_CONTAINER} is not running; PDF processing will use the Poppler fallback"
fi

section "Provider reachability"
require_command curl
API_KEY="${HERMES_INFERENCE_API_KEY}"
API_BASE_URL="${HERMES_INFERENCE_BASE_URL}"
curl_config="$(mktemp)"
models_response="$(mktemp)"
chmod 600 "${curl_config}" "${models_response}"
trap 'rm -f "${curl_config}" "${models_response}"' EXIT
printf 'header = "Authorization: Bearer %s"\n' "${API_KEY}" >"${curl_config}"
printf 'header = "Accept: application/json"\n' >>"${curl_config}"

CLOUD_STATUS="$(curl --silent --show-error --output "${models_response}" \
  --write-out '%{http_code}' --max-time 30 --config "${curl_config}" \
  "${API_BASE_URL%/}/models" || true)"

if [[ "${CLOUD_STATUS}" == "200" ]]; then
  pass "The configured inference endpoint is reachable"
else
  fail "The inference endpoint did not return 200 (status: ${CLOUD_STATUS})"
fi

python3 - "${models_response}" <<'PY'
import json
import os
import pathlib
import sys

required = {
    os.environ["HERMES_MODEL_PRIMARY"],
    os.environ["HERMES_MODEL_VISION"],
    os.environ["HERMES_MODEL_REVIEW"],
}
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
available = {
    str(item.get("id", "")).strip()
    for item in payload.get("data", [])
    if isinstance(item, dict)
}
missing = sorted(required - available)
if missing:
    raise SystemExit(f"Configured models missing from provider catalog: {', '.join(missing)}")
PY
pass "Every configured model is available from the provider"
pass "Model names exist; run capability-test and multimodal-test to prove behavior, not only catalog presence"

section "Public gateway mode"
if [[ "${INSTALL_MODE}" == "cli" ]]; then
  pass "CLI-only mode is enabled; Telegram is intentionally optional"
else
  if TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}" \
    python3 "${ROOT_DIR}/scripts/telegram-bootstrap.py" identity >/dev/null; then
    pass "The Telegram token resolves to a valid bot"
  else
    fail "Telegram could not validate the configured bot token"
  fi
  if TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN}" \
    python3 "${ROOT_DIR}/scripts/telegram-bootstrap.py" \
      check-chat "${TELEGRAM_HOME_CHANNEL}" >/dev/null; then
    pass "The Telegram bot can access the configured notification chat"
  else
    fail "The Telegram bot cannot access TELEGRAM_HOME_CHANNEL"
  fi
  pass "Telegram access is restricted to an explicit numeric allowlist"
  if [[ "${HERMES_TELEGRAM_PUBLIC_MENU_ONLY:-}" == "1" ]]; then
    pass "Public Telegram menu mode is enabled"
  else
    warn "HERMES_TELEGRAM_PUBLIC_MENU_ONLY is not set to 1"
  fi
fi

printf '\nDoctor finished. Resolve every failure and review warnings before capability and smoke tests.\n'
