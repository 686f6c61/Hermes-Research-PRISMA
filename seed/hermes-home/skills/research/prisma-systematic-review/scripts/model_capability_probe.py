#!/usr/bin/env python3
"""Build a role-aware capability registry for configured inference models."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
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
) -> dict[str, object]:
    """Verify that the model can finish a compact machine-readable object."""
    response = post_openai_compatible_chat(
        base_url=base_url,
        api_key=api_key,
        payload={
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
        },
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


def build_registry(
    env_values: dict[str, str],
    *,
    live: bool,
    review_dir: pathlib.Path | None = None,
) -> dict[str, object]:
    """Create declared-only or live-tested capability evidence by role."""
    base_url, api_key = resolve_inference_runtime(env_values)
    role_models = configured_research_model_roles(env_values)
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
                    try:
                        tests.append(
                            probe(
                                base_url=base_url,
                                api_key=api_key,
                                model=model,
                                role=role,
                                review_dir=review_dir,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        tests.append(
                            {
                                "capability": "json" if probe is probe_json else "text",
                                "status": "fail",
                                "effective_model": "",
                                "detail": str(exc)[:300],
                            }
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

    env_values = load_env_file(HERMES_HOME / ".env")
    review_arg = args.review_dir_option or args.review_dir_pos
    review_dir = review_arg.expanduser().resolve() if review_arg else None
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
