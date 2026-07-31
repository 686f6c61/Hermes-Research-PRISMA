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
    for exclusion in (".env", ".git/", "dist/", "runtime/", "__pycache__/", ".cache/"):
        assert f"--exclude '{exclusion}'" in release_script


def test_runtime_does_not_replace_hermes_core_modules() -> None:
    dockerfile = (ROOT / "Dockerfile.research").read_text(encoding="utf-8")
    forbidden = (
        "build/overrides/hermes_cli",
        "build/overrides/gateway",
    )
    assert all(path not in dockerfile for path in forbidden)
    assert not (ROOT / "build" / "overrides").exists()


def test_structural_analysis_is_wired_into_runtime_and_publication_package() -> None:
    autopilot = (
        ROOT
        / "seed/hermes-home/skills/research/prisma-systematic-review/scripts/publication_autopilot.py"
    ).read_text(encoding="utf-8")
    runtime = (
        ROOT
        / "seed/hermes-home/skills/research/prisma-systematic-review/scripts/review_runtime_state.py"
    ).read_text(encoding="utf-8")
    package = (
        ROOT
        / "seed/hermes-home/skills/research/prisma-systematic-review/scripts/package_publication_bundle.py"
    ).read_text(encoding="utf-8")
    assert "build_network_analysis.py" in autopilot
    assert "analysis/atlas/network-atlas.html" in runtime
    assert "analysis/metrics/network-summary.json" in runtime
    assert "analysis_assets" in package
    assert "analysis/atlas/network-atlas.html" in package


def test_research_dependency_is_consistent_across_local_ci_and_container() -> None:
    requirements = (ROOT / "build/research-requirements.txt").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.research").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "networkx==3.6.1" in requirements
    assert "build/research-requirements.txt" in dockerfile
    assert "build/research-requirements.txt" in makefile
    workflow_path = ROOT / ".github/workflows/ci.yml"
    if workflow_path.exists():
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "build/research-requirements.txt" in workflow


def test_landing_publishes_a_complete_structural_atlas_example() -> None:
    # The product landing is deployed from this repository but intentionally
    # excluded from the installable research-pack ZIP.
    if not (ROOT / "landing").is_dir():
        return

    home = (ROOT / "landing/index.html").read_text(encoding="utf-8")
    example = (ROOT / "landing/atlas-estructural.html").read_text(encoding="utf-8")
    atlas = (ROOT / "landing/ejemplos/atlas/network-atlas.html").read_text(
        encoding="utf-8"
    )
    nginx = (ROOT / "nginx.conf").read_text(encoding="utf-8")

    assert 'href="/atlas-estructural.html"' in home
    assert 'href="/ejemplos/atlas/network-atlas.html"' in example
    assert "GEXF · Gephi" in atlas
    assert "downloadPng" in atlas
    assert "downloadSvg" in atlas
    assert "downloadGexf" in atlas
    assert 'href="../data/graph.graphml"' in atlas
    assert "location ^~ /ejemplos/atlas/" in nginx

    for relative in (
        "landing/ejemplos/data/graph.graphml",
        "landing/ejemplos/data/nodes.csv",
        "landing/ejemplos/data/edges.csv",
        "landing/ejemplos/data/studies.csv",
        "landing/ejemplos/figures/png/authors-network.png",
        "landing/ejemplos/figures/png/topics-network.png",
        "landing/ejemplos/figures/svg/authors-network.svg",
        "landing/ejemplos/figures/svg/topics-network.svg",
    ):
        assert (ROOT / relative).is_file(), relative
