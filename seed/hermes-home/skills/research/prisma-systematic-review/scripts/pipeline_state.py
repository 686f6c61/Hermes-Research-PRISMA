"""Content-addressed step state for resumable review execution."""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from typing import Any, Iterable

from artifact_contracts import expand_patterns, files_digest, read_json, write_json_atomic

STATE_SCHEMA = "hermes.pipeline-state/v1"


def now_iso() -> str:
    """Return a timezone-aware event timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def state_path(review_dir: pathlib.Path) -> pathlib.Path:
    """Return the canonical machine-readable pipeline state."""
    return review_dir / "notes" / "pipeline-state.json"


def load_state(review_dir: pathlib.Path) -> dict[str, Any]:
    """Load pipeline state with a stable empty default."""
    loaded = read_json(state_path(review_dir), {})
    if not isinstance(loaded, dict) or loaded.get("schema_version") != STATE_SCHEMA:
        return {
            "schema_version": STATE_SCHEMA,
            "updated_at": now_iso(),
            "steps": {},
            "events": [],
        }
    loaded.setdefault("steps", {})
    loaded.setdefault("events", [])
    return loaded


def output_paths(review_dir: pathlib.Path, outputs: Iterable[str]) -> list[pathlib.Path]:
    """Resolve expected output paths."""
    return [review_dir / output for output in outputs]


def outputs_ready(review_dir: pathlib.Path, outputs: Iterable[str]) -> bool:
    """Return True only when every declared output is material and non-empty."""
    resolved = output_paths(review_dir, outputs)
    return bool(resolved) and all(path.is_file() and path.stat().st_size > 0 for path in resolved)


def step_input_hash(review_dir: pathlib.Path, patterns: Iterable[str]) -> str:
    """Hash all declared step inputs."""
    return files_digest(expand_patterns(review_dir, patterns), root=review_dir)


def should_run(
    review_dir: pathlib.Path,
    step_id: str,
    *,
    inputs: Iterable[str],
    outputs: Iterable[str],
    force: bool = False,
) -> tuple[bool, str]:
    """Decide whether a step is dirty using content rather than timestamps."""
    current_hash = step_input_hash(review_dir, inputs)
    state = load_state(review_dir)
    previous = state.get("steps", {}).get(step_id, {})
    clean = (
        not force
        and previous.get("status") == "completed"
        and previous.get("input_hash") == current_hash
        and outputs_ready(review_dir, outputs)
    )
    return not clean, current_hash


def record_step(
    review_dir: pathlib.Path,
    step_id: str,
    *,
    status: str,
    inputs: Iterable[str],
    outputs: Iterable[str],
    detail: str = "",
) -> pathlib.Path:
    """Persist one state transition and a bounded execution event ledger."""
    state = load_state(review_dir)
    steps = state["steps"]
    previous = steps.get(step_id, {})
    attempts = int(previous.get("attempts") or 0)
    if status == "running":
        attempts += 1
    entry = {
        "status": status,
        "attempts": attempts,
        "input_hash": step_input_hash(review_dir, inputs),
        "inputs": list(inputs),
        "outputs": list(outputs),
        "outputs_ready": outputs_ready(review_dir, outputs),
        "detail": detail,
        "updated_at": now_iso(),
    }
    if status == "running":
        entry["started_at"] = now_iso()
    else:
        entry["started_at"] = previous.get("started_at") or ""
        entry["finished_at"] = now_iso()
    steps[step_id] = entry
    events = state["events"]
    events.append(
        {
            "timestamp": now_iso(),
            "step": step_id,
            "status": status,
            "detail": detail,
        }
    )
    state["events"] = events[-300:]
    state["updated_at"] = now_iso()
    return write_json_atomic(state_path(review_dir), state)


def pipeline_summary(review_dir: pathlib.Path) -> dict[str, object]:
    """Return counts used by the delivery guide and runtime inspector."""
    state = load_state(review_dir)
    steps = list(state.get("steps", {}).values())
    return {
        "schema_version": STATE_SCHEMA,
        "updated_at": state.get("updated_at", ""),
        "steps_total": len(steps),
        "steps_completed": sum(1 for step in steps if step.get("status") in {"completed", "skipped"}),
        "steps_failed": sum(1 for step in steps if step.get("status") == "failed"),
        "steps_running": sum(1 for step in steps if step.get("status") == "running"),
    }
