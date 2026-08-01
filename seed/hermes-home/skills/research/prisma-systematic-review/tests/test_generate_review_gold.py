"""Tests for review-specific machine-adjudicated reference sets."""

from __future__ import annotations

import csv
import json
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from generate_review_gold import build_gold


def write_csv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_gold_is_traceable_and_not_claimed_as_human_truth(
    tmp_path: pathlib.Path,
) -> None:
    review_dir = tmp_path / "review"
    dual_row = {
        "record_id": "doi:10.1000/example",
        "assigned_doi": "10.1000/example",
        "final_decision": "include",
        "adjudicator_decision": "",
        "reviewer_a_engine": "model-a",
        "reviewer_b_engine": "model-b",
        "adjudicator_engine": "",
    }
    write_csv(
        review_dir / "screening" / "title-abstract-dual-review.csv",
        [dual_row],
    )
    write_csv(
        review_dir / "screening" / "full-text-dual-review.csv",
        [dual_row],
    )
    write_csv(
        review_dir / "extraction" / "extraction-table.csv",
        [
            {
                "record_id": "doi:10.1000/example",
                "assigned_doi": "10.1000/example",
                "evidence_snippet": "Reported result",
                "evidence_location": "Results, p. 5",
            }
        ],
    )

    manifest = build_gold(review_dir)
    output_dir = review_dir / "paper" / "audit" / "gold"
    card = (output_dir / "DATASET-CARD.md").read_text(encoding="utf-8")
    on_disk = json.loads(
        (output_dir / "gold-manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["external_human_ground_truth"] is False
    assert on_disk["counts"]["extraction_with_evidence"] == 1
    assert "must not be reported as external" in card
    assert (output_dir / "full-text-gold.csv").is_file()


def test_gold_records_signed_researcher_resolution_without_claiming_ground_truth(
    tmp_path: pathlib.Path,
) -> None:
    review_dir = tmp_path / "review"
    consensus = {
        "record_id": "doi:10.1000/consensus",
        "assigned_doi": "10.1000/consensus",
        "final_decision": "include",
        "adjudicator_decision": "",
        "researcher_decision": "",
        "reviewer_a_engine": "model-a",
        "reviewer_b_engine": "model-b",
        "adjudicator_engine": "",
    }
    resolved = {
        **consensus,
        "record_id": "doi:10.1000/resolved",
        "assigned_doi": "10.1000/resolved",
        "adjudicator_decision": "exclude",
        "researcher_decision": "include",
    }
    write_csv(
        review_dir / "screening" / "title-abstract-dual-review.csv",
        [consensus],
    )
    write_csv(
        review_dir / "screening" / "full-text-dual-review.csv",
        [resolved],
    )
    write_csv(
        review_dir / "extraction" / "extraction-table.csv",
        [
            {
                "record_id": "doi:10.1000/resolved",
                "assigned_doi": "10.1000/resolved",
                "evidence_snippet": "Reported result",
                "evidence_location": "Results, p. 5",
            }
        ],
    )

    build_gold(review_dir)

    with (
        review_dir / "paper" / "audit" / "gold" / "full-text-gold.csv"
    ).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["reference_basis"] == "signed_researcher_resolution"
