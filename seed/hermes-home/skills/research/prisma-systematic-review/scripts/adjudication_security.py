"""Cryptographic records for human review adjudication.

An approval stored inside a writable review folder is not trustworthy by
itself. These helpers bind the researcher identity, decision, review, and
current protocol contract to an HMAC secret kept outside the workspace.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import secrets
import tempfile
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "hermes.human-adjudication/v2"
SIGNATURE_ALGORITHM = "hmac-sha256"
DECISIONS = {"approved", "rejected"}


def now_iso() -> str:
    """Return a timezone-aware approval timestamp."""

    return datetime.now(timezone.utc).astimezone().isoformat()


def researcher_identity(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return the configured accountable researcher identity."""

    source = env or os.environ
    return {
        "name": str(source.get("HERMES_RESEARCHER_NAME") or "").strip(),
        "email": str(source.get("HERMES_RESEARCHER_EMAIL") or "").strip(),
        "orcid": str(source.get("HERMES_RESEARCHER_ORCID") or "").strip(),
    }


def adjudication_secret(env: dict[str, str] | None = None) -> str:
    """Return the signing secret without persisting it in the review."""

    source = env or os.environ
    return str(source.get("HERMES_ADJUDICATION_SECRET") or "").strip()


def contract_digest(review_dir: pathlib.Path) -> str:
    """Hash the frozen protocol contract approved by the researcher."""

    path = review_dir / "protocol" / "contracts-manifest.json"
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_payload(payload: dict[str, Any]) -> bytes:
    """Serialize signed fields deterministically."""

    signed = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        signed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    """Return the HMAC signature for one adjudication payload."""

    if len(secret) < 32:
        raise ValueError("HERMES_ADJUDICATION_SECRET must contain at least 32 characters")
    return hmac.new(secret.encode("utf-8"), canonical_payload(payload), hashlib.sha256).hexdigest()


def write_json_atomic(path: pathlib.Path, payload: dict[str, Any]) -> None:
    """Persist an approval atomically with private file permissions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = pathlib.Path(handle.name)
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, path)


def create_adjudication(
    review_dir: pathlib.Path,
    *,
    decision: str,
    reason: str,
    env: dict[str, str] | None = None,
) -> pathlib.Path:
    """Create a signed approval or rejection for the current protocol."""

    normalized_decision = decision.strip().lower()
    if normalized_decision not in DECISIONS:
        raise ValueError("Decision must be approved or rejected")
    identity = researcher_identity(env)
    if not identity["name"] or not identity["email"]:
        raise ValueError("Researcher name and email must be configured before adjudication")
    digest = contract_digest(review_dir)
    if not digest:
        raise ValueError("The review has no frozen contracts-manifest.json")
    secret = adjudication_secret(env)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "decision": normalized_decision,
        "reason": " ".join((reason or "").split())[:2000],
        "researcher": identity,
        "review": review_dir.name,
        "contract_sha256": digest,
        "timestamp": now_iso(),
        "nonce": secrets.token_hex(16),
    }
    payload["signature"] = sign_payload(payload, secret)
    output = review_dir / "paper" / "audit" / "human-adjudication.json"
    write_json_atomic(output, payload)
    return output


def verify_adjudication(
    review_dir: pathlib.Path,
    payload: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Verify identity, protocol binding, and HMAC authenticity."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        return False, "unsupported adjudication schema"
    if payload.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        return False, "unsupported adjudication signature"
    if str(payload.get("decision") or "").lower() not in DECISIONS:
        return False, "invalid adjudication decision"
    researcher = payload.get("researcher")
    if not isinstance(researcher, dict) or not researcher.get("name") or not researcher.get("email"):
        return False, "missing accountable researcher identity"
    if payload.get("review") != review_dir.name:
        return False, "adjudication belongs to another review"
    digest = contract_digest(review_dir)
    if not digest or payload.get("contract_sha256") != digest:
        return False, "adjudication does not match the current protocol contract"
    secret = adjudication_secret(env)
    if len(secret) < 32:
        return False, "adjudication signing secret is unavailable"
    expected = sign_payload(payload, secret)
    if not hmac.compare_digest(str(payload.get("signature") or ""), expected):
        return False, "adjudication signature is invalid"
    return True, "signed adjudication matches the current protocol"
