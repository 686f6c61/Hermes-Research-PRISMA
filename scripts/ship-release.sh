#!/usr/bin/env bash
set -euo pipefail

# End-to-end release pipeline for Hermes Research Pack.
#
# This maintainer command turns the bundle into a distributable artifact in one
# pass. It intentionally runs the same public checks that a future user should
# trust:
#   1. Sync the bundle assets from the current source tree.
#   2. Build a sanitized ZIP release.
#   3. Verify that ZIP in a fresh temporary folder.
#
# If this script exits successfully, the maintainer gets one release ZIP plus
# its checksum, and both have already passed the package-level validation path.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

section "Prerequisites"
require_command bash
pass "Shell dependencies are available"

section "Sync bundle assets"
bash "${ROOT_DIR}/scripts/sync-bundle-assets.sh"
pass "Bundle assets are synchronized"

section "Run public tests"
python3 -m pytest -q
pass "The public test suite passed"

section "Audit the runtime image"
bash "${ROOT_DIR}/scripts/security-audit.sh"
pass "The image security gate and SBOM generation passed"

section "Create release archive"
bash "${ROOT_DIR}/scripts/release-bundle.sh"

latest_zip="$(latest_release_zip)"
[[ -n "${latest_zip}" ]] || fail "Could not find the newly generated release ZIP"

section "Verify the generated release ZIP"
bash "${ROOT_DIR}/scripts/verify-release-zip.sh" "${latest_zip}"

section "Publish release pointers"
printf '%s\n' "$(basename "${latest_zip}")" > "${ROOT_DIR}/dist/LATEST.txt"
cat "${latest_zip}.sha256" > "${ROOT_DIR}/dist/LATEST_SHA256.txt"
pass "LATEST pointers and checksum were written to dist/"

printf '\nRelease pipeline finished successfully.\n'
printf 'ZIP: %s\n' "${latest_zip}"
printf 'SHA256: %s\n' "${latest_zip}.sha256"
