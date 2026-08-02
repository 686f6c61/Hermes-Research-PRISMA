#!/usr/bin/env bash
set -euo pipefail

# Build and audit the exact runtime image that will support the public bundle.
# Unfixed operating-system findings are recorded in the SBOM but do not block a
# release; a HIGH or CRITICAL finding with an available fix does.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
umask 077

section "Prerequisites"
require_command docker
require_command trivy
pass "Docker and Trivy are available"

version="$(package_version)"
image_name="hermes-agent-local:${HERMES_IMAGE_TAG:-v2026.7.20-public}"
report_dir="${ROOT_DIR}/dist/security"
mkdir -p "${report_dir}"

section "Build runtime image"
docker compose -f "${ROOT_DIR}/docker-compose.research.yml" build hermes
pass "The pinned runtime image was built"

section "Scan repository for secrets"
trivy fs \
  --scanners secret \
  --exit-code 1 \
  --skip-dirs .git \
  --skip-dirs .venv \
  --skip-dirs dist \
  --skip-dirs Hermes \
  --skip-dirs node_modules \
  --skip-dirs runtime \
  --skip-dirs tmp \
  --skip-dirs output \
  --skip-dirs venv \
  --skip-dirs workspace \
  --skip-dirs .playwright-cli \
  --skip-files .env \
  "${ROOT_DIR}" >/dev/null
pass "No secret pattern was detected in the public source tree"

section "Block fixable HIGH and CRITICAL vulnerabilities"
trivy image \
  --scanners vuln \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --exit-code 1 \
  --format json \
  --output "${report_dir}/hermes-research-pack-v${version}-fixable-vulnerabilities.json" \
  "${image_name}"
pass "No fixable HIGH or CRITICAL vulnerability was detected"

section "Generate CycloneDX SBOM"
trivy image \
  --scanners vuln \
  --format cyclonedx \
  --output "${report_dir}/hermes-research-pack-v${version}.cdx.json" \
  "${image_name}"
pass "CycloneDX SBOM written to dist/security/"
