#!/usr/bin/env python3
"""Export the publication-ready Markdown manuscript to LaTeX and PDF."""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import tempfile

FIGURE_CAPTION_RE = re.compile(r"^Figura(?:\s+\d+[A-Z]?|\s+adicional|\s+complementaria)\.\s+.+$", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(
    r"^Tabla(?:\s+\d+[A-Z]?|\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][^.]{2,120})\.\s+.+$"
)
PIPE_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
IMAGE_LINE_RE = re.compile(r"^!\[([^\]]*)\]\((.+)\)$")
LATEX_IMAGE_ALT_RE = re.compile(r"alt=\{(?P<alt>.+?)\}")
LATEX_INCLUDEGRAPHICS_RE = re.compile(r"^(?P<indent>\s*)\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^}]+)\}\s*$")
LATEX_PANDOCBOUNDED_IMAGE_RE = re.compile(
    r"^(?P<indent>\s*)\\pandocbounded\{\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^}]+)\}\}\s*$"
)
MARKDOWN_DOI_RE = re.compile(r"(?<![A-Za-z0-9])10\.\d{4,9}/[^\s|)]+")
CYRILLIC_TEXT_RE = re.compile(r"[А-Яа-яІіЇїЄєҐґ][А-Яа-яІіЇїЄєҐґ'’ʼ-]*")
CJK_OR_GREEK_TEXT_RE = re.compile(r"[\u0370-\u03FF\u4E00-\u9FFF]+")
LATEX_FORMAT_CONTROL_RE = re.compile(r"[\u202A-\u202E]")
GREEK_TEXT_REPLACEMENTS = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "π": "pi",
}
MATH_TEXT_REPLACEMENTS = {
    "Δ": "Delta",
    "∅": "conjunto vacio",
    "▷": "->",
    "≥": ">=",
    "∈": "en",
    "∼": "aprox.",
    "≈": "aprox.",
    "𝑝": "p",
    "𝑑": "d",
    "𝑞": "q",
    "𝜏": "tau",
}


def is_pipe_table_line(line: str) -> bool:
    """Return True when a line is a Markdown pipe-table row.

    Hermes manuscripts are assembled from many generated sections. A single
    missing blank line before a pipe table makes Pandoc treat the table as raw
    paragraph text, so the exporter defensively recognizes and normalizes every
    table block before LaTeX conversion.
    """
    stripped = line.strip()
    return bool(PIPE_TABLE_LINE_RE.match(stripped)) and stripped.count("|") >= 2


def scaled_includegraphics(path: str, indent: str = "") -> str:
    """Return a consistently bounded image command for manuscript figures."""
    return (
        f"{indent}"
        r"\includegraphics[width=0.98\linewidth,height=0.72\textheight,keepaspectratio]"
        f"{{{path}}}"
    )


def sync_manuscript_figure_assets(review_dir: pathlib.Path, manuscript_dir: pathlib.Path) -> None:
    """Copy regenerated figure assets into the LaTeX working directory.

    Pandoc emits relative paths such as ``figures/png/name.png`` and LaTeX
    resolves them from ``paper/manuscript``. Without this sync step, a rebuilt
    manuscript can silently compile against stale copied figures.
    """
    source_figures = review_dir / "figures"
    target_figures = manuscript_dir / "figures"
    for subdir in ("png", "svg"):
        source_dir = source_figures / subdir
        if not source_dir.exists():
            continue
        target_dir = target_figures / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        source_names = {path.name for path in source_dir.glob(f"*.{subdir}") if path.is_file()}
        for stale_path in target_dir.glob(f"*.{subdir}"):
            if stale_path.name not in source_names:
                stale_path.unlink()
        for metadata_path in target_dir.glob(".*"):
            if metadata_path.is_file():
                metadata_path.unlink()
        for source_path in source_dir.glob(f"*.{subdir}"):
            shutil.copy2(source_path, target_dir / source_path.name)


