#!/usr/bin/env python3
"""Bootstrap a PRISMA review from the intake topic and research question."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date, datetime, timezone

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cloud_inference import (  # noqa: E402
    configured_research_models,
    post_openai_compatible_chat,
    resolve_inference_runtime,
)
from review_mode_router import (  # noqa: E402
    infer_review_mode,
    review_mode_summary,
    write_review_mode_artifacts,
)

USER_AGENT = "HermesTopicReviewBootstrap/1.0"
OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_URL = "https://export.arxiv.org/api/query"
EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENAIRE_URL = "https://api.openaire.eu/graph/v2/researchProducts"
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
LENS_SCHOLAR_URL = "https://api.lens.org/scholarly/search"
SOURCE_PRIORITY = {
    "openalex": 7,
    "lens": 6,
    "crossref": 5,
    "openaire": 4,
    "europepmc": 4,
    "semanticscholar": 3,
    "pubmed": 3,
    "arxiv": 2,
}
HERMES_HOME = pathlib.Path(__file__).resolve().parents[4]
SOURCE_QUERY_LIMITS = {
    "openalex": 28,
    "crossref": 28,
    "semanticscholar": 28,
    "arxiv": 18,
    "openaire": 20,
    "europepmc": 16,
    "pubmed": 16,
    "lens": 20,
}
SMOKE_TEST_MODE = os.environ.get("HERMES_RESEARCH_SMOKE_TEST", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
PUBLIC_API_PAGE_SIZE = 10 if SMOKE_TEST_MODE else 100
if SMOKE_TEST_MODE:
    # Exercise two independent bibliographic sources without turning an
    # installation check into a costly full review.
    SOURCE_QUERY_LIMITS = {
        source: 1 if source in {"openalex", "crossref"} else 0
        for source in SOURCE_QUERY_LIMITS
    }

GENERIC_SEARCH_STOPWORDS = {
    "about",
    "after",
    "against",
    "analysis",
    "based",
    "between",
    "como",
    "con",
    "contra",
    "desde",
    "during",
    "efectos",
    "estudio",
    "estudios",
    "evidencia",
    "para",
    "por",
    "sobre",
    "systematic",
    "review",
    "revision",
    "revisión",
    "study",
    "studies",
    "the",
    "their",
    "this",
    "through",
    "using",
    "what",
    "with",
    "without",
    "años",
    "ano",
    "año",
    "entre",
    "investigacion",
    "investigación",
    "literatura",
    "modelo",
    "modelos",
    "paper",
    "papers",
    "publicaciones",
    "qué",
    "que",
}

MASTER_FIELDS = [
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

SEARCH_FIELDS = [
    "source",
    "platform",
    "query_string",
    "author_filter",
    "run_date",
    "from_date",
    "to_date",
    "notes",
    "export_file",
]

SEARCH_STAGE_FIELDS = [
    "stage_id",
    "stage_name",
    "source",
    "query_string",
    "axis_covered",
    "purpose",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: pathlib.Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def resolve_env_value(env_values: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = os.environ.get(key, "").strip() or env_values.get(key, "").strip()
        if value:
            return value
    return ""


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


def parse_json_response(raw: str) -> object:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def call_search_planner_llm(prompt: str) -> dict | None:
    """Ask the configured cloud model to decompose the question into search stages.

    This step is intentionally non-blocking. If credentials or the provider are
    unavailable, the bootstrap falls back to deterministic decomposition and the
    audit files still explain the search logic.
    """
    env_values = load_env_file(HERMES_HOME / ".env")
    base_url, api_key = resolve_inference_runtime(env_values)
    if not api_key or not base_url:
        return None
    search_planner_models = configured_research_models(env_values)
    if not search_planner_models:
        return None
    deadline = time.monotonic() + 45
    for model in search_planner_models:
        remaining_seconds = int(deadline - time.monotonic())
        if remaining_seconds < 5:
            break
        payload = {
            "model": model,
            "temperature": 0.1,
            "max_tokens": 2500,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a systematic-review search strategist. "
                        "Return only valid JSON. Do not invent databases or sources."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        try:
            data = post_openai_compatible_chat(
                base_url=base_url,
                api_key=api_key,
                payload=payload,
                timeout_seconds=min(25, remaining_seconds),
                user_agent=USER_AGENT,
            )
            content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            parsed = parse_json_response(content)
            if isinstance(parsed, dict):
                parsed["planner_model"] = model
                return parsed
        except Exception:
            continue
    return None


def contact_email() -> str:
    """Optional polite contact address for scholarly APIs."""
    return os.environ.get("HERMES_CONTACT_EMAIL", "").strip()


def add_contact_param(params: dict[str, str]) -> dict[str, str]:
    email = contact_email()
    if email:
        params["mailto"] = email
    return params


def semantic_scholar_headers() -> dict[str, str]:
    env_values = load_env_file(HERMES_HOME / ".env")
    key = resolve_env_value(env_values, "SEMANTIC_SCHOLAR_API_KEY", "HERMES_SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": key} if key else {}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "si", "sí", "on"}


def optional_source_key(*keys: str) -> str:
    env_values = load_env_file(HERMES_HOME / ".env")
    return resolve_env_value(env_values, *keys)


def lens_headers() -> dict[str, str]:
    token = optional_source_key("HERMES_LENS_API_KEY", "LENS_API_KEY")
    if not token:
        return {}
    if token.lower().startswith("bearer "):
        authorization = token
    else:
        authorization = f"Bearer {token}"
    return {"Authorization": authorization, "Content-Type": "application/json"}


def pubmed_extra_params() -> dict[str, str]:
    params = {"tool": "HermesPRISMA"}
    email = contact_email() or optional_source_key("HERMES_NCBI_EMAIL", "NCBI_EMAIL")
    api_key = optional_source_key("HERMES_NCBI_API_KEY", "NCBI_API_KEY")
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    return params


def biomedical_source_relevant(topic: str, question: str, inclusion: str = "") -> bool:
    """Use specialist biomedical engines only when the question warrants them."""
    blob = f"{topic or ''} {question or ''} {inclusion or ''}".lower()
    markers = (
        "biomed",
        "clinical",
        "clinico",
        "clínico",
        "disease",
        "enfermedad",
        "health",
        "medical",
        "medicine",
        "medicina",
        "mental health",
        "neuro",
        "patient",
        "paciente",
        "pharma",
        "psycholog",
        "psicolog",
        "psychiatr",
        "public health",
        "salud",
    )
    return any(marker in blob for marker in markers)


def arxiv_source_relevant(topic: str, question: str, inclusion: str = "") -> bool:
    """arXiv is valuable for technical/preprint-heavy topics, but noisy elsewhere."""
    blob = f"{topic or ''} {question or ''} {inclusion or ''}".lower()
    markers = (
        "artificial intelligence",
        "agent",
        "algorithm",
        "architecture",
        "benchmark",
        "computer science",
        "deep learning",
        "foundation model",
        "generative",
        "inteligencia artificial",
        "language model",
        "llm",
        "machine learning",
        "neural",
        "rag",
        "software",
        "transformer",
    )
    return any(marker in blob for marker in markers)


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def slugify(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def normalize_title(text: str) -> str:
    return slugify((text or "").replace("&", "and"))


def normalize_doi(text: str) -> str:
    if not text:
        return ""
    value = text.strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    return value.lower()


def stable_record_key(row: dict[str, str]) -> str:
    doi = normalize_doi(row.get("assigned_doi") or row.get("raw_doi") or "")
    if doi:
        return f"doi::{doi}"
    title = normalize_title(row.get("title_original", "") or row.get("title_en", "") or row.get("title_es", ""))
    authors = normalize_title(row.get("authors", ""))
    year = str(row.get("year", "") or row.get("publication_date", "")[:4]).strip()
    return f"title::{title}|authors::{authors}|year::{year}"


def stable_record_id(row: dict[str, str]) -> str:
    digest = hashlib.sha1(stable_record_key(row).encode("utf-8", errors="ignore")).hexdigest()[:10].upper()
    return f"RID-{digest}"


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split())


def parse_intake_value(intake_path: pathlib.Path, label: str) -> str:
    content = read_text(intake_path)
    # Use only horizontal whitespace after the colon. A generic ``\s*`` would
    # also consume the following newline, which can accidentally pull the next
    # bullet into the current field when an optional intake value is left blank.
    pattern = rf"^- {re.escape(label)}:[ \t]*(.*)$"
    match = re.search(pattern, content, flags=re.MULTILINE)
    return (match.group(1) if match else "").strip()


def parse_years(intake_path: pathlib.Path) -> tuple[int, int]:
    content = read_text(intake_path)
    match = re.search(r"Año o años:\s*([0-9]{4})(?:\s*-\s*([0-9]{4}))?", content)
    if not match:
        return 2026, 2026
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    return start, end


def parse_ultraquality_n_range(intake_path: pathlib.Path) -> tuple[int | None, int]:
    raw = parse_intake_value(intake_path, "Límite final N ultraquality")
    numbers = [int(match) for match in re.findall(r"\d+", raw or "")]
    if len(numbers) >= 2:
        low, high = sorted(numbers[:2])
        return max(1, low), max(1, high)
    if len(numbers) == 1:
        return None, max(1, numbers[0])
    return None, 37


def parse_ultraquality_limit(intake_path: pathlib.Path) -> int:
    _minimum, maximum = parse_ultraquality_n_range(intake_path)
    return maximum


def parse_topic(intake_path: pathlib.Path) -> str:
    return parse_intake_value(intake_path, "Tema")


def parse_question(intake_path: pathlib.Path) -> str:
    return parse_intake_value(intake_path, "Pregunta de investigación (opcional)")


def parse_review_mode(intake_path: pathlib.Path) -> str:
    for label in (
        "Modo metodológico (opcional)",
        "Modo metodologico (opcional)",
        "Modo de revisión (opcional)",
        "Modo de revision (opcional)",
        "Review mode",
    ):
        value = parse_intake_value(intake_path, label)
        if value:
            return value
    return ""


def parse_target_outlet(intake_path: pathlib.Path) -> str:
    for label in (
        "Revista o medio objetivo (opcional; si se omite, o si solo indicas una familia temática amplia, Hermes usa `generic-common-core`)",
        "Revista o medio objetivo (opcional; si se omite, Hermes usa `generic-common-core`)",
        "Revista objetivo (opcional)",
        "Target outlet",
    ):
        value = parse_intake_value(intake_path, label)
        if value:
            return value
    return ""


def infer_review_mode_from_intake(
    intake_path: pathlib.Path,
    topic: str,
    question: str,
    inclusion: str,
    exclusion: str,
) -> dict[str, object]:
    return infer_review_mode(
        topic=topic,
        question=question,
        inclusion=inclusion,
        exclusion=exclusion,
        target_outlet=parse_target_outlet(intake_path),
        explicit_mode=parse_review_mode(intake_path),
    )


def parse_iso_date(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def parse_date_window(intake_path: pathlib.Path, year_start: int, year_end: int) -> tuple[str, str]:
    start = parse_iso_date(parse_intake_value(intake_path, "Fecha inicial (opcional)")) or f"{year_start}-01-01"
    explicit_end = parse_iso_date(parse_intake_value(intake_path, "Fecha final (opcional)"))
    end = explicit_end or f"{year_end}-12-31"
    today = date.today().isoformat()
    if not explicit_end and end > today:
        end = today
    if start > end:
        start, end = end, start
    return start, end


def year_from_date(date_text: str, fallback: int) -> int:
    if (date_text or "")[:4].isdigit():
        return int(date_text[:4])
    return fallback


def record_in_window(date_text: str, year_value: str | int | None, from_date: str, to_date: str) -> bool:
    normalized = parse_iso_date(str(date_text or ""))
    if normalized:
        return from_date <= normalized <= to_date
    year_text = str(year_value or "").strip()
    if year_text.isdigit():
        return year_from_date(from_date, 0) <= int(year_text) <= year_from_date(to_date, 9999)
    return True


def criteria_to_bullets(raw: str, fallback: str) -> list[str]:
    tokens = [part.strip() for part in re.split(r"[;\n]+", raw or "") if part.strip()]
    if not tokens:
        return [fallback]
    return [f"- {token}" for token in tokens]


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 25) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def post_json(url: str, payload: dict[str, object], headers: dict[str, str] | None = None, timeout: int = 30) -> dict | list:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def is_creativity_llm_topic(topic: str, question: str) -> bool:
    blob = f"{topic or ''} {question or ''}".lower()
    creativity_tokens = (
        "creatividad",
        "creativity",
        "creative",
        "creativo",
        "creativa",
        "criatividade",
        "pensamiento divergente",
        "divergent thinking",
        "creative writing",
        "ideacion",
        "ideación",
        "originality",
        "originalidad",
        "novelty",
        "novedad",
    )
    model_tokens = (
        "llm",
        "llms",
        "large language model",
        "language model",
        "modelos de lenguaje",
        "modelo de lenguaje",
        "generative ai",
        "ia generativa",
        "chatgpt",
        "gpt",
    )
    return any(token in blob for token in creativity_tokens) and any(token in blob for token in model_tokens)


def normalize_query_token(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9+-]+", " ", value).strip()


def compact_query_text(text: str, max_chars: int = 96) -> str:
    value = " ".join(re.split(r"\s+", (text or "").strip()))
    value = re.sub(r"^[¿?]+|[¿?]+$", "", value).strip(" .,:;")
    if len(value) <= max_chars:
        return value
    words = value.split()
    trimmed: list[str] = []
    for word in words:
        if len(" ".join([*trimmed, word])) > max_chars:
            break
        trimmed.append(word)
    return " ".join(trimmed) or value[:max_chars].rstrip()


def unique_queries(queries: list[str], limit: int = 10) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for query in queries:
        clean = " ".join(str(query or "").split()).strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(clean)
        if len(output) >= limit:
            break
    return output


def generic_search_terms(topic: str, question: str = "", inclusion: str = "", limit: int = 8) -> list[str]:
    """Extract portable search terms from intake text for unknown domains.

    The fallback must work for any future topic, so it avoids hard-coded agent,
    software, LLM, or creativity assumptions. It keeps quoted phrases first,
    then promotes repeated topical tokens from the topic, question and
    inclusion criteria.
    """
    raw = " ".join(part for part in [topic, question, inclusion] if part)
    quoted = [
        compact_query_text(match.group(1), 72)
        for match in re.finditer(r"[\"'“”‘’]([^\"'“”‘’]{4,100})[\"'“”‘’]", raw)
    ]
    normalized = normalize_query_token(raw)
    tokens = [
        token
        for token in re.findall(r"\b[a-z0-9+-]{3,}\b", normalized)
        if token not in GENERIC_SEARCH_STOPWORDS and not token.isdigit()
    ]
    scores: dict[str, int] = {}
    topic_tokens = set(
        token
        for token in re.findall(r"\b[a-z0-9+-]{3,}\b", normalize_query_token(topic))
        if token not in GENERIC_SEARCH_STOPWORDS and not token.isdigit()
    )
    for token in tokens:
        scores[token] = scores.get(token, 0) + (3 if token in topic_tokens else 1)
    ranked_tokens = [
        token
        for token, _score in sorted(scores.items(), key=lambda item: (-item[1], tokens.index(item[0])))
    ]
    output: list[str] = []
    for phrase in quoted:
        if phrase and phrase.lower() not in {item.lower() for item in output}:
            output.append(phrase)
    output.extend(ranked_tokens)
    return unique_queries(output, limit=limit)


def ordered_content_terms(text: str, limit: int = 4) -> list[str]:
    output: list[str] = []
    for token in re.findall(r"\b[a-z0-9+-]{3,}\b", normalize_query_token(text)):
        if token in GENERIC_SEARCH_STOPWORDS or token.isdigit() or token in output:
            continue
        output.append(token)
        if len(output) >= limit:
            break
    return output


def generic_query_plan(topic: str, question: str = "", inclusion: str = "") -> dict[str, list[str]]:
    base = compact_query_text(topic.strip() or question.strip() or "systematic review topic")
    terms = generic_search_terms(topic, question, inclusion, limit=8)
    core_terms = unique_queries([*ordered_content_terms(topic, limit=4), *terms], limit=8) or [base]
    primary = " ".join(core_terms[:3])
    secondary = " ".join(core_terms[1:4]) if len(core_terms) >= 4 else ""
    quoted_base = f'"{base}"' if base and len(base) <= 96 else base
    open_queries = unique_queries(
        [
            quoted_base,
            primary,
            secondary,
            f"{primary} review",
            f"{primary} empirical",
            f"{primary} study",
            *(f'"{term}"' for term in core_terms[:4] if " " in term),
        ]
    )
    semantic_queries = unique_queries(
        [
            base,
            primary,
            secondary,
            f"{primary} review",
            f"{primary} empirical",
            f"{primary} method",
            *core_terms[:4],
        ]
    )
    arxiv_terms = [normalize_query_token(term).replace(" ", " AND all:") for term in core_terms[:4]]
    arxiv_queries = unique_queries(
        [
            f'all:"{base}"' if base and len(base) <= 96 else "",
            f"all:{arxiv_terms[0]}" if arxiv_terms else "",
            f"all:{arxiv_terms[0]} AND all:{arxiv_terms[1]}" if len(arxiv_terms) >= 2 else "",
            f"all:{arxiv_terms[0]} AND all:{arxiv_terms[2]}" if len(arxiv_terms) >= 3 else "",
            f"all:{arxiv_terms[0]} AND all:review" if arxiv_terms else "",
        ]
    )
    return {
        "openalex": open_queries,
        "crossref": open_queries,
        "semanticscholar": semantic_queries,
        "arxiv": arxiv_queries,
    }


def scope_marker_present(scope_lower: str, marker: str, *, prefix: bool = False) -> bool:
    """Match topical markers without accidental substring hits."""
    value = (marker or "").lower().strip()
    if not value:
        return False
    if prefix:
        return value in scope_lower
    boundary = r"a-z0-9áéíóúüñ"
    return re.search(rf"(?<![{boundary}]){re.escape(value)}(?![{boundary}])", scope_lower) is not None


def scope_any_marker(scope_lower: str, markers: tuple[str, ...], *, prefix_markers: tuple[str, ...] = ()) -> bool:
    return any(scope_marker_present(scope_lower, marker, prefix=marker in prefix_markers) for marker in markers)


def query_plan(topic: str, question: str, inclusion: str = "") -> dict[str, list[str]]:
    topic_lower = (topic or "").lower()
    scope_lower = f"{topic or ''} {question or ''} {inclusion or ''}".lower()
    scope_padded = f" {scope_lower} "
    corporate_political_leadership_scope = (
        any(token in scope_lower for token in ("ideolog", "political ideology", "political orientation", "political conservatism", "political leaning"))
        and any(token in scope_lower for token in ("leadership", "liderazgo", "ceo", "executive", "top management", "tmt", "director", "corporate leader"))
        and any(token in scope_lower for token in ("firma", "firm", "corporate", "empresa", "strategic", "strategy", "decisiones", "decisions"))
    )
    if corporate_political_leadership_scope:
        return {
            "openalex": [
                '"CEO political ideology" "corporate strategy"',
                '"executive political ideology" firm',
                '"top management team" "political ideology"',
                '"CEO political conservatism" firm',
                '"CEO political orientation" "strategic decisions"',
                '"manager political ideology" "corporate decisions"',
                '"political ideology" executives "firm performance"',
                '"political ideology" "corporate social responsibility" CEO',
                '"CEO ideology" "risk taking"',
                '"CEO political ideology" innovation',
                '"executive ideology" "mergers and acquisitions"',
                '"political conservatism" "corporate governance"',
                '"political ideology" "strategic change" firm',
                '"leadership political ideology" organization',
            ],
            "crossref": [
                '"CEO political ideology" "corporate strategy"',
                '"executive political ideology" firm',
                '"top management team" "political ideology"',
                '"CEO political conservatism" firm',
                '"CEO political orientation" "strategic decisions"',
                '"manager political ideology" "corporate decisions"',
                '"political ideology" executives "firm performance"',
                '"political ideology" "corporate social responsibility" CEO',
                '"CEO ideology" "risk taking"',
                '"CEO political ideology" innovation',
                '"executive ideology" "mergers and acquisitions"',
                '"political conservatism" "corporate governance"',
                '"political ideology" "strategic change" firm',
                '"leadership political ideology" organization',
            ],
            "semanticscholar": [
                "CEO political ideology corporate strategy",
                "executive political ideology firm",
                "top management team political ideology",
                "CEO political conservatism firm",
                "CEO political orientation strategic decisions",
                "manager political ideology corporate decisions",
                "political ideology executives firm performance",
                "political ideology corporate social responsibility CEO",
                "CEO ideology risk taking",
                "CEO political ideology innovation",
                "executive ideology mergers acquisitions",
                "political conservatism corporate governance",
                "political ideology strategic change firm",
                "leadership political ideology organization",
            ],
            "arxiv": [
                'all:"CEO political ideology" AND all:"corporate strategy"',
                'all:"executive political ideology" AND all:firm',
                'all:"top management team" AND all:"political ideology"',
                'all:"CEO political conservatism" AND all:firm',
                'all:"CEO political orientation" AND all:"strategic decisions"',
                'all:"manager political ideology" AND all:"corporate decisions"',
                'all:"political ideology" AND all:executives AND all:firm',
                'all:"political ideology" AND all:"corporate social responsibility"',
                'all:"CEO ideology" AND all:"risk taking"',
                'all:"CEO political ideology" AND all:innovation',
            ],
        }
    ai_architecture_scope = (
        any(token in scope_lower for token in ("arquitectur", "architecture", "architectural"))
        and any(
            token in scope_lower
            for token in (
                "inteligencia artificial",
                "artificial intelligence",
                "llm",
                "large language model",
                "modelo fundacional",
                "foundation model",
                "rag",
                "agent",
                "agente",
                "multimodal",
                "mixture of experts",
                "moe",
                "inferencia",
                "inference",
            )
        )
        or (
            any(token in scope_lower for token in ("arquitectur", "architecture", "architectural"))
            and (" ia " in scope_padded or " ai " in scope_padded)
        )
    )
    if ai_architecture_scope:
        return {
            "openalex": [
                '"AI agents" architecture',
                '"agentic AI" architecture',
                '"LLM agents" architecture',
                '"multi-agent" "large language model"',
                '"retrieval augmented generation" architecture',
                '"RAG" "large language model" architecture',
                '"tool use" "large language model"',
                '"memory" "large language model" agents',
                '"foundation model" architecture',
                '"multimodal" "foundation model" architecture',
                '"mixture of experts" "large language model"',
                '"inference" "large language model" architecture',
                '"AI system architecture" "large language model"',
                '"agent orchestration" "large language model"',
            ],
            "crossref": [
                '"AI agents" architecture',
                '"agentic AI" architecture',
                '"LLM agents" architecture',
                '"multi-agent" "large language model"',
                '"retrieval augmented generation" architecture',
                '"RAG" "large language model" architecture',
                '"tool use" "large language model"',
                '"memory" "large language model" agents',
                '"foundation model" architecture',
                '"multimodal" "foundation model" architecture',
                '"mixture of experts" "large language model"',
                '"inference" "large language model" architecture',
                '"AI system architecture" "large language model"',
                '"agent orchestration" "large language model"',
            ],
            "semanticscholar": [
                "AI agents architecture",
                "agentic AI architecture",
                "LLM agents architecture",
                "multi-agent large language model",
                "retrieval augmented generation architecture",
                "RAG large language model architecture",
                "tool use large language model",
                "memory large language model agents",
                "foundation model architecture",
                "multimodal foundation model architecture",
                "mixture of experts large language model",
                "inference large language model architecture",
                "AI system architecture large language model",
                "agent orchestration large language model",
            ],
            "arxiv": [
                'all:"AI agents" AND all:architecture',
                'all:"agentic AI" AND all:architecture',
                'all:"LLM agents" AND all:architecture',
                'all:"multi-agent" AND all:"large language model"',
                'all:"retrieval augmented generation" AND all:architecture',
                'all:RAG AND all:"large language model" AND all:architecture',
                'all:"tool use" AND all:"large language model"',
                'all:memory AND all:"large language model" AND all:agents',
                'all:"foundation model" AND all:architecture',
                'all:multimodal AND all:"foundation model" AND all:architecture',
                'all:"mixture of experts" AND all:"large language model"',
                'all:inference AND all:"large language model" AND all:architecture',
                'all:"AI system architecture" AND all:"large language model"',
                'all:"agent orchestration" AND all:"large language model"',
            ],
        }
    higher_education_ai_teaching_scope = (
        scope_any_marker(
            scope_lower,
            (
                "artificial intelligence",
                "inteligencia artificial",
                "ia",
                "ai",
                "generative ai",
                "ia generativa",
                "large language model",
                "llm",
                "chatgpt",
                "chatbot",
                "copilot",
                "agent",
                "agente",
                "agents",
                "agentes",
            ),
        )
        and scope_any_marker(
            scope_lower,
            (
                "higher education",
                "educación superior",
                "educacion superior",
                "university",
                "universidad",
                "universitario",
                "universitarios",
                "teacher",
                "teachers",
                "docente",
                "docentes",
                "faculty",
                "profesor",
                "profesores",
                "lecturer",
                "instructor",
                "teaching",
                "enseñanza",
                "ensenanza",
            ),
            prefix_markers=("universit",),
        )
    )
    if higher_education_ai_teaching_scope:
        return {
            "openalex": [
                '"generative AI" "higher education" faculty',
                '"artificial intelligence" "university teachers"',
                '"ChatGPT" "university teaching"',
                '"large language model" "higher education" teachers',
                '"AI" "teacher feedback" "higher education"',
                '"generative AI" "teaching practices" university',
                '"artificial intelligence" "curriculum design" "higher education"',
                '"AI literacy" faculty "higher education"',
                '"AI" assessment "higher education" teachers',
                '"academic staff" "generative AI"',
                '"faculty development" "artificial intelligence"',
                '"teacher productivity" "generative AI"',
                '"AI teaching assistant" university',
                '"intelligent tutoring system" "higher education"',
            ],
            "crossref": [
                '"generative AI" "higher education" faculty',
                '"artificial intelligence" "university teachers"',
                '"ChatGPT" "university teaching"',
                '"large language model" "higher education" teachers',
                '"AI" "teacher feedback" "higher education"',
                '"generative AI" "teaching practices" university',
                '"artificial intelligence" "curriculum design" "higher education"',
                '"AI literacy" faculty "higher education"',
                '"AI" assessment "higher education" teachers',
                '"academic staff" "generative AI"',
                '"faculty development" "artificial intelligence"',
                '"teacher productivity" "generative AI"',
                '"AI teaching assistant" university',
                '"intelligent tutoring system" "higher education"',
            ],
            "semanticscholar": [
                "generative AI higher education faculty",
                "artificial intelligence university teachers",
                "ChatGPT university teaching",
                "large language model higher education teachers",
                "AI teacher feedback higher education",
                "generative AI teaching practices university",
                "artificial intelligence curriculum design higher education",
                "AI literacy faculty higher education",
                "AI assessment higher education teachers",
                "academic staff generative AI",
                "faculty development artificial intelligence",
                "teacher productivity generative AI",
                "AI teaching assistant university",
                "intelligent tutoring system higher education",
            ],
            "arxiv": [
                'all:"generative AI" AND all:"higher education" AND all:faculty',
                'all:"artificial intelligence" AND all:"university teachers"',
                'all:ChatGPT AND all:"university teaching"',
                'all:"large language model" AND all:"higher education" AND all:teachers',
                'all:AI AND all:"teacher feedback" AND all:"higher education"',
                'all:"generative AI" AND all:"teaching practices" AND all:university',
                'all:"artificial intelligence" AND all:"curriculum design" AND all:"higher education"',
                'all:"AI literacy" AND all:faculty AND all:"higher education"',
                'all:AI AND all:assessment AND all:"higher education" AND all:teachers',
                'all:"academic staff" AND all:"generative AI"',
                'all:"faculty development" AND all:"artificial intelligence"',
                'all:"teacher productivity" AND all:"generative AI"',
            ],
        }
    mind_brain_llm_scope = (
        any(token in scope_lower for token in ("llm", "large language model", "language model", "chatgpt", "transformer"))
        and scope_any_marker(
            scope_lower,
            (
                "brain",
                "cerebro",
                "mind",
                "mente",
                "neuroscience",
                "neurociencia",
                "cognition",
                "cognitive",
                "cognici",
                "neural representation",
                "fmri",
                "meg",
                "theory of mind",
            ),
            prefix_markers=("neuro", "cognici"),
        )
    )
    if mind_brain_llm_scope:
        return {
            "openalex": [
                '"large language model" brain',
                '"large language model" neuroscience',
                '"large language model" cognition',
                '"LLM" "human brain"',
                '"language model" "brain activity"',
                '"language model" fMRI',
                '"language model" "neural representations"',
                '"large language model" "cognitive science"',
                '"transformer" "human brain"',
                '"ChatGPT" cognition',
                '"LLM" "theory of mind"',
                '"brain alignment" "language model"',
            ],
            "crossref": [
                '"large language model" brain',
                '"large language model" neuroscience',
                '"large language model" cognition',
                '"LLM" "human brain"',
                '"language model" "brain activity"',
                '"language model" fMRI',
                '"language model" "neural representations"',
                '"large language model" "cognitive science"',
                '"transformer" "human brain"',
                '"ChatGPT" cognition',
                '"LLM" "theory of mind"',
                '"brain alignment" "language model"',
            ],
            "semanticscholar": [
                "large language model brain",
                "large language model neuroscience",
                "large language model cognition",
                "LLM human brain",
                "language model brain activity",
                "language model fMRI",
                "language model neural representations",
                "large language model cognitive science",
                "transformer human brain",
                "ChatGPT cognition",
                "LLM theory of mind",
                "brain alignment language model",
            ],
            "arxiv": [
                'all:"large language model" AND all:brain',
                'all:"large language model" AND all:neuroscience',
                'all:"large language model" AND all:cognition',
                'all:LLM AND all:"human brain"',
                'all:"language model" AND all:"brain activity"',
                'all:"language model" AND all:fMRI',
                'all:"neural representations" AND all:"language model"',
                'all:"large language model" AND all:"cognitive science"',
                'all:transformer AND all:"human brain"',
                'all:ChatGPT AND all:cognition',
                'all:LLM AND all:"theory of mind"',
            ],
        }
    education_agents_scope = (
        any(token in scope_lower for token in ("agent", "agente", "agents", "agentes", "ai tutor", "teaching assistant"))
        and any(
            token in scope_lower
            for token in (
                "education",
                "educaci",
                "higher education",
                "university",
                "universit",
                "teacher",
                "teaching",
                "profesor",
                "docente",
                "classroom",
                "aula",
            )
        )
    )
    if education_agents_scope:
        return {
            "openalex": [
                '"AI agents" "higher education"',
                '"LLM agents" education',
                '"AI teaching assistant" university',
                '"intelligent tutoring system" "higher education"',
                '"pedagogical agent" university',
                '"educational agents" "higher education"',
                '"generative AI" "teaching quality"',
                '"AI agents" teachers',
                '"LLM" "teacher feedback"',
                '"AI tutor" university',
                '"multi-agent" education',
                '"learning analytics" "AI agents"',
            ],
            "crossref": [
                '"AI agents" "higher education"',
                '"LLM agents" education',
                '"AI teaching assistant" university',
                '"intelligent tutoring system" "higher education"',
                '"pedagogical agent" university',
                '"educational agents" "higher education"',
                '"generative AI" "teaching quality"',
                '"AI agents" teachers',
                '"LLM" "teacher feedback"',
                '"AI tutor" university',
                '"multi-agent" education',
                '"learning analytics" "AI agents"',
            ],
            "semanticscholar": [
                "AI agents higher education",
                "LLM agents education",
                "AI teaching assistant university",
                "intelligent tutoring system higher education",
                "pedagogical agent university",
                "educational agents higher education",
                "generative AI teaching quality",
                "AI agents teachers",
                "LLM teacher feedback",
                "AI tutor university",
                "multi-agent education",
                "learning analytics AI agents",
            ],
            "arxiv": [
                'all:"AI agents" AND all:"higher education"',
                'all:"LLM agents" AND all:education',
                'all:"AI teaching assistant" AND all:university',
                'all:"intelligent tutoring system" AND all:"higher education"',
                'all:"pedagogical agent" AND all:university',
                'all:"educational agents" AND all:"higher education"',
                'all:"generative AI" AND all:"teaching quality"',
                'all:"AI agents" AND all:teachers',
                'all:LLM AND all:"teacher feedback"',
                'all:"AI tutor" AND all:university',
                'all:"multi-agent" AND all:education',
            ],
        }
    if is_creativity_llm_topic(topic, question):
        return {
            "openalex": [
                '"large language model" creativity',
                '"LLM" creativity',
                '"generative AI" creativity',
                '"creative writing" "large language model"',
                '"divergent thinking" "large language model"',
                '"creative problem solving" "large language model"',
                '"creativity evaluation" "large language model"',
                '"human creativity" "ChatGPT"',
                '"creatividad" "modelos de lenguaje"',
                '"criatividade" "modelos de linguagem"',
            ],
            "crossref": [
                '"large language model" creativity',
                '"LLM" creativity',
                '"generative AI" creativity',
                '"creative writing" "large language model"',
                '"divergent thinking" "large language model"',
                '"creative problem solving" "large language model"',
                '"creativity evaluation" "large language model"',
                '"human creativity" "ChatGPT"',
                '"creatividad" "modelos de lenguaje"',
                '"criatividade" "modelos de linguagem"',
            ],
            "semanticscholar": [
                "large language model creativity",
                "LLM creativity",
                "generative AI creativity",
                "creative writing large language model",
                "divergent thinking large language model",
                "creative problem solving large language model",
                "creativity evaluation large language model",
                "ChatGPT creativity",
                "creatividad modelos de lenguaje",
                "criatividade modelos de linguagem",
            ],
            "arxiv": [
                'all:"large language model" AND all:creativity',
                'all:LLM AND all:creativity',
                'all:"generative AI" AND all:creativity',
                'all:"creative writing" AND all:"large language model"',
                'all:"divergent thinking" AND all:"large language model"',
                'all:"creative problem solving" AND all:"large language model"',
                'all:"creativity evaluation" AND all:"large language model"',
                'all:ChatGPT AND all:creativity',
            ],
        }
    if "personalidad" in topic_lower and any(token in topic_lower for token in ("razonador", "reasoning", "reasoner", "razonamiento")):
        return {
            "openalex": [
                '"reasoning model" personality',
                '"reasoning language model" personality',
                '"reasoning llm" personality',
                '"personality traits" "reasoning model"',
                '"persona" "reasoning model"',
            ],
            "crossref": [
                '"reasoning model" personality',
                '"reasoning language model" personality',
                '"reasoning llm" personality',
                '"personality traits" "reasoning model"',
                '"persona" "reasoning model"',
            ],
            "semanticscholar": [
                'reasoning model personality',
                'reasoning language model personality',
                'reasoning llm personality',
                'personality traits reasoning model',
            ],
            "arxiv": [
                'all:"reasoning model" AND all:personality',
                'all:"reasoning language model" AND all:personality',
                'all:"reasoning llm" AND all:personality',
                'all:"personality traits" AND all:"reasoning model"',
            ],
        }
    if "personalidad" in topic_lower and ("llm" in topic_lower or "language model" in topic_lower or "modelo de lenguaje" in topic_lower):
        return {
            "openalex": [
                '"large language model" personality',
                '"llm personality"',
                '"personality traits" llm',
                '"language model persona"',
                '"persona" "large language model"',
            ],
            "crossref": [
                '"large language model" personality',
                '"llm personality"',
                '"personality traits" "language model"',
                '"language model persona"',
                '"persona" "llm"',
            ],
            "semanticscholar": [
                'large language model personality',
                'llm personality',
                'personality traits language model',
                'persona llm',
            ],
            "arxiv": [
                'all:"large language model" AND all:personality',
                'all:llm AND all:personality',
                'all:"personality traits" AND all:"language model"',
                'all:persona AND all:llm',
            ],
        }
    if (
        ("multiagente" in topic_lower or "multi-agent" in topic_lower or "multi agent" in topic_lower)
        and ("software" in topic_lower or "ingeniería del software" in topic_lower or "software engineering" in topic_lower or "desarrollo de software" in topic_lower)
    ):
        return {
            "openalex": [
                '"multi-agent" software development architecture',
                '"multi-agent system" software engineering',
                '"orchestrated agents" coding software',
                '"multi-agent coding" architecture',
                '"agent delegation" software engineering',
            ],
            "crossref": [
                '"multi-agent" "software development"',
                '"multi-agent system" "software engineering"',
                '"orchestrated agents" coding',
                '"agent delegation" "software engineering"',
                '"multi-agent coding" architecture',
            ],
            "semanticscholar": [
                'multi-agent software development architecture',
                'multi-agent system software engineering',
                'orchestrated agents coding software',
                'agent delegation software engineering',
            ],
            "arxiv": [
                'all:"multi-agent" AND all:"software development"',
                'all:"multi-agent system" AND all:"software engineering"',
                'all:"orchestrated agents" AND all:coding',
                'all:"agent delegation" AND all:"software engineering"',
            ],
        }
    if (
        ("framework" in topic_lower or "frameworks" in topic_lower or "marco" in topic_lower or "marcos" in topic_lower)
        and ("arquitectur" in topic_lower or "architecture" in topic_lower)
        and ("agente" in topic_lower or "agent" in topic_lower)
    ):
        return {
            "openalex": [
                '"agent architecture framework" software',
                '"multi-agent framework" software engineering architecture',
                '"agentic framework" coding architecture',
                '"software agent framework" architecture',
                '"orchestration framework" "software agents"',
            ],
            "crossref": [
                '"agent architecture framework" software',
                '"multi-agent framework" "software engineering"',
                '"software agent framework" architecture',
                '"agentic framework" coding architecture',
                '"orchestration framework" "software agents"',
            ],
            "semanticscholar": [
                'agent architecture framework software',
                'multi-agent framework software engineering architecture',
                'software agent framework architecture',
                'agentic framework coding architecture',
            ],
            "arxiv": [
                'all:"agent architecture framework" AND all:software',
                'all:"multi-agent framework" AND all:"software engineering"',
                'all:"software agent framework" AND all:architecture',
                'all:"agentic framework" AND all:coding',
            ],
        }
    if "arquitectur" in topic_lower and ("agente" in topic_lower or "agent" in topic_lower):
        return {
            "openalex": [
                '"agent architecture" software development',
                '"multi-agent architecture" software engineering',
                '"agent orchestration" coding software',
                '"agentic software engineering" architecture',
                '"coding agent framework" software development',
            ],
            "crossref": [
                '"agent architecture" "software development"',
                '"multi-agent architecture" "software engineering"',
                '"agent orchestration" coding',
                '"agentic software engineering" architecture',
                '"autonomous software development" architecture',
            ],
            "semanticscholar": [
                'agent architecture software development',
                'multi-agent architecture software engineering',
                'agent orchestration coding software',
            ],
            "arxiv": [
                'all:"agent architecture" AND all:"software development"',
                'all:"multi-agent architecture" AND all:"software engineering"',
                'all:"agent orchestration" AND all:coding',
            ],
        }
    return generic_query_plan(topic, question, inclusion)


def normalize_plan(raw_plan: dict[str, list[str]] | None) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {}
    for source in SOURCE_QUERY_LIMITS:
        values = (raw_plan or {}).get(source) or []
        plan[source] = unique_queries([str(value) for value in values], limit=SOURCE_QUERY_LIMITS[source])
    return plan


def source_queries_from_stage(stage: dict[str, object]) -> dict[str, list[str]]:
    raw = stage.get("queries_by_source") or stage.get("queries") or {}
    if not isinstance(raw, dict):
        return normalize_plan({})
    return normalize_plan({source: list(raw.get(source) or []) for source in SOURCE_QUERY_LIMITS})


def is_corporate_political_leadership_scope(topic: str, question: str, inclusion: str = "") -> bool:
    scope_lower = f"{topic or ''} {question or ''} {inclusion or ''}".lower()
    return (
        any(token in scope_lower for token in ("ideolog", "political ideology", "political orientation", "political conservatism", "political leaning"))
        and any(token in scope_lower for token in ("leadership", "liderazgo", "ceo", "executive", "top management", "tmt", "director", "corporate leader"))
        and any(token in scope_lower for token in ("firma", "firm", "corporate", "empresa", "strategic", "strategy", "decisiones", "decisions"))
    )


def corporate_political_staged_decomposition(
    topic: str,
    question: str,
    inclusion: str,
    exclusion: str,
    fallback_plan: dict[str, list[str]],
) -> dict[str, object]:
    stage_templates = [
        {
            "stage_id": "S1",
            "name": "Liderazgo corporativo + ideología política",
            "purpose": "Capturar estudios donde la ideología, orientación partidista, conservadurismo o donaciones políticas se atribuyen a CEO, ejecutivos, TMT, fundadores o consejo.",
            "axis_covered": ["liderazgo corporativo", "ideología política"],
            "base_queries": [
                '"CEO political ideology"',
                '"executive political ideology" firm',
                '"top management team" "political ideology"',
                '"CEO political conservatism" firm',
                '"CEO political orientation"',
                '"campaign contributions" CEO firm',
                '"political donations" executives',
                '"party affiliation" executives',
            ],
        },
        {
            "stage_id": "S2",
            "name": "Ideología + decisiones estratégicas de firma",
            "purpose": "Abrir el abanico de decisiones estratégicas sin perder el eje político: inversión, innovación, riesgo, M&A, diversificación, CSR/ESG, disclosure, impuestos, lobbying y gobierno corporativo.",
            "axis_covered": ["ideología política", "decisiones estratégicas"],
            "base_queries": [
                '"CEO political ideology" innovation',
                '"CEO ideology" "risk taking"',
                '"executive ideology" "mergers and acquisitions"',
                '"political ideology" "corporate social responsibility" CEO',
                '"political conservatism" "corporate governance"',
                '"political ideology" "strategic change" firm',
                '"CEO political ideology" "tax avoidance"',
                '"executive political ideology" disclosure',
                '"political ideology" "capital structure" CEO',
                '"corporate political activity" CEO ideology',
            ],
        },
        {
            "stage_id": "S3",
            "name": "Proxies empíricos y bases de datos",
            "purpose": "Localizar trabajos empíricos que usan donaciones, afiliación partidista, FEC, ExecuComp, BoardEx, paneles firm-year o datos archivales como medición de ideología del liderazgo.",
            "axis_covered": ["medición", "diseño empírico"],
            "base_queries": [
                '"CEO" "campaign contributions" "firm"',
                '"executive" "campaign contributions" "corporate"',
                '"CEO political donations" "firm performance"',
                '"ExecuComp" "political ideology"',
                '"FEC" "CEO" "firm"',
                '"BoardEx" "political ideology"',
                '"firm-year" "political ideology" CEO',
                '"archival" "CEO political ideology"',
            ],
        },
        {
            "stage_id": "S4",
            "name": "Frontera de inclusión empírica",
            "purpose": "Recuperar estudios con señal metodológica fuerte para no confundir comentarios, teoría política general o ideología de consumidores con evidencia sobre liderazgo corporativo.",
            "axis_covered": ["evidencia empírica", "criterios de inclusión"],
            "base_queries": [
                '"political ideology" executives regression firm',
                '"CEO political ideology" empirical',
                '"executive political ideology" panel data',
                '"manager political ideology" empirical firm',
                '"political conservatism" executives empirical',
                '"political ideology" corporate decisions empirical',
            ],
        },
    ]
    stages: list[dict[str, object]] = []
    for template in stage_templates:
        semantic = [query.replace('"', "") for query in template["base_queries"]]
        arxiv = []
        for query in template["base_queries"]:
            parts = [part.strip() for part in re.findall(r'"([^"]+)"|(\b[A-Za-z0-9&-]{3,}\b)', query) for part in part if part.strip()]
            if not parts:
                continue
            arxiv.append(" AND ".join(f'all:"{part}"' if " " in part else f"all:{part}" for part in parts[:4]))
        stages.append(
            {
                "stage_id": template["stage_id"],
                "name": template["name"],
                "purpose": template["purpose"],
                "axis_covered": template["axis_covered"],
                "queries_by_source": {
                    "openalex": template["base_queries"],
                    "crossref": template["base_queries"],
                    "semanticscholar": semantic,
                    "arxiv": arxiv,
                },
            }
        )
    if fallback_plan:
        stages.append(
            {
                "stage_id": "S5",
                "name": "Cobertura heredada y control de sensibilidad",
                "purpose": "Conservar las ecuaciones del plan base como control de sensibilidad para no perder literatura por una descomposición demasiado estrecha.",
                "axis_covered": ["cobertura", "sensibilidad"],
                "queries_by_source": fallback_plan,
            }
        )
    return {
        "planner": "deterministic-domain-profile",
        "planner_model": "",
        "question": question,
        "topic": topic,
        "question_axes": {
            "population_context": ["liderazgo corporativo", "CEO", "ejecutivos", "TMT", "consejo", "fundadores"],
            "exposure_construct": ["ideología política", "orientación política", "conservadurismo/liberalismo", "partidismo", "donaciones políticas"],
            "outcome_decision": ["decisiones estratégicas", "inversión", "innovación", "riesgo", "M&A", "CSR/ESG", "disclosure", "impuestos", "lobbying", "gobierno corporativo"],
            "evidence_method": ["evidencia empírica", "regresión", "panel", "datos archivales", "firm-year", "FEC/ExecuComp/BoardEx"],
            "boundaries": [inclusion, exclusion],
        },
        "search_stages": stages,
    }


def arxiv_query_from_phrase(query: str) -> str:
    parts = [
        part.strip()
        for part in re.findall(r'"([^"]+)"|(\b[A-Za-z0-9&+-]{3,}\b)', query)
        for part in part
        if part.strip()
    ]
    if not parts:
        return ""
    return " AND ".join(f'all:"{part}"' if " " in part else f"all:{part}" for part in parts[:4])


def source_query_bundle(queries: list[str]) -> dict[str, list[str]]:
    clean = unique_queries(queries, limit=10)
    semantic = [query.replace('"', "") for query in clean]
    arxiv = unique_queries([arxiv_query_from_phrase(query) for query in clean], limit=8)
    return {
        "openalex": clean,
        "crossref": clean,
        "semanticscholar": semantic,
        "arxiv": arxiv,
        "openaire": clean,
        "lens": clean,
    }


def mode_stage_templates(
    mode_decision: dict[str, object],
    base: str,
    axis_a: list[str],
    axis_b: list[str],
    mode_axes: list[str],
) -> list[dict[str, object]]:
    mode = str(mode_decision.get("primary_mode") or mode_decision.get("mode") or "")
    quoted_base = f'"{base}"' if base and len(base) <= 96 else base
    anchor_a = axis_a[0] if axis_a else base
    anchor_b = axis_b[0] if axis_b else base
    mode_map: dict[str, list[tuple[str, str, list[str], list[str]]]] = {
        "management": [
            (
                "Teoría, constructos y variables",
                "Localizar estudios que declaran teoría, constructos, variables o mecanismos organizativos.",
                ["theory", "construct", "variable", "mechanism", "mediator", "moderator"],
                ["teoría", "constructos", "variables", "mecanismos"],
            ),
            (
                "Contexto, muestra y método de management",
                "Recuperar evidencia con empresa, sector, país, muestra, panel, encuesta, caso o identificación empírica.",
                ["empirical", "survey", "panel data", "regression", "case study", "endogeneity", "robustness"],
                ["contexto", "muestra", "método", "endogeneidad"],
            ),
            (
                "Resultados estratégicos y límites causales",
                "Abrir resultados estratégicos sin convertir asociación en causalidad no demostrada.",
                ["strategic outcome", "firm performance", "decision", "causal", "identification", "baseline"],
                ["resultado", "decisión", "causalidad", "comparador"],
            ),
        ],
        "education": [
            (
                "Actividad pedagógica y actores",
                "Capturar nivel educativo, profesorado, estudiantes, actividad docente y práctica pedagógica.",
                ["teacher", "faculty", "student", "teaching", "learning", "pedagogy", "higher education"],
                ["actores", "actividad pedagógica", "nivel educativo"],
            ),
            (
                "Resultado educativo y evaluación",
                "Buscar aprendizaje, evaluación, feedback, currículo, calidad docente, adopción y equidad.",
                ["learning outcome", "assessment", "feedback", "curriculum", "teaching quality", "adoption", "equity"],
                ["resultado educativo", "evaluación", "feedback", "equidad"],
            ),
            (
                "Diseño empírico educativo",
                "Diferenciar intervención, encuesta, estudio de caso, diseño mixto, revisión y marco conceptual.",
                ["intervention", "survey", "case study", "mixed methods", "qualitative", "experimental", "review"],
                ["diseño", "método", "contexto institucional"],
            ),
        ],
        "social_sciences": [
            (
                "Constructo, fenómeno y población",
                "Representar fenómeno social, constructo, población, caso y contexto.",
                ["construct", "phenomenon", "population", "context", "attitudes", "perceptions", "behavior"],
                ["constructo", "fenómeno", "población", "contexto"],
            ),
            (
                "Método y evidencia social",
                "Cubrir diseños cuantitativos, cualitativos, mixtos, entrevistas, encuestas, etnografía y casos.",
                ["qualitative", "interview", "survey", "ethnography", "case study", "mixed methods", "quantitative"],
                ["método", "evidencia", "reflexividad"],
            ),
            (
                "Mecanismo, transferencia y límites",
                "Recuperar estudios que discuten mecanismos, teoría, transferibilidad y límites de inferencia.",
                ["mechanism", "theory", "transferability", "validity", "reflexivity", "limitations"],
                ["mecanismo", "teoría", "transferibilidad", "límites"],
            ),
        ],
        "biomedical": [
            (
                "Población, exposición/intervención y outcome",
                "Representar PICO/PICOS sin perder población, exposición, intervención, comparador y outcome.",
                ["population", "intervention", "exposure", "comparator", "outcome", "clinical"],
                ["población", "intervención/exposición", "outcome"],
            ),
            (
                "Diseño y riesgo de sesgo",
                "Recuperar ensayos, cohortes, casos-control, estudios observacionales, revisiones y riesgo de sesgo.",
                ["trial", "cohort", "case-control", "observational", "systematic review", "risk of bias"],
                ["diseño", "riesgo de sesgo"],
            ),
        ],
        "technical": [
            (
                "Sistema, arquitectura y componentes",
                "Capturar sistemas, arquitectura, componentes, pipeline, memoria, herramientas, recuperación y orquestación.",
                ["architecture", "system", "pipeline", "component", "memory", "tool use", "orchestration", "retrieval"],
                ["sistema", "arquitectura", "componentes"],
            ),
            (
                "Benchmark, dataset y métrica",
                "Recuperar evaluación técnica, datasets, benchmarks, métricas, robustez, coste, latencia y reproducibilidad.",
                ["benchmark", "dataset", "metric", "evaluation", "robustness", "latency", "cost", "reproducibility"],
                ["benchmark", "métrica", "reproducibilidad"],
            ),
        ],
    }
    templates = mode_map.get(mode, [])
    stages: list[dict[str, object]] = []
    for offset, (name, purpose, qualifiers, axes) in enumerate(templates, start=3):
        queries: list[str] = []
        for qualifier in qualifiers:
            queries.extend(
                [
                    f"{quoted_base} {qualifier}".strip(),
                    f'"{anchor_a}" {qualifier}'.strip() if anchor_a and len(anchor_a) <= 72 else f"{anchor_a} {qualifier}".strip(),
                    f'"{anchor_a}" "{anchor_b}" {qualifier}'.strip() if anchor_a and anchor_b and len(anchor_a) <= 48 and len(anchor_b) <= 48 else "",
                ]
            )
        stages.append(
            {
                "stage_id": f"S{offset}",
                "name": name,
                "purpose": purpose,
                "axis_covered": unique_queries([*axes, *mode_axes[:3]], limit=8),
                "queries_by_source": source_query_bundle(queries),
            }
        )
    return stages


def generic_staged_decomposition(
    topic: str,
    question: str,
    inclusion: str,
    exclusion: str,
    fallback_plan: dict[str, list[str]],
    mode_decision: dict[str, object] | None = None,
) -> dict[str, object]:
    terms = generic_search_terms(topic, question, inclusion, limit=8)
    base = compact_query_text(topic or question or "systematic review topic")
    axis_a = terms[:3] or [base]
    axis_b = terms[3:6] or terms[:3] or [base]
    mode_decision = mode_decision or {}
    mode_axes = [str(item) for item in mode_decision.get("screening_axes", [])[:6]] if isinstance(mode_decision.get("screening_axes"), list) else []
    framework = str(mode_decision.get("default_framework") or "")
    mode_label = str(mode_decision.get("mode_label") or "modo genérico")
    stage_one = unique_queries([base, " ".join(axis_a), f"{' '.join(axis_a)} empirical"], limit=8)
    stage_two = unique_queries([f"{' '.join(axis_a[:2])} {' '.join(axis_b[:2])}", f"{base} method", f"{base} evidence"], limit=8)
    mode_stages = mode_stage_templates(mode_decision, base, axis_a, axis_b, mode_axes)
    coverage_stage_id = f"S{len(mode_stages) + 3}"
    stages = [
        {
            "stage_id": "S1",
            "name": f"Núcleo de la pregunta ({mode_label})",
            "purpose": "Recuperar registros que representen el eje central de la pregunta de investigación y su marco disciplinar.",
            "axis_covered": axis_a,
            "queries_by_source": {
                "openalex": stage_one,
                "crossref": stage_one,
                "semanticscholar": [query.replace('"', "") for query in stage_one],
                "arxiv": [f'all:"{query}"' if " " in query else f"all:{query}" for query in stage_one[:5]],
            },
        },
        {
            "stage_id": "S2",
            "name": "Relación, método y evidencia disciplinar",
            "purpose": "Añadir términos de relación, método, resultado y evidencia para evitar búsquedas decorativas basadas solo en tema.",
            "axis_covered": unique_queries([*axis_b, *mode_axes[:3]], limit=8),
            "queries_by_source": {
                "openalex": stage_two,
                "crossref": stage_two,
                "semanticscholar": [query.replace('"', "") for query in stage_two],
                "arxiv": [f'all:"{query}"' if " " in query else f"all:{query}" for query in stage_two[:5]],
            },
        },
        *mode_stages,
        {
            "stage_id": coverage_stage_id,
            "name": "Cobertura base y sensibilidad",
            "purpose": "Conservar las consultas del plan base como cobertura transversal y control de sensibilidad.",
            "axis_covered": ["cobertura", "sensibilidad"],
            "queries_by_source": fallback_plan,
        },
    ]
    return {
        "planner": "deterministic-generic-profile",
        "planner_model": "",
        "question": question,
        "topic": topic,
        "review_mode": mode_decision.get("mode") or "",
        "review_mode_label": mode_decision.get("mode_label") or "",
        "question_framework": framework,
        "question_axes": {
            "population_context": axis_a,
            "exposure_construct": axis_b,
            "outcome_decision": [],
            "evidence_method": ["empirical", "method", "evidence"],
            "disciplinary_axes": mode_axes,
            "boundaries": [inclusion, exclusion],
        },
        "search_stages": stages,
    }


def search_planner_prompt(
    topic: str,
    question: str,
    inclusion: str,
    exclusion: str,
    fallback_plan: dict[str, list[str]],
    mode_decision: dict[str, object] | None = None,
) -> str:
    mode_decision = mode_decision or {}
    return "\n".join(
        [
            "Descompón esta pregunta de revisión sistemática en estadios de búsqueda auditables.",
            "La búsqueda debe representar el 100% de la pregunta: población/contexto, exposición o constructo, relación, resultado/decisión, método/evidencia y fronteras de exclusión.",
            "Respeta el modo metodológico declarado por Hermes. No uses un molde biomédico para preguntas técnicas, sociales, educativas o de management si no corresponde.",
            "No conviertas la pregunta en una lista plana de palabras. Cada estadio debe tener una función metodológica clara.",
            "No inventes ventanas temporales, límites de fecha ni criterios no indicados; conserva literalmente la inclusión y exclusión dadas.",
            "Usa solo estas fuentes: openalex, crossref, semanticscholar, arxiv, openaire, europepmc, pubmed, lens.",
            "OpenAlex, Crossref, OpenAIRE y Lens pueden usar frases; Semantic Scholar, Europe PMC y PubMed deben ir sin operadores excesivamente complejos; arXiv debe usar all: y AND.",
            "Devuelve JSON válido con esta forma exacta:",
            '{"planner":"llm-search-decomposition","question":"...","topic":"...","question_axes":{"population_context":[],"exposure_construct":[],"outcome_decision":[],"evidence_method":[],"boundaries":[]},"search_stages":[{"stage_id":"S1","name":"...","purpose":"...","axis_covered":[],"queries_by_source":{"openalex":[],"crossref":[],"semanticscholar":[],"arxiv":[],"openaire":[],"europepmc":[],"pubmed":[],"lens":[]}}]}',
            "",
            f"Tema: {topic}",
            f"Pregunta: {question}",
            f"Inclusión: {inclusion}",
            f"Exclusión: {exclusion}",
            f"Modo metodológico: {json.dumps(mode_decision, ensure_ascii=False)}",
            f"Plan base para no perder sensibilidad: {json.dumps(fallback_plan, ensure_ascii=False)}",
        ]
    )


def normalize_search_decomposition(raw: dict | None, fallback: dict[str, object]) -> dict[str, object]:
    if not isinstance(raw, dict):
        return fallback
    stages_raw = raw.get("search_stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        return fallback
    normalized_stages: list[dict[str, object]] = []
    for index, stage in enumerate(stages_raw[:8], start=1):
        if not isinstance(stage, dict):
            continue
        queries = source_queries_from_stage(stage)
        if not any(queries.values()):
            continue
        normalized_stages.append(
            {
                "stage_id": str(stage.get("stage_id") or f"S{index}"),
                "name": str(stage.get("name") or f"Estadio {index}"),
                "purpose": str(stage.get("purpose") or "Cobertura de la pregunta de investigación."),
                "axis_covered": stage.get("axis_covered") if isinstance(stage.get("axis_covered"), list) else [str(stage.get("axis_covered") or "")],
                "queries_by_source": queries,
            }
        )
    if not normalized_stages:
        return fallback
    axes = raw.get("question_axes") if isinstance(raw.get("question_axes"), dict) else fallback.get("question_axes", {})
    fallback_axes = fallback.get("question_axes", {}) if isinstance(fallback.get("question_axes"), dict) else {}
    axes = dict(axes) if isinstance(axes, dict) else {}
    # The model may decompose the question, but the intake owns the hard boundaries.
    if fallback_axes.get("boundaries"):
        axes["boundaries"] = fallback_axes["boundaries"]
    return {
        "planner": str(raw.get("planner") or "llm-search-decomposition"),
        "planner_model": str(raw.get("planner_model") or ""),
        "question": str(raw.get("question") or fallback.get("question") or ""),
        "topic": str(raw.get("topic") or fallback.get("topic") or ""),
        "question_axes": axes,
        "search_stages": normalized_stages,
    }


def build_deterministic_search_decomposition(
    topic: str,
    question: str,
    inclusion: str,
    exclusion: str,
    mode_decision: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the reproducible search plan without waiting for a model call."""
    mode_decision = mode_decision or infer_review_mode(topic=topic, question=question, inclusion=inclusion, exclusion=exclusion)
    fallback_plan = normalize_plan(query_plan(topic, question, inclusion))
    if is_corporate_political_leadership_scope(topic, question, inclusion):
        fallback = corporate_political_staged_decomposition(topic, question, inclusion, exclusion, fallback_plan)
    else:
        fallback = generic_staged_decomposition(topic, question, inclusion, exclusion, fallback_plan, mode_decision)
    fallback["review_mode"] = mode_decision.get("mode") or fallback.get("review_mode", "")
    fallback["review_mode_label"] = mode_decision.get("mode_label") or fallback.get("review_mode_label", "")
    fallback["question_framework"] = mode_decision.get("default_framework") or fallback.get("question_framework", "")
    return fallback


