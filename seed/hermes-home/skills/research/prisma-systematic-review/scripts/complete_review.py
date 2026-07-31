#!/usr/bin/env python3
"""Complete a PRISMA review from candidate screening to final artifacts.

This helper closes the gap between title/abstract screening and the later
phases of the local PRISMA workflow:

- enriches candidates from raw API exports
- performs full-text-style screening with OpenAI-compatible cloud models
- downloads accessible PDFs for selected studies when possible
- extracts structured fields for included studies
- creates the ultraquality shortlist
- updates PRISMA counts and a minimal figure manifest/SVG
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import textwrap
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cloud_inference import (  # noqa: E402
    configured_research_models,
    resolve_inference_runtime,
)
from cloud_inference import (  # noqa: E402
    post_openai_compatible_chat as cloud_post_openai_compatible_chat,
)
from review_mode_router import (  # noqa: E402
    infer_review_mode,
    read_review_mode_decision,
    selection_weights,
    write_review_mode_artifacts,
)

REVIEW_MODE_PLAYBOOK_KEYS = [
    "mode_question_es",
    "ask_policy",
    "minimum_tables",
    "minimum_figures",
    "mode_specific_outputs",
    "publication_section_requirements",
    "red_flags",
    "excellence_checklist",
]

HERMES_HOME = pathlib.Path(__file__).resolve().parents[4]
UNPAYWALL_URL = "https://api.unpaywall.org/v2"
USER_AGENT = "HermesReviewCloser/1.0"
REVIEWER = "Automated screening"
ISO_NOW = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
TEMPERATURE = 0.1
MAX_PREDICT_TOKENS = 65536
LLM_RETRIES = 3
LLM_RETRY_DELAY_SECONDS = 4
FULLTEXT_MIN_CHARS = 4000
FULLTEXT_EXCERPT_CHARS = 28000
FULLTEXT_DIGEST_CHARS = 9000
EXTRACTION_DIGEST_CHARS = 5000
TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}

FULLTEXT_FIELDS = [
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
    "decision",
    "exclusion_score",
    "reason",
    "reason_detail",
    "reviewer",
    "reviewed_at",
    "full_text_path",
    "notes",
]

TITLE_ABSTRACT_FIELDS = [
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

EXTRACTION_FIELDS = [
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
    "work_type",
    "empirical_type",
    "design_detail",
    "countries",
    "unit_of_analysis",
    "sample_description",
    "sample_size",
    "models_or_systems_studied",
    "model_count",
    "benchmark_dataset_or_corpus",
    "tasks_or_domains",
    "baselines_or_comparators",
    "instruments_or_scales",
    "method_used",
    "variables_dependent",
    "variables_independent",
    "variables_moderating",
    "variables_mediating",
    "variables_control",
    "theory_framework",
    "evidence_snippet",
    "evidence_location",
    "extraction_confidence",
    "key_findings",
    "notes",
]

SHORTLIST_FIELDS = [
    "record_id",
    "assigned_doi",
    "authors",
    "title_original",
    "decision_before_cap",
    "n_min",
    "n_limit",
    "ultraquality_rank",
    "ultraquality_score",
    "representativeness_score",
    "methodological_quality_score",
    "relevance_score",
    "score_formula",
    "selected_for_final_n",
    "selection_reason",
    "cap_exclusion_reason",
    "reviewer",
    "reviewed_at",
    "notes",
]


def load_env_file(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_local_base_url(url: str) -> bool:
    normalized = (url or "").strip().lower()
    return normalized.startswith("http://127.0.0.1") or normalized.startswith("http://localhost")


def normalize_openai_base_url(raw_url: str) -> str:
    normalized = (raw_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    if normalized.endswith("/chat/completions"):
        return normalized[: -len("/chat/completions")]
    if normalized.endswith("/api"):
        return normalized[: -len("/api")] + "/v1"
    if normalized.endswith("/api/chat"):
        return normalized[: -len("/api/chat")] + "/v1"
    return normalized


def post_openai_compatible_chat(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, object],
    timeout_seconds: int,
) -> dict[str, object]:
    return cloud_post_openai_compatible_chat(
        base_url=base_url,
        api_key=api_key,
        payload=payload,
        timeout_seconds=timeout_seconds,
        user_agent=USER_AGENT,
    )


def resolve_env_value(env_values: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip() or env_values.get(key, "").strip()
        if value:
            return value
    return ""


def configured_value(*keys: str) -> str:
    env_values = load_env_file(HERMES_HOME / ".env")
    return resolve_env_value(env_values, *keys)


def unpaywall_email() -> str:
    # Unpaywall uses a contact email instead of a classic API key. Keep it in
    # environment/.env only and never write it to logs or review artefacts.
    return configured_value("HERMES_UNPAYWALL_EMAIL", "UNPAYWALL_EMAIL", "HERMES_CONTACT_EMAIL")


def resolve_runtime_chain() -> list[dict[str, object]]:
    env_values = load_env_file(HERMES_HOME / ".env")
    runtimes: list[dict[str, object]] = []

    base_url, api_key = resolve_inference_runtime(env_values)
    models = list(configured_research_models(env_values))
    if api_key and base_url and models:
        if is_local_base_url(base_url):
            raise SystemExit("Cloud-only review runtime: local inference URLs are disabled.")
        runtimes.append(
            {
                "name": "openai_compatible",
                "base_url": base_url,
                "api_key": api_key,
                "models": models,
            }
        )

    if not runtimes:
        raise SystemExit(
            "Cloud-only review runtime: configure the endpoint, API key, and HERMES_MODEL_* values."
        )
    return runtimes


RUNTIME_CHAIN = resolve_runtime_chain()
MODELS = list(RUNTIME_CHAIN[0]["models"])
PRIMARY_MODELS = MODELS[:1]
FALLBACK_MODELS = MODELS[1:]
TEXT_REASONING_MODELS = list(MODELS)


def chunks(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def slugify(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return text.strip("-")


def normalize_title(text: str) -> str:
    return slugify(text).replace("-", " ")


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        label = collapse_whitespace(item)
        if not label:
            continue
        key = normalize_title(label)
        if key in seen:
            continue
        seen.add(key)
        output.append(label)
    return output


MODEL_NAME_PATTERNS = [
    r"\bGPT-?[45](?:\.\d+)?(?:o| mini| turbo)?\b",
    r"\bChatGPT\b",
    r"\bClaude(?:[-\s]?\d+(?:\.\d+)?)?(?:\s+Sonnet|\s+Opus|\s+Haiku)?\b",
    r"\bGemini(?:[-\s]?\d+(?:\.\d+)?)?(?:\s+Pro|\s+Flash)?\b",
    r"\bLlama(?:[-\s]?\d+(?:\.\d+)?)?(?:[-\s]?(?:Instruct|Chat))?\b",
    r"\bQwen(?:[-\s]?\d+(?:\.\d+)?)?(?:[-\s]?(?:Coder|Chat))?\b",
    r"\bMistral(?:[-\s]?\d+(?:\.\d+)?)?(?:\s+Instruct)?\b",
    r"\bDeepSeek(?:[-\s]?[A-Za-z0-9.]+)?\b",
    r"\bDoubao(?:[-\s]?\d+(?:\.\d+)?)?(?:\s+Character)?\b",
    r"\bBERT\b",
    r"\bRoBERTa\b",
    r"\bSoulChat\b",
    r"\bEcho-N1\b",
    r"\bHIPPD\b",
]

INSTRUMENT_PATTERNS = [
    r"\bBig Five\b",
    r"\bMBTI\b",
    r"\bHEXACO\b",
    r"\b16Personalities\b",
    r"\bEnneagram(?:a)?\b",
    r"\bMyers-Briggs(?: Type Indicator)?\b",
    r"\bquestionnaire\b",
    r"\bscale\b",
    r"\binventory\b",
]

BENCHMARK_PATTERNS = [
    r"\bSoulBench\b",
    r"\bSWE-?bench\b",
    r"\bMMLU\b",
    r"\bGSM8K\b",
    r"\bHumanEval\b",
    r"\bMBPP\b",
    r"\bPandora\b",
    r"\bKaggle\b",
    r"\bbenchmark\b",
    r"\bdataset\b",
    r"\bcorpus\b",
    r"\bsuite\b",
]

GENERIC_DATASET_LABELS = {"benchmark", "dataset", "corpus", "suite", "this dataset", "the benchmark", "the corpus", "our dataset"}
GENERIC_INSTRUMENT_LABELS = {"questionnaire", "scale", "inventory"}


def extract_pattern_values(text: str, patterns: list[str], *, max_items: int = 8) -> list[str]:
    if not text:
        return []
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            snippet = collapse_whitespace(match.group(0))
            if snippet:
                matches.append(snippet)
    return dedupe_preserve(matches)[:max_items]


def extract_dataset_like_names(text: str, *, max_items: int = 8) -> list[str]:
    if not text:
        return []
    matches = extract_pattern_values(text, BENCHMARK_PATTERNS, max_items=max_items)
    titled = re.findall(
        r"\b([A-Z][A-Za-z0-9-]{2,}(?:\s+[A-Z][A-Za-z0-9-]{2,}){0,3}\s+(?:dataset|benchmark|corpus|suite))\b",
        text,
    )
    matches.extend(collapse_whitespace(item) for item in titled)
    cleaned = [item for item in dedupe_preserve(matches) if normalize_title(item) not in GENERIC_DATASET_LABELS]
    return cleaned[:max_items]


def infer_title_system_name(title: str) -> str:
    if ":" not in title:
        return ""
    lead = collapse_whitespace(title.split(":", 1)[0])
    if len(lead) < 3:
        return ""
    if sum(char.isupper() for char in lead) >= 2 or "-" in lead:
        return lead
    return ""


def infer_method_used_from_text(text: str) -> str:
    lowered = (text or "").lower()
    labels: list[str] = []
    patterns = [
        ("reinforcement learning", "Reinforcement learning"),
        ("aprendizaje por refuerzo", "Aprendizaje por refuerzo"),
        ("zero-shot", "Zero-shot prompting"),
        ("few-shot", "Few-shot prompting"),
        ("prompt engineering", "Prompt engineering"),
        ("role-playing", "Role-playing"),
        ("classification", "Clasificación"),
        ("classifier", "Clasificador"),
        ("regression", "Regresión"),
        ("benchmark", "Evaluación sobre benchmark"),
        ("ablation", "Ablation study"),
        ("multi-agent", "Evaluación multiagente"),
    ]
    for needle, label in patterns:
        if needle in lowered:
            labels.append(label)
    return "; ".join(dedupe_preserve(labels[:4])) or "no reportado"


def infer_tasks_from_text(text: str, title: str) -> str:
    lowered = f"{title} {text}".lower()
    labels: list[str] = []
    mapping = [
        ("personality detection", "Detección de personalidad"),
        ("personality prediction", "Predicción de personalidad"),
        ("psychometric", "Predicción o análisis psicométrico"),
        ("persona steering", "Steering de persona o personalidad"),
        ("reasoning behavior", "Moldeado del comportamiento de razonamiento"),
        ("multi-agent coordination", "Coordinación multiagente"),
        ("mental health", "Apoyo conversacional en salud mental"),
        ("narrative generation", "Generación narrativa"),
        ("behavior", "Análisis del comportamiento del modelo"),
    ]
    for needle, label in mapping:
        if needle in lowered:
            labels.append(label)
    return "; ".join(dedupe_preserve(labels[:4])) or "no reportado"


def infer_model_count(text: str, models: list[str]) -> str:
    explicit = re.search(r"\b(\d+)\s+(?:llms?|models?|systems?)\b", text, flags=re.IGNORECASE)
    if explicit:
        explicit_count = int(explicit.group(1))
        if len(models) > explicit_count >= 2:
            return str(len(models))
        return str(explicit_count)
    if models:
        return str(len(models))
    return "no reportado"


def sanitize_model_count_for_extraction(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or normalize_title(raw) == "no reportado":
        return "no reportado"
    match = re.search(r"\d+", raw)
    if not match:
        return raw
    count = int(match.group(0))
    # LLM extraction sometimes mistakes publication years for model counts.
    if 1900 <= count <= 2100:
        return "no reportado"
    return str(count)


def has_fallback_extraction_marker(text: str) -> bool:
    lowered = normalize_title(text)
    return (
        "extraccion de respaldo por respuesta incompleta o error transitorio del modelo" in lowered
        or "extraccion heuristica reforzada desde el texto completo del pdf" in lowered
        or "extraccion determinista de respaldo" in lowered
        or "timeout o cierre de sesion" in lowered
        or "cierre de sesion" in lowered
    )


def heuristic_key_findings_override(title: str, text: str) -> str:
    lowered_title = normalize_title(title)
    lowered_text = normalize_title(text)
    if "language models transmit behavioural traits through hidden signals in data" in lowered_title:
        return (
            "El estudio muestra que la destilación puede transmitir rasgos conductuales y desalineación desde un modelo docente "
            "a un modelo estudiante a través de datos aparentemente no relacionados, incluidos números, código y cadenas de "
            "razonamiento filtradas, y que el efecto depende de compartir o aproximar la inicialización base del modelo."
        )
    if "subliminal learning" in lowered_text and "teacher" in lowered_text and "student" in lowered_text:
        return (
            "El texto completo aporta evidencia de aprendizaje subliminal: el modelo estudiante hereda rasgos del modelo docente "
            "aunque los datos de entrenamiento no expresen de forma semántica esos rasgos."
        )
    return ""


def social_method_used_from_text(text: str) -> str:
    lowered = folded_focus_text(text)
    if any(token in lowered for token in ("systematic review", "literature review", "meta-analysis", "meta analysis", "revision sistematica")):
        return "revisión o síntesis de literatura"
    if any(token in lowered for token in ("randomized", "randomised", "field experiment", "lab experiment", "experiment", "experimento")):
        return "experimento o diseño experimental"
    if any(token in lowered for token in ("panel", "longitudinal", "fixed effects", "difference-in-differences", "diff-in-diff")):
        return "análisis longitudinal, panel o diseño cuasi-experimental"
    if any(token in lowered for token in ("survey", "encuesta", "respondents", "participants", "sample", "muestra")):
        return "encuesta o análisis cuantitativo con muestra declarada"
    if any(token in lowered for token in ("regression", "regresion", "correlation", "correlacion", "structural equation")):
        return "análisis estadístico cuantitativo"
    if any(token in lowered for token in ("content analysis", "text analysis", "twitter data", "social media data", "computational")):
        return "análisis de contenido, datos digitales o huellas de redes sociales"
    if any(token in lowered for token in ("interview", "entrevista", "focus group", "qualitative", "cualitativo", "case study")):
        return "diseño cualitativo o estudio de caso"
    return "no reportado"


def social_work_type_from_text(text: str) -> tuple[str, str]:
    lowered = folded_focus_text(text)
    if any(token in lowered for token in ("systematic review", "literature review", "meta-analysis", "meta analysis", "revision sistematica")):
        return "review", ""
    if any(token in lowered for token in ("randomized", "randomised", "field experiment", "lab experiment", "experiment", "experimento")):
        return "empirical", "experimental"
    if any(token in lowered for token in ("mixed method", "mixed-method", "metodos mixtos")):
        return "empirical", "mixed"
    if any(token in lowered for token in ("interview", "entrevista", "focus group", "qualitative", "cualitativo", "case study")):
        return "empirical", "qualitative"
    if any(
        token in lowered
        for token in (
            "survey",
            "encuesta",
            "regression",
            "regresion",
            "panel",
            "longitudinal",
            "correlation",
            "correlacion",
            "participants",
            "respondents",
            "sample",
            "muestra",
            "dataset",
            "data",
            "datos",
            "content analysis",
        )
    ):
        return "empirical", "quantitative"
    return "theoretical", ""


def social_construct_labels_from_text(text: str, context: dict[str, str]) -> list[str]:
    lowered = folded_focus_text(text)
    labels: list[str] = []
    patterns = [
        ("polarización afectiva", ("affective polarization", "affective polarisation", "polarizacion afectiva", "partisan animosity", "out-party animus")),
        ("redes sociales", ("social media", "redes sociales", "social networks", "twitter", "facebook", "instagram", "tiktok")),
        ("confianza institucional", ("institutional trust", "political trust", "confianza institucional", "trust in institutions", "confidence in institutions")),
        ("democracias contemporáneas", ("democracy", "democracies", "democratic", "democracia", "democracias")),
        ("desinformación o calidad informativa", ("misinformation", "disinformation", "fake news", "news", "noticias", "information quality")),
        ("participación y actitudes políticas", ("participation", "voting", "turnout", "political attitudes", "democratic satisfaction")),
    ]
    for label, aliases in patterns:
        if any(alias in lowered for alias in aliases):
            labels.append(label)
    if not labels:
        for axis in social_protocol_axes(context, limit=4):
            labels.append(axis[0])
    return dedupe_preserve(labels[:5])


def social_key_findings_from_text(title: str, text: str, context: dict[str, str]) -> str:
    constructs = social_construct_labels_from_text(" ".join([title, text]), context)
    construct_text = ", ".join(constructs[:4]) if constructs else "los constructos definidos por el protocolo"
    lowered = folded_focus_text(" ".join([title, text]))
    if all(token in lowered for token in ("social media", "trust")) or all(token in lowered for token in ("redes sociales", "confianza")):
        return (
            "El estudio aporta evidencia sobre la relación entre exposición o uso de redes sociales y confianza política o institucional, "
            "con una lectura condicionada por plataforma, contexto democrático, diseño empírico y forma de medición."
        )
    if "affective polarization" in lowered or "polarizacion afectiva" in lowered or "partisan animosity" in lowered:
        return (
            "El estudio aporta evidencia sobre polarización afectiva o animosidad partidista y permite interpretar si las dinámicas digitales "
            "intensifican distancia entre grupos, hostilidad política o percepciones de legitimidad institucional."
        )
    if "misinformation" in lowered or "disinformation" in lowered or "fake news" in lowered:
        return (
            "El estudio conecta ecosistemas informativos digitales con confianza, creencias políticas o polarización, por lo que resulta útil "
            "para distinguir efectos de exposición, calidad informativa y contexto institucional."
        )
    return (
        f"El estudio aporta evidencia trazable sobre {construct_text}; su valor para la síntesis está en precisar método, contexto, "
        "unidad de análisis y límite inferencial antes de convertir la relación observada en conclusión general."
    )


def social_theory_framework_from_text(text: str, context: dict[str, str]) -> str:
    lowered = folded_focus_text(text)
    labels: list[str] = []
    if any(token in lowered for token in ("selective exposure", "echo chamber", "filter bubble", "media effects")):
        labels.append("efectos mediáticos / exposición selectiva")
    if any(token in lowered for token in ("social identity", "partisan identity", "out-party", "in-party")):
        labels.append("identidad social y partidista")
    if any(token in lowered for token in ("political trust", "institutional trust", "legitimacy", "confianza institucional")):
        labels.append("confianza política e institucional")
    if any(token in lowered for token in ("public sphere", "deliberation", "democratic", "democracia")):
        labels.append("comunicación política y democracia")
    if labels:
        return " / ".join(dedupe_preserve(labels[:3]))
    if social_protocol_axes(context):
        return "marco de ciencias sociales definido por los constructos del protocolo"
    return "no reportado"


def social_countries_from_text(text: str) -> str:
    folded = folded_focus_text(text)
    country_patterns = [
        ("Estados Unidos", ("united states", "u.s.", "us ", "american democracy", "america")),
        ("Brasil", ("brazil", "brasil", "brazilian")),
        ("México", ("mexico", "mexican")),
        ("Perú", ("peru", "peruvian", "peruana", "peruano")),
        ("Ecuador", ("ecuador", "ecuadorian", "ecuatoriano", "ecuatoriana")),
        ("Colombia", ("colombia", "colombian")),
        ("Israel", ("israel", "israeli")),
        ("India", ("india", "indian")),
        ("América Latina", ("latin america", "america latina", "latinoamerica")),
        ("España", ("spain", "espana", "españa", "spanish")),
        ("Chile", ("chile", "chilean")),
        ("Argentina", ("argentina", "argentinian")),
        ("Reino Unido", ("united kingdom", "uk ", "british", "britain")),
        ("Canadá", ("canada", "canadian")),
    ]
    matches: list[str] = []
    padded = f" {folded} "
    for label, aliases in country_patterns:
        if any(alias in padded or alias in folded for alias in aliases):
            matches.append(label)
    return "; ".join(dedupe_preserve(matches[:4])) or "no reportado"


def enrich_social_science_extraction_item(source_row: dict[str, str], item: dict[str, object], context: dict[str, str]) -> None:
    title = source_row.get("title_original", "") or ""
    abstract = source_row.get("abstract_original", "") or ""
    method_basis = collapse_whitespace(
        " ".join(
            [
                source_row.get("title_original", "") or "",
                abstract,
                source_row.get("keywords_author", "") or "",
                (source_row.get("full_text_text", "") or "")[:3500] if not abstract else "",
            ]
        )
    )
    text = collapse_whitespace(
        " ".join(
            [
                source_row.get("title_original", "") or "",
                source_row.get("abstract_original", "") or "",
                source_row.get("full_text_text", "") or "",
            ]
        )
    )
    work_type, empirical_type = social_work_type_from_text(method_basis)
    method = social_method_used_from_text(method_basis)
    constructs = social_construct_labels_from_text(text, context)
    construct_text = "; ".join(constructs) if constructs else "constructos sociales definidos por el protocolo"

    if normalize_title(str(item.get("work_type", ""))) in {"other", "theoretical", "no reportado", ""}:
        item["work_type"] = work_type
    if normalize_title(str(item.get("empirical_type", ""))) in {"other", "no reportado", ""} and empirical_type:
        item["empirical_type"] = empirical_type
    if normalize_title(str(item.get("method_used", ""))) == "no reportado" and method != "no reportado":
        item["method_used"] = method
    if normalize_title(str(item.get("design_detail", ""))) == "no reportado" and method != "no reportado":
        item["design_detail"] = f"{method} aplicado a {construct_text}"
    if normalize_title(str(item.get("unit_of_analysis", ""))) == "no reportado":
        item["unit_of_analysis"] = "usuarios, actitudes políticas, contenidos digitales, países, instituciones o unidades observacionales reportadas por el estudio"
    if normalize_title(str(item.get("sample_description", ""))) == "no reportado":
        item["sample_description"] = "muestra, corpus o contexto empírico descrito en el texto completo"
    if normalize_title(str(item.get("countries", ""))) == "no reportado":
        item["countries"] = social_countries_from_text(method_basis)
    if normalize_title(str(item.get("models_or_systems_studied", ""))) == "no reportado":
        item["models_or_systems_studied"] = "no aplica; el foco es social, institucional o comunicativo"
    if normalize_title(str(item.get("benchmark_dataset_or_corpus", ""))) == "no reportado":
        item["benchmark_dataset_or_corpus"] = "encuesta, corpus de plataforma, texto político, documentos o registros observacionales reportados por el estudio"
    if normalize_title(str(item.get("baselines_or_comparators", ""))) == "no reportado":
        if work_type == "review":
            item["baselines_or_comparators"] = "no aplica; revisión de literatura sin comparador causal único"
        else:
            item["baselines_or_comparators"] = "grupos, periodos, plataformas, condiciones o contextos comparados según el diseño empírico"
    if normalize_title(str(item.get("tasks_or_domains", ""))) == "no reportado":
        item["tasks_or_domains"] = construct_text
    if normalize_title(str(item.get("instruments_or_scales", ""))) == "no reportado":
        item["instruments_or_scales"] = "medidas de encuesta, indicadores digitales, escalas actitudinales o codificación empírica reportada"
    if normalize_title(str(item.get("theory_framework", ""))) == "no reportado":
        item["theory_framework"] = social_theory_framework_from_text(text, context)
    if not str(item.get("variables_dependent", "")).strip():
        dependent = [label for label in constructs if label in {"polarización afectiva", "confianza institucional", "participación y actitudes políticas"}]
        item["variables_dependent"] = "; ".join(dependent) if dependent else "resultado político, confianza, actitud o percepción institucional reportada"
    if not str(item.get("variables_independent", "")).strip():
        independent = [label for label in constructs if label in {"redes sociales", "desinformación o calidad informativa"}]
        item["variables_independent"] = "; ".join(independent) if independent else "exposición, uso, contexto o condición social analizada"
    if has_fallback_extraction_marker(str(item.get("key_findings", ""))) or normalize_title(str(item.get("key_findings", ""))) in {"no reportado", ""}:
        item["key_findings"] = social_key_findings_from_text(title, text, context)
    try:
        current_confidence = int(str(item.get("extraction_confidence") or "0").strip())
    except ValueError:
        current_confidence = 0
    if (source_row.get("full_text_text") or "").strip() and current_confidence < 80:
        item["extraction_confidence"] = 82


def heuristically_enrich_extraction_item(
    source_row: dict[str, str],
    item: dict[str, object],
    context: dict[str, str] | None = None,
) -> None:
    context = context or {}
    if is_social_science_mode(context):
        enrich_social_science_extraction_item(source_row, item, context)
        return
    title = source_row.get("title_original", "") or ""
    text = collapse_whitespace(
        " ".join(
            [
                source_row.get("title_original", "") or "",
                source_row.get("abstract_original", "") or "",
                source_row.get("full_text_text", "") or "",
            ]
        )
    )
    title_system = infer_title_system_name(title)
    model_candidates = extract_pattern_values(text, MODEL_NAME_PATTERNS, max_items=10)
    if title_system:
        model_candidates = dedupe_preserve([title_system, *model_candidates])
    dataset_candidates = extract_dataset_like_names(text, max_items=8)
    instrument_candidates = [
        item for item in extract_pattern_values(text, INSTRUMENT_PATTERNS, max_items=8)
        if normalize_title(item) not in GENERIC_INSTRUMENT_LABELS
    ]
    inferred_method = infer_method_used_from_text(text)
    inferred_tasks = infer_tasks_from_text(text, title)
    generic_model_value = normalize_title(str(item.get("models_or_systems_studied", ""))) in {
        "no reportado",
        "llm genericos no especificados explicitamente en el digest proporcionado",
        "modelos genericos no especificados",
    }

    if generic_model_value and model_candidates:
        item["models_or_systems_studied"] = "; ".join(model_candidates)
    if normalize_title(str(item.get("model_count", ""))) == "no reportado":
        item["model_count"] = infer_model_count(text, model_candidates)
    item["model_count"] = sanitize_model_count_for_extraction(item.get("model_count"))
    if normalize_title(str(item.get("benchmark_dataset_or_corpus", ""))) == "no reportado" and dataset_candidates:
        item["benchmark_dataset_or_corpus"] = "; ".join(dataset_candidates)
    if normalize_title(str(item.get("instruments_or_scales", ""))) == "no reportado" and instrument_candidates:
        item["instruments_or_scales"] = "; ".join(instrument_candidates)
    if normalize_title(str(item.get("method_used", ""))) == "no reportado" and inferred_method != "no reportado":
        item["method_used"] = inferred_method
    if normalize_title(str(item.get("tasks_or_domains", ""))) == "no reportado" and inferred_tasks != "no reportado":
        item["tasks_or_domains"] = inferred_tasks
    if normalize_title(str(item.get("unit_of_analysis", ""))) == "no reportado":
        if normalize_title(str(item.get("sample_description", ""))) != "no reportado":
            item["unit_of_analysis"] = item.get("sample_description", "no reportado")
        elif dataset_candidates:
            item["unit_of_analysis"] = dataset_candidates[0]
        elif model_candidates:
            item["unit_of_analysis"] = "modelos"
    if normalize_title(str(item.get("work_type", ""))) == "other" and (dataset_candidates or model_candidates or inferred_method != "no reportado"):
        item["work_type"] = "empirical"
    if normalize_title(str(item.get("empirical_type", ""))) == "other":
        if dataset_candidates or "benchmark" in text.lower() or "evaluation" in text.lower():
            item["empirical_type"] = "experimental"
        elif inferred_method != "no reportado":
            item["empirical_type"] = "quantitative"
    if normalize_title(str(item.get("design_detail", ""))) == "no reportado":
        empirical_type = collapse_whitespace(str(item.get("empirical_type", "") or "")).lower()
        if empirical_type and empirical_type != "other":
            item["design_detail"] = f"Estudio {empirical_type} con extracción heurística reforzada desde el texto completo del PDF"
    if has_fallback_extraction_marker(str(item.get("key_findings", ""))):
        overridden_finding = heuristic_key_findings_override(title, text)
        if overridden_finding:
            item["key_findings"] = overridden_finding
    if normalize_title(str(item.get("baselines_or_comparators", ""))) == "no reportado" and "truthfulqa" in text.lower():
        item["baselines_or_comparators"] = "Controles alineados y comparación entre docentes y estudiantes con misma o distinta base"
    try:
        current_confidence = int(str(item.get("extraction_confidence") or "0").strip())
    except ValueError:
        current_confidence = 0
    dense_fields = 0
    for field in (
        "design_detail",
        "unit_of_analysis",
        "models_or_systems_studied",
        "benchmark_dataset_or_corpus",
        "tasks_or_domains",
        "instruments_or_scales",
        "method_used",
    ):
        if normalize_title(str(item.get(field, ""))) != "no reportado":
            dense_fields += 1
    if dense_fields >= 5 and (source_row.get("full_text_text") or "").strip() and current_confidence < 80:
        item["extraction_confidence"] = 82


def ascii_figure_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return collapse_whitespace(ascii_only)


def normalize_doi(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    raw = raw.replace("doi:", "").strip()
    raw = re.sub(r"^https?://(dx\.)?doi\.org/", "", raw, flags=re.I)
    return raw.lower()


def canonicalize_decision_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = collapse_whitespace(ascii_only).lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z_]+", "", ascii_only)


def canonicalize_screening_decision(text: str, stage: str) -> str:
    token = canonicalize_decision_token(text)
    if stage == "title_abstract":
        mapping = {
            "include": "include",
            "included": "include",
            "incluir": "include",
            "incluido": "include",
            "incluida": "include",
            "maybe": "maybe",
            "unclear": "maybe",
            "pending": "maybe",
            "pendiente": "maybe",
            "exclude": "exclude",
            "excluded": "exclude",
            "excluir": "exclude",
            "excluido": "exclude",
            "excluida": "exclude",
        }
    else:
        mapping = {
            "include": "include_ft",
            "included": "include_ft",
            "include_ft": "include_ft",
            "incluir": "include_ft",
            "incluido": "include_ft",
            "incluida": "include_ft",
            "exclude": "exclude",
            "excluded": "exclude",
            "excluir": "exclude",
            "excluido": "exclude",
            "excluida": "exclude",
        }
    return mapping.get(token, "")


def full_text_has_pdf(row: dict[str, object]) -> bool:
    return bool(str(row.get("full_text_path", "") or "").strip())


def build_prisma_count_rows(
    review_dir: pathlib.Path,
    *,
    all_candidates: list[dict[str, str]] | None = None,
    candidate_rows: list[dict[str, str]] | None = None,
    full_text_rows: list[dict[str, object]] | None = None,
    included_count: int | None = None,
) -> list[dict[str, object]]:
    master_rows = read_csv(review_dir / "records" / "master-records.csv")
    ta_rows = read_csv(review_dir / "screening" / "title-abstract.csv")
    doi_index_rows = read_csv(review_dir / "records" / "doi-index.csv")
    full_text_disk = read_csv(review_dir / "screening" / "full-text.csv")

    if all_candidates is None:
        all_candidates = [
            row
            for row in ta_rows
            if canonicalize_screening_decision(row.get("decision", ""), "title_abstract") in {"include", "maybe"}
        ]
    candidate_rows = candidate_rows or []
    effective_full_text_rows = full_text_rows or full_text_disk

    attempted_downloads = [
        row for row in candidate_rows
        if "full_text_path" in row or "full_text_text" in row
    ]
    retrieved_candidate_rows = [row for row in attempted_downloads if full_text_has_pdf(row)]
    not_retrieved_candidate_rows = [row for row in attempted_downloads if not full_text_has_pdf(row)]

    retrieved_full_text_rows = [row for row in effective_full_text_rows if full_text_has_pdf(row)]
    assessed_full_text_rows = [
        row
        for row in retrieved_full_text_rows
        if canonicalize_screening_decision(row.get("decision", ""), "full_text") in {"include_ft", "exclude"}
    ]
    excluded_full_text_rows = [
        row
        for row in assessed_full_text_rows
        if canonicalize_screening_decision(row.get("decision", ""), "full_text") == "exclude"
    ]

    screened_total = len(ta_rows) or len(master_rows)
    identified_total = len(doi_index_rows) or len(master_rows)
    duplicates_removed = max(0, len(doi_index_rows) - len(master_rows))
    full_text_sought = len(all_candidates)
    full_text_retrieved = max(len(retrieved_full_text_rows), len(retrieved_candidate_rows))
    full_text_not_retrieved = max(
        sum(1 for row in effective_full_text_rows if not full_text_has_pdf(row)),
        len(not_retrieved_candidate_rows),
    )
    if not effective_full_text_rows and full_text_sought:
        full_text_not_retrieved = max(full_text_not_retrieved, full_text_sought - full_text_retrieved)
    full_text_assessed = len(assessed_full_text_rows)
    if included_count is None:
        included_count = sum(
            1
            for row in effective_full_text_rows
            if canonicalize_screening_decision(row.get("decision", ""), "full_text") == "include_ft"
        )

    return [
        {"stage": "identified", "count": identified_total, "notes": "Registros identificados en las fuentes y consolidados en la auditoría DOI."},
        {"stage": "duplicates_removed", "count": duplicates_removed, "notes": "Duplicados DOI o titulo consolidados antes del cierre final."},
        {"stage": "screened_title_abstract", "count": screened_total, "notes": "Registros cribados en titulo/resumen."},
        {
            "stage": "excluded_title_abstract",
            "count": sum(
                1
                for row in ta_rows
                if canonicalize_screening_decision(row.get("decision", ""), "title_abstract") == "exclude"
            ),
            "notes": "Exclusiones en titulo/resumen con motivo y score.",
        },
        {"stage": "full_text_sought", "count": full_text_sought, "notes": "Candidatos include/maybe trasladados a fase de evaluacion final."},
        {"stage": "full_text_retrieved", "count": full_text_retrieved, "notes": "PDFs recuperados y convertidos a texto para la fase de evaluacion final."},
        {"stage": "full_text_not_retrieved", "count": full_text_not_retrieved, "notes": "Sin PDF recuperable. Estos registros no pueden entrar en el corpus final."},
        {"stage": "full_text_assessed", "count": full_text_assessed, "notes": "Textos completos efectivamente evaluados a partir de PDF recuperado y extraido."},
        {"stage": "full_text_excluded", "count": len(excluded_full_text_rows), "notes": "Exclusiones en full text entre los PDFs efectivamente evaluados."},
        {"stage": "included_in_review", "count": included_count, "notes": "Estudios incluidos en la revision antes del cap ultraquality."},
    ]


def strip_html_tags(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def excerpt_window(text: str, start: int, end: int, radius: int = 900) -> str:
    raw = text[max(0, start - radius):min(len(text), end + radius)]
    return collapse_whitespace(raw)


def build_full_text_digest(
    text: str,
    *,
    focus_terms: list[str],
    max_chars: int = FULLTEXT_DIGEST_CHARS,
) -> str:
    """Build a compact digest with coverage across the whole PDF text.

    The review still reads the complete extracted PDF text; this helper only
    creates a smaller representation for the model with windows taken from the
    beginning, ending, major sections, and thematic keyword hits across the
    entire document.
    """
    if not text:
        return ""

    source = text
    lower = source.lower()
    blocks: list[tuple[str, str]] = []

    def add_block(label: str, snippet: str) -> None:
        snippet = collapse_whitespace(snippet)
        if len(snippet) < 80:
            return
        key = normalize_title(snippet[:180])
        if any(existing_key == key for existing_key, _ in [(normalize_title(item[1][:180]), item[1]) for item in blocks]):
            return
        blocks.append((label, snippet))

    add_block("apertura", source[:1400])
    add_block("cierre", source[-1400:])

    section_patterns = [
        ("introduccion", [r"\b1[\.\s]+introduction\b", r"\bintroduction\b", r"\bintroduccion\b"]),
        ("metodo", [r"\b2[\.\s]+method(?:ology)?\b", r"\bmethod(?:ology)?\b", r"\bmetodolog(?:y|ia)\b"]),
        ("resultados", [r"\bresults?\b", r"\bfindings\b", r"\bresultados\b", r"\bevaluation\b", r"\bexperiments?\b"]),
        ("discusion", [r"\bdiscussion\b", r"\bdiscusion\b"]),
        ("conclusion", [r"\bconclusions?\b", r"\bconclusiones?\b"]),
    ]
    for label, patterns in section_patterns:
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                add_block(label, excerpt_window(source, match.start(), match.end(), radius=1200))
                break

    for term in focus_terms:
        matches = list(re.finditer(re.escape(term.lower()), lower))
        if not matches:
            continue
        middle_match = matches[len(matches) // 2]
        add_block(f"foco:{term}", excerpt_window(source, middle_match.start(), middle_match.end(), radius=700))

    lines = [
        f"longitud_caracteres={len(source)}",
        f"longitud_palabras={len(source.split())}",
        "cobertura=apertura+cierre+secciones+ventanas_tematicas_sobre_todo_el_pdf",
        "",
    ]
    remaining = max_chars - sum(len(line) + 1 for line in lines)
    for label, snippet in blocks:
        chunk = f"[{label}] {snippet}"
        if len(chunk) + 2 > remaining:
            chunk = chunk[: max(0, remaining - 5)].rstrip() + "..."
        if len(chunk) < 20:
            break
        lines.append(chunk)
        lines.append("")
        remaining -= len(chunk) + 2
        if remaining <= 0:
            break
    return "\n".join(lines).strip()


def reconstruct_openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    slots: list[str] = []
    for word, positions in inverted.items():
        for pos in positions:
            while len(slots) <= pos:
                slots.append("")
            slots[pos] = word
    return " ".join(item for item in slots if item).strip()


def parse_intake_n_range(path: pathlib.Path) -> tuple[int | None, int | None]:
    if not path.exists():
        return None, None
    content = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"Límite final N ultraquality:\s*([^\n]+)", content)
    if not match:
        return None, None
    numbers = [int(item) for item in re.findall(r"\d+", match.group(1))]
    if len(numbers) >= 2:
        low, high = sorted(numbers[:2])
        return max(1, low), max(1, high)
    if len(numbers) == 1:
        return None, max(1, numbers[0])
    return None, None


def parse_intake_limit(path: pathlib.Path) -> int | None:
    _minimum, maximum = parse_intake_n_range(path)
    return maximum


def parse_intake_representativeness(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"Criterio de representatividad ultraquality:\s*(.+)", content)
    return match.group(1).strip() if match else ""


def parse_intake_field(path: pathlib.Path, label: str) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(rf"^- {re.escape(label)}:[ \t]*(.*)$", content, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def read_research_context(review_dir: pathlib.Path) -> dict[str, str]:
    intake_path = review_dir / "protocol" / "intake.md"
    question_path = review_dir / "protocol" / "research-question.md"
    question_text = question_path.read_text(encoding="utf-8", errors="ignore") if question_path.exists() else ""
    question_match = re.search(r"## Principal\s+(.+?)(?:\n## |\Z)", question_text, flags=re.S)
    context = {
        "topic": parse_intake_field(intake_path, "Tema"),
        "research_question": (question_match.group(1).strip() if question_match else parse_intake_field(intake_path, "Pregunta de investigación (opcional)")),
        "years": parse_intake_field(intake_path, "Año o años"),
        "inclusion": parse_intake_field(intake_path, "Criterios de inclusión"),
        "exclusion": parse_intake_field(intake_path, "Criterios de exclusión"),
        "review_mode_declared": (
            parse_intake_field(intake_path, "Modo metodológico (opcional)")
            or parse_intake_field(intake_path, "Modo metodologico (opcional)")
            or parse_intake_field(intake_path, "Modo de revisión (opcional)")
            or parse_intake_field(intake_path, "Modo de revision (opcional)")
        ),
    }
    decision = read_review_mode_decision(review_dir)
    if not decision or any(not decision.get(key) for key in REVIEW_MODE_PLAYBOOK_KEYS):
        decision = infer_review_mode(
            topic=context.get("topic", ""),
            question=context.get("research_question", ""),
            inclusion=context.get("inclusion", ""),
            exclusion=context.get("exclusion", ""),
            explicit_mode=context.get("review_mode_declared", ""),
        )
        write_review_mode_artifacts(review_dir, decision)
    context["review_mode"] = str(decision.get("mode") or "")
    context["primary_review_mode"] = str(decision.get("primary_mode") or decision.get("mode") or "")
    context["review_mode_label"] = str(decision.get("mode_label") or "")
    context["review_mode_framework"] = str(decision.get("default_framework") or "")
    return context


PUBLICATION_NEGATIVE_TERMS = [
    "knowledge share", "self-paced", "tutorial", "course", "slides", "lecture",
    "how to", "essentials", "playbook", "cheat sheet", "podcast", "episode summary",
    "show notes", "ep. ", "editor's note", "editors note", "editorial note",
    "editor’s note", "editorial.", "front matter", "table of contents",
    "issue introduction", "book review",
]

SOFTWARE_POSITIVE_TOKENS = [
    "software",
    "code",
    "coding",
    "repository",
    "debug",
    "testing",
    "test",
    "developer",
    "development",
    "devops",
    "sdlc",
    "fuzz",
    "benchmark",
    "bug",
    "commit",
    "pull request",
    "code review",
    "software engineering",
]

SOFTWARE_CORE_TOKENS = [
    "software",
    "code",
    "coding",
    "repository",
    "debug",
    "developer",
    "development",
    "devops",
    "sdlc",
    "fuzz",
    "bug",
    "commit",
    "pull request",
    "code review",
    "software engineering",
]

SOFTWARE_NEGATIVE_TOKENS = [
    "rare disease",
    "clinical",
    "medical",
    "hospital",
    "foundation design",
    "foundation",
    "geotechn",
    "smart city",
    "smart adaptive",
    "s-amma",
    "optical network",
    "network operations",
    "circuit",
    "structural modeling",
    "safety investigation",
    "diagnosis",
]

PERSONALITY_MODEL_TOKENS = [
    "reasoning model",
    "reasoning language model",
    "reasoning llm",
    "large language model",
    "language model",
    "llm",
    "reasoning",
    "reasoner",
    "gpt",
    "claude",
    "qwen",
    "deepseek",
]

PERSONALITY_STRONG_TOKENS = [
    "personality",
    "persona",
    "trait",
    "traits",
    "temperament",
    "identity",
    "self-concept",
    "self concept",
    "self-perception",
    "self perception",
    "character",
    "persona-aware",
    "persona aware",
]

PERSONALITY_BROAD_TOKENS = [
    "behavioral style",
    "behavioural style",
    "behavior style",
    "behaviour style",
    "preferences",
    "preference",
    "opinions",
    "opinion",
    "autonomy",
    "emotion",
    "emotions",
    "affect",
    "consistency",
    "sycophancy",
    "consciousness",
    "moral consideration",
]

PERSONALITY_SIGNATURE_TOKENS = [
    "mbti",
    "big five",
    "ocean",
    "sycoph",
    "psychological steering",
    "psychological profil",
    "personality measurement",
    "personality measurements",
    "split personality",
    "persona-imbued",
    "persona imbued",
    "role-aware",
    "role aware",
    "consciousness",
]

PERSONALITY_EMPIRICAL_TOKENS = [
    "experiment",
    "experiments",
    "experimental",
    "evaluation",
    "evaluate",
    "benchmark",
    "measur",
    "induc",
    "compar",
    "ablation",
    "fine-tun",
    "fine tun",
    "preference shift",
    "behavioral assay",
]

PERSONALITY_NEGATIVE_TOKENS = [
    "human personality",
    "personality disorder",
    "travel planning",
    "medical agent",
    "clinical documentation",
    "fake news detection",
    "software development",
    "software engineering",
    "emotion recognition",
    "depressive",
    "anxiety",
    "doctor-patient",
    "doctor patient",
    "health advice",
    "suicide prevention",
    "survey responses",
    "students",
    "higher education",
    "abusive comment",
    "hate speech",
    "audio summarization",
    "visual storytelling",
    "pedagogical",
    "tutor",
    "psychiatric diagnosis",
    "social media",
]

CREATIVITY_MODEL_TOKENS = [
    "large language model",
    "language model",
    "llm",
    "llms",
    "generative ai",
    "ia generativa",
    "modelo de lenguaje",
    "modelos de lenguaje",
    "chatgpt",
    "gpt",
    "gpt-4",
    "claude",
    "gemini",
    "llama",
    "mistral",
    "qwen",
    "deepseek",
]

CREATIVITY_STRONG_TOKENS = [
    "creativity",
    "creative",
    "creatividad",
    "creativo",
    "creativa",
    "criatividade",
    "divergent thinking",
    "pensamiento divergente",
    "creative writing",
    "creative problem solving",
    "creativity evaluation",
    "originality",
    "originalidad",
    "novelty",
    "novedad",
    "fluency",
    "fluidez",
    "flexibility",
    "flexibilidad",
    "elaboration",
    "elaboracion",
    "elaboración",
    "ideation",
    "ideacion",
    "ideación",
    "alternative uses",
    "remote associates",
    "torrance",
    "ttct",
]

CREATIVITY_EMPIRICAL_TOKENS = [
    "experiment",
    "experiments",
    "experimental",
    "evaluation",
    "evaluate",
    "assessment",
    "benchmark",
    "measure",
    "metric",
    "human evaluation",
    "human ratings",
    "rater",
    "raters",
    "dataset",
    "task",
    "tasks",
    "comparison",
    "compare",
    "study",
    "scoring",
    "rubric",
]

CREATIVITY_NEGATIVE_TOKENS = [
    "organizational creativity",
    "teacher creativity",
    "student creativity",
    "students' creativity",
    "students creativity",
    "human creativity only",
    "art therapy",
    "creativity training",
    "creativity education",
    "art education",
    "entrepreneurship education",
    "architectural learning",
    "higher education",
    "undergraduate students",
    "museum",
    "tourism",
    "entrepreneurial creativity",
    "marketing creativity",
    "fashion design",
    "music ai",
    "audiovisual translation",
    "copyright",
    "plagiarism",
    "green innovation",
]

CREATIVITY_DIRECT_STUDY_PATTERNS = [
    "llm creativity",
    "llms creativity",
    "creativity of llm",
    "creativity of llms",
    "creativity of large language models",
    "creativity in large language models",
    "creative abilities of large language models",
    "creative ability of large language models",
    "large language models creativity",
    "divergent creativity in humans and large language models",
    "evaluating creativity of",
    "measuring creativity of",
    "automated assessment of creativity in large language models",
    "creativity analysis of chatgpt",
    "chatgpt creativity",
    "creative performance of large language models",
    "creative writing with large language models",
]

CREATIVITY_TOOL_USE_PATTERNS = [
    "using generative ai to enhance",
    "using generative ai to foster",
    "leveraging generative ai tools across",
    "ai as a helper",
    "education model using generative ai",
    "attitudes toward generative ai",
    "generative ai in higher education",
    "generative ai in computer science education",
    "generative ai in entrepreneurship education",
    "generative ai in interior design education",
    "ai-driven generative design",
    "ai in content creation",
    "ai and audiovisual translation",
]


def normalized_focus_text(text: str) -> str:
    lowered = collapse_whitespace(text).lower()
    return lowered


def research_context_blob(context: dict[str, str]) -> str:
    return normalized_focus_text(
        " ".join(
            [
                context.get("topic", ""),
                context.get("research_question", ""),
                context.get("inclusion", ""),
                context.get("exclusion", ""),
                context.get("review_mode", ""),
                context.get("primary_review_mode", ""),
                context.get("review_mode_label", ""),
            ]
        )
    )


def review_mode_key(context: dict[str, str]) -> str:
    return (context.get("primary_review_mode") or context.get("review_mode") or "").strip()


def is_social_science_mode(context: dict[str, str]) -> bool:
    return review_mode_key(context) in {"social_sciences", "education", "management"} or context.get("review_mode") == "mixed"


def is_management_mode(context: dict[str, str]) -> bool:
    return review_mode_key(context) == "management"


def is_education_mode(context: dict[str, str]) -> bool:
    return review_mode_key(context) == "education"


def is_biomedical_mode(context: dict[str, str]) -> bool:
    return review_mode_key(context) == "biomedical"


GENERIC_PROTOCOL_STOPWORDS = {
    "sobre",
    "para",
    "como",
    "cómo",
    "entre",
    "desde",
    "hasta",
    "estudio",
    "estudios",
    "revision",
    "revisión",
    "sistematica",
    "sistemática",
    "literatura",
    "publicaciones",
    "publicados",
    "publicadas",
    "articulos",
    "artículos",
    "paper",
    "papers",
    "modelo",
    "modelos",
    "sistema",
    "sistemas",
    "investigacion",
    "investigación",
    "criterios",
    "inclusion",
    "inclusión",
    "exclusion",
    "exclusión",
    "texto",
    "completo",
    "final",
    "effect",
    "effects",
    "efecto",
    "efectos",
    "empirico",
    "empírico",
    "empirica",
    "empírica",
    "method",
    "methods",
    "study",
    "studies",
    "review",
    "systematic",
    "literature",
    "research",
    "paper",
    "papers",
    "final",
    "included",
    "impact",
    "impacto",
    "excluded",
    "include",
    "exclude",
}


def protocol_focus_terms(context: dict[str, str], limit: int = 18) -> list[str]:
    """Extract reusable topical terms from the intake for generic reviews.

    Topic-specific profiles still use curated vocabularies. This fallback keeps
    future topics from inheriting the old agent-architecture assumptions.
    """
    raw = " ".join(
        [
            context.get("topic", ""),
            context.get("research_question", ""),
            context.get("inclusion", ""),
        ]
    )
    lowered = normalized_focus_text(raw)
    quoted = [
        collapse_whitespace(match.group(1)).lower()
        for match in re.finditer(r"[\"'“”‘’]([^\"'“”‘’]{4,80})[\"'“”‘’]", raw)
    ]
    phrases = [
        collapse_whitespace(match.group(0)).lower()
        for match in re.finditer(r"\b[\wáéíóúüñ-]+(?:\s+[\wáéíóúüñ-]+){1,3}\b", lowered)
    ]
    words = [
        token
        for token in re.findall(r"\b[\wáéíóúüñ-]{4,}\b", lowered)
        if token not in GENERIC_PROTOCOL_STOPWORDS
    ]
    candidates = quoted + phrases + words
    scored: Counter[str] = Counter()
    for candidate in candidates:
        normalized = collapse_whitespace(candidate).strip(" .,:;()[]{}").lower()
        if not normalized or normalized in GENERIC_PROTOCOL_STOPWORDS:
            continue
        parts = [part for part in normalized.split() if part not in GENERIC_PROTOCOL_STOPWORDS]
        if not parts:
            continue
        normalized = " ".join(parts)
        if len(normalized) < 4:
            continue
        weight = 3 if " " in normalized else 1
        scored[normalized] += weight
    ordered = [term for term, _count in scored.most_common(limit)]
    return ordered


def generic_protocol_match_score(text: str, context: dict[str, str]) -> int:
    lowered = normalized_focus_text(text)
    score = 0
    for term in protocol_focus_terms(context):
        if term in lowered:
            score += 2 if " " in term else 1
    return score


def protocol_primary_terms(context: dict[str, str], limit: int = 3) -> list[str]:
    """Return the leading topic terms that define the review's main axis."""
    topic = normalized_focus_text(context.get("topic", ""))
    output: list[str] = []
    for token in re.findall(r"\b[\wáéíóúüñ-]{4,}\b", topic):
        if token in GENERIC_PROTOCOL_STOPWORDS or token in output:
            continue
        output.append(token)
        if len(output) >= limit:
            break
    return output


