#!/usr/bin/env bash
set -euo pipefail

# Clean-room validator for Hermes Research Pack.
#
# The goal is to answer a simple product question:
# "If I copy this bundle to a fresh folder, does it still install and build?"
#
# This validator intentionally avoids starting Telegram-connected containers,
# because doing so would conflict with a live bot session on the maintainer's
# machine. Instead, it verifies the clean copy, the seeded runtime structure,
# compose rendering, and the autonomous Docker build path.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
umask 077

tmp_root=""
build_log=""
cleanup() {
  if [[ -n "${build_log}" && -f "${build_log}" ]]; then
    rm -f "${build_log}"
  fi
  if [[ -n "${tmp_root}" && -d "${tmp_root}" ]]; then
    find "${tmp_root}" -depth -delete
  fi
}
trap cleanup EXIT

section "Prerequisites"
require_command docker
require_command python3
require_command rsync
pass "Shell dependencies are available"

section "Create a clean-room copy"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/hermes-research-pack-cleanroom.XXXXXX")"
cleanroom_dir="${tmp_root}/hermes-research-pack"

# Copy the distributable package only. We intentionally exclude local runtime
# state, bytecode caches, and the maintainer's private .env file.
rsync -a \
  --exclude '.env' \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude 'dist/' \
  --exclude 'runtime/' \
  --exclude 'Hermes/' \
  --exclude 'landing/' \
  --exclude 'Dockerfile' \
  --exclude 'nginx.conf' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache/' \
  --exclude '.coverage' \
  --exclude 'htmlcov/' \
  --exclude 'output/' \
  --exclude '.playwright-cli/' \
  "${ROOT_DIR}/" "${cleanroom_dir}/"
pass "A clean-room package copy was created"

section "Seed an inert environment file"
cp "${cleanroom_dir}/.env.example" "${cleanroom_dir}/.env"
pass "A credential-free .env was created"

section "Install the clean-room copy"
bash "${cleanroom_dir}/install.sh" >/dev/null
pass "install.sh completed inside the clean-room copy"

section "Validate seeded runtime paths"
[[ -f "${cleanroom_dir}/runtime/hermes-home/bin/start-gateway.sh" ]] || fail "Missing seeded start-gateway.sh in clean-room runtime"
[[ -d "${cleanroom_dir}/runtime/workspace/systematic-review-template" ]] || fail "Missing runtime template in clean-room workspace"
pass "Seeded runtime paths look correct"

section "Render compose in the clean-room copy"
docker compose -f "${cleanroom_dir}/docker-compose.research.yml" --profile docling config >/dev/null
pass "docker-compose.research.yml and its Docling profile render correctly in the clean-room copy"

section "Build the public image from the clean-room copy"
image_name="hermes-agent-local:${HERMES_IMAGE_TAG:-v2026.7.20-public}"
build_log="$(mktemp "${TMPDIR:-/tmp}/hermes-research-pack-build.XXXXXX")"
if docker compose -f "${cleanroom_dir}/docker-compose.research.yml" build hermes >"${build_log}" 2>&1; then
  pass "The clean-room copy can build the public Hermes image from scratch"
elif docker image inspect "${image_name}" >/dev/null 2>&1; then
  warn "Docker build failed in clean-room validation, but ${image_name} already exists locally. Continuing with the cached image."
else
  cat "${build_log}" >&2
  fail "The clean-room copy could not build the public Hermes image"
fi
rm -f "${build_log}"
build_log=""

section "Validate runtime binaries inside the built image"
docker run --rm --entrypoint bash "${image_name}" -lc \
  "test \"\$(id -u):\$(id -g)\" = '1000:1000' && \
   command -v python3 >/dev/null && \
   command -v pdftotext >/dev/null && \
   command -v pandoc >/dev/null && \
   command -v latexmk >/dev/null && \
   command -v xelatex >/dev/null && \
   command -v rsvg-convert >/dev/null && \
   ! command -v gcc >/dev/null && \
   ! command -v git >/dev/null"
pass "The built image includes the runtime binaries required by the research workflow"

printf '\nClean-room validation finished successfully.\n'
