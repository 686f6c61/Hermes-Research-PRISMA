#!/usr/bin/env python3
"""Bootstrap a PRISMA review focused on agent architectures for software development."""

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
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_mode_router import (  # noqa: E402
    infer_review_mode,
    write_review_mode_artifacts,
)

USER_AGENT = "HermesArchitectureReviewBootstrap/1.0"
OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_URL = "https://export.arxiv.org/api/query"
SOURCE_PRIORITY = {"openalex": 4, "crossref": 3, "semanticscholar": 2, "arxiv": 1}

MASTER_FIELDS = [
    "record_id",
    "source",
    "year",
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


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def contact_email() -> str:
    """Optional polite contact address for scholarly APIs."""
    return os.environ.get("HERMES_CONTACT_EMAIL", "").strip()


def add_contact_param(params: dict[str, str]) -> dict[str, str]:
    email = contact_email()
    if email:
        params["mailto"] = email
    return params


def semantic_scholar_headers() -> dict[str, str]:
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


def write_json(path: pathlib.Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    year = str(row.get("year", "")).strip()
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


def parse_ultraquality_limit(intake_path: pathlib.Path) -> int:
    raw = parse_intake_value(intake_path, "Límite final N ultraquality")
    try:
        return max(1, int(raw))
    except ValueError:
        return 37


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 90) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 90) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def openalex_queries() -> list[str]:
    return [
        '"agent architecture" software development',
        '"multi-agent architecture" software engineering',
        '"agent orchestration" coding software',
        '"agentic software engineering" architecture',
        '"coding agent framework" software development',
    ]


def crossref_queries() -> list[str]:
    return [
        '"agent architecture" "software development"',
        '"multi-agent architecture" "software engineering"',
        '"agent orchestration" coding',
        '"agentic software engineering" architecture',
        '"autonomous software development" architecture',
    ]


def semantic_scholar_queries() -> list[str]:
    return [
        'agent architecture software development',
        'multi-agent architecture software engineering',
        'agent orchestration coding software',
    ]


def arxiv_queries() -> list[str]:
    return [
        'all:"agent architecture" AND all:"software development"',
        'all:"multi-agent architecture" AND all:"software engineering"',
        'all:"agent orchestration" AND all:coding',
    ]


def fetch_openalex(year_start: int, year_end: int) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    for idx, query in enumerate(openalex_queries(), start=1):
        params = {
            "search": query,
            "filter": f"publication_year:{year_start}|{year_end}" if year_start != year_end else f"publication_year:{year_start}",
            "per-page": "100",
        }
        add_contact_param(params)
        url = OPENALEX_URL + "?" + urllib.parse.urlencode(params)
        data = fetch_json(url)
        results = data.get("results", []) if isinstance(data, dict) else []
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
                "from_date": f"{year_start}-01-01",
                "to_date": f"{year_end}-12-31",
                "notes": f"{len(results)} resultados recuperados; revisión de arquitecturas",
                "export_file": "raw/openalex-2026.json",
            }
        )
    return list(items.values()), search_rows


def fetch_crossref(year_start: int, year_end: int) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    for query in crossref_queries():
        params = {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{year_start}-01-01,until-pub-date:{year_end}-12-31",
            "rows": "100",
        }
        add_contact_param(params)
        url = CROSSREF_URL + "?" + urllib.parse.urlencode(params)
        data = fetch_json(url)
        results = ((data or {}).get("message") or {}).get("items", []) if isinstance(data, dict) else []
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
                "from_date": f"{year_start}-01-01",
                "to_date": f"{year_end}-12-31",
                "notes": f"{len(results)} resultados recuperados; revisión de arquitecturas",
                "export_file": "raw/crossref-2026.json",
            }
        )
    return list(items.values()), search_rows


