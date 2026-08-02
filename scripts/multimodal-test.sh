#!/usr/bin/env bash
set -euo pipefail

# Run the image/PDF quality probe in the same container that executes reviews.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
load_env

HERMES_CONTAINER="$(hermes_container_name)"
if ! docker ps --format '{{.Names}}' | grep -qx "${HERMES_CONTAINER}"; then
  fail "${HERMES_CONTAINER} is not running"
fi

section "Scientific PDF and image probe"
SCIENTIFIC_PDF="$(
  docker exec "${HERMES_CONTAINER}" sh -lc \
    'find /workspace -type f -path "*/paper/manuscript/publication-ready.pdf" -printf "%T@ %p\n" 2>/dev/null | sort -nr | head -n 1 | cut -d" " -f2-'
)"
PROBE_COMMAND=(
  python3
  /opt/data/skills/research/prisma-systematic-review/scripts/verify_multimodal_pdf.py
)
if [[ -n "${SCIENTIFIC_PDF}" ]]; then
  REVIEW_DIR="$(dirname "$(dirname "$(dirname "${SCIENTIFIC_PDF}")")")"
  PROBE_OUTPUT="${REVIEW_DIR}/paper/audit/multimodal-pdf-verification.json"
  printf '[INFO] Validating the newest material scientific PDF\n'
  PROBE_COMMAND+=(--pdf "${SCIENTIFIC_PDF}" --output "${PROBE_OUTPUT}")
else
  warn "No completed review PDF exists yet; using the deterministic acceptance fixture"
fi
docker exec "${HERMES_CONTAINER}" "${PROBE_COMMAND[@]}"
pass "PDF extraction, page rendering, and the configured visual role passed"