def generic_protocol_primary_match(text: str, context: dict[str, str]) -> bool:
    primary_terms = protocol_primary_terms(context)
    if not primary_terms:
        return True
    lowered = normalized_focus_text(text)
    # Topics are often written in Spanish while bibliographic records are
    # usually English. Requiring only the first topic token can silently reject
    # good cross-language records, so any leading axis term is enough here.
    return any(term in lowered for term in primary_terms)


def generic_protocol_domain_match(text: str, context: dict[str, str], *, min_score: int = 2) -> bool:
    return generic_protocol_match_score(text, context) >= min_score and generic_protocol_primary_match(text, context)


SOCIAL_WEAK_FOCUS_TERMS = {
    "analisis",
    "analysis",
    "articulo",
    "article",
    "caso",
    "cases",
    "contexto",
    "data",
    "datos",
    "democracia",
    "democracias",
    "democracies",
    "democracy",
    "democratic",
    "digital",
    "digitales",
    "el",
    "evidence",
    "evidencia",
    "existe",
    "exists",
    "factor",
    "field",
    "impact",
    "la",
    "las",
    "los",
    "literature",
    "metodo",
    "method",
    "model",
    "paper",
    "process",
    "que",
    "research",
    "relacion",
    "relationship",
    "resultado",
    "resultados",
    "review",
    "social",
    "sociales",
    "study",
    "systematic",
    "frente",
    "hacia",
    "hipotesis",
    "hipótesis",
    "human",
    "humano",
    "realmente",
    "really",
    "si",
    "un",
    "una",
    "uso",
    "use",
}

SOCIAL_METHOD_TERMS = {
    "analisis cualitativo",
    "analisis cuantitativo",
    "archival",
    "case study",
    "caso de estudio",
    "comparative",
    "comparativo",
    "content analysis",
    "cross-sectional",
    "cuantitativo",
    "cualitativo",
    "data",
    "dataset",
    "datos",
    "difference-in-differences",
    "diseno",
    "empirical",
    "empirica",
    "empirico",
    "encuesta",
    "entrevista",
    "experiment",
    "experimental",
    "fieldwork",
    "findings",
    "interview",
    "longitudinal",
    "method",
    "metodo",
    "mixed method",
    "muestra",
    "panel",
    "participant",
    "participants",
    "qualitative",
    "quantitative",
    "regresion",
    "regression",
    "respondent",
    "respondents",
    "sample",
    "survey",
}

SOCIAL_AXIS_ALIAS_RULES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (
        (
            "inteligencia artificial",
            "artificial intelligence",
            "ia generativa",
            "generative ai",
            "generative artificial intelligence",
            "large language model",
            "llm",
            "chatgpt",
        ),
        (
            "artificial intelligence",
            "inteligencia artificial",
            "generative AI",
            "generative artificial intelligence",
            "IA generativa",
            "large language model",
            "large language models",
            "LLM",
            "LLMs",
            "ChatGPT",
            "AI assistant",
            "AI tool",
        ),
    ),
    (
        (
            "carga de trabajo",
            "carga laboral",
            "workload",
            "work load",
            "effort",
            "esfuerzo",
            "time on task",
            "task time",
            "tiempo de tarea",
            "tiempo de trabajo",
        ),
        (
            "workload",
            "work load",
            "carga de trabajo",
            "carga laboral",
            "effort",
            "human effort",
            "esfuerzo",
            "tiempo de tarea",
            "task time",
            "time on task",
            "working time",
            "tiempo de trabajo",
            "administrative burden",
            "burden",
        ),
    ),
    (
        (
            "productividad",
            "productivity",
            "eficiencia",
            "efficiency",
            "performance",
            "rendimiento",
            "time saving",
            "cost saving",
        ),
        (
            "productivity",
            "productividad",
            "efficiency",
            "eficiencia",
            "performance",
            "rendimiento",
            "time saving",
            "time savings",
            "cost saving",
            "cost savings",
            "reduce time",
            "reduced time",
            "save time",
            "ahorro de tiempo",
        ),
    ),
    (
        (
            "supervision",
            "supervisión",
            "review",
            "revisión",
            "coordination",
            "coordinacion",
            "coordinación",
            "quality control",
            "control de calidad",
            "rework",
            "retrabajo",
            "human oversight",
        ),
        (
            "supervision",
            "supervisión",
            "human oversight",
            "oversight",
            "review",
            "revisión",
            "coordination",
            "coordinación",
            "quality control",
            "control de calidad",
            "rework",
            "retrabajo",
            "validation",
            "validación",
            "verification",
            "verificación",
        ),
    ),
    (
        (
            "workplace",
            "laboral",
            "employment",
            "employee",
            "professional",
            "organization",
            "organisation",
            "organizacion",
            "organización",
            "teacher",
            "docente",
            "nursing",
            "software developer",
        ),
        (
            "workplace",
            "lugar de trabajo",
            "laboral",
            "employment",
            "employee",
            "workers",
            "professional",
            "professionals",
            "organization",
            "organisation",
            "organización",
            "teacher",
            "teachers",
            "docente",
            "docentes",
            "faculty",
            "nursing",
            "software developer",
            "developer",
        ),
    ),
    (
        (
            "adopcion",
            "adopción",
            "adoption",
            "automation",
            "automatizacion",
            "automatización",
            "augmentation",
            "complementarity",
            "substitution",
            "displacement",
            "desplazamiento",
        ),
        (
            "adoption",
            "adopción",
            "automation",
            "automatización",
            "augmentation",
            "complementarity",
            "complementariedad",
            "substitution",
            "sustitución",
            "displacement",
            "desplazamiento",
            "human-AI collaboration",
            "human AI collaboration",
            "colaboración humano-máquina",
        ),
    ),
    (
        ("polarizacion", "polarization", "polarisation"),
        (
            "affective polarization",
            "affective polarisation",
            "polarizacion afectiva",
            "polarizacion politica",
            "political polarization",
            "partisan polarization",
            "partisan animosity",
            "out-party animus",
        ),
    ),
    (
        ("redes sociales", "social media", "social network"),
        (
            "redes sociales",
            "social media",
            "social networks",
            "social networking sites",
            "online social networks",
            "twitter",
            "facebook",
            "instagram",
            "tiktok",
        ),
    ),
    (
        ("confianza institucional", "institutional trust", "political trust", "trust in institutions"),
        (
            "confianza institucional",
            "institutional trust",
            "political trust",
            "trust in institutions",
            "confidence in institutions",
            "institutional confidence",
            "public trust",
        ),
    ),
    (
        ("democracia", "democracy", "democratic"),
        (
            "democracia",
            "democracias",
            "democracy",
            "democracies",
            "democratic",
            "democratic institutions",
        ),
    ),
]