def normalize_markdown_for_pandoc(markdown: str) -> str:
    """Adapt Hermes manuscript conventions to Pandoc-native figures/tables."""
    markdown = (
        markdown.replace("ρ", "rho")
        .replace("≤", "<=")
        .replace("\u202a", "")
        .replace("\u202b", "")
        .replace("\u202c", "")
        .replace("\u202d", "")
        .replace("\u202e", "")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("✉", "")
        .replace("●", "-")
        .replace("†", "")
        .replace("∗", "*")
        .replace("©", "(c)")
    )
    for char, replacement in MATH_TEXT_REPLACEMENTS.items():
        markdown = markdown.replace(char, replacement)
    lines = markdown.splitlines()
    normalized: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if FIGURE_CAPTION_RE.match(stripped):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                image_match = IMAGE_LINE_RE.match(lines[j].strip())
                if image_match:
                    image_path = image_match.group(2)
                    normalized.append(f"![{stripped}]({image_path})")
                    normalized.append("")
                    i = j + 1
                    continue

        if TABLE_CAPTION_RE.match(stripped):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and is_pipe_table_line(lines[j]):
                normalized.append(f"Table: {stripped}")
                normalized.append("")
                i = j
                continue

        if is_pipe_table_line(line):
            if normalized and normalized[-1].strip() and not is_pipe_table_line(normalized[-1]):
                normalized.append("")
            while i < len(lines) and is_pipe_table_line(lines[i]):
                table_line = MARKDOWN_DOI_RE.sub(lambda match: rf"\nolinkurl{{{match.group(0)}}}", lines[i])
                normalized.append(table_line)
                i += 1
            if i < len(lines) and lines[i].strip():
                normalized.append("")
            continue

        normalized.append(line)
        i += 1

    return "\n".join(normalized) + ("\n" if markdown.endswith("\n") else "")


def wrap_standalone_latex_images(tex: str) -> str:
    """Convert bare Pandoc image lines into proper LaTeX figure environments."""
    lines = tex.splitlines()
    wrapped: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(r"\pandocbounded{\includegraphics"):
            prev_nonempty = next((entry.strip() for entry in reversed(wrapped) if entry.strip()), "")
            next_nonempty = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), "")
            bounded_match = LATEX_PANDOCBOUNDED_IMAGE_RE.match(line)
            image_line = scaled_includegraphics(
                bounded_match.group("path"),
                bounded_match.group("indent"),
            ) if bounded_match else line
            if prev_nonempty != r"\centering" and not next_nonempty.startswith(r"\caption{"):
                alt_match = LATEX_IMAGE_ALT_RE.search(stripped)
                wrapped.append(r"\begin{figure}[H]")
                wrapped.append(r"\centering")
                wrapped.append(image_line)
                if alt_match:
                    wrapped.append(rf"\caption{{{alt_match.group('alt')}}}")
                wrapped.append(r"\end{figure}")
                i += 1
                continue
            wrapped.append(image_line)
            i += 1
            continue
        image_match = LATEX_INCLUDEGRAPHICS_RE.match(line)
        if image_match:
            wrapped.append(scaled_includegraphics(image_match.group("path"), image_match.group("indent")))
            i += 1
            continue
        wrapped.append(line)
        i += 1
    return "\n".join(wrapped) + ("\n" if tex.endswith("\n") else "")


def clean_caption_labels(tex: str) -> str:
    """Let LaTeX number figures, but preserve the manuscript's manual table labels."""
    cleaned = re.sub(r"\\caption\{Figura(?:\s+\d+[A-Z]?|\s+adicional|\s+complementaria)\.\s*", r"\\caption{", tex)
    cleaned = re.sub(r"\\caption\{(Tabla\s+\d+[A-Z]?\.\s*)", r"\\caption*{\1", cleaned)
    cleaned = re.sub(r"\\caption\{(Tabla\s+(?!\d)[^}]+)\}", r"\\caption*{\1}", cleaned)
    # Scientific figures must stay adjacent to their interpretation. Floating
    # several large charts can place explanatory paragraphs before the visual.
    cleaned = re.sub(r"\\begin\{figure\}(?:\[[^\]]+\])?", r"\\begin{figure}[H]", cleaned)
    # Keep Pandoc's default LaTeX typography stable across reviews; journal-specific
    # fonts should be applied by templates, not silently by the exporter.
    if r"\renewcommand{\figurename}{Figura}" not in cleaned:
        cleaned = cleaned.replace(
            r"\usepackage{graphicx}",
            "\n".join(
                [
                    r"\usepackage{graphicx}",
                    r"\usepackage{caption}",
                    r"\usepackage{float}",
                    r"\renewcommand{\figurename}{Figura}",
                    r"\renewcommand{\tablename}{Tabla}",
                    r"\setlength{\LTcapwidth}{\textwidth}",
                    r"\setlength{\emergencystretch}{3em}",
                    r"\AtBeginDocument{\ifdefined\Urlmuskip\Urlmuskip=0mu plus 2mu\relax\fi}",
                    r"\sloppy",
                ]
            ),
            1,
        )
    return cleaned