def build_search_decomposition(
    topic: str,
    question: str,
    inclusion: str,
    exclusion: str,
    mode_decision: dict[str, object] | None = None,
) -> dict[str, object]:
    """Refine the deterministic plan with the configured cloud planner."""
    mode_decision = mode_decision or infer_review_mode(topic=topic, question=question, inclusion=inclusion, exclusion=exclusion)
    fallback = build_deterministic_search_decomposition(
        topic,
        question,
        inclusion,
        exclusion,
        mode_decision,
    )
    fallback_plan = normalize_plan(query_plan(topic, question, inclusion))
    raw = call_search_planner_llm(search_planner_prompt(topic, question, inclusion, exclusion, fallback_plan, mode_decision))
    normalized = normalize_search_decomposition(raw, fallback)
    normalized["review_mode"] = mode_decision.get("mode") or normalized.get("review_mode", "")
    normalized["review_mode_label"] = mode_decision.get("mode_label") or normalized.get("review_mode_label", "")
    normalized["question_framework"] = mode_decision.get("default_framework") or normalized.get("question_framework", "")
    if normalized is not fallback and fallback_plan:
        # Keep the deterministic base as a sensitivity stage. LLM planners can be
        # precise but occasionally omit a synonym family; this guard preserves recall.
        stages = list(normalized.get("search_stages") or [])
        stages.append(
            {
                "stage_id": f"S{len(stages) + 1}",
                "name": "Control de sensibilidad determinista",
                "purpose": "Añadir las ecuaciones del perfil determinista para proteger cobertura y reproducibilidad.",
                "axis_covered": ["sensibilidad", "recall"],
                "queries_by_source": fallback_plan,
            }
        )
        normalized["search_stages"] = stages
    return normalized


