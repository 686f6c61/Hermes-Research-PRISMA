#!/usr/bin/env python3
"""Build a deterministic review packet for an academic manuscript."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Iterable

SECTION_HINTS = {
    "abstract": ("abstract", "resumen"),
    "keywords": ("keywords", "palabras clave"),
    "introduction": ("introduction", "introduccion", "introducción"),
    "method": ("method", "methods", "methodology", "metodo", "método", "metodologia", "metodología"),
    "results": ("results", "findings", "hallazgos", "resultados"),
    "discussion": ("discussion", "discusion", "discusión"),
    "limitations": ("limitations", "limitaciones"),
    "conclusion": ("conclusion", "conclusions", "conclusiones"),
    "references": ("references", "bibliography", "referencias", "bibliografia", "bibliografía"),
}


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def find_headings(text: str) -> list[str]:
    return [match.group(2).strip() for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.MULTILINE)]


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


def detect_sections(headings: Iterable[str]) -> dict[str, bool]:
    normalized = [normalize(item) for item in headings]
    found: dict[str, bool] = {}
    for section, patterns in SECTION_HINTS.items():
        found[section] = any(any(pattern in heading for pattern in patterns) for heading in normalized)
    return found


def count_pattern(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE))


def local_assets_count(review_dir: pathlib.Path | None) -> dict[str, int]:
    if review_dir is None or not review_dir.exists():
        return {}
    pdf_dirs = [review_dir / "fulltext" / "pdf", review_dir / "pdfs"]
    pdf_count = sum(len(list(path.glob("*.pdf"))) for path in pdf_dirs if path.exists())
    appendices_dir = review_dir / "paper" / "appendices" / "data"
    figures_dir = review_dir / "figures" / "png"
    svg_dir = review_dir / "figures" / "svg"
    tables_dir = review_dir / "tables"
    return {
        "pdf_count": pdf_count,
        "appendix_csv_count": len(list(appendices_dir.glob("*.csv"))) if appendices_dir.exists() else 0,
        "figure_png_count": len(list(figures_dir.glob("*.png"))) if figures_dir.exists() else 0,
        "figure_svg_count": len(list(svg_dir.glob("*.svg"))) if svg_dir.exists() else 0,
        "table_file_count": len(list(tables_dir.rglob("*.csv"))) if tables_dir.exists() else 0,
    }


def build_packet(manuscript_path: pathlib.Path, review_dir: pathlib.Path | None, response_path: pathlib.Path | None) -> dict:
    text = read_text(manuscript_path)
    headings = find_headings(text)
    sections = detect_sections(headings)
    words = len(re.findall(r"\b\w+\b", text))
    image_links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    markdown_tables = count_pattern(text, r"^\|.+\|\s*$")
    figure_mentions = count_pattern(text, r"\b(?:figure|figura)\s+\d+\b")
    table_mentions = count_pattern(text, r"\b(?:table|tabla)\s+\d+\b")
    apa_citations = count_pattern(text, r"\([^)]*(?:19|20)\d{2}[a-z]?[^)]*\)")
    numeric_citations = count_pattern(text, r"\[\d+(?:\s*[-,]\s*\d+)*\]")
    placeholders = sorted(
        {
            match.group(0)
            for match in re.finditer(
                r"TODO|TBD|FIXME|\[CITATION NEEDED\]|_Pendiente_|lorem ipsum",
                text,
                flags=re.IGNORECASE,
            )
        }
    )

    packet = {
        "manuscript_path": str(manuscript_path),
        "review_dir": str(review_dir) if review_dir else "",
        "response_path": str(response_path) if response_path else "",
        "word_count": words,
        "heading_count": len(headings),
        "headings": headings[:40],
        "sections_detected": sections,
        "image_count": len(image_links),
        "table_line_count": markdown_tables,
        "figure_mentions": figure_mentions,
        "table_mentions": table_mentions,
        "apa_citation_count": apa_citations,
        "numeric_citation_count": numeric_citations,
        "placeholder_tokens": placeholders,
        "assets": local_assets_count(review_dir),
    }
    if response_path and response_path.exists():
        packet["response_word_count"] = len(re.findall(r"\b\w+\b", read_text(response_path)))
    return packet


def render_markdown(packet: dict) -> str:
    lines = [
        "# Review Packet",
        "",
        f"- Manuscript: `{packet['manuscript_path']}`",
    ]
    if packet.get("review_dir"):
        lines.append(f"- Review dir: `{packet['review_dir']}`")
    if packet.get("response_path"):
        lines.append(f"- Response letter: `{packet['response_path']}`")
    lines.extend(
        [
            "",
            "## Manuscript Snapshot",
            f"- Word count: {packet['word_count']}",
            f"- Headings: {packet['heading_count']}",
            f"- APA-style citations: {packet['apa_citation_count']}",
            f"- Numeric citations: {packet['numeric_citation_count']}",
            f"- Images embedded: {packet['image_count']}",
            f"- Figure mentions in text: {packet['figure_mentions']}",
            f"- Table mentions in text: {packet['table_mentions']}",
            "",
            "## Section Detection",
        ]
    )
    for key, value in packet["sections_detected"].items():
        lines.append(f"- {key}: {'yes' if value else 'no'}")
    lines.extend(["", "## Review Bundle Assets"])
    assets = packet.get("assets", {})
    if assets:
        for key, value in assets.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- No review workspace metadata detected.")
    lines.extend(["", "## Headings Preview"])
    for heading in packet["headings"]:
        lines.append(f"- {heading}")
    if packet.get("placeholder_tokens"):
        lines.extend(["", "## Placeholder Tokens", *[f"- {token}" for token in packet["placeholder_tokens"]]])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manuscript", type=pathlib.Path)
    parser.add_argument("--review-dir", type=pathlib.Path)
    parser.add_argument("--response-path", type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path)
    args = parser.parse_args()

    manuscript_path = args.manuscript.resolve()
    output_dir = args.output_dir or manuscript_path.parent / "review-packet"
    output_dir.mkdir(parents=True, exist_ok=True)

    packet = build_packet(manuscript_path, args.review_dir.resolve() if args.review_dir else None, args.response_path.resolve() if args.response_path else None)
    (output_dir / "review-packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "review-packet.md").write_text(render_markdown(packet), encoding="utf-8")
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
