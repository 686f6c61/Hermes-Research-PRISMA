#!/usr/bin/env python3
"""Run static integrity checks over a manuscript and optional review bundle."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from dataclasses import asdict, dataclass

PLACEHOLDER_SPECS = [
    (r"\bTODO\b", 0),
    (r"\bTBD\b", 0),
    (r"\bFIXME\b", 0),
    (r"\[CITATION NEEDED\]", re.IGNORECASE),
    (r"_Pendiente_", 0),
    (r"lorem ipsum", re.IGNORECASE),
]


REQUIRED_SECTION_GROUPS = {
    "abstract": ("abstract", "resumen"),
    "keywords": ("keywords", "palabras clave"),
    "introduction": ("introduction", "introduccion", "introducción"),
    "method": ("method", "methods", "methodology", "metodo", "método", "metodologia", "metodología"),
    "discussion_or_results": ("results", "findings", "hallazgos", "resultados", "discussion", "discusion", "discusión"),
    "conclusion": ("conclusion", "conclusions", "conclusiones"),
    "references": ("references", "referencias", "bibliography", "bibliografia", "bibliografía"),
}


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    evidence: str = ""


def normalize(value: str) -> str:
    value = value.lower()
    return (
        value.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def find_headings(text: str) -> list[str]:
    return [match.group(2).strip() for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.MULTILINE)]


def local_links(text: str) -> list[str]:
    links = []
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("#"):
            continue
        links.append(target)
    return links


def exists_relative(target: str, base: pathlib.Path) -> bool:
    clean = target.split(":", 1)[0].strip("<>").strip()
    if not clean:
        return True
    path = pathlib.Path(clean)
    if path.is_absolute():
        return path.exists()
    return (base / path).exists()


def build_issues(manuscript_path: pathlib.Path, review_dir: pathlib.Path | None) -> tuple[list[Issue], dict]:
    text = read_text(manuscript_path)
    headings = [normalize(item) for item in find_headings(text)]
    issues: list[Issue] = []
    words = len(re.findall(r"\b\w+\b", text))
    citation_count = len(re.findall(r"\([^)]*(?:19|20)\d{2}[a-z]?[^)]*\)", text))
    numeric_citation_count = len(re.findall(r"\[\d+(?:\s*[-,]\s*\d+)*\]", text))
    figure_mentions = len(re.findall(r"\b(?:figure|figura)\s+\d+\b", text, flags=re.IGNORECASE))
    image_count = len(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text))
    table_mentions = len(re.findall(r"\b(?:table|tabla)\s+\d+\b", text, flags=re.IGNORECASE))

    for pattern, flags in PLACEHOLDER_SPECS:
        for match in re.finditer(pattern, text, flags=flags):
            issues.append(Issue("ERROR", "placeholder", f"Placeholder token found: {match.group(0)}", match.group(0)))

    for key, patterns in REQUIRED_SECTION_GROUPS.items():
        if not any(any(pattern in heading for pattern in patterns) for heading in headings):
            severity = "ERROR" if key in {"abstract", "references"} else "WARN"
            issues.append(Issue(severity, "missing-section", f"Missing expected section group: {key}"))

    if words > 1200 and citation_count + numeric_citation_count == 0:
        issues.append(Issue("WARN", "citation-scarcity", "Long manuscript without visible in-text citations."))

    if (citation_count + numeric_citation_count) > 0 and not any("references" in heading or "referencias" in heading for heading in headings):
        issues.append(Issue("ERROR", "missing-references", "In-text citations found but no references section detected."))

    if figure_mentions > 0 and image_count == 0:
        issues.append(Issue("WARN", "figure-support", "Figures are mentioned in text but no image embeds were found."))

    if table_mentions > 0 and "|" not in text:
        issues.append(Issue("WARN", "table-support", "Tables are mentioned in text but no markdown tables were detected."))

    for target in local_links(text):
        if not exists_relative(target, manuscript_path.parent):
            issues.append(Issue("ERROR", "broken-link", f"Broken local link: {target}", target))

    if review_dir and review_dir.exists():
        package_zip = review_dir / "paper" / "package" / "publication-package.zip"
        if not package_zip.exists():
            issues.append(Issue("WARN", "missing-package", "Publication package ZIP not found in review workspace."))
        appendix_dir = review_dir / "paper" / "appendices" / "data"
        if not appendix_dir.exists() or not list(appendix_dir.glob("*.csv")):
            issues.append(Issue("WARN", "missing-appendices", "No appendix CSV files detected in paper/appendices/data."))
        pdf_count = 0
        for candidate in (review_dir / "fulltext" / "pdf", review_dir / "pdfs"):
            if candidate.exists():
                pdf_count += len(list(candidate.glob("*.pdf")))
        if pdf_count == 0:
            issues.append(Issue("WARN", "missing-pdfs", "No local PDF corpus detected in fulltext/pdf or pdfs."))
        audit_path = review_dir / "paper" / "audit" / "publication-audit.md"
        if not audit_path.exists():
            issues.append(Issue("WARN", "missing-audit", "Audit artifact missing: publication-audit.md"))

    summary = {
        "manuscript_path": str(manuscript_path),
        "review_dir": str(review_dir) if review_dir else "",
        "word_count": words,
        "citation_count": citation_count,
        "numeric_citation_count": numeric_citation_count,
        "figure_mentions": figure_mentions,
        "image_count": image_count,
        "issue_counts": {
            "error": sum(1 for issue in issues if issue.severity == "ERROR"),
            "warn": sum(1 for issue in issues if issue.severity == "WARN"),
            "info": sum(1 for issue in issues if issue.severity == "INFO"),
        },
    }
    return issues, summary


def render_markdown(summary: dict, issues: list[Issue]) -> str:
    lines = [
        "# Integrity Audit",
        "",
        f"- Manuscript: `{summary['manuscript_path']}`",
    ]
    if summary.get("review_dir"):
        lines.append(f"- Review dir: `{summary['review_dir']}`")
    lines.extend(
        [
            f"- Word count: {summary['word_count']}",
            f"- In-text citations: {summary['citation_count'] + summary['numeric_citation_count']}",
            f"- Figure mentions: {summary['figure_mentions']}",
            f"- Embedded images: {summary['image_count']}",
            "",
            "## Findings",
        ]
    )
    if not issues:
        lines.append("- No static issues detected.")
    else:
        for issue in issues:
            suffix = f" (`{issue.evidence}`)" if issue.evidence else ""
            lines.append(f"- [{issue.severity}] `{issue.code}` {issue.message}{suffix}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manuscript", type=pathlib.Path)
    parser.add_argument("--review-dir", type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path)
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    manuscript_path = args.manuscript.resolve()
    review_dir = args.review_dir.resolve() if args.review_dir else None
    output_dir = args.output_dir or manuscript_path.parent / "integrity-audit"
    output_dir.mkdir(parents=True, exist_ok=True)

    issues, summary = build_issues(manuscript_path, review_dir)
    (output_dir / "integrity-audit.json").write_text(
        json.dumps({"summary": summary, "issues": [asdict(issue) for issue in issues]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "integrity-audit.md").write_text(render_markdown(summary, issues), encoding="utf-8")
    print(output_dir)
    if args.fail_on_error and any(issue.severity == "ERROR" for issue in issues):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