def flatten_search_plan(decomposition: dict[str, object]) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {source: [] for source in SOURCE_QUERY_LIMITS}
    stages = decomposition.get("search_stages") if isinstance(decomposition, dict) else []
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        stage_plan = source_queries_from_stage(stage)
        for source, queries in stage_plan.items():
            plan[source].extend(queries)
    return {source: unique_queries(queries, limit=SOURCE_QUERY_LIMITS[source]) for source, queries in plan.items()}


def stage_queries_filtered_by_plan(stage: dict[str, object], plan: dict[str, list[str]] | None) -> dict[str, list[str]]:
    """Return only stage queries that are still present in the executable plan."""

    stage_plan = source_queries_from_stage(stage)
    if plan is None:
        return stage_plan
    filtered: dict[str, list[str]] = {}
    plan_sets = {source: set(queries) for source, queries in plan.items() if queries}
    for source, queries in stage_plan.items():
        allowed = plan_sets.get(source)
        if not allowed:
            continue
        kept = [query for query in queries if query in allowed]
        if kept:
            filtered[source] = kept
    return filtered


def sanitize_decomposition_for_plan(decomposition: dict[str, object], plan: dict[str, list[str]]) -> dict[str, object]:
    """Remove source queries that the mode-aware executable plan has disabled."""

    sanitized = json.loads(json.dumps(decomposition, ensure_ascii=False))
    stages = sanitized.get("search_stages") if isinstance(sanitized, dict) else []
    if not isinstance(stages, list):
        return sanitized
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        queries_by_source = stage.get("queries_by_source")
        if not isinstance(queries_by_source, dict):
            continue
        filtered = stage_queries_filtered_by_plan(stage, plan)
        stage["queries_by_source"] = {source: filtered.get(source, []) for source in SOURCE_QUERY_LIMITS}
    return sanitized


