#!/usr/bin/env bash
set -euo pipefail

# Create a sanitized distributable ZIP for Hermes Research Pack.
#
# The output intentionally excludes:
# - local .env secrets
# - runtime state and generated review folders
# - bytecode caches and transient build leftovers
#
# The result is a portable archive that another person can unpack and use as
# the public starting point for Hermes Research Mode.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
umask 077

section "Prerequisites"
require_command rsync
require_command zip
pass "Shell dependencies are available"

timestamp="$(date +%Y%m%d-%H%M%S)"
version="$(package_version)"
release_root="${ROOT_DIR}/dist"
staging_dir="${release_root}/staging/hermes-research-pack"
zip_path="${release_root}/hermes-research-pack-v${version}-${timestamp}.zip"
sha_path="${zip_path}.sha256"
keep_staging="${KEEP_STAGING:-0}"

section "Prepare staging directory"
rm -rf "${staging_dir}"
mkdir -p "${staging_dir}"

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
  --exclude '.cache/' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache/' \
  --exclude '.coverage' \
  --exclude 'htmlcov/' \
  --exclude 'output/' \
  --exclude '.playwright-cli/' \
  --exclude '.DS_Store' \
  "${ROOT_DIR}/" "${staging_dir}/"
pass "A sanitized staging copy was created"

section "Write release notes"
cat > "${staging_dir}/RELEASE-NOTES.md" <<EOF
# Hermes Research Pack Release

- Version: ${version}
- Built at: ${timestamp}
- Secrets included: no
- Runtime state included: no
- Installation guide: \`docs/installation.md\`
- Clean-room validation command: \`./hermes-research cleanroom-validate\`
- Role capability test command: \`./hermes-research capability-test\`
- Golden harness test command: \`./hermes-research golden-eval\`
- Structured PDF test command: \`./hermes-research docling-test\`

## First steps

1. Unzip the bundle.
2. Run \`./hermes-research setup\`.
3. Run \`./hermes-research up\`.
4. Run \`./hermes-research smoke-test\`.
5. Start a review from Telegram or the CLI.
EOF
pass "Release notes were added"

section "Write release manifest"
release_commit="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || printf 'unversioned')"
release_dirty="false"
if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain 2>/dev/null || true)" ]]; then
  release_dirty="true"
fi
if [[ "${REQUIRE_CLEAN_RELEASE:-0}" == "1" && "${release_dirty}" == "true" ]]; then
  fail "The source tree has uncommitted changes; official releases require a clean tree"
fi
export RELEASE_BUILT_AT="${timestamp}"
export RELEASE_COMMIT="${release_commit}"
export RELEASE_DIRTY="${release_dirty}"
export RELEASE_VERSION="${version}"
python3 - "${staging_dir}" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
files = []
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    relative = path.relative_to(root).as_posix()
    if relative == "RELEASE-MANIFEST.json":
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    files.append({"path": relative, "sha256": digest, "size": path.stat().st_size})

manifest = {
    "schema_version": 1,
    "package": "hermes-research-pack",
    "version": os.environ["RELEASE_VERSION"],
    "built_at": os.environ["RELEASE_BUILT_AT"],
    "source_commit": os.environ["RELEASE_COMMIT"],
    "source_tree_dirty": os.environ["RELEASE_DIRTY"] == "true",
    "hermes": {
        "ref": "v2026.7.20",
        "commit": "3ef6bbd201263d354fd83ec55b3c306ded2eb72a",
    },
    "file_count": len(files),
    "files": files,
}
(root / "RELEASE-MANIFEST.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
unset RELEASE_BUILT_AT RELEASE_COMMIT RELEASE_DIRTY RELEASE_VERSION
pass "Version, provenance, file sizes, and SHA-256 hashes were recorded"

section "Create ZIP archive"
mkdir -p "${release_root}"
rm -f "${zip_path}"
(
  cd "${release_root}/staging"
  zip -qry "${zip_path}" "hermes-research-pack"
)
pass "Release archive created at ${zip_path}"

section "Write checksum"
(
  cd "${release_root}"
  shasum -a 256 "$(basename "${zip_path}")" > "${sha_path}"
)
pass "SHA-256 checksum written to ${sha_path}"

section "Clean staging directory"
if [[ "${keep_staging}" == "1" ]]; then
  pass "Staging directory preserved because KEEP_STAGING=1"
else
  rm -rf "${release_root}/staging"
  pass "Temporary staging files were removed"
fi

printf '\nRelease bundle ready.\n'
printf 'ZIP: %s\n' "${zip_path}"
printf 'SHA256: %s\n' "${sha_path}"
