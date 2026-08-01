"""Tests for fast and auditable search-plan bootstrapping."""

from __future__ import annotations

import importlib.util
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
