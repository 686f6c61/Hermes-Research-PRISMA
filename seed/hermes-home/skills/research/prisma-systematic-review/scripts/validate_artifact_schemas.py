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


def csv_integrity_issues(path: pathlib.Path, relative: str) -> list[str]:
    """Detect material row corruption that a valid header would otherwise hide."""
    if relative != "selection/ultraquality-shortlist.csv" or not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    malformed = [
        row
        for row in rows
        if row.get("record_id")
        and not any(
            str(row.get(field) or "").strip()
            for field in ("assigned_doi", "title_original", "selected_for_final_n", "ultraquality_score")
        )
    ]
    if len(malformed) > max(5, len(rows) // 4):
        return [f"malformed_rows:{len(malformed)}/{len(rows)}"]
    return []


def validate(review_dir: pathlib.Path) -> dict[str, object]:
    """Validate every declared artifact that exists and report missing required files."""
    config = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    checks: list[dict[str, object]] = []
    for relative, contract in config.get("csv", {}).items():
        path = review_dir / relative
        artifact_required = bool(contract.get("required", True))
        header = csv_header(path)
        required = list(contract.get("required_columns") or [])
        missing = [field for field in required if field not in header]
        integrity_issues = csv_integrity_issues(path, relative)
        if not path.exists() and not artifact_required:
            status = "skip"
            missing = []
            integrity_issues = []
        else:
            status = "pass" if path.exists() and not missing and not integrity_issues else "fail"
        checks.append(
            {
                "path": relative,
                "kind": "csv",
                "version": contract.get("version", ""),
                "status": status,
                "missing": missing if path.exists() or status == "skip" else ["file"],
                "integrity_issues": integrity_issues,
                "required": artifact_required,
            }
        )
    for relative, raw_contract in config.get("json", {}).items():
        path = review_dir / relative
        if isinstance(raw_contract, dict):
            required = list(raw_contract.get("required_keys") or [])
            artifact_required = bool(raw_contract.get("required", True))
        else:
            required = list(raw_contract or [])
            artifact_required = True
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            payload = {}
        missing = required_keys(payload, required)
        if not path.exists() and not artifact_required:
            status = "skip"
            missing = []
        else:
            status = "pass" if path.exists() and not missing else "fail"
        checks.append(
            {
                "path": relative,
                "kind": "json",
                "version": str(payload.get("schema_version") or ""),
                "status": status,
                "missing": missing if path.exists() or status == "skip" else ["file"],
                "required": artifact_required,
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
        integrity = ", ".join(check.get("integrity_issues") or []) or "ninguno"
        lines.append(
            f"- `{str(check['status']).upper()}` `{check['path']}` "
            f"({check['kind']} {check['version'] or 'sin versión'}"
            f"{', opcional' if not check.get('required', True) else ''}): faltan {missing}; "
            f"integridad {integrity}."
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
