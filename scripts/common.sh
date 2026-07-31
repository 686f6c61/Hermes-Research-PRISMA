#!/usr/bin/env bash
set -euo pipefail

# Common helpers shared by the public package scripts. The goal is to keep
# doctor.sh and smoke-test.sh easy to read while centralizing the path and
# environment rules in one place.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

info() {
  printf '[INFO] %s\n' "$*"
}

pass() {
  printf '[PASS] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*"
}

fail() {
  printf '[FAIL] %s\n' "$*" >&2
  exit 1
}

section() {
  printf '\n== %s ==\n' "$*"
}

require_command() {
  local command_name="$1"
  command -v "${command_name}" >/dev/null 2>&1 || fail "Missing required command: ${command_name}"
}

ensure_file() {
  local path="$1"
  [[ -f "${path}" ]] || fail "Missing required file: ${path}"
}

ensure_dir() {
  local path="$1"
  [[ -d "${path}" ]] || fail "Missing required directory: ${path}"
}

ensure_template_dir() {
  local workspace_dir="$1"
  local template_dir="${workspace_dir}/systematic-review-template"
  [[ -d "${template_dir}" ]] || fail "Missing runtime template directory: ${template_dir}"
}

# Load package defaults from .env without replacing variables explicitly
# exported by the caller. This lets operators test a temporary model or path
# without mutating the persistent configuration.
load_env() {
  local env_path="${ROOT_DIR}/.env"
  local line
  local key
  ensure_file "${env_path}"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -n "${line//[[:space:]]/}" ]] || continue
    [[ "${line}" != [[:space:]]*#* ]] || continue
    [[ "${line}" == *=* ]] || continue
    key="${line%%=*}"
    key="${key//[[:space:]]/}"
    [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "Invalid key in .env: ${key}"
    if ! declare -p "${key}" >/dev/null 2>&1; then
      eval "export ${line}"
    fi
  done < "${env_path}"
}

# Resolve package-relative paths such as ./runtime/workspace to absolute paths.
# This mirrors how docker-compose interprets relative volume entries.
resolve_package_path() {
  local raw_path="$1"
  if [[ "${raw_path}" = /* ]]; then
    printf '%s\n' "${raw_path}"
  else
    python3 - <<PY
from pathlib import Path
print((Path(${ROOT_DIR@Q}) / Path(${raw_path@Q})).resolve())
PY
  fi
}

docker_compose_cmd() {
  printf 'docker compose -f %q' "${ROOT_DIR}/docker-compose.research.yml"
}

container_mount_matches() {
  local container_name="$1"
  local destination="$2"
  local expected_source="$3"
  local actual_source

  actual_source="$(
    docker inspect "${container_name}" \
      --format "{{range .Mounts}}{{if eq .Destination \"${destination}\"}}{{.Source}}{{end}}{{end}}" 2>/dev/null || true
  )"

  [[ -n "${actual_source}" && "${actual_source}" == "${expected_source}" ]]
}

hermes_container_name() {
  printf '%s\n' "${HERMES_CONTAINER_NAME:-hermes-agent}"
}

hermes_watchdog_container_name() {
  printf '%s\n' "${HERMES_WATCHDOG_CONTAINER_NAME:-hermes-prisma-watchdog}"
}

docling_container_name() {
  printf '%s\n' "${DOCLING_CONTAINER_NAME:-hermes-docling}"
}

package_version() {
  ensure_file "${ROOT_DIR}/VERSION"
  tr -d '[:space:]' < "${ROOT_DIR}/VERSION"
}

latest_release_zip() {
  local candidate=""
  local newest=""
  shopt -s nullglob
  for candidate in "${ROOT_DIR}"/dist/hermes-research-pack-v*.zip; do
    if [[ -z "${newest}" || "${candidate}" -nt "${newest}" ]]; then
      newest="${candidate}"
    fi
  done
  shopt -u nullglob
  printf '%s\n' "${newest}"
}
