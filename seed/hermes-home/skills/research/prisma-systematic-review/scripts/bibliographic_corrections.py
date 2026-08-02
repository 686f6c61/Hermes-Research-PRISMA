#!/usr/bin/env python3
"""Apply source-verified bibliographic identities across review artifacts."""

from __future__ import annotations

import csv
import pathlib
import re


def normalize_doi(value: object) -> str:
    """Return a lowercase DOI without resolver prefixes or trailing punctuation."""
    text = str(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(".,;").lower()


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def correction_targets(review_dir: pathlib.Path) -> list[pathlib.Path]:
    """Return derived artifacts whose canonical identities must stay aligned."""
    patterns = (
        "records/*.csv",
        "screening/*.csv",
        "selection/*.csv",
        "extraction/*.csv",
        "tables/*.csv",
        "analysis/data/studies.csv",
        "fulltext/manifest.csv",
        "paper/audit/gold/*.csv",
    )
    targets: list[pathlib.Path] = []
    for pattern in patterns:
        targets.extend(review_dir.glob(pattern))
    return sorted({path.resolve() for path in targets if path.is_file()})


def apply_source_verified_identity_corrections(review_dir: pathlib.Path) -> dict[str, int]:
    """Propagate verified version-of-record data without rewriting raw imports."""
    correction_path = review_dir / "paper" / "audit" / "source-verified-identities.csv"
    corrections = [
        row
        for row in read_csv(correction_path)
        if str(row.get("verification_status") or "").strip().lower() == "source_verified"
        and normalize_doi(row.get("old_doi"))
        and normalize_doi(row.get("new_doi"))
    ]
    if not corrections:
        return {"files": 0, "rows": 0}

    by_old_doi = {normalize_doi(row["old_doi"]): row for row in corrections}
    files_changed = 0
    rows_changed = 0
    doi_fields = ("assigned_doi", "normalized_doi", "doi")
    title_fields = ("title_original", "title", "title_full")

    for path in correction_targets(review_dir):
        rows = read_csv(path)
        if not rows:
            continue
        fieldnames = list(rows[0].keys())
        file_changed = False
        for row in rows:
            matched = None
            for field in doi_fields:
                candidate = normalize_doi(row.get(field))
                if candidate in by_old_doi:
                    matched = by_old_doi[candidate]
                    break
            if matched is None:
                continue
            row_changed = False
            old_doi = normalize_doi(matched["old_doi"])
            new_doi = normalize_doi(matched["new_doi"])
            for field in doi_fields:
                if field in row and normalize_doi(row.get(field)) == old_doi:
                    row[field] = new_doi
                    row_changed = True
            new_title = str(matched.get("new_title") or "").strip()
            if new_title:
                for field in title_fields:
                    if field in row and str(row.get(field) or "").strip():
                        row[field] = new_title
                        row_changed = True
            new_authors = str(matched.get("new_authors") or "").strip()
            if new_authors and "authors" in row:
                row["authors"] = new_authors
                row_changed = True
            if row_changed:
                rows_changed += 1
                file_changed = True
        if file_changed:
            write_csv(path, fieldnames, rows)
            files_changed += 1
    return {"files": files_changed, "rows": rows_changed}