def extend_search_plan(
    plan: dict[str, list[str]],
    topic: str,
    question: str,
    inclusion: str,
    mode_decision: dict[str, object] | None = None,
) -> dict[str, list[str]]:
    """Backfill adaptive sources without forcing every engine on every topic."""
    extended = normalize_plan(plan)
    mode = str((mode_decision or {}).get("primary_mode") or (mode_decision or {}).get("mode") or "")
    broad_queries = unique_queries(
        [
            *extended.get("openalex", []),
            *extended.get("crossref", []),
            *extended.get("semanticscholar", []),
        ],
        limit=28,
    )
    if broad_queries and not extended.get("openaire"):
        extended["openaire"] = unique_queries(broad_queries, limit=SOURCE_QUERY_LIMITS["openaire"])
    if broad_queries and not extended.get("lens"):
        extended["lens"] = unique_queries(broad_queries, limit=SOURCE_QUERY_LIMITS["lens"])

    if not optional_source_key("SEMANTIC_SCHOLAR_API_KEY", "HERMES_SEMANTIC_SCHOLAR_API_KEY") and not env_flag("HERMES_ENABLE_SEMANTIC_SCHOLAR"):
        extended["semanticscholar"] = []

    specialist_relevant = mode == "biomedical" or biomedical_source_relevant(topic, question, inclusion)
    if env_flag("HERMES_ENABLE_EUROPEPMC") or specialist_relevant:
        if broad_queries and not extended.get("europepmc"):
            extended["europepmc"] = unique_queries(broad_queries, limit=SOURCE_QUERY_LIMITS["europepmc"])
    else:
        extended["europepmc"] = []
    if env_flag("HERMES_ENABLE_PUBMED") or specialist_relevant:
        if broad_queries and not extended.get("pubmed"):
            extended["pubmed"] = unique_queries(broad_queries, limit=SOURCE_QUERY_LIMITS["pubmed"])
    else:
        extended["pubmed"] = []

    if not (env_flag("HERMES_ENABLE_ARXIV") or mode == "technical" or arxiv_source_relevant(topic, question, inclusion)):
        extended["arxiv"] = []

    if env_flag("HERMES_DISABLE_SEMANTIC_SCHOLAR"):
        extended["semanticscholar"] = []
    if env_flag("HERMES_DISABLE_ARXIV"):
        extended["arxiv"] = []
    if env_flag("HERMES_DISABLE_LENS"):
        extended["lens"] = []
    if env_flag("HERMES_DISABLE_OPENAIRE"):
        extended["openaire"] = []
    if env_flag("HERMES_DISABLE_EUROPEPMC"):
        extended["europepmc"] = []
    if env_flag("HERMES_DISABLE_PUBMED"):
        extended["pubmed"] = []
    return extended


