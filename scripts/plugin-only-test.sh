#!/usr/bin/env bash
set -euo pipefail

# Prove that the distribution runs against the pinned Hermes source without
# replacing core CLI or gateway modules.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
umask 077

image_ref="${HERMES_IMAGE_REF:-hermes-agent-local:v2026.7.20-public}"
hermes_commit="3ef6bbd201263d354fd83ec55b3c306ded2eb72a"
version="$(package_version)"
skip_build="${1:-}"
host_uid="$(id -u)"
host_gid="$(id -g)"
tmp_root=""

cleanup() {
  if [[ -n "${tmp_root}" && -d "${tmp_root}" ]]; then
    find "${tmp_root}" -depth -delete
  fi
}
trap cleanup EXIT

section "Prerequisites"
require_command cmp
require_command docker
pass "Plugin-only test dependencies are available"

if [[ "${skip_build}" != "--skip-build" ]]; then
  section "Build unmodified upstream runtime"
  docker compose -f "${ROOT_DIR}/docker-compose.research.yml" build hermes >/dev/null
  pass "Runtime image built from the pinned Hermes source"
fi

section "Reject core-module overlays"
if grep -Eq 'COPY[[:space:]]+build/overrides/(hermes_cli|gateway)' "${ROOT_DIR}/Dockerfile.research"; then
  fail "Dockerfile.research still replaces Hermes core modules"
fi
pass "Dockerfile.research does not copy CLI or gateway overlays"

section "Verify pinned runtime modules"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/hermes-plugin-only.XXXXXX")"
mkdir -p "${tmp_root}/home" "${tmp_root}/workspace"

runtime_commit="$(
  docker run --rm --entrypoint cat "${image_ref}" /opt/hermes/.hermes-source-commit
)"
[[ "${runtime_commit}" == "${hermes_commit}" ]] \
  || fail "Runtime image does not contain the pinned Hermes commit"

# These digests belong to the unmodified files at HERMES_COMMIT. Keeping them
# in the test avoids a flaky dependency on GitHub's raw-content rate limit.
docker run --rm --entrypoint sha256sum "${image_ref}" \
  /opt/hermes/hermes_cli/commands.py \
  /opt/hermes/gateway/run.py \
  /opt/hermes/gateway/slash_commands.py >"${tmp_root}/core-modules.sha256"
expected_core_digests="$(
  cat <<'EOF'
41d16ee11e4a358313e3b20bec9a3e243857f6d4a0b969bf26b8f0e7975cde9f  /opt/hermes/hermes_cli/commands.py
c6e0f443772e4a8a7eac0d9ccf9a4f659de5fc5493c572a69a46e4c61a8aa966  /opt/hermes/gateway/run.py
a78f12e9199ffc9c5c0019701cd91da9005bfcdd6c09b0ab0e511c5f567ff60a  /opt/hermes/gateway/slash_commands.py
EOF
)"
cmp <(printf '%s\n' "${expected_core_digests}") "${tmp_root}/core-modules.sha256" \
  || fail "Runtime CLI or gateway modules differ from the pinned upstream files"
pass "CLI and gateway modules match the pinned upstream commit byte for byte"

section "Seed isolated Hermes home"
docker run --rm --user 0:0 --entrypoint sh \
  -e HOST_UID="${host_uid}" \
  -e HOST_GID="${host_gid}" \
  -v "${ROOT_DIR}/seed/hermes-home:/seed:ro" \
  -v "${tmp_root}/home:/opt/data" \
  -v "${tmp_root}/workspace:/workspace" \
  "${image_ref}" \
  -c 'cp -a /seed/. /opt/data/ && chown -R "${HOST_UID}:${HOST_GID}" /opt/data /workspace'
pass "Credential-free plugin home created"

common_run_args=(
  --rm
  --user "${host_uid}:${host_gid}"
  -e HERMES_HOME=/opt/data
  -e HOME=/opt/data/home/default
  -e HERMES_TELEGRAM_PUBLIC_MENU_ONLY=1
  -e HERMES_INFERENCE_API_KEY=test-only
  -v "${tmp_root}/home:/opt/data"
  -v "${tmp_root}/workspace:/workspace"
  "${image_ref}"
)

section "Discover plugin and public commands"
plugin_status="$(
  docker run --entrypoint hermes "${common_run_args[@]}" \
    plugins list --plain --no-bundled
)"
escaped_version="${version//./\\.}"
grep -Eq "^enabled[[:space:]]+user[[:space:]]+${escaped_version}[[:space:]]+hermes_research$" \
  <<<"${plugin_status}" || fail "hermes_research was not enabled"

docker run --entrypoint python "${common_run_args[@]}" -c '
from hermes_cli.plugins import discover_plugins, get_plugin_commands

discover_plugins(force=True)
commands = get_plugin_commands()
expected = {"research", "nueva_revision", "estado", "reanudar", "cancelar", "ayuda"}
missing = sorted(expected - set(commands))
if missing:
    raise SystemExit(f"Missing plugin commands: {missing}")
'
pass "Hermes loaded every public command through the plugin API"

section "Exercise gateway hook"
docker run --entrypoint python "${common_run_args[@]}" -c '
from types import SimpleNamespace
from hermes_cli.plugins import discover_plugins, invoke_hook

discover_plugins(force=True)
event = SimpleNamespace(
    text="/start@research_bot",
    source=SimpleNamespace(
        platform=SimpleNamespace(value="telegram"),
        chat_id="123",
        user_id="456",
    ),
)
expected = {
    "action": "rewrite",
    "text": "/research help --binding telegram:123:456",
}
results = invoke_hook(
    "pre_gateway_dispatch",
    event=event,
    gateway=None,
    session_store=None,
)
if expected not in results:
    raise SystemExit(f"Unexpected hook results: {results!r}")
'
pass "The official pre_gateway_dispatch hook owns the public /start flow"

section "Start upstream gateway"
gateway_log="${tmp_root}/gateway-startup.log"
set +e
docker run --entrypoint /usr/bin/timeout "${common_run_args[@]}" \
  8 hermes gateway >"${gateway_log}" 2>&1
gateway_exit=$?
set -e
if [[ "${gateway_exit}" -ne 0 && "${gateway_exit}" -ne 124 ]]; then
  cat "${gateway_log}" >&2
  fail "Upstream gateway exited unexpectedly with code ${gateway_exit}"
fi
grep -q "Hermes Gateway Starting" "${gateway_log}" \
  || fail "Gateway startup banner was not observed"
grep -q "hermes_research plugin loaded" "${tmp_root}/home/logs/agent.log" \
  || fail "Gateway did not load hermes_research"
if grep -Eq 'Traceback|ERROR .*hermes_research' "${gateway_log}" "${tmp_root}/home/logs/agent.log"; then
  cat "${gateway_log}" >&2
  fail "Gateway startup reported a plugin failure"
fi
pass "Pinned upstream gateway started with hermes_research and no core patch"

printf '\nPlugin-only verification finished successfully.\n'
