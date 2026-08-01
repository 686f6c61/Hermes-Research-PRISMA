#!/usr/bin/env python3
"""Materialize versioned methodological, editorial, and delivery contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone

from artifact_contracts import CONTRACT_VERSION, read_json, write_json_atomic
from protocol_change_control import (
    ProtocolChangeApprovalRequired,
    archive_applied_change,
    require_change_approval,
)
from review_mode_router import mode_config

CONTRACTS_VERSION = "hermes.review-contracts/v2"


def clean_label(value: str) -> str:
    """Normalize a Markdown intake label while preserving its meaning."""
    return re.sub(r"\s+", " ", value.strip()).lower()


def parse_intake(path: pathlib.Path) -> dict[str, str]:
    """Convert the human-readable intake into a stable key-value contract."""
    aliases = {
        "tema": "topic",
        "pregunta de investigación (opcional)": "research_question",
        "pregunta de investigacion (opcional)": "research_question",
        "año o años": "years",
        "ano o anos": "years",
        "fecha inicial (opcional)": "from_date",
        "fecha final (opcional)": "to_date",
        "criterios de inclusión": "inclusion_criteria",
        "criterios de inclusion": "inclusion_criteria",
        "criterios de exclusión": "exclusion_criteria",
        "criterios de exclusion": "exclusion_criteria",
        "modo autónomo": "autonomous_mode",
        "modo autonomo": "autonomous_mode",
        "modo metodológico (opcional)": "declared_review_mode",
        "modo metodologico (opcional)": "declared_review_mode",
        "límite final n ultraquality": "final_n",
        "limite final n ultraquality": "final_n",
        "límite final n": "final_n",
        "limite final n": "final_n",
        "criterio de representatividad ultraquality": "representativeness",
        "autoría del manuscrito (opcional)": "authors",
        "autoria del manuscrito (opcional)": "authors",
        "correo de contacto (opcional)": "contact_email",
        "fecha del manuscrito (opcional)": "manuscript_date",
        "longitud objetivo del manuscrito (opcional)": "target_length",
        "modo de validación (opcional)": "validation_mode",
        "modo de validacion (opcional)": "validation_mode",
    }
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"^-\s+([^:]+):\s*(.*)$", line)
        if not match:
            continue
        label = clean_label(match.group(1))
        value = match.group(2).strip()
        key = aliases.get(label)
        if key:
            values[key] = value
        elif label.startswith("revista o medio objetivo"):
            values["target_outlet"] = value
    return values


def parse_n_range(raw: str) -> dict[str, int | None]:
    """Represent exact and ranged N targets without turning them into quotas."""
    numbers = [int(value) for value in re.findall(r"\d+", raw or "")]
    if not numbers:
        return {"minimum": None, "maximum": None, "exact": None}
    if len(numbers) == 1:
        return {"minimum": numbers[0], "maximum": numbers[0], "exact": numbers[0]}
    low, high = sorted(numbers[:2])
    return {"minimum": low, "maximum": high, "exact": None}


def build_intake_contract(review_dir: pathlib.Path) -> dict[str, object]:
    """Build the single intake representation shared by every interface."""
    values = parse_intake(review_dir / "protocol" / "intake.md")
    return {
        "schema_version": "hermes.intake/v1",
        "topic": values.get("topic", ""),
        "research_question": values.get("research_question", ""),
        "time_window": {
            "label": values.get("years", ""),
            "from": values.get("from_date", ""),
            "to": values.get("to_date", ""),
        },
        "eligibility": {
            "inclusion": values.get("inclusion_criteria", ""),
            "exclusion": values.get("exclusion_criteria", ""),
            "doi_policy": "doi-only",
            "full_text_required": True,
        },
        "target_n": {
            **parse_n_range(values.get("final_n", "")),
            "policy": "desired range, never an inclusion quota",
        },
        "representativeness": values.get("representativeness", ""),
        "declared_review_mode": values.get("declared_review_mode", ""),
        "target_outlet": values.get("target_outlet", "") or "generic-common-core",
        "target_length": values.get("target_length", ""),
        "manuscript": {
            "authors": values.get("authors", ""),
            "contact_email": values.get("contact_email", ""),
            "date": values.get("manuscript_date", ""),
        },
        "autonomous_mode": values.get("autonomous_mode", "sí"),
        "validation_mode": values.get("validation_mode", "autonomous"),
    }


def build_method_contract(review_dir: pathlib.Path, intake: dict[str, object]) -> dict[str, object]:
    """Freeze the discipline-aware unit of comparison and appraisal rules."""
    mode_decision = read_json(review_dir / "protocol" / "review-mode.json", {}) or {}
    mode_name = str(mode_decision.get("mode") or "social_sciences")
    primary_name = str(mode_decision.get("primary_mode") or mode_name)
    config = mode_config(primary_name)
    return {
        "schema_version": "hermes.method-contract/v1",
        "review_mode": mode_name,
        "review_mode_label": mode_decision.get("mode_label") or config.get("label_public_es"),
        "primary_mode": primary_name,
        "secondary_modes": mode_decision.get("secondary_modes") or [],
        "confidence": mode_decision.get("confidence") or "not-recorded",
        "rationale": mode_decision.get("rationale") or "",
        "question_framework": mode_decision.get("question_framework") or config.get("default_framework"),
        "unit_of_comparison": mode_decision.get("primary_unit") or config.get("primary_unit"),
        "screening_axes": mode_decision.get("screening_axes") or config.get("screening_axes") or [],
        "critical_appraisal": {
            "tools": mode_decision.get("critical_appraisal_tools") or config.get("appraisal_tools") or [],
            "domains": mode_decision.get("critical_appraisal_domains")
            or config.get("critical_appraisal_domains")
            or [],
        },
        "selection_score_weights": mode_decision.get("selection_score_weights")
        or config.get("selection_score_weights")
        or {},
        "synthesis_options": mode_decision.get("synthesis_modes") or config.get("synthesis_modes") or [],
        "writing_rules": mode_decision.get("writing_rules") or config.get("writing_rules") or [],
        "research_question": intake.get("research_question") or "",
    }


def build_synthesis_plan(method: dict[str, object]) -> dict[str, object]:
    """Declare how evidence determines the synthesis method."""
    return {
        "schema_version": "hermes.synthesis-plan/v1",
        "unit_of_comparison": method.get("unit_of_comparison"),
        "candidate_modes": method.get("synthesis_options") or [],
        "decision_rules": [
            {
                "method": "meta-analysis",
                "use_when": [
                    "compatible outcomes and effect measures",
                    "comparable populations, interventions/exposures, and designs",
                    "variance or convertible uncertainty is available",
                ],
                "otherwise": "do not pool; document heterogeneity and use a structured alternative",
            },
            {
                "method": "SWiM or structured narrative synthesis",
                "use_when": [
                    "quantitative evidence is relevant but statistical pooling is not defensible",
                    "direction, magnitude, and design can still be compared transparently",
                ],
            },
            {
                "method": "thematic/framework synthesis",
                "use_when": [
                    "constructs, mechanisms, contexts, or qualitative findings are the comparison unit",
                    "coding decisions and negative cases are retained",
                ],
            },
            {
                "method": "configurational synthesis",
                "use_when": [
                    "outcomes depend on combinations of architecture, context, mechanism, or implementation",
                    "single-variable aggregation would erase the causal or functional configuration",
                ],
            },
        ],
        "required_layers": [
            "descriptive corpus map",
            "critical appraisal",
            "focal comparative synthesis",
            "contradictions and negative findings",
            "sensitivity analysis",
            "certainty, emerging signal, and unresolved gap",
        ],
        "prohibited_shortcuts": [
            "select synthesis solely because it is easy to automate",
            "treat frequency as effect or causal importance",
            "pool incompatible measures",
            "force the requested N by weakening eligibility",
        ],
    }


def build_journal_profile(intake: dict[str, object]) -> dict[str, object]:
    """Create a generic common core or an explicit outlet adaptation contract."""
    outlet = str(intake.get("target_outlet") or "generic-common-core").strip()
    mode = "generic-common-core" if outlet.lower() == "generic-common-core" else "specific-outlet"
    return {
        "schema_version": "hermes.journal-profile/v1",
        "mode": mode,
        "target_outlet": outlet,
        "format_policy": (
            "Use the broadest journal-ready common core; adapt style only after a target is named."
            if mode == "generic-common-core"
            else "Preserve the scientific core and apply only verified target-outlet constraints."
        ),
        "required_submission_elements": [
            "complete title and author block",
            "abstract and keywords",
            "method and reporting checklist appropriate to the review",
            "data and code availability",
            "funding, conflicts, ethics, and generative-AI disclosure",
            "editable tables and figures",
            "cover letter and supplementary files",
        ],
        "citation_policy": "Do not impose APA unless the target outlet requires it.",
    }


def build_delivery_contract() -> dict[str, object]:
    """Describe the twelve product-facing packages expected at delivery."""
    categories = [
        ("methodology", "Protocol, question decomposition, eligibility, amendments, and synthesis plan."),
        ("bibliography", "DOI-only corpus, searches, deduplication, missing DOI, and references."),
        ("screening", "Independent decisions, normalized reasons, uncertainty, and full-text adjudication."),
        ("full_text", "Source documents, structured extraction, hashes, and extraction quality."),
        ("evidence", "Study sheets, variables, findings, page anchors, snippets, and claim ledger."),
        ("analysis", "Descriptive synthesis, appraisal, sensitivity, contradictions, and network atlas."),
        ("visuals", "Publication figures, editable sources, evidence manifests, and rationale."),
        ("publication", "Canonical Markdown, editable LaTeX, compiled PDF, bibliography, and annexes."),
        ("editorial", "Journal readiness, cover letter, declarations, checklists, and review roadmap."),
        ("audit", "Model provenance, capability tests, gates, hashes, and reproducibility state."),
        ("update", "Pipeline cache, job ledger, runtime state, and change-aware rerun evidence."),
        ("interactive", "This delivery guide and the structural atlas with Gephi exports."),
    ]
    return {
        "schema_version": "hermes.deliverables-contract/v1",
        "categories": [{"id": key, "description": description} for key, description in categories],
        "closure_rule": (
            "PASS requires the manuscript, evidence, traceability, editorial checks, and portable guide; "
            "a PDF alone never closes a review."
        ),
    }


def build_contracts(review_dir: pathlib.Path) -> list[pathlib.Path]:
    """Write every contract and initialize the amendments ledger."""
    protocol_dir = review_dir / "protocol"
    now = datetime.now(timezone.utc).astimezone().isoformat()
    intake = build_intake_contract(review_dir)
    method = build_method_contract(review_dir, intake)
    payloads = {
        protocol_dir / "intake.json": intake,
        protocol_dir / "method-contract.json": method,
        protocol_dir / "synthesis-plan.json": build_synthesis_plan(method),
        protocol_dir / "journal-profile.json": build_journal_profile(intake),
        protocol_dir / "deliverables-contract.json": build_delivery_contract(),
    }
    existing = {
        path: read_json(path, {}) or {}
        for path in payloads
        if path.is_file()
    }
    approved_change = require_change_approval(
        review_dir,
        existing,
        payloads,
    )
    if existing and approved_change is None and all(existing.get(path) == payload for path, payload in payloads.items()):
        manifest_path = protocol_dir / "contracts-manifest.json"
        contracts = [
            {
                "path": str(path.relative_to(review_dir)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in payloads
        ]
        current_manifest = read_json(manifest_path, {}) or {}
        if (
            current_manifest.get("schema_version") == CONTRACTS_VERSION
            and current_manifest.get("artifact_contract_version") == CONTRACT_VERSION
            and current_manifest.get("contracts") == contracts
        ):
            return [*payloads.keys(), manifest_path]
        meta = {
            "schema_version": CONTRACTS_VERSION,
            "artifact_contract_version": CONTRACT_VERSION,
            "generated_at": now,
            "contracts": contracts,
        }
        write_json_atomic(manifest_path, meta)
        return [*payloads.keys(), manifest_path]
    written = [write_json_atomic(path, payload) for path, payload in payloads.items()]
    amendments_path = protocol_dir / "amendments.jsonl"
    if not amendments_path.exists():
        amendments_path.write_text(
            json.dumps(
                {
                    "schema_version": "hermes.protocol-amendment/v1",
                    "timestamp": now,
                    "type": "protocol_initialized",
                    "reason": "Initial methodological contract materialized before publication.",
                    "affected_artifacts": [path.name for path in payloads],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    meta = {
        "schema_version": CONTRACTS_VERSION,
        "artifact_contract_version": CONTRACT_VERSION,
        "generated_at": now,
        "contracts": [
            {
                "path": str(path.relative_to(review_dir)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in written
        ],
    }
    written.append(write_json_atomic(protocol_dir / "contracts-manifest.json", meta))
    if approved_change is not None:
        archive_path = archive_applied_change(review_dir, approved_change)
        with amendments_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "schema_version": "hermes.protocol-amendment/v2",
                        "timestamp": now,
                        "type": "protocol_change_applied",
                        "proposal_id": approved_change["proposal_id"],
                        "reason": approved_change["approval"].get("reason", ""),
                        "researcher": approved_change["approval"].get("researcher", {}),
                        "archive": str(archive_path.relative_to(review_dir)),
                        "affected_artifacts": [
                            item["contract"]
                            for item in approved_change["contracts"]
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory not found: {review_dir}")
    try:
        paths = build_contracts(review_dir)
    except ProtocolChangeApprovalRequired as exc:
        print(
            json.dumps(
                {
                    "status": "needs_approval",
                    "message": str(exc),
                    "pending": str(review_dir / "protocol" / "pending-amendment.json"),
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps({"status": "pass", "contracts": [str(path) for path in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