def search_stage_rows(decomposition: dict[str, object], plan: dict[str, list[str]] | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    stages = decomposition.get("search_stages") if isinstance(decomposition, dict) else []
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("stage_id") or "")
        stage_name = str(stage.get("name") or "")
        purpose = str(stage.get("purpose") or "")
        axis_raw = stage.get("axis_covered") or []
        axis = "; ".join(str(item) for item in axis_raw if str(item).strip()) if isinstance(axis_raw, list) else str(axis_raw)
        for source, queries in stage_queries_filtered_by_plan(stage, plan).items():
            for query in queries:
                seen.add((source, query))
                rows.append(
                    {
                        "stage_id": stage_id,
                        "stage_name": stage_name,
                        "source": source,
                        "query_string": query,
                        "axis_covered": axis,
                        "purpose": purpose,
                    }
                )
    for source, queries in (plan or {}).items():
        for query in queries:
            if (source, query) in seen:
                continue
            rows.append(
                {
                    "stage_id": "ADAPT",
                    "stage_name": "Cobertura adaptativa por fuente",
                    "source": source,
                    "query_string": query,
                    "axis_covered": "cobertura; sensibilidad; fuente especializada",
                    "purpose": "Consulta añadida por Hermes para ampliar cobertura sin perder la representación de la pregunta.",
                }
            )
    return rows


def render_search_decomposition_markdown(decomposition: dict[str, object], plan: dict[str, list[str]]) -> str:
    axes = decomposition.get("question_axes") if isinstance(decomposition.get("question_axes"), dict) else {}
    lines = [
        "# Descomposición semántica de la búsqueda",
        "",
        f"- Planner: {decomposition.get('planner', 'no reportado')}",
        f"- Modelo: {decomposition.get('planner_model', '') or 'perfil determinista / fallback'}",
        f"- Tema: {decomposition.get('topic', '')}",
        f"- Pregunta: {decomposition.get('question', '')}",
        "",
        "## Ejes obligatorios de la pregunta",
    ]
    for key, values in axes.items():
        if isinstance(values, list):
            rendered = "; ".join(str(value) for value in values if str(value).strip())
        else:
            rendered = str(values)
        if rendered:
            lines.append(f"- {key}: {rendered}")
    lines.extend(["", "## Estadios de búsqueda"])
    stages = decomposition.get("search_stages") if isinstance(decomposition, dict) else []
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        axis_raw = stage.get("axis_covered") or []
        axis = "; ".join(str(item) for item in axis_raw if str(item).strip()) if isinstance(axis_raw, list) else str(axis_raw)
        lines.extend(
            [
                "",
                f"### {stage.get('stage_id', '')}. {stage.get('name', '')}",
                f"- Propósito: {stage.get('purpose', '')}",
                f"- Ejes cubiertos: {axis}",
            ]
        )
        for source, queries in stage_queries_filtered_by_plan(stage, plan).items():
            if not queries:
                continue
            lines.append(f"- {source}: " + " | ".join(f"`{query}`" for query in queries))
    lines.extend(["", "## Plan ejecutado por fuente"])
    for source, queries in plan.items():
        if not queries:
            continue
        lines.append(f"### {source}")
        lines.extend(f"- `{query}`" for query in queries)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_search_decomposition_files(review_dir: pathlib.Path, decomposition: dict[str, object], plan: dict[str, list[str]]) -> None:
    sanitized = sanitize_decomposition_for_plan(decomposition, plan)
    write_json(review_dir / "protocol" / "search-decomposition.json", sanitized)
    write_text(review_dir / "protocol" / "search-decomposition.md", render_search_decomposition_markdown(sanitized, plan))
    write_csv(review_dir / "searches" / "search-stage-map.csv", SEARCH_STAGE_FIELDS, search_stage_rows(sanitized, plan))


