#!/usr/bin/env python3
"""Validate versioned CSV and JSON artifacts for one review workspace."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
from datetime import datetime, timezone

from artifact_contracts import required_keys, write_json_atomic

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent.parent / "config" / "artifact-schemas.json"


def csv_header(path: pathlib.Path) -> list[str]:
    """Read only the CSV header so validation stays cheap on large corpora."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader, [])


def validate(review_dir: pathlib.Path) -> dict[str, object]:
    """Validate every declared artifact that exists and report missing required files."""
    config = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    checks: list[dict[str, object]] = []
    for relative, contract in config.get("csv", {}).items():
        path = review_dir / relative
        header = csv_header(path)
        required = list(contract.get("required_columns") or [])
        missing = [field for field in required if field not in header]
        checks.append(
            {
                "path": relative,
                "kind": "csv",
                "version": contract.get("version", ""),
                "status": "pass" if path.exists() and not missing else "fail",
                "missing": missing if path.exists() else ["file"],
            }
        )
    for relative, required in config.get("json", {}).items():
        path = review_dir / relative
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            payload = {}
        missing = required_keys(payload, required)
        checks.append(
            {
                "path": relative,
                "kind": "json",
                "version": str(payload.get("schema_version") or ""),
                "status": "pass" if path.exists() and not missing else "fail",
                "missing": missing if path.exists() else ["file"],
            }
        )
    failed = [check for check in checks if check["status"] == "fail"]
    return {
        "schema_version": "hermes.schema-validation/v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "fail" if failed else "pass",
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "checks": checks,
    }


def write_outputs(review_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, dict[str, object]]:
    """Write machine and reader-facing schema validation evidence."""
    result = validate(review_dir)
    audit_dir = review_dir / "paper" / "audit"
    json_path = write_json_atomic(audit_dir / "schema-validation.json", result)
    md_path = audit_dir / "schema-validation.md"
    lines = [
        "# Validación de contratos de artefactos",
        "",
        f"- Estado: **{str(result['status']).upper()}**",
        f"- Contratos comprobados: {result['checks_total']}",
        f"- Fallos: {result['checks_failed']}",
        "",
        "## Comprobaciones",
    ]
    for check in result["checks"]:
        missing = ", ".join(check["missing"]) or "ninguno"
        lines.append(
            f"- `{str(check['status']).upper()}` `{check['path']}` "
            f"({check['kind']} {check['version'] or 'sin versión'}): faltan {missing}."
        )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    json_path, md_path, result = write_outputs(review_dir)
    print(
        json.dumps(
            {"status": result["status"], "json": str(json_path), "markdown": str(md_path)},
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
