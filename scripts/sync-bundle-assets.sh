#!/usr/bin/env bash
set -euo pipefail

# Refresh generated bundle metadata and an already-installed local runtime.
#
# The repository is the public source of truth. This script deliberately avoids
# maintainer-specific parent folders so a contributor can run it from any clone.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_SEED_HOME="${ROOT_DIR}/seed/hermes-home"

command -v rsync >/dev/null 2>&1 || {
  printf '[FAIL] Missing required command: rsync\n' >&2
  exit 1
}

[[ -f "${TARGET_SEED_HOME}/plugins/hermes_research/plugin.yaml" ]] || {
  printf '[FAIL] The bundled Hermes Research plugin is incomplete\n' >&2
  exit 1
}

printf '[INFO] Rebuilding research skill manifest\n'
ROOT_DIR="${ROOT_DIR}" python3 - <<'PY'
from pathlib import Path
import json
import os

package_root = Path(os.environ["ROOT_DIR"])
root = package_root / "seed" / "hermes-home" / "skills" / "research"
target = package_root / "skills" / "research-manifest.json"

entries = []
for skill_dir in sorted(path for path in root.iterdir() if path.is_dir()):
    scripts = sorted(
        str(path.relative_to(root))
        for path in skill_dir.rglob("*.py")
        if not any(part.startswith(".") or part == "__pycache__" for part in path.parts)
    )
    references = sorted(
        str(path.relative_to(root))
        for path in skill_dir.rglob("*.md")
        if path.name != "SKILL.md"
        and not any(part.startswith(".") or part == "__pycache__" for part in path.parts)
    )
    entries.append(
        {
            "name": skill_dir.name,
            "has_skill": (skill_dir / "SKILL.md").exists(),
            "script_count": len(scripts),
            "scripts": scripts,
            "reference_count": len(references),
        }
    )

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

printf '[INFO] Refreshing runtime template copy\n'
if [[ -d "${ROOT_DIR}/runtime/workspace" ]]; then
  rm -rf "${ROOT_DIR}/runtime/workspace/systematic-review-template"
  cp -R "${ROOT_DIR}/templates/systematic-review-template" "${ROOT_DIR}/runtime/workspace/systematic-review-template"
fi

printf '[INFO] Refreshing runtime Hermes home seed copy\n'
if [[ -d "${ROOT_DIR}/runtime/hermes-home" ]]; then
  # Never replace the bind-mount root while containers are running. Updating
  # in place preserves the inode mounted at /opt/data and keeps live workers
  # able to write logs, cron state, and Kanban databases.
  rsync -a \
    --exclude '.env' \
    --exclude 'config.yaml' \
    --exclude 'cron/' \
    --exclude 'logs/' \
    --exclude 'kanban/' \
    --exclude 'sessions/' \
    --exclude 'watchdog/' \
    --exclude 'home/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "${TARGET_SEED_HOME}/" "${ROOT_DIR}/runtime/hermes-home/"
fi

printf '[PASS] Bundle assets are synchronized\n'