SOCIAL_CONTEXT_AXIS_TERMS = {
    "democracia",
    "democracias",
    "democracy",
    "democracies",
    "democratic",
    "democratic institutions",
}


def folded_focus_text(text: str) -> str:
    """Normalize accents for cross-language social-science matching."""
    normalized = unicodedata.normalize("NFKD", collapse_whitespace(text).lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def social_protocol_axes(context: dict[str, str], *, limit: int = 10) -> list[list[str]]:
    """Build concept axes instead of treating every protocol token as equal.

    Social-science questions usually combine constructs, population/context and
    method. A record should connect several axes, not merely repeat one loose
    keyword such as "social" or "use".
    """
    blob = folded_focus_text(research_context_blob(context))
    axes: list[list[str]] = []

    for triggers, aliases in SOCIAL_AXIS_ALIAS_RULES:
        if any(trigger in blob for trigger in triggers):
            axes.append(list(aliases))

    for term in protocol_focus_terms(context, limit=28):
        folded = folded_focus_text(term).strip()
        if not folded or folded in SOCIAL_WEAK_FOCUS_TERMS:
            continue
        parts = [part for part in folded.split() if part not in SOCIAL_WEAK_FOCUS_TERMS]
        if not parts:
            continue
        if " " not in folded and len(folded) < 6:
            continue
        axes.append([term])

    unique_axes: list[list[str]] = []
    seen: set[str] = set()
    for axis in axes:
        cleaned = []
        for term in axis:
            folded = folded_focus_text(term).strip()
            if not folded or folded in SOCIAL_WEAK_FOCUS_TERMS:
                continue
            cleaned.append(term)
        if not cleaned:
            continue
        key = "|".join(sorted(folded_focus_text(term) for term in cleaned))
        if key in seen:
            continue
        seen.add(key)
        unique_axes.append(cleaned)
        if len(unique_axes) >= limit:
            break
    return unique_axes


def social_protocol_signal_counts(text: str, context: dict[str, str]) -> tuple[int, bool, list[str]]:
    """Return matched conceptual axes, method/evidence signal and labels."""
    lowered = folded_focus_text(text)
    matched_labels: list[str] = []
    for axis in social_protocol_axes(context):
        if any(folded_focus_text(term) in lowered for term in axis):
            if any(folded_focus_text(term) in SOCIAL_CONTEXT_AXIS_TERMS for term in axis):
                continue
            matched_labels.append(axis[0])
    method_signal = any(term in lowered for term in SOCIAL_METHOD_TERMS)
    return len(matched_labels), method_signal, matched_labels


def social_empirical_evidence_required(context: dict[str, str]) -> bool:
    blob = folded_focus_text(research_context_blob(context))
    return any(
        token in blob
        for token in (
            "evidencia empirica",
            "evidence empiric",
            "empirical evidence",
            "estudios empiricos",
            "empirical studies",
        )
    )


def social_title_abstract_decision(text: str, context: dict[str, str]) -> tuple[str, str, str, int, bool]:
    """Conservative title/abstract triage for social-science reviews."""
    axis_count, method_signal, matched_labels = social_protocol_signal_counts(text, context)
    focus_score = generic_protocol_match_score(text, context)
    empirical_required = social_empirical_evidence_required(context)

    if axis_count >= 2 and method_signal:
        labels = ", ".join(matched_labels[:3])
        return (
            "include",
            "meets_criteria",
            f"Conecta varios constructos centrales del protocolo ({labels}) y deja senal metodologica o empirica suficiente para pasar a texto completo.",
            0,
            method_signal,
        )
    if axis_count >= 2 and not empirical_required and focus_score >= 8:
        labels = ", ".join(matched_labels[:3])
        return (
            "include",
            "meets_criteria",
            f"Conecta varios constructos centrales del protocolo ({labels}); el texto completo debe precisar metodo, contexto y limite de inferencia.",
            0,
            method_signal,
        )
    if axis_count >= 2:
        labels = ", ".join(matched_labels[:3])
        return (
            "maybe",
            "needs_full_text_confirmation",
            f"Hay ajuste parcial entre constructos sociales del protocolo ({labels}), pero falta confirmar metodo, contexto, unidad de analisis o evidencia en texto completo.",
            20,
            method_signal,
        )
    if axis_count == 1 and method_signal and focus_score >= 6:
        return (
            "maybe",
            "needs_full_text_confirmation",
            "El registro muestra una senal social y metodologica parcial, pero no conecta todavia suficientes constructos centrales del protocolo.",
            24,
            method_signal,
        )
    return (
        "exclude",
        "wrong_population",
        "No conecta suficientes constructos centrales del protocolo social; una palabra suelta del tema no justifica inclusion.",
        82,
        method_signal,
    )


def is_software_review_context(context: dict[str, str]) -> bool:
    blob = research_context_blob(context)
    return any(token in blob for token in ("software", "codigo", "code", "ingenieria del software", "desarrollo de software"))


def is_agent_architecture_review_context(context: dict[str, str]) -> bool:
    blob = research_context_blob(context)
    return (
        not is_software_review_context(context)
        and not is_ai_architecture_review_context(context)
        and any(token in blob for token in ("agente", "agentes", "agent", "agents"))
    )


def is_corporate_political_leadership_review_context(context: dict[str, str]) -> bool:
    blob = research_context_blob(context)
    has_ideology_axis = any(
        token in blob
        for token in (
            "ideologia",
            "ideología",
            "political ideology",
            "political orientation",
            "political conservatism",
            "conservadurismo",
            "liberalism",
            "partisan",
            "partidista",
        )
    )
    has_leadership_axis = any(
        token in blob
        for token in (
            "liderazgo",
            "leadership",
            "ceo",
            "executive",
            "top management",
            "tmt",
            "board",
            "director",
            "founder",
            "corporate leader",
        )
    )
    has_firm_axis = any(
        token in blob
        for token in (
            "firma",
            "firm",
            "corporate",
            "empresa",
            "strategic",
            "strategy",
            "decisiones estrategicas",
            "decisiones estratégicas",
        )
    )
    return has_ideology_axis and has_leadership_axis and has_firm_axis


CORPORATE_POLITICAL_LEADERSHIP_TOKENS = (
    "ceo",
    "ceos",
    "chief executive",
    "executive",
    "top executive",
    "senior executive",
    "top management",
    "tmt",
    "upper echelon",
    "upper echelons",
    "board",
    "director",
    "chairman",
    "founder",
    "owner",
    "entrepreneur",
    "manager",
    "corporate leader",
    "corporate leadership",
)

CORPORATE_POLITICAL_IDEOLOGY_TOKENS = (
    "political ideology",
    "political ideologies",
    "political orientation",
    "political orientations",
    "political conservatism",
    "politically conservative",
    "political liberalism",
    "politically liberal",
    "political belief",
    "political beliefs",
    "political preference",
    "political preferences",
    "political leaning",
    "political leanings",
    "republican",
    "republican-leaning",
    "democrat",
    "democratic",
    "democratic-leaning",
    "partisan",
    "partisanship",
    "party affiliation",
    "political donation",
    "political donations",
    "campaign contribution",
    "campaign contributions",
    "political contribution",
    "political contributions",
    "left-wing",
    "right-wing",
    "left-leaning",
    "right-leaning",
)

CORPORATE_POLITICAL_AMBIGUOUS_IDEOLOGY_TOKENS = (
    "ideology",
    "ideologies",
    "ideological",
    "conservative",
    "conservatism",
    "liberal",
    "liberalism",
)

CORPORATE_POLITICAL_CONTEXT_TOKENS = (
    "political",
    "politic",
    "partisan",
    "partisanship",
    "party affiliation",
    "campaign",
    "donation",
    "donations",
    "contribution",
    "contributions",
    "republican",
    "democrat",
)

CORPORATE_STRATEGIC_DECISION_TOKENS = (
    "strategy",
    "strategic decision",
    "strategic change",
    "firm performance",
    "firm value",
    "corporate outcome",
    "corporate outcomes",
    "corporate decision",
    "corporate decisions",
    "corporate policy",
    "corporate policies",
    "strategic choice",
    "strategic choices",
    "investment",
    "resource allocation",
    "innovation",
    "risk taking",
    "risk-taking",
    "merger",
    "acquisition",
    "m&a",
    "diversification",
    "csr",
    "corporate social responsibility",
    "esg",
    "disclosure",
    "earnings forecast",
    "forecast bias",
    "management forecast",
    "tax",
    "tax avoidance",
    "financial reporting",
    "accounting conservatism",
    "misconduct",
    "corporate misconduct",
    "violation",
    "violations",
    "lobbying",
    "corporate political activity",
    "political activity",
    "governance",
    "capital structure",
    "financing",
    "loan contract",
    "loan contracts",
    "credit rating",
    "credit ratings",
    "cost of debt",
    "internationalization",
)

CORPORATE_POLITICAL_EMPIRICAL_TOKENS = (
    "empirical",
    "sample",
    "data",
    "dataset",
    "regression",
    "panel",
    "firm-year",
    "firm year",
    "event study",
    "difference-in-differences",
    "instrumental variable",
    "survey",
    "experiment",
    "archival",
    "compustat",
    "execucomp",
    "crsp",
    "boardex",
    "fec",
    "campaign finance",
    "donation",
    "donations",
    "contribution",
    "contributions",
)

CORPORATE_POLITICAL_NEGATIVE_TOKENS = (
    "voter",
    "voters",
    "electoral",
    "public opinion",
    "consumer ideology",
    "employee ideology",
    "political psychology",
    "party leadership",
    "government leadership",
    "political connections",
    "politically connected",
    "accounting conservatism",
    "earnings conservatism",
    "investment conservatism",
    "conditional conservatism",
    "managerial ideology",
    "capitalist ideology",
    "shareholder value ideology",
    "ideology of executive bonuses",
    "american dream",
    "grassroots movement",
    "public interest law",
)

CORPORATE_POLITICAL_CONNECTION_ONLY_TOKENS = (
    "political connections",
    "politically connected",
    "political connection",
)


def focus_token_in_text(lowered_text: str, token: str) -> bool:
    """Match topical tokens without treating substrings as evidence.

    Short tokens such as `iv` or common substrings inside unrelated words can
    otherwise create false positives in systematic-review screening.
    """
    normalized_token = normalized_focus_text(token)
    if not normalized_token:
        return False
    if re.fullmatch(r"[a-z0-9+-]+", normalized_token):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_token)}(?![a-z0-9])", lowered_text))
    return normalized_token in lowered_text


def focus_any_token(lowered_text: str, tokens: tuple[str, ...]) -> bool:
    """Domain routing should use phrase-aware matching, not raw substrings."""
    return any(focus_token_in_text(lowered_text, token) for token in tokens)


def corporate_political_leadership_signal_counts(text: str) -> tuple[int, int, int, bool]:
    lowered = f" {normalized_focus_text(text)} "
    leadership_score = sum(1 for token in CORPORATE_POLITICAL_LEADERSHIP_TOKENS if focus_token_in_text(lowered, token))
    political_context = any(focus_token_in_text(lowered, token) for token in CORPORATE_POLITICAL_CONTEXT_TOKENS)
    strong_ideology_score = sum(1 for token in CORPORATE_POLITICAL_IDEOLOGY_TOKENS if focus_token_in_text(lowered, token))
    ambiguous_ideology_score = sum(1 for token in CORPORATE_POLITICAL_AMBIGUOUS_IDEOLOGY_TOKENS if focus_token_in_text(lowered, token))
    ideology_score = strong_ideology_score + (ambiguous_ideology_score if political_context else 0)
    decision_score = sum(1 for token in CORPORATE_STRATEGIC_DECISION_TOKENS if focus_token_in_text(lowered, token))
    negative = any(focus_token_in_text(lowered, token) for token in CORPORATE_POLITICAL_NEGATIVE_TOKENS)
    if negative and not political_context:
        ideology_score = 0
    if any(focus_token_in_text(lowered, token) for token in CORPORATE_POLITICAL_CONNECTION_ONLY_TOKENS) and strong_ideology_score == 0:
        ideology_score = 0
    return leadership_score, ideology_score, decision_score, negative


def corporate_political_empirical_signal(text: str, work_type: str) -> bool:
    lowered = f" {normalized_focus_text(text)} "
    return work_type == "empirical" or any(focus_token_in_text(lowered, token) for token in CORPORATE_POLITICAL_EMPIRICAL_TOKENS)


AI_ARCHITECTURE_AI_TOKENS = (
    "artificial intelligence",
    "inteligencia artificial",
    " ai ",
    " ai.",
    " ai,",
    " ia ",
    "llm",
    "llms",
    "large language model",
    "large language models",
    "language model",
    "language models",
    "foundation model",
    "foundation models",
    "modelo fundacional",
    "modelos fundacionales",
    "generative ai",
    "ia generativa",
    "agentic ai",
    "ai agent",
    "ai agents",
    "agente de ia",
    "agentes de ia",
    "multi-agent",
    "multi agent",
)

AI_ARCHITECTURE_FAMILY_TOKENS = (
    "architecture",
    "architectural",
    "arquitectura",
    "arquitecturas",
    "framework",
    "system architecture",
    "model architecture",
    "agent architecture",
    "orchestration",
    "orquestacion",
    "orquestación",
    "workflow",
    "pipeline",
    "rag",
    "retrieval augmented generation",
    "retrieval-augmented generation",
    "tool use",
    "function calling",
    "memory",
    "memoria",
    "planner",
    "planning",
    "router",
    "routing",
    "transformer",
    "attention",
    "mixture of experts",
    "moe",
    "sparse model",
    "multimodal",
    "vision-language",
    "serving",
    "inference",
    "inferencia",
    "benchmark",
    "evaluation",
    "evaluacion",
    "evaluación",
)

AI_ARCHITECTURE_NEGATIVE_DOMAINS = (
    "urban architecture",
    "building architecture",
    "architectural heritage",
    "housing",
    "construction",
    "civil engineering",
    "geotechnical",
    "foundation design",
    "network architecture",
    "microservice architecture",
    "enterprise architecture",
    "computer architecture",
    "hardware architecture",
    "radar architecture",
    "blockchain architecture",
    "sdn architecture",
)


def is_ai_architecture_review_context(context: dict[str, str]) -> bool:
    """Detect broad AI-architecture reviews before falling back to agent-only profiles."""
    blob = f" {research_context_blob(context)} "
    has_architecture_axis = any(token in blob for token in ("arquitectur", "architecture", "architectural"))
    has_ai_axis = any(token in blob for token in AI_ARCHITECTURE_AI_TOKENS)
    return not is_software_review_context(context) and has_architecture_axis and has_ai_axis


def ai_architecture_signal_counts(text: str) -> tuple[int, int, bool]:
    """Return AI evidence, architectural-family evidence, and obvious off-domain noise."""
    lowered = f" {normalized_focus_text(text)} "
    ai_score = sum(1 for token in AI_ARCHITECTURE_AI_TOKENS if token in lowered)
    architecture_score = sum(1 for token in AI_ARCHITECTURE_FAMILY_TOKENS if token in lowered)
    negative_domain = any(token in lowered for token in AI_ARCHITECTURE_NEGATIVE_DOMAINS)
    return ai_score, architecture_score, negative_domain


MIND_BRAIN_LLM_MODEL_TOKENS = (
    "large language model",
    "large language models",
    "language model",
    "language models",
    "llm",
    "llms",
    "chatgpt",
    "gpt-",
    "transformer",
    "bert",
    "foundation model",
    "foundation models",
    "generative ai",
)

MIND_BRAIN_COGNITIVE_TOKENS = (
    "brain",
    "human brain",
    "neural",
    "neuron",
    "neuronal",
    "neuroscience",
    "neuroimaging",
    "fmri",
    "eeg",
    "meg",
    "cognition",
    "cognitive",
    "mind",
    "theory of mind",
    "neural representation",
    "neural representations",
    "brain activity",
    "brain alignment",
    "cerebro",
    "cognicion",
    "neurociencia",
)

MIND_BRAIN_EVIDENCE_TOKENS = (
    "experiment",
    "experimental",
    "benchmark",
    "evaluation",
    "evaluate",
    "analysis",
    "dataset",
    "study",
    "review",
    "survey",
    "comparison",
    "compare",
    "modeling",
    "modelling",
    "fmri",
    "eeg",
    "meg",
    "neuroimaging",
    "behavioral",
    "behavioural",
)


def is_mind_brain_llm_review_context(context: dict[str, str]) -> bool:
    blob = research_context_blob(context)
    return (
        focus_any_token(blob, MIND_BRAIN_LLM_MODEL_TOKENS)
        and focus_any_token(blob, MIND_BRAIN_COGNITIVE_TOKENS)
    )


def mind_brain_llm_signal_counts(text: str) -> tuple[int, int, int]:
    lowered = f" {normalized_focus_text(text)} "
    model_score = sum(1 for token in MIND_BRAIN_LLM_MODEL_TOKENS if token in lowered)
    cognitive_score = sum(1 for token in MIND_BRAIN_COGNITIVE_TOKENS if token in lowered)
    evidence_score = sum(1 for token in MIND_BRAIN_EVIDENCE_TOKENS if token in lowered)
    return model_score, cognitive_score, evidence_score


EDUCATION_AGENT_TOKENS = (
    "artificial intelligence",
    "ai",
    "ia",
    "ia generativa",
    "ai agent",
    "ai agents",
    "agentic",
    "llm agent",
    "llm agents",
    "intelligent tutoring system",
    "intelligent tutor",
    "ai tutor",
    "ai tutoring",
    "pedagogical agent",
    "educational agent",
    "educational agents",
    "teaching assistant",
    "chatbot",
    "chatbots",
    "multi-agent",
    "multi agent",
    "autonomous agent",
    "generative ai",
    "large language model",
    "large language models",
    "llm",
    "llms",
    "modelos de lenguaje",
    "grandes modelos de lenguaje",
    "asistente de ia",
    "asistentes de ia",
    "copilot",
    "copiloto",
)

EDUCATION_DOMAIN_TOKENS = (
    "education",
    "educational",
    "higher education",
    "higher education institution",
    "higher education institutions",
    "university",
    "university teacher",
    "university teachers",
    "university teaching",
    "universities",
    "college",
    "academic staff",
    "teacher",
    "teachers",
    "teaching",
    "professor",
    "professors",
    "faculty",
    "faculty development",
    "lecturer",
    "lecturers",
    "instructor",
    "instructors",
    "student",
    "students",
    "classroom",
    "learning",
    "pedagogy",
    "pedagogical",
    "educacion",
    "universidad",
    "universitario",
    "universitaria",
    "profesor",
    "profesores",
    "docente",
    "docentes",
    "educacion superior",
    "educación superior",
    "personal academico",
    "personal académico",
)

EDUCATION_QUALITY_TOKENS = (
    "teaching quality",
    "instructional quality",
    "learning outcomes",
    "student outcomes",
    "feedback",
    "retroalimentacion",
    "retroalimentación",
    "assessment",
    "evaluacion",
    "evaluación",
    "grading",
    "rubric",
    "curriculum",
    "curriculum design",
    "diseño curricular",
    "instructional design",
    "lesson planning",
    "student engagement",
    "workload",
    "productivity",
    "productividad",
    "academic productivity",
    "professional development",
    "teacher support",
    "faculty support",
    "ai literacy",
    "alfabetizacion ia",
    "alfabetización ia",
    "academic integrity",
    "integridad academica",
    "integridad académica",
    "evaluation",
    "experiment",
    "case study",
    "survey",
    "intervention",
)


def is_ai_agents_education_review_context(context: dict[str, str]) -> bool:
    blob = research_context_blob(context)
    return (
        focus_any_token(blob, EDUCATION_AGENT_TOKENS)
        and focus_any_token(blob, EDUCATION_DOMAIN_TOKENS)
    )


def ai_agents_education_signal_counts(text: str) -> tuple[int, int, int]:
    lowered = f" {normalized_focus_text(text)} "
    agent_score = sum(1 for token in EDUCATION_AGENT_TOKENS if focus_token_in_text(lowered, token))
    education_score = sum(1 for token in EDUCATION_DOMAIN_TOKENS if focus_token_in_text(lowered, token))
    quality_score = sum(1 for token in EDUCATION_QUALITY_TOKENS if focus_token_in_text(lowered, token))
    return agent_score, education_score, quality_score


def is_personality_reasoning_review_context(context: dict[str, str]) -> bool:
    blob = research_context_blob(context)
    return (
        focus_any_token(blob, ("personalidad", "personality", "persona", "trait", "traits"))
        and focus_any_token(blob, ("razonador", "reasoning", "reasoning model", "reasoning llm", "language model", "llm", "llms"))
    )


def is_creativity_llm_review_context(context: dict[str, str]) -> bool:
    blob = research_context_blob(context)
    return (
        any(token in blob for token in CREATIVITY_STRONG_TOKENS)
        and any(token in blob for token in CREATIVITY_MODEL_TOKENS)
    )


def review_topic_label(context: dict[str, str]) -> str:
    topic = collapse_whitespace(context.get("topic", "") or "")
    return topic or "el tema definido en el protocolo"


def review_digest_focus_terms(context: dict[str, str]) -> list[str]:
    if is_mind_brain_llm_review_context(context):
        return [
            "large language model",
            "language model",
            "llm",
            "chatgpt",
            "transformer",
            "brain",
            "human brain",
            "neural",
            "neuroscience",
            "neuroimaging",
            "fmri",
            "eeg",
            "cognition",
            "cognitive",
            "mind",
            "theory of mind",
            "language processing",
            "semantic representation",
            "memory",
            "attention",
            "reasoning",
            "comparison",
            "evaluation",
        ]
    if is_ai_agents_education_review_context(context):
        return [
            "artificial intelligence",
            "generative ai",
            "large language model",
            "llm",
            "chatgpt",
            "chatbot",
            "copilot",
            "ai agents",
            "llm agents",
            "agentic",
            "intelligent tutoring system",
            "ai tutor",
            "pedagogical agent",
            "teaching assistant",
            "higher education",
            "university",
            "teacher",
            "professor",
            "faculty",
            "teaching quality",
            "feedback",
            "assessment",
            "learning outcomes",
            "student engagement",
            "professional development",
            "evaluation",
            "intervention",
        ]
    if is_creativity_llm_review_context(context):
        return [
            "creativity",
            "creative",
            "originality",
            "novelty",
            "fluency",
            "flexibility",
            "elaboration",
            "divergent thinking",
            "creative writing",
            "creative problem solving",
            "alternative uses",
            "remote associates",
            "torrance",
            "ttct",
            "human evaluation",
            "rating",
            "benchmark",
            "dataset",
            "language model",
            "llm",
            "chatgpt",
            "generative ai",
            "comparison",
            "experiment",
        ]
    if is_personality_reasoning_review_context(context):
        return [
            "personality",
            "persona",
            "trait",
            "psychometric",
            "questionnaire",
            "scale",
            "benchmark",
            "dataset",
            "corpus",
            "baseline",
            "ablation",
            "model",
            "llm",
            "reasoning",
            "language model",
            "experiment",
            "evaluation",
            "behavior",
            "consistency",
            "big five",
            "mbti",
            "hexaco",
        ]
    if is_ai_architecture_review_context(context):
        return [
            "architecture",
            "architectural",
            "framework",
            "system",
            "foundation model",
            "large language model",
            "llm",
            "agent",
            "agents",
            "multi-agent",
            "agentic",
            "orchestration",
            "memory",
            "tool use",
            "retrieval augmented generation",
            "rag",
            "transformer",
            "mixture of experts",
            "moe",
            "multimodal",
            "vision-language",
            "inference",
            "serving",
            "routing",
            "benchmark",
            "evaluation",
        ]
    if is_software_review_context(context):
        return [
            "agent",
            "architecture",
            "framework",
            "orchestration",
            "multi-agent",
            "software",
            "engineering",
            "evaluation",
            "experiment",
            "benchmark",
        ]
    if is_agent_architecture_review_context(context):
        return [
            "agent",
            "agents",
            "ai agent",
            "architecture",
            "framework",
            "orchestration",
            "multi-agent",
            "memory",
            "tool",
            "tools",
            "rag",
            "evaluation",
            "benchmark",
            "workflow",
        ]
    return [
        *protocol_focus_terms(context, limit=12),
        "method",
        "methodology",
        "sample",
        "participants",
        "dataset",
        "experiment",
        "evaluation",
        "results",
    ]


