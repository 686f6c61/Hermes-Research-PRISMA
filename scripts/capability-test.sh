#!/usr/bin/env bash
set -euo pipefail

# Exercise each configured model against the capability required by its role.
# This is intentionally separate from doctor.sh because it spends inference.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_env

HERMES_CONTAINER="$(hermes_container_name)"
OUTPUT_NAME="hermes-model-capabilities-$RANDOM.json"
HOST_OUTPUT="$(mktemp "${TMPDIR:-/tmp}/${OUTPUT_NAME}.XXXXXX")"
trap 'rm -f "${HOST_OUTPUT}"' EXIT

section "Role-aware model capabilities"
CONTAINER_PROBE="/opt/data/skills/research/prisma-systematic-review/scripts/model_capability_probe.py"
if docker ps --format '{{.Names}}' | grep -qx "${HERMES_CONTAINER}" \
  && docker exec "${HERMES_CONTAINER}" test -f "${CONTAINER_PROBE}"; then
  CONTAINER_OUTPUT="/tmp/${OUTPUT_NAME}"
  docker exec "${HERMES_CONTAINER}" \
    python3 \
    "${CONTAINER_PROBE}" \
    --live \
    --output "${CONTAINER_OUTPUT}"
  docker exec "${HERMES_CONTAINER}" cat "${CONTAINER_OUTPUT}" >"${HOST_OUTPUT}"
  docker exec "${HERMES_CONTAINER}" rm -f "${CONTAINER_OUTPUT}"
else
  if docker ps --format '{{.Names}}' | grep -qx "${HERMES_CONTAINER}"; then
    warn "The running container predates the capability probe; using the bundled host copy"
  fi
  python3 \
    "${ROOT_DIR}/seed/hermes-home/skills/research/prisma-systematic-review/scripts/model_capability_probe.py" \
    --live \
    --output "${HOST_OUTPUT}"
fi

python3 - "${HOST_OUTPUT}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for role in payload.get("roles", []):
    capabilities = ", ".join(role.get("required_capabilities", []))
    print(
        f"[{str(role.get('status', '')).upper()}] "
        f"{role.get('role')}: {role.get('requested_model')} ({capabilities})"
    )
    for test in role.get("tests", []):
        print(f"  - {test.get('capability')}: {test.get('status')}")
if payload.get("status") != "pass":
    raise SystemExit("At least one configured role failed its live capability contract.")
PY

pass "Primary and review models returned valid text/JSON with the requested identity"
printf '\nRun ./hermes-research multimodal-test to validate the visual role with a rendered scientific page.\n'