def fetch_openalex(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    for idx, query in enumerate(queries, start=1):
        print(f"[search] OpenAlex {idx}/{len(queries)}: {query}", flush=True)
        params = {
            "search": query,
            "filter": f"from_publication_date:{from_date},to_publication_date:{to_date}",
            "per-page": str(PUBLIC_API_PAGE_SIZE),
        }
        add_contact_param(params)
        url = OPENALEX_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = fetch_json(url)
            raw_results = data.get("results", []) if isinstance(data, dict) else []
            results = [item for item in raw_results if record_in_window(item.get("publication_date") or "", item.get("publication_year") or "", from_date, to_date)]
            note = f"{len(results)} resultados recuperados; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
        for item in results:
            item_id = item.get("id") or f"oa-{len(items)+1}"
            items[item_id] = item
        search_rows.append(
            {
                "source": "OpenAlex",
                "platform": "OpenAlex API",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/openalex-2026.json",
            }
        )
        print(f"[search] OpenAlex {idx}/{len(queries)} -> {note}", flush=True)
    return list(items.values()), search_rows


def crossref_publication_date(item: dict) -> str:
    for field in ("published-print", "published-online", "published", "issued", "created"):
        date_parts = ((item.get(field) or {}).get("date-parts") or [])
        if not date_parts or not date_parts[0]:
            continue
        parts = [str(part) for part in date_parts[0]]
        if len(parts) >= 3:
            return f"{parts[0].zfill(4)}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        if len(parts) >= 2:
            return f"{parts[0].zfill(4)}-{parts[1].zfill(2)}-01"
        if len(parts) == 1:
            return f"{parts[0].zfill(4)}-01-01"
    return ""


def fetch_crossref(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    for idx, query in enumerate(queries, start=1):
        print(f"[search] Crossref {idx}/{len(queries)}: {query}", flush=True)
        params = {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{from_date},until-pub-date:{to_date}",
            "rows": str(PUBLIC_API_PAGE_SIZE),
        }
        add_contact_param(params)
        url = CROSSREF_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = fetch_json(url)
            raw_results = ((data or {}).get("message") or {}).get("items", []) if isinstance(data, dict) else []
            results = [item for item in raw_results if record_in_window(crossref_publication_date(item), ((item.get("published") or {}).get("date-parts") or [[ ""]])[0][0] or "", from_date, to_date)]
            note = f"{len(results)} resultados recuperados; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
        for item in results:
            key = item.get("DOI") or "cr-" + str(len(items) + 1)
            items[key] = item
        search_rows.append(
            {
                "source": "Crossref",
                "platform": "Crossref API",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/crossref-2026.json",
            }
        )
        print(f"[search] Crossref {idx}/{len(queries)} -> {note}", flush=True)
    return list(items.values()), search_rows


def fetch_semantic_scholar(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    headers = semantic_scholar_headers()
    year_start = year_from_date(from_date, 2026)
    year_end = year_from_date(to_date, 2026)
    consecutive_errors = 0
    for idx, query in enumerate(queries, start=1):
        print(f"[search] SemanticScholar {idx}/{len(queries)}: {query}", flush=True)
        params = {
            "query": query,
            "year": str(year_start) if year_start == year_end else f"{year_start}-{year_end}",
            "limit": "100",
            "fields": "title,abstract,authors,year,publicationDate,venue,publicationTypes,externalIds,url,openAccessPdf",
        }
        url = SEMANTIC_SCHOLAR_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = fetch_json(url, headers=headers)
            raw_results = data.get("data", []) if isinstance(data, dict) else []
            results = [item for item in raw_results if record_in_window(item.get("publicationDate") or "", item.get("year") or "", from_date, to_date)]
            note = f"{len(results)} resultados recuperados; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
            consecutive_errors += 1
        else:
            consecutive_errors = 0
        for item in results:
            key = item.get("paperId") or item.get("externalIds", {}).get("DOI") or f"ss-{len(items)+1}"
            items[key] = item
        search_rows.append(
            {
                "source": "SemanticScholar",
                "platform": "Semantic Scholar API",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/semanticscholar-2026.json",
            }
        )
        print(f"[search] SemanticScholar {idx}/{len(queries)} -> {note}", flush=True)
        if consecutive_errors >= 3:
            remaining = queries[idx:]
            for skipped in remaining:
                search_rows.append(
                    {
                        "source": "SemanticScholar",
                        "platform": "Semantic Scholar API",
                        "query_string": skipped,
                        "author_filter": "",
                        "run_date": datetime.now().date().isoformat(),
                        "from_date": from_date,
                        "to_date": to_date,
                        "notes": "skipped: consecutive Semantic Scholar errors/rate limit",
                        "export_file": "raw/semanticscholar-2026.json",
                    }
                )
            if remaining:
                print(f"[search] SemanticScholar skipped {len(remaining)} remaining queries after consecutive errors.", flush=True)
            break
    return list(items.values()), search_rows


def fetch_arxiv(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]], str]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    last_xml = ""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    year_start = year_from_date(from_date, 2026)
    year_end = year_from_date(to_date, 2026)
    consecutive_errors = 0
    for idx, query in enumerate(queries, start=1):
        print(f"[search] arXiv {idx}/{len(queries)}: {query}", flush=True)
        params = {
            "search_query": query,
            "start": "0",
            "max_results": "100",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = ARXIV_URL + "?" + urllib.parse.urlencode(params)
        try:
            xml_text = fetch_text(url)
            last_xml = xml_text
            root = ET.fromstring(xml_text)
            results = []
            for entry in root.findall("atom:entry", ns):
                published = entry.findtext("atom:published", default="", namespaces=ns)
                year = int(published[:4]) if published[:4].isdigit() else 0
                if not (year_start <= year <= year_end):
                    continue
                if not record_in_window((published or "")[:10], year, from_date, to_date):
                    continue
                title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
                summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split())
                entry_id = entry.findtext("atom:id", default="", namespaces=ns)
                arxiv_code = entry_id.rstrip("/").rsplit("/", 1)[-1] if entry_id else ""
                authors = [author.findtext("atom:name", default="", namespaces=ns) for author in entry.findall("atom:author", ns)]
                results.append(
                    {
                        "arxiv_id": entry_id,
                        "title": title,
                        "abstract": summary,
                        "authors": "; ".join(a for a in authors if a),
                        "year": str(year),
                        "publication_date": (published or "")[:10],
                        "work_type": "preprint",
                        "doi": f"10.48550/arXiv.{arxiv_code}" if arxiv_code else "",
                    }
                )
            note = f"{len(results)} resultados filtrados por ventana temporal; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
            consecutive_errors += 1
        else:
            consecutive_errors = 0
        for item in results:
            key = item.get("arxiv_id") or f"arxiv-{len(items)+1}"
            items[key] = item
        search_rows.append(
            {
                "source": "arXiv",
                "platform": "arXiv API",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/arxiv-records.json",
            }
        )
        print(f"[search] arXiv {idx}/{len(queries)} -> {note}", flush=True)
        if consecutive_errors >= 2:
            remaining = queries[idx:]
            for skipped in remaining:
                search_rows.append(
                    {
                        "source": "arXiv",
                        "platform": "arXiv API",
                        "query_string": skipped,
                        "author_filter": "",
                        "run_date": datetime.now().date().isoformat(),
                        "from_date": from_date,
                        "to_date": to_date,
                        "notes": "skipped: consecutive arXiv errors/rate limit or timeout",
                        "export_file": "raw/arxiv-records.json",
                    }
                )
            if remaining:
                print(f"[search] arXiv skipped {len(remaining)} remaining queries after consecutive errors.", flush=True)
            break
    return list(items.values()), search_rows, last_xml


def fetch_europepmc(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    for idx, query in enumerate(queries, start=1):
        print(f"[search] EuropePMC {idx}/{len(queries)}: {query}", flush=True)
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": "100",
        }
        url = EUROPEPMC_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = fetch_json(url, timeout=30)
            raw_results = (((data or {}).get("resultList") or {}).get("result") or []) if isinstance(data, dict) else []
            results = [
                item
                for item in raw_results
                if record_in_window(item.get("firstPublicationDate") or "", item.get("pubYear") or "", from_date, to_date)
            ]
            note = f"{len(results)} resultados recuperados; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
        for item in results:
            key = item.get("doi") or item.get("id") or f"epmc-{len(items)+1}"
            items[key] = item
        search_rows.append(
            {
                "source": "EuropePMC",
                "platform": "Europe PMC REST API",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/europepmc-2026.json",
            }
        )
        print(f"[search] EuropePMC {idx}/{len(queries)} -> {note}", flush=True)
    return list(items.values()), search_rows


def fetch_openaire(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    for idx, query in enumerate(queries, start=1):
        print(f"[search] OpenAIRE {idx}/{len(queries)}: {query}", flush=True)
        params = {
            "search": query,
            "pageSize": "100",
            "fromPublicationDate": from_date,
            "toPublicationDate": to_date,
        }
        url = OPENAIRE_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = fetch_json(url, timeout=35)
            if isinstance(data, dict):
                raw_results = data.get("results") or data.get("data") or data.get("response") or []
                if isinstance(raw_results, dict):
                    raw_results = raw_results.get("results") or raw_results.get("items") or []
            else:
                raw_results = data if isinstance(data, list) else []
            results = [
                item
                for item in raw_results
                if isinstance(item, dict)
                and record_in_window(
                    str(item.get("dateofacceptance") or item.get("publicationDate") or item.get("date") or ""),
                    str(item.get("year") or item.get("publicationYear") or ""),
                    from_date,
                    to_date,
                )
            ]
            note = f"{len(results)} resultados recuperados; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
        for item in results:
            key = str(item.get("id") or item.get("pid") or item.get("doi") or f"openaire-{len(items)+1}")
            items[key] = item
        search_rows.append(
            {
                "source": "OpenAIRE",
                "platform": "OpenAIRE Graph API",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/openaire-2026.json",
            }
        )
        print(f"[search] OpenAIRE {idx}/{len(queries)} -> {note}", flush=True)
    return list(items.values()), search_rows


def fetch_lens(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    headers = lens_headers()
    if not headers:
        if queries:
            search_rows.append(
                {
                    "source": "Lens",
                    "platform": "Lens Scholarly API",
                    "query_string": "[skipped: missing HERMES_LENS_API_KEY]",
                    "author_filter": "",
                    "run_date": datetime.now().date().isoformat(),
                    "from_date": from_date,
                    "to_date": to_date,
                    "notes": "skipped: Lens API key not configured",
                    "export_file": "raw/lens-2026.json",
                }
            )
        return [], search_rows
    for idx, query in enumerate(queries, start=1):
        print(f"[search] Lens {idx}/{len(queries)}: {query}", flush=True)
        payload = {
            "query": query,
            "size": 100,
            "include": [
                "lens_id",
                "title",
                "abstract",
                "year_published",
                "date_published",
                "authors",
                "external_ids",
                "doi",
                "source",
                "keywords",
            ],
        }
        try:
            data = post_json(LENS_SCHOLAR_URL, payload, headers=headers, timeout=45)
            raw_results = []
            if isinstance(data, dict):
                raw_results = data.get("data") or data.get("results") or []
            results = [
                item
                for item in raw_results
                if isinstance(item, dict)
                and record_in_window(
                    str(item.get("date_published") or ""),
                    str(item.get("year_published") or item.get("year") or ""),
                    from_date,
                    to_date,
                )
            ]
            note = f"{len(results)} resultados recuperados; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
        for item in results:
            key = str(item.get("lens_id") or item.get("doi") or f"lens-{len(items)+1}")
            items[key] = item
        search_rows.append(
            {
                "source": "Lens",
                "platform": "Lens Scholarly API",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/lens-2026.json",
            }
        )
        print(f"[search] Lens {idx}/{len(queries)} -> {note}", flush=True)
    return list(items.values()), search_rows


def fetch_pubmed(from_date: str, to_date: str, queries: list[str], topic: str) -> tuple[list[dict], list[dict[str, str]], str]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    last_xml = ""
    for idx, query in enumerate(queries, start=1):
        print(f"[search] PubMed {idx}/{len(queries)}: {query}", flush=True)
        term = f'({query}) AND ("{from_date}"[Date - Publication] : "{to_date}"[Date - Publication])'
        params = {
            "db": "pubmed",
            "term": term,
            "retmax": "100",
            "retmode": "json",
            **pubmed_extra_params(),
        }
        try:
            data = fetch_json(PUBMED_ESEARCH_URL + "?" + urllib.parse.urlencode(params), timeout=30)
            ids = ((data or {}).get("esearchresult") or {}).get("idlist") or []
            if ids:
                efetch_params = {
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "retmode": "xml",
                    **pubmed_extra_params(),
                }
                last_xml = fetch_text(PUBMED_EFETCH_URL + "?" + urllib.parse.urlencode(efetch_params), timeout=45)
                results = pubmed_items_from_xml(last_xml, from_date, to_date)
            else:
                results = []
            note = f"{len(results)} resultados recuperados; tema: {topic}"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
        for item in results:
            key = item.get("pmid") or item.get("doi") or f"pubmed-{len(items)+1}"
            items[key] = item
        search_rows.append(
            {
                "source": "PubMed",
                "platform": "NCBI E-utilities",
                "query_string": query,
                "author_filter": "",
                "run_date": datetime.now().date().isoformat(),
                "from_date": from_date,
                "to_date": to_date,
                "notes": note,
                "export_file": "raw/pubmed-2026.json",
            }
        )
        print(f"[search] PubMed {idx}/{len(queries)} -> {note}", flush=True)
    return list(items.values()), search_rows, last_xml


def pubmed_items_from_xml(xml_text: str, from_date: str, to_date: str) -> list[dict]:
    if not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    items: list[dict] = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find("MedlineCitation")
        article_node = medline.find("Article") if medline is not None else None
        if article_node is None:
            continue
        pmid = (medline.findtext("PMID") if medline is not None else "") or ""
        title = "".join(article_node.findtext("ArticleTitle", default="") or "").strip()
        abstract_parts = [
            "".join(node.itertext()).strip()
            for node in article_node.findall(".//AbstractText")
            if "".join(node.itertext()).strip()
        ]
        year = article_node.findtext(".//PubDate/Year") or article_node.findtext(".//ArticleDate/Year") or ""
        month = article_node.findtext(".//ArticleDate/Month") or "01"
        day = article_node.findtext(".//ArticleDate/Day") or "01"
        pub_date = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}" if str(year).isdigit() else ""
        if not record_in_window(pub_date, year, from_date, to_date):
            continue
        authors = []
        for author in article_node.findall(".//Author"):
            last = author.findtext("LastName") or ""
            fore = author.findtext("ForeName") or author.findtext("Initials") or ""
            name = " ".join(part for part in [fore, last] if part).strip()
            if name:
                authors.append(name)
        doi = ""
        for article_id in article.findall(".//ArticleId"):
            if (article_id.attrib.get("IdType") or "").lower() == "doi":
                doi = article_id.text or ""
                break
        items.append(
            {
                "pmid": pmid,
                "title": title,
                "abstract": " ".join(abstract_parts),
                "authors": "; ".join(authors),
                "year": year,
                "publication_date": pub_date,
                "doi": doi,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            }
        )
    return items


def reconstruct_openalex_abstract(item: dict) -> str:
    inverted = item.get("abstract_inverted_index") or {}
    slots: list[str] = []
    for word, positions in inverted.items():
        for pos in positions:
            while len(slots) <= pos:
                slots.append("")
            slots[pos] = word
    return " ".join(word for word in slots if word).strip()


def split_authors(names: list[str]) -> str:
    return "; ".join(name.strip() for name in names if name and name.strip())


def split_keywords(values: list[str]) -> str:
    return ", ".join(value.strip() for value in values if value and value.strip())


def normalize_keywords(raw: str) -> str:
    tokens = sorted({token.strip().lower() for token in re.split(r"[;,]", raw or "") if token.strip()})
    return ", ".join(tokens)


def row_score(row: dict[str, str]) -> tuple[int, int, int, int]:
    abstract_bonus = 1 if row.get("abstract_original") else 0
    doi_bonus = 1 if row.get("assigned_doi") else 0
    author_bonus = 1 if row.get("authors") else 0
    return (
        SOURCE_PRIORITY.get(row.get("source", ""), 0),
        abstract_bonus,
        doi_bonus,
        author_bonus,
    )


def merge_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: OrderedDict[str, dict[str, str]] = OrderedDict()
    for row in rows:
        key = stable_record_key(row)
        if key not in merged:
            merged[key] = dict(row)
            continue
        if row_score(row) > row_score(merged[key]):
            keep = dict(merged[key])
            keep.update({k: v for k, v in row.items() if v})
            merged[key] = keep
        else:
            for field, value in row.items():
                if value and not merged[key].get(field):
                    merged[key][field] = value
    output = []
    for row in sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("year", "") or ""),
            normalize_title(item.get("title_original", "") or item.get("title_en", "")),
            item.get("source", ""),
        ),
    ):
        item = dict(row)
        item["record_id"] = stable_record_id(item)
        output.append(item)
    return output