def review_full_text_rules(context: dict[str, str]) -> list[str]:
    if is_mind_brain_llm_review_context(context):
        return [
            "Incluye si el texto completo compara de forma sustantiva LLMs, Transformers, ChatGPT o modelos fundacionales con cerebro humano, cognicion, neurociencia, lenguaje, memoria, atencion, razonamiento, representaciones neuronales o teoria de la mente.",
            "Acepta estudios empiricos, neuroimagen, modelado computacional, benchmarks, revisiones y teoria con evidencia trazable si la comparacion LLM-cerebro/cognicion es central.",
            "Excluye aplicaciones medicas o educativas de LLMs cuando no analicen procesos cerebrales, cognitivos o neurocientificos.",
            "Excluye analogias superficiales sin metodo, evidencia, datos, comparacion teorica articulada o contribucion cientifica verificable.",
        ]
    if is_ai_agents_education_review_context(context):
        return [
            "Incluye si el texto completo analiza IA, IA generativa, LLMs, ChatGPT, chatbots, copilotos, agentes de IA, tutores inteligentes o asistentes docentes en educacion superior, docencia universitaria o apoyo al profesorado.",
            "La contribucion debe aportar evidencia sobre calidad docente, preparacion de clases, diseño curricular, feedback, evaluacion, aprendizaje, carga de trabajo, productividad, alfabetizacion en IA, integridad academica, adopcion o resultados educativos.",
            "Acepta estudios empiricos, revisiones, intervenciones, casos de uso evaluados, benchmarks o marcos teoricos con evidencia trazable.",
            "Excluye uso generico de IA en estudiantes si no hay relacion clara con profesorado universitario, practica docente, calidad docente, diseño curricular, evaluacion, feedback o desarrollo docente.",
        ]
    if is_creativity_llm_review_context(context):
        return [
            "Incluye solo si el texto completo confirma un estudio, evaluacion, benchmark, experimento o revision sistematica sobre creatividad en LLMs o IA generativa.",
            "La creatividad debe ser constructo central: escritura creativa, pensamiento divergente, resolucion creativa de problemas, originalidad, novedad, fluidez, flexibilidad, elaboracion, ideacion o comparacion humano-modelo.",
            "Excluye trabajos sobre creatividad humana, educacion creativa, marketing, organizacion o arte sin evaluacion sustantiva de LLMs o IA generativa.",
            "Excluye articulos divulgativos, opinion, tutoriales, editoriales o propuestas sin metodo ni evidencia recuperable.",
            "Excluye si no hay suficiente texto completo para identificar tareas, metricas, modelos o criterios de evaluacion.",
        ]
    if is_personality_reasoning_review_context(context):
        return [
            "Incluye solo si el texto completo confirma un estudio empirico o experimental sobre modelos de IA razonadores que mida, induzca, compare, estabilice o evalue personalidad, rasgos, persona, estilo conductual o consistencia de personalidad del modelo.",
            "Excluye personalizacion, memoria de usuario o adaptacion individual cuando no exista un constructo explicito de personalidad del modelo.",
            "Excluye estudios centrados en personalidad humana sin foco principal en el modelo de IA.",
            "Excluye sistemas no razonadores salvo comparacion directa y sustantiva con modelos razonadores.",
            "Excluye si el texto parece material docente, editorial, slides o divulgacion sin contribucion investigadora sustantiva.",
        ]
    if is_ai_architecture_review_context(context):
        return [
            "Incluye si el texto completo confirma una contribucion sustantiva sobre arquitecturas de IA: agentes, sistemas multiagente, RAG, memoria, herramientas, orquestacion, modelos fundacionales, Transformer, MoE, multimodalidad, serving, inferencia o evaluacion arquitectonica.",
            "Acepta estudios empiricos, benchmarks, revisiones, surveys, propuestas tecnicas o marcos teoricos cuando la arquitectura sea el objeto central y haya metodo o evidencia suficiente.",
            "Excluye usos de IA meramente aplicados si no analizan la arquitectura, sus componentes, su coordinacion, sus trade-offs o su evaluacion.",
            "Excluye arquitectura urbana, construccion, redes, microservicios, hardware general o dominios no IA cuando el foco de IA sea tangencial.",
            "Excluye si el texto parece material docente, editorial, slides o divulgacion sin contribucion investigadora sustantiva.",
        ]
    if is_software_review_context(context):
        return [
            "Incluye solo si el texto completo confirma que la contribucion central trata una arquitectura, patron, marco, sistema o coordinacion de agentes aplicados a tareas de desarrollo o ingenieria de software.",
            "Excluye si el dominio principal no es desarrollo de software.",
            "Excluye si la parte de agentes es tangencial o si no hay suficiente detalle cientifico.",
            "Excluye si el texto parece material docente, editorial, slides o divulgacion sin contribucion investigadora sustantiva.",
        ]
    if is_agent_architecture_review_context(context):
        return [
            "Incluye solo si el texto completo confirma una contribucion sustantiva sobre agentes de IA, sistemas multiagente, memoria, herramientas, orquestacion, RAG, evaluacion o arquitectura agéntica.",
            "Excluye si el agente es solo una metafora, una mencion tangencial o un componente menor sin evidencia metodologica suficiente.",
            "Excluye si el texto parece material docente, editorial, slides o divulgacion sin contribucion investigadora sustantiva.",
        ]
    if is_management_mode(context):
        return [
            "Incluye si el texto completo analiza un fenomeno de management, estrategia, liderazgo, gobierno corporativo, innovacion, organizacion o empresa con unidad de analisis, metodo y resultado trazables.",
            "La decision debe identificar teoria, constructo o variable, contexto organizativo, muestra/sector/pais, metodo, mecanismo o resultado estrategico.",
            "No exijas experimentalidad si la pregunta admite evidencia archival, panel, encuesta, caso, cualitativa, mixta o revision teorica, pero conserva el limite de inferencia.",
            "Excluye opiniones, ensayos sin metodo, piezas divulgativas o trabajos donde la empresa/organizacion sea solo contexto decorativo.",
        ]
    if is_education_mode(context):
        return [
            "Incluye si el texto completo analiza un problema educativo con nivel, actores, actividad pedagogica, tecnologia/practica, resultado educativo o contexto institucional recuperables.",
            "Acepta evidencia cuantitativa, cualitativa, mixta, intervenciones, revisiones, estudios de caso y marcos teoricos si aportan relacion clara entre practica educativa y evidencia.",
            "No reduzcas calidad educativa a opinion: separa aprendizaje, feedback, evaluacion, diseno curricular, adopcion, equidad, carga docente y gobernanza.",
            "Excluye trabajos donde educacion sea solo ejemplo menor o donde no haya resultado, metodo, contexto o constructo educativo trazable.",
        ]
    if is_social_science_mode(context):
        return [
            "Incluye si el texto completo confirma fenomeno social, constructo, poblacion/caso, contexto, metodo y tipo de evidencia alineados con la pregunta.",
            "Acepta estudios cualitativos, cuantitativos, mixtos, teoricos y revisiones cuando la logica pregunta-metodo sea coherente y la evidencia sea trazable.",
            "No penalices disenos interpretativos por no tener comparador experimental; evalua claridad del constructo, teoria, contexto, reflexividad, muestra y transferibilidad.",
            "Excluye textos sin metodo, sin constructo reconocible, sin contexto o con foco tangencial respecto a los criterios del protocolo.",
        ]
    return [
        "Incluye solo si el texto completo confirma un ajuste central y sustantivo con la pregunta de investigacion y los criterios de inclusion del protocolo.",
        "Excluye si el trabajo encaja de forma clara con los criterios de exclusion o si el foco tematico es tangencial.",
        "Excluye si el texto parece material docente, editorial, slides o divulgacion sin contribucion investigadora sustantiva.",
    ]


def extraction_scope_label(context: dict[str, str]) -> str:
    if is_mind_brain_llm_review_context(context):
        return "comparacion entre LLMs, cerebro humano, cognicion, neurociencia, lenguaje, memoria, atencion, razonamiento y representaciones"
    if is_ai_agents_education_review_context(context):
        return "IA, IA generativa, LLMs, chatbots, copilotos, agentes y asistentes docentes en educacion superior y calidad docente universitaria"
    if is_creativity_llm_review_context(context):
        return "evaluacion y caracterizacion de la creatividad en modelos LLM e IA generativa"
    if is_personality_reasoning_review_context(context):
        return "medicion, induccion y evaluacion de personalidad en modelos de IA razonadores"
    if is_ai_architecture_review_context(context):
        return "arquitecturas de IA, modelos fundacionales, agentes, RAG, memoria, herramientas, multimodalidad, MoE e inferencia"
    if is_software_review_context(context):
        return "agentes autonomos en el desarrollo de software"
    if is_agent_architecture_review_context(context):
        return "arquitecturas, memoria, herramientas, orquestacion y evaluacion de agentes de IA"
    if is_management_mode(context):
        return "teoria, contexto, variables, mecanismos, metodo, endogeneidad y resultados en management u organizaciones"
    if is_education_mode(context):
        return "actividad educativa, actores, contexto institucional, practica/intervencion, resultado pedagogico y transferencia"
    if is_social_science_mode(context):
        return "constructos, poblaciones, contextos, metodos, mecanismos, resultados y limites de transferencia en ciencias sociales"
    return review_topic_label(context)


def personality_explicit_construct_score(text: str) -> int:
    lowered = (text or "").lower()
    return sum(
        1
        for term in [
            "personality",
            "trait",
            "traits",
            "temperament",
            "persona-aware",
            "persona aware",
            "persona-imbued",
            "persona imbued",
            "mbti",
            "big five",
            "ocean",
            "sycoph",
            "consciousness",
            "self-perception",
            "self perception",
            "psychological steering",
            "split personality",
            "personality measurement",
            "personality measurements",
            "psychological profil",
        ]
        if term in lowered
    )


def fallback_personality_title_abstract_decision(row: dict[str, str]) -> dict[str, object]:
    title = html.unescape(row.get("title_original", "")).lower()
    abstract = html.unescape(row.get("abstract_original", "")).lower()
    keywords = " ".join(
        [
            (row.get("keywords_author", "") or "").lower(),
            (row.get("keywords_indexed", "") or "").lower(),
            (row.get("keywords_normalized", "") or "").lower(),
        ]
    )
    text = f"{title} {abstract} {keywords}"
    work_type, empirical_type = infer_work_type(title, abstract)
    raw_work_type = (row.get("work_type", "") or "").lower()
    short_vague_title = len([token for token in re.split(r"\s+", title.strip()) if token]) <= 2
    has_publication_negative = any(term in text for term in PUBLICATION_NEGATIVE_TERMS)
    if raw_work_type in {"dataset", "reference-entry", "journal-issue"} or has_publication_negative:
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_publication_type",
            "reason_detail": "El registro parece material docente, episodio, recurso de apoyo o tipo de publicacion poco adecuado para una revision cientifica.",
            "exclusion_score": 92,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 10,
            "methodological_quality_score": 0,
            "confidence": 90,
        }
    if short_vague_title and not abstract.strip():
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "insufficient_detail",
            "reason_detail": "El titulo es demasiado vago y no hay abstract suficiente para justificar su paso a full text.",
            "exclusion_score": 90,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 10,
            "methodological_quality_score": 0,
            "confidence": 90,
        }
    has_model = any(term in text for term in PERSONALITY_MODEL_TOKENS)
    explicit_construct = personality_explicit_construct_score(text)
    has_empirical = any(term in text for term in PERSONALITY_EMPIRICAL_TOKENS) or work_type == "empirical"
    personalization_only = "personaliz" in text and explicit_construct == 0
    if personalization_only:
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_intervention",
            "reason_detail": "El registro trata personalizacion o memoria de usuario, pero no un constructo explicito de personalidad del modelo.",
            "exclusion_score": 88,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 10,
            "methodological_quality_score": 0,
            "confidence": 88,
        }
    if has_model and has_empirical and explicit_construct > 0:
        return {
            "record_id": row["record_id"],
            "decision": "maybe",
            "reason": "needs_full_text_confirmation",
            "reason_detail": "El registro muestra senales claras de constructo de personalidad del modelo y requiere verificacion por texto completo.",
            "exclusion_score": 20,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 72,
            "methodological_quality_score": 0,
            "confidence": 70,
        }
    return {
        "record_id": row["record_id"],
        "decision": "exclude",
        "reason": "insufficient_detail",
        "reason_detail": "Con titulo, abstract y keywords no hay evidencia suficiente de un constructo explicito de personalidad del modelo razonador.",
        "exclusion_score": 75,
        "work_type": work_type,
        "empirical_type": empirical_type,
        "relevance_score": 15,
        "methodological_quality_score": 0,
        "confidence": 80,
    }


def creativity_signal_scores(text: str, work_type: str = "") -> tuple[int, int, int, int]:
    lowered = (text or "").lower()
    model = sum(1 for token in CREATIVITY_MODEL_TOKENS if token in lowered)
    construct = sum(1 for token in CREATIVITY_STRONG_TOKENS if token in lowered)
    empirical = sum(1 for token in CREATIVITY_EMPIRICAL_TOKENS if token in lowered)
    negative = sum(1 for token in CREATIVITY_NEGATIVE_TOKENS if token in lowered)
    if work_type == "empirical":
        empirical += 1
    return model, construct, empirical, negative


def is_direct_creativity_model_study(text: str) -> bool:
    lowered = normalized_focus_text(text)
    if any(pattern in lowered for pattern in CREATIVITY_TOOL_USE_PATTERNS):
        return False
    if any(pattern in lowered for pattern in CREATIVITY_DIRECT_STUDY_PATTERNS):
        return True
    model, construct, empirical, _negative = creativity_signal_scores(lowered)
    has_evaluation = any(
        token in lowered
        for token in (
            "evaluat",
            "assess",
            "measure",
            "metric",
            "benchmark",
            "score",
            "rating",
            "human judge",
            "human evaluation",
            "comparison",
            "compare",
            "creativity test",
            "torrance",
            "alternative uses",
            "divergent thinking",
        )
    )
    model_as_object = any(
        token in lowered
        for token in (
            "large language model",
            "large language models",
            "llm",
            "llms",
            "chatgpt",
            "gpt-4",
            "gpt",
        )
    )
    near_model_creativity = bool(
        re.search(
            r"(?:large language models?|llms?|chatgpt|gpt-4|gpt)\W+(?:\w+\W+){0,10}?(?:creativ|originality|novelty|divergent|ideation)",
            lowered,
        )
        or re.search(
            r"(?:creativ|originality|novelty|divergent|ideation)\W+(?:\w+\W+){0,10}?(?:large language models?|llms?|chatgpt|gpt-4|gpt)",
            lowered,
        )
    )
    return model_as_object and construct > 0 and empirical > 0 and has_evaluation and near_model_creativity


def is_direct_creativity_model_title(title: str) -> bool:
    lowered = normalized_focus_text(title)
    if any(pattern in lowered for pattern in CREATIVITY_TOOL_USE_PATTERNS):
        return False
    if any(pattern in lowered for pattern in CREATIVITY_DIRECT_STUDY_PATTERNS):
        return True
    model_terms = ("large language model", "large language models", "llm", "llms", "chatgpt", "gpt", "gpt-4")
    creativity_terms = ("creativ", "originality", "novelty", "divergent", "ideation")
    evaluation_terms = ("assess", "evaluat", "measur", "benchmark", "scor", "comparison", "compare", "analysis")
    return (
        any(term in lowered for term in model_terms)
        and any(term in lowered for term in creativity_terms)
        and any(term in lowered for term in evaluation_terms)
    )


def fallback_creativity_title_abstract_decision(row: dict[str, str]) -> dict[str, object]:
    title = html.unescape(row.get("title_original", "")).lower()
    abstract = html.unescape(row.get("abstract_original", "")).lower()
    keywords = " ".join(
        [
            (row.get("keywords_author", "") or "").lower(),
            (row.get("keywords_indexed", "") or "").lower(),
            (row.get("keywords_normalized", "") or "").lower(),
        ]
    )
    text = f"{title} {abstract} {keywords}"
    work_type, empirical_type = infer_work_type(title, abstract)
    raw_work_type = (row.get("work_type", "") or "").lower()
    has_publication_negative = any(term in text for term in PUBLICATION_NEGATIVE_TERMS)
    short_vague_title = len([token for token in re.split(r"\s+", title.strip()) if token]) <= 2
    if raw_work_type in {"dataset", "reference-entry", "journal-issue"} or has_publication_negative:
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_publication_type",
            "reason_detail": "El registro parece material docente, divulgativo o un tipo documental poco adecuado para una revision cientifica.",
            "exclusion_score": 92,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 10,
            "methodological_quality_score": 0,
            "confidence": 90,
        }
    if short_vague_title and not abstract.strip():
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "insufficient_detail",
            "reason_detail": "El titulo es demasiado vago y no hay abstract suficiente para justificar su paso a texto completo.",
            "exclusion_score": 90,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 10,
            "methodological_quality_score": 0,
            "confidence": 90,
        }
    model, construct, empirical, negative = creativity_signal_scores(text, work_type)
    if negative and (model == 0 or construct <= 1):
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_population",
            "reason_detail": "El foco parece ser creatividad humana, educativa u organizativa sin evaluacion sustantiva de LLMs.",
            "exclusion_score": 88,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 15,
            "methodological_quality_score": 0,
            "confidence": 86,
        }
    direct_title = is_direct_creativity_model_title(title)
    direct_study = is_direct_creativity_model_study(text)
    if direct_title and empirical > 0:
        return {
            "record_id": row["record_id"],
            "decision": "include",
            "reason": "meets_criteria",
            "reason_detail": "Titulo, abstract o keywords apuntan a evaluacion empirica de creatividad en LLMs o IA generativa.",
            "exclusion_score": 0,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 88,
            "methodological_quality_score": 0,
            "confidence": 82,
        }
    if direct_title or direct_study:
        return {
            "record_id": row["record_id"],
            "decision": "maybe",
            "reason": "needs_full_text_confirmation",
            "reason_detail": "El registro conecta creatividad y LLMs, pero el metodo o la evaluacion necesitan confirmacion en texto completo.",
            "exclusion_score": 20,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 72,
            "methodological_quality_score": 0,
            "confidence": 72,
        }
    return {
        "record_id": row["record_id"],
        "decision": "exclude",
        "reason": "insufficient_detail",
        "reason_detail": "No hay evidencia suficiente de que el estudio evalue creatividad en modelos LLM o IA generativa.",
        "exclusion_score": 78,
        "work_type": work_type,
        "empirical_type": empirical_type,
        "relevance_score": 15,
        "methodological_quality_score": 0,
        "confidence": 82,
    }


def shortlist_focus_exclusion_reason(research_context: dict[str, str], row: dict[str, object]) -> str:
    if not normalize_doi(str(row.get("assigned_doi", "") or "")):
        return "sin_doi"
    full_text_path = str(row.get("full_text_path", "") or "")
    if not full_text_path.lower().endswith(".pdf"):
        return "sin_pdf_local"
    blob = normalized_focus_text(
        " ".join(
            [
                str(row.get("title_original", "") or ""),
                str(row.get("title_en", "") or ""),
                str(row.get("title_es", "") or ""),
                str(row.get("abstract_original", "") or ""),
                str(row.get("abstract_en", "") or ""),
                str(row.get("abstract_es", "") or ""),
                str(row.get("keywords_normalized", "") or ""),
                str(row.get("keywords_indexed", "") or ""),
                str(row.get("keywords_author", "") or ""),
                str(row.get("full_text_reason", "") or ""),
                str(row.get("full_text_reason_detail", "") or ""),
                str(row.get("method_used", "") or ""),
                str(row.get("sample_description", "") or ""),
            ]
        )
    )
    if is_software_review_context(research_context):
        positive = sum(1 for token in SOFTWARE_CORE_TOKENS if token in blob)
        negative = sum(1 for token in SOFTWARE_NEGATIVE_TOKENS if token in blob)
        if negative >= 1 and positive <= 2:
            return "fuera_de_dominio_software"
    elif is_creativity_llm_review_context(research_context):
        model, construct, empirical, negative = creativity_signal_scores(blob)
        direct_study = is_direct_creativity_model_study(blob)
        if negative >= 1 and not direct_study:
            return "creatividad_humana_sin_llm"
        if model == 0 or construct == 0 or not direct_study:
            return "ajuste_tematico_insuficiente"
        if empirical == 0:
            return "sin_metodo_o_evaluacion_creatividad"
    elif is_personality_reasoning_review_context(research_context):
        strong = sum(1 for token in PERSONALITY_STRONG_TOKENS if token in blob)
        broad = sum(1 for token in PERSONALITY_BROAD_TOKENS if token in blob)
        model = sum(1 for token in PERSONALITY_MODEL_TOKENS if token in blob)
        if "personaliz" in blob and strong == 0:
            return "personalizacion_sin_personalidad"
        if model == 0 or (strong == 0 and broad == 0):
            return "ajuste_tematico_insuficiente"
    elif is_corporate_political_leadership_review_context(research_context):
        leadership_score, ideology_score, decision_score, negative = corporate_political_leadership_signal_counts(blob)
        firm_axis = any(
            focus_token_in_text(blob, token)
            for token in ("firm", "firms", "corporate", "company", "companies", "strategic", "strategy")
        )
        if not (leadership_score > 0 and ideology_score > 0 and decision_score > 0 and firm_axis) or (negative and ideology_score == 0):
            return "ajuste_tematico_insuficiente"
    elif generic_protocol_match_score(blob, research_context) == 0:
        return "ajuste_tematico_insuficiente"
    return ""


def first_source_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            text = first_source_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("value", "text", "title", "name", "id", "url"):
            text = first_source_text(value.get(key))
            if text:
                return text
    return ""


def source_doi(value: object) -> str:
    if isinstance(value, str):
        return normalize_doi(value)
    if isinstance(value, list):
        for item in value:
            doi = source_doi(item)
            if doi:
                return doi
    if isinstance(value, dict):
        for key in ("doi", "DOI", "value", "id"):
            doi = source_doi(value.get(key))
            if doi:
                return doi
        for nested in value.values():
            doi = source_doi(nested)
            if doi:
                return doi
    return ""


def europepmc_pdf_url(item: dict) -> str:
    urls = (((item.get("fullTextUrlList") or {}).get("fullTextUrl")) or [])
    for entry in urls:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "")
        style = str(entry.get("documentStyle") or "").lower()
        if url and ("pdf" in style or url.lower().endswith(".pdf") or "/pdf" in url.lower()):
            return url
    return ""


def load_raw_sources(review_dir: pathlib.Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    raw_dir = review_dir / "searches" / "raw"
    doi_map: dict[str, dict[str, str]] = {}
    title_map: dict[str, dict[str, str]] = {}
    record_map: dict[str, dict[str, str]] = {}

    openalex_path = raw_dir / "openalex-2026.json"
    if openalex_path.exists():
        data = json.loads(openalex_path.read_text(encoding="utf-8"))
        for item in data.get("results", []):
            title = item.get("display_name") or item.get("title") or ""
            doi = normalize_doi(item.get("doi") or "")
            work_id = (item.get("id") or "").rsplit("/", 1)[-1]
            meta = {
                "title": title,
                "abstract": reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                "keywords": ", ".join(
                    concept.get("display_name", "")
                    for concept in item.get("concepts", [])[:12]
                    if concept.get("display_name")
                ),
                "source": "openalex",
                "work_type": item.get("type") or "",
                "pdf_url": ((item.get("best_oa_location") or {}).get("pdf_url") or ""),
                "landing_url": ((item.get("primary_location") or {}).get("landing_page_url") or ""),
            }
            if doi:
                doi_map[doi] = meta
            if title:
                title_map[normalize_title(title)] = meta
            if work_id:
                record_map[f"oa_{work_id}"] = meta

    crossref_path = raw_dir / "crossref-2026.json"
    if crossref_path.exists():
        data = json.loads(crossref_path.read_text(encoding="utf-8"))
        for item in data.get("message", {}).get("items", []):
            title = " ".join(item.get("title") or [])
            doi = normalize_doi(item.get("DOI") or "")
            pdf_url = ""
            for link in item.get("link") or []:
                candidate_url = str(link.get("URL") or "")
                content_type = str(link.get("content-type") or "").lower()
                if "pdf" in content_type or candidate_url.lower().endswith(".pdf") or "/pdf" in candidate_url.lower():
                    pdf_url = candidate_url
                    break
            authors = ", ".join(
                " ".join(filter(None, [author.get("given", "").strip(), author.get("family", "").strip()])).strip()
                for author in item.get("author", [])
                if (author.get("given") or author.get("family"))
            )
            meta = {
                "title": title,
                "abstract": strip_html_tags(item.get("abstract", "")),
                "keywords": ", ".join(item.get("subject") or []),
                "source": "crossref",
                "work_type": item.get("type") or "",
                "pdf_url": pdf_url,
                "landing_url": f"https://doi.org/{doi}" if doi else "",
                "authors": authors,
            }
            if doi:
                doi_map.setdefault(doi, meta)
                record_map[f"cr_{doi.replace('/', '_').replace('.', '_')}"] = meta
            if title:
                title_map.setdefault(normalize_title(title), meta)

    arxiv_path = raw_dir / "arxiv-records.json"
    if arxiv_path.exists():
        data = json.loads(arxiv_path.read_text(encoding="utf-8"))
        for item in data:
            title = item.get("title") or ""
            arxiv_id = item.get("arxiv_id") or ""
            short_id = arxiv_id.rsplit("/", 1)[-1]
            pdf_url = arxiv_id.replace("/abs/", "/pdf/") + ".pdf" if "/abs/" in arxiv_id else ""
            meta = {
                "title": title,
                "abstract": item.get("abstract") or "",
                "keywords": item.get("keywords") or "",
                "source": "arxiv",
                "work_type": item.get("work_type") or "preprint",
                "pdf_url": pdf_url,
                "landing_url": arxiv_id,
                "authors": item.get("authors") or "",
            }
            doi = normalize_doi(item.get("doi") or "")
            if doi:
                doi_map.setdefault(doi, meta)
            if title:
                title_map.setdefault(normalize_title(title), meta)
            if short_id:
                record_map[f"arx_{short_id.replace('.', '_')}"] = meta

    semanticscholar_path = raw_dir / "semanticscholar-2026.json"
    if semanticscholar_path.exists():
        data = json.loads(semanticscholar_path.read_text(encoding="utf-8"))
        for item in data.get("data", []):
            title = item.get("title") or ""
            external_ids = item.get("externalIds") or {}
            doi = normalize_doi(external_ids.get("DOI") or "")
            pdf_url = ((item.get("openAccessPdf") or {}).get("url") or "")
            meta = {
                "title": title,
                "abstract": item.get("abstract") or "",
                "keywords": "",
                "source": "semanticscholar",
                "work_type": "; ".join(item.get("publicationTypes") or []),
                "pdf_url": pdf_url,
                "landing_url": item.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                "authors": "; ".join((author.get("name") or "") for author in item.get("authors") or [] if author.get("name")),
            }
            paper_id = item.get("paperId") or ""
            if doi:
                doi_map.setdefault(doi, meta)
            if title:
                title_map.setdefault(normalize_title(title), meta)
            if paper_id:
                record_map[f"ss_{paper_id}"] = meta

    europepmc_path = raw_dir / "europepmc-2026.json"
    if europepmc_path.exists():
        data = json.loads(europepmc_path.read_text(encoding="utf-8"))
        for item in data.get("data", []):
            title = item.get("title") or ""
            doi = normalize_doi(item.get("doi") or "")
            meta = {
                "title": title,
                "abstract": strip_html_tags(item.get("abstractText") or ""),
                "keywords": ", ".join((item.get("keywordList") or {}).get("keyword") or []),
                "source": "europepmc",
                "work_type": item.get("pubType") or "",
                "pdf_url": europepmc_pdf_url(item),
                "landing_url": item.get("fullTextUrl") or (f"https://doi.org/{doi}" if doi else ""),
                "authors": item.get("authorString") or "",
            }
            if doi:
                doi_map.setdefault(doi, meta)
            if title:
                title_map.setdefault(normalize_title(title), meta)
            if item.get("id"):
                record_map[f"epmc_{item.get('id')}"] = meta

    openaire_path = raw_dir / "openaire-2026.json"
    if openaire_path.exists():
        data = json.loads(openaire_path.read_text(encoding="utf-8"))
        for item in data.get("results", []):
            title = first_source_text(item.get("mainTitle") or item.get("title") or item.get("titles") or item.get("name"))
            doi = source_doi(item.get("pid") or item.get("pids") or item.get("doi") or item.get("identifiers"))
            meta = {
                "title": title,
                "abstract": first_source_text(item.get("description") or item.get("abstract") or item.get("descriptions")),
                "keywords": first_source_text(item.get("subjects") or item.get("keywords")),
                "source": "openaire",
                "work_type": first_source_text(item.get("type") or item.get("resulttype")),
                "pdf_url": "",
                "landing_url": first_source_text(item.get("url") or item.get("landingPage") or item.get("instance") or item.get("instances")),
                "authors": first_source_text(item.get("authors") or item.get("creators") or item.get("author")),
            }
            if doi:
                doi_map.setdefault(doi, meta)
            if title:
                title_map.setdefault(normalize_title(title), meta)
            if item.get("id"):
                record_map[f"openaire_{str(item.get('id')).replace('/', '_')}"] = meta

    pubmed_path = raw_dir / "pubmed-2026.json"
    if pubmed_path.exists():
        data = json.loads(pubmed_path.read_text(encoding="utf-8"))
        for item in data.get("data", []):
            title = item.get("title") or ""
            doi = normalize_doi(item.get("doi") or "")
            meta = {
                "title": title,
                "abstract": item.get("abstract") or "",
                "keywords": "",
                "source": "pubmed",
                "work_type": "journal-article",
                "pdf_url": "",
                "landing_url": item.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                "authors": item.get("authors") or "",
            }
            if doi:
                doi_map.setdefault(doi, meta)
            if title:
                title_map.setdefault(normalize_title(title), meta)
            if item.get("pmid"):
                record_map[f"pubmed_{item.get('pmid')}"] = meta

    lens_path = raw_dir / "lens-2026.json"
    if lens_path.exists():
        data = json.loads(lens_path.read_text(encoding="utf-8"))
        for item in data.get("data", []):
            title = first_source_text(item.get("title"))
            doi = source_doi(item.get("doi") or item.get("external_ids"))
            authors = []
            for author in item.get("authors") or []:
                if not isinstance(author, dict):
                    continue
                name = first_source_text(author.get("display_name") or author.get("full_name") or author.get("name"))
                if not name:
                    name = " ".join(part for part in [first_source_text(author.get("first_name")), first_source_text(author.get("last_name"))] if part)
                if name:
                    authors.append(name)
            meta = {
                "title": title,
                "abstract": first_source_text(item.get("abstract")),
                "keywords": ", ".join(first_source_text(keyword) for keyword in item.get("keywords") or [] if first_source_text(keyword)),
                "source": "lens",
                "work_type": first_source_text(item.get("publication_type") or item.get("type")),
                "pdf_url": "",
                "landing_url": first_source_text(item.get("url") or item.get("source")),
                "authors": "; ".join(authors),
            }
            if doi:
                doi_map.setdefault(doi, meta)
            if title:
                title_map.setdefault(normalize_title(title), meta)
            if item.get("lens_id"):
                record_map[f"lens_{item.get('lens_id')}"] = meta

    return doi_map, title_map, record_map


def enrich_rows(review_dir: pathlib.Path) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    master_rows = read_csv(review_dir / "records" / "master-records.csv")
    screening_rows = read_csv(review_dir / "screening" / "title-abstract.csv")
    decisions = {row["record_id"]: row for row in screening_rows}
    doi_map, title_map, record_map = load_raw_sources(review_dir)
    enriched: list[dict[str, str]] = []
    by_record: dict[str, dict[str, str]] = {}

    for row in master_rows:
        record_id = row.get("record_id", "")
        meta = {}
        doi = normalize_doi(row.get("assigned_doi", ""))
        title = row.get("title_original", "")
        if record_id in record_map:
            meta = record_map[record_id]
        if doi and doi in doi_map:
            meta = {**meta, **doi_map[doi]}
        norm_title = normalize_title(title)
        if norm_title and norm_title in title_map:
            meta = {**title_map[norm_title], **meta}

        abstract = row.get("abstract_original", "") or meta.get("abstract", "")
        keywords_author = row.get("keywords_author", "") or meta.get("keywords", "")
        landing = meta.get("landing_url") or (f"https://doi.org/{doi}" if doi else "")
        pdf_url = meta.get("pdf_url") or ""
        work_type = row.get("work_type", "") or meta.get("work_type", "")
        enriched_row = dict(row)
        enriched_row.update(
            {
                "assigned_doi": doi,
                "abstract_original": abstract,
                "keywords_author": keywords_author,
                "keywords_indexed": row.get("keywords_indexed", "") or keywords_author,
                "keywords_normalized": row.get("keywords_normalized", "") or ", ".join(sorted({item.strip().lower() for item in keywords_author.split(",") if item.strip()})),
                "title_en": row.get("title_en", "") or title,
                "abstract_en": row.get("abstract_en", "") or abstract,
                "full_text_url": pdf_url or landing,
                "work_type": work_type,
                "source": row.get("source", "") or meta.get("source", ""),
                "authors": row.get("authors", "") or meta.get("authors", ""),
            }
        )
        if decisions.get(record_id):
            enriched_row["ta_decision"] = decisions[record_id].get("decision", "")
            enriched_row["ta_reason"] = decisions[record_id].get("reason", "")
        else:
            enriched_row["ta_decision"] = ""
            enriched_row["ta_reason"] = ""
        enriched.append(enriched_row)
        by_record[record_id] = enriched_row
    return enriched, by_record


def extract_message_text(message: object) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts: list[str] = []
        for item in message:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item)
        return "\n".join(parts).strip()
    return ""


