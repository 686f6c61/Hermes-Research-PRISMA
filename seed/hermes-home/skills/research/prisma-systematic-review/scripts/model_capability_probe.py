#!/usr/bin/env python3
"""Build a role-aware capability registry for configured inference models."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time
from datetime import datetime, timezone

from cloud_inference import (
    MODEL_ROLE_CAPABILITIES,
    adaptive_max_tokens,
    configured_research_model_roles,
    post_openai_compatible_chat,
    resolve_inference_runtime,
    response_effective_model,
)

SCHEMA_VERSION = "hermes.model-capabilities/v1"
HERMES_HOME = pathlib.Path(__file__).resolve().parents[4]
LIVE_PROBE_ATTEMPTS = 3
LIVE_PROBE_BACKOFF_SECONDS = 1.0


def load_env_file(path: pathlib.Path) -> dict[str, str]:
    """Read a dotenv file without printing or returning it outside this process."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_private_env_values(review_dir: pathlib.Path | None) -> dict[str, str]:
    """Load bounded local runtime configuration without exposing secret values."""
    candidates: list[pathlib.Path] = []
    if review_dir is not None:
        candidates.extend(parent / ".env" for parent in review_dir.resolve().parents[:4])
        candidates.append(review_dir / ".env")
    candidates.extend(
        [
            HERMES_HOME / ".env",
            HERMES_HOME.parent / ".env",
            HERMES_HOME.parent.parent / ".env",
        ]
    )
    values: dict[str, str] = {}
    seen: set[pathlib.Path] = set()
    for candidate in reversed(candidates):
        normalized = candidate.resolve()
        if normalized in seen:
            continue
        seen.add(normalized)
        values.update(load_env_file(candidate))
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def extract_text(response: dict[str, object]) -> str:
    """Extract final text from a standard OpenAI-compatible response."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        ).strip()
    return ""


def parse_json_object(text: str) -> dict[str, object]:
    """Parse JSON even when a provider wraps it in a Markdown fence."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.I)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("The JSON probe did not return an object")
    return parsed


def probe_text(
    *,
    base_url: str,
    api_key: str,
    model: str,
    role: str,
    review_dir: pathlib.Path | None,
) -> dict[str, object]:
    """Verify final text and effective-model identity."""
    response = post_openai_compatible_chat(
        base_url=base_url,
        api_key=api_key,
        payload={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly HERMES_OK."}],
            "temperature": 0,
            "max_tokens": adaptive_max_tokens(model, 64),
        },
        timeout_seconds=90,
        user_agent="HermesResearchCapabilityProbe/1.0",
        role=role,
        capability="text",
        review_dir=review_dir,
    )
    answer = extract_text(response)
    return {
        "capability": "text",
        "status": "pass" if answer.strip() == "HERMES_OK" else "fail",
        "effective_model": response_effective_model(response, model),
        "detail": answer[:160],
    }


def probe_json(
    *,
    base_url: str,
    api_key: str,
    model: str,
    role: str,
    review_dir: pathlib.Path | None,
    reasoning_effort: str = "",
) -> dict[str, object]:
    """Verify that the model can finish a compact machine-readable object."""
    payload: dict[str, object] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": 'Return only this JSON object: {"status":"HERMES_OK","value":7}',
            }
        ],
        "temperature": 0,
        "max_tokens": adaptive_max_tokens(model, 128),
        "response_format": {"type": "json_object"},
    }
    if reasoning_effort in {"none", "minimal", "low", "medium", "high"}:
        payload["reasoning_effort"] = reasoning_effort
    response = post_openai_compatible_chat(
        base_url=base_url,
        api_key=api_key,
        payload=payload,
        timeout_seconds=90,
        user_agent="HermesResearchCapabilityProbe/1.0",
        role=role,
        capability="json",
        review_dir=review_dir,
    )
    answer = extract_text(response)
    parsed = parse_json_object(answer)
    passed = parsed.get("status") == "HERMES_OK" and parsed.get("value") == 7
    return {
        "capability": "json",
        "status": "pass" if passed else "fail",
        "effective_model": response_effective_model(response, model),
        "detail": json.dumps(parsed, ensure_ascii=False)[:160],
    }