def fetch_semantic_scholar(year_start: int, year_end: int) -> tuple[list[dict], list[dict[str, str]]]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    headers = semantic_scholar_headers()
    for query in semantic_scholar_queries():
        params = {
            "query": query,
            "year": str(year_start) if year_start == year_end else f"{year_start}-{year_end}",
            "limit": "100",
            "fields": "title,abstract,authors,year,venue,publicationTypes,externalIds,url",
        }
        url = SEMANTIC_SCHOLAR_URL + "?" + urllib.parse.urlencode(params)
        try:
            data = fetch_json(url, headers=headers)
            results = data.get("data", []) if isinstance(data, dict) else []
            note = f"{len(results)} resultados recuperados; revisión de arquitecturas"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
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
                "from_date": f"{year_start}-01-01",
                "to_date": f"{year_end}-12-31",
                "notes": note,
                "export_file": "raw/semanticscholar-2026.json",
            }
        )
    return list(items.values()), search_rows


def fetch_arxiv(year_start: int, year_end: int) -> tuple[list[dict], list[dict[str, str]], str]:
    items: OrderedDict[str, dict] = OrderedDict()
    search_rows: list[dict[str, str]] = []
    last_xml = ""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for query in arxiv_queries():
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
                title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
                summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split())
                entry_id = entry.findtext("atom:id", default="", namespaces=ns)
                authors = [author.findtext("atom:name", default="", namespaces=ns) for author in entry.findall("atom:author", ns)]
                results.append(
                    {
                        "arxiv_id": entry_id,
                        "title": title,
                        "abstract": summary,
                        "authors": "; ".join(a for a in authors if a),
                        "year": str(year),
                        "work_type": "preprint",
                        "doi": "",
                    }
                )
            note = f"{len(results)} resultados filtrados por año; revisión de arquitecturas"
        except Exception as exc:
            results = []
            note = f"error: {exc}"
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
                "from_date": f"{year_start}-01-01",
                "to_date": f"{year_end}-12-31",
                "notes": note,
                "export_file": "raw/arxiv-records.json",
            }
        )
    return list(items.values()), search_rows, last_xml


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
        rows.append(
            {
                "record_id": "",
                "source": "arxiv",
                "year": str(item.get("year") or ""),
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
                "assigned_doi": normalize_doi(item.get("doi") or ""),
                "needs_doi_resolution": "yes" if not item.get("doi") else "no",
                "status": "",
                "notes": item.get("arxiv_id") or "",
            }
        )
    return rows


def ensure_protocol(review_dir: pathlib.Path, year_start: int, year_end: int, final_n: int) -> None:
    year_label = str(year_start) if year_start == year_end else f"{year_start}-{year_end}"
    write_text(
        review_dir / "protocol" / "research-question.md",
        "\n".join(
            [
                "# Pregunta de investigación",
                "",
                "## Principal",
                f"¿Qué arquitecturas de agentes se están proponiendo, evaluando o consolidando en {year_label} para el desarrollo de software, de forma agnóstica a tecnología, framework o proveedor?",
                "",
                "## Secundarias",
                "- ¿Qué patrones arquitectónicos aparecen con más frecuencia?",
                "- ¿Qué papel juegan la orquestación, la memoria, la delegación, la planificación y la verificación?",
                "- ¿Qué tareas de ingeniería de software cubren esas arquitecturas?",
                "- ¿Cómo se evalúan y qué limitaciones reportan?",
                f"- ¿Qué corpus final de hasta {final_n} estudios resulta más representativo para síntesis profunda en {year_label}?",
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
                "- Universo abierto sin criterios restrictivos adicionales ex ante.",
                f"- Publicaciones de {year_label} sobre arquitecturas de agentes aplicadas al desarrollo de software o a tareas claras de ingeniería de software.",
                "- Estudios agnósticos a tecnología cuando sea posible, sin limitarse a ADK, framework o proveedor concreto.",
                "",
                "## Exclusión",
                "- Ninguna exclusión restrictiva ex ante aparte de la irrelevancia manifiesta respecto al objetivo del review.",
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
                "",
                "## Racional",
                "Búsqueda amplia orientada a arquitecturas de agentes para desarrollo de software, sin limitar por framework concreto, manteniendo un universo abierto en 2026.",
                "",
                "## Ecuaciones orientativas",
                "- \"agent architecture\" software development",
                "- \"multi-agent architecture\" software engineering",
                "- \"agent orchestration\" coding software",
                "- \"agentic software engineering\" architecture",
                "- \"coding agent framework\" software development",
                "",
                "## Requisito de explotación posterior",
                "Para la síntesis profunda y el manuscrito, el subconjunto final debe contar con `title`, `keywords`, `abstract`, `PDF` local y lectura íntegra del texto completo extraído desde ese PDF.",
            ]
        ),
    )


