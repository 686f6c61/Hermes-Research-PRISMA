"""Tests for the public command wrapper contract."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest


def load_public_cli():
    """Load the extensionless CLI script as a normal Python module."""

    package_root = Path(__file__).resolve().parents[5]
    cli_path = package_root / "hermes-research"
    loader = importlib.machinery.SourceFileLoader("hermes_research_public_cli", str(cli_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("37", "37"),
        ("23-63", "23-63"),
        ("23 – 63", "23-63"),
    ],
)
def test_final_n_accepts_exact_and_ranged_targets(raw: str, expected: str) -> None:
    cli = load_public_cli()
    assert cli.validate_final_n(raw) == expected


@pytest.mark.parametrize("raw", ["", "0", "63-23", "twenty"])
def test_final_n_rejects_invalid_targets(raw: str) -> None:
    cli = load_public_cli()
    with pytest.raises(SystemExit):
        cli.validate_final_n(raw)


def test_parser_preserves_ranged_final_n() -> None:
    cli = load_public_cli()
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "init",
            "--topic",
            "AI systems",
            "--years",
            "2024-2026",
            "--include",
            "full-text empirical studies",
            "--exclude",
            "opinion pieces",
            "--final-n",
            "23-63",
        ]
    )
    assert cli.collect_init_payload(args)["final_n"] == "23-63"


def test_fresh_pipeline_uses_durable_job_runner_without_shell(tmp_path: Path) -> None:
    cli = load_public_cli()
    command = cli.build_pipeline_command(
        tmp_path,
        skip_publication_layer=False,
        target_review_dir="/workspace/systematic-review-test",
        target_script_root="/opt/data/skills/research/prisma-systematic-review/scripts",
        target_plugin_root="/opt/data/plugins/hermes_research",
    )
    assert command[:2] == ["python3", "-u"]
    assert command[2] == "/opt/data/plugins/hermes_research/job_runner.py"
    assert "bash" not in command
    assert "--job-id" in command


def test_process_environment_overrides_dotenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cli = load_public_cli()
    env_path = tmp_path / ".env"
    env_path.write_text("HERMES_MODEL_VISION=file-model\n", encoding="utf-8")
    monkeypatch.setattr(cli, "ENV_PATH", env_path)
    monkeypatch.setenv("HERMES_MODEL_VISION", "temporary-model")

    assert cli.load_package_env()["HERMES_MODEL_VISION"] == "temporary-model"


def test_parser_exposes_recoverable_screening_resolution() -> None:
    cli = load_public_cli()
    parser = cli.build_parser()

    args = parser.parse_args(
        [
            "resolve-screening",
            "systematic-review-example",
            "--doi",
            "10.1000/example",
            "--decision",
            "include",
            "--reason",
            "The population and outcome match the frozen protocol.",
        ]
    )

    assert args.doi == "10.1000/example"
    assert args.decision == "include"
    assert args.func is cli.command_resolve_screening
