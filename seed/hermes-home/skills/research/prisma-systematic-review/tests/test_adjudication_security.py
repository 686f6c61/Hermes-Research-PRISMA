"""Tests for researcher-bound signed adjudication records."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from adjudication_security import create_adjudication, verify_adjudication


def materialize_contract(review_dir: pathlib.Path, value: str = "v1") -> None:
    protocol = review_dir / "protocol"
    protocol.mkdir(parents=True, exist_ok=True)
    (protocol / "contracts-manifest.json").write_text(
        json.dumps({"schema_version": value}) + "\n",
        encoding="utf-8",
    )


def signing_env() -> dict[str, str]:
    return {
        "HERMES_RESEARCHER_NAME": "Test Researcher",
        "HERMES_RESEARCHER_EMAIL": "researcher@example.org",
        "HERMES_RESEARCHER_ORCID": "0000-0000-0000-0000",
        "HERMES_ADJUDICATION_SECRET": "a" * 64,
    }


def test_signed_adjudication_is_bound_to_current_contract(tmp_path: pathlib.Path) -> None:
    review_dir = tmp_path / "systematic-review-test"
    materialize_contract(review_dir)
    path = create_adjudication(
        review_dir,
        decision="approved",
        reason="Scientific review completed.",
        env=signing_env(),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert verify_adjudication(review_dir, payload, env=signing_env()) == (
        True,
        "signed adjudication matches the current protocol",
    )
    assert path.stat().st_mode & 0o777 == 0o600


def test_tampering_or_contract_change_invalidates_approval(tmp_path: pathlib.Path) -> None:
    review_dir = tmp_path / "systematic-review-test"
    materialize_contract(review_dir)
    path = create_adjudication(
        review_dir,
        decision="approved",
        reason="Original decision.",
        env=signing_env(),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reason"] = "Changed after signing."
    valid, detail = verify_adjudication(review_dir, payload, env=signing_env())
    assert valid is False
    assert detail == "adjudication signature is invalid"

    payload = json.loads(path.read_text(encoding="utf-8"))
    materialize_contract(review_dir, "v2")
    valid, detail = verify_adjudication(review_dir, payload, env=signing_env())
    assert valid is False
    assert detail == "adjudication does not match the current protocol contract"


def test_verification_loads_private_review_env_without_shell_source(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in signing_env():
        monkeypatch.delenv(key, raising=False)
    review_dir = tmp_path / "systematic-review-test"
    materialize_contract(review_dir)
    (review_dir / ".env").write_text(
        "\n".join(f"{key}={value}" for key, value in signing_env().items())
        + "\n",
        encoding="utf-8",
    )

    path = create_adjudication(
        review_dir,
        decision="approved",
        reason="Verified from bounded private configuration.",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert verify_adjudication(review_dir, payload) == (
        True,
        "signed adjudication matches the current protocol",
    )
