#!/usr/bin/env python3
"""Render provider-neutral Hermes runtime settings from environment variables."""

from __future__ import annotations

import os
import pathlib
import tempfile

import yaml


HERMES_HOME = pathlib.Path(os.environ.get("HERMES_HOME", "/opt/data"))
CONFIG_PATH = HERMES_HOME / "config.yaml"


def required_env(name: str) -> str:
    """Return a required non-empty environment variable."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required. Run ./hermes-research setup.")
    return value


def unique_models(*models: str) -> list[str]:
    """Keep configured model identifiers in stable order without duplicates."""
    result: list[str] = []
    for model in models:
        value = (model or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def render_config() -> None:
    """Update only provider-dependent fields and replace the file atomically."""
    base_url = required_env("HERMES_INFERENCE_BASE_URL").rstrip("/")
    primary = required_env("HERMES_MODEL_PRIMARY")
    vision = os.environ.get("HERMES_MODEL_VISION", "").strip() or primary
    reviewer = os.environ.get("HERMES_MODEL_REVIEW", "").strip() or vision
    fallback_models = unique_models(vision, reviewer)
    fallback_models = [model for model in fallback_models if model != primary]

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    config["model"] = {
        "default": primary,
        "provider": "custom",
        "base_url": base_url,
    }
    config["fallback_providers"] = [
        {
            "provider": "custom",
            "model": model,
            "base_url": base_url,
            "api_key_env": "HERMES_INFERENCE_API_KEY",
        }
        for model in fallback_models
    ]
    config["custom_providers"] = [
        {
            "name": "OpenAI-compatible",
            "base_url": base_url,
            "api_key_env": "HERMES_INFERENCE_API_KEY",
            "model": primary,
        }
    ]

    auxiliary = config.setdefault("auxiliary", {})
    auxiliary["vision"] = {
        "provider": "custom",
        "model": vision,
        "base_url": base_url,
        "api_key": "",
        "timeout": 120,
        "download_timeout": 30,
    }
    config["model_aliases"] = {
        "research": {"model": primary, "provider": "custom", "base_url": base_url},
        "vision": {"model": vision, "provider": "custom", "base_url": base_url},
        "review": {"model": reviewer, "provider": "custom", "base_url": base_url},
    }

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=CONFIG_PATH.parent,
        prefix=".config.",
        delete=False,
    ) as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
        temp_path = pathlib.Path(handle.name)
    temp_path.chmod(0o600)
    temp_path.replace(CONFIG_PATH)


if __name__ == "__main__":
    render_config()
