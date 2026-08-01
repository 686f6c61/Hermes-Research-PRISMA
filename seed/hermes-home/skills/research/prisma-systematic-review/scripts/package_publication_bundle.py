#!/usr/bin/env python3
"""Create a distributable publication bundle zip for a review workspace."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import pathlib
import re
import shutil
import unicodedata
import zipfile
from datetime import datetime, timezone

from delivery_portal import build_delivery_assets, render_html
from publication_audit import stage_data_annexes

ROOT_FILES = [
    ("paper/manuscript/publication-ready.md", "paper/manuscript/publication-ready.md"),
    ("paper/manuscript/publication-ready.tex", "paper/manuscript/publication-ready.tex"),
    ("paper/manuscript/publication-ready.pdf", "paper/manuscript/publication-ready.pdf"),
    ("paper/manuscript/compiled-submission.md", "paper/manuscript/compiled-submission.md"),
    ("paper/references/references.generated.md", "paper/references/references.generated.md"),
    ("paper/references/references.generated.bib", "paper/references/references.generated.bib"),
    ("paper/audit/publication-audit.md", "paper/audit/publication-audit.md"),
    ("paper/audit/publication-gate.md", "paper/audit/publication-gate.md"),
    ("paper/audit/publication-gate.json", "paper/audit/publication-gate.json"),
    ("paper/audit/model-provenance.csv", "paper/audit/model-provenance.csv"),
    ("paper/audit/model-capabilities.json", "paper/audit/model-capabilities.json"),
    ("paper/audit/claim-evidence-ledger.csv", "paper/audit/claim-evidence-ledger.csv"),
    ("paper/audit/evidence-coverage.md", "paper/audit/evidence-coverage.md"),
    ("paper/audit/evidence-coverage.json", "paper/audit/evidence-coverage.json"),
    ("paper/audit/gold/DATASET-CARD.md", "paper/audit/gold/DATASET-CARD.md"),
    ("paper/audit/gold/gold-manifest.json", "paper/audit/gold/gold-manifest.json"),
    ("paper/audit/gold/title-abstract-gold.csv", "paper/audit/gold/title-abstract-gold.csv"),
    ("paper/audit/gold/full-text-gold.csv", "paper/audit/gold/full-text-gold.csv"),
    ("paper/audit/gold/extraction-gold.jsonl", "paper/audit/gold/extraction-gold.jsonl"),
    ("paper/audit/integrity-audit/integrity-audit.md", "paper/audit/integrity-audit/integrity-audit.md"),
    ("paper/audit/integrity-audit/integrity-audit.json", "paper/audit/integrity-audit/integrity-audit.json"),
    ("paper/journal-readiness/journal-readiness-report.md", "paper/journal-readiness/journal-readiness-report.md"),
    ("paper/journal-readiness/journal-readiness-gate.csv", "paper/journal-readiness/journal-readiness-gate.csv"),
    ("paper/journal-readiness/protocol-publication-ready.md", "paper/journal-readiness/protocol-publication-ready.md"),
    ("paper/journal-readiness/protocol-deviations.md", "paper/journal-readiness/protocol-deviations.md"),
    ("paper/journal-readiness/prisma-2020-checklist-completed.csv", "paper/journal-readiness/prisma-2020-checklist-completed.csv"),
    ("paper/journal-readiness/prisma-s-checklist-completed.csv", "paper/journal-readiness/prisma-s-checklist-completed.csv"),
    ("paper/journal-readiness/search-strategies-by-source.md", "paper/journal-readiness/search-strategies-by-source.md"),
    ("paper/journal-readiness/search-peer-review.md", "paper/journal-readiness/search-peer-review.md"),
    ("paper/journal-readiness/full-text-excluded-with-reasons.csv", "paper/journal-readiness/full-text-excluded-with-reasons.csv"),
    ("paper/journal-readiness/risk-of-bias-matrix.csv", "paper/journal-readiness/risk-of-bias-matrix.csv"),
    ("paper/journal-readiness/synthesis-eligibility-decision.md", "paper/journal-readiness/synthesis-eligibility-decision.md"),
    ("paper/journal-readiness/no-meta-analysis-rationale.md", "paper/journal-readiness/no-meta-analysis-rationale.md"),
    ("paper/journal-readiness/data-availability-statement.md", "paper/journal-readiness/data-availability-statement.md"),
    ("paper/journal-readiness/code-availability-statement.md", "paper/journal-readiness/code-availability-statement.md"),
    ("paper/journal-readiness/generative-ai-disclosure.md", "paper/journal-readiness/generative-ai-disclosure.md"),
    ("paper/journal-readiness/conflicts-funding-ethics.md", "paper/journal-readiness/conflicts-funding-ethics.md"),
    ("paper/journal-readiness/cover-letter.md", "paper/journal-readiness/cover-letter.md"),
    ("paper/journal-readiness/journal-fit-report.md", "paper/journal-readiness/journal-fit-report.md"),
    ("protocol/review-mode.md", "protocol/review-mode.md"),
    ("protocol/review-mode.json", "protocol/review-mode.json"),
    ("protocol/intake.json", "protocol/intake.json"),
    ("protocol/method-contract.json", "protocol/method-contract.json"),
    ("protocol/synthesis-plan.json", "protocol/synthesis-plan.json"),
    ("protocol/journal-profile.json", "protocol/journal-profile.json"),
    ("protocol/deliverables-contract.json", "protocol/deliverables-contract.json"),
    ("protocol/contracts-manifest.json", "protocol/contracts-manifest.json"),
    ("protocol/amendments.jsonl", "protocol/amendments.jsonl"),
    ("screening/title-abstract-dual-review.csv", "screening/title-abstract-dual-review.csv"),
    ("screening/full-text-dual-review.csv", "screening/full-text-dual-review.csv"),
    ("screening/screening-reliability.json", "screening/screening-reliability.json"),
    ("notes/pipeline-state.json", "notes/pipeline-state.json"),
    ("notes/job-ledger.json", "notes/job-ledger.json"),
    ("selection/n-range-audit.md", "selection/n-range-audit.md"),
    ("paper/review/peer-review-overview.md", "paper/review/peer-review-overview.md"),
    ("paper/review/review-packet/review-packet.md", "paper/review/review-packet/review-packet.md"),
    ("paper/review/review-packet/review-packet.json", "paper/review/review-packet/review-packet.json"),
    ("paper/review/revision-roadmap/revision-roadmap.md", "paper/review/revision-roadmap/revision-roadmap.md"),
    ("paper/review/revision-roadmap/revision-roadmap.csv", "paper/review/revision-roadmap/revision-roadmap.csv"),
]


APA_REFERENCE_RE = re.compile(r"^(?P<authors>.+?)\s+\((?P<year>\d{4})\)\.\s+(?P<title>.+?)\.\s+(?P<rest>.+)$")
URL_RE = re.compile(r"(https?://\S+)$")
ARTICLE_VENUE_RE = re.compile(r"^(?P<journal>[^,]+),\s*(?P<volume>\d+)(?:\((?P<number>[^)]+)\))?,\s*(?P<pages>\d+(?:-\d+)?)\.?$")
CONFERENCE_HINT_RE = re.compile(r"\b(conference|proceedings|workshop|symposium|neurips|iclr|icml|acl|emnlp|naacl|cvpr|aaai|coling)\b", re.IGNORECASE)
INTERNAL_RECORD_RE = re.compile(r"RID-[A-F0-9]{6,}", re.IGNORECASE)
LOCAL_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![:/A-Za-z0-9_])/(?:Applications|Users|home|private/var/folders)/"
    r"[^,\n\r\"'<>]+"
)
PUBLIC_TEXT_SUFFIXES = {
    ".bib",
    ".csv",
    ".gexf",
    ".graphml",
    ".html",
    ".json",
    ".jsonl",
    ".md",
    ".svg",
    ".tex",
    ".txt",
}


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def normalize_lookup(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def clean_reference_text(value: str) -> str:
    """Remove DOI-provider markup that should never reach BibTeX/APA exports."""
    text = str(value or "")
    text = re.sub(r"</?[^>]+>", "", text)
    text = re.sub(r"(?<=[A-Za-zÀ-ÿ])\d+(?=\b|[,;\s])", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_intake_value(review_dir: pathlib.Path, labels: list[str]) -> str:
    intake_path = review_dir / "protocol" / "intake.md"
    if not intake_path.exists():
        return ""
    content = intake_path.read_text(encoding="utf-8", errors="ignore")
    for label in labels:
        match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", content, flags=re.MULTILINE)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return ""


def declared_target_outlet(review_dir: pathlib.Path) -> str:
    return parse_intake_value(
        review_dir,
        [
            "Revista o medio objetivo (opcional; si se omite, o si solo indicas una familia temática amplia, Hermes usa `generic-common-core`)",
            "Revista objetivo (opcional)",
        ],
    )


def classify_target_outlet(raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    if not value:
        return "generic-common-core", ""
    lowered = value.lower()
    broad_markers = [
        "revista científica",
        "revista cientifica",
        "inteligencia artificial",
        "interacción humano-ia",
        "interaccion humano-ia",
        "ciencias del comportamiento",
        "behavior",
        "human-ai",
        "computacional",
    ]
    proper_markers = [
        "journal",
        "transactions",
        "nature",
        "science",
        "springer",
        "elsevier",
        "mdpi",
        "frontiers",
        "plos",
        "acm",
        "ieee",
    ]
    if any(marker in lowered for marker in proper_markers) and len(value.split()) <= 14:
        return "specific-target-outlet", value
    if any(marker in lowered for marker in broad_markers):
        return "generic-common-core", value
    return "specific-target-outlet", value


def normalize_doi(value: str) -> str:
    """Return a bare DOI suitable for reader-facing identities."""
    doi = str(value or "").strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().lower()


def record_doi_map(review_dir: pathlib.Path) -> dict[str, str]:
    """Map private runtime record IDs to the DOI used in public artifacts."""
    mapping: dict[str, str] = {}
    sources = [
        review_dir / "records" / "master-records.csv",
        review_dir / "screening" / "title-abstract.csv",
        review_dir / "screening" / "full-text.csv",
        review_dir / "selection" / "ultraquality-shortlist.csv",
        review_dir / "extraction" / "extraction-table.csv",
    ]
    for source in sources:
        if not source.exists():
            continue
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                record_id = str(row.get("record_id") or "").strip().lower()
                doi = normalize_doi(str(row.get("assigned_doi") or row.get("doi") or ""))
                if record_id and doi:
                    mapping[record_id] = doi
    return mapping


def doi_file_token(doi: str) -> str:
    """Render a DOI as a portable filename without losing its identity."""
    return re.sub(r"[^a-z0-9._-]+", "-", normalize_doi(doi)).strip("-")


def replace_private_runtime_values(
    value: str,
    *,
    review_dir: pathlib.Path,
    id_to_doi: dict[str, str],
) -> str:
    """Remove local paths and internal IDs from reader-facing text."""
    text = str(value or "")
    text = text.replace(str(review_dir), ".")
    review_name = re.escape(review_dir.name)
    # Artifacts can retain paths from the machine that originally built the
    # review, not only from the current staging copy. Anchor on the stable
    # review folder name and collapse every machine-specific prefix.
    text = re.sub(
        rf"(?:/(?!/)[^,\n\r\"'<>]+?)*?/{review_name}(?=/|\b)",
        ".",
        text,
    )
    text = LOCAL_ABSOLUTE_PATH_RE.sub("<LOCAL_PATH>", text)

    def replace_id(match: re.Match[str]) -> str:
        record_id = match.group(0).lower()
        return id_to_doi.get(record_id, "NO-DOI-EXCLUDED")

    return INTERNAL_RECORD_RE.sub(replace_id, text)


def public_relative_path(relative: str, id_to_doi: dict[str, str]) -> str:
    """Translate RID-based filenames to DOI-based names or omit them."""
    matches = list(INTERNAL_RECORD_RE.finditer(relative))
    public = relative
    for match in matches:
        doi = id_to_doi.get(match.group(0).lower())
        if not doi:
            return ""
        public = public.replace(match.group(0), doi_file_token(doi))
        public = public.replace(match.group(0).lower(), doi_file_token(doi))
    return public


def public_csv_bytes(
    source: pathlib.Path,
    *,
    review_dir: pathlib.Path,
    id_to_doi: dict[str, str],
) -> bytes:
    """Serialize a CSV without private record IDs or machine-local paths."""
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        original_fields = list(reader.fieldnames or [])
        rows = list(reader)

    fields: list[str] = []
    for field in original_fields:
        if field == "record_id":
            continue
        public_field = "doi" if field == "assigned_doi" else field
        if public_field not in fields:
            fields.append(public_field)

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        rendered: dict[str, str] = {}
        record_id = str(row.get("record_id") or "").strip().lower()
        mapped_doi = id_to_doi.get(record_id, "")
        for field in original_fields:
            if field == "record_id":
                continue
            public_field = "doi" if field == "assigned_doi" else field
            value = str(row.get(field) or "")
            if public_field == "doi":
                value = normalize_doi(value) or mapped_doi
            elif value.strip() in {"record_id", "assigned_doi"}:
                # Long-form tables encode the original column name as data.
                value = "doi"
            rendered[public_field] = replace_private_runtime_values(
                value,
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )
        writer.writerow(rendered)
    return output.getvalue().encode("utf-8")


def public_json_value(
    value: object,
    *,
    review_dir: pathlib.Path,
    id_to_doi: dict[str, str],
) -> object:
    """Remove private identifiers recursively from JSON-compatible values."""

    if isinstance(value, dict):
        rendered: dict[str, object] = {}
        record_id = str(value.get("record_id") or "").strip().lower()
        mapped_doi = id_to_doi.get(record_id, "")
        for key, item in value.items():
            if key == "record_id":
                continue
            public_key = "doi" if key == "assigned_doi" else str(key)
            public_item = public_json_value(
                item,
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )
            if public_key == "doi" and isinstance(public_item, str):
                public_item = normalize_doi(public_item) or mapped_doi
            rendered[public_key] = public_item
        return rendered
    if isinstance(value, list):
        return [
            public_json_value(
                item,
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )
            for item in value
        ]
    if isinstance(value, str):
        label = "doi" if value.strip() in {"record_id", "assigned_doi"} else value
        return replace_private_runtime_values(
            label,
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
    return value


def public_json_bytes(
    source: pathlib.Path,
    *,
    review_dir: pathlib.Path,
    id_to_doi: dict[str, str],
) -> bytes:
    """Serialize JSON or JSONL after structural identifier sanitization."""

    if source.suffix.lower() == ".jsonl":
        rendered_lines: list[str] = []
        for line in source.read_text(
            encoding="utf-8",
            errors="ignore",
        ).splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                value = line
            public_value = public_json_value(
                value,
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )
            rendered_lines.append(
                json.dumps(
                    public_value,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        return ("\n".join(rendered_lines) + "\n").encode("utf-8")

    try:
        value = json.loads(source.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        value = source.read_text(encoding="utf-8", errors="ignore")
    public_value = public_json_value(
        value,
        review_dir=review_dir,
        id_to_doi=id_to_doi,
    )
    if (
        source.name == "gold-manifest.json"
        and isinstance(public_value, dict)
    ):
        public_files: list[dict[str, object]] = []
        for item in public_value.get("files", []):
            if not isinstance(item, dict):
                continue
            relative = str(item.get("path") or "")
            candidate = review_dir / relative
            if not candidate.is_file() or candidate == source:
                continue
            payload = public_file_bytes(
                candidate,
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )
            public_files.append(
                {
                    **item,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        public_value["files"] = public_files
    return (
        json.dumps(public_value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def public_file_bytes(
    source: pathlib.Path,
    *,
    review_dir: pathlib.Path,
    id_to_doi: dict[str, str],
) -> bytes:
    """Return the exact sanitized bytes stored in the publication archive."""
    if source.suffix.lower() == ".csv":
        return public_csv_bytes(source, review_dir=review_dir, id_to_doi=id_to_doi)
    if source.suffix.lower() in {".json", ".jsonl"}:
        return public_json_bytes(
            source,
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
    if source.suffix.lower() in PUBLIC_TEXT_SUFFIXES:
        text = source.read_text(encoding="utf-8", errors="ignore")
        return replace_private_runtime_values(
            text,
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        ).encode("utf-8")
    return source.read_bytes()


def add_public_file(
    archive: zipfile.ZipFile,
    source: pathlib.Path,
    archive_name: str,
    *,
    review_dir: pathlib.Path,
    id_to_doi: dict[str, str],
) -> bool:
    """Add one public artifact using sanitized content and DOI-based paths."""
    if not source.exists() or not source.is_file():
        return False
    public_name = public_relative_path(archive_name, id_to_doi)
    if not public_name:
        return False
    archive.writestr(
        public_name,
        public_file_bytes(source, review_dir=review_dir, id_to_doi=id_to_doi),
    )
    return True


def public_delivery_manifest(
    manifest: dict[str, object],
    *,
    review_dir: pathlib.Path,
    id_to_doi: dict[str, str],
) -> dict[str, object]:
    """Recompute manifest paths, sizes, and hashes for the sanitized ZIP."""
    public_manifest = json.loads(json.dumps(manifest))
    for category in public_manifest.get("categories", []):
        files: list[dict[str, object]] = []
        for item in category.get("files", []):
            relative = str(item.get("path") or "")
            public_relative = public_relative_path(relative, id_to_doi)
            source = review_dir / relative
            if not public_relative or not source.is_file():
                continue
            payload = public_file_bytes(source, review_dir=review_dir, id_to_doi=id_to_doi)
            files.append(
                {
                    "path": public_relative,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        category["files"] = files
        category["file_count"] = len(files)
        category["byte_count"] = sum(int(item["size"]) for item in files)
        requested_start = public_relative_path(
            str(category.get("start_path") or ""),
            id_to_doi,
        )
        available_paths = {str(item["path"]) for item in files}
        category["start_path"] = (
            requested_start
            if requested_start in available_paths
            else (str(files[0]["path"]) if files else "")
        )
    return public_manifest


def selected_metadata_rows(review_dir: pathlib.Path) -> list[dict[str, str]]:
    shortlist_path = review_dir / "selection" / "ultraquality-shortlist.csv"
    extraction_path = review_dir / "extraction" / "extraction-table.csv"
    shortlist_rows = []
    if shortlist_path.exists():
        with shortlist_path.open("r", encoding="utf-8-sig", newline="") as handle:
            shortlist_rows = [
                row
                for row in csv.DictReader(handle)
                if (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "si", "sí", "true", "1"}
            ]
    extraction_by_id = {}
    if extraction_path.exists():
        with extraction_path.open("r", encoding="utf-8-sig", newline="") as handle:
            extraction_by_id = {
                (row.get("record_id") or "").strip(): row
                for row in csv.DictReader(handle)
                if (row.get("record_id") or "").strip()
            }
    merged: list[dict[str, str]] = []
    for row in shortlist_rows:
        record_id = (row.get("record_id") or "").strip()
        payload = {}
        payload.update(row)
        payload.update(extraction_by_id.get(record_id, {}))
        merged.append(payload)
    return merged


def parse_reference_entries(reference_markdown: str) -> dict[str, dict[str, str]]:
    entries: list[str] = []
    current: list[str] = []
    for line in reference_markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            if current:
                entries.append(" ".join(current).strip())
            current = [stripped[2:].strip()]
            continue
        if current and stripped:
            current.append(stripped)
        elif current and not stripped:
            entries.append(" ".join(current).strip())
            current = []
    if current:
        entries.append(" ".join(current).strip())

    parsed: dict[str, dict[str, str]] = {}
    for entry in entries:
        match = APA_REFERENCE_RE.match(entry)
        if not match:
            continue
        rest = match.group("rest").strip()
        url = ""
        url_match = URL_RE.search(rest)
        if url_match:
            url = url_match.group(1).rstrip(").,")
            rest = rest[: url_match.start()].rstrip(" .")
        venue = rest.replace("*", "").strip(" .")
        doi = ""
        if "doi.org/" in url:
            doi = url.split("doi.org/", 1)[1].strip()
        lookup = normalize_lookup(match.group("title"))
        parsed[lookup] = {
            "authors": clean_reference_text(match.group("authors")),
            "year": match.group("year").strip(),
            "title": clean_reference_text(match.group("title")),
            "venue": clean_reference_text(venue),
            "url": url,
            "doi": doi,
        }
    return parsed


def slug_token(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", folded)
    for word in words:
        if word not in {"the", "a", "an", "of", "and", "in", "on", "for"}:
            return word
    return words[0] if words else "study"


def bibtex_key(row: dict[str, str], used: set[str]) -> str:
    authors = str(row.get("authors") or "")
    year = str(row.get("year") or "nd")
    title = str(row.get("title_original") or row.get("title_en") or row.get("title") or "")
    if ";" in authors:
        first_author = authors.split(";", 1)[0].strip()
    else:
        first_author = authors.split(",", 1)[0].strip() if "," in authors else authors.strip().split(" ")[-1]
    surname = slug_token(first_author)
    token = slug_token(title)
    key = f"{surname}{year}{token}"
    candidate = key
    counter = 2
    while candidate in used:
        candidate = f"{key}{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def bibtex_escape(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def authors_to_bibtex(author_text: str) -> str:
    author_text = clean_reference_text(author_text)
    if ";" in author_text:
        parts = [part.strip() for part in author_text.split(";") if part.strip()]
        return " and ".join(parts)
    cleaned = author_text.replace(", & ", " and ").replace(" & ", " and ")
    return cleaned.strip()


def write_generated_bibtex(review_dir: pathlib.Path) -> pathlib.Path:
    references_dir = review_dir / "paper" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    bib_path = references_dir / "references.generated.bib"
    markdown_refs = read_text(references_dir / "references.generated.md")
    parsed_refs = parse_reference_entries(markdown_refs)
    rows = selected_metadata_rows(review_dir)
    used_keys: set[str] = set()
    entries: list[str] = []

    for row in rows:
        title = str(row.get("title_original") or row.get("title_en") or "").strip()
        lookup = normalize_lookup(title)
        ref_meta = parsed_refs.get(lookup, {})
        key = bibtex_key(row, used_keys)
        doi = str(row.get("assigned_doi") or ref_meta.get("doi") or "").strip()
        url = str(ref_meta.get("url") or "").strip()
        if not url and doi:
            if doi.lower().startswith("10.48550/arxiv."):
                arxiv_id = doi.split("10.48550/arxiv.", 1)[1]
                url = f"https://arxiv.org/abs/{arxiv_id}"
            else:
                url = f"https://doi.org/{doi}"
        venue = str(ref_meta.get("venue") or "").strip()
        year = str(row.get("year") or ref_meta.get("year") or "").strip()
        authors = authors_to_bibtex(str(row.get("authors") or ref_meta.get("authors") or "").strip())
        title_value = clean_reference_text(title or str(ref_meta.get("title") or "").strip())

        entry_type = "misc"
        fields: list[tuple[str, str]] = [
            ("author", authors),
            ("title", title_value),
            ("year", year),
        ]
        if venue:
            article_match = ARTICLE_VENUE_RE.match(venue)
            if "arxiv" in venue.lower():
                entry_type = "misc"
                fields.append(("howpublished", venue))
            elif article_match:
                entry_type = "article"
                fields.append(("journal", article_match.group("journal").strip()))
                if article_match.group("volume"):
                    fields.append(("volume", article_match.group("volume").strip()))
                if article_match.group("number"):
                    fields.append(("number", article_match.group("number").strip()))
                if article_match.group("pages"):
                    fields.append(("pages", article_match.group("pages").strip()))
            elif CONFERENCE_HINT_RE.search(venue):
                entry_type = "inproceedings"
                fields.append(("booktitle", venue))
            else:
                fields.append(("howpublished", venue))
        if doi:
            fields.append(("doi", doi))
        if url:
            fields.append(("url", url))
        if url and "arxiv.org/abs/" in url:
            arxiv_id = url.split("/abs/", 1)[1].strip()
            fields.append(("archivePrefix", "arXiv"))
            fields.append(("eprint", arxiv_id))

        rendered_fields = []
        for field_name, field_value in fields:
            if not field_value:
                continue
            rendered_fields.append(f"  {field_name} = {{{bibtex_escape(field_value)}}}")
        entries.append(f"@{entry_type}{{{key},\n" + ",\n".join(rendered_fields) + "\n}\n")

    bib_path.write_text("\n".join(entries).rstrip() + "\n", encoding="utf-8")
    return bib_path


def selected_record_ids(review_dir: pathlib.Path) -> list[str]:
    shortlist = review_dir / "selection" / "ultraquality-shortlist.csv"
    if not shortlist.exists():
        return []
    with shortlist.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        selected = [
            (row.get("ultraquality_rank") or "999999", (row.get("record_id") or "").strip().lower())
            for row in rows
            if (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "si", "sí", "true", "1"}
            and (row.get("record_id") or "").strip()
        ]
    selected.sort(key=lambda item: (int(item[0]) if str(item[0]).isdigit() else 999999, item[1]))
    return [record_id for _rank, record_id in selected]


def selected_pdf_paths(review_dir: pathlib.Path) -> list[pathlib.Path]:
    pdf_dir = review_dir / "fulltext" / "pdf"
    if not pdf_dir.exists():
        return []
    chosen = set(selected_record_ids(review_dir))
    if not chosen:
        return []
    rendered: list[pathlib.Path] = []
    for path in sorted(pdf_dir.glob("*.pdf")):
        stem = path.stem.strip().lower()
        if stem in chosen:
            rendered.append(path)
    return rendered


def collect_tree_files(root: pathlib.Path) -> list[pathlib.Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def write_readme(
    archive: zipfile.ZipFile,
    archive_root: str,
    review_dir: pathlib.Path,
    annex_paths: list[pathlib.Path],
    rendered_pngs: list[pathlib.Path],
    rendered_svgs: list[pathlib.Path],
    focal_pdfs: list[pathlib.Path],
    figure_assets: list[pathlib.Path],
    page_render_assets: list[pathlib.Path],
    table_assets: list[pathlib.Path],
    manuscript_assets: list[pathlib.Path],
    analysis_assets: list[pathlib.Path],
    id_to_doi: dict[str, str],
) -> None:
    now = datetime.now(timezone.utc).astimezone().isoformat()
    outlet_mode, outlet_value = classify_target_outlet(declared_target_outlet(review_dir))
    target_outlet = outlet_value if outlet_mode == "specific-target-outlet" else "generic-common-core"
    lines = [
        "# Publication Package",
        "",
        f"- Review workspace: `{review_dir.name}`",
        f"- Generated at: `{now}`",
        f"- Editorial profile: `{target_outlet}`",
        *([f"- Intake thematic band: `{outlet_value}`"] if outlet_mode == "generic-common-core" and outlet_value else []),
        "",
        "## Recommended reading order",
        "1. Start with `paper/manuscript/publication-ready.md` for the canonical article text.",
        "2. Move to `paper/references/references.generated.md` and the audit/review notes if you want to verify editorial status.",
        "2a. Use `paper/references/references.generated.bib` if you want a structured bibliography seed for journal adaptation.",
        "2b. Use `paper/audit/integrity-audit/` for static preflight issues and `paper/review/revision-roadmap/` for the actionable change matrix derived from peer review.",
        "3. Use `paper/appendices/data/` for systematic-review traceability, selection logic, and derived tables.",
        "3a. Check `protocol/review-mode.md` before interpreting the method: it declares whether the review used biomedical, technical, social-science, education, management or mixed logic.",
        "4. Inspect `figures/mode-figure-plan.md` and `tables/mode-table-plan.md` to see which visuals and tables the methodological mode requires.",
        "5. Inspect `figures/png/` and `figures/svg/` for the final publication figures, then `figures/extracted/` and `tables/extracted/` for source evidence.",
        "6. Use `figures/page-renders/` only as diagnostic fallback material when a PDF page had to be preserved for audit support.",
        "7. Consult `fulltext/pdf/` when you need to audit a focal study at the source-document level.",
        "8. Open `analysis/atlas/network-atlas.html` for the offline structural atlas and use `analysis/audit/` before interpreting communities or centrality.",
        "",
        "## Canonical vs derived artifacts",
        "- Canonical article text: `paper/manuscript/publication-ready.md`",
        "- Canonical editorial status: `paper/audit/publication-audit.md`, `paper/audit/publication-gate.md`, `paper/audit/integrity-audit/`, `paper/review/peer-review-overview.md`, `paper/review/revision-roadmap/`",
        "- Journal-readiness status: `paper/journal-readiness/journal-readiness-report.md` and `paper/journal-readiness/journal-readiness-gate.csv`",
        "- Canonical traceability data: `paper/appendices/data/`",
        "- Methodological mode: `protocol/review-mode.md` and `protocol/review-mode.json`",
        "- Mode-specific visual/table plan: `figures/mode-figure-plan.md` and `tables/mode-table-plan.md`",
        "- Derived publication visuals: `figures/png/`, `figures/svg/`",
        "- Derived source evidence: `figures/extracted/`, `tables/extracted/`",
        "- Diagnostic page renders: `figures/page-renders/`",
        "- Structural analysis: `analysis/`, with an offline atlas, metrics, GraphML, coverage and provenance",
        "",
        "## Included content",
        "- Main manuscript: `paper/manuscript/publication-ready.md`",
        "- Overleaf/LaTeX manuscript: `paper/manuscript/publication-ready.tex`",
        "- Structured bibliography seed: `paper/references/references.generated.bib`",
        "- Static integrity preflight: `paper/audit/integrity-audit/`",
        "- Journal-readiness pack: `paper/journal-readiness/`",
        "- Peer-review action matrix: `paper/review/revision-roadmap/`",
        "- Deterministic review packet: `paper/review/review-packet/`",
        "- Local manuscript assets: `paper/manuscript/figures/`",
        "- Rendered figures: `figures/png/`",
        "- Editable/vector figures and conceptual diagrams: `figures/svg/`",
        "- Mode figure/table plan: `figures/mode-figure-plan.*`, `tables/mode-table-plan.*`",
        "- Data and traceability annexes: `paper/appendices/data/`",
        "- Focal full-text PDFs: `fulltext/pdf/`",
        "- Extracted visual evidence: `figures/extracted/`",
        "- Diagnostic page renders kept outside the manuscript evidence stream: `figures/page-renders/`",
        "- Extracted tabular evidence: `tables/extracted/`",
        "- Structural atlas and auditable network data: `analysis/`",
        "- Generated references and publication audits",
        "",
        "## Editorial checklist",
        f"- Manuscript included: {'yes' if (review_dir / 'paper' / 'manuscript' / 'publication-ready.md').exists() else 'no'}",
        f"- PNG figures bundled: {len(rendered_pngs)}",
        f"- SVG figures bundled: {len(rendered_svgs)}",
        f"- Data annexes bundled: {len(annex_paths)}",
        f"- Focal PDFs bundled: {len(focal_pdfs)}",
        f"- Visual evidence assets bundled: {len(figure_assets)}",
        f"- Diagnostic page renders bundled: {len(page_render_assets)}",
        f"- Tabular evidence assets bundled: {len(table_assets)}",
        f"- Manuscript-local assets bundled: {len(manuscript_assets)}",
        f"- Structural-analysis assets bundled: {len(analysis_assets)}",
        "",
        "## How to use this package",
        "- If you want to audit the review: compare the manuscript claims with `paper/appendices/data/*.csv`, then open the corresponding `fulltext/pdf/*.pdf` and source evidence assets.",
        "- If you want to replicate the synthesis: start from `search-decomposition.md`, `search-stage-map.csv`, `search-log.csv`, `master-records.csv`, `title-abstract.csv`, `full-text.csv`, `extraction-table.csv`, and `selection-audit-matrix.csv` in `paper/appendices/data/`.",
        "- If you want to cite the article: cite the manuscript and use the generated APA references, not the working files.",
        "- If you want to reuse visuals: use `figures/png/` for direct insertion and `figures/svg/` when you need editable vector assets.",
        "- If you want to inspect study-level evidence: use `figures/extracted/`, `tables/extracted/`, and the focal PDFs together.",
        "- If you need fallback audit material: `figures/page-renders/` contains full-page renders preserved as diagnostics, not as publication-ready figures.",
        "- If you want to inspect relationships: open `analysis/atlas/network-atlas.html`; read `analysis/audit/coverage.json` before interpreting centrality or communities.",
        "",
        "## Traceability annexes",
    ]
    if annex_paths:
        for path in sorted(annex_paths):
            lines.append(f"- `paper/appendices/data/{path.name}`")
    else:
        lines.append("- No staged annex files were found.")
    lines.extend(
        [
            "",
            "## Rendered figures",
        ]
    )
    if rendered_pngs:
        for path in sorted(rendered_pngs):
            lines.append(f"- `figures/png/{path.name}`")
    else:
        lines.append("- No rendered PNG figures were found.")
    lines.extend(
        [
            "",
            "## Editable/vector figures",
        ]
    )
    if rendered_svgs:
        for path in sorted(rendered_svgs):
            lines.append(f"- `figures/svg/{path.name}`")
    else:
        lines.append("- No SVG figures were found.")
    lines.extend(
        [
            "",
            "## Diagnostic page renders",
        ]
    )
    if page_render_assets:
        for path in sorted(page_render_assets):
            lines.append(f"- `figures/page-renders/{path.name}`")
    else:
        lines.append("- No diagnostic page renders were found.")
    lines.extend(
        [
            "",
            "## Focal full-text PDFs",
        ]
    )
    if focal_pdfs:
        for path in focal_pdfs:
            public_name = public_relative_path(path.name, id_to_doi)
            if public_name:
                lines.append(f"- `fulltext/pdf/{public_name}`")
    else:
        lines.append("- No focal PDFs were found.")
    lines.extend(
        [
            "",
            "## Extracted evidence assets",
        ]
    )
    if figure_assets:
        lines.append(f"- Visual assets: {len(figure_assets)} files in `figures/extracted/`")
    else:
        lines.append("- Visual assets: none")
    if table_assets:
        lines.append(f"- Tabular assets: {len(table_assets)} files in `tables/extracted/`")
    else:
        lines.append("- Tabular assets: none")
    archive.writestr(f"{archive_root}/README-package.md", "\n".join(lines) + "\n")


def build_bundle(review_dir: pathlib.Path) -> pathlib.Path:
    paper_dir = review_dir / "paper"
    package_dir = paper_dir / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    write_generated_bibtex(review_dir)

    annex_paths = stage_data_annexes(review_dir)
    _workspace_guide, _workspace_manifest, delivery_manifest = build_delivery_assets(review_dir)
    id_to_doi = record_doi_map(review_dir)
    public_manifest = public_delivery_manifest(
        delivery_manifest,
        review_dir=review_dir,
        id_to_doi=id_to_doi,
    )
    rendered_pngs = sorted(
        path
        for path in (review_dir / "figures" / "png").glob("*.png")
        if path.is_file()
    )
    rendered_svgs = sorted(
        path
        for path in (review_dir / "figures" / "svg").glob("*.svg")
        if path.is_file()
    )
    focal_pdfs = selected_pdf_paths(review_dir)
    figure_assets = collect_tree_files(review_dir / "figures" / "extracted")
    page_render_assets = collect_tree_files(review_dir / "figures" / "page-renders")
    table_assets = collect_tree_files(review_dir / "tables" / "extracted")
    manuscript_assets = collect_tree_files(review_dir / "paper" / "manuscript" / "figures")
    analysis_assets = [
        path
        for path in collect_tree_files(review_dir / "analysis")
        if "cache" not in path.relative_to(review_dir / "analysis").parts
    ]
    figure_manifest = review_dir / "figures" / "evidence-manifest.csv"
    page_render_manifest = review_dir / "figures" / "page-render-manifest.csv"
    table_manifest = review_dir / "tables" / "evidence-manifest.csv"
    figure_catalog = review_dir / "figures" / "figure-catalog.md"
    figure_ranking_csv = review_dir / "figures" / "figure-ranking.csv"
    figure_ranking_md = review_dir / "figures" / "figure-ranking.md"
    mode_figure_plan_md = review_dir / "figures" / "mode-figure-plan.md"
    mode_figure_plan_csv = review_dir / "figures" / "mode-figure-plan.csv"
    mode_table_plan_md = review_dir / "tables" / "mode-table-plan.md"
    mode_table_plan_csv = review_dir / "tables" / "mode-table-plan.csv"

    bundle_path = package_dir / "publication-package.zip"
    archive_root = f"{review_dir.name}-publication-package"
    extracted_bundle_dir = package_dir / archive_root
    if extracted_bundle_dir.exists():
        shutil.rmtree(extracted_bundle_dir)

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{archive_root}/index.html",
            render_html(public_manifest, link_prefix=""),
        )
        archive.writestr(
            f"{archive_root}/deliverables-manifest.json",
            json.dumps(public_manifest, ensure_ascii=False, indent=2) + "\n",
        )
        write_readme(
            archive,
            archive_root,
            review_dir,
            annex_paths,
            rendered_pngs,
            rendered_svgs,
            focal_pdfs,
            figure_assets,
            page_render_assets,
            table_assets,
            manuscript_assets,
            analysis_assets,
            id_to_doi,
        )

        for rel_source, rel_target in ROOT_FILES:
            add_public_file(
                archive,
                review_dir / rel_source,
                f"{archive_root}/{rel_target}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for path in annex_paths:
            add_public_file(
                archive,
                path,
                f"{archive_root}/paper/appendices/data/{path.name}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for png_path in rendered_pngs:
            add_public_file(
                archive,
                png_path,
                f"{archive_root}/figures/png/{png_path.name}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for svg_path in rendered_svgs:
            add_public_file(
                archive,
                svg_path,
                f"{archive_root}/figures/svg/{svg_path.name}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for asset_path in manuscript_assets:
            relative_asset = asset_path.relative_to(review_dir / "paper" / "manuscript").as_posix()
            add_public_file(
                archive,
                asset_path,
                f"{archive_root}/paper/manuscript/{relative_asset}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for asset_path in analysis_assets:
            relative_asset = asset_path.relative_to(review_dir / "analysis").as_posix()
            add_public_file(
                archive,
                asset_path,
                f"{archive_root}/analysis/{relative_asset}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        add_public_file(
            archive,
            figure_manifest,
            f"{archive_root}/figures/evidence-manifest.csv",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            page_render_manifest,
            f"{archive_root}/figures/page-render-manifest.csv",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            table_manifest,
            f"{archive_root}/tables/evidence-manifest.csv",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            figure_catalog,
            f"{archive_root}/figures/figure-catalog.md",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            figure_ranking_csv,
            f"{archive_root}/figures/figure-ranking.csv",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            figure_ranking_md,
            f"{archive_root}/figures/figure-ranking.md",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            mode_figure_plan_md,
            f"{archive_root}/figures/mode-figure-plan.md",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            mode_figure_plan_csv,
            f"{archive_root}/figures/mode-figure-plan.csv",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            mode_table_plan_md,
            f"{archive_root}/tables/mode-table-plan.md",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )
        add_public_file(
            archive,
            mode_table_plan_csv,
            f"{archive_root}/tables/mode-table-plan.csv",
            review_dir=review_dir,
            id_to_doi=id_to_doi,
        )

        for pdf_path in focal_pdfs:
            add_public_file(
                archive,
                pdf_path,
                f"{archive_root}/fulltext/pdf/{pdf_path.name}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for asset_path in figure_assets:
            relative_asset = asset_path.relative_to(review_dir / "figures" / "extracted").as_posix()
            add_public_file(
                archive,
                asset_path,
                f"{archive_root}/figures/extracted/{relative_asset}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for asset_path in page_render_assets:
            relative_asset = asset_path.relative_to(review_dir / "figures" / "page-renders").as_posix()
            add_public_file(
                archive,
                asset_path,
                f"{archive_root}/figures/page-renders/{relative_asset}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        for asset_path in table_assets:
            relative_asset = asset_path.relative_to(review_dir / "tables" / "extracted").as_posix()
            add_public_file(
                archive,
                asset_path,
                f"{archive_root}/tables/extracted/{relative_asset}",
                review_dir=review_dir,
                id_to_doi=id_to_doi,
            )

        # The delivery manifest is the final source of truth for portable
        # artifacts. Add any declared file not already covered by the legacy
        # publication loops, while retaining the curated archive layout.
        existing_names = set(archive.namelist())
        for category in delivery_manifest.get("categories", []):
            for item in category.get("files", []):
                relative = str(item.get("path") or "").strip()
                if not relative:
                    continue
                source = review_dir / relative
                public_relative = public_relative_path(relative, id_to_doi)
                if not public_relative:
                    continue
                archive_name = f"{archive_root}/{public_relative}"
                if archive_name in existing_names:
                    continue
                if add_public_file(
                    archive,
                    source,
                    archive_name,
                    review_dir=review_dir,
                    id_to_doi=id_to_doi,
                ):
                    existing_names.add(archive_name)

    return bundle_path


def write_latex_editable_readme(path: pathlib.Path, review_dir: pathlib.Path) -> None:
    outlet_mode, outlet_value = classify_target_outlet(declared_target_outlet(review_dir))
    target_outlet = outlet_value if outlet_mode == "specific-target-outlet" else ""
    common_core_label = "`main-common-core.tex`"
    target_label = f"`main-journal.tex` ({target_outlet})" if target_outlet else "_No se declaró revista o medio; se usa perfil genérico común._"
    lines = [
        "# Editable LaTeX Package",
        "",
        f"- Review workspace: `{review_dir}`",
        "- Entry point: `main.tex`",
        f"- Variante base común: {common_core_label}",
        f"- Variante orientada a outlet: {target_label}",
        "- Engine recomendado: `XeLaTeX`",
        "- El manuscrito Markdown original se incluye como `publication-ready.md` para edición paralela.",
        "- Las figuras raster usadas por el `.tex` viven en `figures/png/`.",
        "- `publication-ready.tex` se conserva junto a `main.tex` por compatibilidad con el naming interno de Hermes.",
        "- `references.generated.bib` ofrece una bibliografía estructurada inicial para migración a plantilla de revista.",
        "",
        "## Compilación local",
        "1. `xelatex -interaction=nonstopmode main.tex`",
        "2. Repite una segunda pasada para referencias internas y tablas largas.",
        "",
        "## Overleaf",
        "1. Sube el contenido completo de este paquete.",
        "2. Marca `main.tex` como archivo principal.",
        "3. Selecciona `XeLaTeX` como compilador.",
        "4. Si no se declaró outlet al inicio, parte de `main-common-core.tex`.",
        "5. Si se declaró una revista o medio en el intake, puedes usar `main-journal.tex` como punto de adaptación editorial.",
        "",
        "## Notas",
        "- El manuscrito actual ya compila con referencias renderizadas, pero `references.generated.bib` se incluye como semilla estructurada para una adaptación posterior.",
        "- `publication-ready.pdf` se adjunta como referencia visual del estado validado por Hermes.",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_latex_editable_bundle(review_dir: pathlib.Path) -> pathlib.Path:
    paper_dir = review_dir / "paper"
    package_dir = paper_dir / "package"
    package_dir.mkdir(parents=True, exist_ok=True)

    manuscript_dir = paper_dir / "manuscript"
    tex_path = manuscript_dir / "publication-ready.tex"
    pdf_path = manuscript_dir / "publication-ready.pdf"
    md_path = manuscript_dir / "publication-ready.md"
    refs_path = paper_dir / "references" / "references.generated.md"
    bib_path = write_generated_bibtex(review_dir)
    outlet_mode, outlet_value = classify_target_outlet(declared_target_outlet(review_dir))
    target_outlet = outlet_value if outlet_mode == "specific-target-outlet" else ""
    figures_png_dir = manuscript_dir / "figures" / "png"
    figures_svg_dir = manuscript_dir / "figures" / "svg"

    bundle_path = package_dir / "publication-latex-editable.zip"
    archive_root = f"{review_dir.name}-latex-editable"
    extracted_bundle_dir = package_dir / archive_root
    if extracted_bundle_dir.exists():
        shutil.rmtree(extracted_bundle_dir)
    extracted_bundle_dir.mkdir(parents=True, exist_ok=True)

    if tex_path.exists():
        shutil.copy2(tex_path, extracted_bundle_dir / "main.tex")
        shutil.copy2(tex_path, extracted_bundle_dir / "main-common-core.tex")
        if target_outlet:
            shutil.copy2(tex_path, extracted_bundle_dir / "main-journal.tex")
        shutil.copy2(tex_path, extracted_bundle_dir / "publication-ready.tex")
    if pdf_path.exists():
        shutil.copy2(pdf_path, extracted_bundle_dir / "publication-ready.pdf")
    if md_path.exists():
        shutil.copy2(md_path, extracted_bundle_dir / "publication-ready.md")
    if refs_path.exists():
        shutil.copy2(refs_path, extracted_bundle_dir / "references.generated.md")
    if bib_path.exists():
        shutil.copy2(bib_path, extracted_bundle_dir / "references.generated.bib")

    target_png_dir = extracted_bundle_dir / "figures" / "png"
    target_svg_dir = extracted_bundle_dir / "figures" / "svg"
    if figures_png_dir.exists():
        shutil.copytree(figures_png_dir, target_png_dir, dirs_exist_ok=True)
    if figures_svg_dir.exists():
        shutil.copytree(figures_svg_dir, target_svg_dir, dirs_exist_ok=True)

    latexmkrc_path = extracted_bundle_dir / "latexmkrc"
    latexmkrc_path.write_text(
        "$pdf_mode = 5;\n"
        "$pdflatex = 'xelatex -interaction=nonstopmode %O %S';\n",
        encoding="utf-8",
    )
    write_latex_editable_readme(extracted_bundle_dir / "README-latex.md", review_dir)

    if bundle_path.exists():
        bundle_path.unlink()
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(extracted_bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, f"{archive_root}/{path.relative_to(extracted_bundle_dir).as_posix()}")
    return bundle_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory not found: {review_dir}")

    bundle_path = build_bundle(review_dir)
    latex_bundle_path = build_latex_editable_bundle(review_dir)
    print(bundle_path)
    print(latex_bundle_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