def rows_from_openalex(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        title = item.get("display_name") or item.get("title") or ""
        keywords = split_keywords([concept.get("display_name", "") for concept in item.get("concepts", [])[:12]])
        rows.append(
            {
                "record_id": "",
                "source": "openalex",
                "year": str(item.get("publication_year") or ""),
                "publication_date": item.get("publication_date") or "",
                "authors": split_authors([author.get("author", {}).get("display_name", "") for author in item.get("authorships", [])]),
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": reconstruct_openalex_abstract(item),
                "abstract_en": reconstruct_openalex_abstract(item),
                "abstract_es": "",
                "keywords_author": keywords,
                "keywords_indexed": keywords,
                "keywords_normalized": normalize_keywords(keywords),
                "raw_doi": item.get("doi") or "",
                "assigned_doi": normalize_doi(item.get("doi") or ""),
                "needs_doi_resolution": "yes" if not item.get("doi") else "no",
                "status": "",
                "notes": (item.get("primary_location") or {}).get("landing_page_url") or "",
            }
        )
    return rows


def rows_from_crossref(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        title = " ".join(item.get("title") or [])
        authors = split_authors(
            [
                " ".join(filter(None, [author.get("given", "").strip(), author.get("family", "").strip()])).strip()
                for author in item.get("author", [])
            ]
        )
        keywords = split_keywords(item.get("subject") or [])
        abstract = strip_html(item.get("abstract") or "")
        doi = normalize_doi(item.get("DOI") or "")
        rows.append(
            {
                "record_id": "",
                "source": "crossref",
                "year": str(((item.get("published") or {}).get("date-parts") or [[ ""]])[0][0] or ""),
                "publication_date": crossref_publication_date(item),
                "authors": authors,
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": abstract,
                "abstract_en": abstract,
                "abstract_es": "",
                "keywords_author": keywords,
                "keywords_indexed": keywords,
                "keywords_normalized": normalize_keywords(keywords),
                "raw_doi": item.get("DOI") or "",
                "assigned_doi": doi,
                "needs_doi_resolution": "yes" if not doi else "no",
                "status": "",
                "notes": (item.get("resource") or {}).get("primary", {}).get("URL", "") or (f"https://doi.org/{doi}" if doi else ""),
            }
        )
    return rows


def rows_from_semantic_scholar(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        doi = normalize_doi((item.get("externalIds") or {}).get("DOI") or "")
        title = item.get("title") or ""
        authors = split_authors([author.get("name", "") for author in item.get("authors", [])])
        rows.append(
            {
                "record_id": "",
                "source": "semanticscholar",
                "year": str(item.get("year") or ""),
                "publication_date": item.get("publicationDate") or "",
                "authors": authors,
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": item.get("abstract") or "",
                "abstract_en": item.get("abstract") or "",
                "abstract_es": "",
                "keywords_author": "",
                "keywords_indexed": "",
                "keywords_normalized": "",
                "raw_doi": (item.get("externalIds") or {}).get("DOI") or "",
                "assigned_doi": doi,
                "needs_doi_resolution": "yes" if not doi else "no",
                "status": "",
                "notes": item.get("url") or "",
            }
        )
    return rows


def rows_from_arxiv(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        title = item.get("title") or ""
        arxiv_id = (item.get("arxiv_id") or "").rstrip("/").rsplit("/", 1)[-1]
        arxiv_doi = item.get("doi") or (f"10.48550/arXiv.{arxiv_id}" if arxiv_id else "")
        rows.append(
            {
                "record_id": "",
                "source": "arxiv",
                "year": str(item.get("year") or ""),
                "publication_date": item.get("publication_date") or "",
                "authors": item.get("authors") or "",
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": item.get("abstract") or "",
                "abstract_en": item.get("abstract") or "",
                "abstract_es": "",
                "keywords_author": "",
                "keywords_indexed": "",
                "keywords_normalized": "",
                "raw_doi": arxiv_doi,
                "assigned_doi": normalize_doi(arxiv_doi),
                "needs_doi_resolution": "no" if arxiv_doi else "yes",
                "status": "",
                "notes": item.get("arxiv_id") or "",
            }
        )
    return rows


def first_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            text = first_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("value", "text", "title", "name", "id"):
            text = first_text(value.get(key))
            if text:
                return text
    return ""


def doi_from_object(value: object) -> str:
    if isinstance(value, str):
        return normalize_doi(value)
    if isinstance(value, list):
        for item in value:
            doi = doi_from_object(item)
            if doi:
                return doi
    if isinstance(value, dict):
        for key in ("doi", "DOI", "value", "id"):
            doi = doi_from_object(value.get(key))
            if doi:
                return doi
        for nested in value.values():
            doi = doi_from_object(nested)
            if doi:
                return doi
    return ""


def europepmc_pdf_url(item: dict) -> str:
    urls = (((item.get("fullTextUrlList") or {}).get("fullTextUrl")) or [])
    for entry in urls:
        url = str(entry.get("url") or "")
        availability = str(entry.get("availability") or "").lower()
        document_style = str(entry.get("documentStyle") or "").lower()
        if url and ("pdf" in document_style or url.lower().endswith(".pdf") or "open access" in availability):
            return url
    return ""


def rows_from_europepmc(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        title = item.get("title") or ""
        keywords_raw = (item.get("keywordList") or {}).get("keyword") or []
        keywords = split_keywords([str(keyword) for keyword in keywords_raw])
        doi = normalize_doi(item.get("doi") or "")
        notes = europepmc_pdf_url(item) or item.get("fullTextUrl") or (f"https://doi.org/{doi}" if doi else "")
        rows.append(
            {
                "record_id": "",
                "source": "europepmc",
                "year": str(item.get("pubYear") or ""),
                "publication_date": item.get("firstPublicationDate") or "",
                "authors": item.get("authorString") or "",
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": strip_html(item.get("abstractText") or ""),
                "abstract_en": strip_html(item.get("abstractText") or ""),
                "abstract_es": "",
                "keywords_author": keywords,
                "keywords_indexed": keywords,
                "keywords_normalized": normalize_keywords(keywords),
                "raw_doi": item.get("doi") or "",
                "assigned_doi": doi,
                "needs_doi_resolution": "yes" if not doi else "no",
                "status": "",
                "notes": notes,
            }
        )
    return rows


def rows_from_openaire(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        title = first_text(item.get("mainTitle") or item.get("title") or item.get("titles") or item.get("name"))
        abstract = first_text(item.get("description") or item.get("abstract") or item.get("descriptions"))
        doi = doi_from_object(item.get("pid") or item.get("pids") or item.get("doi") or item.get("identifiers"))
        year = first_text(item.get("year") or item.get("publicationYear") or item.get("publicationDate") or item.get("dateofacceptance"))[:4]
        date_value = first_text(item.get("publicationDate") or item.get("dateofacceptance") or item.get("date"))
        authors_value = item.get("authors") or item.get("creators") or item.get("author")
        authors = first_text(authors_value)
        rows.append(
            {
                "record_id": "",
                "source": "openaire",
                "year": year,
                "publication_date": date_value,
                "authors": authors,
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": abstract,
                "abstract_en": abstract,
                "abstract_es": "",
                "keywords_author": first_text(item.get("subjects") or item.get("keywords")),
                "keywords_indexed": first_text(item.get("subjects") or item.get("keywords")),
                "keywords_normalized": normalize_keywords(first_text(item.get("subjects") or item.get("keywords"))),
                "raw_doi": doi,
                "assigned_doi": doi,
                "needs_doi_resolution": "yes" if not doi else "no",
                "status": "",
                "notes": first_text(item.get("url") or item.get("landingPage") or item.get("instance")),
            }
        )
    return rows


def rows_from_lens(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        title = first_text(item.get("title"))
        doi = doi_from_object(item.get("doi") or item.get("external_ids"))
        authors = []
        for author in item.get("authors") or []:
            if isinstance(author, dict):
                name = first_text(author.get("display_name") or author.get("full_name") or author.get("name"))
                if not name:
                    name = " ".join(part for part in [first_text(author.get("first_name")), first_text(author.get("last_name"))] if part)
                if name:
                    authors.append(name)
        year = str(item.get("year_published") or item.get("year") or "")
        date_value = str(item.get("date_published") or "")
        rows.append(
            {
                "record_id": "",
                "source": "lens",
                "year": year,
                "publication_date": date_value,
                "authors": split_authors(authors),
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": first_text(item.get("abstract")),
                "abstract_en": first_text(item.get("abstract")),
                "abstract_es": "",
                "keywords_author": split_keywords([first_text(keyword) for keyword in item.get("keywords") or []]),
                "keywords_indexed": split_keywords([first_text(keyword) for keyword in item.get("keywords") or []]),
                "keywords_normalized": normalize_keywords(split_keywords([first_text(keyword) for keyword in item.get("keywords") or []])),
                "raw_doi": doi,
                "assigned_doi": doi,
                "needs_doi_resolution": "yes" if not doi else "no",
                "status": "",
                "notes": first_text(item.get("url") or item.get("source")),
            }
        )
    return rows


def rows_from_pubmed(items: list[dict]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        title = item.get("title") or ""
        doi = normalize_doi(item.get("doi") or "")
        rows.append(
            {
                "record_id": "",
                "source": "pubmed",
                "year": str(item.get("year") or ""),
                "publication_date": item.get("publication_date") or "",
                "authors": item.get("authors") or "",
                "title_original": title,
                "title_en": title,
                "title_es": "",
                "abstract_original": item.get("abstract") or "",
                "abstract_en": item.get("abstract") or "",
                "abstract_es": "",
                "keywords_author": "",
                "keywords_indexed": "",
                "keywords_normalized": "",
                "raw_doi": item.get("doi") or "",
                "assigned_doi": doi,
                "needs_doi_resolution": "yes" if not doi else "no",
                "status": "",
                "notes": item.get("url") or "",
            }
        )
    return rows


def ensure_protocol(
    review_dir: pathlib.Path,
    year_start: int,
    year_end: int,
    from_date: str,
    to_date: str,
    final_n: int,
    topic: str,
    question: str,
    inclusion: str,
    exclusion: str,
    plan: dict[str, list[str]],
    decomposition: dict[str, object],
    mode_decision: dict[str, object] | None = None,
) -> None:
    mode_decision = mode_decision or {}
    final_n_min, final_n_max = parse_ultraquality_n_range(review_dir / "protocol" / "intake.md")
    n_contract = (
        f"entre {final_n_min} y {final_n_max}"
        if final_n_min
        else f"hasta {final_n}"
    )
    year_label = str(year_start) if year_start == year_end else f"{year_start}-{year_end}"
    main_question = question or f"¿Qué se está publicando en {year_label} sobre {topic} y qué corpus final de {n_contract} estudios resulta más representativo para una síntesis profunda y publicable?"
    source_sections = []
    for source, queries in plan.items():
        source_sections.extend(
            [
                f"### {source}",
                *[f"- `{query}`" for query in queries],
                "",
            ]
        )
    axes = decomposition.get("question_axes") if isinstance(decomposition.get("question_axes"), dict) else {}
    axis_lines: list[str] = []
    for key, values in axes.items():
        rendered = "; ".join(str(value) for value in values if str(value).strip()) if isinstance(values, list) else str(values)
        if rendered:
            axis_lines.append(f"- {key}: {rendered}")
    stage_lines: list[str] = []
    stages = decomposition.get("search_stages") if isinstance(decomposition, dict) else []
    for stage in stages if isinstance(stages, list) else []:
        if not isinstance(stage, dict):
            continue
        stage_lines.extend(
            [
                f"### {stage.get('stage_id', '')}. {stage.get('name', '')}",
                f"- Propósito: {stage.get('purpose', '')}",
                "",
            ]
        )
    mode_axes = mode_decision.get("screening_axes") if isinstance(mode_decision.get("screening_axes"), list) else []
    mode_source_lines = [
        f"- {source}"
        for source in mode_decision.get("recommended_sources", [])
        if str(source).strip()
    ] if isinstance(mode_decision.get("recommended_sources"), list) else []
    mode_appraisal_lines = [
        f"- {tool}"
        for tool in mode_decision.get("critical_appraisal_tools", [])
        if str(tool).strip()
    ] if isinstance(mode_decision.get("critical_appraisal_tools"), list) else []
    mode_synthesis_lines = [
        f"- {mode}"
        for mode in mode_decision.get("synthesis_modes", [])
        if str(mode).strip()
    ] if isinstance(mode_decision.get("synthesis_modes"), list) else []
    write_text(
        review_dir / "protocol" / "research-question.md",
        "\n".join(
            [
                "# Pregunta de investigación",
                "",
                "## Principal",
                main_question,
                "",
                "## Secundarias",
                f"- ¿Qué subtemas, constructos o patrones aparecen con mayor frecuencia en el corpus sobre {topic}?",
                "- ¿Cómo se evalúan estos estudios y qué limitaciones reportan?",
                "- ¿Qué vacíos empíricos, teóricos o metodológicos quedan abiertos?",
                f"- ¿Qué corpus final de {n_contract} estudios resulta más representativo para síntesis profunda en {year_label}?",
                "",
                "## Marco metodológico",
                f"- Modo: {review_mode_summary(mode_decision)}",
                f"- Marco de pregunta: {mode_decision.get('default_framework', 'common-core') or 'common-core'}",
                f"- Unidad primaria de comparación: {mode_decision.get('primary_unit', 'estudio') or 'estudio'}",
            ]
        ),
    )
    write_text(
        review_dir / "protocol" / "eligibility-criteria.md",
        "\n".join(
            [
                "# Criterios de elegibilidad",
                "",
                "## Inclusión",
                *criteria_to_bullets(inclusion, f"Publicaciones relevantes para el tema `{topic}` dentro de la ventana {from_date} a {to_date}."),
                "",
                "## Exclusión",
                *criteria_to_bullets(exclusion, "Excluir estudios manifiestamente irrelevantes para la pregunta de investigación."),
                "- En la síntesis profunda y el paper, los estudios seleccionados deben preservar un PDF local y lectura íntegra del texto completo extraído desde ese PDF.",
            ]
        ),
    )
    write_text(
        review_dir / "protocol" / "search-strategy.md",
        "\n".join(
            [
                "# Estrategia de búsqueda",
                "",
                "## Fuentes",
                "- OpenAlex",
                "- Crossref",
                "- Semantic Scholar",
                "- arXiv",
                "- OpenAIRE",
                "- Lens si existe API key",
                "- Europe PMC/PubMed si el modo o la pregunta lo justifican",
                "",
                "## Racional",
                f"Búsqueda orientada al tema `{topic}` en la ventana exacta {from_date} a {to_date}, respetando los criterios de inclusión y exclusión definidos en la intake.",
                "La estrategia se construye en dos pasos: primero se descompone semánticamente la pregunta en ejes obligatorios y estadios de búsqueda; después se ejecutan queries por fuente. Esto evita que una pregunta compleja quede reducida a palabras sueltas.",
                "",
                "## Modo metodológico aplicado",
                f"- Norma: {mode_decision.get('version', 'HERMES-REVIEW-MODE')}",
                f"- Modo: {review_mode_summary(mode_decision)}",
                f"- Marco de pregunta: {mode_decision.get('default_framework', 'common-core') or 'common-core'}",
                f"- Lógica: {mode_decision.get('core_logic', 'revisión sistemática con trazabilidad DOI, texto completo y síntesis focal.')}",
                "",
                "### Ejes disciplinares que deben estar representados",
                *[f"- {axis}" for axis in mode_axes],
                "",
                "### Fuentes recomendadas por modo",
                *(mode_source_lines or ["- OpenAlex", "- Crossref", "- Semantic Scholar"]),
                "",
                "### Evaluación crítica prevista",
                *(mode_appraisal_lines or ["- Rúbrica de reporting y trazabilidad"]),
                "",
                "### Síntesis prevista",
                *(mode_synthesis_lines or ["- Síntesis narrativa y focal"]),
                "",
                "## Ventana temporal",
                f"- desde {from_date}",
                f"- hasta {to_date}",
                "",
                "## Descomposición de la pregunta",
                f"- Planner: {decomposition.get('planner', 'no reportado')}",
                f"- Modelo: {decomposition.get('planner_model', '') or 'perfil determinista / fallback'}",
                *axis_lines,
                "",
                "## Estadios de búsqueda",
                *stage_lines,
                "## Ecuaciones orientativas",
                *source_sections,
                "## Elementos PRISMA-S documentados",
                "- Bases y plataformas consultadas: OpenAlex, Crossref, Semantic Scholar y arXiv.",
                "- Fecha de ejecución: registrada por consulta en `searches/search-log.csv`.",
                "- Ventana exacta: conservada en `from_date` y `to_date` para cada consulta.",
                "- Cadenas ejecutadas: conservadas literalmente por fuente en este protocolo y en `searches/search-log.csv`.",
                "- Proceso de deduplicación: consolidación por DOI normalizado y, si falta DOI, por título-autores-año.",
                "- Regla publicable: el corpus final exige DOI público, PDF local legible y extracción textual trazable.",
                "",
                "## Requisito de explotación posterior",
                "Para la síntesis profunda y el manuscrito, el subconjunto final debe contar con `title`, `keywords`, `abstract`, `PDF` local y lectura íntegra del texto completo extraído desde ese PDF.",
            ]
        ),
    )


def append_decision(
    review_dir: pathlib.Path,
    search_count: int,
    master_count: int,
    year_label: str,
    from_date: str,
    to_date: str,
    final_n: int,
    topic: str,
    inclusion: str,
    exclusion: str,
    decomposition: dict[str, object],
    mode_decision: dict[str, object] | None = None,
) -> None:
    mode_decision = mode_decision or {}
    final_n_min, final_n_max = parse_ultraquality_n_range(review_dir / "protocol" / "intake.md")
    n_contract = (
        f"entre {final_n_min} y {final_n_max}"
        if final_n_min
        else f"hasta {final_n}"
    )
    path = review_dir / "notes" / "decisions.md"
    existing = read_text(path).rstrip()
    stage_count = len(decomposition.get("search_stages") or []) if isinstance(decomposition, dict) else 0
    entry = "\n".join(
        [
            f"## {now_iso()}",
            "",
            f"- Se lanza una nueva revisión separada sobre el tema: {topic}.",
            f"- Ventana temporal: {year_label} con filtro exacto desde {from_date} hasta {to_date}.",
            f"- Criterios de inclusión activos: {inclusion or 'no especificados; se usará relevancia temática explícita.'}",
            f"- Criterios de exclusión activos: {exclusion or 'no especificados; se excluirá irrelevancia manifiesta.'}",
            f"- Modo metodológico aplicado: {review_mode_summary(mode_decision)}.",
            f"- Marco de pregunta y síntesis: {mode_decision.get('default_framework', 'common-core') or 'common-core'}.",
            f"- La pregunta se descompone antes de buscar en {stage_count} estadios auditables; el detalle queda en `protocol/search-decomposition.md` y `searches/search-stage-map.csv`.",
            f"- Se fija un contrato `ultraquality` de {n_contract} estudios para la síntesis profunda y el manuscrito final.",
            "- Se fija `temperature = 0.1` para llamadas críticas del workflow y se intenta un `max_tokens` alto en los modelos soportados.",
            f"- Búsquedas registradas en esta ejecución: {search_count}.",
            f"- Registros maestros iniciales tras consolidación: {master_count}.",
            "- Requisito metodológico: el subconjunto final para síntesis profunda o paper debe tener PDF local y lectura íntegra de texto completo extraído desde ese PDF.",
        ]
    )
    write_text(path, (existing + "\n\n" + entry + "\n").lstrip())


def bootstrap_refresh(review_dir: pathlib.Path) -> None:
    script_dir = pathlib.Path(__file__).resolve().parent
    commands = [
        [sys.executable, str(script_dir / "review_runtime_state.py"), str(review_dir)],
        [sys.executable, str(script_dir / "review_audit.py"), str(review_dir)],
        [sys.executable, str(script_dir / "sync_review_to_obsidian.py"), str(review_dir)],
        [sys.executable, str(script_dir / "telegram_prisma_notify.py"), "event", "bootstrap", str(review_dir), "--force"],
        [sys.executable, str(script_dir / "telegram_prisma_notify.py"), "phase", str(review_dir), "--force", "--label", "Revision creada y lista para screening"],
    ]
    for command in commands:
        try:
            subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            continue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    review_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = review_dir / "searches" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    intake_path = review_dir / "protocol" / "intake.md"
    year_start, year_end = parse_years(intake_path)
    from_date, to_date = parse_date_window(intake_path, year_start, year_end)
    final_n = parse_ultraquality_limit(intake_path)
    topic = parse_topic(intake_path) or "tema no especificado"
    question = parse_question(intake_path)
    inclusion = parse_intake_value(intake_path, "Criterios de inclusión")
    exclusion = parse_intake_value(intake_path, "Criterios de exclusión")
    year_label = str(year_start) if year_start == year_end else f"{year_start}-{year_end}"
    mode_decision = infer_review_mode_from_intake(intake_path, topic, question, inclusion, exclusion)
    write_review_mode_artifacts(review_dir, mode_decision)
    decomposition = build_search_decomposition(topic, question, inclusion, exclusion, mode_decision)
    plan = extend_search_plan(flatten_search_plan(decomposition), topic, question, inclusion, mode_decision)
    if not any(plan.values()):
        plan = extend_search_plan(normalize_plan(query_plan(topic, question, inclusion)), topic, question, inclusion, mode_decision)

    write_search_decomposition_files(review_dir, decomposition, plan)
    ensure_protocol(review_dir, year_start, year_end, from_date, to_date, final_n, topic, question, inclusion, exclusion, plan, decomposition, mode_decision)

    openalex_items, openalex_log = fetch_openalex(from_date, to_date, plan["openalex"], topic)
    crossref_items, crossref_log = fetch_crossref(from_date, to_date, plan["crossref"], topic)
    semanticscholar_items, semanticscholar_log = fetch_semantic_scholar(from_date, to_date, plan["semanticscholar"], topic)
    arxiv_items, arxiv_log, arxiv_xml = fetch_arxiv(from_date, to_date, plan["arxiv"], topic)
    openaire_items, openaire_log = fetch_openaire(from_date, to_date, plan["openaire"], topic)
    europepmc_items, europepmc_log = fetch_europepmc(from_date, to_date, plan["europepmc"], topic)
    pubmed_items, pubmed_log, pubmed_xml = fetch_pubmed(from_date, to_date, plan["pubmed"], topic)
    lens_items, lens_log = fetch_lens(from_date, to_date, plan["lens"], topic)

    write_json(raw_dir / "openalex-2026.json", {"results": openalex_items})
    write_json(raw_dir / "crossref-2026.json", {"message": {"items": crossref_items}})
    write_json(raw_dir / "semanticscholar-2026.json", {"data": semanticscholar_items})
    write_json(raw_dir / "arxiv-records.json", arxiv_items)
    write_json(raw_dir / "openaire-2026.json", {"results": openaire_items})
    write_json(raw_dir / "europepmc-2026.json", {"data": europepmc_items})
    write_json(raw_dir / "pubmed-2026.json", {"data": pubmed_items})
    write_json(raw_dir / "lens-2026.json", {"data": lens_items})
    if arxiv_xml:
        write_text(raw_dir / "arxiv-2026.xml", arxiv_xml)
    if pubmed_xml:
        write_text(raw_dir / "pubmed-2026.xml", pubmed_xml)

    search_rows = openalex_log + crossref_log + semanticscholar_log + arxiv_log + openaire_log + europepmc_log + pubmed_log + lens_log
    write_csv(review_dir / "searches" / "search-log.csv", SEARCH_FIELDS, search_rows)

    raw_rows = (
        rows_from_openalex(openalex_items)
        + rows_from_crossref(crossref_items)
        + rows_from_semantic_scholar(semanticscholar_items)
        + rows_from_arxiv(arxiv_items)
        + rows_from_openaire(openaire_items)
        + rows_from_europepmc(europepmc_items)
        + rows_from_pubmed(pubmed_items)
        + rows_from_lens(lens_items)
    )
    merged_rows = merge_rows(raw_rows)
    write_csv(review_dir / "records" / "master-records.csv", MASTER_FIELDS, merged_rows)
    write_csv(review_dir / "searches" / "raw" / "combined-raw-export.csv", MASTER_FIELDS, merged_rows)

    doi_script = pathlib.Path(__file__).resolve().parent / "doi_audit.py"
    subprocess.run(
        [
            "python3",
            str(doi_script),
            str(raw_dir / "openalex-2026.json"),
            str(raw_dir / "crossref-2026.json"),
            str(raw_dir / "semanticscholar-2026.json"),
            str(raw_dir / "arxiv-records.json"),
            str(raw_dir / "openaire-2026.json"),
            str(raw_dir / "europepmc-2026.json"),
            str(raw_dir / "pubmed-2026.json"),
            str(raw_dir / "lens-2026.json"),
            "--index",
            str(review_dir / "records" / "doi-index.csv"),
            "--duplicates",
            str(review_dir / "records" / "duplicates.csv"),
            "--missing",
            str(review_dir / "records" / "missing-doi.csv"),
        ],
        check=True,
    )

    append_decision(review_dir, len(search_rows), len(merged_rows), year_label, from_date, to_date, final_n, topic, inclusion, exclusion, decomposition, mode_decision)
    bootstrap_refresh(review_dir)
    print(f"review_dir: {review_dir}")
    print(f"searches_logged: {len(search_rows)}")
    print(f"master_records: {len(merged_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