def run_live_probe_with_retries(
    probe,
    probe_kwargs: dict[str, object],
    *,
    capability: str,
    attempts: int = LIVE_PROBE_ATTEMPTS,
    sleep_fn=time.sleep,
) -> dict[str, object]:
    """Retry a bounded live probe when a provider returns an empty or transient failure."""
    bounded_attempts = max(1, min(int(attempts), 5))
    last_result: dict[str, object] = {
        "capability": capability,
        "status": "fail",
        "effective_model": "",
        "detail": "Capability probe did not run.",
    }
    for attempt in range(1, bounded_attempts + 1):
        try:
            result = probe(**probe_kwargs)
        except Exception as exc:  # noqa: BLE001
            result = {
                "capability": capability,
                "status": "fail",
                "effective_model": "",
                "detail": str(exc)[:300],
            }
        result["attempts"] = attempt
        last_result = result
        if result.get("status") == "pass":
            return result
        if attempt < bounded_attempts:
            sleep_fn(LIVE_PROBE_BACKOFF_SECONDS * attempt)
    return last_result


def build_registry(
    env_values: dict[str, str],
    *,
    live: bool,
    review_dir: pathlib.Path | None = None,
) -> dict[str, object]:
    """Create declared-only or live-tested capability evidence by role."""
    base_url, api_key = resolve_inference_runtime(env_values)
    role_models = configured_research_model_roles(env_values)
    reasoning_effort = (
        os.environ.get("HERMES_REASONING_EFFORT", "").strip().lower()
        or env_values.get("HERMES_REASONING_EFFORT", "").strip().lower()
    )
    roles: list[dict[str, object]] = []
    for role, model in role_models.items():
        required = list(MODEL_ROLE_CAPABILITIES.get(role, ("text",)))
        tests: list[dict[str, object]] = []
        if live:
            if not base_url or not api_key:
                tests.append(
                    {
                        "capability": "runtime",
                        "status": "fail",
                        "effective_model": "",
                        "detail": "Inference endpoint or API key is not configured.",
                    }
                )
            else:
                probes = [probe_text]
                if "json" in required:
                    probes.append(probe_json)
                for probe in probes:
                    capability = "json" if probe is probe_json else "text"
                    probe_kwargs: dict[str, object] = {
                        "base_url": base_url,
                        "api_key": api_key,
                        "model": model,
                        "role": role,
                        "review_dir": review_dir,
                    }
                    if probe is probe_json:
                        probe_kwargs["reasoning_effort"] = reasoning_effort
                    tests.append(
                        run_live_probe_with_retries(
                            probe,
                            probe_kwargs,
                            capability=capability,
                        )
                    )
        if "vision" in required:
            tests.append(
                {
                    "capability": "vision",
                    "status": "external_probe_required" if not live else "external_probe_required",
                    "effective_model": "",
                    "detail": "Run verify_multimodal_pdf.py against a rendered scientific page.",
                }
            )
        passed = all(
            test.get("status") == "pass"
            for test in tests
            if test.get("status") != "external_probe_required"
        )
        roles.append(
            {
                "role": role,
                "requested_model": model,
                "required_capabilities": required,
                "status": "pass" if live and passed else ("declared" if not live else "fail"),
                "tests": tests,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "mode": "live" if live else "declared",
        "provider_host": base_url.split("://", 1)[-1].split("/", 1)[0] if base_url else "",
        "roles": roles,
        "status": (
            "pass"
            if live and roles and all(row["status"] == "pass" for row in roles)
            else ("declared" if not live else "fail")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir_pos", nargs="?", type=pathlib.Path)
    parser.add_argument("--live", action="store_true", help="Call the configured provider.")
    parser.add_argument(
        "--review-dir",
        dest="review_dir_option",
        type=pathlib.Path,
        help="Optional review receiving provenance records.",
    )
    parser.add_argument("--output", type=pathlib.Path, help="Output JSON path.")
    args = parser.parse_args()

    review_arg = args.review_dir_option or args.review_dir_pos
    review_dir = review_arg.expanduser().resolve() if review_arg else None
    env_values = resolve_private_env_values(review_dir)
    registry = build_registry(env_values, live=args.live, review_dir=review_dir)
    output = args.output
    if output is None and review_dir is not None:
        output = review_dir / "paper" / "audit" / "model-capabilities.json"
    if output is None:
        output = pathlib.Path("model-capabilities.json")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": registry["status"], "output": str(output)}, ensure_ascii=False))
    return 0 if registry["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
