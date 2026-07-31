#!/usr/bin/env python3
"""Convert review comments into a revision roadmap."""

from __future__ import annotations

import argparse
import csv
import pathlib
import re


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def detect_reviewer(active_heading: str) -> str:
    if not active_heading:
        return "general"
    text = active_heading.lower()
    if "reviewer" in text or "revisor" in text or "editor" in text or "eic" in text:
        return active_heading.strip()
    return "general"


def classify_category(text: str) -> str:
    t = text.lower()
    mapping = {
        "method": ("method", "methodolog", "sample", "variable", "regression", "design", "validity", "bias"),
        "results": ("result", "finding", "effect", "metric", "benchmark", "performance"),
        "discussion": ("discussion", "implication", "limitation", "future work"),
        "figures-tables": ("figure", "figura", "table", "tabla", "chart", "graph"),
        "citations": ("citation", "reference", "doi", "bibliograph", "apa"),
        "writing": ("clar", "rewrite", "wording", "style", "english", "spanish", "grammar"),
        "formatting": ("format", "latex", "docx", "pdf", "layout", "caption"),
        "ethics": ("ethic", "disclosure", "bias", "consent", "privacy", "irb"),
        "argument": ("argument", "claim", "contribution", "novelty", "theory", "hypothesis"),
    }
    for category, patterns in mapping.items():
        if any(pattern in t for pattern in patterns):
            return category
    return "other"


def detect_section(text: str) -> str:
    t = text.lower()
    sections = (
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "conclusion",
        "figure",
        "table",
        "references",
        "appendix",
    )
    for section in sections:
        if section in t:
            return section
    if "resumen" in t:
        return "abstract"
    if "metodo" in t or "método" in t or "metodologia" in t or "metodología" in t:
        return "methods"
    if "resultados" in t:
        return "results"
    if "discusion" in t or "discusión" in t:
        return "discussion"
    if "conclus" in t:
        return "conclusion"
    if "referenc" in t or "bibliograf" in t:
        return "references"
    return ""


def detect_priority(text: str) -> str:
    t = text.lower()
    if any(token in t for token in ("critical", "fatal", "major revision", "major", "must", "unsupported", "invalid", "block", "fail", "debe", "ausencia", "omisión")):
        return "high"
    if any(token in t for token in ("should", "unclear", "missing", "needs", "revise", "clarify", "justify", "expand", "debería", "corregir", "verificar", "especificar", "incluir", "añadir", "justificar", "reformular", "completar", "unificar", "qualificar", "desambiguar", "definir")):
        return "medium"
    return "low"


def action_template(category: str) -> str:
    mapping = {
        "method": "Strengthen design, sampling, variables, or analytical justification.",
        "results": "Add or refine evidence, metrics, and result interpretation.",
        "discussion": "Clarify implications, limitations, and boundaries of inference.",
        "figures-tables": "Update figure/table content, captions, or in-text references.",
        "citations": "Verify sources, add missing references, or correct citation style.",
        "writing": "Rewrite for clarity, structure, and register.",
        "formatting": "Fix formatting, packaging, or venue-compliance issues.",
        "ethics": "Resolve disclosure, bias, or ethics documentation issues.",
        "argument": "Tighten contribution framing and claim-evidence alignment.",
    }
    return mapping.get(category, "Resolve the issue and document the change clearly.")


def evidence_template(category: str) -> str:
    mapping = {
        "method": "Method section, extraction table, or supplemental design notes.",
        "results": "Updated table/figure or results paragraph with supporting evidence.",
        "discussion": "Revised discussion or limitations text.",
        "figures-tables": "Updated figure/table asset plus caption and in-text mention.",
        "citations": "Corrected references list and supporting source.",
        "writing": "Revised manuscript passage.",
        "formatting": "Updated output artifact or package check.",
        "ethics": "Disclosure statement or ethics appendix.",
        "argument": "Reframed contribution and supporting citations.",
    }
    return mapping.get(category, "Revised manuscript evidence.")


