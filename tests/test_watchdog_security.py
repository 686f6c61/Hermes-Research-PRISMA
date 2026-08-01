"""Regression tests for bounded, deterministic watchdog behavior."""

from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCHDOG_PATH = ROOT / "seed" / "hermes-home" / "bin" / "prisma-watchdog.py"
SPEC = importlib.util.spec_from_file_location("prisma_watchdog_under_test", WATCHDOG_PATH)
assert SPEC and SPEC.loader
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


def test_backoff_grows_with_repeated_state_attempts() -> None:
    entry = {
        "last_signature": "same",
        "attempts_for_signature": 3,
        "last_attempt_at": (watchdog.now() - timedelta(minutes=100)).isoformat(),
    }
    assert watchdog.should_skip(entry, "same", 30, 360) is True
    entry["last_attempt_at"] = (watchdog.now() - timedelta(minutes=130)).isoformat()
    assert watchdog.should_skip(entry, "same", 30, 360) is False


def test_retry_limit_materializes_needs_human_state(tmp_path: Path, monkeypatch) -> None:
    review_dir = tmp_path / "systematic-review-test"
    review_dir.mkdir()
    state_path = tmp_path / "watchdog-state.json"
    monkeypatch.setattr(watchdog, "STATE_PATH", state_path)
    monkeypatch.setattr(watchdog, "list_review_dirs", lambda: [review_dir])
    monkeypatch.setattr(watchdog, "parse_intake_mode", lambda _path: "sí")
    monkeypatch.setattr(watchdog, "refresh_review", lambda *_args: None)
    runtime_state = {
        "status": "stalled",
        "current_phase": "Fase 3",
        "next_phase": "Fase 3",
        "next_action": "Continue",
        "last_update": "2026-08-01T00:00:00+00:00",
        "blocker": "",
    }
    monkeypatch.setattr(watchdog, "load_runtime", lambda _path: runtime_state)
    monkeypatch.setattr(watchdog, "send_telegram_message", lambda _text: True)
    signature = watchdog.candidate_signature(runtime_state)
    state_db = {
        "reviews": {
            str(review_dir): {
                "last_signature": signature,
                "attempts_for_signature": 3,
                "total_attempts": 3,
            }
        }
    }

    selected, state = watchdog.select_candidate(
        15,
        30,
        360,
        3,
        12,
        state_db,
    )

    assert selected is None
    assert state is None
    terminal = json.loads((review_dir / "notes" / "watchdog-needs-human.json").read_text())
    assert terminal["status"] == "needs_human"
    assert state_db["reviews"][str(review_dir)]["status"] == "needs_human"


def test_deterministic_mode_never_builds_hermes_yolo_command(tmp_path: Path, monkeypatch) -> None:
    review_dir = tmp_path / "systematic-review-test"
    review_dir.mkdir()
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(watchdog, "STATE_PATH", tmp_path / "state.json")
    def fake_run_cmd(args, **_kwargs):
        captured["command"] = args
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(watchdog, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(watchdog, "refresh_review", lambda *_args: None)
    monkeypatch.setattr(watchdog, "status_markdown", lambda _path: "ok")
    monkeypatch.setattr(watchdog, "send_telegram_message", lambda _text: True)

    watchdog.resume_review(
        review_dir,
        {
            "status": "stalled",
            "current_phase": "Fase 3",
            "next_phase": "Fase 3",
            "next_action": "Continue",
            "last_update": "now",
            "blocker": "",
        },
        {"reviews": {}},
        ["model-a"],
        30,
        "deterministic",
        False,
    )

    command = captured["command"]
    assert command[0:3] == ["python3", "-u", str(watchdog.JOB_RUNNER)]
    assert "hermes" not in command
    assert "--yolo" not in command