def add_unicode_font_fallbacks(tex: str) -> str:
    """Render non-Latin snippets without changing the manuscript's main font."""
    tex = LATEX_FORMAT_CONTROL_RE.sub("", tex)
    tex = tex.replace("≤", r"$\leq$")
    for char, replacement in MATH_TEXT_REPLACEMENTS.items():
        tex = tex.replace(char, replacement)
    for char, replacement in GREEK_TEXT_REPLACEMENTS.items():
        tex = tex.replace(rf"\({char}\)", replacement)
        tex = tex.replace(char, replacement)

    needs_cyrillic = bool(CYRILLIC_TEXT_RE.search(tex))
    needs_unicode_fallback = bool(CJK_OR_GREEK_TEXT_RE.search(tex))
    if not needs_cyrillic and not needs_unicode_fallback:
        return tex

    if (needs_cyrillic or needs_unicode_fallback) and r"\newfontfamily\hermesunicodefont" not in tex:
        fallback_block = "\n".join(
            [
                r"\ifPDFTeX\else",
                r"  \IfFontExistsTF{Arial Unicode MS}{",
                r"    \newfontfamily\hermesunicodefont{Arial Unicode MS}",
                r"  }{",
                r"    \IfFontExistsTF{STIX Two Text}{",
                r"      \newfontfamily\hermesunicodefont{STIX Two Text}",
                r"    }{",
                r"      \IfFontExistsTF{Times New Roman}{",
                r"        \newfontfamily\hermesunicodefont{Times New Roman}",
                r"      }{",
                r"        \newfontfamily\hermesunicodefont{DejaVu Sans}",
                r"      }",
                r"    }",
                r"  }",
                r"\fi",
            ]
        )
        tex = tex.replace(r"\usepackage{graphicx}", f"{fallback_block}\n\\usepackage{{graphicx}}", 1)

    if needs_cyrillic:
        tex = CYRILLIC_TEXT_RE.sub(lambda match: rf"{{\hermesunicodefont {match.group(0)}}}", tex)
    if needs_unicode_fallback:
        tex = CJK_OR_GREEK_TEXT_RE.sub(lambda match: rf"{{\hermesunicodefont {match.group(0)}}}", tex)
    return tex


def tighten_wide_longtables(tex: str) -> str:
    """Apply narrower local spacing to very wide longtables."""
    lines = tex.splitlines()
    tightened: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(r"\begin{longtable}"):
            j = i
            while j < len(lines) and lines[j].strip() != r"\end{longtable}":
                j += 1
            if j < len(lines):
                block = lines[i : j + 1]
                wide_columns = sum(1 for entry in block if r">{\raggedright\arraybackslash}p{" in entry)
                if wide_columns >= 6:
                    tightened.append(r"\begingroup")
                    tightened.append(r"\footnotesize")
                    tightened.append(r"\setlength{\tabcolsep}{4pt}")
                    tightened.extend(block)
                    tightened.append(r"\endgroup")
                    i = j + 1
                    continue
        tightened.append(line)
        i += 1
    return "\n".join(tightened) + ("\n" if tex.endswith("\n") else "")


