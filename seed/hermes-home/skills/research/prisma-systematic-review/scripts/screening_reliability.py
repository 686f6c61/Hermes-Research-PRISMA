"""Agreement metrics and auditable artifacts for independent screening."""

from __future__ import annotations

import csv
import json
import pathlib
import tempfile
from collections import Counter
from datetime import datetime, timezone
from typing import Any

DUAL_REVIEW_FIELDS = [
    "stage",
    "record_id",
    "assigned_doi",
    "reviewer_a_decision",
    "reviewer_b_decision",
    "agreement",
    "adjudicator_decision",
    "researcher_decision",
    "final_decision",
    "reviewer_a_reason",
    "reviewer_b_reason",
    "adjudicator_reason",
    "researcher_reason",
    "reviewer_a_engine",
    "reviewer_b_engine",
    "adjudicator_engine",
    "researcher_identity",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def binary_decision(decision: str, stage: str) -> str:
    """Map stage-specific labels to comparable include/exclude classes."""

    normalized = (decision or "").strip().lower()
    if stage == "title_abstract":
        return "exclude" if normalized == "exclude" else "include"
    return "include" if normalized in {"include", "include_ft"} else "exclude"


def cohen_kappa(rows: list[dict[str, Any]], stage: str) -> float | None:
    """Calculate Cohen's kappa for two complete automatic judgments."""

    pairs = [
        (
            binary_decision(str(row.get("reviewer_a_decision", "")), stage),
            binary_decision(str(row.get("reviewer_b_decision", "")), stage),
        )
        for row in rows
        if row.get("reviewer_a_decision") and row.get("reviewer_b_decision")
    ]
    if not pairs:
        return None
    observed = sum(left == right for left, right in pairs) / len(pairs)
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum(
        (left_counts[label] / len(pairs)) * (right_counts[label] / len(pairs))
        for label in {"include", "exclude"}
    )
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return round((observed - expected) / (1 - expected), 4)


def stage_metrics(rows: list[dict[str, Any]], stage: str) -> dict[str, Any]:
    """Summarize agreement without hiding disagreements or missing judgments."""

    complete = [
        row
        for row in rows
        if row.get("reviewer_a_decision") and row.get("reviewer_b_decision")
    ]
    agreements = [
        row
        for row in complete
        if binary_decision(str(row["reviewer_a_decision"]), stage)
        == binary_decision(str(row["reviewer_b_decision"]), stage)
    ]
    disagreements = len(complete) - len(agreements)
    return {
        "records": len(rows),
        "paired_judgments": len(complete),
        "agreements": len(agreements),
        "disagreements": disagreements,
        "raw_agreement": round(len(agreements) / len(complete), 4) if complete else None,
        "disagreement_rate": round(disagreements / len(complete), 4) if complete else None,
        "cohen_kappa": cohen_kappa(complete, stage),
        "adjudicated_disagreements": sum(
            bool(row.get("adjudicator_decision")) for row in complete
        ),
        "researcher_resolved_disagreements": sum(
            bool(row.get("researcher_decision")) for row in complete
        ),
    }


def write_dual_review_artifacts(
    review_dir: pathlib.Path,
    stage: str,
    rows: list[dict[str, Any]],
    *,
    limitations: list[str] | None = None,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Write record-level judgments and a cumulative reliability report."""

    screening_dir = review_dir / "screening"
    screening_dir.mkdir(parents=True, exist_ok=True)
    csv_path = screening_dir / f"{stage.replace('_', '-')}-dual-review.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DUAL_REVIEW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in DUAL_REVIEW_FIELDS})

    report_path = screening_dir / "screening-reliability.json"
    report: dict[str, Any] = {}
    if report_path.is_file():
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                report = loaded
        except (OSError, json.JSONDecodeError):
            report = {}
    report.update(
        {
            "schema_version": "hermes.screening-reliability/v1",
            "updated_at": now_iso(),
            "interpretation": (
                "Agreement statistics describe consistency between independent "
                "automatic judgments; they do not establish ground truth."
            ),
        }
    )
    stages = report.setdefault("stages", {})
    stages[stage] = {
        **stage_metrics(rows, stage),
        "decisions_path": str(csv_path.relative_to(review_dir)),
        "limitations": limitations or [],
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=screening_dir,
        prefix=".screening-reliability.",
        delete=False,
    ) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = pathlib.Path(handle.name)
    temporary.replace(report_path)
    return csv_path, report_path


def resolve_title_abstract(primary: str, secondary: str) -> str:
    """Use a conservative rule when title/abstract judgments disagree."""

    left = (primary or "").strip().lower()
    right = (secondary or "").strip().lower()
    if left == right:
        return left
    if "exclude" in {left, right}:
        return "maybe"
    return "maybe"
