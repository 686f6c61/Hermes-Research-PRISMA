#!/usr/bin/env python3
"""Generate machine-adjudicated reference sets for review regression tests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import tempfile
from collections import Counter
from datetime import datetime, timezone
from typing import Any

GOLD_FIELDS = [
    "record_id",
    "assigned_doi",
    "decision",
    "reference_basis",
    "confidence_tier",
    "reviewer_a_engine",
    "reviewer_b_engine",
    "adjudicator_engine",
]


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_atomic(
    path: pathlib.Path,
    rows: list[dict[str, Any]],
) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=GOLD_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in GOLD_FIELDS})
        temporary = pathlib.Path(handle.name)
    temporary.replace(path)
    return path


def write_text_atomic(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(content.rstrip() + "\n")
        temporary = pathlib.Path(handle.name)
    temporary.replace(path)
    return path


def reference_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Convert dual-review evidence into explicit operational labels."""

    references: list[dict[str, str]] = []
    for row in rows:
        final = (row.get("final_decision") or "").strip()
        if not final:
            continue
        adjudicated = bool((row.get("adjudicator_decision") or "").strip())
        researcher_resolved = bool(
            (row.get("researcher_decision") or "").strip()
        )
        same_engine = (
            (row.get("reviewer_a_engine") or "").strip()
            == (row.get("reviewer_b_engine") or "").strip()
        )
        references.append(
            {
                "record_id": row.get("record_id", ""),
                "assigned_doi": row.get("assigned_doi", ""),
                "decision": final,
                "reference_basis": (
                    "signed_researcher_resolution"
                    if researcher_resolved
                    else "automatic_adjudication"
                    if adjudicated
                    else "automatic_consensus"
                ),
                "confidence_tier": (
                    "moderate"
                    if (adjudicated and not researcher_resolved) or same_engine
                    else "high_operational"
                ),
                "reviewer_a_engine": row.get("reviewer_a_engine", ""),
                "reviewer_b_engine": row.get("reviewer_b_engine", ""),
                "adjudicator_engine": row.get("adjudicator_engine", ""),
            }
        )
    return references


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_gold(review_dir: pathlib.Path) -> dict[str, Any]:
    """Build decisions, structured extractions, a dataset card, and manifest."""

    output_dir = review_dir / "paper" / "audit" / "gold"
    output_dir.mkdir(parents=True, exist_ok=True)
    title_rows = reference_rows(
        read_csv(review_dir / "screening" / "title-abstract-dual-review.csv")
    )
    full_text_rows = reference_rows(
        read_csv(review_dir / "screening" / "full-text-dual-review.csv")
    )
    extraction_rows = read_csv(
        review_dir / "extraction" / "extraction-table.csv"
    )
    if not title_rows or not full_text_rows:
        raise RuntimeError(
            "Dual-review decisions are required before generating reference sets"
        )

    generated: list[pathlib.Path] = []
    generated.append(
        write_csv_atomic(output_dir / "title-abstract-gold.csv", title_rows)
    )
    generated.append(
        write_csv_atomic(output_dir / "full-text-gold.csv", full_text_rows)
    )
    extraction_path = output_dir / "extraction-gold.jsonl"
    extraction_content = "\n".join(
        json.dumps(
            {
                "schema_version": "hermes.extraction-reference/v1",
                "record": row,
                "reference_basis": "machine_extraction_with_source_location",
                "evidence_required": bool(
                    (row.get("evidence_snippet") or "").strip()
                    and (row.get("evidence_location") or "").strip()
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for row in extraction_rows
    )
    generated.append(write_text_atomic(extraction_path, extraction_content))

    title_counts = Counter(row["decision"] for row in title_rows)
    full_text_counts = Counter(row["decision"] for row in full_text_rows)
    evidence_complete = sum(
        bool(
            (row.get("evidence_snippet") or "").strip()
            and (row.get("evidence_location") or "").strip()
        )
        for row in extraction_rows
    )
    card = f"""# Machine-adjudicated review reference set

## Intended use

This versioned set supports regression testing, pipeline updates, and
reproducibility checks for this review. It records the final operational labels
that produced the current corpus and structured extraction.

## Important limitation

These labels are generated from independent automatic judgments,
evidence-linked extraction, and signed researcher decisions when automatic
judgments disagree at full text. The complete set has not been independently
annotated by external human reviewers and must not be reported as external
ground truth.

## Composition

- Title/abstract labels: {len(title_rows)}
- Full-text labels: {len(full_text_rows)}
- Structured extraction records: {len(extraction_rows)}
- Extractions with evidence snippet and location: {evidence_complete}
- Title/abstract distribution: {dict(sorted(title_counts.items()))}
- Full-text distribution: {dict(sorted(full_text_counts.items()))}

## Provenance

Every decision retains the engines involved and whether its basis was automatic
consensus, an automatic recommendation, or a signed researcher resolution.
Every extraction retains the DOI, extracted fields, evidence snippet, and
source location available in the review matrix.
"""
    generated.append(write_text_atomic(output_dir / "DATASET-CARD.md", card))

    manifest = {
        "schema_version": "hermes.review-gold/v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "scope": "machine_adjudicated_operational_reference",
        "external_human_ground_truth": False,
        "counts": {
            "title_abstract": len(title_rows),
            "full_text": len(full_text_rows),
            "extraction": len(extraction_rows),
            "extraction_with_evidence": evidence_complete,
        },
        "files": [
            {
                "path": str(path.relative_to(review_dir)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in generated
        ],
    }
    manifest_path = write_text_atomic(
        output_dir / "gold-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    return {**manifest, "manifest_path": str(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    print(json.dumps(build_gold(review_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
