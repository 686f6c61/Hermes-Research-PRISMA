import csv
import json
import pathlib
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import build_research_memory
import build_scientific_intelligence
import build_security_harness_analysis
import paper_code_audit


def write_csv(path: pathlib.Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_review(tmp_path: pathlib.Path, name: str = "systematic-review-current") -> pathlib.Path:
    review = tmp_path / name
    extraction = [
        {
            "assigned_doi": "10.1000/positive",
            "title_original": "Positive study",
            "work_type": "Empirical",
            "design_detail": "Panel study",
            "method_used": "Regression with fixed effects",
            "sample_description": "Public firms",
            "variables_independent": "AI adoption",
            "variables_dependent": "Work quality",
            "benchmark_dataset_or_corpus": "Panel dataset",
            "baselines_or_comparators": "Non-adopters",
            "models_or_systems_studied": "AI assistant",
            "tasks_or_domains": "Knowledge work",
            "key_findings": "AI adoption was positively associated with work quality.",
            "evidence_snippet": "The estimates showed a positive association.",
            "evidence_location": "p. 8",
            "extraction_confidence": "92",
            "notes": "Code: https://github.com/example/research-code",
        },
        {
            "assigned_doi": "10.1000/negative",
            "title_original": "Negative study",
            "work_type": "Empirical",
            "design_detail": "Experiment",
            "method_used": "Randomized experiment",
            "sample_description": "University staff",
            "variables_independent": "AI adoption",
            "variables_dependent": "Work quality",
            "key_findings": "AI adoption was negatively associated with work quality.",
            "evidence_snippet": "Quality decreased in the treatment group.",
            "evidence_location": "p. 11",
            "extraction_confidence": "88",
            "notes": "",
        },
        {
            "assigned_doi": "10.1000/null",
            "title_original": "Null study",
            "work_type": "Empirical",
            "method_used": "Survey",
            "variables_independent": "AI use",
            "variables_dependent": "Hours worked",
            "key_findings": "There was no significant association with hours worked.",
            "evidence_snippet": "The coefficient was not significant.",
            "evidence_location": "p. 5",
            "extraction_confidence": "80",
            "notes": "",
        },
    ]
    write_csv(review / "extraction/extraction-table.csv", list(extraction[0]), extraction)
    shortlist = [
        {
            "assigned_doi": row["assigned_doi"],
            "selected_for_final_n": "yes",
            "relevance_score": str(90 - index),
            "methodological_quality_score": str(85 - index),
        }
        for index, row in enumerate(extraction)
    ]
    write_csv(review / "selection/ultraquality-shortlist.csv", list(shortlist[0]), shortlist)
    master = [
        {
            "assigned_doi": row["assigned_doi"],
            "title_original": row["title_original"],
        }
        for row in extraction
    ]
    write_csv(review / "records/master-records.csv", list(master[0]), master)
    (review / "protocol").mkdir(parents=True, exist_ok=True)
    (review / "protocol/intake.json").write_text(
        json.dumps({"topic": "AI adoption and work quality"}),
        encoding="utf-8",
    )
    (review / "protocol/review-mode.json").write_text(
        json.dumps({"mode": "management"}),
        encoding="utf-8",
    )
    write_csv(
        review / "searches/search-log.csv",
        ["query_string"],
        [{"query_string": "AI adoption work quality employees"}],
    )
    write_csv(
        review / "screening/full-text.csv",
        ["assigned_doi", "decision", "reason", "reason_detail"],
        [
            {
                "assigned_doi": row["assigned_doi"],
                "decision": "include_ft",
                "reason": "",
                "reason_detail": "",
            }
            for row in extraction
        ],
    )
    return review


def test_scientific_intelligence_separates_disagreement_from_eligibility(tmp_path):
    review = build_review(tmp_path)

    result = build_scientific_intelligence.build(review)

    assert result["bibliometric_used_in_score"] is False
    assert result["eligibility_effect"] == "none"
    summary = json.loads(
        (review / "analysis/evidence/evidence-position-summary.json").read_text(encoding="utf-8")
    )
    ai_quality = next(
        group
        for group in summary["comparison_groups"]
        if group["comparison_key"] == "artificial_intelligence_system -> quality_and_performance"
    )
    assert ai_quality["status"] == "directional_disagreement"
    quality_domain = next(
        domain
        for domain in summary["outcome_domains"]
        if domain["outcome_family"] == "quality_and_performance"
    )
    assert quality_domain["claim_status"] == "cross_study_signal"
    with (review / "analysis/reading-priority.csv").open(encoding="utf-8") as handle:
        priority = list(csv.DictReader(handle))
    assert priority
    assert all(row["bibliometric_used_in_score"] == "no" for row in priority)
    assert all(row["eligibility_effect"] == "none" for row in priority)
    positive = next(row for row in priority if row["doi"] == "10.1000/positive")
    negative = next(row for row in priority if row["doi"] == "10.1000/negative")
    assert positive["practical_valence"] == "favorable"
    assert negative["practical_valence"] == "adverse"


def test_scientific_intelligence_rejects_character_split_shortlist(tmp_path):
    review = build_review(tmp_path)
    shortlist = review / "selection/ultraquality-shortlist.csv"
    shortlist.write_text(
        "record_id,assigned_doi,title_original,selected_for_final_n,ultraquality_score\n"
        + "\n".join("RID-BROKEN")
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="malformed"):
        build_scientific_intelligence.build(review)


def test_cross_context_alignment_is_not_reported_as_direct_convergence():
    status = build_scientific_intelligence.group_status(
        {"positive_association"},
        2,
        {"healthcare", "industry_and_manufacturing"},
    )

    assert status == "cross_context_alignment"


def test_repeated_descriptive_positions_are_only_descriptive_alignment():
    status = build_scientific_intelligence.group_status(
        {"descriptive_or_theoretical"},
        3,
        {"industry_and_manufacturing"},
    )

    assert status == "descriptive_alignment"


def test_negative_direction_can_have_favorable_practical_valence():
    row = {
        "work_type": "Empirical",
        "key_findings": "The intervention significantly reduced latency.",
        "evidence_snippet": "Latency decreased relative to the baseline.",
    }
    position = build_scientific_intelligence.evidence_position(row)
    orientation = build_scientific_intelligence.outcome_orientation(row)

    assert position == "negative_association"
    assert orientation == "lower_is_better"
    assert build_scientific_intelligence.practical_valence(row, position, orientation) == "favorable"


def test_theoretical_proposal_cannot_be_labelled_as_demonstrated_benefit():
    row = {
        "work_type": "Theoretical framework",
        "key_findings": "The proposed framework could improve decision quality.",
        "evidence_snippet": "A conceptual model is proposed.",
    }
    position = build_scientific_intelligence.evidence_position(row)
    orientation = build_scientific_intelligence.outcome_orientation(row)

    assert position == "descriptive_or_theoretical"
    assert build_scientific_intelligence.practical_valence(row, position, orientation) == "not_applicable"


def test_paper_code_audit_is_optional_and_never_executes_code(tmp_path):
    review = build_review(tmp_path)

    manifest = paper_code_audit.run(review, inspect_remote=False)

    assert manifest["optional"] is True
    assert manifest["code_executed"] is False
    with (review / "analysis/reproducibility/paper-code-consistency.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    repository = next(row for row in rows if row["doi"] == "10.1000/positive")
    assert repository["repository_url"] == "https://github.com/example/research-code"
    assert repository["status"] == "declared_not_inspected"
    assert repository["code_executed"] == "no"


def test_cross_review_memory_is_private_and_advisory(tmp_path):
    previous = build_review(tmp_path, "systematic-review-previous")
    current = build_review(tmp_path, "systematic-review-current")
    write_csv(
        previous / "screening/full-text.csv",
        ["assigned_doi", "decision", "reason", "reason_detail"],
        [
            {
                "assigned_doi": "10.1000/positive",
                "decision": "exclude",
                "reason": "wrong_context",
                "reason_detail": "Prior protocol used a different population.",
            }
        ],
    )

    result = build_research_memory.build(current, tmp_path)

    assert result["related_reviews"] >= 1
    catalog = json.loads((tmp_path / ".hermes/research-memory.json").read_text(encoding="utf-8"))
    context = json.loads((current / "notes/prior-research-context.json").read_text(encoding="utf-8"))
    assert catalog["private"] is True
    assert context["decision_reuse"] == "forbidden"
    assert context["prior_decision_signals"][0]["reuse_policy"] == "advisory_only_reassess_under_current_protocol"
    assert str(tmp_path) not in json.dumps(context)


def test_security_harness_analysis_keeps_superiority_conditional(tmp_path):
    review = build_review(tmp_path, "systematic-review-security-harness")
    extraction_path = review / "extraction/extraction-table.csv"
    security_rows = [
        {
            "assigned_doi": "10.1000/secure",
            "title_original": "Adaptive prompt injection defense",
            "work_type": "Empirical",
            "design_detail": "Adversarial benchmark",
            "security_harness_name": "Layered guard",
            "control_architecture": "Runtime monitor and policy guardrail",
            "enforcement_point": "Input and tool call",
            "threat_model": "Indirect prompt injection",
            "attack_type": "Prompt injection",
            "attacker_adaptivity": "Adaptive attacker",
            "evaluation_setting": "Held-out adversarial benchmark",
            "baselines_or_comparators": "Input-only filter",
            "security_metrics": "Attack success rate",
            "attack_success_rate": "12%",
            "false_positive_rate": "3%",
            "utility_impact": "1.5 point task success reduction",
            "latency_overhead": "18 ms",
            "cost_overhead": "Not reported",
            "robustness_evidence": "Retested after attacker adaptation",
            "failure_modes": "Tool-description injection",
            "code_or_artifact_availability": "https://github.com/example/guard",
            "security_conclusion": "Outperformed the input-only baseline in this benchmark.",
            "key_findings": "The layered guard reduced attack success under adaptive attacks.",
            "evidence_snippet": "Attack success fell to 12 percent.",
            "evidence_location": "p. 9",
        },
        {
            "assigned_doi": "10.1000/weak",
            "title_original": "Prompt filter proposal",
            "work_type": "Theoretical",
            "security_harness_name": "Prompt filter",
            "control_architecture": "Input filtering",
            "threat_model": "Jailbreak",
            "attack_type": "Jailbreak",
            "security_metrics": "",
            "baselines_or_comparators": "",
            "key_findings": "A filter is proposed.",
        },
    ]
    write_csv(extraction_path, list(security_rows[0]), security_rows)
    write_csv(
        review / "selection/ultraquality-shortlist.csv",
        ["assigned_doi", "selected_for_final_n"],
        [
            {"assigned_doi": "10.1000/secure", "selected_for_final_n": "yes"},
            {"assigned_doi": "10.1000/weak", "selected_for_final_n": "yes"},
        ],
    )
    (review / "protocol/intake.json").write_text(
        json.dumps({"topic": "Harnesses de seguridad y prompt injection"}),
        encoding="utf-8",
    )

    result = build_security_harness_analysis.build(review)

    assert result["enabled"] is True
    with (review / "analysis/security/security-harness-comparison.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    secure = next(row for row in rows if row["doi"] == "10.1000/secure")
    weak = next(row for row in rows if row["doi"] == "10.1000/weak")
    assert secure["dominance_status"] == "conditional_dominance_candidate"
    assert weak["dominance_status"] == "not_established"
    assert "universal" not in secure["dominance_reason"].casefold()
    summary = json.loads(
        (review / "analysis/security/security-harness-summary.json").read_text(encoding="utf-8")
    )
    assert "No universal winner" in summary["scientific_boundary"]


def test_security_missing_value_with_explanation_is_still_missing() -> None:
    row = {
        "threat_model": "Prompt injection",
        "control_architecture": "Input filter",
        "baselines_or_comparators": "No reportado (no se comparan defensas existentes)",
        "security_metrics": "Attack success rate",
        "utility_impact": "No aplica: el estudio no mide utilidad",
        "robustness_evidence": "Not reported (adaptive attacks were not tested)",
    }

    readiness, dominance, reason, security_effect, tradeoff = (
        build_security_harness_analysis.comparison_readiness(row)
    )

    assert readiness == "insufficient_comparability"
    assert dominance == "not_established"
    assert "baseline" in reason
    assert security_effect == "missing"
    assert tradeoff == "missing"


def test_security_taxonomy_recognizes_bilingual_operational_controls() -> None:
    threat = build_security_harness_analysis.classify(
        "Envenenamiento de memoria y exfiltración de datos mediante una herramienta maliciosa",
        build_security_harness_analysis.THREAT_RULES,
        "other_or_unspecified",
    )
    control = build_security_harness_analysis.classify(
        "Monitor en tiempo de ejecución con procedencia y contratos de capacidad antes de la llamada",
        build_security_harness_analysis.CONTROL_RULES,
        "other_or_unspecified",
    )

    assert "memory_or_retrieval_poisoning" in threat
    assert "tool_poisoning_or_misuse" in threat
    assert "provenance_or_information_flow" in control
    assert "tool_authorization" in control


def test_security_table_headings_do_not_count_as_quantified_results() -> None:
    row = {
        "threat_model": "Indirect prompt injection",
        "control_architecture": "Runtime monitor",
        "baselines_or_comparators": "AgentDojo baseline",
        "security_metrics": "Attack Success Rate; False Positive Rate",
        "attack_success_rate": "Table 7. Attack Success Rate analysis.",
        "false_positive_rate": "Section 4.1. Detailed False Positive Results.",
        "utility_impact": "Utility under attack is discussed in Table 1.",
        "latency_overhead": "Challenge 3: latency-bounded environments.",
        "robustness_evidence": "Adaptive attacks were evaluated.",
    }

    readiness, dominance, _, security_effect, tradeoff = (
        build_security_harness_analysis.comparison_readiness(row)
    )

    assert readiness == "insufficient_comparability"
    assert dominance == "not_established"
    assert security_effect == "mention_only"
    assert tradeoff == "mention_only"


def test_security_zero_false_positives_is_quantified_evidence() -> None:
    assert (
        build_security_harness_analysis.evidence_level(
            "0 falsos positivos en 267 llamadas benignas."
        )
        == "quantified"
    )


def test_security_residual_taxonomy_cannot_become_a_frontier() -> None:
    members = [
        {
            "doi": f"10.1000/residual-{index}",
            "threat_family": "prompt_injection",
            "control_family": "other_or_unspecified",
            "comparison_readiness": "frontier_ready",
            "baselines_or_comparators": "Baseline",
            "attacker_adaptivity": "Adaptive attacker",
            "security_metrics": "ASR",
            "attack_success_rate": "8%",
            "false_positive_rate": "2%",
            "utility_impact": "1 point",
            "latency_overhead": "12 ms",
            "cost_overhead": "",
            "robustness_evidence": "Held-out attacks",
            "failure_modes": "Bypass",
            "code_or_artifact_availability": "https://github.com/example/test",
        }
        for index in range(2)
    ]

    frontier = build_security_harness_analysis.frontier_rows(members)

    assert frontier[0]["frontier_status"] == "insufficient_taxonomy"
    assert "cannot support" in frontier[0]["interpretation"]


def test_security_arxiv_doi_versions_share_one_identity() -> None:
    assert (
        build_security_harness_analysis.clean_doi(
            "https://doi.org/10.48550/arXiv.2512.06716v2"
        )
        == "10.48550/arxiv.2512.06716"
    )


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("Attack success rate fell from 42% to 9%.", "attack_success_and_compromise"),
        ("La tasa de éxito del ataque cayó del 42% al 9%.", "attack_success_and_compromise"),
        ("False positive rate was 1.8%.", "false_positive_burden"),
        ("La tasa de detección alcanzó el 96%.", "defense_and_detection"),
        ("Data leakage remained below 2%.", "data_leakage_and_privacy"),
    ],
)
def test_security_outcome_synonyms_share_one_family(wording: str, expected: str) -> None:
    family = build_scientific_intelligence.semantic_families(
        wording,
        build_scientific_intelligence.OUTCOME_FAMILIES,
        "outcome",
    )

    assert family.split("+")[0] == expected
