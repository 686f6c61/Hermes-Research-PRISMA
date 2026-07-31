#!/usr/bin/env python3
"""Audit review exports with DOI-first normalization and duplicate detection."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict
from typing import Iterable

DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
DOI_TRAILING = ".,;:)]}>\"'"
CSV_FIELDS = [
    "source_file",
    "source_record",
    "record_id",
    "title",
    "year",
    "raw_doi",
    "normalized_doi",
    "assigned_doi",
    "extraction_method",
]


def normalize_doi(text: str | None) -> str:
    if not text:
        return ""
    value = text.strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
    match = DOI_RE.search(value)
    if not match:
        return ""
    doi = match.group(1).rstrip(DOI_TRAILING).lower()
    return doi


def sniff_text_for_doi(text: str | None) -> str:
    if not text:
        return ""
    return normalize_doi(text)


def candidate_strings(record: dict[str, object]) -> Iterable[tuple[str, str]]:
    preferred = (
        "doi",
        "DOI",
        "DO",
        "url",
        "URL",
        "link",
        "uri",
        "UR",
        "id",
        "ID",
        "identifier",
        "dc:identifier",
    )
    seen = set()
    for key in preferred:
        if key in record and isinstance(record[key], str):
            seen.add(key)
            yield key, record[key]
    for key, value in record.items():
        if key in seen:
            continue
        if isinstance(value, str):
            yield key, value


def extract_doi(record: dict[str, object]) -> tuple[str, str, str]:
    for key, value in candidate_strings(record):
        normalized = sniff_text_for_doi(value)
        if normalized:
            return value, normalized, key
    return "", "", ""


def get_first(record: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def parse_delimited(path: pathlib.Path, delimiter: str) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = []
        for idx, row in enumerate(reader, start=2):
            row = dict(row)
            row["_source_record"] = str(idx)
            rows.append(row)
        return rows


def parse_jsonl(path: pathlib.Path) -> list[dict[str, object]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                data["_source_record"] = str(idx)
                rows.append(data)
    return rows


def annotate_json_records(records: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for idx, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["_source_record"] = str(idx)
        annotated.append(row)
    return annotated


def parse_json(path: pathlib.Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if isinstance(data, list):
        return annotate_json_records(data)
    if not isinstance(data, dict):
        return []

    if isinstance(data.get("results"), list):
        return annotate_json_records(data["results"])

    message = data.get("message")
    if isinstance(message, dict):
        if isinstance(message.get("items"), list):
            return annotate_json_records(message["items"])
        return annotate_json_records([message])

    if isinstance(data.get("data"), list):
        return annotate_json_records(data["data"])

    if isinstance(data.get("papers"), list):
        return annotate_json_records(data["papers"])

    if isinstance(data.get("records"), list):
        return annotate_json_records(data["records"])

    return annotate_json_records([data])


def parse_ris(path: pathlib.Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.rstrip("\r\n")
            match = re.match(r"^([A-Z0-9]{2})  -\s?(.*)$", line)
            if not match:
                continue
            key = match.group(1)
            value = match.group(2).strip()
            if key == "ER":
                if current:
                    flattened = {k: " | ".join(v) for k, v in current.items()}
                    flattened["_source_record"] = str(len(records) + 1)
                    records.append(flattened)
                    current = {}
                continue
            current.setdefault(key, []).append(value)
    if current:
        flattened = {k: " | ".join(v) for k, v in current.items()}
        flattened["_source_record"] = str(len(records) + 1)
        records.append(flattened)
    return records


def parse_bib(path: pathlib.Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    chunks = re.split(r"(?=@\w+\s*{)", text)
    records: list[dict[str, str]] = []
    field_re = re.compile(r"(\w+)\s*=\s*(\{.*?\}|\".*?\"),?", re.DOTALL)
    for idx, chunk in enumerate(chunks, start=1):
        chunk = chunk.strip()
        if not chunk:
            continue
        record: dict[str, str] = {"_source_record": str(idx)}
        key_match = re.match(r"@\w+\s*{\s*([^,]+),", chunk)
        if key_match:
            record["bibtex_key"] = key_match.group(1).strip()
        for match in field_re.finditer(chunk):
            key = match.group(1)
            value = match.group(2).strip().strip("{}").strip('"')
            record[key] = re.sub(r"\s+", " ", value).strip()
        records.append(record)
    return records


def parse_text(path: pathlib.Path) -> list[dict[str, str]]:
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for idx, line in enumerate(handle, start=1):
            value = line.strip()
            if not value:
                continue
            rows.append({"line": value, "_source_record": str(idx)})
    return rows


def load_records(path: pathlib.Path) -> list[dict[str, object]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return parse_delimited(path, ",")
    if suffix == ".tsv":
        return parse_delimited(path, "\t")
    if suffix == ".json":
        return parse_json(path)
    if suffix in {".jsonl", ".ndjson"}:
        return parse_jsonl(path)
    if suffix == ".ris":
        return parse_ris(path)
    if suffix == ".bib":
        return parse_bib(path)
    return parse_text(path)


def project_record(path: pathlib.Path, raw: dict[str, object]) -> dict[str, str]:
    raw_doi, normalized_doi, method = extract_doi(raw)
    title = get_first(
        raw,
        "title",
        "Title",
        "TI",
        "T1",
        "article_title",
        "name",
        "line",
    )
    year = get_first(raw, "year", "Year", "PY", "publication_year", "issued")
    record_id = get_first(raw, "id", "ID", "record_id", "bibtex_key", "PMID")
    source_record = get_first(raw, "_source_record") or record_id
    return {
        "source_file": str(path),
        "source_record": source_record or "",
        "record_id": record_id or f"{path.name}:{source_record}",
        "title": title,
        "year": year,
        "raw_doi": raw_doi,
        "normalized_doi": normalized_doi,
        "assigned_doi": normalized_doi,
        "extraction_method": method,
    }


def write_csv(path: pathlib.Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Export files: csv, tsv, jsonl, ris, bib, or txt")
    parser.add_argument("--index", help="Write normalized DOI index CSV")
    parser.add_argument("--duplicates", help="Write duplicate DOI rows CSV")
    parser.add_argument("--missing", help="Write missing DOI rows CSV")
    args = parser.parse_args()

    projected: list[dict[str, str]] = []
    for raw_path in args.paths:
        path = pathlib.Path(raw_path).expanduser()
        if not path.exists():
            print(f"warning: missing file skipped: {path}", file=sys.stderr)
            continue
        for raw_record in load_records(path):
            projected.append(project_record(path, raw_record))

    doi_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    missing_rows: list[dict[str, str]] = []
    for row in projected:
        if row["normalized_doi"]:
            doi_groups[row["normalized_doi"]].append(row)
        else:
            missing_rows.append(row)

    duplicate_rows: list[dict[str, str]] = []
    duplicate_groups = 0
    duplicate_record_count = 0
    for doi, rows in sorted(doi_groups.items()):
        if len(rows) < 2:
            continue
        duplicate_groups += 1
        duplicate_record_count += len(rows)
        for row in rows:
            duplicate_rows.append({**row, "group_size": str(len(rows))})

    if args.index:
        write_csv(pathlib.Path(args.index), projected, CSV_FIELDS)
    if args.duplicates:
        write_csv(pathlib.Path(args.duplicates), duplicate_rows, CSV_FIELDS + ["group_size"])
    if args.missing:
        write_csv(pathlib.Path(args.missing), missing_rows, CSV_FIELDS)

    doi_counts = Counter(row["normalized_doi"] for row in projected if row["normalized_doi"])
    print(f"records_scanned: {len(projected)}")
    print(f"records_with_doi: {sum(1 for row in projected if row['normalized_doi'])}")
    print(f"records_missing_doi: {len(missing_rows)}")
    print(f"unique_doi_count: {len(doi_counts)}")
    print(f"duplicate_doi_groups: {duplicate_groups}")
    print(f"records_in_duplicate_groups: {duplicate_record_count}")

    if duplicate_groups:
        print("top_duplicate_dois:")
        for doi, count in doi_counts.most_common(10):
            if count > 1:
                print(f"  {doi} ({count})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
