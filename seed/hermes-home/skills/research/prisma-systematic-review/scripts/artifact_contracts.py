"""Small, dependency-free contracts shared by the research pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
from typing import Any, Iterable

CONTRACT_VERSION = "hermes.review-artifacts/v1"


def read_json(path: pathlib.Path, default: Any = None) -> Any:
    """Read JSON without allowing a malformed file to crash status inspection."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: pathlib.Path, payload: Any) -> pathlib.Path:
    """Replace a JSON artifact atomically and persist the directory entry."""
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
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return path
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return path


def sha256_file(path: pathlib.Path) -> str:
    """Return a stable content hash for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_digest(paths: Iterable[pathlib.Path], *, root: pathlib.Path | None = None) -> str:
    """Hash paths and contents so pipeline steps can be skipped safely."""
    digest = hashlib.sha256()
    existing = sorted({path.resolve() for path in paths if path.exists() and path.is_file()})
    for path in existing:
        try:
            label = path.relative_to(root.resolve()).as_posix() if root else path.as_posix()
        except ValueError:
            label = path.as_posix()
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    if not existing:
        digest.update(b"no-input-files")
    return digest.hexdigest()


def expand_patterns(root: pathlib.Path, patterns: Iterable[str]) -> list[pathlib.Path]:
    """Expand relative glob patterns into a deterministic list of files."""
    paths: list[pathlib.Path] = []
    for pattern in patterns:
        paths.extend(path for path in root.glob(pattern) if path.is_file())
    return sorted(set(paths))


def required_keys(payload: dict[str, Any], keys: Iterable[str]) -> list[str]:
    """Return missing or empty top-level contract keys."""
    missing: list[str] = []
    for key in keys:
        value = payload.get(key)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(key)
    return missing
