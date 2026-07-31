#!/usr/bin/env bash
set -euo pipefail

# Hermes Research Pack smoke test.
# This script exercises the public Telegram product flow inside the running
# container and then validates that the expected review artifacts exist on disk.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

section "Prerequisites"
require_command docker
require_command python3
load_env

WORKSPACE_DIR="$(resolve_package_path "${HERMES_WORKSPACE_DIR:-./runtime/workspace}")"
DATA_DIR="$(resolve_package_path "${HERMES_DATA_DIR:-./runtime/hermes-home}")"
HERMES_CONTAINER="$(hermes_container_name)"

docker ps --format '{{.Names}}' | grep -qx "${HERMES_CONTAINER}" || fail "${HERMES_CONTAINER} container is not running"
pass "${HERMES_CONTAINER} container is running"

if container_mount_matches "${HERMES_CONTAINER}" /opt/data "${DATA_DIR}" && container_mount_matches "${HERMES_CONTAINER}" /workspace "${WORKSPACE_DIR}"; then
  pass "${HERMES_CONTAINER} is attached to this bundle's runtime paths"
else
  warn "${HERMES_CONTAINER} is running from another runtime or compose project; this smoke test is not a pure package-only validation"
fi

section "Create a public test review"
timestamp="$(date +%Y%m%d%H%M%S)"
topic="zz public smoke test ${timestamp}"

TEST_OUTPUT="$(docker exec "${HERMES_CONTAINER}" sh -c "python3 - <<'PY'
import asyncio, json, os
from gateway.run import GatewayRunner
from gateway.config import GatewayConfig
from gateway.session import SessionSource, Platform
from gateway.platforms.base import MessageEvent, MessageType

os.environ['HERMES_TELEGRAM_PUBLIC_MENU_ONLY'] = '1'
os.environ['HERMES_RESEARCH_SMOKE_TEST'] = '1'

class DummyAdapter:
    platform = Platform.TELEGRAM
    _pending_messages = {}
    async def send(self, *args, **kwargs):
        return None

runner = GatewayRunner(GatewayConfig())
runner._is_user_authorized = lambda source: True
runner.adapters[Platform.TELEGRAM] = DummyAdapter()
source = SessionSource(
    platform=Platform.TELEGRAM,
    user_id='smoke-test-user',
    chat_id='smoke-test-chat',
    chat_name='dm',
)

def ev(text: str):
    event = MessageEvent(text=text, source=source, message_type=MessageType.TEXT)
    event.platform_update_id = 1
    return event

async def main():
    q1 = await runner._handle_message(ev('/nueva_revision'))
    q2 = await runner._handle_message(ev('${topic}'))
    q3 = await runner._handle_message(ev('2026'))
    q4 = await runner._handle_message(ev('estudios empíricos con PDF'))
    q5 = await runner._handle_message(ev('opiniones o notas breves'))
    q6 = await runner._handle_message(ev('saltar'))
    q7 = await runner._handle_message(ev('saltar'))
    q8 = await runner._handle_message(ev('5'))
    q9 = await runner._handle_message(ev('saltar'))
    q10 = await runner._handle_message(ev('saltar'))
    q11 = await runner._handle_message(ev('saltar'))
    q12 = await runner._handle_message(ev('saltar'))
    summary = await runner._handle_message(ev('sí'))
    create = await runner._handle_message(ev('crear'))
    status = await runner._handle_message(ev('/estado'))
    resume = await runner._handle_message(ev('/reanudar'))
    print(json.dumps({
        'q1': q1,
        'q2': q2,
        'q3': q3,
        'q4': q4,
        'q5': q5,
        'q6': q6,
        'q7': q7,
        'q8': q8,
        'q9': q9,
        'q10': q10,
        'q11': q11,
        'q12': q12,
        'summary': summary,
        'create': create,
        'status': status,
        'resume': resume,
    }, ensure_ascii=False))

asyncio.run(main())
PY")"

# Parse the structured output outside Docker so the shell script can fail with
# a readable message if any public command stops behaving as expected.
TEST_OUTPUT="${TEST_OUTPUT}" python3 - <<'PY'
import json, os
payload = json.loads(os.environ["TEST_OUTPUT"])
print("[INFO] Public create response captured")
print("[INFO] Public status response captured")
print("[INFO] Public resume response captured")
if "He creado la revisión" not in payload["create"]:
    raise SystemExit("Smoke test failed: create response did not confirm review creation")
if "Resumen antes de crear" not in payload["summary"]:
    raise SystemExit("Smoke test failed: wizard did not show the confirmation summary")
if "**Revisión activa:**" not in payload["status"]:
    raise SystemExit("Smoke test failed: status response did not expose the active review")
if "ya está en marcha" not in payload["resume"] and "He reanudado" not in payload["resume"]:
    raise SystemExit("Smoke test failed: resume response was not deterministic")
PY
pass "Public Telegram flow responded as expected"

section "Locate host-side artifacts"
review_dir="$(find "${WORKSPACE_DIR}" -maxdepth 1 -type d -name "systematic-review-zz-public-smoke-test-${timestamp}-2026-n5*" | sort | head -n 1)"
[[ -n "${review_dir}" ]] || fail "Could not find the smoke-test review directory on the host"
pass "Review directory created at ${review_dir}"

ensure_file "${review_dir}/protocol/intake.md"
ensure_file "${review_dir}/protocol/research-question.md"
ensure_file "${review_dir}/protocol/eligibility-criteria.md"
ensure_file "${review_dir}/protocol/search-strategy.md"
ensure_file "${review_dir}/notes/runtime-state.json"
ensure_file "${review_dir}/notes/public-autonomous.pid"
pass "Initial protocol artifacts exist"

section "Wait for autonomous background work"
# The public smoke test should verify that autonomous continuation starts
# reliably. It should not fail just because external sources or DOI work
# have not completed yet.
deadline=$((SECONDS + 20))
while [[ ${SECONDS} -lt ${deadline} ]]; do
  if docker exec "${HERMES_CONTAINER}" sh -c "ps -ef | grep -q '${review_dir##*/}'"; then
    break
  fi
  sleep 2
done

docker exec "${HERMES_CONTAINER}" sh -c "ps -ef | grep -q '${review_dir##*/}'" || fail "Autonomous background process did not start"
pass "Autonomous background process started"

deadline=$((SECONDS + 90))
while [[ ${SECONDS} -lt ${deadline} ]]; do
  if [[ -f "${review_dir}/searches/search-log.csv" && -f "${review_dir}/records/master-records.csv" ]]; then
    break
  fi
  sleep 2
done

ensure_file "${review_dir}/searches/search-log.csv"
ensure_file "${review_dir}/records/master-records.csv"
pass "Search and master-record placeholders exist"

# Rows beyond the header are a bonus at this stage. They show that the first
# autonomous loop is already advancing, but they are not required for a fast
# installation smoke test.
search_lines="$(wc -l < "${review_dir}/searches/search-log.csv" | tr -d ' ')"
master_lines="$(wc -l < "${review_dir}/records/master-records.csv" | tr -d ' ')"
if [[ "${search_lines}" -gt 1 || "${master_lines}" -gt 1 ]]; then
  pass "Autonomous loop has already written data rows"
else
  warn "Autonomous loop started, but data rows are not written yet. This can be normal on the first cycle."
fi

printf '\nSmoke test finished successfully.\n'
printf 'Review under test: %s\n' "${review_dir}"
