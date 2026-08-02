"""Content-addressed step state for resumable review execution."""

from __future__ import annotations

import hashlib
import pathlib
from datetime import datetime, timezone
from typing import Any, Iterable

from artifact_contracts import expand_patterns, files_digest, read_json, sha256_file, write_json_atomic

STATE_SCHEMA = "hermes.pipeline-state/v1"
LINEAGE_SCHEMA = "hermes.artifact-lineage/v1"
PRIVATE_LINEAGE_STEPS = {"research_memory"}


def now_iso() -> str:
    """Return a timezone-aware event timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def state_path(review_dir: pathlib.Path) -> pathlib.Path:
    """Return the canonical machine-readable pipeline state."""
    return review_dir / "notes" / "pipeline-state.json"


def new_run_id(review_dir: pathlib.Path) -> str:
    """Create a non-secret run identifier without exposing an absolute path."""
    seed = f"{review_dir.name}\n{now_iso()}".encode()
    return f"run-{hashlib.sha256(seed).hexdigest()[:16]}"


def load_state(review_dir: pathlib.Path) -> dict[str, Any]:
    """Load pipeline state with a stable empty default."""
    loaded = read_json(state_path(review_dir), {})
    if not isinstance(loaded, dict) or loaded.get("schema_version") != STATE_SCHEMA:
        return {
            "schema_version": STATE_SCHEMA,
            "run_id": new_run_id(review_dir),
            "updated_at": now_iso(),
            "steps": {},
            "events": [],
        }
    loaded.setdefault("run_id", new_run_id(review_dir))
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


def artifact_metadata(review_dir: pathlib.Path, paths: Iterable[pathlib.Path]) -> list[dict[str, object]]:
    """Describe material artifacts with relative paths and content hashes."""
    artifacts: list[dict[str, object]] = []
    for path in sorted({item.resolve() for item in paths if item.is_file()}):
        try:
            relative = path.relative_to(review_dir.resolve()).as_posix()
        except ValueError:
            continue
        artifacts.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return artifacts


def lineage_payload(review_dir: pathlib.Path, state: dict[str, Any]) -> dict[str, object]:
    """Build artifact nodes and derivation edges from persisted step contracts."""
    nodes: dict[str, dict[str, object]] = {}
    edges: list[dict[str, str]] = []
    steps: list[dict[str, object]] = []
    for step_id, raw_step in sorted((state.get("steps") or {}).items()):
        if not isinstance(raw_step, dict):
            continue
        if step_id in PRIVATE_LINEAGE_STEPS:
            continue
        inputs = raw_step.get("input_artifacts") or []
        outputs = raw_step.get("output_artifacts") or []
        for item in [*inputs, *outputs]:
            if isinstance(item, dict) and item.get("path"):
                nodes[str(item["path"])] = dict(item)
        for source in inputs:
            if not isinstance(source, dict) or not source.get("path"):
                continue
            for target in outputs:
                if not isinstance(target, dict) or not target.get("path"):
                    continue
                edges.append(
                    {
                        "source": str(source["path"]),
                        "target": str(target["path"]),
                        "step": str(step_id),
                    }
                )
        steps.append(
            {
                "step": str(step_id),
                "status": str(raw_step.get("status") or ""),
                "attempts": int(raw_step.get("attempts") or 0),
                "verification_status": str(raw_step.get("verification_status") or "not_checked"),
                "input_hash": str(raw_step.get("input_hash") or ""),
                "updated_at": str(raw_step.get("updated_at") or ""),
            }
        )
    return {
        "schema_version": LINEAGE_SCHEMA,
        "run_id": state.get("run_id", ""),
        "generated_at": now_iso(),
        "scientific_boundary": (
            "Lineage proves file derivation and content identity. "
            "It does not by itself prove scientific validity."
        ),
        "model_provenance": (
            "paper/audit/model-provenance.csv"
            if (review_dir / "paper" / "audit" / "model-provenance.csv").is_file()
            else ""
        ),
        "source_provenance": (
            "searches/search-log.csv"
            if (review_dir / "searches" / "search-log.csv").is_file()
            else ""
        ),
        "nodes": sorted(nodes.values(), key=lambda item: str(item["path"])),
        "edges": sorted(edges, key=lambda item: (item["source"], item["target"], item["step"])),
        "steps": steps,
    }


def write_lineage(review_dir: pathlib.Path, state: dict[str, Any]) -> pathlib.Path:
    """Persist the artifact graph next to the private runtime state."""
    return write_json_atomic(review_dir / "notes" / "artifact-lineage.json", lineage_payload(review_dir, state))


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
        "input_artifacts": artifact_metadata(review_dir, expand_patterns(review_dir, inputs)),
        "output_artifacts": artifact_metadata(review_dir, output_paths(review_dir, outputs)),
        "verification_status": (
            "verified"
            if status in {"completed", "skipped"} and outputs_ready(review_dir, outputs)
            else "failed"
            if status == "failed"
            else "pending"
        ),
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
    state_file = write_json_atomic(state_path(review_dir), state)
    # Public lineage represents materialized derivations, not in-flight intent.
    if status != "running":
        write_lineage(review_dir, state)
    return state_file


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
