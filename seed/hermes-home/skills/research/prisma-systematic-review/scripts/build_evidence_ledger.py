#!/usr/bin/env python3
"""Build a DOI-first claim-to-evidence ledger for a review manuscript."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import unicodedata
from datetime import datetime, timezone

from artifact_contracts import write_json_atomic

LEDGER_FIELDS = [
    "claim_id",
    "section",
    "claim_type",
    "claim_text",
    "dois",
    "evidence_locations",
    "evidence_snippets",
    "coverage_status",
    "coverage_detail",
]
CRITICAL_SECTIONS = {
    "resultados",
    "results",
    "discusion",
    "discussion",
    "implicaciones teoricas",
    "implicaciones practicas",
    "conclusiones",
    "conclusions",
    "aporte teorico e interpretativo del autor",
    "aporte interpretativo final del autor",
}
EMPIRICAL_MARKERS = (
    "evidencia",
    "estudio",
    "estudios",
    "corpus",
    "muestra",
    "resultado",
    "resultados",
    "indica",
    "indican",
    "muestra",
    "muestran",
    "asociacion",
    "efecto",
    "diferencia",
    "frecuencia",
    "proporcion",
)


def normalized(text: str) -> str:
    """Return lowercase accent-free text for conservative matching."""
    folded = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in folded if not unicodedata.combining(char)).lower()


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    """Read one CSV as dictionaries."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean_doi(value: str) -> str:
    """Normalize a DOI and reject opaque internal identifiers."""
    doi = (value or "").strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi if doi.startswith("10.") and "/" in doi else ""


def author_year_keys(row: dict[str, str]) -> set[str]:
    """Build conservative surname-year keys used by author-date citations."""
    authors = (row.get("authors") or "").strip()
    year = re.search(r"\b(?:19|20)\d{2}\b", row.get("year") or "")
    if not authors or not year:
        return set()
    first = re.split(r";|,?\s+and\s+|,?\s+&\s+", authors, maxsplit=1, flags=re.I)[0].strip()
    if "," in first:
        surname = normalized(first.split(",", 1)[0])
    else:
        words = re.findall(r"[A-Za-zÀ-ÿ'-]+", first)
        surname = normalized(words[-1]) if words else ""
    return {f"{surname}|{year.group(0)}"} if surname else set()


