"""Tests for provider-neutral runtime configuration."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import yaml

SCRIPT_PATH = Path(__file__).resolve().parents[4] / "bin" / "configure-runtime.py"


def load_module():
    """Load the runtime renderer from its executable script."""
    spec = importlib.util.spec_from_file_location("configure_runtime_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_config_uses_environment_without_persisting_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model: {}\nauxiliary: {}\n", encoding="utf-8")
    monkeypatch.setattr(module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(module, "HERMES_HOME", tmp_path)
    monkeypatch.setenv("HERMES_INFERENCE_BASE_URL", "https://provider.example/v1/")
    monkeypatch.setenv("HERMES_INFERENCE_API_KEY", "must-not-be-written")
    monkeypatch.setenv("HERMES_MODEL_PRIMARY", "writer-model")
    monkeypatch.setenv("HERMES_MODEL_VISION", "vision-model")
    monkeypatch.setenv("HERMES_MODEL_REVIEW", "review-model")

    module.render_config()

    rendered = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert rendered["model"]["default"] == "writer-model"
    assert rendered["model"]["base_url"] == "https://provider.example/v1"
    assert rendered["auxiliary"]["vision"]["model"] == "vision-model"
    assert "must-not-be-written" not in config_path.read_text(encoding="utf-8")
    assert os.stat(config_path).st_mode & 0o777 == 0o600
