"""Signed change control for frozen review protocols."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone
from typing import Any

from adjudication_security import (
    adjudication_secret,
    researcher_identity,
    sign_payload,
)

PENDING_SCHEMA = "hermes.protocol-change/v1"
APPROVAL_SCHEMA = "hermes.protocol-change-approval/v1"


class ProtocolChangeApprovalRequired(RuntimeError):
    """Raised when a material protocol change has not been approved."""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bounded_value(value: Any) -> Any:
    """Keep the explanation inspectable without copying huge payloads."""

    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, list):
        return value[:20]
    if isinstance(value, dict):
        return {str(key): bounded_value(item) for key, item in list(value.items())[:30]}
    return value


def diff_contract_values(
    before: Any,
    after: Any,
    *,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """Explain every material change using a stable dotted contract path."""

    if before == after:
        return []
    changes: list[dict[str, Any]] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            changes.extend(
                diff_contract_values(before.get(key), after.get(key), prefix=path)
            )
        return changes
    return [
        {
            "path": prefix or "$",
            "before": bounded_value(before),
            "after": bounded_value(after),
        }
    ]


def write_json_atomic(path: pathlib.Path, payload: dict[str, Any]) -> None:
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
        temporary = pathlib.Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def build_pending_change(
    review_dir: pathlib.Path,
    existing: dict[pathlib.Path, dict[str, Any]],
    proposed: dict[pathlib.Path, dict[str, Any]],
) -> dict[str, Any]:
    """Create one deterministic proposal for all changed contracts."""

    contract_changes: list[dict[str, Any]] = []
    for path, after in proposed.items():
        before = existing.get(path)
        if before is None or before == after:
            continue
        contract_changes.append(
            {
                "contract": str(path.relative_to(review_dir)),
                "before_sha256": canonical_hash(before),
                "after_sha256": canonical_hash(after),
                "changes": diff_contract_values(before, after),
            }
        )
    proposal_id = canonical_hash(contract_changes)
    return {
        "schema_version": PENDING_SCHEMA,
        "proposal_id": proposal_id,
        "status": "pending",
        "created_at": now_iso(),
        "explanation": (
            "La pregunta, elegibilidad, método, síntesis u otra regla congelada cambiaría. "
            "La propuesta no se aplica hasta que el investigador la apruebe."
        ),
        "contracts": contract_changes,
    }


def read_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def create_change_approval(
    review_dir: pathlib.Path,
    *,
    reason: str,
    env: dict[str, str] | None = None,
) -> pathlib.Path:
    """Sign the currently pending protocol proposal."""

    pending_path = review_dir / "protocol" / "pending-amendment.json"
    pending = read_json(pending_path)
    if pending.get("schema_version") != PENDING_SCHEMA or not pending.get("proposal_id"):
        raise ValueError("There is no pending protocol amendment")
    identity = researcher_identity(env)
    if not identity["name"] or not identity["email"]:
        raise ValueError("Researcher name and email must be configured")
    payload: dict[str, Any] = {
        "schema_version": APPROVAL_SCHEMA,
        "proposal_id": pending["proposal_id"],
        "decision": "approved",
        "reason": " ".join((reason or "").split())[:2000],
        "researcher": identity,
        "timestamp": now_iso(),
    }
    payload["signature"] = sign_payload(payload, adjudication_secret(env))
    path = review_dir / "protocol" / "amendment-approval.json"
    write_json_atomic(path, payload)
    return path


def approval_matches(
    pending: dict[str, Any],
    approval: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> bool:
    """Return True only for a valid signature over this exact proposal."""

    if approval.get("schema_version") != APPROVAL_SCHEMA:
        return False
    if approval.get("decision") != "approved":
        return False
    if approval.get("proposal_id") != pending.get("proposal_id"):
        return False
    try:
        expected = sign_payload(approval, adjudication_secret(env))
    except ValueError:
        return False
    return bool(
        approval.get("signature")
        and hmac.compare_digest(str(approval["signature"]), expected)
    )


def require_change_approval(
    review_dir: pathlib.Path,
    existing: dict[pathlib.Path, dict[str, Any]],
    proposed: dict[pathlib.Path, dict[str, Any]],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Block changed contracts until the exact proposal is signed."""

    pending = build_pending_change(review_dir, existing, proposed)
    if not pending["contracts"]:
        return None
    pending_path = review_dir / "protocol" / "pending-amendment.json"
    write_json_atomic(pending_path, pending)
    approval = read_json(review_dir / "protocol" / "amendment-approval.json")
    if not approval_matches(pending, approval, env=env):
        raise ProtocolChangeApprovalRequired(
            "Protocol change pending approval. Inspect protocol/pending-amendment.json "
            "and approve it before rerunning the pipeline."
        )
    return {
        **pending,
        "status": "approved",
        "approval": approval,
    }


def archive_applied_change(review_dir: pathlib.Path, approved: dict[str, Any]) -> pathlib.Path:
    """Preserve the proposal and approval after applying the contracts."""

    protocol_dir = review_dir / "protocol"
    proposal_id = str(approved["proposal_id"])
    archive = protocol_dir / "amendments" / f"{proposal_id}.json"
    payload = {**approved, "status": "applied", "applied_at": now_iso()}
    write_json_atomic(archive, payload)
    (protocol_dir / "pending-amendment.json").unlink(missing_ok=True)
    (protocol_dir / "amendment-approval.json").unlink(missing_ok=True)
    return archive
