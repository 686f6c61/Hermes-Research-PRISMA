#!/usr/bin/env python3
"""Run one autonomous review job with durable heartbeat and phase state."""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import subprocess
import tempfile
import time
from datetime import datetime, timezone

SCHEMA_VERSION = "hermes.research-job/v1"


def now_iso() -> str:
    """Return a timezone-aware timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def write_json_atomic(path: pathlib.Path, payload: dict[str, object]) -> None:
    """Persist job state without exposing a partially written JSON document."""
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
    os.replace(temp_path, path)


def run_phase(
    command: list[str],
    *,
    ledger_path: pathlib.Path,
    state: dict[str, object],
    phase: str,
    log_path: pathlib.Path,
    poll_seconds: float = 5.0,
) -> int:
    """Run one phase and refresh its heartbeat until the child exits."""
    state.update(
        {
            "status": "running",
            "phase": phase,
            "phase_started_at": now_iso(),
            "heartbeat_at": now_iso(),
            "child_pid": None,
            "last_exit_code": None,
        }
    )
    write_json_atomic(ledger_path, state)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    state["child_pid"] = process.pid
    write_json_atomic(ledger_path, state)
    while process.poll() is None:
        state["heartbeat_at"] = now_iso()
        write_json_atomic(ledger_path, state)
        time.sleep(max(poll_seconds, 1.0))
    exit_code = int(process.returncode or 0)
    state.update(
        {
            "heartbeat_at": now_iso(),
            "phase_finished_at": now_iso(),
            "last_exit_code": exit_code,
            "child_pid": None,
        }
    )
    write_json_atomic(ledger_path, state)
    return exit_code


def csv_has_data_rows(path: pathlib.Path) -> bool:
    """Treat template header-only CSV files as empty pipeline inputs."""
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return any(any(str(cell).strip() for cell in row) for row in reader)
    except (OSError, csv.Error):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-dir", type=pathlib.Path, required=True)
    parser.add_argument("--scripts-dir", type=pathlib.Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--skip-publication-layer", action="store_true")
    args = parser.parse_args()

    review_dir = args.review_dir.expanduser().resolve()
    scripts_dir = args.scripts_dir.expanduser().resolve()
    ledger_path = review_dir / "notes" / "job-ledger.json"
    log_path = review_dir / "notes" / "run.log"
    previous_attempt = 0
    if ledger_path.exists():
        try:
            previous_attempt = int(json.loads(ledger_path.read_text(encoding="utf-8")).get("attempt") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            previous_attempt = 0
    state: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "job_id": args.job_id,
        "runner_pid": os.getpid(),
        "review_dir": review_dir.name,
        "status": "starting",
        "phase": "initializing",
        "attempt": previous_attempt + 1,
        "started_at": now_iso(),
        "heartbeat_at": now_iso(),
        "smoke_test": args.smoke_test,
    }
    write_json_atomic(ledger_path, state)
    has_search_material = csv_has_data_rows(review_dir / "searches" / "search-log.csv") and csv_has_data_rows(
        review_dir / "records" / "master-records.csv"
    )
    phases: list[tuple[str, list[str]]] = []
    if not has_search_material:
        phases.append(
            (
                "protocol_and_search",
                ["python3", "-u", str(scripts_dir / "bootstrap_topic_review.py"), str(review_dir)],
            )
        )
    if not args.smoke_test:
        review_command = ["python3", "-u", str(scripts_dir / "complete_review.py")]
        if args.skip_publication_layer:
            review_command.append("--skip-publication-layer")
        review_command.append(str(review_dir))
        phases.append(
            (
                "review_end_to_end",
                review_command,
            )
        )
    for phase, command in phases:
        exit_code = run_phase(
            command,
            ledger_path=ledger_path,
            state=state,
            phase=phase,
            log_path=log_path,
        )
        if exit_code != 0:
            state.update(
                {
                    "status": "failed",
                    "failed_phase": phase,
                    "finished_at": now_iso(),
                    "heartbeat_at": now_iso(),
                }
            )
            write_json_atomic(ledger_path, state)
            return exit_code
    state.update(
        {
            "status": "completed",
            "phase": "completed",
            "finished_at": now_iso(),
            "heartbeat_at": now_iso(),
            "last_exit_code": 0,
        }
    )
    write_json_atomic(ledger_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
