"""Regression tests for safe review-directory resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from hermes_research import bindings, hooks, runtime


def materialize_review(root: Path, name: str = "systematic-review-example") -> Path:
    """Create the minimum directory contract for a real review."""
    review_dir = root / name
    protocol_dir = review_dir / "protocol"
    protocol_dir.mkdir(parents=True)
    (protocol_dir / "intake.md").write_text("# Intake\n", encoding="utf-8")
    return review_dir


def test_is_review_dir_rejects_workspace_and_template(tmp_path: Path) -> None:
    template = tmp_path / "systematic-review-template"
    (template / "protocol").mkdir(parents=True)
    (template / "protocol" / "intake.md").write_text("# Template\n", encoding="utf-8")

    assert runtime.is_review_dir(tmp_path) is False
    assert runtime.is_review_dir(template) is False
    assert runtime.is_review_dir(materialize_review(tmp_path)) is True


def test_empty_or_legacy_binding_never_resolves_to_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bindings_path = tmp_path / "bindings.json"
    monkeypatch.setattr(runtime, "public_bindings_path", lambda: bindings_path)

    bindings_path.write_text("{}", encoding="utf-8")
    assert bindings.resolve_bound_review("telegram:missing") is None

    bindings_path.write_text(
        json.dumps({"telegram:legacy": str(tmp_path)}),
        encoding="utf-8",
    )
    assert bindings.resolve_bound_review("telegram:legacy") is None


def test_binding_resolves_only_a_materialized_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    review_dir = materialize_review(tmp_path)
    bindings_path = tmp_path / "bindings.json"
    monkeypatch.setattr(runtime, "public_bindings_path", lambda: bindings_path)
    bindings.bind_review("telegram:valid", review_dir)

    assert bindings.resolve_bound_review("telegram:valid") == review_dir.resolve()
    assert os.stat(bindings_path).st_mode & 0o777 == 0o600


def test_explicit_workspace_path_is_not_a_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runtime, "workspace_root", lambda: tmp_path)

    assert runtime.resolve_review_dir(str(tmp_path)) is None


def test_group_bindings_include_user_identity() -> None:
    event = SimpleNamespace(
        source=SimpleNamespace(
            platform=SimpleNamespace(value="telegram"),
            chat_id="-100123",
            user_id="456",
        )
    )

    assert hooks._binding_key(event) == "telegram:-100123:456"


def test_public_start_is_rewritten_to_plugin_help(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_TELEGRAM_PUBLIC_MENU_ONLY", "1")
    event = SimpleNamespace(
        text="/start@research_bot",
        source=SimpleNamespace(
            platform=SimpleNamespace(value="telegram"),
            chat_id="123",
            user_id="456",
        ),
    )

    assert hooks.rewrite_public_research_flow(event) == {
        "action": "rewrite",
        "text": "/research help --binding telegram:123:456",
    }


def test_public_alias_with_bot_suffix_keeps_its_argument(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_TELEGRAM_PUBLIC_MENU_ONLY", "1")
    event = SimpleNamespace(
        text="/estado@research_bot systematic-review-example",
        source=SimpleNamespace(
            platform=SimpleNamespace(value="telegram"),
            chat_id="123",
            user_id="456",
        ),
    )

    assert hooks.rewrite_public_research_flow(event) == {
        "action": "rewrite",
        "text": "/research status --binding telegram:123:456 systematic-review-example",
    }


def test_smoke_autonomous_run_stops_after_bounded_bootstrap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "bootstrap_topic_review.py").write_text("", encoding="utf-8")
    (scripts_dir / "complete_review.py").write_text("", encoding="utf-8")
    review_dir = materialize_review(tmp_path)
    captured: dict[str, object] = {}

    def fake_launch(command, log_path, cwd=None):
        captured["command"] = command
        captured["log_path"] = log_path
        captured["cwd"] = cwd
        return 123

    monkeypatch.setenv("HERMES_RESEARCH_SMOKE_TEST", "1")
    monkeypatch.setattr(runtime, "prisma_scripts_dir", lambda: scripts_dir)
    monkeypatch.setattr(runtime, "launch_background", fake_launch)

    assert runtime.launch_public_autonomous_review(review_dir) == 123
    command = captured["command"]
    assert command[:2] == ["bash", "-c"]
    assert "bootstrap_topic_review.py" in command[2]
    assert "complete_review.py" not in command[2]
