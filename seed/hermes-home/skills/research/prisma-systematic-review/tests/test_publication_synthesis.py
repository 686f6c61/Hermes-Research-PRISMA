"""Regression tests for topic-independent manuscript synthesis."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "publication_audit.py"
SCRIPT_DIR = SCRIPT_PATH.parent
sys.path.insert(0, str(SCRIPT_DIR))

import model_capability_probe
import prepare_paper_figures
import publication_autopilot
import publication_peer_review
from bibliographic_corrections import apply_source_verified_identity_corrections


def load_publication_module():
    """Load the standalone publication generator without installing the bundle."""
    spec = importlib.util.spec_from_file_location("publication_audit_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generic_synthesis_uses_topic_without_topic_specific_state() -> None:
    publication = load_publication_module()

    lines = publication.domain_substantive_synthesis_lines(
        "generic",
        "adopción de tecnología en organizaciones",
        [{"title_original": "A comparative organizational study"}],
        ["10.1000/example"],
    )

    rendered = "\n".join(lines)
    assert "Síntesis sustantiva de resultados" in rendered
    assert "adopción de tecnología en organizaciones" in rendered


def test_management_workload_synthesis_uses_complete_work_accounting() -> None:
    publication = load_publication_module()
    workload_row = {
        "title_original": "Artificial intelligence and workload productivity",
        "key_findings": "AI reduces execution time but increases supervision effort.",
        "method_used": "Longitudinal field study",
    }

    lines = publication.domain_substantive_synthesis_lines(
        "management",
        "impacto de la IA en la carga de trabajo",
        [workload_row],
        ["10.1000/workload"],
    )

    rendered = "\n".join(lines)
    assert "desplazamiento del esfuerzo" in rendered
    assert "reducción neta y general del trabajo humano" in rendered


def test_security_harness_profile_produces_a_non_universal_comparison_model() -> None:
    publication = load_publication_module()
    context = {
        "topic": "Harnesses de seguridad para modelos generativos y sistemas agénticos",
        "research_question": "¿Qué harnesses son mejores frente a prompt injection y jailbreak?",
        "review_mode": "technical",
    }
    row = {
        "work_type": "empirical",
        "empirical_type": "experimental",
        "threat_model": "prompt injection indirecta",
        "control_architecture": "sandbox y verificador externo",
        "enforcement_point": "llamada a herramientas",
        "baselines_or_comparators": "agente sin guardrail",
        "attack_success_rate": "ASR 8,4%",
        "attacker_adaptivity": "ataque adaptativo",
        "utility_impact": "utilidad 96%",
        "robustness_evidence": "ataques no vistos",
        "failure_modes": "bypass por codificación",
        "code_or_artifact_availability": "código disponible",
    }

    profile = publication.detect_review_profile(context)
    contribution = publication.authorial_contribution_model(
        profile,
        context["topic"],
        1,
        1,
        {},
    )
    result_rows = publication.domain_aggregate_result_rows([row], profile)
    synthesis = "\n".join(
        publication.domain_substantive_synthesis_lines(
            profile,
            context["topic"],
            [row],
            [],
        )
    )

    assert profile == "ai_security_harness"
    assert "contrato operacional" in str(contribution["name"])
    assert "fronteras de dominancia" in str(contribution["field"])
    assert any("Coste de seguridad" in result[0] for result in result_rows)
    assert "Atacante adaptativo:" in synthesis
    assert "robustez amplia:" in synthesis
    assert "Utilidad:" in synthesis
    assert "latencia:" in synthesis
    assert "coste:" in synthesis


def test_same_surname_citations_use_first_author_initials_before_extra_surnames() -> None:
    publication = load_publication_module()

    lin = publication.build_disambiguated_citation(
        ["Lin", "Niu", "Ji", "Gao"],
        "2026",
        1,
        "Z.",
    )
    zhao = publication.build_disambiguated_citation(
        ["Zhao", "Bhaskar", "Dobriban"],
        "2026",
        1,
        "L.",
    )

    assert lin == "(Z. Lin et al., 2026)"
    assert zhao == "(L. Zhao et al., 2026)"


def test_disambiguation_prefers_first_author_initials_for_same_surname_and_year() -> None:
    publication = load_publication_module()
    corpus = {
        "lin-j": publication.CorpusRecord(
            "lin-j",
            "10.1000/lin-j",
            "Study J",
            "Jun Lin; Zoe Niu; Ana Doe",
            "2026",
            "empirical",
            True,
            "",
        ),
        "lin-z": publication.CorpusRecord(
            "lin-z",
            "10.1000/lin-z",
            "Study Z",
            "Zoe Lin; Jun Zhou; Ana Doe",
            "2026",
            "empirical",
            True,
            "",
        ),
    }
    citations = {record_id: "(Lin et al., 2026)" for record_id in corpus}

    _, disambiguated = publication.disambiguate_short_citations(
        corpus,
        {},
        {record_id: f"Lin ({record_id})" for record_id in corpus},
        citations,
        set(corpus),
    )

    assert disambiguated["lin-j"] == "(J. Lin et al., 2026)"
    assert disambiguated["lin-z"] == "(Z. Lin et al., 2026)"


def test_different_authors_with_same_surname_do_not_receive_year_suffixes() -> None:
    publication = load_publication_module()
    corpus = {
        "singh-b": publication.CorpusRecord(
            "singh-b",
            "10.1000/singh-b",
            "Boundary security",
            "Bhupinder Singh",
            "2026",
            "empirical",
            True,
            "",
        ),
        "singh-v": publication.CorpusRecord(
            "singh-v",
            "10.1000/singh-v",
            "Zero trust",
            "Vikram Singh",
            "2026",
            "empirical",
            True,
            "",
        ),
    }
    references = {
        "singh-b": "Singh, B. (2026). Boundary security.",
        "singh-v": "Singh, V. (2026). Zero trust.",
    }
    citations = {record_id: "(Singh, 2026)" for record_id in corpus}

    disambiguated_references, disambiguated_citations = publication.disambiguate_short_citations(
        corpus,
        {},
        references,
        citations,
        set(corpus),
    )

    assert "(2026a)" not in disambiguated_references["singh-b"]
    assert "(2026b)" not in disambiguated_references["singh-v"]
    assert disambiguated_citations["singh-b"] == "(B. Singh, 2026)"
    assert disambiguated_citations["singh-v"] == "(V. Singh, 2026)"


def test_peer_review_resolves_private_repo_env_without_shell_source(
    tmp_path,
    monkeypatch,
) -> None:
    review = tmp_path / "runtime" / "workspace" / "systematic-review-test"
    review.mkdir(parents=True)
    (tmp_path / ".env").write_text(
        "HERMES_INFERENCE_BASE_URL=https://example.invalid/v1\n"
        "HERMES_INFERENCE_API_KEY=private-test-key\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HERMES_INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_API_KEY", raising=False)

    assert publication_peer_review.resolve_primary_base_url(review) == "https://example.invalid/v1"
    assert (
        publication_peer_review.resolve_provider_api_key(review, "openai_compatible")
        == "private-test-key"
    )


def test_model_capability_registry_loads_bounded_private_repo_env(
    tmp_path,
    monkeypatch,
) -> None:
    review = tmp_path / "runtime" / "workspace" / "systematic-review-test"
    review.mkdir(parents=True)
    (tmp_path / ".env").write_text(
        "HERMES_INFERENCE_BASE_URL=https://example.invalid/v1\n"
        "HERMES_INFERENCE_API_KEY=private-test-key\n"
        "HERMES_MODEL_PRIMARY=primary-test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        model_capability_probe,
        "HERMES_HOME",
        tmp_path / "seed" / "hermes-home",
    )
    for name in (
        "HERMES_INFERENCE_API_KEY",
        "HERMES_MODEL_API_KEY",
        "PRIMARY_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "HERMES_INFERENCE_BASE_URL",
        "HERMES_MODEL_BASE_URL",
        "PRIMARY_OPENAI_BASE_URL",
        "OPENAI_BASE_URL",
        "HERMES_MODEL_PRIMARY",
    ):
        monkeypatch.delenv(name, raising=False)

    env_values = model_capability_probe.resolve_private_env_values(review)
    registry = model_capability_probe.build_registry(env_values, live=False, review_dir=review)

    assert registry["provider_host"] == "example.invalid"
    assert any(role["role"] == "primary" for role in registry["roles"])


def test_live_capability_probe_retries_a_transient_empty_response() -> None:
    calls = 0

    def transient_probe(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "capability": "text",
                "status": "fail",
                "effective_model": "vision-test",
                "detail": "",
            }
        return {
            "capability": "text",
            "status": "pass",
            "effective_model": "vision-test",
            "detail": "HERMES_OK",
        }

    result = model_capability_probe.run_live_probe_with_retries(
        transient_probe,
        {},
        capability="text",
        sleep_fn=lambda _seconds: None,
    )

    assert calls == 2
    assert result["status"] == "pass"
    assert result["attempts"] == 2


def test_live_capability_probe_stops_after_bounded_failures() -> None:
    calls = 0

    def failing_probe(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("temporary provider timeout")

    result = model_capability_probe.run_live_probe_with_retries(
        failing_probe,
        {},
        capability="json",
        attempts=3,
        sleep_fn=lambda _seconds: None,
    )

    assert calls == 3
    assert result["status"] == "fail"
    assert result["attempts"] == 3
    assert result["detail"] == "temporary provider timeout"


def test_source_verified_identity_correction_preserves_raw_doi(tmp_path) -> None:
    review = tmp_path / "systematic-review-test"
    (review / "paper/audit").mkdir(parents=True)
    (review / "records").mkdir()
    (review / "paper/audit/source-verified-identities.csv").write_text(
        "old_doi,new_doi,new_title,new_authors,verification_basis,verification_status\n"
        "10.1000/preprint,10.1000/final,Final title,Alice Author; Bob Author,"
        "publisher version of record,source_verified\n",
        encoding="utf-8",
    )
    (review / "records/master-records.csv").write_text(
        "record_id,raw_doi,assigned_doi,authors,title_original\n"
        "RID-1,10.1000/preprint,10.1000/preprint,Old Author,Preprint title\n",
        encoding="utf-8",
    )

    result = apply_source_verified_identity_corrections(review)
    rows = list(csv.DictReader((review / "records/master-records.csv").open()))

    assert result == {"files": 1, "rows": 1}
    assert rows[0]["raw_doi"] == "10.1000/preprint"
    assert rows[0]["assigned_doi"] == "10.1000/final"
    assert rows[0]["title_original"] == "Final title"
    assert rows[0]["authors"] == "Alice Author; Bob Author"


def test_second_peer_reviewer_has_a_bounded_complete_review_contract() -> None:
    prompt = publication_peer_review.build_prompt(
        {
            "reviewer_id": "reviewer_b",
            "role": "Revisor B",
            "focus": "Consistencia científica y trazabilidad.",
        },
        "# Manuscrito\nContenido.",
        "# Referencias\n- Example (2026).",
        "# Auditoría\nEstado: PASS.",
        "- Tema: harnesses de seguridad para LLMs",
    )

    assert "Máximo absoluto: 1200 palabras" in prompt
    assert "tres viñetas breves por sección" in prompt
    assert "termina siempre con `## Dictamen final`" in prompt
    assert publication_peer_review.review_attempts_for_model("mimo-v2.5") == 2


def test_peer_review_verdict_prefers_bold_explicit_header_over_acceptance_prose() -> None:
    review = "\n".join(
        [
            "**Veredicto: minor revision**",
            "",
            "## APA",
            "Sin problemas materiales.",
            "",
            "## Problemas mayores",
            "Ninguno.",
            "",
            "## Dictamen final",
            "Se recomienda la aceptación tras correcciones menores.",
        ]
    )

    assert publication_peer_review.extract_verdict(review) == "minor revision"


def test_peer_review_verdict_rejects_conflicting_explicit_headers() -> None:
    review = "Veredicto: accept\n\nVeredicto final: major revision"

    assert publication_peer_review.extract_verdict(review) == "unresolved"


def test_peer_review_honours_operator_reasoning_policy(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_REASONING_EFFORT", "none")
    payload: dict[str, object] = {"model": "mimo-v2.5"}

    result = publication_peer_review.apply_optional_reasoning_effort(payload)

    assert result["reasoning_effort"] == "none"


def test_peer_review_packet_preserves_priority_result_tables() -> None:
    manuscript = "\n".join(
        [
            "# Resultados",
            "",
            "Contexto extenso. " * 9000,
            "",
            "Tabla 8B. Matriz de toma de posición interpretativa.",
            "",
            "|Plano|Lectura|Base|",
            "|---|---|---|",
            "|Afirmación que sí sostiene|Dominancia condicionada|Contrato comparable|",
            "|Afirmación que no sostiene|Ranking universal|Heterogeneidad|",
            "",
            "# Discusión",
            "",
            "Discusión final.",
        ]
    )

    packet = publication_peer_review.build_review_packet(
        manuscript,
        mode="focused_apa",
    )

    assert "Extracto prioritario conservado para revisión" in packet
    assert "Dominancia condicionada" in packet
    assert "Ranking universal" in packet


def test_peer_review_packet_omits_long_study_appendix_instead_of_cutting_a_claim() -> None:
    manuscript = "\n".join(
        [
            "# Resultados",
            "",
            "Resultado principal completo.",
            "",
            "# Anexo A. Fichas analíticas del corpus final incluido",
            "",
            "## Estudio 1. MELON",
            "",
            "MELON supera a las defensas comparadas en el benchmark completo.",
            "",
            "# Anexo B. Datos y trazabilidad",
            "",
            "Anexos CSV disponibles.",
        ]
    )

    packet = publication_peer_review.build_review_packet(manuscript, mode="focused_apa")

    assert "Resultado principal completo." in packet
    assert "MELON supera" not in packet
    assert "apéndice analítico por estudio" in packet


def test_peer_review_reference_packet_exposes_every_reference_identity() -> None:
    references = "\n".join(
        [
            "# Referencias APA generadas",
            "",
            "- Alpha, A. (2024). First study. https://doi.org/10.1000/alpha",
            "- Louck, J. (2026). Middle study. https://doi.org/10.1000/louck",
            "- Rethlefsen, M. L., Kirtley, S., & Page, M. J. (2021). Last study. https://doi.org/10.1000/rethlefsen",
        ]
    )

    packet = publication_peer_review.summarize_references(references, sample_size=2)

    assert "Índice bibliográfico completo" in packet
    assert "Alpha, A. (2024). First study. https://doi.org/10.1000/alpha" in packet
    assert "Louck, J. (2026). Middle study. https://doi.org/10.1000/louck" in packet
    assert (
        "Rethlefsen, M. L., Kirtley, S., & Page, M. J. (2021). Last study. "
        "https://doi.org/10.1000/rethlefsen"
    ) in packet
    assert "no infieras ausencias" in packet


def test_review_mode_display_removes_duplicate_primary_label() -> None:
    publication = load_publication_module()

    rendered = publication.review_mode_display(
        {
            "review_mode_label": "Modo técnico",
            "review_mode_summary": "Modo técnico; principal: Modo técnico",
        }
    )

    assert rendered == "Modo técnico"


def test_security_harness_front_matter_uses_the_real_question_in_english() -> None:
    publication = load_publication_module()
    context = {
        "topic": "Harnesses de seguridad para modelos generativos y sistemas agénticos",
        "research_question": "¿Qué controles reducen prompt injection y jailbreak?",
        "review_mode": "technical",
    }

    question = publication.publication_research_question_en(
        context,
        "ai_security_harness",
    )

    assert "Which architectures, controls, and evaluation strategies" in question
    assert "unsafe tool use" in question
    assert "baselines" in question


def test_security_harness_introduction_and_theory_have_academic_depth() -> None:
    publication = load_publication_module()
    context = {
        "topic": "Harnesses de seguridad para modelos generativos y sistemas agénticos",
        "research_question": "¿Qué controles reducen prompt injection y jailbreak?",
        "review_mode": "technical",
    }
    rows = [
        {
            "record_id": "doi:10.1000/security",
            "assigned_doi": "10.1000/security",
            "title_original": "Runtime guardrails for agent security",
            "work_type": "empirical",
            "empirical_type": "experimental",
            "theory_framework": "information-flow control",
        }
    ]

    introduction = publication.build_introduction_section_domain(rows, context)
    theory = publication.build_theoretical_framework_section_domain(rows, context)

    assert len(introduction.split()) >= 500
    assert "contrato comparativo" in introduction
    assert "frontera condicionada" in introduction
    assert "Modelo conceptual de la defensa operacional" in theory
    assert "El primer eje del modelo conceptual es la autoridad" in theory
    assert "La unidad de comparación no es el modelo" in theory


def test_security_appraisal_uses_robustness_evidence() -> None:
    publication = load_publication_module()
    row = {
        "work_type": "empirical",
        "sample_size": "1,000 attack trials",
        "countries": "benchmark multi-modelo",
        "theory_framework": "information-flow control",
        "baselines_or_comparators": "no-defense baseline",
        "security_harness_name": "Sentinel",
        "threat_model": "prompt injection",
        "control_architecture": "runtime monitor",
        "robustness_evidence": "adaptive attacks and cross-model transfer",
        "extraction_confidence": "95",
    }

    appraisal = publication.appraisal_signals_for_row(row)

    assert appraisal["validation_reported"] == "1"
    assert "validación" not in appraisal["gaps"]


def test_method_reports_automatic_kappa_and_signed_human_resolution(tmp_path) -> None:
    publication = load_publication_module()
    review = tmp_path / "review"
    path = review / "screening/screening-reliability.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "stages": {
                    "title_abstract": {
                        "records": 100,
                        "agreements": 80,
                        "disagreements": 20,
                        "raw_agreement": 0.8,
                        "cohen_kappa": 0.5,
                    },
                    "full_text": {
                        "records": 25,
                        "agreements": 23,
                        "disagreements": 2,
                        "raw_agreement": 0.92,
                        "cohen_kappa": 0.84,
                        "researcher_resolved_disagreements": 2,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    rendered = "\n".join(publication.screening_reliability_method_lines(review))

    assert "kappa de Cohen 0,500" in rendered
    assert "kappa de Cohen 0,840" in rendered
    assert "2 discrepancias quedaron resueltas" in rendered
    assert "no constituyen ground truth" in rendered


def test_security_harness_figures_use_threat_control_semantics() -> None:
    context = {
        "topic": "Harnesses de seguridad para modelos generativos y sistemas agénticos",
        "research_question": "prompt injection jailbreak guardrails",
    }
    rows = [
        {
            "title_original": "Runtime Guardrails against Prompt Injection",
            "threat_model": "prompt injection indirecta",
            "attack_type": "prompt injection indirecta",
            "control_architecture": "guardrail de políticas; sandbox y permisos",
            "enforcement_point": "llamada a herramientas",
            "work_type": "empirical",
            "empirical_type": "experimental",
        }
    ]

    profile = prepare_paper_figures.detect_review_profile(context)
    svg = prepare_paper_figures.render_agent_task_matrix(
        rows,
        profile,
        "monochrome-academic",
    )

    assert profile == "ai_security_harness"
    assert "Matriz amenaza-control" in svg
    assert "ARQUITECTURA DE CONTROL Y AMENAZA" in svg


def test_security_harness_counts_only_genuinely_adaptive_attackers() -> None:
    publication = load_publication_module()
    rows = [
        {
            "attacker_adaptivity": "ataque adaptativo",
            "baselines_or_comparators": "baseline explícito",
            "code_or_artifact_availability": "código disponible",
        },
        {
            "attacker_adaptivity": "human red team adapts after feedback",
            "baselines_or_comparators": "no reportado (el artículo no compara)",
            "code_or_artifact_availability": "not available",
        },
        {"attacker_adaptivity": "no adaptativo (ataques predefinidos)"},
        {"attacker_adaptivity": "static benchmark attacks"},
        {"attacker_adaptivity": "no reportado"},
    ]

    counts = publication.security_harness_signal_counts(rows)

    assert counts["adaptive"] == 2
    assert counts["baseline"] == 1
    assert counts["artifact"] == 1


def test_security_frontier_table_names_the_best_supported_signal(tmp_path) -> None:
    publication = load_publication_module()
    review = tmp_path / "review"
    path = review / "analysis/security/dominance-frontier.csv"
    path.parent.mkdir(parents=True)
    fields = [
        "threat_family",
        "control_family",
        "studies",
        "with_explicit_baseline",
        "with_adaptive_attacker",
        "with_false_positive_rate",
        "with_utility_impact",
        "with_latency_or_cost",
        "frontier_status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "threat_family": "prompt_injection",
                    "control_family": "provenance_or_information_flow+tool_authorization",
                    "studies": "2",
                    "with_explicit_baseline": "2",
                    "with_adaptive_attacker": "1",
                    "with_false_positive_rate": "1",
                    "with_utility_impact": "2",
                    "with_latency_or_cost": "0",
                    "frontier_status": "replicated_frontier_candidate",
                },
                {
                    "threat_family": "prompt_injection",
                    "control_family": "other_or_unspecified",
                    "studies": "6",
                    "with_explicit_baseline": "6",
                    "with_adaptive_attacker": "4",
                    "with_false_positive_rate": "2",
                    "with_utility_impact": "1",
                    "with_latency_or_cost": "2",
                    "frontier_status": "insufficient_taxonomy",
                },
            ]
        )

    rendered = "\n".join(publication.security_frontier_result_lines(review))

    assert "Procedencia y flujo de información + Autorización de herramientas" in rendered
    assert "Candidata replicada" in rendered
    assert "dirección prioritaria" in rendered
    assert "falsa mayoría" in rendered
    assert "ganador universal" in rendered
    assert "disponer de baseline no corrige" in rendered
    assert "`Frontera emergente`" in rendered


def test_security_results_use_unique_table_numbers() -> None:
    publication = load_publication_module()
    context = {
        "topic": "Harnesses de seguridad para modelos generativos y sistemas agénticos",
        "research_question": "¿Qué controles reducen prompt injection y jailbreak?",
        "review_mode": "technical",
    }
    row = {
        "record_id": "doi:10.1000/security",
        "assigned_doi": "10.1000/security",
        "work_type": "empirical",
        "threat_model": "prompt injection",
        "control_architecture": "runtime monitor",
        "baselines_or_comparators": "no-defense baseline",
        "attack_success_rate": "ASR 1%",
        "utility_impact": "utility 95%",
        "robustness_evidence": "adaptive cross-model attacks",
        "failure_modes": "encoded bypass",
    }

    stance = "\n".join(
        publication.build_results_authorial_stance_lines([row], context)
    )
    synthesis = "\n".join(
        publication.domain_substantive_synthesis_lines(
            "ai_security_harness",
            context["topic"],
            [row],
            ["10.1000/security"],
        )
    )

    assert "Tabla 8B. Matriz de toma de posición interpretativa." in stance
    assert "Tabla 8C. Contrato comparativo" in synthesis
    assert "ranking universal" in stance


def test_security_discussion_figure_follows_method_and_result_figures(tmp_path) -> None:
    publication = load_publication_module()
    review = tmp_path / "review"
    gate = review / "figures/figure-gate.csv"
    gate.parent.mkdir(parents=True)
    gate.write_text(
        "figure_id,decision\n"
        "fig-review-architecture,supplementary\n"
        "fig-theme-landscape,main_body\n"
        "fig-agent-task-matrix,main_body\n"
        "fig-method-profile,main_body\n"
        "fig-evidence-maturity,main_body\n"
        "fig-analytical-grammar,main_body\n",
        encoding="utf-8",
    )

    assert publication.next_discussion_figure_number(review) == 6


def test_security_method_uses_an_operational_defense_contract(tmp_path) -> None:
    publication = load_publication_module()
    context = {
        "topic": "Harnesses de seguridad para modelos generativos y sistemas agénticos",
        "research_question": "¿Qué controles reducen prompt injection y jailbreak?",
        "review_mode": "technical",
    }
    row = {
        "work_type": "empirical",
        "threat_model": "prompt injection",
        "control_architecture": "tool authorization",
    }

    rendered = "\n".join(
        publication.build_method_depth_lines(
            tmp_path,
            [row],
            {
                "identified": 1,
                "screened_title_abstract": 1,
                "full_text_sought": 1,
                "full_text_assessed": 1,
                "included_in_review": 1,
                "full_text_not_retrieved": 0,
            },
            context,
        )
    )

    assert "contrato operacional de defensa" in rendered
    assert "atacante estático o adaptativo" in rendered
    assert "coste del atacante" in rendered


def test_security_harness_matrix_uses_normalized_taxonomy() -> None:
    rows = [
        {
            "threat_family": "prompt_injection+tool_poisoning_or_misuse",
            "control_family": "tool_authorization+sandboxing_or_isolation",
        },
        {
            "threat_family": "data_exfiltration",
            "control_family": "other_or_unspecified",
        },
    ]

    matrix = prepare_paper_figures.build_agent_task_matrix(rows, "ai_security_harness")

    assert matrix["Autorización de herramientas"]["Prompt injection"] == 1
    assert matrix["Autorización de herramientas"]["Herramientas y acciones"] == 1
    assert matrix["Sandbox y aislamiento"]["Prompt injection"] == 1
    assert matrix["Control no tipificado"]["Exfiltración y privacidad"] == 1


def test_render_figures_cache_tracks_generated_svg_content() -> None:
    assert "figures/svg/*.svg" in publication_autopilot.STEP_CONTRACTS["render_figures"]["inputs"]


def test_security_harness_portfolio_prioritizes_substantive_figures(tmp_path) -> None:
    review = tmp_path / "systematic-review-security"
    evidence_summary = review / "analysis" / "evidence" / "evidence-position-summary.json"
    evidence_summary.parent.mkdir(parents=True)
    evidence_summary.write_text("{}\n", encoding="utf-8")
    figure_ids = {
        "fig-review-architecture",
        "fig-corpus-map",
        "fig-theme-landscape",
        "fig-agent-task-matrix",
        "fig-method-profile",
        "fig-evidence-maturity",
        "fig-analytical-grammar",
        "fig-topic-network",
    }
    specs = [{"figure_id": figure_id} for figure_id in sorted(figure_ids)]

    ranked = prepare_paper_figures.rank_figure_portfolio(
        review,
        specs,
        "ai_security_harness",
        {"topic": "harnesses de seguridad para modelos generativos"},
    )
    recommendations = {row["figure_id"]: row["recommendation"] for row in ranked}
    body = {figure_id for figure_id, decision in recommendations.items() if decision == "main_body"}

    assert body == prepare_paper_figures.SECURITY_HARNESS_MAIN_BODY_FIGURES
    assert recommendations["fig-review-architecture"] == "supplementary"
    assert recommendations["fig-corpus-map"] == "supplementary"
    assert recommendations["fig-topic-network"] == "supplementary"


def test_publication_timeout_scales_with_focal_corpus(tmp_path, monkeypatch) -> None:
    review = tmp_path / "systematic-review-timeout"
    shortlist = review / "selection" / "ultraquality-shortlist.csv"
    shortlist.parent.mkdir(parents=True)
    shortlist.write_text(
        "selected_for_final_n\n" + "\n".join(["yes"] * 50) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_DOCLING_DOCUMENT_TIMEOUT", "600")

    timeout = publication_autopilot.resolved_step_timeout("publication_audit.py", review)

    assert timeout == 50 * 600 + 1800


def test_search_source_table_separates_results_errors_and_optional_skips(tmp_path) -> None:
    publication = load_publication_module()
    search_log = tmp_path / "searches" / "search-log.csv"
    search_log.parent.mkdir(parents=True)
    with search_log.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "notes"])
        writer.writeheader()
        writer.writerows(
            [
                {"source": "Crossref", "notes": "99 resultados recuperados"},
                {"source": "Crossref", "notes": "100 resultados recuperados"},
                {"source": "SemanticScholar", "notes": "error: HTTP Error 429"},
                {"source": "Scopus", "notes": "optional source skipped; open-source acquisition remains active"},
                {"source": "OpenAlex", "notes": "omitida: cuota diaria anónima agotada"},
            ]
        )

    rows = {row[0]: row[1:] for row in publication.search_source_execution_rows(tmp_path)}

    assert rows["Crossref"] == ["2", "199", "Ejecutada con resultados"]
    assert rows["SemanticScholar"][2] == "Interrumpida por error o límite de API"
    assert rows["Scopus"][1] == "—"
    assert rows["Scopus"][2] == "Fuente opcional no ejecutada"
    assert rows["OpenAlex"][2] == "Omitida por cuota; reanudable con credencial"


def test_search_coverage_limit_names_sources_without_claiming_zero_results() -> None:
    publication = load_publication_module()

    sentence = publication.search_coverage_limit_sentence(
        [
            ["Crossref", "3", "120", "Ejecutada con resultados"],
            ["OpenAlex", "3", "—", "Omitida por cuota; reanudable con credencial"],
            ["Scopus", "1", "—", "Fuente opcional no ejecutada"],
        ]
    )

    assert "OpenAlex y Scopus" in sentence
    assert "APIs abiertas" in sentence
    assert "cero resultados" not in sentence


def test_arxiv_reference_uses_repository_style_instead_of_redundant_label() -> None:
    publication = load_publication_module()
    record = publication.CorpusRecord(
        "record-1",
        "10.48550/arxiv.2601.01234",
        "A SECURITY PREPRINT",
        "Example, Alice",
        "2026",
        "empirical",
        True,
        "https://arxiv.org/abs/2601.01234",
    )

    reference, _citation = publication.build_apa_reference(record, None)

    assert "*A security preprint* [Preprint]. arXiv." in reference
    assert "arXiv preprint arXiv:" not in reference
    assert reference.endswith("https://arxiv.org/abs/2601.01234")


def test_biorxiv_reference_names_repository_and_preprint_status() -> None:
    publication = load_publication_module()
    record = publication.CorpusRecord(
        "record-1",
        "10.1101/2025.09.17.676717",
        "A biosecurity agent",
        "Meng, Meiyin; Zhang, Zaixi",
        "2025",
        "empirical",
        True,
        "",
    )
    metadata = {
        "DOI": record.assigned_doi,
        "type": "posted-content",
        "subtype": "preprint",
        "title": record.title,
        "publisher": "openRxiv",
        "institution": [{"name": "bioRxiv"}],
        "issued": {"date-parts": [[2025, 9, 20]]},
        "author": [
            {"family": "Meng", "given": "Meiyin"},
            {"family": "Zhang", "given": "Zaixi"},
        ],
    }

    reference, _citation = publication.build_apa_reference(record, metadata)

    assert "*A biosecurity agent* [Preprint]. bioRxiv." in reference
    assert reference.endswith("https://doi.org/10.1101/2025.09.17.676717")


def test_research_square_reference_does_not_repeat_generic_preprint_label() -> None:
    publication = load_publication_module()
    record = publication.CorpusRecord(
        "record-1",
        "10.21203/rs.3.rs-10302085/v1",
        "A multi-agent framework",
        "Atul",
        "2026",
        "empirical",
        True,
        "",
    )
    metadata = {
        "DOI": record.assigned_doi,
        "type": "posted-content",
        "subtype": "preprint",
        "title": record.title,
        "publisher": "Springer Science and Business Media LLC",
        "issued": {"date-parts": [[2026]]},
        "author": [{"family": "Atul"}],
    }

    reference, _citation = publication.build_apa_reference(record, metadata)

    assert reference.startswith("Atul. (2026).")
    assert "*A multi-agent framework* [Preprint]. Research Square." in reference
    assert "[Preprint]. Preprint." not in reference


def test_preprints_org_reference_names_repository_from_doi_prefix() -> None:
    publication = load_publication_module()
    record = publication.CorpusRecord(
        "record-1",
        "10.20944/preprints202602.1188.v1",
        "Memory poisoning propagation",
        "Liu, Hong",
        "2026",
        "empirical",
        True,
        "",
    )
    metadata = {
        "DOI": record.assigned_doi,
        "type": "posted-content",
        "subtype": "preprint",
        "title": record.title,
        "publisher": "MDPI AG",
        "issued": {"date-parts": [[2026]]},
        "author": [{"family": "Liu", "given": "Hong"}],
    }

    reference, _citation = publication.build_apa_reference(record, metadata)

    assert "*Memory poisoning propagation* [Preprint]. Preprints.org." in reference
    assert "[Preprint]. Preprint." not in reference


def test_csl_batch_preserves_results_and_failures_by_record(tmp_path, monkeypatch) -> None:
    publication = load_publication_module()

    def fake_fetch(doi: str, _cache_dir: Path) -> dict:
        if doi.endswith("broken"):
            raise TimeoutError("publisher timeout")
        return {"DOI": doi}

    monkeypatch.setattr(publication, "fetch_csl_json", fake_fetch)

    results, failures = publication.fetch_csl_batch(
        [
            ("record-a", "10.1000/a"),
            ("record-b", "10.1000/broken"),
            ("record-c", "10.1000/c"),
        ],
        tmp_path,
        max_workers=2,
    )

    assert results == {
        "record-a": {"DOI": "10.1000/a"},
        "record-c": {"DOI": "10.1000/c"},
    }
    assert isinstance(failures["record-b"], TimeoutError)
