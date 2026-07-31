"""Resolve OpenAlex metadata with local-first caching."""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .io import discover_json_payloads, iter_json_objects, load_json, normalize_doi, normalize_label

OPENALEX_API = "https://api.openalex.org"
USER_AGENT = "HermesResearchNetworkAnalysis/1.0"


def _openalex_doi(work: dict[str, Any]) -> str:
    return normalize_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))


def _compact_work(work: dict[str, Any]) -> dict[str, Any]:
    authors: list[dict[str, str]] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        institutions = [
            normalize_label((item or {}).get("display_name"))
            for item in authorship.get("institutions") or []
            if isinstance(item, dict) and normalize_label(item.get("display_name"))
        ]
        authors.append(
            {
                "id": normalize_label(author.get("id")),
                "display_name": normalize_label(author.get("display_name")),
                "orcid": normalize_label(author.get("orcid")),
                "institutions": institutions,
            }
        )
    concepts = [
        normalize_label((item or {}).get("display_name"))
        for item in (work.get("concepts") or [])
        if isinstance(item, dict) and normalize_label(item.get("display_name"))
    ]
    keywords = [
        normalize_label((item or {}).get("display_name") or (item or {}).get("keyword"))
        for item in (work.get("keywords") or [])
        if isinstance(item, dict)
        and normalize_label(item.get("display_name") or item.get("keyword"))
    ]
    source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
    return {
        "doi": _openalex_doi(work),
        "openalex_id": normalize_label(work.get("id")),
        "title": normalize_label(work.get("display_name") or work.get("title")),
        "publication_year": work.get("publication_year") or "",
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "authors": authors,
        "referenced_works": sorted(set(work.get("referenced_works") or [])),
        "concepts": concepts,
        "keywords": keywords,
        "source": normalize_label(source),
    }


def load_local_openalex(review_dir: pathlib.Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    works: dict[str, dict[str, Any]] = {}
    provenance: list[dict[str, str]] = []
    for path in discover_json_payloads(review_dir):
        payload = load_json(path)
        count = 0
        for raw_work in iter_json_objects(payload):
            doi = _openalex_doi(raw_work)
            if not doi:
                continue
            compact = _compact_work(raw_work)
            current = works.get(doi, {})
            # Prefer the richer object when duplicate exports contain the same DOI.
            if not current or _richness(compact) > _richness(current):
                works[doi] = compact
            count += 1
        if count:
            provenance.append(
                {
                    "source": "openalex_local",
                    "path": str(path.relative_to(review_dir)),
                    "records": str(count),
                    "status": "read",
                }
            )
    return works, provenance


def _richness(work: dict[str, Any]) -> int:
    return (
        len(work.get("authors") or [])
        + len(work.get("referenced_works") or [])
        + len(work.get("concepts") or [])
        + len(work.get("keywords") or [])
    )


def _request_json(url: str, email: str, timeout: float = 15.0) -> dict[str, Any] | None:
    separator = "&" if "?" in url else "?"
    polite_url = f"{url}{separator}mailto={urllib.parse.quote(email)}" if email else url
    request = urllib.request.Request(polite_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def enrich_openalex(
    review_dir: pathlib.Path,
    records: list[dict[str, Any]],
    *,
    offline: bool,
    max_requests: int,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    works, provenance = load_local_openalex(review_dir)
    cache_dir = review_dir / "analysis" / "cache" / "openalex"
    cache_dir.mkdir(parents=True, exist_ok=True)
    email = os.environ.get("OPENALEX_EMAIL") or os.environ.get("UNPAYWALL_EMAIL") or ""
    requests_used = 0

    ordered_records = sorted(
        records,
        key=lambda record: (
            0
            if "focal" in record["stages"]
            else 1
            if "included" in record["stages"]
            else 2
            if "full_text_assessed" in record["stages"]
            else 3,
            record["doi"],
        ),
    )
    for record in ordered_records:
        doi = record["doi"]
        if doi in works:
            continue
        cache_path = cache_dir / f"{doi.replace('/', '__')}.json"
        if cache_path.exists():
            payload = load_json(cache_path)
            if isinstance(payload, dict) and _openalex_doi(payload):
                works[doi] = _compact_work(payload)
                provenance.append(
                    {
                        "source": "openalex_cache",
                        "path": str(cache_path.relative_to(review_dir)),
                        "records": "1",
                        "status": "read",
                    }
                )
                continue
        if offline or requests_used >= max_requests:
            continue
        encoded = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
        payload = _request_json(f"{OPENALEX_API}/works/{encoded}", email)
        requests_used += 1
        if not payload or not _openalex_doi(payload):
            provenance.append(
                {
                    "source": "openalex_api",
                    "path": doi,
                    "records": "0",
                    "status": "unavailable",
                }
            )
            continue
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        works[doi] = _compact_work(payload)
        provenance.append(
            {
                "source": "openalex_api",
                "path": str(cache_path.relative_to(review_dir)),
                "records": "1",
                "status": "cached",
            }
        )
        time.sleep(0.05)

    return works, provenance


def enrich_author_profiles(
    review_dir: pathlib.Path,
    works: dict[str, dict[str, Any]],
    included_dois: set[str],
    *,
    offline: bool,
    max_requests: int,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Load author productivity context without feeding it into selection."""
    cache_dir = review_dir / "analysis" / "cache" / "openalex" / "authors"
    cache_dir.mkdir(parents=True, exist_ok=True)
    email = os.environ.get("OPENALEX_EMAIL") or os.environ.get("UNPAYWALL_EMAIL") or ""
    author_ids = sorted(
        {
            author.get("id")
            for doi, work in works.items()
            if doi in included_dois
            for author in work.get("authors") or []
            if author.get("id")
        }
    )
    profiles: dict[str, dict[str, Any]] = {}
    provenance: list[dict[str, str]] = []
    requests_used = 0
    for author_id in author_ids:
        short_id = author_id.rstrip("/").rsplit("/", 1)[-1]
        cache_path = cache_dir / f"{short_id}.json"
        payload = load_json(cache_path) if cache_path.exists() else None
        status = "read"
        if not isinstance(payload, dict) and not offline and requests_used < max_requests:
            payload = _request_json(f"{OPENALEX_API}/authors/{urllib.parse.quote(short_id)}", email)
            requests_used += 1
            status = "cached"
            if payload:
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                time.sleep(0.05)
        if not isinstance(payload, dict):
            continue
        canonical_id = normalize_label(payload.get("id") or author_id)
        profiles[canonical_id] = {
            "id": canonical_id,
            "display_name": normalize_label(payload.get("display_name")),
            "orcid": normalize_label(payload.get("orcid")),
            "works_count": int(payload.get("works_count") or 0),
            "cited_by_count": int(payload.get("cited_by_count") or 0),
            "last_known_institutions": [
                normalize_label(item.get("display_name"))
                for item in payload.get("last_known_institutions") or []
                if normalize_label(item.get("display_name"))
            ],
        }
        provenance.append(
            {
                "source": "openalex_author_profile",
                "path": str(cache_path.relative_to(review_dir)),
                "records": "1",
                "status": status,
            }
        )
    return profiles, provenance
