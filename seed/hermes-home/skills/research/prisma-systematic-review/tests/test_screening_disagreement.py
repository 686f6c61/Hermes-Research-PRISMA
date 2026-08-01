"""Tests for recoverable, signed screening disagreements."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from review_runtime_state import determine_state
from screening_disagreement import (
    build_case,
    record_resolution,
    resolution_for_case,
    resolution_status,
    write_pending_cases,
)


def signing_env() -> dict[str, str]:
    return {
        "HERMES_RESEARCHER_NAME": "Research Owner",
        "HERMES_RESEARCHER_EMAIL": "owner@example.org",
        "HERMES_RESEARCHER_ORCID": "",
        "HERMES_ADJUDICATION_SECRET": "c" * 64,
    }


def make_case(review_dir: pathlib.Path) -> dict:
    return build_case(
        review_dir,
        {
            "record_id": "doi:10.1000/example",
            "assigned_doi": "10.1000/example",
            "title_original": "Disputed study",
        },
        {"decision": "include", "reason": "meets", "_engine": "model-a"},
        {"decision": "exclude", "reason": "population", "_engine": "model-b"},
        {
            "decision": "exclude",
            "reason": "recommend exclusion",
            "_engine": "model-c",
        },
    )


def test_disagreement_preserves_work_and_waits_for_researcher(
    tmp_path: pathlib.Path,
) -> None:
    review_dir = tmp_path / "review"
    case = make_case(review_dir)

    path = write_pending_cases(review_dir, [case])
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "waiting_for_researcher"
    assert payload["cases"][0]["automatic_recommendation"]["decision"] == "exclude"
    assert resolution_for_case(review_dir, case, env=signing_env()) is None


def test_only_signed_resolution_for_exact_case_can_continue(
    tmp_path: pathlib.Path,
) -> None:
    review_dir = tmp_path / "review"
    case = make_case(review_dir)
    write_pending_cases(review_dir, [case])

    record_resolution(
        review_dir,
        doi="10.1000/example",
        decision="include",
        reason="The construct is central after reviewing both rationales.",
        env=signing_env(),
    )
    resolution = resolution_for_case(review_dir, case, env=signing_env())

    assert resolution is not None
    assert resolution["decision"] == "include"
    status = resolution_status(review_dir, env=signing_env())
    assert status["resolved"] == 1
    assert status["unresolved"] == 0
    assert status["status"] == "ready_to_resume"

    changed_case = {**case, "case_id": "different"}
    assert resolution_for_case(
        review_dir,
        changed_case,
        env=signing_env(),
    ) is None


def test_runtime_state_waits_without_reporting_pipeline_failure(
    tmp_path: pathlib.Path,
) -> None:
    review_dir = tmp_path / "review"
    case = make_case(review_dir)
    write_pending_cases(review_dir, [case])

    state = determine_state(review_dir, stalled_minutes=0)

    assert state["status"] == "waiting_for_researcher"
    assert state["pending_disagreements"] == 1
    assert "no ha fallado" in state["blocker"]


def test_resolution_requires_a_scientific_reason(
    tmp_path: pathlib.Path,
) -> None:
    review_dir = tmp_path / "review"
    write_pending_cases(review_dir, [make_case(review_dir)])

    with pytest.raises(ValueError, match="scientific reason"):
        record_resolution(
            review_dir,
            doi="10.1000/example",
            decision="exclude",
            reason=" ",
            env=signing_env(),
        )
