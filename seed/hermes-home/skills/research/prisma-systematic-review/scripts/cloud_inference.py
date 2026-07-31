"""Shared OpenAI-compatible cloud inference helpers for the review pipeline."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from typing import Any

DEFAULT_OPENAI_BASE_URL = ""
INFERENCE_API_KEY_NAMES = (
    "HERMES_INFERENCE_API_KEY",
    "HERMES_MODEL_API_KEY",
    "PRIMARY_OPENAI_API_KEY",
    "OPENAI_API_KEY",
)
INFERENCE_BASE_URL_NAMES = (
    "HERMES_INFERENCE_BASE_URL",
    "HERMES_MODEL_BASE_URL",
    "PRIMARY_OPENAI_BASE_URL",
    "OPENAI_BASE_URL",
)
INFERENCE_MODEL_NAMES = (
    "HERMES_MODEL_PRIMARY",
    "HERMES_MODEL_VISION",
    "HERMES_MODEL_REVIEW",
)


def normalize_openai_base_url(raw_url: str) -> str:
    """Normalize an OpenAI-compatible endpoint to its versioned API root."""
    normalized = (raw_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    if normalized.endswith("/chat/completions"):
        return normalized[: -len("/chat/completions")]
    return normalized


def resolve_value(env_values: dict[str, str], names: tuple[str, ...]) -> str:
    """Resolve the first populated environment or dotenv value."""
    for name in names:
        value = os.environ.get(name, "").strip() or env_values.get(name, "").strip()
        if value:
            return value
    return ""


def resolve_inference_runtime(env_values: dict[str, str]) -> tuple[str, str]:
    """Return the configured OpenAI-compatible base URL and API key."""
    base_url = normalize_openai_base_url(
        resolve_value(env_values, INFERENCE_BASE_URL_NAMES) or DEFAULT_OPENAI_BASE_URL
    )
    api_key = resolve_value(env_values, INFERENCE_API_KEY_NAMES)
    return base_url, api_key


def configured_research_models(env_values: dict[str, str]) -> tuple[str, ...]:
    """Return configured writer, vision, and reviewer models without duplicates."""
    models: list[str] = []
    for name in INFERENCE_MODEL_NAMES:
        value = os.environ.get(name, "").strip() or env_values.get(name, "").strip()
        if value and value not in models:
            models.append(value)
    return tuple(models)


def _curl_config_value(value: str) -> str:
    safe = (value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{safe}"'


def post_openai_compatible_chat(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    user_agent: str,
) -> dict[str, Any]:
    """Call a chat-completions endpoint without exposing credentials in argv."""
    endpoint = normalize_openai_base_url(base_url) + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    curl_path = shutil.which("curl")
    if curl_path:
        config_path = ""
        payload_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as payload_file:
                payload_path = payload_file.name
                payload_file.write(json.dumps(payload))
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
                config_path = config_file.name
                os.chmod(config_path, 0o600)
                lines = [
                    f"url = {_curl_config_value(endpoint)}",
                    'request = "POST"',
                    "silent",
                    "show-error",
                    f"max-time = {timeout_seconds}",
                    f"connect-timeout = {min(20, max(5, timeout_seconds // 4))}",
                    f"data-binary = {_curl_config_value('@' + payload_path)}",
                ]
                for name, value in headers.items():
                    lines.append(f"header = {_curl_config_value(f'{name}: {value}')}")
                config_file.write("\n".join(lines) + "\n")
            completed = subprocess.run(
                [curl_path, "--config", config_path],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 10,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(detail or f"curl exited with {completed.returncode}")
            response = json.loads(completed.stdout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Inference request exceeded {timeout_seconds + 10}s") from exc
        finally:
            if config_path:
                pathlib.Path(config_path).unlink(missing_ok=True)
            if payload_path:
                pathlib.Path(payload_path).unlink(missing_ok=True)
    else:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code}: {body or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc

    error_payload = response.get("error")
    if error_payload:
        raise RuntimeError(json.dumps(error_payload, ensure_ascii=False))
    return response
