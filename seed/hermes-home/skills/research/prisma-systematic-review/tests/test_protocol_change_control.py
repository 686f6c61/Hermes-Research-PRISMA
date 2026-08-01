"""Tests for frozen protocol amendments and signed approvals."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from protocol_change_control import (
    ProtocolChangeApprovalRequired,
    approval_matches,
    create_change_approval,
    require_change_approval,
)


def signing_env() -> dict[str, str]:
    return {
        "HERMES_RESEARCHER_NAME": "Research Owner",
        "HERMES_RESEARCHER_EMAIL": "owner@example.org",
        "HERMES_RESEARCHER_ORCID": "",
        "HERMES_ADJUDICATION_SECRET": "b" * 64,
    }


def test_material_change_is_explained_and_blocked(tmp_path: pathlib.Path) -> None:
    review_dir = tmp_path / "systematic-review-test"
    protocol = review_dir / "protocol"
    protocol.mkdir(parents=True)
    path = protocol / "intake.json"
    existing = {
        path: {
            "research_question": "Original",
            "eligibility": {"population": {"inclusion": "A"}},
        }
    }
    proposed = {
        path: {
            "research_question": "Revised",
            "eligibility": {"population": {"inclusion": "B"}},
        }
    }

    with pytest.raises(ProtocolChangeApprovalRequired):
        require_change_approval(review_dir, existing, proposed, env=signing_env())

    pending = json.loads((protocol / "pending-amendment.json").read_text(encoding="utf-8"))
    changed_paths = {
        item["path"]
        for contract in pending["contracts"]
        for item in contract["changes"]
    }
    assert {"research_question", "eligibility.population.inclusion"} <= changed_paths


def test_only_exact_signed_proposal_can_be_applied(tmp_path: pathlib.Path) -> None:
    review_dir = tmp_path / "systematic-review-test"
    protocol = review_dir / "protocol"
    protocol.mkdir(parents=True)
    path = protocol / "intake.json"
    existing = {path: {"research_question": "Original"}}
    proposed = {path: {"research_question": "Revised"}}

    with pytest.raises(ProtocolChangeApprovalRequired):
        require_change_approval(review_dir, existing, proposed, env=signing_env())
    create_change_approval(
        review_dir,
        reason="The population definition changed before screening.",
        env=signing_env(),
    )
    approved = require_change_approval(review_dir, existing, proposed, env=signing_env())

    assert approved is not None
    assert approval_matches(
        approved,
        approved["approval"],
        env=signing_env(),
    )

    different = {path: {"research_question": "A third version"}}
    with pytest.raises(ProtocolChangeApprovalRequired):
        require_change_approval(review_dir, existing, different, env=signing_env())
