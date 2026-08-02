"""Tests for fast and auditable search-plan bootstrapping."""

from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_topic_review.py"


def load_bootstrap_module():
    """Load the standalone bootstrap script as a testable module."""
    spec = importlib.util.spec_from_file_location("bootstrap_topic_review_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_decomposition_never_calls_cloud_planner(monkeypatch) -> None:
    bootstrap = load_bootstrap_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("The fast deterministic bootstrap called the cloud planner")

    monkeypatch.setattr(bootstrap, "call_search_planner_llm", fail_if_called)
    result = bootstrap.build_deterministic_search_decomposition(
        topic="AI agents in higher education",
        question="How do AI agents affect university teaching quality?",
        inclusion="Empirical studies with full text",
        exclusion="Opinion pieces",
    )

    assert result["planner"].startswith("deterministic-")
    assert result["search_stages"]
    assert result["question_axes"]["boundaries"] == [
        "Empirical studies with full text",
        "Opinion pieces",
    ]


def test_smoke_mode_bounds_queries_and_records(monkeypatch) -> None:
    monkeypatch.setenv("HERMES_RESEARCH_SMOKE_TEST", "1")
    bootstrap = load_bootstrap_module()

    assert bootstrap.PUBLIC_API_PAGE_SIZE == 10
    assert bootstrap.SOURCE_QUERY_LIMITS["openalex"] == 1
    assert bootstrap.SOURCE_QUERY_LIMITS["crossref"] == 1
    assert all(
        limit == 0
        for source, limit in bootstrap.SOURCE_QUERY_LIMITS.items()
        if source not in {"openalex", "crossref"}
    )


def test_arxiv_versions_merge_into_one_canonical_record() -> None:
    bootstrap = load_bootstrap_module()
    rows = [
        {
            "source": "openaire",
            "assigned_doi": "10.48550/arxiv.2512.06716",
            "title_original": "Cognitive Control Architecture",
            "authors": "Zhibo",
            "abstract_original": "Detailed abstract",
            "year": "2025",
        },
        {
            "source": "arxiv",
            "assigned_doi": "10.48550/arXiv.2512.06716v2",
            "title_original": "Cognitive Control Architecture",
            "authors": "Zhibo Liang; Tianze Hu",
            "abstract_original": "Detailed abstract",
            "year": "2025",
        },
    ]

    merged = bootstrap.merge_rows(rows)

    assert bootstrap.normalize_doi("10.48550/arXiv.2512.06716v2") == "10.48550/arxiv.2512.06716"
    assert len(merged) == 1
    assert merged[0]["authors"] == "Zhibo Liang; Tianze Hu"


def test_education_expansions_keep_question_anchors() -> None:
    bootstrap = load_bootstrap_module()
    topic = "Evaluación de agentes LLM con herramientas en educación superior"
    question = (
        "¿Qué evidencia empírica muestra que los agentes LLM con herramientas "
        "mejoran tareas docentes o de aprendizaje en educación superior?"
    )
    mode = bootstrap.infer_review_mode(
        topic=topic,
        question=question,
        inclusion="Estudios empíricos con texto completo y DOI verificable",
        exclusion="Opinión, marketing y educación no universitaria",
    )

    decomposition = bootstrap.build_deterministic_search_decomposition(
        topic=topic,
        question=question,
        inclusion="Estudios empíricos con texto completo y DOI verificable",
        exclusion="Opinión, marketing y educación no universitaria",
        mode_decision=mode,
    )

    mode_stages = [
        stage
        for stage in decomposition["search_stages"]
        if stage["stage_id"] in {"S3", "S4", "S5"}
    ]
    assert len(mode_stages) == 3
    for stage in mode_stages:
        for query in stage["queries_by_source"]["openalex"]:
            normalized = bootstrap.normalize_query_token(query)
            assert "llm" in normalized
            assert "educacion superior" in normalized
    assert all(
        bootstrap.normalize_query_token(query) != "educacion teacher"
        for stage in mode_stages
        for query in stage["queries_by_source"]["openalex"]
    )


def test_topic_pack_queries_survive_the_executable_query_budget() -> None:
    bootstrap = load_bootstrap_module()
    topic = "Evaluación de agentes LLM con herramientas en educación superior"
    question = (
        "¿Qué evidencia empírica muestra que los agentes LLM con herramientas "
        "mejoran tareas docentes o de aprendizaje en educación superior?"
    )
    inclusion = "Estudios empíricos con texto completo y DOI verificable"
    exclusion = "Opinión, marketing y educación no universitaria"
    mode = bootstrap.infer_review_mode(
        topic=topic,
        question=question,
        inclusion=inclusion,
        exclusion=exclusion,
    )
    decomposition = bootstrap.build_deterministic_search_decomposition(
        topic=topic,
        question=question,
        inclusion=inclusion,
        exclusion=exclusion,
        mode_decision=mode,
    )
    decomposition = bootstrap.apply_topic_packs(
        decomposition,
        topic=topic,
        question=question,
        inclusion=inclusion,
        mode_decision=mode,
    )

    plan = bootstrap.flatten_search_plan(decomposition)

    assert '"generative AI" "higher education" faculty workload' in plan["openalex"]
    assert any(stage.get("topic_pack") == "ai-higher-education" for stage in decomposition["search_stages"])
    assert len(plan["openalex"]) <= bootstrap.SOURCE_QUERY_LIMITS["openalex"]


def test_ai_security_harness_decomposition_preserves_threat_and_control_axes() -> None:
    bootstrap = load_bootstrap_module()
    topic = "Harnesses de seguridad para modelos generativos y sistemas agénticos"
    question = (
        "¿Qué harnesses reducen prompt injection, jailbreak, uso inseguro de "
        "herramientas y fuga de datos con menor coste y pérdida de utilidad?"
    )
    inclusion = (
        "Evaluaciones comparativas de controles de seguridad en runtime para "
        "LLM, modelos multimodales o agentes."
    )
    exclusion = "Alineamiento del modelo base sin defensa operacional."
    mode = bootstrap.infer_review_mode(
        topic=topic,
        question=question,
        inclusion=inclusion,
        exclusion=exclusion,
    )

    decomposition = bootstrap.build_deterministic_search_decomposition(
        topic=topic,
        question=question,
        inclusion=inclusion,
        exclusion=exclusion,
        mode_decision=mode,
    )
    plan = bootstrap.flatten_search_plan(decomposition)
    joined_queries = " ".join(plan["openalex"]).lower()

    assert decomposition["planner"] == "deterministic-ai-security-harness-profile"
    assert "prompt injection" in joined_queries
    assert "data exfiltration" in joined_queries
    assert "false positive" in joined_queries
    assert "mixture of experts" not in joined_queries
    assert "robustez adaptativa" in decomposition["question_axes"]["outcome_decision"]
    assert decomposition["question_axes"]["boundaries"] == [inclusion, exclusion]


def test_ai_security_cloud_planner_cannot_precede_specialist_queries(monkeypatch) -> None:
    bootstrap = load_bootstrap_module()
    monkeypatch.setattr(
        bootstrap,
        "call_search_planner_llm",
        lambda _prompt: {
            "planner": "llm-search-decomposition",
            "planner_model": "test-model",
            "question_axes": {"population_context": ["LLM"]},
            "search_stages": [
                {
                    "stage_id": "S1",
                    "name": "Generic architecture",
                    "purpose": "An intentionally broad model proposal.",
                    "axis_covered": ["architecture"],
                    "queries_by_source": {
                        "openalex": ['"mixture of experts" "large language model"'],
                    },
                }
            ],
        },
    )

    decomposition = bootstrap.build_search_decomposition(
        topic="Security harnesses for generative AI and agentic systems",
        question="Which runtime controls best defend LLM agents from prompt injection?",
        inclusion="Comparative evaluations of security controls for LLM agents.",
        exclusion="Base-model training without an operational defense.",
    )
    plan = bootstrap.flatten_search_plan(decomposition)

    assert decomposition["planner"].endswith("+llm-axis-validation")
    assert decomposition["planner_model"] == "test-model"
    assert plan["openalex"][0] == '"LLM security guardrails" evaluation'
    assert '"mixture of experts" "large language model"' not in plan["openalex"]


def test_scholarly_http_retries_rate_limits(monkeypatch) -> None:
    bootstrap = load_bootstrap_module()
    calls = []
    sleeps = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"results": []}'

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "0"},
                None,
            )
        return FakeResponse()

    monkeypatch.setenv("HERMES_HTTP_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("HERMES_HTTP_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("HERMES_HTTP_RETRY_MAX_SECONDS", "0")
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(bootstrap.time, "sleep", sleeps.append)
    bootstrap._LAST_HTTP_REQUEST_AT.clear()
    bootstrap._HTTP_CIRCUIT_ERRORS.clear()

    payload = bootstrap.fetch_json("https://api.openalex.org/works")

    assert payload == {"results": []}
    assert len(calls) == 2
    assert sleeps


def test_exhausted_provider_opens_circuit_for_following_queries(monkeypatch) -> None:
    bootstrap = load_bootstrap_module()
    calls = []

    def always_limited(request, timeout):
        calls.append((request.full_url, timeout))
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "0"},
            None,
        )

    monkeypatch.setenv("HERMES_HTTP_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", always_limited)
    bootstrap._LAST_HTTP_REQUEST_AT.clear()
    bootstrap._HTTP_CIRCUIT_ERRORS.clear()

    for _ in range(2):
        try:
            bootstrap.fetch_json("https://api.semanticscholar.org/graph/v1/paper/search")
        except (RuntimeError, urllib.error.HTTPError):
            pass

    assert len(calls) == 1
    assert "api.semanticscholar.org" in bootstrap._HTTP_CIRCUIT_ERRORS


