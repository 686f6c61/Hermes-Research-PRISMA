"""Optional institutional scholarly-source adapters.

The adapters only activate when their API key is configured. They return a
small provider-neutral record shape so the review pipeline can merge licensed
and open discovery results without leaking credentials into artifacts.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from collections.abc import Callable
from datetime import date
from typing import Any

SCOPUS_URL = "https://api.elsevier.com/content/search/scopus"
EMBASE_URL = "https://api.elsevier.com/content/embase/article"
WOS_URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"
IEEE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

SOURCE_CONFIG = {
    "scopus": {
        "label": "Scopus",
        "platform": "Scopus Search API",
        "key": "HERMES_SCOPUS_API_KEY",
        "export": "raw/scopus-2026.json",
    },
    "wos": {
        "label": "Web of Science",
        "platform": "Web of Science Starter API",
        "key": "HERMES_WOS_API_KEY",
        "export": "raw/wos-2026.json",
    },
    "embase": {
        "label": "Embase",
        "platform": "Embase Search API",
        "key": "HERMES_EMBASE_API_KEY",
        "export": "raw/embase-2026.json",
    },
    "ieee": {
        "label": "IEEE Xplore",
        "platform": "IEEE Xplore Metadata API",
        "key": "HERMES_IEEE_API_KEY",
        "export": "raw/ieee-2026.json",
    },
}


def first_text(value: Any) -> str:
    """Extract the first useful scalar from inconsistent API response shapes."""

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
        for key in (
            "value",
            "displayName",
            "wosStandard",
            "full_name",
            "name",
            "title",
            "id",
        ):
            text = first_text(value.get(key))
            if text:
                return text
    return ""


def authors_text(value: Any) -> str:
    """Normalize provider-specific author containers."""

    if isinstance(value, dict):
        value = value.get("authors") or value.get("author") or value.get("names")
    if isinstance(value, list):
        names = [first_text(item) for item in value]
        return "; ".join(name for name in names if name)
    return first_text(value)


def keywords_text(value: Any) -> str:
    if isinstance(value, dict):
        value = (
            value.get("authorKeywords")
            or value.get("ieee_terms")
            or value.get("terms")
            or value.get("keywords")
        )
    if isinstance(value, list):
        return ", ".join(text for item in value if (text := first_text(item)))
    return first_text(value)


def normalize_doi(value: Any) -> str:
    doi = first_text(value)
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip().lower()
    match = re.search(r"10\.\d{4,9}/\S+", doi)
    if not match:
        return ""
    normalized = match.group(0).rstrip(".,;)]}")
    return re.sub(r"^(10\.48550/arxiv\..+?)v\d+$", r"\1", normalized)


def safe_error_note(exc: Exception) -> str:
    """Describe a provider error without serializing URLs, keys, or tokens."""

    status = getattr(exc, "code", "")
    suffix = f" (HTTP {status})" if status else ""
    return f"error: {type(exc).__name__}{suffix}"


def build_request(
    source: str,
    query: str,
    from_date: str,
    to_date: str,
    env: dict[str, str],
) -> tuple[str, dict[str, str]]:
    """Build one authenticated request without placing keys in artifacts."""

    start_year = from_date[:4]
    end_year = to_date[:4]
    key = env[SOURCE_CONFIG[source]["key"]]
    if source == "scopus":
        params = {
            "query": (
                f"TITLE-ABS-KEY({query}) AND PUBYEAR > {int(start_year) - 1} "
                f"AND PUBYEAR < {int(end_year) + 1}"
            ),
            "date": f"{start_year}-{end_year}",
            "count": "100",
            "view": "COMPLETE",
        }
        headers = {"Accept": "application/json", "X-ELS-APIKey": key}
        inst_token = env.get("HERMES_ELSEVIER_INST_TOKEN", "").strip()
        if inst_token:
            headers["X-ELS-Insttoken"] = inst_token
        return SCOPUS_URL + "?" + urllib.parse.urlencode(params), headers
    if source == "embase":
        params = {
            "query": f"({query}) AND [{start_year}-{end_year}]/py",
            "start": "1",
            "count": "100",
            "sort": "relevance",
        }
        headers = {"Accept": "application/json", "X-ELS-APIKey": key}
        inst_token = env.get("HERMES_ELSEVIER_INST_TOKEN", "").strip()
        if inst_token:
            headers["X-ELS-Insttoken"] = inst_token
        return EMBASE_URL + "?" + urllib.parse.urlencode(params), headers
    if source == "wos":
        params = {
            "q": f"TS=({query}) AND PY={start_year}-{end_year}",
            "db": "WOS",
            "limit": "50",
            "page": "1",
            "sortField": "RS+D",
        }
        return WOS_URL + "?" + urllib.parse.urlencode(params), {
            "Accept": "application/json",
            "X-ApiKey": key,
        }
    params = {
        "querytext": query,
        "start_year": start_year,
        "end_year": end_year,
        "max_records": "200",
        "start_record": "1",
        "format": "json",
        "apikey": key,
    }
    return IEEE_URL + "?" + urllib.parse.urlencode(params), {
        "Accept": "application/json"
    }


def response_items(source: str, payload: Any) -> list[dict[str, Any]]:
    """Locate records in each official response envelope."""

    if not isinstance(payload, dict):
        return []
    if source in {"scopus", "embase"}:
        search_results = payload.get("search-results") or payload.get(
            "embase-results"
        )
        if isinstance(search_results, dict):
            values = search_results.get("entry") or search_results.get("results")
            return [item for item in values or [] if isinstance(item, dict)]
    if source == "wos":
        values = (
            payload.get("hits")
            or payload.get("documents")
            or payload.get("data")
            or []
        )
        if isinstance(values, dict):
            values = values.get("hits") or values.get("documents") or []
        return [item for item in values or [] if isinstance(item, dict)]
    values = payload.get("articles") or []
    return [item for item in values if isinstance(item, dict)]


def normalize_record(source: str, item: dict[str, Any]) -> dict[str, str]:
    """Convert one source item to the common acquisition record."""

    if source in {"scopus", "embase"}:
        title = first_text(
            item.get("dc:title") or item.get("title") or item.get("article-title")
        )
        publication_date = first_text(
            item.get("prism:coverDate")
            or item.get("publicationDate")
            or item.get("publication-date")
        )
        doi = normalize_doi(
            item.get("prism:doi")
            or item.get("doi")
            or item.get("dc:identifier")
        )
        return {
            "source": source,
            "year": publication_date[:4]
            or first_text(item.get("prism:coverDisplayDate"))[:4],
            "publication_date": publication_date,
            "authors": authors_text(
                item.get("author") or item.get("authors") or item.get("dc:creator")
            ),
            "title": title,
            "abstract": first_text(
                item.get("dc:description")
                or item.get("abstract")
                or item.get("description")
            ),
            "keywords": keywords_text(
                item.get("authkeywords") or item.get("keywords")
            ),
            "doi": doi,
            "url": first_text(
                item.get("prism:url") or item.get("link") or item.get("url")
            ),
        }
    if source == "wos":
        source_data = item.get("source") if isinstance(item.get("source"), dict) else {}
        identifiers = (
            item.get("identifiers")
            if isinstance(item.get("identifiers"), dict)
            else {}
        )
        names = item.get("names") or item.get("authors")
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        publication_date = first_text(
            source_data.get("publishDate")
            or item.get("publicationDate")
            or item.get("published")
        )
        return {
            "source": source,
            "year": first_text(
                source_data.get("publishYear")
                or item.get("year")
                or publication_date[:4]
            ),
            "publication_date": publication_date,
            "authors": authors_text(names),
            "title": first_text(item.get("title")),
            "abstract": first_text(item.get("abstract")),
            "keywords": keywords_text(item.get("keywords")),
            "doi": normalize_doi(identifiers.get("doi") or item.get("doi")),
            "url": first_text(links.get("record") or item.get("url")),
        }
    publication_date = first_text(
        item.get("publication_date") or item.get("publication_year")
    )
    index_terms = item.get("index_terms") or {}
    return {
        "source": source,
        "year": first_text(item.get("publication_year")) or publication_date[:4],
        "publication_date": publication_date,
        "authors": authors_text(item.get("authors")),
        "title": first_text(item.get("title") or item.get("article_title")),
        "abstract": first_text(item.get("abstract")),
        "keywords": keywords_text(index_terms),
        "doi": normalize_doi(item.get("doi")),
        "url": first_text(
            item.get("pdf_url") or item.get("html_url") or item.get("abstract_url")
        ),
    }


def active_source_plan(
    queries: list[str],
    env: dict[str, str],
    *,
    limit: int = 8,
) -> dict[str, list[str]]:
    """Enable only sources whose credentials are actually present."""

    bounded = list(dict.fromkeys(query for query in queries if query))[:limit]
    return {
        source: list(bounded) if env.get(config["key"], "").strip() else []
        for source, config in SOURCE_CONFIG.items()
    }


def search_sources(
    plan: dict[str, list[str]],
    from_date: str,
    to_date: str,
    topic: str,
    env: dict[str, str],
    fetch_json: Callable[..., dict | list],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]], list[dict[str, str]]]:
    """Execute active sources sequentially and return raw, log, and common rows."""

    raw: dict[str, list[dict[str, Any]]] = {source: [] for source in SOURCE_CONFIG}
    logs: list[dict[str, str]] = []
    normalized: list[dict[str, str]] = []
    for source, config in SOURCE_CONFIG.items():
        queries = plan.get(source) or []
        if not queries:
            logs.append(
                {
                    "source": config["label"],
                    "platform": config["platform"],
                    "query_string": f"[skipped: missing {config['key']}]",
                    "author_filter": "",
                    "run_date": date.today().isoformat(),
                    "from_date": from_date,
                    "to_date": to_date,
                    "notes": (
                        "optional source skipped; open-source acquisition remains active"
                    ),
                    "export_file": config["export"],
                }
            )
            continue
        for query in queries:
            try:
                url, headers = build_request(
                    source,
                    query,
                    from_date,
                    to_date,
                    env,
                )
                payload = fetch_json(url, headers=headers, timeout=45)
                items = response_items(source, payload)
                raw[source].extend(items)
                normalized.extend(normalize_record(source, item) for item in items)
                note = f"{len(items)} results retrieved; topic: {topic}"
            except Exception as exc:
                note = safe_error_note(exc)
            logs.append(
                {
                    "source": config["label"],
                    "platform": config["platform"],
                    "query_string": query,
                    "author_filter": "",
                    "run_date": date.today().isoformat(),
                    "from_date": from_date,
                    "to_date": to_date,
                    "notes": note,
                    "export_file": config["export"],
                }
            )
    return raw, logs, normalized


def sanitized_environment(
    env_file: dict[str, str],
    process_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Resolve only the credentials required by these adapters."""

    process_env = process_env or os.environ
    keys = {
        config["key"] for config in SOURCE_CONFIG.values()
    } | {"HERMES_ELSEVIER_INST_TOKEN"}
    return {
        key: (process_env.get(key, "").strip() or env_file.get(key, "").strip())
        for key in keys
    }


def raw_export_payload(source: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Use source-shaped envelopes while never serializing request credentials."""

    if source in {"scopus", "embase"}:
        return {"search-results": {"entry": items}}
    if source == "wos":
        return {"hits": items}
    return {"articles": items}


def compact_json(payload: Any) -> str:
    """Stable representation used only by request-shape tests."""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
