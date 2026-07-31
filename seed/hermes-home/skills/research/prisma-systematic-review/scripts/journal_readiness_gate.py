#!/usr/bin/env python3
"""Build journal-readiness artifacts for a systematic review workspace.

The script is intentionally deterministic: it does not call a model and it does
not claim that a review is publishable because text exists. It creates the
submission-facing files that journals commonly request and writes a gate report
showing what is complete, what is weak, and what must be fixed before submission.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

PRISMA_2020_URL = "https://www.prisma-statement.org/prisma-2020-checklist"
PRISMA_S_URL = "https://www.prisma-statement.org/prisma-search"
PLOS_SYSTEMATIC_REVIEW_URL = "https://journals.plos.org/plosone/s/submission-guidelines"
ELSEVIER_AI_POLICY_URL = "https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals"
ROBIS_URL = "https://www.robis-tool.info/"
JBI_APPRAISAL_URL = "https://jbi.global/critical-appraisal-tools"


@dataclass
class GateCheck:
    item: str
    status: str
    standard: str
    evidence: str
    detail: str
    fix: str


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def clean_cell(value: object) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return re.sub(r"\s+", " ", text)


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    rendered = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        rendered.append("| " + " | ".join(clean_cell(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(rendered)


def first_existing(review_dir: pathlib.Path, candidates: list[str]) -> pathlib.Path | None:
    for rel in candidates:
        path = review_dir / rel
        if path.exists():
            return path
    return None


def parse_intake_value(intake_text: str, labels: list[str]) -> str:
    for label in labels:
        match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", intake_text, flags=re.MULTILINE)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return ""


def row_first(row: dict[str, str], *fields: str) -> str:
    for field in fields:
        value = clean_cell(row.get(field))
        if value:
            return value
    return ""


def review_title(review_dir: pathlib.Path) -> str:
    manuscript = read_text(review_dir / "paper" / "manuscript" / "publication-ready.md")
    match = re.search(r"^#\s+(.+)$", manuscript, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    intake = read_text(review_dir / "protocol" / "intake.md")
    return parse_intake_value(intake, ["Tema", "Topic", "Título", "Titulo"]) or review_dir.name


def declared_target_outlet(review_dir: pathlib.Path) -> str:
    intake = read_text(review_dir / "protocol" / "intake.md")
    return parse_intake_value(
        intake,
        [
            "Revista o medio objetivo (opcional; si se omite, o si solo indicas una familia temática amplia, Hermes usa `generic-common-core`)",
            "Revista objetivo (opcional)",
            "Target outlet",
        ],
    )


def review_mode_decision(review_dir: pathlib.Path) -> dict[str, object]:
    path = review_dir / "protocol" / "review-mode.json"
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def selected_rows(review_dir: pathlib.Path) -> list[dict[str, str]]:
    shortlist = read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")
    if shortlist:
        selected = [
            row
            for row in shortlist
            if (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "si", "sí", "true", "1"}
        ]
        if selected:
            return selected
    extraction = read_csv_rows(review_dir / "extraction" / "extraction-table.csv")
    return extraction


def excluded_full_text_rows(review_dir: pathlib.Path) -> list[dict[str, str]]:
    rows = read_csv_rows(review_dir / "screening" / "full-text.csv")
    excluded: list[dict[str, str]] = []
    for row in rows:
        decision = (row.get("full_text_decision") or row.get("decision") or row.get("include_full_text") or "").strip().lower()
        if decision in {"exclude", "excluded", "ko", "no", "false", "0"}:
            excluded.append(row)
    return excluded


def write_full_text_exclusions(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    rows = excluded_full_text_rows(review_dir)
    output = submission_dir / "full-text-excluded-with-reasons.csv"
    fieldnames = ["record_id", "doi", "title", "exclusion_reason", "detail", "source_file"]
    rendered = []
    for row in rows:
        rendered.append(
            {
                "record_id": row.get("record_id") or row.get("id") or "",
                "doi": row.get("assigned_doi") or row.get("doi") or "",
                "title": row.get("title_original") or row.get("title") or row.get("title_en") or "",
                "exclusion_reason": row.get("exclusion_reason") or row.get("reason") or row.get("full_text_reason") or "",
                "detail": row.get("detail") or row.get("notes") or "",
                "source_file": "screening/full-text.csv",
            }
        )
    write_csv(output, fieldnames, rendered)
    return output


def quality_label(row: dict[str, str]) -> str:
    confidence_raw = row.get("extraction_confidence") or row.get("methodological_quality") or row.get("quality_score") or ""
    try:
        confidence = float(str(confidence_raw).replace(",", "."))
    except ValueError:
        confidence = 0.0
    missing = 0
    for field in ("sample_size", "countries", "theory_framework", "method_used"):
        if not (row.get(field) or "").strip():
            missing += 1
    if confidence >= 75 and missing <= 1:
        return "bajo"
    if missing >= 3 or confidence < 45:
        return "medio-alto"
    return "medio"


def write_risk_of_bias_matrix(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    output = submission_dir / "risk-of-bias-matrix.csv"
    mode = review_mode_decision(review_dir)
    appraisal_family = "; ".join(str(item) for item in mode.get("critical_appraisal_tools", [])[:6]) if isinstance(mode.get("critical_appraisal_tools"), list) else "ROBIS/JBI/MMAT-style appraisal"
    appraisal_domains = "; ".join(str(item) for item in mode.get("critical_appraisal_domains", [])[:8]) if isinstance(mode.get("critical_appraisal_domains"), list) else ""
    critical_rows = read_csv_rows(review_dir / "tables" / "critical-appraisal-matrix.csv")

    def indicator(value: str) -> str:
        normalized = (value or "").strip().upper()
        if normalized == "1":
            return "yes"
        if normalized == "0":
            return "no"
        if normalized == "NA":
            return "not applicable"
        return value or "not reported"

    if critical_rows:
        fieldnames = [
            "record_id",
            "doi",
            "title",
            "review_mode",
            "appraisal_family",
            "mode_specific_domains",
            "work_type",
            "empirical_type",
            "appraisal_design",
            "extraction_confidence",
            "coverage_score",
            "appraisal_score",
            "sample_reported",
            "context_reported",
            "theory_reported",
            "comparator_reported",
            "validation_reported",
            "overall_reporting_risk",
            "gaps",
            "basis",
        ]
        rendered = []
        for row in critical_rows:
            rendered.append(
                {
                    "record_id": row.get("record_id", ""),
                    "doi": row.get("doi", ""),
                    "title": row.get("title_original", ""),
                    "review_mode": row.get("review_mode") or mode.get("mode_label", ""),
                    "appraisal_family": row.get("appraisal_family") or appraisal_family,
                    "mode_specific_domains": row.get("mode_specific_domains") or appraisal_domains,
                    "work_type": row.get("work_type", ""),
                    "empirical_type": row.get("empirical_type", ""),
                    "appraisal_design": row.get("appraisal_design", ""),
                    "extraction_confidence": row.get("extraction_confidence", ""),
                    "coverage_score": row.get("coverage_score", ""),
                    "appraisal_score": row.get("appraisal_score", ""),
                    "sample_reported": indicator(row.get("sample_reported", "")),
                    "context_reported": indicator(row.get("context_reported", "")),
                    "theory_reported": indicator(row.get("theory_reported", "")),
                    "comparator_reported": indicator(row.get("comparator_reported", "")),
                    "validation_reported": indicator(row.get("validation_reported", "")),
                    "overall_reporting_risk": row.get("reporting_risk", ""),
                    "gaps": row.get("gaps", ""),
                    "basis": "Mode-aware critical appraisal from the full-text extraction matrix; this is reporting/traceability appraisal and does not claim to replace a validated causal risk-of-bias tool for every design.",
                }
            )
        write_csv(output, fieldnames, rendered)
        return output

    rows = selected_rows(review_dir)
    fieldnames = [
        "record_id",
        "doi",
        "title",
        "review_mode",
        "appraisal_family",
        "work_type",
        "empirical_type",
        "sample_reported",
        "context_reported",
        "theory_reported",
        "method_reported",
        "overall_reporting_risk",
        "basis",
    ]
    rendered = []
    for row in rows:
        rendered.append(
            {
                "record_id": row.get("record_id") or "",
                "doi": row.get("assigned_doi") or row.get("doi") or "",
                "title": row.get("title_original") or row.get("title_en") or row.get("title") or "",
                "review_mode": mode.get("mode_label", ""),
                "appraisal_family": appraisal_family,
                "work_type": row.get("work_type") or "",
                "empirical_type": row.get("empirical_type") or "",
                "sample_reported": "yes" if (row.get("sample_size") or row.get("sample_description") or "").strip() else "no",
                "context_reported": "yes" if (row.get("countries") or row.get("context") or "").strip() else "no",
                "theory_reported": "yes" if (row.get("theory_framework") or "").strip() else "no",
                "method_reported": "yes" if (row.get("method_used") or "").strip() else "no",
                "overall_reporting_risk": quality_label(row),
                "basis": f"Mode-aware reporting-risk appraisal from the extraction matrix. Domains: {appraisal_domains or 'sample/context/theory/method/comparator/validation'}.",
            }
        )
    write_csv(output, fieldnames, rendered)
    return output


def write_protocol_publication_ready(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    intake = read_text(review_dir / "protocol" / "intake.md")
    search_strategy = read_text(review_dir / "protocol" / "search-strategy.md")
    review_mode = read_text(review_dir / "protocol" / "review-mode.md")
    title = review_title(review_dir)
    target = declared_target_outlet(review_dir) or "generic-common-core"
    output = submission_dir / "protocol-publication-ready.md"
    lines = [
        "# Protocol Publication-Ready",
        "",
        f"- Title: {title}",
        f"- Editorial target: {target}",
        f"- Generated: {datetime.now(timezone.utc).astimezone().isoformat()}",
        "",
        "## Scope fixed before screening",
        intake.strip() or "_No intake file was found; this must be completed before submission._",
        "",
        "## Review mode fixed before search",
        review_mode.strip() or "_No protocol/review-mode.md was found; add discipline-specific mode before submission._",
        "",
        "## Search strategy",
        search_strategy.strip() or "_No protocol/search-strategy.md was found; use search-strategies-by-source.md and searches/search-log.csv as fallback evidence._",
        "",
        "## Minimum publication rule",
        "The protocol must make the research question, eligibility criteria, sources, time window, screening logic, full-text requirements, extraction fields, quality appraisal, synthesis strategy, and deviations auditable before the manuscript is submitted.",
    ]
    write_text(output, "\n".join(lines))
    return output


def write_protocol_deviations(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    decisions = read_text(review_dir / "notes" / "decisions.md")
    runtime = read_text(review_dir / "notes" / "runtime-state.md") or read_text(review_dir / "notes" / "runtime-state.json")
    output = submission_dir / "protocol-deviations.md"
    lines = [
        "# Protocol Deviations",
        "",
        "This file separates planned method from operational deviations. Journals usually tolerate deviations better when they are explicit, dated, and linked to evidence.",
        "",
        "## Recorded decisions",
        decisions.strip() or "_No decisions.md file was found. If the review changed eligibility, source coverage, N target, search terms, model policy, or synthesis strategy, document it here before submission._",
        "",
        "## Runtime evidence",
        runtime.strip()[:8000] or "_No runtime-state note was found._",
    ]
    write_text(output, "\n".join(lines))
    return output


def write_search_strategies_by_source(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    rows = read_csv_rows(review_dir / "searches" / "search-log.csv")
    output = submission_dir / "search-strategies-by-source.md"
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        source = row.get("source") or row.get("database") or row.get("provider") or "unknown"
        grouped.setdefault(source, []).append(row)
    lines = [
        "# Search Strategies by Source",
        "",
        f"Normative anchor: PRISMA-S ({PRISMA_S_URL}). Each source should preserve query string, date, limits, export format, and incidents.",
    ]
    if not grouped:
        lines.append("\n_No search-log.csv rows were found._")
    for source, source_rows in sorted(grouped.items()):
        lines.extend(["", f"## {source}", ""])
        table_rows = []
        for row in source_rows[:50]:
            table_rows.append(
                [
                    row_first(row, "date", "searched_at", "run_date"),
                    row_first(row, "query", "search_query", "query_string"),
                    row.get("records") or row.get("count") or "",
                    row.get("notes") or row.get("limits") or "",
                ]
            )
        lines.append(markdown_table(["Date", "Query", "Records", "Notes/limits"], table_rows))
    write_text(output, "\n".join(lines))
    return output


def write_search_peer_review(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    search_log = read_csv_rows(review_dir / "searches" / "search-log.csv")
    sources = sorted({row.get("source") or row.get("database") or row.get("provider") or "unknown" for row in search_log})
    output = submission_dir / "search-peer-review.md"
    lines = [
        "# Search Peer Review",
        "",
        "This is a PRESS-like internal check of the search strategy. It does not pretend that an external librarian reviewed the strategy unless that actually happened.",
        "",
        markdown_table(
            ["Question", "Status", "Evidence", "Action"],
            [
                ["Are all databases/sources named?", "yes" if sources else "no", ", ".join(sources) or "search-log.csv missing", "Complete source list before submission."],
                ["Are exact query strings preserved?", "yes" if any(row_first(row, "query", "search_query", "query_string") for row in search_log) else "no", "searches/search-log.csv", "Add exact query strings for every source."],
                ["Are dates and limits visible?", "yes" if any(row_first(row, "date", "searched_at", "run_date") for row in search_log) else "no", "searches/search-log.csv", "Add search dates, filters, language/date limits, and export format."],
                ["Is the strategy replicable without Hermes internals?", "partial", "protocol/search-strategy.md", "Rewrite any internal command as a method description."],
            ],
        ),
    ]
    write_text(output, "\n".join(lines))
    return output


def write_prisma_2020_checklist(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    manuscript = read_text(review_dir / "paper" / "manuscript" / "publication-ready.md")
    items = [
        ("1", "Title", "title" if re.search(r"^#\s+", manuscript, re.M) else ""),
        ("2", "Abstract", "resumen" if re.search(r"(?mi)^#*\s*Resumen|^#*\s*Abstract", manuscript) else ""),
        ("5", "Eligibility criteria", "Método" if "criterios" in manuscript.lower() else ""),
        ("6", "Information sources", "Método" if "fuente" in manuscript.lower() or "database" in manuscript.lower() else ""),
        ("7", "Search strategy", "paper/journal-readiness/search-strategies-by-source.md"),
        ("8", "Selection process", "screening/title-abstract.csv; screening/full-text.csv"),
        ("9", "Data collection process", "extraction/extraction-table.csv"),
        ("11", "Risk of bias assessment", "paper/journal-readiness/risk-of-bias-matrix.csv"),
        ("13", "Synthesis methods", "Método; Resultados; Discusión"),
        ("16", "Study selection", "prisma/flow-counts.csv"),
        ("24", "Registration and protocol", "paper/journal-readiness/protocol-publication-ready.md"),
        ("27", "Funding", "paper/journal-readiness/conflicts-funding-ethics.md"),
    ]
    rows = []
    for item, label, evidence in items:
        rows.append({"item": item, "prisma_2020_element": label, "status": "covered" if evidence else "missing", "evidence": evidence})
    output = submission_dir / "prisma-2020-checklist-completed.csv"
    write_csv(output, ["item", "prisma_2020_element", "status", "evidence"], rows)
    return output


def write_prisma_s_checklist(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    search_log = read_csv_rows(review_dir / "searches" / "search-log.csv")
    rows = [
        {"item": "1", "prisma_s_element": "Database/source names", "status": "covered" if search_log else "missing", "evidence": "searches/search-log.csv"},
        {"item": "2", "prisma_s_element": "Full search strategies", "status": "covered" if any(row_first(row, "query", "search_query", "query_string") for row in search_log) else "missing", "evidence": "paper/journal-readiness/search-strategies-by-source.md"},
        {"item": "3", "prisma_s_element": "Limits and restrictions", "status": "partial", "evidence": "searches/search-log.csv; protocol/search-strategy.md"},
        {"item": "4", "prisma_s_element": "Search dates", "status": "covered" if any(row_first(row, "date", "searched_at", "run_date") for row in search_log) else "missing", "evidence": "searches/search-log.csv"},
        {"item": "5", "prisma_s_element": "Record management", "status": "covered", "evidence": "records/master-records.csv; records/duplicates.csv; records/doi-index.csv"},
    ]
    output = submission_dir / "prisma-s-checklist-completed.csv"
    write_csv(output, ["item", "prisma_s_element", "status", "evidence"], rows)
    return output


def write_synthesis_decisions(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    selected = selected_rows(review_dir)
    output = submission_dir / "synthesis-eligibility-decision.md"
    lines = [
        "# Synthesis Eligibility Decision",
        "",
        "This note explains why the manuscript uses narrative/thematic/focal synthesis rather than treating every included record as equally informative.",
        "",
        f"- Focal or extracted records available: {len(selected)}",
        "- Intensive synthesis is justified only when full text, extraction fields, and quality/risk signals are available.",
        "- Records outside the focal N may remain useful for mapping the field, but should not carry fine-grained causal or comparative claims.",
    ]
    write_text(output, "\n".join(lines))
    return output


def write_no_meta_analysis_rationale(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> pathlib.Path:
    extraction = read_csv_rows(review_dir / "extraction" / "extraction-table.csv")
    methods = sorted({clean_cell(row.get("method_used")) for row in extraction if clean_cell(row.get("method_used"))})
    output = submission_dir / "no-meta-analysis-rationale.md"
    lines = [
        "# No Meta-Analysis Rationale",
        "",
        "A meta-analysis should only be claimed when effect sizes, comparable outcomes, compatible designs, and sufficient statistical information are available. This review defaults to structured synthesis unless those conditions are met.",
        "",
        f"- Distinct reported methods detected: {len(methods)}",
        f"- Method examples: {', '.join(methods[:12]) if methods else 'not enough method detail recovered'}",
        "- Operational decision: use narrative, thematic, architectural, methodological, or configurational synthesis unless a target journal asks for quantitative pooling and the extraction matrix supports it.",
    ]
    write_text(output, "\n".join(lines))
    return output


def write_editorial_statements(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> list[pathlib.Path]:
    title = review_title(review_dir)
    target = declared_target_outlet(review_dir) or "generic-common-core"
    outputs: list[pathlib.Path] = []
    statements = {
        "data-availability-statement.md": [
            "# Data Availability Statement",
            "",
            "All derived review data needed to audit the synthesis are provided in the publication package, including search logs, screening decisions, full-text exclusions, extraction tables, selection matrices, figure gates, and journal-readiness reports. Source PDFs are included only when locally available and legally usable for audit.",
        ],
        "code-availability-statement.md": [
            "# Code Availability Statement",
            "",
            "The review used a deterministic and auditable systematic-review workflow. The reproducibility package preserves the manuscript, LaTeX source, CSV matrices, audit reports, peer-review packet, and readiness gate. Reusable code should be shared without API keys, local paths, private tokens, or provider-specific secrets.",
        ],
        "generative-ai-disclosure.md": [
            "# Generative AI Disclosure",
            "",
            "Generative AI was used as an assisted drafting, extraction, synthesis, and editorial-audit layer under deterministic file-based controls. The system retained search logs, screening decisions, extraction matrices, full-text evidence, peer-review outputs, and gate reports. The author remains responsible for verifying claims, references, figures, tables, and journal-specific declarations.",
            "",
            f"Policy anchor: Elsevier generative AI policy ({ELSEVIER_AI_POLICY_URL}). Adapt wording to the target journal before submission.",
        ],
        "conflicts-funding-ethics.md": [
            "# Conflicts, Funding, and Ethics",
            "",
            "Conflicts of interest: to be completed by the author before submission.",
            "",
            "Funding: to be completed by the author before submission.",
            "",
            "Ethics: this review synthesizes published literature and does not involve new human-subject data collection unless the author adds such material later.",
        ],
        "cover-letter.md": [
            "# Cover Letter Draft",
            "",
            "Dear Editor,",
            "",
            f"I submit the manuscript “{title}” for consideration in {target}. The article reports a systematic literature review with transparent search, screening, extraction, selection, synthesis, and journal-readiness artifacts. The submission package includes the manuscript, editable LaTeX, references, CSV annexes, figure evidence, full-text exclusion reasons, risk/reporting appraisal, and AI-use disclosure.",
            "",
            "Sincerely,",
            "",
            "[Author name]",
        ],
        "journal-fit-report.md": [
            "# Journal Fit Report",
            "",
            f"- Current outlet profile: {target}",
            "- If no journal is declared, Hermes uses a generic-common-core profile and avoids journal-specific claims.",
            "- Before submission, check word limits, abstract structure, reference style, figure/table limits, AI disclosure wording, data availability wording, and whether the journal requires PRISMA flow as a figure rather than a table.",
            "",
            f"Useful benchmark: PLOS ONE systematic review guidance ({PLOS_SYSTEMATIC_REVIEW_URL}).",
        ],
    }
    for filename, lines in statements.items():
        path = submission_dir / filename
        write_text(path, "\n".join(lines))
        outputs.append(path)
    return outputs


def count_main_body_figures(review_dir: pathlib.Path) -> int:
    rows = read_csv_rows(review_dir / "figures" / "figure-gate.csv")
    return sum(1 for row in rows if (row.get("placement") or "").strip() == "main_body" and (row.get("decision") or "").strip() == "include")


def build_checks(review_dir: pathlib.Path, submission_dir: pathlib.Path) -> list[GateCheck]:
    manuscript_md = review_dir / "paper" / "manuscript" / "publication-ready.md"
    manuscript_tex = review_dir / "paper" / "manuscript" / "publication-ready.tex"
    manuscript_pdf = review_dir / "paper" / "manuscript" / "publication-ready.pdf"
    manuscript = read_text(manuscript_md)
    selected = selected_rows(review_dir)
    search_log = read_csv_rows(review_dir / "searches" / "search-log.csv")
    flow_counts = read_csv_rows(review_dir / "prisma" / "flow-counts.csv")
    exclusions = read_csv_rows(submission_dir / "full-text-excluded-with-reasons.csv")
    risk_rows = read_csv_rows(submission_dir / "risk-of-bias-matrix.csv")
    figure_gate = read_csv_rows(review_dir / "figures" / "figure-gate.csv")
    checks: list[GateCheck] = []

    def add(item: str, status: str, standard: str, evidence: str, detail: str, fix: str) -> None:
        checks.append(GateCheck(item, status, standard, evidence, detail, fix))

    add(
        "complete_manuscript_files",
        "PASS" if manuscript_md.exists() and manuscript_tex.exists() and manuscript_pdf.exists() else "FAIL",
        "Journal submission package",
        "paper/manuscript/",
        "MD, LaTeX, and PDF should exist together.",
        "Regenerate export_publication_latex.py and package_publication_bundle.py.",
    )
    add(
        "protocol_traceability",
        "PASS" if (review_dir / "protocol" / "intake.md").exists() else "FAIL",
        "PRISMA 2020 item 24",
        "protocol/intake.md; paper/journal-readiness/protocol-publication-ready.md",
        "The review must preserve its question, eligibility criteria, scope, and planned method.",
        "Complete intake and protocol before claiming systematic-review status.",
    )
    add(
        "search_reproducibility",
        "PASS" if search_log and any(row_first(row, "query", "search_query", "query_string") for row in search_log) else "WARN",
        "PRISMA-S",
        "searches/search-log.csv; paper/journal-readiness/search-strategies-by-source.md",
        f"Search rows detected: {len(search_log)}.",
        "Ensure every source has exact query, date, limits, and export format.",
    )
    add(
        "study_selection_accounting",
        "PASS" if flow_counts else "FAIL",
        "PRISMA 2020 study selection",
        "prisma/flow-counts.csv",
        f"Flow-count rows detected: {len(flow_counts)}.",
        "Recompute flow counts from screening CSV files.",
    )
    add(
        "full_text_exclusion_reasons",
        "PASS" if exclusions else "WARN",
        "PRISMA 2020 item 16b",
        "paper/journal-readiness/full-text-excluded-with-reasons.csv",
        f"Full-text exclusions exported: {len(exclusions)}.",
        "If there were no exclusions, state that explicitly; otherwise fill reasons.",
    )
    add(
        "critical_appraisal",
        "PASS" if risk_rows else "WARN",
        "ROBIS/JBI/MMAT-style appraisal",
        "paper/journal-readiness/risk-of-bias-matrix.csv",
        f"Risk/reporting rows detected: {len(risk_rows)}.",
        "Use a named instrument if the target journal requires one.",
    )
    add(
        "no_internal_ids_in_manuscript",
        "PASS" if not re.search(r"\bRID-|record_id\b", manuscript, flags=re.IGNORECASE) else "FAIL",
        "Submission readability",
        "paper/manuscript/publication-ready.md",
        "The manuscript should cite DOI/title/author evidence, not internal IDs.",
        "Replace internal IDs with DOI or stable bibliographic identifiers.",
    )
    add(
        "figure_gate",
        "PASS" if figure_gate and count_main_body_figures(review_dir) <= 4 else "WARN",
        "Figure economy and journal fit",
        "figures/figure-gate.csv",
        f"Main-body figures included: {count_main_body_figures(review_dir)}.",
        "Keep only analytical figures in the body; move process/internal figures to supplement.",
    )
    add(
        "ai_use_disclosure",
        "PASS" if (submission_dir / "generative-ai-disclosure.md").exists() else "FAIL",
        "Publisher AI disclosure policies",
        "paper/journal-readiness/generative-ai-disclosure.md",
        "The package must disclose AI assistance truthfully without naming secrets or internal endpoints unnecessarily.",
        "Generate and adapt the AI disclosure for the target journal.",
    )
    add(
        "data_code_availability",
        "PASS" if (submission_dir / "data-availability-statement.md").exists() and (submission_dir / "code-availability-statement.md").exists() else "FAIL",
        "Journal transparency statements",
        "paper/journal-readiness/data-availability-statement.md; code-availability-statement.md",
        "Submission should include data and code availability statements.",
        "Write statements that match the final sharing policy.",
    )
    add(
        "focal_corpus_documented",
        "PASS" if selected else "FAIL",
        "Systematic synthesis traceability",
        "selection/ultraquality-shortlist.csv; extraction/extraction-table.csv",
        f"Focal/extracted rows detected: {len(selected)}.",
        "Complete extraction and focal selection before final manuscript generation.",
    )
    return checks


def global_status(checks: list[GateCheck]) -> str:
    if any(check.status == "FAIL" for check in checks):
        return "FAIL"
    if any(check.status == "WARN" for check in checks):
        return "WARN"
    return "PASS"


def write_gate_outputs(review_dir: pathlib.Path, submission_dir: pathlib.Path, checks: list[GateCheck]) -> tuple[pathlib.Path, pathlib.Path]:
    csv_path = submission_dir / "journal-readiness-gate.csv"
    write_csv(
        csv_path,
        ["item", "status", "standard", "evidence", "detail", "fix"],
        [
            {
                "item": check.item,
                "status": check.status,
                "standard": check.standard,
                "evidence": check.evidence,
                "detail": check.detail,
                "fix": check.fix,
            }
            for check in checks
        ],
    )
    status = global_status(checks)
    report_path = submission_dir / "journal-readiness-report.md"
    rows = [[check.item, check.status, check.standard, check.evidence, check.fix] for check in checks]
    lines = [
        "# Journal Readiness Gate",
        "",
        f"Estado global: **{status}**",
        f"Fecha: {datetime.now(timezone.utc).astimezone().isoformat()}",
        "",
        "## Purpose",
        "This gate checks whether a systematic review package is close to journal submission, not whether the argument is scientifically true. It focuses on traceability, reporting, disclosure, packaging, and avoidable editorial blockers.",
        "",
        "## Gate Matrix",
        markdown_table(["Item", "Status", "Standard", "Evidence", "Fix"], rows),
        "",
        "## Normative Anchors",
        f"- PRISMA 2020 checklist: {PRISMA_2020_URL}",
        f"- PRISMA-S search reporting: {PRISMA_S_URL}",
        f"- PLOS ONE systematic review submission guidance: {PLOS_SYSTEMATIC_REVIEW_URL}",
        f"- ROBIS risk-of-bias tool: {ROBIS_URL}",
        f"- JBI critical appraisal tools: {JBI_APPRAISAL_URL}",
        f"- Publisher AI disclosure example policy: {ELSEVIER_AI_POLICY_URL}",
    ]
    write_text(report_path, "\n".join(lines))
    return csv_path, report_path


def build_journal_readiness(review_dir: pathlib.Path) -> tuple[str, pathlib.Path]:
    submission_dir = review_dir / "paper" / "journal-readiness"
    submission_dir.mkdir(parents=True, exist_ok=True)

    write_protocol_publication_ready(review_dir, submission_dir)
    write_protocol_deviations(review_dir, submission_dir)
    write_search_strategies_by_source(review_dir, submission_dir)
    write_search_peer_review(review_dir, submission_dir)
    write_full_text_exclusions(review_dir, submission_dir)
    write_risk_of_bias_matrix(review_dir, submission_dir)
    write_prisma_2020_checklist(review_dir, submission_dir)
    write_prisma_s_checklist(review_dir, submission_dir)
    write_synthesis_decisions(review_dir, submission_dir)
    write_no_meta_analysis_rationale(review_dir, submission_dir)
    write_editorial_statements(review_dir, submission_dir)

    checks = build_checks(review_dir, submission_dir)
    _csv_path, report_path = write_gate_outputs(review_dir, submission_dir, checks)
    return global_status(checks), report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review workspace")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory not found: {review_dir}")

    status, report_path = build_journal_readiness(review_dir)
    print(f"journal_readiness_gate: {status} {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
