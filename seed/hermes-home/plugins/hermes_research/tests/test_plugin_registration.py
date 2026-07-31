"""Tests for the official Hermes plugin registration surface."""

from __future__ import annotations

import json
import os
from pathlib import Path

from hermes_research import commands, register, runtime


class RecordingContext:
    """Capture plugin registrations without importing the Hermes runtime."""

    def __init__(self) -> None:
        self.commands: dict[str, object] = {}
        self.cli_commands: dict[str, object] = {}
        self.hooks: dict[str, object] = {}
        self.skills: dict[str, Path] = {}

    def register_command(self, name, *, handler, description) -> None:
        self.commands[name] = (handler, description)

    def register_cli_command(self, *, name, handler_fn, **kwargs) -> None:
        self.cli_commands[name] = (handler_fn, kwargs)

    def register_hook(self, name, handler) -> None:
        self.hooks[name] = handler

    def register_skill(self, name, path) -> None:
        self.skills[name] = Path(path)


def test_register_exposes_public_commands_through_plugin_api() -> None:
    context = RecordingContext()
    register(context)

    assert {
        "research",
        "nueva_revision",
        "estado",
        "reanudar",
        "cancelar",
        "ayuda",
    }.issubset(context.commands)
    assert "research" in context.cli_commands
    assert "pre_gateway_dispatch" in context.hooks
    assert "prisma-systematic-review" in context.skills
    assert "research-network-analysis" in context.skills


def test_bootstrap_removes_contact_bearing_transport_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    hermes_home = tmp_path / "hermes-home"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_RESEARCH_WORKSPACE", str(workspace))

    observed_temp_file: Path | None = None

    def fake_run(command, cwd=None, *, timeout=None):
        del cwd
        assert timeout == 300
        intake_path = Path(command[command.index("--intake-json") + 1])
        assert os.stat(intake_path).st_mode & 0o777 == 0o600
        assert json.loads(intake_path.read_text(encoding="utf-8"))["manuscript_email"] == "author@example.test"
        nonlocal observed_temp_file
        observed_temp_file = intake_path
        return json.dumps(
            {
                "review_dir": str(workspace / "systematic-review-example"),
                "review_name": "systematic-review-example",
                "review_mode": "technical",
                "review_mode_label": "Technical",
                "review_mode_confidence": "high",
                "status": "created",
                "next_phase": "search",
                "next_action": "Acquire records",
                "autonomous_mode": "no",
            }
        )

    monkeypatch.setattr(runtime, "run_command_capture", fake_run)
    message = commands._run_bootstrap(
        "",
        "\n".join(
            [
                "Tema: Agent systems",
                "Año o años: 2024-2026",
                "Criterios de inclusión: Full-text empirical studies",
                "Criterios de exclusión: Opinion pieces",
                "Correo de contacto (opcional): author@example.test",
                "Modo autónomo: no",
            ]
        ),
    )

    assert "systematic-review-example" in message
    assert observed_temp_file is not None
    assert not observed_temp_file.exists()
