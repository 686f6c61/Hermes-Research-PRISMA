"""Tests for durable full-text judgments across researcher pauses."""

from __future__ import annotations

import importlib
import json
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def load_pipeline(monkeypatch):
    """Import the pipeline with an inert cloud configuration."""

    monkeypatch.setenv("HERMES_INFERENCE_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("HERMES_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HERMES_MODEL_PRIMARY", "model-a")
    monkeypatch.setenv("HERMES_MODEL_REVIEW", "model-b")
    monkeypatch.setenv("HERMES_RESEARCHER_NAME", "Research Owner")
    monkeypatch.setenv("HERMES_RESEARCHER_EMAIL", "owner@example.org")
    monkeypatch.setenv("HERMES_ADJUDICATION_SECRET", "c" * 64)
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    sys.modules.pop("complete_review", None)
    return importlib.import_module("complete_review")


def materialize_review(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create the frozen protocol required by disagreement signatures."""

    review_dir = tmp_path / "review"
    manifest = review_dir / "protocol" / "contracts-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"schema_version": "test", "contracts": []}),
        encoding="utf-8",
    )
    return review_dir


def test_checkpoint_is_reused_only_for_identical_protocol_and_evidence(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    pipeline = load_pipeline(monkeypatch)
    review_dir = materialize_review(tmp_path)
    candidates = [
        {
            "record_id": "doi:10.1000/example",
            "assigned_doi": "10.1000/example",
            "full_text_text": "A stable full-text evidence body.",
        }
    ]
    primary = {
        "doi:10.1000/example": {
            "decision": "include",
            "reason": "eligible",
        }
    }
    secondary = {
        "doi:10.1000/example": {
            "decision": "exclude",
            "reason": "population mismatch",
        }
    }

    pipeline.write_full_text_review_checkpoint(
        review_dir,
        candidates,
        primary,
        secondary,
    )

    assert pipeline.load_full_text_review_checkpoint(
        review_dir,
        candidates,
    ) == (primary, secondary)
    changed = [{**candidates[0], "full_text_text": "Changed evidence."}]
    assert pipeline.load_full_text_review_checkpoint(review_dir, changed) is None


def test_each_reviewer_has_an_independent_resumable_checkpoint(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    pipeline = load_pipeline(monkeypatch)
    review_dir = materialize_review(tmp_path)
    candidates = [
        {
            "record_id": "doi:10.1000/one",
            "assigned_doi": "10.1000/one",
            "full_text_text": "Stable full-text evidence.",
        },
        {
            "record_id": "doi:10.1000/two",
            "assigned_doi": "10.1000/two",
            "full_text_text": "Second stable evidence body.",
        },
    ]
    first_result = {
        "doi:10.1000/one": {
            "decision": "include",
            "reason": "eligible",
        }
    }

    pipeline.write_partial_full_text_reviewer_checkpoint(
        review_dir,
        candidates,
        "reviewer_a",
        first_result,
    )

    assert pipeline.load_partial_full_text_reviewer_checkpoint(
        review_dir,
        candidates,
        "reviewer_a",
    ) == first_result
    assert pipeline.load_partial_full_text_reviewer_checkpoint(
        review_dir,
        candidates,
        "reviewer_b",
    ) == {}
    changed = [{**candidates[0], "full_text_text": "Changed evidence."}, candidates[1]]
    assert pipeline.load_partial_full_text_reviewer_checkpoint(
        review_dir,
        changed,
        "reviewer_a",
    ) == {}


def test_signed_choice_applies_to_the_exact_preserved_case(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    pipeline = load_pipeline(monkeypatch)
    disagreement = importlib.import_module("screening_disagreement")
    review_dir = materialize_review(tmp_path)
    row = {
        "record_id": "doi:10.1000/example",
        "assigned_doi": "10.1000/example",
        "title_original": "Disputed study",
    }
    original_a = {
        "decision": "include",
        "reason": "eligible",
        "_engine": "model-a",
    }
    original_b = {
        "decision": "exclude",
        "reason": "population mismatch",
        "_engine": "model-b",
    }
    recommendation = {
        "decision": "exclude",
        "reason": "automatic recommendation",
        "_engine": "model-c",
    }
    case = disagreement.build_case(
        review_dir,
        row,
        original_a,
        original_b,
        recommendation,
    )
    disagreement.write_pending_cases(review_dir, [case])
    disagreement.record_resolution(
        review_dir,
        doi="10.1000/example",
        decision="include",
        reason="The population matches the frozen eligibility contract.",
    )

    resolved = pipeline.reconcile_full_text_reviews(
        review_dir,
        [row],
        {
            row["record_id"]: {
                "decision": "exclude",
                "reason": "a later model output must not replace the case",
            }
        },
        {
            row["record_id"]: {
                "decision": "exclude",
                "reason": "a later model output must not replace the case",
            }
        },
        {},
        [],
    )

    assert resolved[row["record_id"]]["decision"] == "include"
    pending = json.loads(
        (
            review_dir / "screening" / "pending-disagreements.json"
        ).read_text(encoding="utf-8")
    )
    assert pending["status"] == "resolved"
    assert pending["cases"] == [case]
    assert pending["resolved_count"] == 1
    assert pending["unresolved_count"] == 0

    resolved_again = pipeline.reconcile_full_text_reviews(
        review_dir,
        [row],
        {
            row["record_id"]: {
                "decision": "exclude",
                "reason": "new output after an interrupted editorial phase",
            }
        },
        {
            row["record_id"]: {
                "decision": "exclude",
                "reason": "new output after an interrupted editorial phase",
            }
        },
        {},
        [],
    )

    assert resolved_again[row["record_id"]]["decision"] == "include"
    assert (
        resolved_again[row["record_id"]]["_engine"]
        == "signed_researcher_resolution"
    )
