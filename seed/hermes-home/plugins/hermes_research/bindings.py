"""Chat-to-review binding helpers for the Hermes Research plugin."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import runtime


@contextmanager
def _lock(path: Path, *, exclusive: bool):
    """Serialize binding reads and writes across gateway workers."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_unlocked(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        # Flush both Python and kernel buffers before the atomic replacement.
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.chmod(0o600)
    temp_path.replace(path)


def bind_review(binding_key: str, review_dir: Path) -> None:
    """Persist the review directory associated with a gateway chat binding."""
    if not binding_key:
        return
    path = runtime.public_bindings_path()
    with _lock(path, exclusive=True):
        data = _load_unlocked(path)
        data[binding_key] = {
            "review_dir": str(review_dir),
            "review_name": review_dir.name,
            "updated_at": runtime.iso_now(),
        }
        _save_unlocked(path, data)


def resolve_bound_review(binding_key: str) -> Path | None:
    """Resolve the latest review directory associated with ``binding_key``."""
    if not binding_key:
        return None
    path = runtime.public_bindings_path()
    with _lock(path, exclusive=False):
        data = _load_unlocked(path)
    entry = data.get(binding_key) or {}
    if not isinstance(entry, dict):
        return None
    raw_path = str(entry.get("review_dir", "") or "").strip()
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if runtime.is_review_dir(candidate):
        return candidate.resolve()
    return None
