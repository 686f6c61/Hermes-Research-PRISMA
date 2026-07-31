"""Read review artifacts and normalize study-level metadata."""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
POSITIVE_DECISIONS = {
    "include",
    "included",
    "include_ta",
    "include_ft",
    "included_ft",
    "retain",
    "retained",
    "maybe",
    "pending",
}
INCLUDED_DECISIONS = {"include", "included", "include_ft", "included_ft"}
FOCAL_FLAGS = {"1", "true", "yes", "y", "selected", "focal", "include", "included"}
EMPTY_MARKERS = {"", "na", "n/a", "none", "null", "unknown", "not reported", "no reportado"}


def normalize_doi(value: Any) -> str:
    """Return a canonical DOI or an empty string when no DOI can be proven."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text, flags=re.IGNORECASE)
    match = DOI_PATTERN.search(text)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}").lower()


def normalize_label(value: Any) -> str:
    """Normalize labels conservatively without removing meaningful accents."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = "".join(
        "" if unicodedata.category(char) == "Cf"
        else " " if unicodedata.category(char).startswith("C")
        else char
        for char in text
    )
    text = re.sub(r"\s+", " ", text)
    return text


def normalized_key(value: Any) -> str:
    """Build a comparison key while retaining the original label for display."""
    text = unicodedata.normalize("NFKD", normalize_label(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field, "")) for field in fieldnames})


def write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "1" if value else "0"
    return value


def first_value(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = normalize_label(row.get(field, ""))
        if value and value.casefold() not in EMPTY_MARKERS:
            return value
    return ""


def split_values(value: Any, *, max_items: int = 40, max_length: int = 140) -> list[str]:
    text = normalize_label(value)
    if not text or text.casefold() in EMPTY_MARKERS:
        return []
    candidates = re.split(r"\s*(?:;|\||•|\n)\s*", text)
    if len(candidates) == 1 and text.count(",") <= 8:
        candidates = re.split(r"\s*,\s*", text)
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        label = normalize_label(candidate).strip(" .")
        key = normalized_key(label)
        if not key or key in EMPTY_MARKERS or key in seen or len(label) > max_length:
            continue
        seen.add(key)
        output.append(label)
        if len(output) >= max_items:
            break
    return output


def _row_doi(row: dict[str, str]) -> str:
    return normalize_doi(
        first_value(
            row,
            "assigned_doi",
            "doi",
            "DOI",
            "raw_doi",
            "id",
        )
    )


def _index_rows(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        doi = _row_doi(row)
        if doi:
            indexed[doi] = row
    return indexed


def _decision(row: dict[str, str]) -> str:
    return normalized_key(first_value(row, "decision", "full_text_decision", "status"))


def _is_focal(row: dict[str, str]) -> bool:
    for field in (
        "selected_for_final_n",
        "selected_for_synthesis",
        "selected",
        "is_focal",
        "focal",
        "include",
    ):
        if normalized_key(row.get(field, "")) in FOCAL_FLAGS:
            return True
    decision = normalized_key(row.get("decision_before_cap", ""))
    return decision in INCLUDED_DECISIONS and bool(first_value(row, "ultraquality_rank", "rank"))


def _merge_rows(*rows: dict[str, str] | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for row in rows:
        if not row:
            continue
        for key, value in row.items():
            if value and (not merged.get(key) or key in {"decision", "status"}):
                merged[key] = value
    return merged


def load_review_records(review_dir: pathlib.Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load DOI-resolved records and attach cumulative review stages."""
    sources = {
        "master": review_dir / "records" / "master-records.csv",
        "title_abstract": review_dir / "screening" / "title-abstract.csv",
        "full_text": review_dir / "screening" / "full-text.csv",
        "extraction": review_dir / "extraction" / "extraction-table.csv",
        "shortlist": review_dir / "selection" / "ultraquality-shortlist.csv",
    }
    rows = {name: read_csv(path) for name, path in sources.items()}
    indices = {name: _index_rows(items) for name, items in rows.items()}
    all_dois: set[str] = set()
    for index in indices.values():
        all_dois.update(index)

    records: list[dict[str, Any]] = []
    focal_outside_included: list[str] = []
    raw_focal_count = 0
    for doi in sorted(all_dois):
        master = indices["master"].get(doi)
        title_abstract = indices["title_abstract"].get(doi)
        full_text = indices["full_text"].get(doi)
        extraction = indices["extraction"].get(doi)
        shortlist = indices["shortlist"].get(doi)
        merged = _merge_rows(master, title_abstract, full_text, extraction, shortlist)

        title_decision = _decision(title_abstract or {})
        full_text_decision = _decision(full_text or {})
        stages = ["master"]
        if title_abstract and title_decision in POSITIVE_DECISIONS:
            stages.append("title_abstract_retained")
        if full_text:
            stages.append("full_text_assessed")
        if extraction or full_text_decision in INCLUDED_DECISIONS:
            stages.append("included")
        shortlist_focal = bool(shortlist and _is_focal(shortlist))
        if shortlist_focal:
            raw_focal_count += 1
            if "included" in stages:
                stages.append("focal")
            else:
                focal_outside_included.append(doi)

        records.append(
            {
                "doi": doi,
                "title": first_value(merged, "title_original", "title_en", "title_es", "title"),
                "year": first_value(merged, "year", "publication_year"),
                "source": first_value(merged, "source", "primary_location_source_display_name"),
                "work_type": first_value(merged, "work_type", "type"),
                "authors_raw": first_value(merged, "authors", "author"),
                "keywords_raw": "; ".join(
                    filter(
                        None,
                        (
                            first_value(merged, "keywords_normalized"),
                            first_value(merged, "keywords_author"),
                            first_value(merged, "keywords_indexed"),
                        ),
                    )
                ),
                "stages": stages,
                "fields": merged,
            }
        )

    coverage = {
        "source_files": {name: str(path.relative_to(review_dir)) for name, path in sources.items()},
        "source_row_counts": {name: len(items) for name, items in rows.items()},
        "doi_resolved_records": len(records),
        "raw_focal_shortlist_count": raw_focal_count,
        "focal_outside_included_count": len(focal_outside_included),
        "focal_outside_included_dois": focal_outside_included,
        "records_without_doi": {
            name: sum(1 for row in items if not _row_doi(row)) for name, items in rows.items()
        },
    }
    return records, coverage


def discover_json_payloads(review_dir: pathlib.Path) -> list[pathlib.Path]:
    candidates = [
        *sorted((review_dir / "searches" / "raw").glob("**/*.json")),
        *sorted((review_dir / "analysis" / "cache" / "openalex").glob("*.json")),
    ]
    return [path for path in candidates if path.is_file() and path.stat().st_size > 0]


def iter_json_objects(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            yield from iter_json_objects(item)
        return
    if not isinstance(payload, dict):
        return
    if "results" in payload and isinstance(payload["results"], list):
        for item in payload["results"]:
            yield from iter_json_objects(item)
        return
    if payload.get("id") and (
        payload.get("doi")
        or (payload.get("ids") or {}).get("doi")
        or payload.get("authorships")
        or payload.get("referenced_works")
    ):
        yield payload
        return
    for value in payload.values():
        if isinstance(value, (dict, list)):
            yield from iter_json_objects(value)


def load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def group_by_stage(records: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    stages: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for stage in record["stages"]:
            stages[stage].add(record["doi"])
    return dict(stages)
