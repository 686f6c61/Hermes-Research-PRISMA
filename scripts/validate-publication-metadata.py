#!/usr/bin/env python3
"""Validate the metadata that identifies a public Hermes Research release."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _match(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Could not read {label}.")
    return match.group(1).strip().strip("\"'")


def main() -> int:
    """Fail when release metadata disagrees across public entry points."""
    version = _read("VERSION").strip()
    plugin_version = _match(
        r"^version:\s*(.+)$",
        _read("seed/hermes-home/plugins/hermes_research/plugin.yaml"),
        "plugin version",
    )
    citation_version = _match(
        r"^version:\s*(.+)$",
        _read("CITATION.cff"),
        "citation version",
    )
    expected_heading = f"## {version} - "
    changelog = _read("CHANGELOG.md")

    errors = []
    for label, candidate in (
        ("plugin.yaml", plugin_version),
        ("CITATION.cff", citation_version),
    ):
        if candidate != version:
            errors.append(f"{label} declares {candidate}; VERSION declares {version}.")
    if expected_heading not in changelog:
        errors.append(f"CHANGELOG.md has no release heading for {version}.")

    required_files = (
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "SUPPORT.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "CITATION.cff",
        "THIRD_PARTY_NOTICES.md",
    )
    for relative_path in required_files:
        if not (ROOT / relative_path).is_file():
            errors.append(f"Missing public project file: {relative_path}.")

    if errors:
        raise SystemExit("\n".join(errors))

    print(f"Publication metadata is consistent for version {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