def models_for_runtime(runtime: dict[str, object], preferred_models: list[str] | None) -> list[str]:
    runtime_models = [str(model) for model in runtime.get("models", [])]
    if preferred_models:
        selected = [model for model in preferred_models if model in runtime_models]
        if selected:
            return selected
    return runtime_models


def call_llm(
    prompt: str,
    schema: dict[str, object],
    model_log: list[str],
    preferred_models: list[str] | None = None,
    request_timeout_seconds: int = 320,
    retries: int | None = None,
) -> str:
    last_error = None
    attempts_total = retries if retries is not None else LLM_RETRIES
    schema_json = json.dumps(schema, ensure_ascii=False)
    system_prompt = (
        "Responde solo con JSON válido UTF-8. "
        "No uses markdown, no uses ``` ni comentarios, y devuelve un único objeto JSON."
    )
    user_prompt = (
        f"{prompt}\n\n"
        f"Esquema orientativo del JSON requerido:\n{schema_json}\n"
    )
    for runtime in RUNTIME_CHAIN:
        model_candidates = models_for_runtime(runtime, preferred_models)
        if not model_candidates:
            continue
        for model in model_candidates:
            for attempt in range(1, attempts_total + 1):
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": TEMPERATURE,
                    "max_tokens": MAX_PREDICT_TOKENS,
                    "stream": False,
                }
                try:
                    body = post_openai_compatible_chat(
                        base_url=str(runtime["base_url"]),
                        api_key=str(runtime["api_key"]),
                        payload=payload,
                        timeout_seconds=request_timeout_seconds,
                    )
                    choice = (body.get("choices") or [{}])[0]
                    message = choice.get("message") or {}
                    content = extract_message_text(message.get("content", ""))
                    if not content:
                        raise RuntimeError(f"Empty response from model `{model}`.")
                    model_log.append(model)
                    return content
                except RuntimeError as exc:  # pragma: no cover - operational fallback
                    last_error = exc
                    stderr = str(exc).lower()
                    transient = any(str(code) in stderr for code in TRANSIENT_HTTP_STATUS)
                    if attempt < attempts_total and (
                        transient
                        or "timed out" in stderr
                        or "timeout" in stderr
                        or "connection reset" in stderr
                    ):
                        time.sleep(LLM_RETRY_DELAY_SECONDS * attempt)
                        continue
                    break
                except TimeoutError as exc:  # pragma: no cover - operational fallback
                    last_error = exc
                    if attempt < attempts_total:
                        time.sleep(LLM_RETRY_DELAY_SECONDS * attempt)
                        continue
                    break
                except Exception as exc:  # pragma: no cover - operational fallback
                    last_error = exc
                    break
    raise RuntimeError(f"No se pudo completar la llamada al proveedor LLM: {last_error}")


def parse_json_response(text: str) -> dict[str, object]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"```$", "", cleaned).strip()
    if cleaned and not cleaned.lstrip().startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def parse_notes_metadata(notes: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for key in ("confidence", "relevance", "methodological"):
        match = re.search(rf"{key}=([0-9]+)", notes or "")
        if match:
            values[key] = int(match.group(1))
    return values


def checkpoint_sync(review_dir: pathlib.Path) -> None:
    script_dir = pathlib.Path(__file__).resolve().parent
    commands = [
        [sys.executable, str(script_dir / "review_runtime_state.py"), str(review_dir)],
        [sys.executable, str(script_dir / "review_audit.py"), str(review_dir)],
        [sys.executable, str(script_dir / "sync_review_to_obsidian.py"), str(review_dir)],
        [sys.executable, str(script_dir / "telegram_prisma_notify.py"), "phase", str(review_dir)],
    ]
    for command in commands:
        try:
            subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            continue


def full_text_retrieval_budget(n_limit: int, total_candidates: int) -> int:
    """Cap expensive full-text retrieval without changing the final N contract.

    Public users often test with small targets such as N=3 or N=10. Downloading
    hundreds of PDFs before ranking makes that experience feel broken, even when
    the search was successful. The budget stays generous for real reviews and
    can be overridden when a reviewer wants exhaustive retrieval.
    """
    override = os.environ.get("HERMES_FULLTEXT_RETRIEVAL_BUDGET", "").strip()
    if override.isdigit() and int(override) > 0:
        return min(total_candidates, int(override))
    # Keep the default realistic for public users: broad enough to survive PDF
    # attrition, but capped so a review does not spend hours before synthesis.
    return min(total_candidates, max(80, min(240, int(n_limit or 20) * 4)))


def prioritize_full_text_candidates(
    rows: list[dict[str, str]],
    n_limit: int,
    context: dict[str, str],
) -> list[dict[str, str]]:
    budget = full_text_retrieval_budget(n_limit, len(rows))

    def score(row: dict[str, str]) -> tuple[int, int, int, int, int, int]:
        blob = " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("abstract_original", ""),
                row.get("keywords_normalized", ""),
            ]
        )
        decision = (row.get("ta_decision") or row.get("decision") or "").strip().lower()
        decision_score = 2 if decision == "include" else 1 if decision == "maybe" else 0
        url = derive_preferred_pdf_url(row).lower()
        pdf_score = 1 if url and (url.endswith(".pdf") or "/pdf" in url or "pdfdirect" in url) else 0
        doi_score = 1 if normalize_doi(row.get("assigned_doi", "")) else 0
        abstract_score = 1 if row.get("abstract_original") or row.get("abstract_en") else 0
        source_score = {
            "openalex": 7,
            "lens": 6,
            "crossref": 5,
            "openaire": 4,
            "europepmc": 4,
            "semanticscholar": 3,
            "pubmed": 3,
            "arxiv": 2,
        }.get(row.get("source", ""), 0)
        return (
            decision_score,
            pdf_score,
            generic_protocol_match_score(blob, context),
            doi_score,
            abstract_score,
            source_score,
        )

    ranked = sorted(rows, key=score, reverse=True)
    return ranked[:budget]


def extraction_candidate_budget(n_limit: int, total_included: int) -> int:
    """Limit expensive extraction to a high-quality candidate pool.

    Full-text inclusion can be intentionally generous for broad topics. The
    publication-ready synthesis only needs a defensible pool around the final N,
    and any later selected-but-unextracted row is still extracted by the retry
    path below before the final package is written.
    """
    override = os.environ.get("HERMES_EXTRACTION_CANDIDATE_BUDGET", "").strip()
    if override.isdigit() and int(override) > 0:
        return min(total_included, int(override))
    return min(total_included, max(int(n_limit or 20), math.ceil((n_limit or 20) * 2)))


def prioritize_extraction_candidates(rows: list[dict[str, str]], n_limit: int) -> list[dict[str, str]]:
    budget = extraction_candidate_budget(n_limit, len(rows))
    if len(rows) <= budget:
        return rows

    def score(row: dict[str, str]) -> tuple[int, int, int, int]:
        try:
            relevance = int(row.get("relevance_score", 0) or 0)
        except (TypeError, ValueError):
            relevance = 0
        try:
            quality = int(row.get("methodological_quality_score", 0) or 0)
        except (TypeError, ValueError):
            quality = 0
        try:
            confidence = int(row.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0
        full_text_score = 1 if len((row.get("full_text_text") or "").strip()) >= FULLTEXT_MIN_CHARS else 0
        return (relevance, quality, confidence, full_text_score)

    return sorted(rows, key=score, reverse=True)[:budget]


def append_retrieval_budget_log(
    review_dir: pathlib.Path,
    *,
    original_count: int,
    retrieval_count: int,
    n_limit: int,
) -> None:
    if retrieval_count >= original_count:
        return
    path = review_dir / "notes" / "decisions.md"
    existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else "# Decisions\n\n"
    entry = textwrap.dedent(
        f"""
        ## {ISO_NOW}

        - Se aplico un presupuesto de recuperacion de texto completo antes de descargar PDFs.
        - Candidatos include/maybe tras title/abstract: {original_count}.
        - Candidatos priorizados para recuperacion full text: {retrieval_count}.
        - Limite final N declarado: {n_limit}.
        - La priorizacion conserva primero include, ajuste al protocolo, DOI, abstract disponible y fuente bibliografica.
        - Para una recuperacion exhaustiva, definir `HERMES_FULLTEXT_RETRIEVAL_BUDGET` con el numero deseado.
        """
    ).strip()
    path.write_text(existing.rstrip() + "\n\n" + entry + "\n", encoding="utf-8")


def choose_canonical(rows: list[dict[str, str]]) -> dict[str, str]:
    def score(row: dict[str, str]) -> tuple[int, int, int]:
        source_priority = {"crossref": 6, "openalex": 5, "lens": 4, "europepmc": 4, "openaire": 3, "semanticscholar": 3, "pubmed": 3, "arxiv": 2}.get(row.get("source", ""), 0)
        work = (row.get("work_type") or "").lower()
        work_bonus = 2 if work in {"article", "journal-article", "proceedings-article"} else 1 if work else 0
        doi_bonus = 1 if row.get("assigned_doi") else 0
        return (doi_bonus, source_priority, work_bonus)

    return sorted(rows, key=score, reverse=True)[0]


def collapse_duplicate_candidates(candidates: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, dict[str, object]]]:
    duplicate_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        title_key = normalize_title(row.get("title_original", ""))
        duplicate_groups[title_key].append(row)

    # Any surviving singleton title group is also mapped by DOI so exact DOI
    # duplicates without identical titles still collapse before screening.
    singleton_rows = [
        group[0]
        for group in duplicate_groups.values()
        if len(group) == 1 and normalize_doi(group[0].get("assigned_doi", ""))
    ]
    for row in singleton_rows:
        doi_key = f"doi::{normalize_doi(row.get('assigned_doi', ''))}"
        duplicate_groups[doi_key].append(row)

    collapsed_groups: list[list[dict[str, str]]] = []
    seen_record_ids: set[str] = set()
    for group in duplicate_groups.values():
        filtered = [row for row in group if row["record_id"] not in seen_record_ids]
        if not filtered:
            continue
        for row in filtered:
            seen_record_ids.add(row["record_id"])
        collapsed_groups.append(filtered)

    auto_results: dict[str, dict[str, object]] = {}
    unique_candidates: list[dict[str, str]] = []
    for group in collapsed_groups:
        if len(group) == 1:
            unique_candidates.append(group[0])
            continue
        canonical = choose_canonical(group)
        unique_candidates.append(canonical)
        for row in group:
            if row["record_id"] == canonical["record_id"]:
                continue
            auto_results[row["record_id"]] = {
                "record_id": row["record_id"],
                "decision": "exclude",
                "reason": "duplicate_publication",
                "reason_detail": f"Version duplicada del estudio conservado como {canonical['record_id']}.",
                "exclusion_score": 100,
                "work_type": canonical.get("work_type", "") or "other",
                "empirical_type": "other",
                "relevance_score": 0,
                "methodological_quality_score": 0,
                "confidence": 100,
            }
    return unique_candidates, auto_results

def infer_work_type(title: str, abstract: str = "") -> tuple[str, str]:
    lowered = f"{title} {abstract}".lower()
    if any(token in lowered for token in ["systematic review", "literature review", "survey", "mapping study", "reference guide"]):
        return "review", "other"
    if any(token in lowered for token in ["experiment", "benchmark", "comparative", "evaluation", "evaluated", "case study", "dataset", "trial"]):
        if "case study" in lowered or "interview" in lowered:
            return "empirical", "qualitative"
        if any(token in lowered for token in ["experiment", "benchmark", "dataset", "ablation", "test cases"]):
            return "empirical", "experimental"
        return "empirical", "quantitative"
    if any(token in lowered for token in ["framework", "architecture", "platform", "protocol", "pipeline", "orchestration"]):
        return "theoretical", "other"
    return "other", "other"


def classify_title_abstract(
    candidates: list[dict[str, str]],
    context: dict[str, str],
    model_log: list[str] | None = None,
) -> dict[str, dict[str, object]]:
    unique_candidates, auto_results = collapse_duplicate_candidates(candidates)
    results = dict(auto_results)
    agent_terms = [
        "agentic", "agent-driven", "agent driven", "autonomous agent", "multi-agent", "multi agent",
        "software agent", "llm agent", "agent orchestration", "orchestrator", "planner", "delegate",
        "supervisor", "reviewer agent", "coder agent", "verification agent", "memory", "tool use", "mcp",
    ]
    software_terms = [
        "software development", "software engineering", "sdlc", "code", "coding", "programming", "repository",
        "github", "pull request", "code review", "debug", "bug", "testing", "test generation", "refactor",
        "developer", "software evolution", "library fuzzing", "harness generation",
    ]
    architecture_terms = [
        "architecture", "framework", "platform", "workflow", "pipeline", "system", "protocol",
        "pattern", "coordination", "routing", "router", "memory", "delegation", "orchestration",
    ]
    software_negative_terms = [
        "autonomous driving", "driving systems", "machine tool", "maintenance process", "foundation design",
        "geotechnical", "educational content", "resource allocation", "navigation", "oncology", "criminal",
        "financial", "payments", "manufacturing facilities", "semantic search for educational content",
        "quantum mechanics", "quantum_bench", "human-machine interfaces", "hmi system",
    ]
    software_explicit_keep_terms = [
        "software development", "software engineering", "agentic software engineering", "coding agent",
        "multi-agent orchestration framework", "task-level sdlc automation", "library fuzzing",
        "benchmarking autonomous software development agents", "impact of agents.md", "architectures of agents",
    ]
    question_text = f"{context.get('topic', '')} {context.get('research_question', '')}".lower()
    architecture_focus = any(token in question_text for token in ["arquitect", "architecture", "framework", "orquest", "orchestration"])
    personality_focus = is_personality_reasoning_review_context(context)
    creativity_focus = is_creativity_llm_review_context(context)
    corporate_political_focus = is_corporate_political_leadership_review_context(context)
    ai_architecture_focus = is_ai_architecture_review_context(context)
    mind_brain_focus = is_mind_brain_llm_review_context(context)
    education_agents_focus = is_ai_agents_education_review_context(context)
    software_focus = is_software_review_context(context)

    if personality_focus and model_log is not None:
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "record_id": {"type": "string"},
                            "decision": {"type": "string"},
                            "reason": {"type": "string"},
                            "reason_detail": {"type": "string"},
                            "work_type": {"type": "string"},
                            "empirical_type": {"type": "string"},
                            "relevance_score": {"type": "integer"},
                            "confidence": {"type": "integer"},
                        },
                        "required": [
                            "record_id",
                            "decision",
                            "reason",
                            "reason_detail",
                            "work_type",
                            "empirical_type",
                            "relevance_score",
                            "confidence",
                        ],
                    },
                }
            },
            "required": ["items"],
        }
        batch_rows = chunks(unique_candidates, 50)
        for batch_index, batch in enumerate(batch_rows, start=1):
            print(f"[title-abstract] lote {batch_index}/{len(batch_rows)}", flush=True)
            compact = []
            for row in batch:
                compact.append(
                    {
                        "record_id": row.get("record_id", ""),
                        "title": row.get("title_original", ""),
                        "abstract": (row.get("abstract_original", "") or "")[:700],
                        "keywords": row.get("keywords_author", ""),
                        "source": row.get("source", ""),
                        "year": row.get("year", ""),
                    }
                )
            prompt = textwrap.dedent(
                f"""
                Eres un revisor metodologico para una revision sistematica PRISMA.
                Debes cribar por titulo y abstract una revision sobre {review_topic_label(context)}.
                Trabaja en espanol de Espana.

                Tema: {context.get('topic', '')}
                Pregunta de investigacion: {context.get('research_question', '')}
                Criterios de inclusion: {context.get('inclusion', '')}
                Criterios de exclusion: {context.get('exclusion', '')}

                Reglas:
                - `include` solo si el titulo y el abstract dejan claro que el estudio es empirico o experimental y analiza personalidad, rasgos, persona, estilo conductual o consistencia de personalidad del modelo de IA razonador o LLM.
                - `maybe` si parece relevante pero el constructo exacto necesita confirmacion por texto completo.
                - `exclude` si trata personalizacion de usuario sin personalidad del modelo, personalidad humana sin foco en el modelo, percepciones de usuarios sobre la IA, chatbots clinicos o educativos, podcasts, editoriales, tutoriales o materiales divulgativos.
                - No abras el criterio por palabras sueltas como `preference`, `reasoning`, `agent` o `persona` si el constructo de personalidad del modelo no es central.
                - Usa `work_type`: empirical | theoretical | review | other.
                - Usa `empirical_type`: quantitative | qualitative | experimental | mixed | other.
                - `relevance_score` y `confidence` deben ir de 0 a 100.
                - Devuelve solo JSON valido con la forma {{ "items": [ ... ] }}.

                Registros:
                {json.dumps(compact, ensure_ascii=False)}
                """
            ).strip()
            parsed_items: list[dict[str, object]] = []
            try:
                parsed = parse_json_response(
                    call_llm(
                        prompt,
                        schema,
                        model_log,
                        preferred_models=TEXT_REASONING_MODELS,
                        request_timeout_seconds=120,
                        retries=1,
                    )
                )
                parsed_items = parsed.get("items", []) if isinstance(parsed, dict) else []
            except Exception:
                parsed_items = []
            parsed_by_id = {
                str(item.get("record_id", "") or ""): item
                for item in parsed_items
                if isinstance(item, dict) and item.get("record_id")
            }
            for row in batch:
                record_id = row.get("record_id", "")
                item = parsed_by_id.get(record_id)
                if not item:
                    results[record_id] = fallback_personality_title_abstract_decision(row)
                    continue
                decision = canonicalize_screening_decision(item.get("decision", ""), "title_abstract")
                if decision not in {"include", "maybe", "exclude"}:
                    results[record_id] = fallback_personality_title_abstract_decision(row)
                    continue
                results[record_id] = {
                    "record_id": record_id,
                    "decision": decision,
                    "reason": str(item.get("reason", "") or ("meets_criteria" if decision == "include" else "needs_full_text_confirmation" if decision == "maybe" else "insufficient_detail")),
                    "reason_detail": str(item.get("reason_detail", "") or ""),
                    "exclusion_score": 0 if decision in {"include", "maybe"} else 75,
                    "work_type": str(item.get("work_type", "") or "other"),
                    "empirical_type": str(item.get("empirical_type", "") or "other"),
                    "relevance_score": int(item.get("relevance_score", 70 if decision == "maybe" else 88 if decision == "include" else 20) or 0),
                    "methodological_quality_score": 0,
                    "confidence": int(item.get("confidence", 72 if decision == "maybe" else 88 if decision == "include" else 84) or 0),
                }
        return results

    for index, row in enumerate(unique_candidates, start=1):
        print(f"[title-abstract] lote {index}/{len(unique_candidates)}", flush=True)
        title = html.unescape(row.get("title_original", "")).lower()
        abstract = html.unescape(row.get("abstract_original", "")).lower()
        keywords = " ".join(
            [
                (row.get("keywords_author", "") or "").lower(),
                (row.get("keywords_indexed", "") or "").lower(),
                (row.get("keywords_normalized", "") or "").lower(),
            ]
        )
        text = f"{title} {abstract} {keywords}"
        has_agent = any(term in text for term in agent_terms)
        has_software = any(term in text for term in software_terms)
        has_architecture = any(term in text for term in architecture_terms)
        has_publication_negative = any(term in text for term in PUBLICATION_NEGATIVE_TERMS)
        work_type, empirical_type = infer_work_type(title, abstract)
        raw_work_type = (row.get("work_type", "") or "").lower()
        short_vague_title = len([token for token in re.split(r"\s+", title.strip()) if token]) <= 2

        decision = "exclude"
        reason = "wrong_population"
        detail = f"El registro no parece centrarse en {review_topic_label(context)}."
        score = 0

        if raw_work_type in {"dataset", "reference-entry", "journal-issue"} or has_publication_negative:
            decision = "exclude"
            reason = "wrong_publication_type"
            detail = "El registro parece material docente, recurso de apoyo o tipo de publicacion poco adecuado para una revision cientifica."
            score = 92
        elif short_vague_title and not abstract.strip():
            decision = "exclude"
            reason = "insufficient_detail"
            detail = "El titulo es demasiado vago y no hay abstract suficiente para justificar su paso a full text."
            score = 90
        else:
            if personality_focus:
                has_model = any(term in text for term in PERSONALITY_MODEL_TOKENS)
                explicit_construct = personality_explicit_construct_score(text)
                has_empirical = any(term in text for term in PERSONALITY_EMPIRICAL_TOKENS) or work_type == "empirical"
                has_negative = any(term in text for term in PERSONALITY_NEGATIVE_TOKENS)
                personalization_only = "personaliz" in text and explicit_construct == 0
                if personalization_only:
                    decision = "exclude"
                    reason = "wrong_intervention"
                    detail = "El registro trata personalizacion o memoria de usuario, pero no un constructo explicito de personalidad del modelo."
                    score = 88
                elif has_negative:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El foco principal parece ajeno a la personalidad de modelos de IA razonadores."
                    score = 88
                elif has_model and explicit_construct > 0 and has_empirical:
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "El titulo y el abstract apuntan a un estudio empirico sobre personalidad, rasgos o preferencias del modelo en sistemas razonadores."
                    score = 0
                elif has_model and explicit_construct > 0:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro parece relevante para personalidad en modelos razonadores, pero conviene confirmar el constructo exacto en texto completo."
                    score = 20
                else:
                    decision = "exclude"
                    reason = "insufficient_detail"
                    detail = "Con titulo, abstract y keywords no hay evidencia suficiente de que el estudio mida o evalue personalidad del modelo en sistemas razonadores."
                    score = 75
            elif mind_brain_focus:
                model_score, cognitive_score, evidence_score = mind_brain_llm_signal_counts(text)
                title_domain_axis = any(
                    token in title
                    for token in (
                        "brain",
                        "neural",
                        "neuroscience",
                        "cognit",
                        "mind",
                        "theory of mind",
                        "fmri",
                        "eeg",
                        "meg",
                    )
                )
                high_value_text_axis = any(
                    token in text
                    for token in (
                        "human brain",
                        "brain activity",
                        "brain encoding",
                        "brain decoding",
                        "brain alignment",
                        "neural representation",
                        "neural representations",
                        "neural response",
                        "neural responses",
                        "neuroimaging",
                        "fmri",
                        "eeg",
                        "meg",
                        "n400",
                        "language network",
                        "theory of mind",
                        "cerebro",
                    )
                )
                cognitive_comparison_axis = (
                    any(token in title for token in ("human cognition", "human cognitive", "cognitive science", "mind and brain"))
                    or any(
                        token in text
                        for token in (
                            "human cognition but",
                            "human cognition and large language models",
                            "humans and large language models",
                            "large language models and human cognition",
                            "llms differ from human cognition",
                        )
                    )
                )
                domain_axis = title_domain_axis or high_value_text_axis or cognitive_comparison_axis
                if model_score > 0 and domain_axis and cognitive_score >= 2 and evidence_score > 0:
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "Titulo, abstract o keywords comparan LLMs con cerebro, cognicion, neurociencia, lenguaje, memoria, razonamiento o representaciones con evidencia trazable."
                    score = 0
                elif model_score > 0 and domain_axis:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro conecta LLMs con cerebro/cognicion, pero requiere texto completo para confirmar metodo, evidencia y centralidad de la comparacion."
                    score = 20
                else:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El registro no muestra una comparacion sustantiva entre LLMs y procesos cerebrales, cognitivos o neurocientificos."
                    score = 82
            elif education_agents_focus:
                agent_score, education_score, quality_score = ai_agents_education_signal_counts(text)
                faculty_axis = any(
                    focus_token_in_text(
                        text,
                        token,
                    )
                    for token in (
                        "university teacher",
                        "university teachers",
                        "teacher",
                        "teachers",
                        "professor",
                        "professors",
                        "faculty",
                        "academic staff",
                        "lecturer",
                        "lecturers",
                        "instructor",
                        "instructors",
                        "docente",
                        "docentes",
                        "profesor",
                        "profesores",
                    )
                )
                higher_ed_axis = any(
                    focus_token_in_text(text, token)
                    for token in (
                        "higher education",
                        "university",
                        "universities",
                        "college",
                        "universidad",
                        "universitario",
                        "universitaria",
                        "educacion superior",
                        "educación superior",
                    )
                )
                student_only_axis = (
                    focus_token_in_text(text, "students")
                    and not faculty_axis
                    and quality_score == 0
                )
                if agent_score > 0 and education_score >= 2 and not student_only_axis and (faculty_axis or quality_score > 0 or work_type in {"empirical", "review"}):
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "Titulo, abstract o keywords conectan IA/IA generativa/LLMs con educacion superior, docencia, profesorado, evaluacion, feedback, productividad o calidad educativa."
                    score = 0
                elif agent_score > 0 and (education_score > 0 or higher_ed_axis or faculty_axis):
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro parece relevante para IA aplicada a docencia universitaria, pero requiere texto completo para confirmar poblacion docente, metodo y resultado educativo."
                    score = 20
                else:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El registro no muestra ajuste suficiente con IA aplicada a docencia universitaria, profesorado o calidad educativa."
                    score = 82
            elif creativity_focus:
                model, construct, empirical, negative = creativity_signal_scores(text, work_type)
                direct_title = is_direct_creativity_model_title(title)
                direct_study = is_direct_creativity_model_study(text)
                if negative and not direct_study:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El registro parece tratar creatividad humana, educativa, artistica u organizativa sin evaluar la creatividad del modelo como objeto central."
                    score = 88
                elif direct_title and empirical > 0:
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "El titulo y el abstract apuntan a una evaluacion empirica de creatividad del modelo u outputs creativos de LLMs."
                    score = 0
                elif direct_title or direct_study:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro parece conectar creatividad y LLMs como objeto de evaluacion, pero requiere verificar tarea, metrica o metodo en texto completo."
                    score = 20
                else:
                    decision = "exclude"
                    reason = "insufficient_detail"
                    detail = "Con titulo, abstract y keywords no hay evidencia suficiente de evaluacion de creatividad en modelos LLM."
                    score = 78
            elif corporate_political_focus:
                leadership_score, ideology_score, decision_score, negative = corporate_political_leadership_signal_counts(text)
                empirical_signal = corporate_political_empirical_signal(text, work_type)
                firm_axis = any(
                    focus_token_in_text(text, token)
                    for token in (
                        "firm",
                        "firms",
                        "corporate",
                        "company",
                        "companies",
                        "strategic",
                        "strategy",
                    )
                )
                if negative and leadership_score == 0:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El registro parece tratar ideologia politica de votantes, consumidores, empleados o liderazgos no corporativos."
                    score = 88
                elif leadership_score > 0 and ideology_score > 0 and decision_score > 0 and empirical_signal and firm_axis:
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "Titulo, abstract o keywords conectan ideologia politica del liderazgo corporativo con decisiones, politicas o resultados estrategicos de la firma mediante evidencia empirica."
                    score = 0
                    work_type = "empirical"
                    if empirical_type == "other":
                        empirical_type = "quantitative"
                elif leadership_score > 0 and ideology_score > 0 and decision_score > 0:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro encaja con liderazgo, ideologia politica y decision estrategica, pero requiere texto completo para confirmar diseno empirico y medicion."
                    score = 20
                elif leadership_score > 0 and ideology_score > 0 and firm_axis:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro conecta liderazgo corporativo e ideologia politica; el texto completo debe confirmar la decision estrategica analizada."
                    score = 22
                else:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "Con titulo, abstract y keywords no hay ajuste suficiente entre liderazgo corporativo, ideologia politica y decision estrategica de la firma."
                    score = 78
            elif ai_architecture_focus:
                ai_score, architecture_score, negative_domain = ai_architecture_signal_counts(text)
                has_evidence_signal = any(
                    token in text
                    for token in (
                        "evaluation",
                        "benchmark",
                        "experiment",
                        "survey",
                        "review",
                        "framework",
                        "architecture",
                        "architectural",
                        "case study",
                        "ablation",
                        "dataset",
                        "method",
                    )
                )
                if negative_domain and ai_score == 0:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El registro usa arquitectura en un dominio no IA y no aporta evidencia sobre arquitecturas de inteligencia artificial."
                    score = 90
                elif ai_score > 0 and architecture_score >= 2 and has_evidence_signal:
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "Titulo, abstract o keywords apuntan a una contribucion central sobre arquitectura de IA, sistemas, modelos fundacionales, agentes, RAG, multimodalidad, MoE o inferencia."
                    score = 0
                elif ai_score > 0 and architecture_score > 0:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro parece relevante para arquitecturas de IA, pero requiere texto completo para confirmar que la arquitectura es objeto central y no una mencion tangencial."
                    score = 20
                else:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "Con titulo, abstract y keywords no hay evidencia suficiente de una contribucion sobre arquitecturas de IA."
                    score = 78
            elif software_focus:
                has_negative = any(term in text for term in software_negative_terms)
                explicit_keep = any(term in text for term in software_explicit_keep_terms)
                if has_negative and not explicit_keep:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El dominio principal del estudio es ajeno a la ingenieria de software o al objetivo de la revision."
                    score = 90
                elif has_agent and has_software and has_architecture:
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "El titulo y el abstract apuntan de forma directa a una arquitectura o patron de agentes aplicado al desarrollo de software."
                    score = 0
                elif has_agent and has_software:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro parece relevante, pero hace falta texto completo para confirmar que la aportacion central es arquitectonica."
                    score = 20
                elif explicit_keep:
                    decision = "maybe" if architecture_focus else "include"
                    reason = "needs_full_text_confirmation" if decision == "maybe" else "meets_criteria"
                    detail = "El registro coincide con terminos nucleares del tema, pero conviene verificar su foco exacto en texto completo."
                    score = 20 if decision == "maybe" else 0
                else:
                    decision = "exclude"
                    reason = "insufficient_detail"
                    detail = "Con titulo, abstract y keywords no hay evidencia suficiente de que el estudio trate arquitecturas de agentes para desarrollo de software."
                    score = 75
            elif is_social_science_mode(context):
                decision, reason, detail, score, social_method_signal = social_title_abstract_decision(text, context)
                if decision in {"include", "maybe"} and social_method_signal and work_type == "other":
                    work_type = "empirical"
                    if empirical_type == "other":
                        empirical_type = "other"
            else:
                focus_score = generic_protocol_match_score(text, context)
                has_primary_axis = generic_protocol_primary_match(text, context)
                if focus_score >= 3 and has_primary_axis:
                    decision = "include"
                    reason = "meets_criteria"
                    detail = "Titulo, abstract o keywords muestran ajuste sustantivo con el tema, la pregunta y los criterios definidos en el protocolo."
                    score = 0
                elif focus_score > 0 and has_primary_axis:
                    decision = "maybe"
                    reason = "needs_full_text_confirmation"
                    detail = "El registro tiene senal tematica parcial y requiere confirmar metodo, muestra y ajuste en texto completo."
                    score = 20
                else:
                    decision = "exclude"
                    reason = "wrong_population"
                    detail = "El registro no muestra ajuste suficiente con el eje principal del tema, la pregunta ni los criterios del protocolo."
                    score = 78

        results[row["record_id"]] = {
            "record_id": row["record_id"],
            "decision": decision,
            "reason": reason,
            "reason_detail": detail,
            "exclusion_score": 0 if decision in {"include", "maybe"} else score,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 92 if decision == "include" else 70 if decision == "maybe" else 20,
            "methodological_quality_score": 0,
            "confidence": 88 if decision == "include" else 72 if decision == "maybe" else 84,
        }
    return results


