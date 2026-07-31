"""Shared OpenAI-compatible cloud inference helpers for the review pipeline."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
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
MODEL_ROLE_ENV = {
    "primary": "HERMES_MODEL_PRIMARY",
    "vision": "HERMES_MODEL_VISION",
    "review": "HERMES_MODEL_REVIEW",
}
MODEL_ROLE_CAPABILITIES = {
    "primary": ("text", "json"),
    "vision": ("text", "vision"),
    "review": ("text", "json"),
}
REASONING_MODEL_HINTS = (
    "deepseek",
    "reason",
    "thinking",
    "qwq",
    "qwen3",
    "o1",
    "o3",
    "o4",
)
PROVENANCE_FIELDS = (
    "timestamp",
    "role",
    "capability",
    "provider_host",
    "requested_model",
    "effective_model",
    "fallback_detected",
    "status",
    "finish_reason",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "request_id",
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


def configured_research_model_roles(env_values: dict[str, str]) -> dict[str, str]:
    """Return the configured model for each scientific role.

    Roles are intentionally preserved even when two roles use the same model.
    Capability probes and provenance reports need to know why a model was
    called, not only that its identifier appeared in configuration.
    """
    roles: dict[str, str] = {}
    for role, env_name in MODEL_ROLE_ENV.items():
        value = os.environ.get(env_name, "").strip() or env_values.get(env_name, "").strip()
        if value:
            roles[role] = value
    return roles


def adaptive_max_tokens(model: str, requested: int, *, minimum: int = 256) -> int:
    """Reserve enough output budget for models that emit hidden reasoning.

    Several OpenAI-compatible providers count reasoning tokens inside
    ``max_tokens``. A very small cap can therefore truncate valid JSON before
    the final answer appears. The caller remains in control of larger budgets.
    """
    budget = max(int(requested), int(minimum))
    normalized = (model or "").strip().lower()
    if any(hint in normalized for hint in REASONING_MODEL_HINTS):
        budget = max(budget, 1024, int(requested) * 2)
    return budget


def response_effective_model(response: dict[str, Any], requested_model: str) -> str:
    """Return the provider-reported model, falling back only when omitted."""
    effective = str(response.get("model") or "").strip()
    return effective or requested_model


def _provider_host(base_url: str) -> str:
    parsed = urllib.parse.urlparse(normalize_openai_base_url(base_url))
    return parsed.netloc or parsed.path.split("/", 1)[0]


def _token_usage(response: dict[str, Any]) -> tuple[str, str, str]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return "", "", ""
    prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", ""))
    completion_tokens = usage.get("completion_tokens", usage.get("output_tokens", ""))
    total_tokens = usage.get("total_tokens", "")
    return str(prompt_tokens), str(completion_tokens), str(total_tokens)


def append_model_provenance(
    review_dir: pathlib.Path,
    *,
    role: str,
    capability: str,
    base_url: str,
    requested_model: str,
    effective_model: str,
    status: str,
    response: dict[str, Any] | None = None,
) -> pathlib.Path:
    """Append one credential-free inference record to the review audit trail."""
    import csv

    response = response or {}
    choices = response.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    input_tokens, output_tokens, total_tokens = _token_usage(response)
    requested_norm = requested_model.strip().lower()
    effective_norm = effective_model.strip().lower()
    row = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        "role": role or "unspecified",
        "capability": capability or "text",
        "provider_host": _provider_host(base_url),
        "requested_model": requested_model,
        "effective_model": effective_model,
        "fallback_detected": "yes" if requested_norm and effective_norm and requested_norm != effective_norm else "no",
        "status": status,
        "finish_reason": str(first_choice.get("finish_reason") or ""),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "request_id": str(response.get("id") or ""),
    }
    path = review_dir / "paper" / "audit" / "model-provenance.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROVENANCE_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())
    return path


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
    role: str = "",
    capability: str = "text",
    review_dir: pathlib.Path | None = None,
    allow_model_fallback: bool = False,
) -> dict[str, Any]:
    """Call a chat-completions endpoint and reject undocumented model fallback."""
    requested_model = str(payload.get("model") or "").strip()
    if "max_tokens" in payload:
        payload = dict(payload)
        payload["max_tokens"] = adaptive_max_tokens(
            requested_model,
            int(payload.get("max_tokens") or 0),
        )
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
    effective_model = response_effective_model(response, requested_model)
    fallback_detected = (
        bool(requested_model)
        and bool(effective_model)
        and requested_model.strip().lower() != effective_model.strip().lower()
    )
    if review_dir is not None:
        append_model_provenance(
            pathlib.Path(review_dir),
            role=role,
            capability=capability,
            base_url=base_url,
            requested_model=requested_model,
            effective_model=effective_model,
            status="fallback_rejected" if fallback_detected and not allow_model_fallback else "ok",
            response=response,
        )
    if fallback_detected and not allow_model_fallback:
        raise RuntimeError(
            "Provider returned a different model than requested: "
            f"requested={requested_model!r}, effective={effective_model!r}."
        )
    return response
