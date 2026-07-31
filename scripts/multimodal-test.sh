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
docker exec "${HERMES_CONTAINER}" \
  python3 \
  /opt/data/skills/research/prisma-systematic-review/scripts/verify_multimodal_pdf.py
pass "PDF extraction, page rendering, and all approved visual models passed"