def is_actionable_comment(text: str) -> bool:
    t = text.strip()
    lower = t.lower()
    if not t:
        return False
    if lower.startswith(("`warn`", "`fail`", "warn:", "fail:")):
        return False
    if lower.startswith(("pass:", "`pass`", "estado global: **pass**", "figuras renderizadas:", "figuras svg disponibles:", "activos visuales/tabulares fuente:", "renders diagnósticos de página:", "tablas integradas en manuscrito:", "palabras aproximadas del manuscrito:", "objetivo mínimo de palabras:", "revisiones cruzadas detectadas:", "estudios seleccionados para el n final:", "anexos csv listos:", "zip editorial generado:", "fecha:")):
        return False
    if re.match(r"^(?:cribado|exclusiones|texto completo|estudios incluidos|diagramas|pdfs válidos|activos visuales|tablas integradas)\b.*:\s*\d+", lower):
        return False
    if re.match(r"^`pass`", lower):
        return False
    if len(t) < 24 and "warn" not in lower and "fail" not in lower:
        return False
    issue_tokens = (
        "should",
        "must",
        "needs",
        "unclear",
        "missing",
        "revise",
        "clarify",
        "justify",
        "expand",
        "critical",
        "major",
        "minor",
        "absence",
        "redund",
        "correg",
        "incluir",
        "añadir",
        "justificar",
        "reformular",
        "verificar",
        "completar",
        "definir",
        "unificar",
        "qualificar",
        "desambiguar",
        "especificar",
        "warn",
        "fail",
        "**",
    )
    return any(token in lower for token in issue_tokens)


def extract_items(path: pathlib.Path) -> list[dict[str, str]]:
    lines = read_text(path).splitlines()
    items: list[dict[str, str]] = []
    active_heading = ""
    fallback_buffer: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            active_heading = re.sub(r"^#+\s*", "", line).strip()
            continue
        bullet = re.match(r"^(?:[-*+]\s+|\d+\.\s+)(.+)$", line)
        if bullet:
            comment = bullet.group(1).strip()
        elif len(line) > 40 and re.search(r"\b(should|must|needs|unclear|missing|revise|clarify|justify|expand|critical|major)\b", line, flags=re.IGNORECASE):
            comment = line
        else:
            fallback_buffer.append(line)
            continue
        if not is_actionable_comment(comment):
            continue
        category = classify_category(comment)
        items.append(
            {
                "reviewer": detect_reviewer(active_heading),
                "comment": comment,
                "category": category,
                "priority": detect_priority(comment),
                "section_hint": detect_section(comment),
                "action_needed": action_template(category),
                "evidence_needed": evidence_template(category),
            }
        )
    if not items and fallback_buffer:
        merged = " ".join(fallback_buffer)
        if is_actionable_comment(merged):
            category = classify_category(merged)
            items.append(
                {
                    "reviewer": detect_reviewer(active_heading),
                    "comment": merged,
                    "category": category,
                    "priority": detect_priority(merged),
                    "section_hint": detect_section(merged),
                    "action_needed": action_template(category),
                    "evidence_needed": evidence_template(category),
                }
            )
    return items


def write_csv(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "item_id",
        "source_file",
        "reviewer",
        "category",
        "priority",
        "section_hint",
        "comment",
        "action_needed",
        "evidence_needed",
        "response_placeholder",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_markdown(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    lines = [
        "# Revision Roadmap",
        "",
        "| ID | Reviewer | Category | Priority | Section | Status | Comment |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        comment = row["comment"].replace("|", "\\|")
        lines.append(
            f"| {row['item_id']} | {row['reviewer']} | {row['category']} | {row['priority']} | {row['section_hint']} | {row['status']} | {comment} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path)
    args = parser.parse_args()

    first_parent = args.inputs[0].resolve().parent
    output_dir = args.output_dir or first_parent / "revision-roadmap"
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    counter = 1
    for input_path in args.inputs:
        resolved = input_path.resolve()
        for item in extract_items(resolved):
            row = dict(item)
            row["item_id"] = f"RR-{counter:03d}"
            row["source_file"] = str(resolved)
            row["response_placeholder"] = "Explain the change made and where it appears in the manuscript."
            row["status"] = "open"
            rows.append(row)
            counter += 1

    write_csv(output_dir / "revision-roadmap.csv", rows)
    write_markdown(output_dir / "revision-roadmap.md", rows)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
