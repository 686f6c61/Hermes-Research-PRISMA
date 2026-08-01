"""Tests for independent screening agreement and traceability artifacts."""

from __future__ import annotations

import csv
import json
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from screening_reliability import (
    cohen_kappa,
    resolve_title_abstract,
    stage_metrics,
    write_dual_review_artifacts,
)


def test_metrics_report_disagreement_without_calling_it_ground_truth() -> None:
    rows = [
        {"reviewer_a_decision": "include", "reviewer_b_decision": "include"},
        {"reviewer_a_decision": "exclude", "reviewer_b_decision": "exclude"},
        {"reviewer_a_decision": "include", "reviewer_b_decision": "exclude"},
        {"reviewer_a_decision": "exclude", "reviewer_b_decision": "include"},
    ]

    metrics = stage_metrics(rows, "full_text")

    assert metrics["raw_agreement"] == 0.5
    assert metrics["disagreements"] == 2
    assert cohen_kappa(rows, "full_text") == 0.0


def test_title_abstract_disagreement_stays_eligible_for_full_text() -> None:
    assert resolve_title_abstract("exclude", "include") == "maybe"
    assert resolve_title_abstract("include", "maybe") == "maybe"
    assert resolve_title_abstract("exclude", "exclude") == "exclude"


def test_artifacts_keep_each_judgment_and_limitation(tmp_path: pathlib.Path) -> None:
    review_dir = tmp_path / "review"
    rows = [
        {
            "stage": "full_text",
            "record_id": "doi:10.1000/example",
            "assigned_doi": "10.1000/example",
            "reviewer_a_decision": "include",
            "reviewer_b_decision": "exclude",
            "agreement": "no",
            "adjudicator_decision": "include",
            "final_decision": "include",
            "reviewer_a_engine": "model-a",
            "reviewer_b_engine": "model-b",
            "adjudicator_engine": "model-c",
        }
    ]

    csv_path, report_path = write_dual_review_artifacts(
        review_dir,
        "full_text",
        rows,
        limitations=["Reviewer A and adjudicator used the same model family."],
    )

    with csv_path.open(encoding="utf-8", newline="") as handle:
        written = list(csv.DictReader(handle))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert written[0]["reviewer_b_decision"] == "exclude"
    assert written[0]["adjudicator_decision"] == "include"
    assert report["stages"]["full_text"]["disagreements"] == 1
    assert "ground truth" in report["interpretation"]