def append_decision(review_dir: pathlib.Path, search_count: int, master_count: int, year_label: str, final_n: int) -> None:
    path = review_dir / "notes" / "decisions.md"
    existing = read_text(path).rstrip()
    entry = "\n".join(
        [
            f"## {now_iso()}",
            "",
            "- Se lanza una nueva revisión separada sobre arquitecturas de agentes para desarrollo de software.",
            f"- Ventana temporal: {year_label}.",
            "- Universo abierto sin criterios restrictivos adicionales ex ante; foco en relevancia arquitectónica para SE.",
            f"- Se fija un límite `ultraquality` de hasta {final_n} estudios para la síntesis profunda y el manuscrito final.",
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
    final_n = parse_ultraquality_limit(intake_path)
    year_label = str(year_start) if year_start == year_end else f"{year_start}-{year_end}"
    mode_decision = infer_review_mode(
        topic=parse_intake_value(intake_path, "Tema") or "arquitecturas de agentes para desarrollo de software",
        question=parse_intake_value(intake_path, "Pregunta de investigación (opcional)"),
        inclusion=parse_intake_value(intake_path, "Criterios de inclusión"),
        exclusion=parse_intake_value(intake_path, "Criterios de exclusión"),
        explicit_mode=parse_intake_value(intake_path, "Modo metodológico (opcional)") or "técnico",
    )
    write_review_mode_artifacts(review_dir, mode_decision)

    ensure_protocol(review_dir, year_start, year_end, final_n)

    openalex_items, openalex_log = fetch_openalex(year_start, year_end)
    crossref_items, crossref_log = fetch_crossref(year_start, year_end)
    semanticscholar_items, semanticscholar_log = fetch_semantic_scholar(year_start, year_end)
    arxiv_items, arxiv_log, arxiv_xml = fetch_arxiv(year_start, year_end)

    write_json(raw_dir / "openalex-2026.json", {"results": openalex_items})
    write_json(raw_dir / "crossref-2026.json", {"message": {"items": crossref_items}})
    write_json(raw_dir / "semanticscholar-2026.json", {"data": semanticscholar_items})
    write_json(raw_dir / "arxiv-records.json", arxiv_items)
    if arxiv_xml:
        write_text(raw_dir / "arxiv-2026.xml", arxiv_xml)

    search_rows = openalex_log + crossref_log + semanticscholar_log + arxiv_log
    write_csv(review_dir / "searches" / "search-log.csv", SEARCH_FIELDS, search_rows)

    raw_rows = (
        rows_from_openalex(openalex_items)
        + rows_from_crossref(crossref_items)
        + rows_from_semantic_scholar(semanticscholar_items)
        + rows_from_arxiv(arxiv_items)
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
            "--index",
            str(review_dir / "records" / "doi-index.csv"),
            "--duplicates",
            str(review_dir / "records" / "duplicates.csv"),
            "--missing",
            str(review_dir / "records" / "missing-doi.csv"),
        ],
        check=True,
    )

    append_decision(review_dir, len(search_rows), len(merged_rows), year_label, final_n)
    bootstrap_refresh(review_dir)
    print(f"review_dir: {review_dir}")
    print(f"searches_logged: {len(search_rows)}")
    print(f"master_records: {len(merged_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
