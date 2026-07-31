"""Runtime helpers for the Hermes Research plugin."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def plugin_dir() -> Path:
    """Return the on-disk directory that contains this plugin."""
    return Path(__file__).resolve().parent


def hermes_home() -> Path:
    """Resolve the active Hermes home directory.

    The public bundle exports ``HERMES_HOME=/opt/data`` inside containers. For
    local development we fall back to the nearest ``hermes-home`` ancestor.
    """
    env_home = os.getenv("HERMES_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    for parent in plugin_dir().parents:
        if parent.name == "hermes-home":
            return parent
    return Path.home() / ".hermes"


def workspace_root() -> Path:
    """Resolve the workspace root used by the research workflow."""
    explicit = os.getenv("HERMES_RESEARCH_WORKSPACE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    container_workspace = Path("/workspace")
    if container_workspace.exists():
        return container_workspace

    sibling_workspace = hermes_home().parent / "workspace"
    if sibling_workspace.exists():
        return sibling_workspace

    # In the public bundle source tree the plugin lives under
    # ``seed/hermes-home/plugins/...`` while the materialized runtime template
    # sits under ``runtime/workspace`` next to ``seed``.
    bundle_runtime_workspace = hermes_home().parent.parent / "runtime" / "workspace"
    if bundle_runtime_workspace.exists():
        return bundle_runtime_workspace

    cwd = os.getenv("TERMINAL_CWD", "").strip()
    if cwd:
        return Path(cwd).expanduser().resolve()

    return hermes_home() / "workspace"


def public_bindings_path() -> Path:
    """Return the shared chat-to-review binding store."""
    return hermes_home() / "public-prisma-bindings.json"


def prisma_scripts_dir() -> Path:
    """Return the PRISMA script directory inside Hermes home."""
    return hermes_home() / "skills" / "research" / "prisma-systematic-review" / "scripts"


def prisma_status_script() -> Path:
    """Return the operational status summarizer script."""
    return hermes_home() / "skills" / "research" / "prisma-status" / "scripts" / "review_status.py"


def research_skill_dir(name: str) -> Path:
    """Return the directory for a bundled research skill."""
    return hermes_home() / "skills" / "research" / name


def ensure_workspace() -> Path:
    """Ensure the workspace root exists before commands use it."""
    root = workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_review_dir(path: Path) -> bool:
    """Return True only for a materialized systematic-review workspace."""
    try:
        candidate = path.expanduser().resolve()
    except OSError:
        return False
    return (
        candidate.is_dir()
        and candidate.name.startswith("systematic-review-")
        and candidate.name != "systematic-review-template"
        and (candidate / "protocol" / "intake.md").is_file()
    )


def latest_review_dir() -> Path | None:
    """Return the newest systematic-review workspace, if any."""
    root = ensure_workspace()
    candidates = [
        path for path in root.iterdir()
        if is_review_dir(path)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def resolve_review_dir(token: str | None) -> Path | None:
    """Resolve an explicit review token or fall back to the latest review."""
    value = (token or "").strip()
    if not value:
        return latest_review_dir()

    explicit = Path(value).expanduser()
    if is_review_dir(explicit):
        return explicit.resolve()

    root = ensure_workspace()
    direct = root / value
    if is_review_dir(direct):
        return direct.resolve()

    matches = [path for path in root.iterdir() if is_review_dir(path) and path.name == value]
    if matches:
        return matches[0].resolve()

    suffix_matches = [path for path in root.iterdir() if is_review_dir(path) and path.name.endswith(value)]
    if suffix_matches:
        return max(suffix_matches, key=lambda path: path.stat().st_mtime).resolve()

    return None


def run_command_capture(
    cmd: list[str],
    cwd: Path | None = None,
    *,
    timeout: float | None = None,
) -> str:
    """Run a command and return combined stdout/stderr as UTF-8 text."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout} seconds: {cmd[0]}") from exc
    output = proc.stdout or ""
    if proc.returncode != 0:
        raise RuntimeError(output.strip() or f"Command failed with exit code {proc.returncode}")
    return output


def parse_json_line(output: str) -> dict[str, Any]:
    """Parse the last non-empty output line as JSON."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("The command returned no structured output.")
    return json.loads(lines[-1])


def launch_background(command: list[str], log_path: Path, cwd: Path | None = None) -> int:
    """Launch a detached process and append its output to ``log_path``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    handle.close()
    return int(process.pid)


def autonomous_mode_enabled(value: str | None) -> bool:
    """Return True when the public intake requests autonomous continuation."""
    normalized = (value or "").strip().lower()
    return normalized not in {"", "no", "n", "false", "0", "off"}


def public_autonomous_pid_path(review_dir: Path) -> Path:
    """Return the compatibility marker for older command handlers."""
    return review_dir / "notes" / "public-autonomous.pid"


def public_job_ledger_path(review_dir: Path) -> Path:
    """Return the durable autonomous job ledger."""
    return review_dir / "notes" / "job-ledger.json"


def launch_public_autonomous_review(review_dir: Path) -> int:
    """Start the heartbeat-aware autonomous runner in the background."""
    notes_dir = review_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    log_path = notes_dir / "run.log"
    smoke_test = os.environ.get("HERMES_RESEARCH_SMOKE_TEST", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    job_id = uuid.uuid4().hex
    command = [
        sys.executable,
        "-u",
        str(plugin_dir() / "job_runner.py"),
        "--review-dir",
        str(review_dir),
        "--scripts-dir",
        str(prisma_scripts_dir()),
        "--job-id",
        job_id,
    ]
    if smoke_test:
        command.append("--smoke-test")
    pid = launch_background(command, log_path, cwd=review_dir.parent)
    public_autonomous_pid_path(review_dir).write_text(
        json.dumps(
            {
                "pid": pid,
                "job_id": job_id,
                "started_at": iso_now(),
                "ledger": str(public_job_ledger_path(review_dir)),
                "runner": str(plugin_dir() / "job_runner.py"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return pid


def write_temp_json(payload: dict[str, Any]) -> Path:
    """Write a temporary JSON file used by the deterministic bootstrap."""
    temp_dir = hermes_home() / "home" / "default" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        suffix=".json",
        dir=temp_dir,
        delete=False,
        encoding="utf-8",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    # Intake data can contain author names and contact details.
    temp_path.chmod(0o600)
    return temp_path


def iso_now() -> str:
    """Return a timezone-aware timestamp string."""
    return datetime.now(timezone.utc).isoformat()