def rebalance_full_title_tables(tex: str) -> str:
    """Give full-title columns enough room after pandoc creates even-width tables."""
    lines = tex.splitlines()
    rebalanced: list[str] = []
    i = 0

    def weighted_spec(column_count: int, weights: list[float], total_tabcolsep: int) -> list[str]:
        spec_lines: list[str] = []
        for index, weight in enumerate(weights):
            prefix = r"  >{\raggedright\arraybackslash}p"
            suffix = "@{}}" if index == column_count - 1 else ""
            spec_lines.append(
                f"{prefix}{{(\\columnwidth - {total_tabcolsep}\\tabcolsep) * \\real{{{weight:.4f}}}}}{suffix}"
            )
        return spec_lines

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(r"\begin{longtable}"):
            j = i
            while j < len(lines) and lines[j].strip() != r"\end{longtable}":
                j += 1
            if j < len(lines):
                block = lines[i : j + 1]
                block_text = "\n".join(block)
                spec_count = sum(1 for entry in block if r">{\raggedright\arraybackslash}p{" in entry)
                weights: list[float] | None = None
                total_tabcolsep = max(0, 2 * (spec_count - 1))
                if "Título completo" in block_text and "Score" in block_text and spec_count in {7, 8}:
                    if spec_count == 7:
                        weights = [0.0450, 0.1450, 0.4050, 0.0750, 0.1200, 0.0700, 0.1400]
                    else:
                        weights = [0.0450, 0.1250, 0.2700, 0.0650, 0.0700, 0.0750, 0.0600, 0.2900]
                elif (
                    "Fronteras de dominancia condicionada entre familias de harnesses" in block_text
                    and spec_count == 7
                ):
                    # Threat and control-family labels carry substantially more
                    # information than the count and evidence-ratio columns.
                    weights = [0.1800, 0.2300, 0.0500, 0.0800, 0.0800, 0.2000, 0.1800]
                if weights:
                    replacement = weighted_spec(spec_count, weights, total_tabcolsep)
                    rebuilt: list[str] = []
                    inserted = False
                    skipping_specs = False
                    for entry in block:
                        if r">{\raggedright\arraybackslash}p{" in entry:
                            if not inserted:
                                rebuilt.extend(replacement)
                                inserted = True
                            skipping_specs = not entry.strip().endswith("@{}}")
                            continue
                        if skipping_specs:
                            if entry.strip().endswith("@{}}"):
                                skipping_specs = False
                            continue
                        rebuilt.append(entry)
                    rebalanced.extend(rebuilt)
                    i = j + 1
                    continue
        rebalanced.append(line)
        i += 1
    return "\n".join(rebalanced) + ("\n" if tex.endswith("\n") else "")


def ensure_file(path: pathlib.Path) -> pathlib.Path:
    if not path.exists() or not path.is_file():
        raise SystemExit(f"Required file not found: {path}")
    return path


def run_command(cmd: list[str], workdir: pathlib.Path) -> None:
    subprocess.run(cmd, cwd=workdir, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument("--skip-pdf", action="store_true", help="Export only LaTeX, without compiling PDF")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    manuscript_dir = review_dir / "paper" / "manuscript"
    markdown_path = ensure_file(manuscript_dir / "publication-ready.md")
    tex_path = manuscript_dir / "publication-ready.tex"
    sync_manuscript_figure_assets(review_dir, manuscript_dir)
    normalized_markdown = normalize_markdown_for_pandoc(markdown_path.read_text(encoding="utf-8"))

    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise SystemExit("pandoc is required to export the manuscript to LaTeX.")

    with tempfile.NamedTemporaryFile("w", suffix=".md", dir=manuscript_dir, delete=False, encoding="utf-8") as handle:
        handle.write(normalized_markdown)
        normalized_path = pathlib.Path(handle.name)

    try:
        run_command(
            [
                pandoc,
                "--from=markdown+raw_tex+pipe_tables+table_captions+implicit_figures",
                "--to=latex",
                "--standalone",
                "--wrap=preserve",
                "-V",
                "documentclass=article",
                "-V",
                "geometry:margin=1in",
                "-o",
                str(tex_path),
                str(normalized_path),
            ],
            manuscript_dir,
        )
    finally:
        normalized_path.unlink(missing_ok=True)

    tex_path.write_text(
        add_unicode_font_fallbacks(
            clean_caption_labels(
                tighten_wide_longtables(
                    rebalance_full_title_tables(
                        wrap_standalone_latex_images(tex_path.read_text(encoding="utf-8"))
                    )
                )
            )
        ),
        encoding="utf-8",
    )

    if args.skip_pdf:
        return 0

    latexmk = shutil.which("latexmk")
    xelatex = shutil.which("xelatex")
    lualatex = shutil.which("lualatex")
    if latexmk:
        latexmk_mode = "-xelatex" if xelatex else "-lualatex" if lualatex else "-pdf"
        run_command(
            [
                latexmk,
                latexmk_mode,
                "-interaction=nonstopmode",
                tex_path.name,
            ],
            manuscript_dir,
        )
        return 0

    pdflatex = shutil.which("pdflatex")
    engine = xelatex or lualatex or pdflatex
    if not engine:
        return 0

    run_command([engine, "-interaction=nonstopmode", tex_path.name], manuscript_dir)
    run_command([engine, "-interaction=nonstopmode", tex_path.name], manuscript_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