def test_openalex_quota_failure_opens_source_circuit(monkeypatch) -> None:
    bootstrap = load_bootstrap_module()
    calls = []

    def quota_exhausted(url):
        calls.append(url)
        raise urllib.error.HTTPError(
            url,
            429,
            "Too Many Requests",
            {"Retry-After": "30"},
            None,
        )

    monkeypatch.delenv("HERMES_OPENALEX_API_KEY", raising=False)
    monkeypatch.setattr(bootstrap, "fetch_json", quota_exhausted)

    items, rows = bootstrap.fetch_openalex(
        "2023-01-01",
        "2026-12-31",
        ["first security query", "second security query"],
        "AI security harnesses",
    )

    assert items == []
    assert len(calls) == 1
    assert len(rows) == 2
    assert all("HERMES_OPENALEX_API_KEY" in row["notes"] for row in rows)


def test_openalex_free_key_is_sent_as_query_parameter(monkeypatch) -> None:
    bootstrap = load_bootstrap_module()
    calls = []

    def successful_fetch(url):
        calls.append(url)
        return {"results": []}

    monkeypatch.setenv("HERMES_OPENALEX_API_KEY", "configured-test-key")
    monkeypatch.setattr(bootstrap, "fetch_json", successful_fetch)

    bootstrap.fetch_openalex(
        "2023-01-01",
        "2026-12-31",
        ["security guardrail"],
        "AI security harnesses",
    )

    assert "api_key=configured-test-key" in calls[0]
