import json
import pathlib
import stat
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import cloud_inference


def test_resolve_inference_runtime_prefers_public_contract(monkeypatch):
    monkeypatch.setenv("HERMES_INFERENCE_API_KEY", "public-key")
    monkeypatch.setenv(
        "HERMES_INFERENCE_BASE_URL",
        "https://provider.example/v1/chat/completions",
    )

    base_url, api_key = cloud_inference.resolve_inference_runtime({})

    assert base_url == "https://provider.example/v1"
    assert api_key == "public-key"


def test_resolve_inference_runtime_uses_standard_aliases(monkeypatch):
    for name in cloud_inference.INFERENCE_API_KEY_NAMES + cloud_inference.INFERENCE_BASE_URL_NAMES:
        monkeypatch.delenv(name, raising=False)

    base_url, api_key = cloud_inference.resolve_inference_runtime(
        {
            "OPENAI_API_KEY": "private-key",
            "OPENAI_BASE_URL": "https://example.test/v1/",
        }
    )

    assert base_url == "https://example.test/v1"
    assert api_key == "private-key"


def test_configured_models_are_ordered_and_deduplicated(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL_PRIMARY", "writer")
    monkeypatch.setenv("HERMES_MODEL_VISION", "vision")
    monkeypatch.setenv("HERMES_MODEL_REVIEW", "vision")

    assert cloud_inference.configured_research_models({}) == ("writer", "vision")


def test_configured_model_roles_preserve_scientific_function(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL_PRIMARY", "shared")
    monkeypatch.setenv("HERMES_MODEL_VISION", "vision")
    monkeypatch.setenv("HERMES_MODEL_REVIEW", "shared")

    assert cloud_inference.configured_research_model_roles({}) == {
        "primary": "shared",
        "vision": "vision",
        "review": "shared",
    }


def test_reasoning_models_receive_a_safe_final_answer_budget():
    assert cloud_inference.adaptive_max_tokens("deepseek-v4-flash", 128) >= 1024
    assert cloud_inference.adaptive_max_tokens("plain-text-model", 128) == 256


def test_curl_transport_keeps_api_key_out_of_argv(tmp_path, monkeypatch):
    capture_path = tmp_path / "capture.json"
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

config_path = pathlib.Path(sys.argv[sys.argv.index("--config") + 1])
config_text = config_path.read_text(encoding="utf-8")
pathlib.Path(os.environ["CAPTURE_PATH"]).write_text(
    json.dumps(
        {
            "argv": sys.argv,
            "config_mode": config_path.stat().st_mode & 0o777,
            "has_authorization": "Authorization: Bearer test-secret" in config_text,
        }
    ),
    encoding="utf-8",
)
print('{"choices":[{"message":{"content":"ok"}}]}')
""",
        encoding="utf-8",
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(cloud_inference.shutil, "which", lambda _: str(fake_curl))
    monkeypatch.setenv("CAPTURE_PATH", str(capture_path))

    response = cloud_inference.post_openai_compatible_chat(
        base_url="https://provider.example/v1",
        api_key="test-secret",
        payload={"model": "writer-model", "messages": []},
        timeout_seconds=30,
        user_agent="HermesTest/1.0",
    )

    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    assert response["choices"][0]["message"]["content"] == "ok"
    assert "test-secret" not in " ".join(capture["argv"])
    assert capture["config_mode"] == 0o600
    assert capture["has_authorization"] is True


def test_provider_model_substitution_is_rejected_and_audited(tmp_path, monkeypatch):
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env python3
print('{"id":"req-1","model":"fallback-model","choices":[{"finish_reason":"stop","message":{"content":"ok"}}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}')
""",
        encoding="utf-8",
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(cloud_inference.shutil, "which", lambda _: str(fake_curl))

    with pytest.raises(RuntimeError, match="different model"):
        cloud_inference.post_openai_compatible_chat(
            base_url="https://provider.example/v1",
            api_key="test-secret",
            payload={"model": "requested-model", "messages": []},
            timeout_seconds=30,
            user_agent="HermesTest/1.0",
            role="review",
            review_dir=tmp_path,
        )

    provenance = (tmp_path / "paper/audit/model-provenance.csv").read_text(encoding="utf-8")
    assert "requested-model" in provenance
    assert "fallback-model" in provenance
    assert "test-secret" not in provenance