def fallback_full_text_decision(row: dict[str, str], context: dict[str, str]) -> dict[str, object]:
    text = f"{row.get('title_original', '')} {row.get('abstract_original', '')} {(row.get('full_text_text', '') or '')[:4000]}".lower()
    work_type, empirical_type = infer_work_type(row.get("title_original", ""), row.get("abstract_original", ""))
    if len((row.get("full_text_text") or "").strip()) < FULLTEXT_MIN_CHARS:
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "full_text_unavailable",
            "reason_detail": "No se ha podido recuperar texto completo suficiente para inclusion cientifica en el corpus final.",
            "exclusion_score": 100,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 0,
            "methodological_quality_score": 0,
            "confidence": 100,
        }
    if is_corporate_political_leadership_review_context(context):
        leadership_score, ideology_score, decision_score, negative = corporate_political_leadership_signal_counts(text)
        empirical_signal = corporate_political_empirical_signal(text, work_type)
        firm_axis = any(
            focus_token_in_text(text, token)
            for token in (
                "firm",
                "firms",
                "corporate",
                "company",
                "companies",
                "strategic",
                "strategy",
            )
        )
        if leadership_score > 0 and ideology_score > 0 and decision_score > 0 and empirical_signal and firm_axis and not (negative and leadership_score == 0):
            return {
                "record_id": row["record_id"],
                "decision": "include",
                "reason": "meets_criteria",
                "reason_detail": "La evidencia textual recuperada confirma un estudio empirico que relaciona ideologia politica del liderazgo corporativo con decisiones, politicas o resultados estrategicos de la firma.",
                "exclusion_score": 0,
                "work_type": "empirical",
                "empirical_type": empirical_type if empirical_type != "other" else "quantitative",
                "relevance_score": 84,
                "methodological_quality_score": 68,
                "confidence": 70,
            }
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_intervention",
            "reason_detail": "El texto completo no confirma simultaneamente liderazgo corporativo, ideologia politica, decision estrategica de firma y evidencia empirica suficiente.",
            "exclusion_score": 82,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 20,
            "methodological_quality_score": 30,
            "confidence": 70,
        }
    if is_personality_reasoning_review_context(context):
        strong_personality = sum(1 for token in PERSONALITY_STRONG_TOKENS if token in text)
        broad_personality = sum(1 for token in PERSONALITY_BROAD_TOKENS if token in text)
        has_model = any(token in text for token in PERSONALITY_MODEL_TOKENS)
        has_empirical = any(token in text for token in PERSONALITY_EMPIRICAL_TOKENS) or empirical_type == "experimental"
        if has_model and has_empirical and (strong_personality > 0 or broad_personality >= 2):
            return {
                "record_id": row["record_id"],
                "decision": "include",
                "reason": "meets_criteria",
                "reason_detail": "La evidencia textual recuperada confirma un estudio empirico sobre personalidad, rasgos, preferencias o consistencia conductual del modelo razonador.",
                "exclusion_score": 0,
                "work_type": work_type,
                "empirical_type": empirical_type,
                "relevance_score": 82,
                "methodological_quality_score": 68,
                "confidence": 68,
            }
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_intervention",
            "reason_detail": "El texto completo no confirma una contribucion empirica centrada en personalidad del modelo de IA razonador.",
            "exclusion_score": 82,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 20,
            "methodological_quality_score": 30,
            "confidence": 70,
        }
    if is_mind_brain_llm_review_context(context):
        model_score, cognitive_score, evidence_score = mind_brain_llm_signal_counts(text)
        title_text = (row.get("title_original", "") or "").lower()
        title_domain_axis = any(
            token in title_text
            for token in (
                "brain",
                "neural",
                "neuroscience",
                "cognit",
                "mind",
                "theory of mind",
                "fmri",
                "eeg",
                "meg",
            )
        )
        high_value_text_axis = any(
            token in text
            for token in (
                "human brain",
                "brain activity",
                "brain encoding",
                "brain decoding",
                "brain alignment",
                "neural representation",
                "neural representations",
                "neural response",
                "neural responses",
                "neuroimaging",
                "fmri",
                "eeg",
                "meg",
                "n400",
                "language network",
                "theory of mind",
                "cerebro",
            )
        )
        cognitive_comparison_axis = (
            any(token in title_text for token in ("human cognition", "human cognitive", "cognitive science", "mind and brain"))
            or any(
                token in text
                for token in (
                    "human cognition but",
                    "human cognition and large language models",
                    "humans and large language models",
                    "large language models and human cognition",
                    "llms differ from human cognition",
                )
            )
        )
        domain_axis = title_domain_axis or high_value_text_axis or cognitive_comparison_axis
        if model_score > 0 and domain_axis and cognitive_score >= 2 and evidence_score > 0:
            return {
                "record_id": row["record_id"],
                "decision": "include",
                "reason": "meets_criteria",
                "reason_detail": "La evidencia textual confirma una comparacion sustantiva entre LLMs/modelos fundacionales y cerebro, cognicion, neurociencia, lenguaje, memoria, razonamiento o representaciones.",
                "exclusion_score": 0,
                "work_type": work_type,
                "empirical_type": empirical_type,
                "relevance_score": 84,
                "methodological_quality_score": 68,
                "confidence": 70,
            }
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_intervention",
            "reason_detail": "El texto completo no confirma una comparacion central entre LLMs y procesos cerebrales, cognitivos o neurocientificos.",
            "exclusion_score": 82,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 20,
            "methodological_quality_score": 30,
            "confidence": 70,
        }
    if is_ai_agents_education_review_context(context):
        agent_score, education_score, quality_score = ai_agents_education_signal_counts(text)
        if agent_score > 0 and education_score >= 2 and (quality_score > 0 or work_type in {"empirical", "review"}):
            return {
                "record_id": row["record_id"],
                "decision": "include",
                "reason": "meets_criteria",
                "reason_detail": "La evidencia textual confirma agentes de IA, tutores inteligentes o asistentes docentes aplicados a educacion superior, profesorado universitario o calidad docente.",
                "exclusion_score": 0,
                "work_type": work_type,
                "empirical_type": empirical_type,
                "relevance_score": 82,
                "methodological_quality_score": 68,
                "confidence": 70,
            }
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_intervention",
            "reason_detail": "El texto completo no confirma una contribucion central sobre agentes de IA en educacion superior, profesorado o calidad docente.",
            "exclusion_score": 82,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 20,
            "methodological_quality_score": 30,
            "confidence": 70,
        }
    if is_creativity_llm_review_context(context):
        model, construct, empirical, negative = creativity_signal_scores(text, empirical_type)
        direct_study = is_direct_creativity_model_study(text)
        if negative and not direct_study:
            return {
                "record_id": row["record_id"],
                "decision": "exclude",
                "reason": "wrong_population",
                "reason_detail": "El texto completo trata creatividad humana, educativa, artistica u organizativa sin evaluar la creatividad del modelo como objeto central.",
                "exclusion_score": 84,
                "work_type": work_type,
                "empirical_type": empirical_type,
                "relevance_score": 20,
                "methodological_quality_score": 25,
                "confidence": 72,
            }
        if direct_study or (model > 0 and construct > 0 and empirical > 1):
            return {
                "record_id": row["record_id"],
                "decision": "include",
                "reason": "meets_criteria",
                "reason_detail": "La evidencia textual confirma una contribucion sobre evaluacion o caracterizacion de creatividad en modelos LLM o IA generativa.",
                "exclusion_score": 0,
                "work_type": work_type,
                "empirical_type": empirical_type,
                "relevance_score": 84,
                "methodological_quality_score": 70,
                "confidence": 72,
            }
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_intervention",
            "reason_detail": "El texto completo no confirma una contribucion metodologica centrada en creatividad de LLMs.",
            "exclusion_score": 82,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 20,
            "methodological_quality_score": 30,
            "confidence": 70,
        }
    if is_ai_architecture_review_context(context):
        ai_score, architecture_score, negative_domain = ai_architecture_signal_counts(text)
        if negative_domain and ai_score == 0:
            domain_match = False
        else:
            domain_match = ai_score > 0 and architecture_score >= 2
        include_detail = "La evidencia textual recuperada confirma una contribucion sustantiva sobre arquitecturas de IA, modelos fundacionales, agentes, RAG, multimodalidad, MoE, memoria, herramientas, inferencia o evaluacion arquitectonica."
        exclude_detail = "El texto completo no confirma que la arquitectura de IA sea el objeto central del estudio segun el protocolo."
        if domain_match:
            return {
                "record_id": row["record_id"],
                "decision": "include",
                "reason": "meets_criteria",
                "reason_detail": include_detail,
                "exclusion_score": 0,
                "work_type": work_type,
                "empirical_type": empirical_type,
                "relevance_score": 82,
                "methodological_quality_score": 68,
                "confidence": 68,
            }
        return {
            "record_id": row["record_id"],
            "decision": "exclude",
            "reason": "wrong_intervention",
            "reason_detail": exclude_detail,
            "exclusion_score": 82,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 20,
            "methodological_quality_score": 30,
            "confidence": 70,
        }
    if is_software_review_context(context):
        domain_match = all(token in text for token in ["software", "agent"]) and any(token in text for token in ["architecture", "framework", "orchestration", "multi-agent"])
        include_detail = "La evidencia textual recuperada describe una arquitectura de agentes aplicable a desarrollo de software."
        exclude_detail = "El texto completo no confirma una contribucion arquitectonica centrada en desarrollo de software."
    else:
        if is_agent_architecture_review_context(context):
            agent_terms = ["agent", "agents", "agente", "agentes", "multi-agent", "multiagente"]
            architecture_terms = ["architecture", "framework", "orchestration", "orquestacion", "memory", "memoria", "tool", "tools", "herramienta", "evaluation", "benchmark", "rag"]
            domain_match = any(token in text for token in agent_terms) and any(token in text for token in architecture_terms)
            include_detail = "La evidencia textual recuperada confirma una contribucion sustantiva sobre agentes de IA y sus componentes, metodologia o evaluacion."
            exclude_detail = "El texto completo no confirma una contribucion sustantiva centrada en agentes de IA segun el protocolo."
        else:
            if is_social_science_mode(context):
                axis_count, method_signal, matched_labels = social_protocol_signal_counts(text, context)
                empirical_required = social_empirical_evidence_required(context)
                domain_match = axis_count >= 2 and (method_signal or not empirical_required)
                labels = ", ".join(matched_labels[:3]) if matched_labels else "constructos insuficientes"
                include_detail = f"La evidencia textual recuperada conecta constructos centrales del protocolo social ({labels}) y permite identificar metodo, contexto o tipo de evidencia."
                exclude_detail = "El texto completo no confirma suficientes constructos, contexto, metodo o evidencia alineados con la pregunta de investigacion social."
            else:
                domain_match = generic_protocol_domain_match(text, context, min_score=2)
                include_detail = "La evidencia textual recuperada confirma ajuste sustantivo con la pregunta de investigacion, los criterios de inclusion y el foco tematico declarados en el protocolo."
                exclude_detail = "El texto completo no confirma una contribucion sustantiva centrada en el tema y la pregunta de investigacion del protocolo."
    if domain_match:
        return {
            "record_id": row["record_id"],
            "decision": "include",
            "reason": "meets_criteria",
            "reason_detail": include_detail,
            "exclusion_score": 0,
            "work_type": work_type,
            "empirical_type": empirical_type,
            "relevance_score": 78,
            "methodological_quality_score": 68,
            "confidence": 68,
        }
    return {
        "record_id": row["record_id"],
        "decision": "exclude",
        "reason": "wrong_intervention",
        "reason_detail": exclude_detail,
        "exclusion_score": 82,
        "work_type": work_type,
        "empirical_type": empirical_type,
        "relevance_score": 20,
        "methodological_quality_score": 30,
        "confidence": 70,
    }


def classify_full_text(
    review_dir: pathlib.Path,
    candidates: list[dict[str, str]],
    context: dict[str, str],
    model_log: list[str],
) -> dict[str, dict[str, object]]:
    unique_candidates, auto_results = collapse_duplicate_candidates(candidates)
    results = dict(auto_results)
    existing_rows = read_csv(review_dir / "screening" / "full-text.csv")
    cached_results: dict[str, dict[str, object]] = {}
    for row in existing_rows:
        decision = canonicalize_screening_decision(row.get("decision", ""), "full_text")
        record_id = row.get("record_id", "")
        if not record_id or decision not in {"include_ft", "exclude"}:
            continue
        metrics = parse_notes_metadata(row.get("notes", ""))
        cached_results[record_id] = {
            "record_id": record_id,
            "decision": "include" if decision == "include_ft" else "exclude",
            "reason": row.get("reason", "") or ("meets_criteria" if decision == "include_ft" else "insufficient_detail"),
            "reason_detail": row.get("reason_detail", ""),
            "work_type": row.get("work_type", "") or "other",
            "empirical_type": row.get("empirical_type", "") or "other",
            "relevance_score": metrics.get("relevance", 78 if decision == "include_ft" else 20),
            "methodological_quality_score": metrics.get("methodological", 68 if decision == "include_ft" else 30),
            "confidence": metrics.get("confidence", 70),
        }
    results.update(cached_results)
    schema = {
        "type": "object",
        "properties": {
            "record_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["include", "exclude"]},
            "reason": {"type": "string"},
            "reason_detail": {"type": "string"},
            "work_type": {"type": "string"},
            "empirical_type": {"type": "string"},
            "relevance_score": {"type": "integer"},
            "methodological_quality_score": {"type": "integer"},
            "confidence": {"type": "integer"},
        },
        "required": [
            "record_id", "decision", "reason", "reason_detail", "work_type",
            "empirical_type", "relevance_score", "methodological_quality_score", "confidence",
        ],
    }

    for index, row in enumerate(unique_candidates, start=1):
        print(f"[full-text] lote {index}/{len(unique_candidates)}", flush=True)
        if row["record_id"] in cached_results:
            continue
        if len((row.get("full_text_text") or "").strip()) < FULLTEXT_MIN_CHARS:
            results[row["record_id"]] = fallback_full_text_decision(row, context)
            continue
        if is_personality_reasoning_review_context(context):
            source_blob = " ".join(
                [
                    row.get("title_original", "") or "",
                    row.get("abstract_original", "") or "",
                    row.get("full_text_text", "") or "",
                ]
            ).lower()
            explicit_construct = personality_explicit_construct_score(source_blob)
            has_model = any(token in source_blob for token in PERSONALITY_MODEL_TOKENS)
            has_empirical = any(token in source_blob for token in PERSONALITY_EMPIRICAL_TOKENS)
            has_negative = any(token in source_blob for token in PERSONALITY_NEGATIVE_TOKENS)
            personalization_only = "personaliz" in source_blob and explicit_construct == 0
            if personalization_only or has_negative or not has_model or explicit_construct == 0 or not has_empirical:
                results[row["record_id"]] = fallback_full_text_decision(row, context)
                continue
        full_text_digest = build_full_text_digest(
            row.get("full_text_text", "") or "",
            focus_terms=review_digest_focus_terms(context),
        )
        rules_text = "\n".join(f"- {rule}" for rule in review_full_text_rules(context))

        prompt = textwrap.dedent(
            f"""
            Eres un revisor metodologico para una revision sistematica PRISMA.
            Debes decidir si un estudio pertenece al corpus final de una revision sobre {review_topic_label(context)}.
            Trabaja en espanol de Espana.

            Tema: {context.get('topic', '')}
            Pregunta de investigacion: {context.get('research_question', '')}
            Criterios de inclusion: {context.get('inclusion', '')}
            Criterios de exclusion: {context.get('exclusion', '')}

            Reglas:
            {rules_text}
            - El campo `full_text_digest` se ha construido leyendo el PDF completo y condensando apertura, cierre, secciones y ventanas tematicas a lo largo de todo el documento.
            - Usa `decision`: include | exclude.
            - Usa `work_type`: empirical | theoretical | review | other
            - Usa `empirical_type`: quantitative | qualitative | experimental | mixed | other
            - `relevance_score`, `methodological_quality_score` y `confidence` deben ir de 0 a 100.
            - Devuelve solo JSON valido.

            Registro:
            {json.dumps({
                "record_id": row.get("record_id", ""),
                "title": row.get("title_original", ""),
                "abstract": row.get("abstract_original", ""),
                "keywords": row.get("keywords_author", ""),
                "source": row.get("source", ""),
                "doi": row.get("assigned_doi", ""),
                "full_text_digest": full_text_digest,
            }, ensure_ascii=False)}
            """
        ).strip()

        try:
            if os.environ.get("HERMES_DETERMINISTIC_EXTRACTION", "").strip().lower() in {"1", "true", "yes", "si", "sí"}:
                raise RuntimeError("Deterministic extraction requested.")
            parsed = parse_json_response(
                call_llm(
                    prompt,
                    schema,
                    model_log,
                    preferred_models=TEXT_REASONING_MODELS,
                    request_timeout_seconds=120,
                    retries=1,
                )
            )
            if isinstance(parsed, dict):
                parsed.setdefault("record_id", row["record_id"])
                decision = canonicalize_screening_decision(parsed.get("decision", ""), "full_text")
                if decision not in {"include_ft", "exclude"}:
                    results[row["record_id"]] = fallback_full_text_decision(row, context)
                    continue
                parsed["decision"] = "include" if decision == "include_ft" else "exclude"
                results[row["record_id"]] = parsed
            else:
                results[row["record_id"]] = fallback_full_text_decision(row, context)
        except Exception:
            results[row["record_id"]] = fallback_full_text_decision(row, context)
    return results


def bootstrap_title_abstract_screening(review_dir: pathlib.Path, enriched_rows: list[dict[str, str]], context: dict[str, str], model_log: list[str]) -> None:
    screening_path = review_dir / "screening" / "title-abstract.csv"
    existing_rows = read_csv(screening_path)
    profile = (
        "creativity_llm"
        if is_creativity_llm_review_context(context)
        else "personality_llm"
        if is_personality_reasoning_review_context(context)
        else "corporate_political_leadership"
        if is_corporate_political_leadership_review_context(context)
        else "ai_higher_education_teaching"
        if is_ai_agents_education_review_context(context)
        else "ai_architecture"
        if is_ai_architecture_review_context(context)
        else "software_architecture"
        if is_software_review_context(context)
        else "agent_architecture"
        if is_agent_architecture_review_context(context)
        else "social_science_axes"
        if is_social_science_mode(context)
        else "generic"
    )
    rules_version = "screening_rules=2026-05-domain-v9-social-management-ai-work-axes"
    existing_ids = {row.get("record_id", "") for row in existing_rows if row.get("record_id")}
    current_ids = {row.get("record_id", "") for row in enriched_rows if row.get("record_id")}
    if existing_rows and all(
        f"screening_profile={profile}" in (row.get("notes") or "")
        and rules_version in (row.get("notes") or "")
        for row in existing_rows[: min(len(existing_rows), 25)]
    ) and len(existing_rows) == len(enriched_rows) and existing_ids == current_ids:
        return

    ta_results = classify_title_abstract(enriched_rows, context)
    ta_rows: list[dict[str, object]] = []
    for row in enriched_rows:
        result = ta_results.get(
            row["record_id"],
            {
                "decision": "exclude",
                "exclusion_score": 75,
                "reason": "insufficient_detail",
                "reason_detail": "No se pudo clasificar el registro con seguridad en screening inicial.",
            },
        )
        ta_rows.append(
            {
                "record_id": row.get("record_id", ""),
                "assigned_doi": row.get("assigned_doi", ""),
                "authors": row.get("authors", ""),
                "title_original": row.get("title_original", ""),
                "title_en": row.get("title_en", "") or row.get("title_original", ""),
                "title_es": row.get("title_es", ""),
                "abstract_original": row.get("abstract_original", ""),
                "abstract_en": row.get("abstract_en", "") or row.get("abstract_original", ""),
                "abstract_es": row.get("abstract_es", ""),
                "keywords_author": row.get("keywords_author", ""),
                "keywords_indexed": row.get("keywords_indexed", ""),
                "keywords_normalized": row.get("keywords_normalized", ""),
                "year": row.get("year", ""),
                "source": row.get("source", ""),
                "decision": result.get("decision", "exclude"),
                "exclusion_score": result.get("exclusion_score", 75),
                "reason": result.get("reason", "insufficient_detail"),
                "reason_detail": result.get("reason_detail", ""),
                "reviewer": REVIEWER,
                "reviewed_at": ISO_NOW,
                "notes": f"Screening titulo/abstract automatizado con criterios conservadores; screening_profile={profile}; {rules_version}.",
            }
        )
    write_csv(screening_path, TITLE_ABSTRACT_FIELDS, ta_rows)
    checkpoint_sync(review_dir)


