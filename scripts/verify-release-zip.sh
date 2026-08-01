#!/usr/bin/env bash
set -euo pipefail

# Verify a generated Hermes Research Pack ZIP as a release artifact.
#
# This script extracts the release archive to a temporary directory, creates an
# inert environment file, runs the installer, and executes the clean-room
# validator. Release verification never copies live credentials.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
umask 077

# Verification executes code from an extracted archive. It must never inherit
# the maintainer's provider, Telegram, institutional, or signing credentials.
unset \
  TELEGRAM_BOT_TOKEN \
  TELEGRAM_ALLOWED_USERS \
  TELEGRAM_HOME_CHANNEL \
  TELEGRAM_PRISMA_CHAT_ID \
  HERMES_INFERENCE_API_KEY \
  HERMES_SEMANTIC_SCHOLAR_API_KEY \
  HERMES_LENS_API_KEY \
  HERMES_NCBI_API_KEY \
  HERMES_SCOPUS_API_KEY \
  HERMES_ELSEVIER_INST_TOKEN \
  HERMES_WOS_API_KEY \
  HERMES_EMBASE_API_KEY \
  HERMES_IEEE_API_KEY \
  HERMES_ADJUDICATION_SECRET \
  HERMES_ADJUDICATION_ALLOWED_USERS

tmp_root=""
cleanup() {
  if [[ -n "${tmp_root}" && -d "${tmp_root}" ]]; then
    find "${tmp_root}" -depth -delete
  fi
}
trap cleanup EXIT

section "Prerequisites"
require_command unzip
require_command python3
pass "Shell dependencies are available"

zip_path="${1:-$(latest_release_zip)}"
[[ -n "${zip_path}" ]] || fail "No release ZIP was provided and none was found in dist/"
[[ -f "${zip_path}" ]] || fail "Release ZIP does not exist: ${zip_path}"

section "Extract the release ZIP"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/hermes-research-pack-release.XXXXXX")"
unzip -q "${zip_path}" -d "${tmp_root}"
release_dir="$(find "${tmp_root}" -maxdepth 1 -type d -name 'hermes-research-pack' | head -n 1)"
[[ -n "${release_dir}" ]] || fail "Could not find hermes-research-pack/ after extracting the ZIP"
pass "Release ZIP extracted to ${release_dir}"

section "Verify release manifest"
python3 - "${release_dir}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
manifest = json.loads((root / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
errors = []
recorded = {item["path"] for item in manifest.get("files", [])}
for item in manifest.get("files", []):
    path = root / item["path"]
    if not path.is_file():
        errors.append(f"missing: {item['path']}")
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != item["sha256"] or path.stat().st_size != item["size"]:
        errors.append(f"mismatch: {item['path']}")
if len(manifest.get("files", [])) != manifest.get("file_count"):
    errors.append("file_count does not match manifest entries")
actual = {
    path.relative_to(root).as_posix()
    for path in root.rglob("*")
    if path.is_file() and path.name != "RELEASE-MANIFEST.json"
}
if recorded != actual:
    for path in sorted(recorded - actual):
        errors.append(f"manifest-only: {path}")
    for path in sorted(actual - recorded):
        errors.append(f"unrecorded: {path}")
if errors:
    raise SystemExit("\n".join(errors))
PY
pass "Every release file matches its recorded size and SHA-256 hash"

section "Seed an inert .env for the extracted copy"
cp "${release_dir}/.env.example" "${release_dir}/.env"
pass "The extracted copy has a credential-free .env"

# The release verifier renders the optional Docling profile without deploying
# it. Keep the required authentication value process-local and non-secret.
export HERMES_DOCLING_API_KEY="${HERMES_DOCLING_API_KEY:-ci-only-docling-key-not-for-runtime-0001}"

section "Install and validate the extracted release"
bash "${release_dir}/install.sh" >/dev/null
(cd "${release_dir}" && ./hermes-research cleanroom-validate >/dev/null)
pass "The extracted release ZIP passed install and clean-room validation"

section "Validate structured-document release contract"
ensure_file "${release_dir}/scripts/docling-test.sh"
ensure_file "${release_dir}/scripts/plugin-only-test.sh"
ensure_file "${release_dir}/evals/fixtures/common/predictions.jsonl"
ensure_file "${release_dir}/evals/golden/social_sciences/gold-records.csv"
ensure_file "${release_dir}/docs/docling.md"
ensure_file "${release_dir}/LICENSE"
ensure_file "${release_dir}/SECURITY.md"
ensure_file "${release_dir}/THIRD_PARTY_NOTICES.md"
ensure_file "${release_dir}/RELEASE-MANIFEST.json"
ensure_file "${release_dir}/seed/hermes-home/skills/research/prisma-systematic-review/scripts/docling_extract.py"
ensure_file "${release_dir}/seed/hermes-home/skills/research/prisma-systematic-review/tests/test_docling_extract.py"
ensure_file "${release_dir}/seed/hermes-home/skills/research/research-network-analysis/scripts/build_network_analysis.py"
ensure_file "${release_dir}/seed/hermes-home/skills/research/research-network-analysis/references/methodology.md"
ensure_file "${release_dir}/build/research-requirements.txt"
docker compose -f "${release_dir}/docker-compose.research.yml" --profile docling config >/dev/null
test_venv="${tmp_root}/release-test-venv"
python3 -m venv "${test_venv}"
"${test_venv}/bin/python" -m pip install --disable-pip-version-check --quiet \
  -r "${release_dir}/build/research-requirements.txt" \
  pytest \
  pyyaml
pytest_log="${tmp_root}/release-pytest.log"
if ! (cd "${release_dir}" && "${test_venv}/bin/python" -m pytest -q >"${pytest_log}" 2>&1); then
  cat "${pytest_log}" >&2
  fail "The extracted release test suite failed"
fi
pass "The extracted release contains and passes the complete public test contract"

printf '\nRelease ZIP verification finished successfully.\n'
printf 'ZIP: %s\n' "${zip_path}"
