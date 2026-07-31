"""Repository-level regression tests for public releases."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_publication_metadata_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate-publication-metadata.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_plugin_declares_a_standalone_package() -> None:
    manifest = (
        ROOT / "seed" / "hermes-home" / "plugins" / "hermes_research" / "plugin.yaml"
    ).read_text(encoding="utf-8")
    assert re.search(r"^kind:\s*standalone\s*$", manifest, flags=re.MULTILINE)


def test_release_builder_excludes_local_state_and_secrets() -> None:
    release_script = (ROOT / "scripts" / "release-bundle.sh").read_text(encoding="utf-8")
    for exclusion in (".env", ".git/", "dist/", "runtime/", "__pycache__/"):
        assert f"--exclude '{exclusion}'" in release_script


def test_runtime_does_not_replace_hermes_core_modules() -> None:
    dockerfile = (ROOT / "Dockerfile.research").read_text(encoding="utf-8")
    forbidden = (
        "build/overrides/hermes_cli",
        "build/overrides/gateway",
    )
    assert all(path not in dockerfile for path in forbidden)
    assert not (ROOT / "build" / "overrides").exists()