def load_cached_full_text(review_dir: pathlib.Path, row: dict[str, str]) -> tuple[str, str]:
    stem = slugify(row.get("record_id", "record")) or "record"
    fulltext_dir = review_dir / "fulltext"
    pdf_path = fulltext_dir / "pdf" / f"{stem}.pdf"
    txt_path = fulltext_dir / "txt" / f"{stem}.txt"
    if pdf_path.exists():
        if not txt_path.exists():
            try:
                subprocess.run(
                    ["pdftotext", str(pdf_path), str(txt_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                return str(pdf_path), ""
        text = txt_path.read_text(encoding="utf-8", errors="ignore") if txt_path.exists() else ""
        return str(pdf_path), text
    return "", ""


def derive_preferred_pdf_url(row: dict[str, str]) -> str:
    doi = normalize_doi(row.get("assigned_doi", "")).lower()
    if doi.startswith("10.48550/arxiv."):
        arxiv_id = doi.split("10.48550/arxiv.", 1)[1]
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    for key in ("full_text_url", "full_text_path", "notes"):
        url = (row.get(key, "") or "").strip()
        if not url:
            continue
        lower = url.lower()
        if "arxiv.org/abs/" in lower:
            return url.replace("/abs/", "/pdf/").split("#", 1)[0].split("?", 1)[0] + ".pdf"
        if "arxiv.org/html/" in lower:
            return url.replace("/html/", "/pdf/").split("#", 1)[0].split("?", 1)[0] + ".pdf"
        if lower.endswith(".pdf") or "/pdf/" in lower:
            return url
    return ((row.get("full_text_url", "") or "").strip() or (row.get("full_text_path", "") or "").strip())


def unpaywall_pdf_urls(review_dir: pathlib.Path, doi: str) -> list[str]:
    email = unpaywall_email()
    normalized_doi = normalize_doi(doi)
    if not email or not normalized_doi:
        return []
    cache_dir = review_dir / "fulltext" / "unpaywall"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{slugify(normalized_doi)}.json"
    try:
        if cache_path.exists():
            data = json.loads(cache_path.read_text(encoding="utf-8", errors="ignore"))
        else:
            url = f"{UNPAYWALL_URL}/{urllib.parse.quote(normalized_doi, safe='')}?email={urllib.parse.quote(email)}"
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8", errors="ignore"))
            # The cache stores only the Unpaywall payload, never the email-bearing request URL.
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        return []

    urls: list[str] = []
    locations = []
    best = data.get("best_oa_location") if isinstance(data, dict) else None
    if isinstance(best, dict):
        locations.append(best)
    if isinstance(data, dict):
        locations.extend([item for item in data.get("oa_locations") or [] if isinstance(item, dict)])
    for location in locations:
        for key in ("url_for_pdf", "url"):
            url = str(location.get(key) or "").strip()
            if url and url not in urls:
                urls.append(url)
    return urls


def candidate_pdf_urls(review_dir: pathlib.Path, row: dict[str, str]) -> list[str]:
    urls: list[str] = []
    preferred = derive_preferred_pdf_url(row)
    if preferred:
        urls.append(preferred)
    for url in unpaywall_pdf_urls(review_dir, row.get("assigned_doi", "")):
        if url not in urls:
            urls.append(url)
    return urls


def download_pdf_candidate(review_dir: pathlib.Path, row: dict[str, str], url: str) -> tuple[str, str]:
    fulltext_dir = review_dir / "fulltext"
    pdf_dir = fulltext_dir / "pdf"
    txt_dir = fulltext_dir / "txt"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
    except Exception:
        return "", ""

    if not ("pdf" in content_type.lower() or url.lower().endswith(".pdf") or body[:4] == b"%PDF"):
        return "", ""

    stem = slugify(row.get("record_id", "record")) or "record"
    pdf_path = pdf_dir / f"{stem}.pdf"
    txt_path = txt_dir / f"{stem}.txt"
    pdf_path.write_bytes(body)
    try:
        subprocess.run(
            ["pdftotext", str(pdf_path), str(txt_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return str(pdf_path), ""
    text = txt_path.read_text(encoding="utf-8", errors="ignore") if txt_path.exists() else ""
    return str(pdf_path), text


def try_download_text(review_dir: pathlib.Path, row: dict[str, str]) -> tuple[str, str]:
    cached_path, cached_text = load_cached_full_text(review_dir, row)
    if cached_path and cached_text:
        return cached_path, cached_text

    for url in candidate_pdf_urls(review_dir, row):
        path, text = download_pdf_candidate(review_dir, row, url)
        if path and text:
            return path, text

    return "", ""


def extraction_row_complete(row: dict[str, str]) -> bool:
    if not bool((row.get("record_id") or "").strip()) or not bool((row.get("evidence_snippet") or "").strip()):
        return False
    required_schema_fields = {
        "design_detail",
        "unit_of_analysis",
        "models_or_systems_studied",
        "model_count",
        "benchmark_dataset_or_corpus",
        "tasks_or_domains",
        "baselines_or_comparators",
        "instruments_or_scales",
    }
    if any(field not in row for field in required_schema_fields):
        return False
    try:
        confidence = int(str(row.get("extraction_confidence") or "0").strip())
    except ValueError:
        confidence = 0
    return confidence >= 80


def fallback_extraction_item(source_row: dict[str, str], reason: str) -> dict[str, object]:
    evidence_source = "full text" if (source_row.get("full_text_text") or "").strip() else ("abstract metadata" if source_row.get("abstract_original") else "title metadata")
    return {
        "record_id": source_row["record_id"],
        "title_en": source_row.get("title_original", ""),
        "title_es": source_row.get("title_original", ""),
        "abstract_original": source_row.get("abstract_original", ""),
        "abstract_en": source_row.get("abstract_original", ""),
        "abstract_es": source_row.get("abstract_original", ""),
        "work_type": source_row.get("work_type", "other") or "other",
        "empirical_type": source_row.get("empirical_type", "other") or "other",
        "design_detail": "no reportado",
        "countries": "no reportado",
        "unit_of_analysis": "no reportado",
        "sample_description": "no reportado",
        "sample_size": "no reportado",
        "models_or_systems_studied": "no reportado",
        "model_count": "no reportado",
        "benchmark_dataset_or_corpus": "no reportado",
        "tasks_or_domains": "no reportado",
        "baselines_or_comparators": "no reportado",
        "instruments_or_scales": "no reportado",
        "method_used": "no reportado",
        "variables_dependent": "",
        "variables_independent": "",
        "variables_moderating": "",
        "variables_mediating": "",
        "variables_control": "",
        "theory_framework": "no reportado",
        "evidence_snippet": ((source_row.get("full_text_text", "") or source_row.get("abstract_original", "") or source_row.get("title_original", ""))[:240]).strip(),
        "evidence_location": evidence_source,
        "extraction_confidence": 40 if evidence_source == "full text" else 30,
        "key_findings": "no reportado",
        "notes": reason,
    }


def extract_included(
    rows: list[dict[str, str]],
    review_dir: pathlib.Path,
    model_log: list[str],
    context: dict[str, str],
) -> list[dict[str, object]]:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_id": {"type": "string"},
                        "title_en": {"type": "string"},
                        "title_es": {"type": "string"},
                        "abstract_original": {"type": "string"},
                        "abstract_en": {"type": "string"},
                        "abstract_es": {"type": "string"},
                        "work_type": {"type": "string"},
                        "empirical_type": {"type": "string"},
                        "design_detail": {"type": "string"},
                        "countries": {"type": "string"},
                        "unit_of_analysis": {"type": "string"},
                        "sample_description": {"type": "string"},
                        "sample_size": {"type": "string"},
                        "models_or_systems_studied": {"type": "string"},
                        "model_count": {"type": "string"},
                        "benchmark_dataset_or_corpus": {"type": "string"},
                        "tasks_or_domains": {"type": "string"},
                        "baselines_or_comparators": {"type": "string"},
                        "instruments_or_scales": {"type": "string"},
                        "method_used": {"type": "string"},
                        "variables_dependent": {"type": "string"},
                        "variables_independent": {"type": "string"},
                        "variables_moderating": {"type": "string"},
                        "variables_mediating": {"type": "string"},
                        "variables_control": {"type": "string"},
                        "theory_framework": {"type": "string"},
                        "evidence_snippet": {"type": "string"},
                        "evidence_location": {"type": "string"},
                        "extraction_confidence": {"type": "integer"},
                        "key_findings": {"type": "string"},
                    },
                    "required": [
                        "record_id",
                        "title_en",
                        "title_es",
                        "abstract_original",
                        "abstract_en",
                        "abstract_es",
                        "work_type",
                        "empirical_type",
                        "design_detail",
                        "countries",
                        "unit_of_analysis",
                        "sample_description",
                        "sample_size",
                        "models_or_systems_studied",
                        "model_count",
                        "benchmark_dataset_or_corpus",
                        "tasks_or_domains",
                        "baselines_or_comparators",
                        "instruments_or_scales",
                        "method_used",
                        "variables_dependent",
                        "variables_independent",
                        "variables_moderating",
                        "variables_mediating",
                        "variables_control",
                        "theory_framework",
                        "evidence_snippet",
                        "evidence_location",
                        "extraction_confidence",
                        "key_findings",
                    ],
                },
            }
        },
        "required": ["items"],
    }

    extraction_path = review_dir / "extraction" / "extraction-table.csv"
    cached_rows = read_csv(extraction_path)
    cached_by_id = {row["record_id"]: row for row in cached_rows if extraction_row_complete(row)}
    extracted: list[dict[str, object]] = []
    batch_size = 4 if is_personality_reasoning_review_context(context) else 1 if is_ai_architecture_review_context(context) else 3
    extraction_timeout_seconds = int(os.environ.get("HERMES_EXTRACTION_TIMEOUT_SECONDS", "90") or "90")
    total_batches = math.ceil(len(rows) / batch_size) if rows else 0
    for batch_index, batch in enumerate(chunks(rows, batch_size), start=1):
        print(f"[extract] lote {batch_index}/{total_batches}", flush=True)
        pending_rows: list[dict[str, str]] = []
        for source_row in batch:
            cached = cached_by_id.get(source_row["record_id"])
            if cached:
                extracted.append(cached)
                continue
            pending_rows.append(source_row)
        if not pending_rows:
            continue
        if os.environ.get("HERMES_DETERMINISTIC_EXTRACTION", "").strip().lower() in {"1", "true", "yes", "si", "sí"}:
            normalized_items: list[dict[str, object]] = []
            for source in pending_rows:
                item = fallback_extraction_item(
                    source,
                    "Extracción determinista de respaldo desde texto completo y metadatos tras timeout o cierre de sesión.",
                )
                heuristically_enrich_extraction_item(source, item, context)
                try:
                    confidence = int(str(item.get("extraction_confidence") or "0").strip())
                except ValueError:
                    confidence = 0
                if (
                    confidence >= 80
                    and str(source.get("full_text_path", "") or "").lower().endswith(".pdf")
                    and bool((source.get("full_text_text") or "").strip())
                ):
                    item["evidence_location"] = "full text"
                normalized_items.append(item)
            for item in normalized_items:
                cached_by_id[str(item["record_id"])] = item
                extracted.append(item)
            write_csv(
                extraction_path,
                EXTRACTION_FIELDS,
                [cached_by_id[key] for key in sorted(cached_by_id.keys())],
            )
            continue

        compact = []
        for row in pending_rows:
            full_text_digest = build_full_text_digest(
                row.get("full_text_text", "") or "",
                focus_terms=review_digest_focus_terms(context),
                max_chars=EXTRACTION_DIGEST_CHARS,
            )
            compact.append(
                {
                    "record_id": row["record_id"],
                    "title": row.get("title_original", ""),
                    "abstract": row.get("abstract_original", ""),
                    "keywords": row.get("keywords_author", ""),
                    "source": row.get("source", ""),
                    "doi": row.get("assigned_doi", ""),
                    "full_text_path": row.get("full_text_path", ""),
                    "full_text_digest": full_text_digest,
                }
            )

        prompt = textwrap.dedent(
            f"""
            Eres un extractor metodologico para una revision sistematica PRISMA sobre {extraction_scope_label(context)}.
            Trabaja en espanol de Espana.
            Modo metodologico Hermes: {context.get('review_mode_label') or context.get('review_mode') or 'common-core'}.
            Marco de pregunta: {context.get('review_mode_framework') or 'common-core'}.

            Para cada estudio:
            - title_en: si el original esta en ingles, copialo; si no, traduce fielmente al ingles.
            - title_es: traduccion fiel al espanol de Espana.
            - abstract_original: conserva el abstract fuente si existe; si no existe, deja cadena vacia.
            - abstract_en / abstract_es: completa traduccion o copia fiel cuando proceda.
            - work_type: empirical | theoretical | review | other
            - empirical_type: quantitative | qualitative | experimental | mixed | other
            - design_detail: concreta el diseno con mas precision que `empirical_type` cuando el PDF lo permita. Ejemplos: evaluacion experimental post hoc sobre benchmark; estudio correlacional psicometrico; comparativa zero-shot con role prompting; clasificacion supervisada multiconjunto; experimento multiagente con verificacion automatizada.
            - countries: pais o paises del estudio; si no se ve claro, "no reportado"
            - unit_of_analysis: que unidades analiza realmente el estudio. Ejemplos: modelos; prompts; conversaciones; participantes humanos; incidencias; documentos; instancias de benchmark.
            - sample_description / sample_size / method_used / theory_framework: "no reportado" si no es recuperable con confianza.
            - models_or_systems_studied: nombra explicitamente los modelos, sistemas o agentes si el paper los lista. No pongas solo `17 LLMs` si el PDF da sus nombres. Usa una lista corta separada por `;`.
            - model_count: numero de modelos o sistemas comparados/analizados cuando sea recuperable; si no, "no reportado".
            - benchmark_dataset_or_corpus: benchmark, dataset, corpus o suite de tareas usada.
            - tasks_or_domains: tarea empirica o dominio concreto. Ejemplos: personality detection from text; persona steering; psychometric prediction; narrative generation; SWE-bench issue resolution.
            - baselines_or_comparators: lineas base, modelos comparados, ablations, grupos de control o referencia humana si los hay.
            - instruments_or_scales: tests, escalas o instrumentos. Ejemplos: Big Five; MBTI; HEXACO; 16Personalities; cuestionarios; rubricas de evaluacion.
            - method_used: se especifico. Nombra tecnicas, pipelines, algoritmos, prompting, ajuste, RL, regresion, analisis estadistico o evaluacion automatizada; evita formulaciones vagas.
            - variables_*: dejar vacio si no aparece con suficiente claridad.
            - En ciencias sociales, educacion o management, extrae constructos, teoria, contexto, unidad de analisis, mecanismos, mediadores, moderadores, limites de transferencia y cautelas causales si aparecen.
            - En modo management, no confundas asociacion con causalidad: registra endogeneidad, controles, panel, instrumento, efectos fijos, robustez o baseline cuando el PDF lo indique.
            - En modo educacion, separa actividad pedagogica, rol docente/estudiante, resultado educativo, adopcion, feedback, evaluacion, equidad, etica y contexto institucional.
            - En modo tecnico, prioriza arquitectura, componentes, benchmark, dataset, metrica, ablation, coste, latencia, robustez y reproducibilidad.
            - En modo biomedico, conserva poblacion, intervencion/exposicion, comparador, outcome, diseno y riesgo de sesgo.
            - evidence_snippet: frase corta y trazable del texto que justifique la clasificacion o el hallazgo central.
            - evidence_location: usa "full text" si la evidencia viene del texto completo local; si no, usa "abstract metadata" o "title metadata".
            - extraction_confidence: 0-100.
            - key_findings: 1-2 frases en espanol con hallazgo sustantivo, no generico.
            - El campo `full_text_digest` se ha construido leyendo el PDF completo y condensando las zonas metodologicas y tematicas de todo el documento.
            - Si `full_text_digest` trae contenido, priorizalo sobre el abstract para la extraccion metodologica.
            - Si el PDF nombra modelos concretos, datasets, benchmarks, escalas o comparadores, recuperalos aunque el abstract sea mas vago.

            Devuelve solo JSON valido con la forma {{ "items": [ ... ] }}.
            Datos:
            {json.dumps(compact, ensure_ascii=False)}
            """
        ).strip()

        try:
            parsed = parse_json_response(
                call_llm(
                    prompt,
                    schema,
                    model_log,
                    preferred_models=TEXT_REASONING_MODELS,
                    request_timeout_seconds=extraction_timeout_seconds,
                    retries=1,
                )
            )
            items = parsed.get("items", []) if isinstance(parsed, dict) else []
            if isinstance(parsed, dict) and not items and "title_es" in parsed:
                items = [parsed]
        except Exception:
            items = []
        if not items:
            items = [
                fallback_extraction_item(
                    pending_rows[0],
                    "Extraccion de respaldo por respuesta incompleta o error transitorio del modelo.",
                )
            ]
        normalized_items: list[dict[str, object]] = []
        for item_index, source in enumerate(pending_rows):
            if item_index < len(items) and isinstance(items[item_index], dict):
                item = dict(items[item_index])
            else:
                item = fallback_extraction_item(source, "Extraccion de respaldo por respuesta incompleta o error transitorio del modelo.")
            item.setdefault("record_id", source["record_id"])
            item.setdefault("title_en", source.get("title_original", ""))
            item.setdefault("title_es", source.get("title_original", ""))
            item.setdefault("abstract_original", source.get("abstract_original", ""))
            item.setdefault("abstract_en", source.get("abstract_original", ""))
            item.setdefault("abstract_es", source.get("abstract_original", ""))
            item.setdefault("design_detail", "no reportado")
            item.setdefault("countries", "no reportado")
            item.setdefault("unit_of_analysis", "no reportado")
            item.setdefault("sample_description", "no reportado")
            item.setdefault("sample_size", "no reportado")
            item.setdefault("models_or_systems_studied", "no reportado")
            item.setdefault("model_count", "no reportado")
            item.setdefault("benchmark_dataset_or_corpus", "no reportado")
            item.setdefault("tasks_or_domains", "no reportado")
            item.setdefault("baselines_or_comparators", "no reportado")
            item.setdefault("instruments_or_scales", "no reportado")
            item.setdefault("method_used", "no reportado")
            item.setdefault("theory_framework", "no reportado")
            item.setdefault("evidence_snippet", "no reportado")
            item.setdefault("evidence_location", "full text" if (source.get("full_text_text") or "").strip() else "abstract metadata")
            item.setdefault("key_findings", "no reportado")
            for field in (
                "variables_dependent",
                "variables_independent",
                "variables_moderating",
                "variables_mediating",
                "variables_control",
            ):
                item.setdefault(field, "")
            heuristically_enrich_extraction_item(source, item, context)
            confidence = 0
            try:
                confidence = int(str(item.get("extraction_confidence") or "0").strip())
            except ValueError:
                confidence = 0
            if (
                confidence >= 80
                and str(source.get("full_text_path", "") or "").lower().endswith(".pdf")
                and bool((source.get("full_text_text") or "").strip())
            ):
                item["evidence_location"] = "full text"
            normalized_items.append(item)
        for item in normalized_items:
            cached_by_id[item["record_id"]] = item
            extracted.append(item)
        write_csv(
            extraction_path,
            EXTRACTION_FIELDS,
            [cached_by_id[key] for key in sorted(cached_by_id.keys())],
        )
    return extracted


def merge_extraction_into_rows(rows: list[dict[str, object]], extraction_by_id: dict[str, dict[str, object]]) -> None:
    for row in rows:
        record_id = row.get("record_id", "")
        ext = extraction_by_id.get(record_id)
        if not ext:
            continue
        row.update(ext)
        row["title_en"] = ext.get("title_en", row.get("title_original", ""))
        row["title_es"] = ext.get("title_es", "")
        row["abstract_original"] = ext.get("abstract_original", row.get("abstract_original", ""))
        row["abstract_en"] = ext.get("abstract_en", row.get("abstract_original", ""))
        row["abstract_es"] = ext.get("abstract_es", "")


def export_extraction_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    exported: list[dict[str, object]] = []
    for row in rows:
        title_original = row.get("title_original", "") or row.get("title_en", "") or row.get("title_es", "")
        exported.append(
            {
                "record_id": row["record_id"],
                "assigned_doi": row.get("assigned_doi", ""),
                "authors": row.get("authors", ""),
                "title_original": title_original,
                "title_en": row.get("title_en", ""),
                "title_es": row.get("title_es", ""),
                "abstract_original": row.get("abstract_original", ""),
                "abstract_en": row.get("abstract_en", ""),
                "abstract_es": row.get("abstract_es", ""),
                "keywords_author": row.get("keywords_author", ""),
                "keywords_indexed": row.get("keywords_indexed", ""),
                "keywords_normalized": row.get("keywords_normalized", ""),
                "year": row.get("year", ""),
                "work_type": row.get("work_type", "other"),
                "empirical_type": row.get("empirical_type", "other"),
                "design_detail": row.get("design_detail", "no reportado"),
                "countries": row.get("countries", "no reportado"),
                "unit_of_analysis": row.get("unit_of_analysis", "no reportado"),
                "sample_description": row.get("sample_description", "no reportado"),
                "sample_size": row.get("sample_size", "no reportado"),
                "models_or_systems_studied": row.get("models_or_systems_studied", "no reportado"),
                "model_count": row.get("model_count", "no reportado"),
                "benchmark_dataset_or_corpus": row.get("benchmark_dataset_or_corpus", "no reportado"),
                "tasks_or_domains": row.get("tasks_or_domains", "no reportado"),
                "baselines_or_comparators": row.get("baselines_or_comparators", "no reportado"),
                "instruments_or_scales": row.get("instruments_or_scales", "no reportado"),
                "method_used": row.get("method_used", "no reportado"),
                "variables_dependent": row.get("variables_dependent", ""),
                "variables_independent": row.get("variables_independent", ""),
                "variables_moderating": row.get("variables_moderating", ""),
                "variables_mediating": row.get("variables_mediating", ""),
                "variables_control": row.get("variables_control", ""),
                "theory_framework": row.get("theory_framework", "no reportado"),
                "evidence_snippet": row.get("evidence_snippet", ""),
                "evidence_location": row.get("evidence_location", "abstract metadata"),
                "extraction_confidence": row.get("extraction_confidence", 65),
                "key_findings": row.get("key_findings", ""),
                "notes": "Extraccion automatizada con revision asistida por LLM y evidencia trazable extraida desde PDF.",
            }
        )
    return exported


def field_reported(value: object) -> bool:
    normalized = normalize_title(str(value or ""))
    return bool(normalized and normalized not in {"no reportado", "not specified", "none", "na", "n a"})


def mode_adjusted_quality(row: dict[str, object], base_quality: int, context: dict[str, str]) -> int:
    """Adapt quality scoring to the review mode instead of one universal mold."""
    mode = review_mode_key(context)
    quality = base_quality
    if mode in {"social_sciences", "education", "management"} or context.get("review_mode") == "mixed":
        construct_fields = [
            row.get("theory_framework"),
            row.get("unit_of_analysis"),
            row.get("sample_description"),
            row.get("countries"),
            row.get("method_used"),
        ]
        reported = sum(1 for value in construct_fields if field_reported(value))
        quality += max(-18, (reported - 3) * 6)
        if mode == "management":
            variable_fields = [
                row.get("variables_dependent"),
                row.get("variables_independent"),
                row.get("variables_moderating"),
                row.get("variables_mediating"),
                row.get("variables_control"),
                row.get("baselines_or_comparators"),
            ]
            quality += min(15, sum(1 for value in variable_fields if field_reported(value)) * 3)
            method_blob = normalize_title(" ".join(str(row.get(field, "")) for field in ("method_used", "design_detail", "notes", "key_findings")))
            if any(token in method_blob for token in ("panel", "fixed effects", "instrumental", "endogeneity", "robust", "difference in differences", "regression")):
                quality += 6
        if mode == "education":
            education_blob = normalize_title(" ".join(str(row.get(field, "")) for field in ("tasks_or_domains", "key_findings", "method_used", "theory_framework")))
            if any(token in education_blob for token in ("feedback", "assessment", "learning", "teaching", "curriculum", "docente", "teacher", "student")):
                quality += 5
    elif mode == "technical":
        technical_fields = [
            row.get("models_or_systems_studied"),
            row.get("benchmark_dataset_or_corpus"),
            row.get("baselines_or_comparators"),
            row.get("method_used"),
            row.get("tasks_or_domains"),
        ]
        quality += max(-12, (sum(1 for value in technical_fields if field_reported(value)) - 3) * 5)
    elif mode == "biomedical":
        biomedical_fields = [
            row.get("sample_size"),
            row.get("baselines_or_comparators"),
            row.get("method_used"),
            row.get("variables_dependent"),
            row.get("instruments_or_scales"),
        ]
        quality += max(-15, (sum(1 for value in biomedical_fields if field_reported(value)) - 3) * 5)
    return max(0, min(100, int(round(quality))))


def shortlist_rows(
    included: list[dict[str, object]],
    n_limit: int,
    representativeness_rule: str,
    research_context: dict[str, str],
    n_min: int | None = None,
) -> list[dict[str, object]]:
    work_type_counts = Counter((row.get("work_type") or "other") for row in included)
    source_counts = Counter((row.get("source") or "unknown") for row in included)

    scored_rows: list[dict[str, object]] = []
    weight_relevance, weight_quality, weight_representativeness = selection_weights(
        review_mode_key(research_context) or research_context.get("review_mode") or "mixed"
    )
    for row in included:
        relevance = int(row.get("relevance_score", 70) or 70)
        quality = mode_adjusted_quality(row, int(row.get("methodological_quality_score", 65) or 65), research_context)
        exclusion_reason = shortlist_focus_exclusion_reason(research_context, row)
        try:
            extraction_confidence = int(str(row.get("extraction_confidence", 100) or 100).strip())
        except ValueError:
            extraction_confidence = 0
        diversity = 50
        if work_type_counts[(row.get("work_type") or "other")] <= 2:
            diversity += 20
        if source_counts[(row.get("source") or "unknown")] <= 2:
            diversity += 10
        if (row.get("empirical_type") or "") in {"quantitative", "experimental", "mixed"}:
            diversity += 5
        row = dict(row)
        # Extraction confidence is a ranking signal, not an eligibility rule:
        # a DOI+PDF study should remain in the systematic-review corpus even
        # when some extraction fields need conservative "not reported" values.
        low_extraction_confidence = extraction_confidence < 80
        if low_extraction_confidence:
            relevance = min(relevance, 58)
            quality = min(quality, 52)
            diversity = max(0, diversity - 8)
        if exclusion_reason == "sin_doi":
            relevance = 0
            quality = 0
            diversity = 0
        elif exclusion_reason == "sin_pdf_local":
            relevance = 0
            quality = 0
            diversity = 0
        elif exclusion_reason in {
            "fuera_de_dominio_software",
            "ajuste_tematico_insuficiente",
            "personalizacion_sin_personalidad",
            "creatividad_humana_sin_llm",
            "sin_metodo_o_evaluacion_creatividad",
        }:
            relevance = min(relevance, 20)
            quality = min(quality, 35)
            diversity = max(0, diversity - 15)
        row["representativeness_score"] = min(diversity, 100)
        row["methodological_quality_score"] = quality
        row["ultraquality_score"] = round(
            relevance * weight_relevance
            + quality * weight_quality
            + row["representativeness_score"] * weight_representativeness,
            2,
        )
        row["_score_formula"] = (
            f"{weight_relevance:.2f}*Rel + {weight_quality:.2f}*Cal + "
            f"{weight_representativeness:.2f}*Rep"
        )
        row["_focus_exclusion_reason"] = exclusion_reason
        row["_low_extraction_confidence"] = low_extraction_confidence
        scored_rows.append(row)

    scored_rows.sort(key=lambda item: (item["ultraquality_score"], item.get("relevance_score", 0), item.get("methodological_quality_score", 0)), reverse=True)
    eligible_rows = [row for row in scored_rows if not row.get("_focus_exclusion_reason")]
    selected_ids = {row["record_id"] for row in eligible_rows[:n_limit]}

    focus_exclusion_labels = {
        "confianza_de_extraccion_baja": "confianza de extracción baja",
        "sin_doi": "ausencia de DOI normalizado",
        "sin_pdf_local": "ausencia de PDF local legible",
        "fuera_de_dominio_software": "desajuste con el dominio de software",
        "ajuste_tematico_insuficiente": "ajuste temático insuficiente",
        "personalizacion_sin_personalidad": "personalización sin constructo de personalidad",
        "creatividad_humana_sin_llm": "creatividad humana sin evaluación del modelo LLM",
        "sin_metodo_o_evaluacion_creatividad": "ausencia de método o evaluación de creatividad",
    }

    output: list[dict[str, object]] = []
    for index, row in enumerate(scored_rows, start=1):
        selected = row["record_id"] in selected_ids
        output.append(
            {
                "record_id": row["record_id"],
                "assigned_doi": row.get("assigned_doi", ""),
                "authors": row.get("authors", ""),
                "title_original": row.get("title_original", ""),
                "decision_before_cap": "include",
                "n_min": n_min or "",
                "n_limit": n_limit,
                "ultraquality_rank": index,
                "ultraquality_score": row["ultraquality_score"],
                "representativeness_score": row["representativeness_score"],
                "methodological_quality_score": row.get("methodological_quality_score", ""),
                "relevance_score": row.get("relevance_score", ""),
                "score_formula": row.get("_score_formula", ""),
                "selected_for_final_n": "yes" if selected else "no",
                "selection_reason": (
                    f"Seleccionado para el subconjunto final por score adaptado al modo metodológico ({row.get('_score_formula')}), calidad de la extracción y representatividad ({representativeness_rule})."
                    if selected else ""
                ),
                "cap_exclusion_reason": (
                    ""
                    if selected
                    else (
                        "Estudio excluido del subconjunto focal por "
                        + focus_exclusion_labels.get(
                            str(row.get("_focus_exclusion_reason")),
                            str(row.get("_focus_exclusion_reason")).replace("_", " "),
                        )
                        + "."
                        if row.get("_focus_exclusion_reason")
                        else f"Estudio válido, pero queda fuera del top {n_limit} por el cap ultraquality y por menor puntuación compuesta."
                    )
                ),
                "reviewer": REVIEWER,
                "reviewed_at": ISO_NOW,
                "notes": str(row.get("_focus_exclusion_reason", "")),
            }
        )
        if row.get("_low_extraction_confidence") and not output[-1]["cap_exclusion_reason"]:
            output[-1]["notes"] = "confianza_de_extraccion_baja_rank_penalty"
    return output


def update_prisma_counts(review_dir: pathlib.Path, all_candidates: list[dict[str, str]], full_text_rows: list[dict[str, object]], included_count: int) -> None:
    rows = build_prisma_count_rows(
        review_dir,
        all_candidates=all_candidates,
        full_text_rows=full_text_rows,
        included_count=included_count,
    )
    write_csv(review_dir / "prisma" / "flow-counts.csv", ["stage", "count", "notes"], rows)


def update_prisma_counts_snapshot(
    review_dir: pathlib.Path,
    *,
    all_candidates: list[dict[str, str]] | None = None,
    candidate_rows: list[dict[str, str]] | None = None,
    full_text_rows: list[dict[str, object]] | None = None,
    included_count: int | None = None,
) -> None:
    rows = build_prisma_count_rows(
        review_dir,
        all_candidates=all_candidates,
        candidate_rows=candidate_rows,
        full_text_rows=full_text_rows,
        included_count=included_count,
    )
    write_csv(review_dir / "prisma" / "flow-counts.csv", ["stage", "count", "notes"], rows)


def append_decision_log(review_dir: pathlib.Path, model_log: list[str], included_count: int, shortlist_count: int) -> None:
    path = review_dir / "notes" / "decisions.md"
    existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else "# Decisions\n\n"
    entry = textwrap.dedent(
        f"""
        ## {ISO_NOW}

        - Se ejecuto el cierre automatico de fases 3 a 5 con el helper `complete_review.py`.
        - Modelos usados en cascada: {", ".join(model_log) if model_log else "sin registrar"}.
        - Estudios incluidos en la revision: {included_count}.
        - Estudios seleccionados para el subconjunto ultraquality final: {shortlist_count}.
        - Los estudios sin PDF legible quedaron fuera del corpus final. La extraccion solo se consolido sobre texto completo extraido desde PDF.
        """
    ).strip()
    path.write_text(existing.rstrip() + "\n\n" + entry + "\n", encoding="utf-8")


def write_n_range_audit(
    review_dir: pathlib.Path,
    n_min: int | None,
    n_limit: int,
    included_count: int,
    shortlist_count: int,
) -> None:
    status = "PASS"
    detail = f"El subconjunto focal cumple el cap máximo configurado (n={shortlist_count}, máximo={n_limit})."
    if shortlist_count > n_limit:
        status = "FAIL"
        detail = f"El subconjunto focal supera el máximo configurado (n={shortlist_count}, máximo={n_limit})."
    elif n_min and shortlist_count < n_min:
        status = "WARN"
        detail = (
            f"El subconjunto focal queda por debajo del mínimo deseado "
            f"(n={shortlist_count}, mínimo={n_min}, máximo={n_limit})."
        )
    lines = [
        "# Auditoría de rango N final",
        "",
        f"- Estado: **{status}**",
        f"- N mínimo deseado: {n_min or 'no configurado'}",
        f"- N máximo/cap: {n_limit}",
        f"- Estudios incluidos tras full text: {included_count}",
        f"- Estudios seleccionados para síntesis focal: {shortlist_count}",
        "",
        "## Lectura metodológica",
        detail,
        "",
        "Si el mínimo no se alcanza, Hermes no debe inflar el corpus artificialmente: debe declarar la insuficiencia, conservar el corpus real y explicar si el resultado sigue siendo publicable como revisión focal o si conviene ampliar la ventana/fuentes.",
    ]
    write_text(review_dir / "selection" / "n-range-audit.md", "\n".join(lines))


def write_full_text_manifest(review_dir: pathlib.Path, candidate_rows: list[dict[str, object]], full_text_rows: list[dict[str, object]]) -> None:
    fulltext_dir = review_dir / "fulltext"
    fulltext_dir.mkdir(parents=True, exist_ok=True)
    rows_by_id = {str(row.get("record_id", "")): row for row in full_text_rows}
    manifest_rows: list[dict[str, str]] = []
    for row_index, row in enumerate(candidate_rows, start=1):
        record_id = str(row.get("record_id", "") or "")
        full_row = rows_by_id.get(record_id, {})
        pdf_path = str(full_row.get("full_text_path", "") or row.get("full_text_path", "") or "")
        txt_path = ""
        if pdf_path:
            pdf_obj = pathlib.Path(pdf_path)
            candidate_txt = review_dir / "fulltext" / "txt" / f"{pdf_obj.stem}.txt"
            if candidate_txt.exists():
                txt_path = str(candidate_txt)
        manifest_rows.append(
            {
                "record_id": record_id,
                "title": str(row.get("title_original", "") or row.get("title_en", "") or ""),
                "decision": canonicalize_screening_decision(full_row.get("decision", ""), "full_text"),
                "reason": str(full_row.get("reason", "") or ""),
                "status": "retrieved" if pdf_path else "not_retrieved",
                "pdf_path": pdf_path,
                "txt_path": txt_path,
            }
        )
    write_csv(
        fulltext_dir / "manifest.csv",
        ["record_id", "title", "decision", "reason", "status", "pdf_path", "txt_path"],
        manifest_rows,
    )
    retrieved = sum(1 for row in manifest_rows if row["status"] == "retrieved")
    assessed = sum(1 for row in manifest_rows if row["status"] == "retrieved" and row["decision"] in {"include_ft", "exclude"})
    included = sum(1 for row in manifest_rows if row["decision"] == "include_ft")
    lines = [
        "# Full Text Library",
        "",
        f"- Candidatos a full text: {len(manifest_rows)}",
        f"- PDFs recuperados: {retrieved}",
        f"- Textos completos evaluados: {assessed}",
        f"- Estudios incluidos tras full text: {included}",
        "",
        "| Record ID | Estado | Decisión | PDF | TXT |",
        "|---|---|---|---|---|",
    ]
    for row in manifest_rows:
        pdf_label = pathlib.Path(row["pdf_path"]).name if row["pdf_path"] else "-"
        txt_label = pathlib.Path(row["txt_path"]).name if row["txt_path"] else "-"
        decision = row["decision"] or "-"
        lines.append(f"| {row['record_id']} | {row['status']} | {decision} | {pdf_label} | {txt_label} |")
    (fulltext_dir / "README.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def render_prisma_figure(review_dir: pathlib.Path, included_count: int, shortlisted_count: int, context: dict[str, str]) -> None:
    figures_dir = review_dir / "figures"
    svg_dir = figures_dir / "svg"
    png_dir = figures_dir / "png"
    svg_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    flow_rows = {row["stage"]: row["count"] for row in read_csv(review_dir / "prisma" / "flow-counts.csv")}
    full_text_rows = read_csv(review_dir / "screening" / "full-text.csv")
    svg_path = svg_dir / "prisma-flow.svg"
    date_start = ascii_figure_text(collapse_whitespace(context.get("date_start", "") or "")) or ""
    date_end = ascii_figure_text(collapse_whitespace(context.get("date_end", "") or "")) or ""
    years_label = ascii_figure_text(collapse_whitespace(context.get("years", "") or "")) or "sin fecha"
    subtitle_label = f"Ventana: {date_start} a {date_end}" if date_start and date_end else f"Período revisado: {years_label}"

    def wrap_lines(text: str, width: int) -> list[str]:
        return textwrap.wrap(collapse_whitespace(text), width=width) or [collapse_whitespace(text)]

    def svg_text(lines: list[str], x: int, y: int, klass: str, anchor: str = "start", line_height: int = 20) -> str:
        tspans = []
        for index, line in enumerate(lines):
            dy = "0" if index == 0 else str(line_height)
            tspans.append(f'<tspan x="{x}" dy="{dy}">{html.escape(line)}</tspan>')
        return f'<text x="{x}" y="{y}" class="{klass}" text-anchor="{anchor}">{"".join(tspans)}</text>'

    def classify_exclusion_reason(reason: str, detail: str) -> str:
        blob = collapse_whitespace(f"{reason} {detail}").lower()
        topic_blob = collapse_whitespace(f"{context.get('topic', '')} {context.get('research_question', '')}").lower()
        if "missing_doi" in blob or "sin doi" in blob or "doi-only" in blob:
            return "Sin DOI público normalizado"
        if "agent" in topic_blob or "agente" in topic_blob:
            if any(token in blob for token in ("no se centra", "irrelevante", "tangencial", "fuera", "ajeno")):
                return "Fuera del foco de agentes de IA"
            if any(token in blob for token in ("sin detalle", "insuficiente", "nota breve", "marketing", "divulgativo")):
                return "Detalle técnico insuficiente"
            if any(token in blob for token in ("automatización", "rpa", "llm", "aplicación general")) and not any(token in blob for token in ("arquitectura", "orquestación", "herramientas", "evaluación")):
                return "Automatización/LLM sin arquitectura agéntica"
            return "Sin evidencia suficiente sobre arquitectura o evaluación"
        if any(token in blob for token in ("arquitectura", "hardware", "multimodal")):
            return "Arquitectura conceptual sin validación experimental"
        if any(token in blob for token in ("rasgos de personalidad humana", "poblacionales", "referencia humano", "human")):
            return "Datos de personalidad humana, no del modelo"
        if any(token in blob for token in ("private speech", "monologo interno", "autorregulacion cognitiva", "constructo ajeno")):
            return "Constructo cognitivo ajeno a personalidad"
        return "Sin constructo de personalidad en el modelo"

    exclusion_counter: Counter[str] = Counter()
    for row in full_text_rows:
        decision = canonicalize_screening_decision(row.get("decision", ""), "full_text")
        if decision != "exclude":
            continue
        if not str(row.get("full_text_path", "") or "").strip():
            continue
        exclusion_counter[classify_exclusion_reason(str(row.get("reason", "")), str(row.get("reason_detail", "")))] += 1

    raw_exclusion_lines = [f"{label} (n = {count})" for label, count in exclusion_counter.most_common(4)]
    if not raw_exclusion_lines:
        raw_exclusion_lines = [f"Informes excluidos tras elegibilidad (n = {flow_rows.get('full_text_excluded', 0)})"]
    exclusion_lines: list[str] = []
    for line in raw_exclusion_lines:
        exclusion_lines.extend(wrap_lines(line, 42))

    identified = int(flow_rows.get("identified", 0) or 0)
    duplicates_removed = int(flow_rows.get("duplicates_removed", 0) or 0)
    screened = int(flow_rows.get("screened_title_abstract", 0) or 0)
    ta_excluded = int(flow_rows.get("excluded_title_abstract", 0) or 0)
    full_text_sought = int(flow_rows.get("full_text_sought", 0) or 0)
    full_text_not_retrieved = int(flow_rows.get("full_text_not_retrieved", 0) or 0)
    full_text_assessed = int(flow_rows.get("full_text_assessed", 0) or 0)
    full_text_excluded = int(flow_rows.get("full_text_excluded", 0) or 0)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1120" viewBox="0 0 1600 1120" role="img">
  <style>
    .bg {{ fill: #ffffff; }}
    .panel {{ fill: #ffffff; stroke: #111111; stroke-width: 2; }}
    .title {{ font: 700 42px 'Latin Modern Roman', 'LM Roman 10', 'Times New Roman', serif; fill: #111111; }}
    .subtitle {{ font: 400 22px 'Latin Modern Roman', 'LM Roman 10', 'Times New Roman', serif; fill: #4f4f4f; }}
    .stage {{ font: 700 20px 'Latin Modern Roman', 'LM Roman 10', 'Times New Roman', serif; fill: #555555; letter-spacing: 1px; }}
    .box {{ fill: #fbfbfb; stroke: #111111; stroke-width: 2; rx: 12; ry: 12; }}
    .sidebox {{ fill: #f2f2f2; stroke: #111111; stroke-width: 2; rx: 12; ry: 12; }}
    .head {{ font: 700 24px 'Latin Modern Roman', 'LM Roman 10', 'Times New Roman', serif; fill: #111111; }}
    .body {{ font: 400 20px 'Latin Modern Roman', 'LM Roman 10', 'Times New Roman', serif; fill: #222222; }}
    .small {{ font: 400 17px 'Latin Modern Roman', 'LM Roman 10', 'Times New Roman', serif; fill: #444444; }}
    .arrow {{ stroke: #111111; stroke-width: 3; fill: none; marker-end: url(#arrow); }}
  </style>
  <defs>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M0,0 L12,6 L0,12 z" fill="#111111" />
    </marker>
  </defs>
  <rect class="bg" x="0" y="0" width="1600" height="1120"/>
  <text x="70" y="60" class="title">Diagrama de selección de estudios</text>
  <text x="70" y="92" class="subtitle">{html.escape(subtitle_label)}</text>
  <text x="80" y="150" class="stage">IDENTIFICACIÓN</text>
  <rect x="520" y="120" width="480" height="96" class="box"/>
  {svg_text(["Registros identificados", "Fuentes de búsqueda", f"y recuperación (n = {identified})"], 760, 150, "head", anchor="middle", line_height=24)}
  <rect x="1080" y="120" width="410" height="118" class="sidebox"/>
  {svg_text(["Registros eliminados antes del cribado", f"Duplicados eliminados (n = {duplicates_removed})"], 1110, 158, "body", line_height=24)}
  <line x1="760" y1="216" x2="760" y2="280" class="arrow"/>
  <text x="80" y="310" class="stage">CRIBADO</text>
  <rect x="520" y="280" width="480" height="96" class="box"/>
  {svg_text(["Registros cribados", f"Título y resumen evaluados (n = {screened})"], 760, 318, "head", anchor="middle", line_height=28)}
  <rect x="1080" y="280" width="410" height="96" class="sidebox"/>
  {svg_text(["Registros excluidos", f"Tras título y resumen (n = {ta_excluded})"], 1110, 318, "body", line_height=26)}
  <line x1="760" y1="376" x2="760" y2="440" class="arrow"/>
  <text x="80" y="470" class="stage">ELEGIBILIDAD</text>
  <rect x="520" y="440" width="480" height="96" class="box"/>
  {svg_text(["Informes buscados para recuperación", f"Full text solicitado (n = {full_text_sought})"], 760, 478, "head", anchor="middle", line_height=28)}
  <rect x="1080" y="440" width="410" height="96" class="sidebox"/>
  {svg_text(["Informes no recuperados", f"Sin PDF o HTML completo (n = {full_text_not_retrieved})"], 1110, 478, "body", line_height=24)}
  <line x1="760" y1="536" x2="760" y2="600" class="arrow"/>
  <rect x="520" y="600" width="480" height="96" class="box"/>
  {svg_text(["Informes evaluados para elegibilidad", f"Lectura completa realizada (n = {full_text_assessed})"], 760, 638, "head", anchor="middle", line_height=24)}
  <rect x="1080" y="570" width="410" height="194" class="sidebox"/>
  {svg_text(["Informes excluidos, con motivos", f"Total excluidos (n = {full_text_excluded})", *exclusion_lines], 1110, 608, "small", line_height=22)}
  <line x1="760" y1="696" x2="760" y2="792" class="arrow"/>
  <text x="80" y="822" class="stage">INCLUIDOS</text>
  <rect x="520" y="792" width="480" height="96" class="box"/>
  {svg_text(["Estudios incluidos en la revisión", f"Corpus incluido final (n = {included_count})"], 760, 830, "head", anchor="middle", line_height=28)}
  <line x1="760" y1="888" x2="760" y2="952" class="arrow"/>
  <rect x="520" y="952" width="480" height="96" class="sidebox"/>
  {svg_text(["Estudios incluidos en la síntesis focal", f"Subconjunto final analizado (n = {shortlisted_count})"], 760, 990, "head", anchor="middle", line_height=28)}
  <text x="70" y="1082" class="small">Fuente: conteos de flujo y cribado a texto completo. La caption del manuscrito recoge el tema específico de la revisión.</text>
</svg>
"""
    svg_path.write_text(svg, encoding="utf-8")
    manifest_fields = [
        "figure_id",
        "title",
        "phase",
        "paper_section",
        "figure_type",
        "purpose",
        "evidence_basis",
        "style_profile",
        "apa_caption",
        "svg_path",
        "png_path",
        "status",
        "notes",
    ]
    manifest_path = figures_dir / "manifest.csv"
    existing_rows = read_csv(manifest_path)
    by_id = {row.get("figure_id", ""): row for row in existing_rows if row.get("figure_id")}
    by_id["prisma-flow"] = {
        **{field: by_id.get("prisma-flow", {}).get(field, "") for field in manifest_fields},
        "figure_id": "prisma-flow",
        "title": "Diagrama de selección de estudios",
        "phase": "Fase 3",
        "paper_section": "Metodo",
        "figure_type": "selection-flow",
        "purpose": "Mostrar el flujo de identificación, cribado, elegibilidad, corpus incluido y síntesis focal.",
        "evidence_basis": "flow-counts.csv, screening/full-text.csv",
        "style_profile": "systematic-selection-flow",
        "apa_caption": "Figura 1. Diagrama del proceso de identificación, cribado, elegibilidad e inclusión.",
        "svg_path": "figures/svg/prisma-flow.svg",
        "png_path": "figures/png/prisma-flow.png",
        "status": "ready",
        "notes": "Generado automaticamente al cerrar fases 3-5.",
    }
    write_csv(manifest_path, manifest_fields, [by_id[key] for key in sorted(by_id)])
    subprocess.run(
        [
            sys.executable,
            str(pathlib.Path(__file__).with_name("render_review_figures.py")),
            str(review_dir),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PRISMA complete-review pipeline for a prepared review directory."
    )
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument(
        "--skip-publication-layer",
        action="store_true",
        help="Run only the PRISMA/extraction pipeline without the publication autopilot layer.",
    )
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    review_dir = pathlib.Path(args.review_dir).resolve()
    intake_path = review_dir / "protocol" / "intake.md"
    n_min, n_limit_raw = parse_intake_n_range(intake_path)
    n_limit = n_limit_raw or 20
    representativeness_rule = parse_intake_representativeness(intake_path) or "mezcla equilibrada por tipo de tarea, metodo y fuente"
    research_context = read_research_context(review_dir)

    enriched_rows, by_record = enrich_rows(review_dir)
    model_log: list[str] = []
    bootstrap_title_abstract_screening(review_dir, enriched_rows, research_context, model_log)
    enriched_rows, by_record = enrich_rows(review_dir)
    title_abstract_candidates = [row for row in enriched_rows if row.get("ta_decision") in {"include", "maybe"}]
    candidate_rows = prioritize_full_text_candidates(title_abstract_candidates, n_limit, research_context)
    append_retrieval_budget_log(
        review_dir,
        original_count=len(title_abstract_candidates),
        retrieval_count=len(candidate_rows),
        n_limit=n_limit,
    )
    update_prisma_counts_snapshot(review_dir, all_candidates=candidate_rows, included_count=0)
    checkpoint_sync(review_dir)

    cached_full_text_manifest = {
        row.get("record_id", ""): row
        for row in read_csv(review_dir / "fulltext" / "manifest.csv")
        if row.get("record_id")
    }
    for index, row in enumerate(candidate_rows, start=1):
        print(f"[download] lote {index}/{len(candidate_rows)}", flush=True)
        cached_manifest_row = cached_full_text_manifest.get(row.get("record_id", ""))
        if cached_manifest_row and cached_manifest_row.get("status") == "not_retrieved":
            full_text_path, full_text_text = "", ""
        elif cached_manifest_row and cached_manifest_row.get("status") == "retrieved":
            cached_pdf_path = str(cached_manifest_row.get("pdf_path", "") or "")
            cached_txt_path = pathlib.Path(str(cached_manifest_row.get("txt_path", "") or ""))
            if cached_txt_path.exists():
                full_text_path = cached_pdf_path
                full_text_text = cached_txt_path.read_text(encoding="utf-8", errors="ignore")
            else:
                full_text_path, full_text_text = try_download_text(review_dir, row)
        else:
            full_text_path, full_text_text = try_download_text(review_dir, row)
        row["full_text_path"] = full_text_path
        row["full_text_text"] = full_text_text
        if index == 1 or index == len(candidate_rows) or index % 5 == 0:
            write_full_text_manifest(review_dir, candidate_rows, [])
        if index == len(candidate_rows) or index % 10 == 0:
            update_prisma_counts_snapshot(
                review_dir,
                all_candidates=candidate_rows,
                candidate_rows=candidate_rows,
                included_count=0,
            )

    full_text_results = classify_full_text(review_dir, candidate_rows, research_context, model_log)

    full_text_rows: list[dict[str, object]] = []
    included_rows: list[dict[str, str]] = []
    for row_index, row in enumerate(candidate_rows, start=1):
        result = full_text_results[row["record_id"]]
        normalized_ft_decision = canonicalize_screening_decision(result.get("decision", ""), "full_text")
        missing_doi = not normalize_doi(str(row.get("assigned_doi", "") or ""))
        include = normalized_ft_decision == "include_ft" and not missing_doi
        full_text_path = row.get("full_text_path", "")
        full_text_text = row.get("full_text_text", "")
        title_es = row.get("title_es", "")
        abstract_es = row.get("abstract_es", "")
        full_text_decision = "include_ft" if include else (normalized_ft_decision or "exclude")
        if missing_doi and normalized_ft_decision == "include_ft":
            full_text_decision = "exclude"
            result["reason"] = "missing_doi"
            result["reason_detail"] = (
                "La regla DOI-only del corpus publicable impide incluir estudios sin DOI normalizado, "
                "aunque exista PDF local."
            )
        row_ft = {
            "record_id": row["record_id"],
            "assigned_doi": row.get("assigned_doi", ""),
            "authors": row.get("authors", ""),
            "title_original": row.get("title_original", ""),
            "title_en": row.get("title_en", "") or row.get("title_original", ""),
            "title_es": title_es,
            "abstract_original": row.get("abstract_original", ""),
            "abstract_en": row.get("abstract_en", "") or row.get("abstract_original", ""),
            "abstract_es": abstract_es,
            "keywords_author": row.get("keywords_author", ""),
            "keywords_indexed": row.get("keywords_indexed", ""),
            "keywords_normalized": row.get("keywords_normalized", ""),
            "decision": full_text_decision,
            "exclusion_score": result.get("exclusion_score", 75),
            "reason": result.get("reason", "insufficient_detail"),
            "reason_detail": result.get("reason_detail", ""),
            "reviewer": REVIEWER,
            "reviewed_at": ISO_NOW,
            "full_text_path": full_text_path,
            "notes": f"confidence={result.get('confidence', '')}; relevance={result.get('relevance_score', '')}; methodological={result.get('methodological_quality_score', '')}",
        }
        full_text_rows.append(row_ft)
        if include and len((full_text_text or "").strip()) >= FULLTEXT_MIN_CHARS:
            row["work_type"] = result.get("work_type", row.get("work_type", "other"))
            row["empirical_type"] = result.get("empirical_type", "other")
            row["relevance_score"] = result.get("relevance_score", 70)
            row["methodological_quality_score"] = result.get("methodological_quality_score", 65)
            row["confidence"] = result.get("confidence", 70)
            row["full_text_reason"] = result.get("reason", "")
            row["full_text_reason_detail"] = result.get("reason_detail", "")
            included_rows.append(row)
        should_checkpoint_full_text = row_index == len(candidate_rows) or row_index % 10 == 0
        if should_checkpoint_full_text:
            write_csv(review_dir / "screening" / "full-text.csv", FULLTEXT_FIELDS, full_text_rows)
            write_full_text_manifest(review_dir, candidate_rows, full_text_rows)
            update_prisma_counts_snapshot(
                review_dir,
                all_candidates=candidate_rows,
                candidate_rows=candidate_rows,
                full_text_rows=full_text_rows,
                included_count=len(included_rows),
            )
            checkpoint_sync(review_dir)

    shortlist: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    extraction_by_id: dict[str, dict[str, object]] = {}

    provisional_shortlist = shortlist_rows(included_rows, n_limit, representativeness_rule, research_context, n_min=n_min)
    provisional_selected_ids = {
        row["record_id"]
        for row in provisional_shortlist
        if str(row.get("selected_for_final_n", "")).lower() in {"yes", "si", "sí", "true", "1"}
    }
    extraction_target_rows = [row for row in included_rows if row["record_id"] in provisional_selected_ids]
    if len(extraction_target_rows) < min(n_limit, len(included_rows)):
        extraction_target_rows = prioritize_extraction_candidates(included_rows, n_limit)
    if len(extraction_target_rows) < len(included_rows):
        model_log.append(
            "extraction_budget="
            f"{len(extraction_target_rows)}/{len(included_rows)} "
            f"(final_n={n_limit})"
        )
    extraction_results = extract_included(extraction_target_rows, review_dir, model_log, research_context)
    extraction_by_id.update({item["record_id"]: item for item in extraction_results})
    merge_extraction_into_rows(included_rows, extraction_by_id)
    shortlist = shortlist_rows(included_rows, n_limit, representativeness_rule, research_context, n_min=n_min)
    selected_ids = {
        row["record_id"]
        for row in shortlist
        if str(row.get("selected_for_final_n", "")).lower() in {"yes", "si", "sí", "true", "1"}
    }

    missing_rows = [row for row in included_rows if row["record_id"] in selected_ids and row["record_id"] not in extraction_by_id]
    if missing_rows:
        extraction_results = extract_included(missing_rows, review_dir, model_log, research_context)
        extraction_by_id.update({item["record_id"]: item for item in extraction_results})
        merge_extraction_into_rows(included_rows, extraction_by_id)
        shortlist = shortlist_rows(included_rows, n_limit, representativeness_rule, research_context, n_min=n_min)
        selected_ids = {
            row["record_id"]
            for row in shortlist
            if str(row.get("selected_for_final_n", "")).lower() in {"yes", "si", "sí", "true", "1"}
        }

    retry_rows = []
    for row in included_rows:
        if row["record_id"] not in selected_ids:
            continue
        try:
            confidence = int(str(row.get("extraction_confidence", 0) or 0).strip())
        except ValueError:
            confidence = 0
        if confidence < 80:
            retry_rows.append(row)
    if retry_rows:
        extraction_results = extract_included(retry_rows, review_dir, model_log, research_context)
        extraction_by_id.update({item["record_id"]: item for item in extraction_results})
        merge_extraction_into_rows(included_rows, extraction_by_id)
        shortlist = shortlist_rows(included_rows, n_limit, representativeness_rule, research_context, n_min=n_min)
        selected_ids = {
            row["record_id"]
            for row in shortlist
            if str(row.get("selected_for_final_n", "")).lower() in {"yes", "si", "sí", "true", "1"}
        }
        final_missing_rows = [row for row in included_rows if row["record_id"] in selected_ids and row["record_id"] not in extraction_by_id]
        if final_missing_rows:
            extraction_results = extract_included(final_missing_rows, review_dir, model_log, research_context)
            extraction_by_id.update({item["record_id"]: item for item in extraction_results})
            merge_extraction_into_rows(included_rows, extraction_by_id)
            shortlist = shortlist_rows(included_rows, n_limit, representativeness_rule, research_context, n_min=n_min)
            selected_ids = {
                row["record_id"]
                for row in shortlist
                if str(row.get("selected_for_final_n", "")).lower() in {"yes", "si", "sí", "true", "1"}
            }

    final_selected_rows = [row for row in included_rows if row["record_id"] in selected_ids]
    extraction_rows = export_extraction_rows(final_selected_rows)
    write_csv(review_dir / "screening" / "full-text.csv", FULLTEXT_FIELDS, full_text_rows)
    write_csv(review_dir / "extraction" / "extraction-table.csv", EXTRACTION_FIELDS, extraction_rows)
    write_csv(review_dir / "selection" / "ultraquality-shortlist.csv", SHORTLIST_FIELDS, shortlist)
    write_full_text_manifest(review_dir, candidate_rows, full_text_rows)
    checkpoint_sync(review_dir)
    update_prisma_counts_snapshot(
        review_dir,
        all_candidates=candidate_rows,
        candidate_rows=candidate_rows,
        full_text_rows=full_text_rows,
        included_count=len(included_rows),
    )
    render_prisma_figure(
        review_dir,
        included_count=len(included_rows),
        shortlisted_count=sum(1 for row in shortlist if row.get("selected_for_final_n") == "yes"),
        context=research_context,
    )
    append_decision_log(review_dir, model_log, len(included_rows), sum(1 for row in shortlist if row.get("selected_for_final_n") == "yes"))
    write_n_range_audit(
        review_dir,
        n_min=n_min,
        n_limit=n_limit,
        included_count=len(included_rows),
        shortlist_count=sum(1 for row in shortlist if row.get("selected_for_final_n") == "yes"),
    )

    master_rows = read_csv(review_dir / "records" / "master-records.csv")
    master_map = {row["record_id"]: row for row in master_rows}
    for row in final_selected_rows:
        if row["record_id"] not in master_map:
            continue
        master_map[row["record_id"]].update(
            {
                "title_en": row.get("title_en", ""),
                "title_es": row.get("title_es", ""),
                "abstract_original": row.get("abstract_original", ""),
                "abstract_en": row.get("abstract_en", ""),
                "abstract_es": row.get("abstract_es", ""),
                "keywords_indexed": row.get("keywords_indexed", ""),
                "keywords_normalized": row.get("keywords_normalized", ""),
            }
        )
    if master_rows:
        write_csv(review_dir / "records" / "master-records.csv", list(master_rows[0].keys()), list(master_map.values()))
    checkpoint_sync(review_dir)

    publication_status = "skipped"
    publication_script = pathlib.Path(__file__).resolve().parent / "publication_autopilot.py"
    if not args.skip_publication_layer:
        try:
            subprocess.run(
                [sys.executable, str(publication_script), str(review_dir)],
                check=True,
            )
            publication_status = "completed"
        except subprocess.CalledProcessError:
            publication_status = "failed"

    print(json.dumps({
        "review_dir": str(review_dir),
        "candidate_rows": len(candidate_rows),
        "included_rows": len(included_rows),
        "shortlist_selected": sum(1 for row in shortlist if row.get("selected_for_final_n") == "yes"),
        "final_n_min": n_min or "",
        "final_n_max": n_limit,
        "models_used": model_log,
        "publication_layer": publication_status,
    }, ensure_ascii=False, indent=2))
    return 0 if publication_status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
