"""Repository-level regression tests for public releases."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

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


def test_setup_guide_has_the_exact_public_name_and_acceptance_contract() -> None:
    guide_path = ROOT / "Setup_Hermes.txt"
    assert guide_path.is_file()
    assert not (ROOT / ("Set" + "ip_Hermes.txt")).exists()
    guide = guide_path.read_text(encoding="utf-8")
    for expected in (
        "HERMES RESEARCH PACK 0.5.1",
        "./hermes-research setup",
        "./hermes-research doctor",
        "./hermes-research capability-test",
        "./hermes-research multimodal-test",
        "./hermes-research smoke-test",
        "TELEGRAM_ALLOWED_USERS",
        "HERMES_UNPAYWALL_EMAIL",
        "HERMES_LENS_API_KEY",
        "https://cloud.nan.builders/r/EQJ5SRFA",
        "Crear cuenta en NaN.builders",
        "tarifa es plana",
        "Inferencia multimodal local",
        "CRITERIO DE ACEPTACION",
    ):
        assert expected in guide
    assert not re.search(r"\bsk-[A-Za-z0-9_-]{20,}\b", guide)
    assert "/Users/" not in guide


def test_setup_and_example_cover_secure_telegram_and_scholarly_sources() -> None:
    setup = (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    doctor = (ROOT / "scripts" / "doctor.sh").read_text(encoding="utf-8")
    for variable in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_HOME_CHANNEL",
        "TELEGRAM_PRISMA_CHAT_ID",
        "HERMES_CONTACT_EMAIL",
        "HERMES_UNPAYWALL_EMAIL",
        "HERMES_SEMANTIC_SCHOLAR_API_KEY",
        "HERMES_LENS_API_KEY",
        "HERMES_NCBI_EMAIL",
        "HERMES_NCBI_API_KEY",
        "HERMES_SCOPUS_API_KEY",
        "HERMES_ELSEVIER_INST_TOKEN",
        "HERMES_WOS_API_KEY",
        "HERMES_EMBASE_API_KEY",
        "HERMES_IEEE_API_KEY",
        "HERMES_RESEARCHER_NAME",
        "HERMES_RESEARCHER_EMAIL",
        "HERMES_ADJUDICATION_SECRET",
    ):
        assert variable in example
        assert variable in setup
        assert variable in doctor


def test_telegram_bootstrap_rejects_a_missing_token_without_leaking_data() -> None:
    env = os.environ.copy()
    env.pop("TELEGRAM_BOT_TOKEN", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "telegram-bootstrap.py"), "identity"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "invalid format" in result.stderr
    assert "api.telegram.org" not in result.stderr


def test_release_builder_excludes_local_state_and_secrets() -> None:
    release_script = (ROOT / "scripts" / "release-bundle.sh").read_text(encoding="utf-8")
    for exclusion in (".env", ".git/", "dist/", "runtime/", "__pycache__/", ".cache/"):
        assert f"--exclude '{exclusion}'" in release_script


def test_release_verifier_drops_operator_credentials_before_execution() -> None:
    verifier = (ROOT / "scripts" / "verify-release-zip.sh").read_text(encoding="utf-8")
    unset_block = verifier.split("unset \\\n", 1)[1].split("\n\n", 1)[0]
    for variable in (
        "TELEGRAM_BOT_TOKEN",
        "HERMES_INFERENCE_API_KEY",
        "HERMES_LENS_API_KEY",
        "HERMES_SCOPUS_API_KEY",
        "HERMES_ADJUDICATION_SECRET",
        "HERMES_ADJUDICATION_ALLOWED_USERS",
    ):
        assert f"  {variable}" in unset_block


def test_runtime_does_not_replace_hermes_core_modules() -> None:
    dockerfile = (ROOT / "Dockerfile.research").read_text(encoding="utf-8")
    forbidden = (
        "build/overrides/hermes_cli",
        "build/overrides/gateway",
    )
    assert all(path not in dockerfile for path in forbidden)
    assert not (ROOT / "build" / "overrides").exists()


def test_plugin_only_test_is_independent_from_private_docling_configuration() -> None:
    script = (ROOT / "scripts" / "plugin-only-test.sh").read_text(encoding="utf-8")
    assert re.search(
        r'export HERMES_DOCLING_API_KEY="\$\{HERMES_DOCLING_API_KEY:-[^}]+\}"',
        script,
    )


def test_runtime_config_uses_the_upstream_public_telegram_menu(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "HERMES_HOME": str(tmp_path),
            "HERMES_INFERENCE_BASE_URL": "https://inference.example.test/v1",
            "HERMES_MODEL_PRIMARY": "primary-test",
            "HERMES_MODEL_VISION": "vision-test",
            "HERMES_MODEL_REVIEW": "review-test",
            "HERMES_TELEGRAM_PUBLIC_MENU_ONLY": "1",
        }
    )

    result = subprocess.run(
        [sys.executable, str(ROOT / "seed/hermes-home/bin/configure-runtime.py")],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    menu = config["platforms"]["telegram"]["extra"]["command_menu"]
    assert menu == {
        "max_commands": 6,
        "priority_mode": "replace",
        "priority": [
            "start",
            "nueva_revision",
            "estado",
            "reanudar",
            "cancelar",
            "ayuda",
        ],
    }


def test_runtime_config_removes_the_public_menu_when_disabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "platforms": {
                    "telegram": {
                        "extra": {
                            "command_menu": {
                                "max_commands": 1,
                                "priority_mode": "replace",
                                "priority": ["start"],
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "HERMES_HOME": str(tmp_path),
            "HERMES_INFERENCE_BASE_URL": "https://inference.example.test/v1",
            "HERMES_MODEL_PRIMARY": "primary-test",
            "HERMES_TELEGRAM_PUBLIC_MENU_ONLY": "0",
        }
    )

    result = subprocess.run(
        [sys.executable, str(ROOT / "seed/hermes-home/bin/configure-runtime.py")],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert "command_menu" not in config["platforms"]["telegram"]["extra"]


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


def test_research_manifest_matches_the_bundled_skill_tree() -> None:
    skill_root = ROOT / "seed/hermes-home/skills/research"
    manifest = json.loads((ROOT / "skills/research-manifest.json").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in manifest}
    expected_names = {path.name for path in skill_root.iterdir() if path.is_dir()}
    assert set(entries) == expected_names

    for name in sorted(expected_names):
        skill_dir = skill_root / name
        scripts = sorted(
            str(path.relative_to(skill_root))
            for path in skill_dir.rglob("*.py")
            if not any(part.startswith(".") or part == "__pycache__" for part in path.parts)
        )
        references = sorted(
            str(path.relative_to(skill_root))
            for path in skill_dir.rglob("*.md")
            if path.name != "SKILL.md"
            and not any(part.startswith(".") or part == "__pycache__" for part in path.parts)
        )
        entry = entries[name]
        assert entry["has_skill"] == (skill_dir / "SKILL.md").exists()
        assert entry["script_count"] == len(scripts)
        assert entry["scripts"] == scripts
        assert entry["reference_count"] == len(references)


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