def study_index(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Index extraction rows by author-year while retaining DOI evidence."""
    index: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        doi = clean_doi(row.get("assigned_doi") or row.get("doi") or row.get("record_id") or "")
        if not doi:
            continue
        prepared = dict(row)
        prepared["_doi"] = doi
        for key in author_year_keys(row):
            index.setdefault(key, []).append(prepared)
    return index


def manuscript_paragraphs(text: str) -> list[tuple[str, str]]:
    """Return prose paragraphs with their nearest Markdown section."""
    section = "front matter"
    paragraphs: list[tuple[str, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        paragraph = " ".join(line.strip() for line in buffer if line.strip())
        buffer.clear()
        if (
            len(paragraph) >= 80
            and not paragraph.startswith("|")
            and not paragraph.startswith("![")
            and not paragraph.startswith("```")
        ):
            paragraphs.append((section, paragraph))

    for line in text.splitlines():
        heading = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if heading:
            flush()
            section = heading.group(1).strip()
            continue
        if not line.strip():
            flush()
            continue
        if line.lstrip().startswith(("-", "* ")) and not buffer:
            continue
        buffer.append(line)
    flush()
    return paragraphs


def citation_keys(paragraph: str) -> set[str]:
    """Extract surname-year pairs without trying to interpret prose semantics."""
    keys: set[str] = set()
    pattern = re.compile(
        r"\b([A-ZÁÉÍÓÚÑÜ][A-Za-zÀ-ÿ'’-]{1,40})"
        r"(?:\s+et\s+al\.)?(?:\s*&\s+[A-ZÁÉÍÓÚÑÜ][A-Za-zÀ-ÿ'’-]+)?"
        r"[, ]+\s*((?:19|20)\d{2})\b"
    )
    for surname, year in pattern.findall(paragraph):
        keys.add(f"{normalized(surname)}|{year}")
    return keys


def claim_type(section: str, paragraph: str) -> str:
    """Classify claims so unsupported empirical statements can block the gate."""
    section_norm = normalized(section)
    paragraph_norm = normalized(paragraph)
    if section_norm in CRITICAL_SECTIONS and (
        re.search(r"\b\d+(?:[.,]\d+)?%?\b", paragraph)
        or any(marker in paragraph_norm for marker in EMPIRICAL_MARKERS)
    ):
        return "critical_empirical"
    if citation_keys(paragraph):
        return "sourced_context"
    return "interpretive"


def claim_id(section: str, paragraph: str) -> str:
    """Create a stable, non-positional identifier for one manuscript claim."""
    digest = hashlib.sha256(f"{section}\n{paragraph}".encode("utf-8")).hexdigest()[:12]
    return f"claim-{digest}"


def build_ledger(review_dir: pathlib.Path) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Link manuscript claims to DOI evidence and summarize coverage."""
    manuscript_path = review_dir / "paper" / "manuscript" / "publication-ready.md"
    manuscript = manuscript_path.read_text(encoding="utf-8", errors="ignore") if manuscript_path.exists() else ""
    extraction = read_csv(review_dir / "extraction" / "extraction-table.csv")
    index = study_index(extraction)
    ledger: list[dict[str, str]] = []
    for section, paragraph in manuscript_paragraphs(manuscript):
        keys = citation_keys(paragraph)
        matched_rows: list[dict[str, str]] = []
        for key in sorted(keys):
            matched_rows.extend(index.get(key, []))
        unique_rows = {
            row["_doi"]: row
            for row in matched_rows
            if row.get("_doi")
        }
        dois = sorted(unique_rows)
        locations = sorted(
            {
                (row.get("evidence_location") or "").strip()
                for row in unique_rows.values()
                if (row.get("evidence_location") or "").strip()
            }
        )
        snippets = [
            (row.get("evidence_snippet") or "").strip()
            for row in unique_rows.values()
            if (row.get("evidence_snippet") or "").strip()
        ]
        kind = claim_type(section, paragraph)
        page_anchored = any(re.search(r"\b(?:p|pp|page|pagina|página)\.?\s*\d+", item, flags=re.I) for item in locations)
        if dois and snippets and page_anchored:
            status = "located"
            detail = "DOI, source fragment, and page-like location are available."
        elif dois and snippets:
            status = "partial"
            detail = "DOI and source fragment are available, but the evidence location is not page-specific."
        elif dois:
            status = "partial"
            detail = "DOI is linked, but no recoverable evidence fragment is recorded."
        elif kind == "critical_empirical":
            status = "unsupported"
            detail = "Critical empirical claim has no DOI linked from the extraction matrix."
        elif keys:
            status = "unresolved_citation"
            detail = "An author-date citation was detected but could not be resolved to a DOI."
        else:
            status = "author_interpretation"
            detail = "Interpretive prose without a direct empirical citation."
        ledger.append(
            {
                "claim_id": claim_id(section, paragraph),
                "section": section,
                "claim_type": kind,
                "claim_text": paragraph,
                "dois": "; ".join(dois),
                "evidence_locations": "; ".join(locations),
                "evidence_snippets": " || ".join(snippets[:4]),
                "coverage_status": status,
                "coverage_detail": detail,
            }
        )

    critical = [row for row in ledger if row["claim_type"] == "critical_empirical"]
    unsupported = [row for row in critical if row["coverage_status"] == "unsupported"]
    partial = [row for row in critical if row["coverage_status"] == "partial"]
    located = [row for row in critical if row["coverage_status"] == "located"]
    denominator = len(critical)
    summary: dict[str, object] = {
        "schema_version": "hermes.evidence-coverage/v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "claims_total": len(ledger),
        "critical_claims": denominator,
        "critical_located": len(located),
        "critical_partial": len(partial),
        "critical_unsupported": len(unsupported),
        "doi_link_rate": round(
            sum(1 for row in critical if row["dois"]) / denominator,
            4,
        )
        if denominator
        else 1.0,
        "page_anchor_rate": round(len(located) / denominator, 4) if denominator else 1.0,
        "status": "fail" if unsupported else ("warn" if partial else "pass"),
    }
    return ledger, summary


def write_outputs(review_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Write CSV, JSON, and reader-facing Markdown evidence reports."""
    ledger, summary = build_ledger(review_dir)
    audit_dir = review_dir / "paper" / "audit"
    csv_path = audit_dir / "claim-evidence-ledger.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(ledger)
    json_path = write_json_atomic(audit_dir / "evidence-coverage.json", summary)
    md_path = audit_dir / "evidence-coverage.md"
    md_path.write_text(
        "\n".join(
            [
                "# Cobertura de evidencia",
                "",
                f"- Estado: **{str(summary['status']).upper()}**",
                f"- Afirmaciones analizadas: {summary['claims_total']}",
                f"- Afirmaciones empíricas críticas: {summary['critical_claims']}",
                f"- Localizadas con DOI, fragmento y página: {summary['critical_located']}",
                f"- Cobertura parcial: {summary['critical_partial']}",
                f"- Sin DOI enlazado: {summary['critical_unsupported']}",
                f"- Tasa de enlace DOI: {float(summary['doi_link_rate']):.1%}",
                f"- Tasa de anclaje de página: {float(summary['page_anchor_rate']):.1%}",
                "",
                "La matriz completa está en `claim-evidence-ledger.csv`. "
                "Una cobertura parcial no invalida automáticamente una síntesis, pero impide presentar "
                "como totalmente localizada una afirmación que no llega a página o fragmento verificable.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return csv_path, json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    paths = write_outputs(review_dir)
    print(json.dumps({"status": "pass", "outputs": [str(path) for path in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
