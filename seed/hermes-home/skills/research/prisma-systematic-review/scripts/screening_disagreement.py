"""Signed researcher resolution for disputed full-text eligibility."""

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
    private_runtime_env,
    researcher_identity,
    sign_payload,
)

PENDING_SCHEMA = "hermes.screening-disagreements/v1"
CASE_SCHEMA = "hermes.screening-disagreement/v1"
RESOLUTION_SCHEMA = "hermes.screening-resolution/v1"


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


def manifest_sha(review_dir: pathlib.Path) -> str:
    path = review_dir / "protocol" / "contracts-manifest.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def build_case(
    review_dir: pathlib.Path,
    row: dict[str, str],
    reviewer_a: dict[str, object],
    reviewer_b: dict[str, object],
    recommendation: dict[str, object],
) -> dict[str, Any]:
    """Create a stable case bound to evidence and the frozen protocol."""

    payload: dict[str, Any] = {
        "schema_version": CASE_SCHEMA,
        "record_id": row.get("record_id", ""),
        "assigned_doi": row.get("assigned_doi", ""),
        "title": row.get("title_original", ""),
        "protocol_manifest_sha256": manifest_sha(review_dir),
        "reviewer_a": {
            "decision": reviewer_a.get("decision", ""),
            "reason": reviewer_a.get("reason", ""),
            "reason_detail": reviewer_a.get("reason_detail", ""),
            "engine": reviewer_a.get("_engine", ""),
        },
        "reviewer_b": {
            "decision": reviewer_b.get("decision", ""),
            "reason": reviewer_b.get("reason", ""),
            "reason_detail": reviewer_b.get("reason_detail", ""),
            "engine": reviewer_b.get("_engine", ""),
        },
        "automatic_recommendation": {
            "decision": recommendation.get("decision", ""),
            "reason": recommendation.get("reason", ""),
            "reason_detail": recommendation.get("reason_detail", ""),
            "engine": recommendation.get("_engine", ""),
        },
    }
    payload["case_id"] = canonical_hash(payload)
    return payload


def read_json(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_resolutions(review_dir: pathlib.Path) -> list[dict[str, Any]]:
    path = review_dir / "screening" / "disagreement-resolutions.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def pending_cases(review_dir: pathlib.Path) -> list[dict[str, Any]]:
    """Return every preserved disagreement case from the current checkpoint."""

    payload = read_json(review_dir / "screening" / "pending-disagreements.json")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return []
    return [case for case in cases if isinstance(case, dict)]


def valid_resolution(
    case: dict[str, Any],
    resolution: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> bool:
    """Accept only a signed decision for this exact disagreement."""

    if resolution.get("schema_version") != RESOLUTION_SCHEMA:
        return False
    if resolution.get("case_id") != case.get("case_id"):
        return False
    if resolution.get("decision") not in {"include", "exclude"}:
        return False
    try:
        expected = sign_payload(resolution, adjudication_secret(env))
    except ValueError:
        return False
    return bool(
        resolution.get("signature")
        and hmac.compare_digest(str(resolution["signature"]), expected)
    )


def resolution_for_case(
    review_dir: pathlib.Path,
    case: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Return the newest valid researcher decision for a case."""

    runtime_env = private_runtime_env(review_dir, env)
    for resolution in reversed(read_resolutions(review_dir)):
        if valid_resolution(case, resolution, env=runtime_env):
            return resolution
    return None


def resolution_status(
    review_dir: pathlib.Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Summarize which preserved cases still need a researcher decision."""

    cases = pending_cases(review_dir)
    unresolved = [
        case
        for case in cases
        if resolution_for_case(review_dir, case, env=env) is None
    ]
    return {
        "status": (
            "waiting_for_researcher"
            if unresolved
            else "ready_to_resume"
            if cases
            else "resolved"
        ),
        "cases": cases,
        "unresolved_cases": unresolved,
        "total": len(cases),
        "resolved": len(cases) - len(unresolved),
        "unresolved": len(unresolved),
    }


def fsync_directory(path: pathlib.Path) -> None:
    """Persist a replaced directory entry when the platform supports it."""

    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_pending_cases(
    review_dir: pathlib.Path,
    cases: list[dict[str, Any]],
) -> pathlib.Path:
    """Persist every disagreement while identifying those still unresolved."""

    path = review_dir / "screening" / "pending-disagreements.json"
    unresolved_cases = [
        case
        for case in cases
        if resolution_for_case(review_dir, case) is None
    ]
    payload = {
        "schema_version": PENDING_SCHEMA,
        "status": (
            "waiting_for_researcher" if unresolved_cases else "resolved"
        ),
        "updated_at": now_iso(),
        "message": (
            "The pipeline has preserved all completed work. Review each case "
            "before the final corpus and publication layer continue."
        ),
        "cases": cases,
        "case_count": len(cases),
        "resolved_count": len(cases) - len(unresolved_cases),
        "unresolved_count": len(unresolved_cases),
        "unresolved_case_ids": [
            str(case.get("case_id") or "") for case in unresolved_cases
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".pending-disagreements.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = pathlib.Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    fsync_directory(path.parent)
    return path


def record_resolution(
    review_dir: pathlib.Path,
    *,
    doi: str,
    decision: str,
    reason: str,
    env: dict[str, str] | None = None,
) -> pathlib.Path:
    """Sign and append one explicit researcher decision."""

    pending = read_json(review_dir / "screening" / "pending-disagreements.json")
    normalized_doi = doi.strip().lower()
    matching = [
        case
        for case in pending.get("cases") or []
        if str(case.get("assigned_doi") or "").strip().lower() == normalized_doi
    ]
    if len(matching) != 1:
        raise ValueError("The DOI does not identify exactly one pending disagreement")
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"include", "exclude"}:
        raise ValueError("Decision must be include or exclude")
    normalized_reason = " ".join(reason.split())[:2000]
    if not normalized_reason:
        raise ValueError("A scientific reason is required")
    runtime_env = private_runtime_env(review_dir, env)
    identity = researcher_identity(runtime_env)
    if not identity["name"] or not identity["email"]:
        raise ValueError("Researcher name and email must be configured")
    payload: dict[str, Any] = {
        "schema_version": RESOLUTION_SCHEMA,
        "case_id": matching[0]["case_id"],
        "assigned_doi": matching[0].get("assigned_doi", ""),
        "decision": normalized_decision,
        "reason": normalized_reason,
        "researcher": identity,
        "timestamp": now_iso(),
    }
    payload["signature"] = sign_payload(
        payload,
        adjudication_secret(runtime_env),
    )
    path = review_dir / "screening" / "disagreement-resolutions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".disagreement-resolutions.",
        delete=False,
    ) as handle:
        handle.write(existing)
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = pathlib.Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    fsync_directory(path.parent)
    return path
