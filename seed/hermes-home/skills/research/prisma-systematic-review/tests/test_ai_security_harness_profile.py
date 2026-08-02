"""Contract tests for the AI security-harness review profile."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "complete_review.py"


def load_complete_review(monkeypatch):
    """Load the standalone review script as a testable module."""

    monkeypatch.setenv("HERMES_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HERMES_INFERENCE_API_KEY", "test-only")
    monkeypatch.setenv("HERMES_MODEL_PRIMARY", "primary-test")
    monkeypatch.setenv("HERMES_MODEL_VISION", "vision-test")
    monkeypatch.setenv("HERMES_MODEL_REVIEW", "review-test")
    spec = importlib.util.spec_from_file_location(
        "complete_review_security_test",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evidence_page_location_finds_normalized_fragment(monkeypatch):
    complete = load_complete_review(monkeypatch)
    full_text = (
        "Cover page.\f"
        "AgentVisor reduces the attack success rate to 0.65 percent while "
        "preserving benign utility.\fReferences."
    )

    location = complete.evidence_page_location(
        full_text,
        "AgentVisor reduces the attack success rate to 0.65% while preserving benign utility.",
        "full text",
    )

    assert location == "p. 2 (full text; fragmento localizado)"


def test_evidence_page_location_preserves_verified_page_range(monkeypatch):
    complete = load_complete_review(monkeypatch)

    location = complete.evidence_page_location(
        "Source text",
        "Source fragment",
        "pp. 1, 8-9",
    )

    assert location == "pp. 1, 8-9"


def test_reconcile_bibliographic_identities_merges_arxiv_versions(tmp_path, monkeypatch):
    complete = load_complete_review(monkeypatch)
    review = tmp_path / "review"
    master_fields = [
        "record_id",
        "source",
        "year",
        "publication_date",
        "authors",
        "title_original",
        "title_en",
        "title_es",
        "abstract_original",
        "abstract_en",
        "abstract_es",
        "keywords_author",
        "keywords_indexed",
        "keywords_normalized",
        "raw_doi",
        "assigned_doi",
        "needs_doi_resolution",
        "status",
        "notes",
    ]
    title_fields = [
        "record_id",
        "assigned_doi",
        "authors",
        "title_original",
        "title_en",
        "title_es",
        "abstract_original",
        "abstract_en",
        "abstract_es",
        "keywords_author",
        "keywords_indexed",
        "keywords_normalized",
        "year",
        "source",
        "decision",
        "exclusion_score",
        "reason",
        "reason_detail",
        "reviewer",
        "reviewed_at",
        "notes",
    ]
    master_rows = [
        {
            "record_id": "RID-ARXIV",
            "source": "arxiv",
            "authors": "Zhibo Liang; Tianze Hu",
            "title_original": "Cognitive Control Architecture",
            "abstract_original": "Detailed abstract",
            "assigned_doi": "10.48550/arxiv.2512.06716v2",
        },
        {
            "record_id": "RID-OPENAIRE",
            "source": "openaire",
            "authors": "Zhibo",
            "title_original": "Cognitive Control Architecture",
            "abstract_original": "Detailed abstract",
            "assigned_doi": "10.48550/arxiv.2512.06716",
        },
    ]
    title_rows = [
        {
            "record_id": "RID-ARXIV",
            "source": "arxiv",
            "authors": "Zhibo Liang; Tianze Hu",
            "title_original": "Cognitive Control Architecture",
            "assigned_doi": "10.48550/arxiv.2512.06716v2",
            "decision": "exclude",
        },
        {
            "record_id": "RID-OPENAIRE",
            "source": "openaire",
            "authors": "Zhibo",
            "title_original": "Cognitive Control Architecture",
            "assigned_doi": "10.48550/arxiv.2512.06716",
            "decision": "include",
        },
    ]
    complete.write_csv(review / "records/master-records.csv", master_fields, master_rows)
    complete.write_csv(review / "screening/title-abstract.csv", title_fields, title_rows)
    complete.write_csv(
        review / "screening/title-abstract-dual-review.csv",
        [
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
        ],
        [
            {
                "stage": "title_abstract",
                "record_id": "RID-ARXIV",
                "assigned_doi": "10.48550/arxiv.2512.06716v2",
                "reviewer_a_decision": "exclude",
                "reviewer_b_decision": "exclude",
                "agreement": "yes",
                "final_decision": "exclude",
            },
            {
                "stage": "title_abstract",
                "record_id": "RID-OPENAIRE",
                "assigned_doi": "10.48550/arxiv.2512.06716",
                "reviewer_a_decision": "include",
                "reviewer_b_decision": "include",
                "agreement": "yes",
                "final_decision": "include",
            },
        ],
    )
    complete.write_csv(
        review / "extraction/extraction-table.csv",
        ["record_id", "assigned_doi", "authors", "title_original"],
        [
            {
                "record_id": "RID-OPENAIRE",
                "assigned_doi": "10.48550/arxiv.2512.06716",
                "authors": "",
                "title_original": "Cognitive Control Architecture",
            }
        ],
    )

    changed = complete.reconcile_bibliographic_identities(review)

    master = complete.read_csv(review / "records/master-records.csv")
    screened = complete.read_csv(review / "screening/title-abstract.csv")
    dual = complete.read_csv(review / "screening/title-abstract-dual-review.csv")
    extracted = complete.read_csv(review / "extraction/extraction-table.csv")
    assert changed == 1
    assert len(master) == 1
    assert master[0]["record_id"] == "RID-OPENAIRE"
    assert master[0]["authors"] == "Zhibo Liang; Tianze Hu"
    assert len(screened) == 1
    assert screened[0]["decision"] == "include"
    assert screened[0]["authors"] == "Zhibo Liang; Tianze Hu"
    assert len(dual) == 1
    assert dual[0]["record_id"] == "RID-OPENAIRE"
    reliability = json.loads(
        (review / "screening/screening-reliability.json").read_text(
            encoding="utf-8"
        )
    )
    assert reliability["stages"]["title_abstract"]["records"] == 1
    assert extracted[0]["authors"] == "Zhibo Liang; Tianze Hu"
    assert (review / "paper/audit/bibliographic-identity-corrections.csv").exists()


def review_context() -> dict[str, str]:
    return {
        "topic": "Harnesses de seguridad para modelos generativos y sistemas agénticos",
        "research_question": (
            "¿Qué controles reducen prompt injection, jailbreak, uso inseguro "
            "de herramientas y fuga de datos?"
        ),
        "inclusion": (
            "Controles operacionales para LLMs o agentes con amenaza, "
            "arquitectura o evaluación recuperable."
        ),
        "exclusion": (
            "Entrenamiento del modelo base y benchmarks de ataque sin defensa."
        ),
        "review_mode": "technical",
        "primary_review_mode": "technical",
    }


def candidate(record_id: str, title: str, abstract: str) -> dict[str, str]:
    return {
        "record_id": record_id,
        "assigned_doi": f"10.1234/{record_id}",
        "title_original": title,
        "abstract_original": abstract,
        "keywords_author": "",
        "keywords_indexed": "",
        "keywords_normalized": "",
        "source": "crossref",
        "year": "2025",
        "work_type": "",
    }


def test_security_profile_rejects_generic_architecture_and_attack_only_records(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    context = review_context()
    rows = [
        candidate(
            "evaluated",
            "Runtime Guardrails against Prompt Injection in LLM Agents",
            (
                "We evaluate a policy-enforcement guardrail against prompt "
                "injection using baselines, attack success rate, false-positive "
                "rate, utility, latency, and adaptive attacks."
            ),
        ),
        candidate(
            "generic",
            "Mixture-of-Experts Architecture for Efficient LLM Inference",
            "A benchmark of routing, serving latency, and model quality.",
        ),
        candidate(
            "attack-only",
            "A Benchmark of Universal Jailbreak Attacks against LLMs",
            (
                "We release adversarial prompts and report attack success rate. "
                "No defense, guardrail, filter, or mitigation is evaluated."
            ),
        ),
        candidate(
            "architecture",
            "A Security Harness for Tool-Using LLM Agents",
            (
                "The architecture defines a policy-enforcement pipeline, sandbox, "
                "verifier, and components for prompt-injection threats."
            ),
        ),
    ]

    decisions = complete.classify_title_abstract(rows, context, model_log=None)

    assert decisions["evaluated"]["decision"] == "include"
    assert decisions["generic"]["decision"] == "exclude"
    assert decisions["attack-only"]["decision"] == "exclude"
    assert decisions["architecture"]["decision"] == "maybe"


def test_security_full_text_requires_control_and_threat(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    context = review_context()
    evaluated_text = (
        "This large language model agent uses a runtime guardrail and policy "
        "enforcement layer against indirect prompt injection. We compare the "
        "defense with a baseline and report attack success rate, false positives, "
        "utility, latency, cost, and robustness under adaptive attacks. "
    ) * 50
    attack_only_text = (
        "This large language model jailbreak benchmark reports attack success "
        "rate for adversarial prompts but implements no defense or runtime control. "
    ) * 60

    included = complete.fallback_full_text_decision(
        {
            **candidate("full-include", "Evaluated LLM runtime guardrail", ""),
            "full_text_text": evaluated_text,
        },
        context,
    )
    excluded = complete.fallback_full_text_decision(
        {
            **candidate("full-exclude", "Jailbreak attack benchmark", ""),
            "full_text_text": attack_only_text,
        },
        context,
    )

    assert included["decision"] == "include"
    assert excluded["decision"] == "exclude"
    assert "control operacional" in complete.review_full_text_rules(context)[0]


def test_security_extraction_preserves_comparison_dimensions(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    source = {
        **candidate("extract", "Sentinel: Runtime Guardrails for LLM Agents", ""),
        "full_text_text": (
            "Sentinel is an LLM firewall with runtime policy enforcement at tool "
            "calls. We evaluate indirect prompt injection with adaptive attacks "
            "against a baseline. Attack success rate decreased to 8.4%, while "
            "the false-positive rate was 2.1%. Utility remained at 96% and latency "
            "overhead was 14 ms. The ablation and cross-model evaluation identify "
            "bypass attempts as the main failure mode. Code is available at "
            "https://github.com/example/sentinel."
        ),
    }
    item = complete.fallback_extraction_item(source, "test")

    complete.heuristically_enrich_extraction_item(source, item, review_context())

    assert "firewall" in item["control_architecture"]
    assert "llamada a herramientas" in item["enforcement_point"]
    assert "prompt injection indirecta" in item["threat_model"]
    assert item["attacker_adaptivity"] == "ataque adaptativo"
    assert "8.4%" in item["attack_success_rate"]
    assert "2.1%" in item["false_positive_rate"]
    assert "código o artefacto" in item["code_or_artifact_availability"]


def test_security_measurement_hygiene_rejects_pseudocode_and_keeps_real_metrics(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    item = {
        "attack_success_rate": "ASR decreased from 40% to 2% on AgentDojo.",
        "false_positive_rate": "0 false positives on 267 benign tool calls.",
        "utility_impact": "Task utility remained at 76%.",
        "latency_overhead": (
            "payee, setting, recipient) 2: U ← {retrieved untrusted items} "
            "3: if U = ∅ then return ALLOW"
        ),
        "cost_overhead": (
            "A program 𝑝 records its injection 𝑑(𝑝), trajectory 𝜏(𝑝), "
            "18 Table 10: Per-suite BU and inference cost on clean inputs"
        ),
    }

    complete.sanitize_security_extraction_item(item)

    assert item["attack_success_rate"] == "ASR decreased from 40% to 2% on AgentDojo."
    assert item["false_positive_rate"] == "0 false positives on 267 benign tool calls."
    assert item["utility_impact"] == "Task utility remained at 76%."
    assert item["latency_overhead"] == "no reportado"
    assert item["cost_overhead"] == "no reportado"


def test_security_measurement_hygiene_preserves_quantified_latency(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)

    value = complete.sanitize_security_measurement(
        "The runtime guard adds 14 ms latency per tool call.",
        "latency_overhead",
    )

    assert value == "The runtime guard adds 14 ms latency per tool call."


def test_security_measurement_hygiene_ignores_table_numbers_but_keeps_results(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)

    empty_reference = complete.sanitize_security_measurement(
        "Detailed false-positive results are presented in Table 8.",
        "false_positive_rate",
    )
    quantified_reference = complete.sanitize_security_measurement(
        "Table 25 shows token cost 2.82x above the no-defense baseline.",
        "cost_overhead",
    )

    assert empty_reference == "no reportado"
    assert quantified_reference == "Table 25 shows token cost 2.82x above the no-defense baseline."


def test_security_measurement_hygiene_rejects_headings_and_design_counts(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)

    values = [
        "7 False Positive and Negative Analysis.",
        "Detailed False Positive Results Table 8 presents the FP rates.",
        "The dataset contains 500 benign contexts for false positive evaluation.",
        "RQ4 analyzes the average token cost per sample.",
        "Section 3.1 requires hard negatives to suppress false positives.",
    ]

    assert [
        complete.sanitize_security_measurement(value, "cost_overhead" if "cost" in value else "false_positive_rate")
        for value in values
    ] == ["no reportado"] * len(values)


def test_security_rate_fields_require_an_observed_value(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)

    assert complete.sanitize_security_measurement(
        "The architecture reduces false positives and false negatives.",
        "false_positive_rate",
    ) == "no reportado"
    assert complete.sanitize_security_measurement(
        "Figure 3 converts attack success rate into a robustness score.",
        "attack_success_rate",
    ) == "no reportado"
    assert complete.sanitize_security_measurement(
        (
            "Analysis traverses the project directory to enumerate candidate tools, "
            "Tb0 = Estatic (C), where Tb0 may contain false positives."
        ),
        "false_positive_rate",
    ) == "no reportado"
    assert complete.sanitize_security_measurement(
        "The measured false-positive rate was 0.5% on benign calls.",
        "false_positive_rate",
    ) == "The measured false-positive rate was 0.5% on benign calls."


def test_security_measurement_hygiene_separates_attack_cost_from_harness_cost(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)

    attack_cost = complete.sanitize_security_measurement(
        "The adaptive attack requires 13x computational cost.",
        "cost_overhead",
    )
    harness_cost = complete.sanitize_security_measurement(
        "The runtime guard uses 2.82x more input tokens than the no-defense baseline.",
        "cost_overhead",
    )

    assert attack_cost == "no reportado"
    assert harness_cost == "The runtime guard uses 2.82x more input tokens than the no-defense baseline."


def test_source_verified_corrections_survive_cached_regeneration(tmp_path, monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    review = tmp_path / "review"
    complete.write_csv(
        review / "paper/audit/source-verified-corrections.csv",
        [
            "assigned_doi",
            "field",
            "previous_value",
            "corrected_value",
            "evidence_page",
            "verification_basis",
            "verification_status",
        ],
        [
            {
                "assigned_doi": "10.48550/arxiv.2605.26497",
                "field": "latency_overhead",
                "previous_value": "no reportado",
                "corrected_value": "4,61 s por tarea (1,87x).",
                "verification_status": "source_verified",
            },
            {
                "assigned_doi": "10.48550/arxiv.2605.26497",
                "field": "code_or_artifact_availability",
                "previous_value": "código disponible",
                "corrected_value": "no reportado",
                "verification_status": "source_verified",
            },
        ],
    )
    rows = [
        {
            "record_id": "RID-AUTHGRAPH",
            "assigned_doi": "10.48550/arxiv.2605.26497v1",
            "latency_overhead": "no reportado",
            "code_or_artifact_availability": "código disponible",
        }
    ]

    applied = complete.apply_source_verified_corrections(review, rows)

    assert applied == 2
    assert rows[0]["latency_overhead"] == "4,61 s por tarea (1,87x)."
    assert rows[0]["code_or_artifact_availability"] == "no reportado"


def test_model_provenance_role_is_forwarded(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    captured: dict[str, object] = {}

    def fake_cloud_call(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(complete, "cloud_post_openai_compatible_chat", fake_cloud_call)
    complete.post_openai_compatible_chat(
        base_url="https://example.invalid/v1",
        api_key="test-only",
        payload={"model": "review-test"},
        timeout_seconds=5,
        role="reviewer",
    )

    assert captured["role"] == "reviewer"
    assert captured["capability"] == "json"


def test_primary_role_does_not_fall_back_to_vision_or_review(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)

    assert complete.TEXT_REASONING_MODELS == ["primary-test"]
    assert complete.REVIEWER_MODELS == ["review-test"]


def test_llm_output_budget_is_task_specific(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    captured: dict[str, object] = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(complete, "post_openai_compatible_chat", fake_post)
    complete.call_llm(
        "Return an empty object.",
        {"type": "object"},
        [],
        preferred_models=["primary-test"],
        retries=1,
        max_output_tokens=900,
    )

    assert captured["payload"]["max_tokens"] == 900


def test_structured_output_controls_are_opt_in(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    captured: dict[str, object] = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setenv("HERMES_JSON_RESPONSE_FORMAT", "1")
    monkeypatch.setenv("HERMES_REASONING_EFFORT", "none")
    monkeypatch.setattr(complete, "post_openai_compatible_chat", fake_post)
    complete.call_llm(
        "Return an empty object.",
        {"type": "object"},
        [],
        preferred_models=["primary-test"],
        retries=1,
    )

    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["payload"]["reasoning_effort"] == "none"


def test_json_object_call_retries_truncated_output(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    outputs = iter(['{"decision":', '{"decision":"include"}'])
    budgets: list[int] = []

    def fake_call(*_args, **kwargs):
        budgets.append(kwargs["max_output_tokens"])
        return next(outputs)

    monkeypatch.setattr(complete, "call_llm", fake_call)
    result = complete.call_llm_json_object(
        "Classify.",
        {"type": "object"},
        [],
        max_output_tokens=800,
        retry_output_tokens=1400,
    )

    assert result == {"decision": "include"}
    assert budgets == [800, 1400]


def test_focal_ranking_is_stable_before_deep_extraction(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    context = review_context()
    rows = []
    for index in range(3):
        rows.append(
            {
                **candidate(
                    f"stable-{index}",
                    f"Evaluated runtime guardrail {index}",
                    "Security harness with prompt injection evaluation and a baseline.",
                ),
                "full_text_path": f"/workspace/fulltext/stable-{index}.pdf",
                "relevance_score": 90 - index,
                "methodological_quality_score": 80 - index,
                "work_type": "empirical",
                "empirical_type": "experimental",
            }
        )

    before = complete.shortlist_rows(
        rows,
        2,
        "preserve threat diversity",
        context,
        use_extraction_signals=False,
    )
    rows[2].update(
        {
            "extraction_confidence": 100,
            "models_or_systems_studied": "Model A; Model B",
            "benchmark_dataset_or_corpus": "SecurityBench",
            "baselines_or_comparators": "Baseline A",
            "method_used": "Adaptive attack evaluation",
            "tasks_or_domains": "Prompt injection",
        }
    )
    after = complete.shortlist_rows(
        rows,
        2,
        "preserve threat diversity",
        context,
        use_extraction_signals=False,
    )

    selected_before = {
        row["record_id"] for row in before if row["selected_for_final_n"] == "yes"
    }
    selected_after = {
        row["record_id"] for row in after if row["selected_for_final_n"] == "yes"
    }
    assert selected_before == selected_after == {"stable-0", "stable-1"}


def test_extraction_cache_cannot_erase_canonical_doi(monkeypatch) -> None:
    complete = load_complete_review(monkeypatch)
    rows = [
        {
            **candidate("identity", "Canonical title", "Canonical abstract"),
            "authors": "Researcher, A.",
            "year": "2025",
        }
    ]
    extraction = {
        "identity": {
            "record_id": "identity",
            "assigned_doi": "",
            "authors": "",
            "title_original": "",
            "abstract_original": "",
            "title_en": "Canonical title",
            "title_es": "Título canónico",
        }
    }

    complete.merge_extraction_into_rows(rows, extraction)

    assert rows[0]["assigned_doi"] == "10.1234/identity"
    assert rows[0]["authors"] == "Researcher, A."
    assert rows[0]["title_original"] == "Canonical title"
    assert rows[0]["abstract_original"] == "Canonical abstract"


def test_full_text_manifest_does_not_cache_unattempted_rows_as_failures(
    monkeypatch,
    tmp_path,
) -> None:
    complete = load_complete_review(monkeypatch)
    review = tmp_path / "review"
    rows = [
        {
            "record_id": "retrieved",
            "title_original": "Retrieved paper",
            "full_text_path": "/workspace/retrieved.pdf",
            "full_text_text": "material text",
        },
        {
            "record_id": "failed",
            "title_original": "Attempted paper",
            "full_text_path": "",
            "full_text_text": "",
        },
        {
            "record_id": "unattempted",
            "title_original": "Pending paper",
        },
    ]

    complete.write_full_text_manifest(review, rows, [])

    with (review / "fulltext/manifest.csv").open(encoding="utf-8", newline="") as handle:
        manifest = {row["record_id"]: row for row in csv.DictReader(handle)}
    assert manifest["retrieved"]["status"] == "retrieved"
    assert manifest["failed"]["status"] == "not_retrieved"
    assert manifest["unattempted"]["status"] == "pending"
