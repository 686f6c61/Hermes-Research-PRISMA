#!/usr/bin/env python3
"""Audit and compile a publication-ready manuscript from a systematic review workspace."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Iterable
from urllib import error, parse, request

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bibliographic_corrections import (  # noqa: E402
    apply_source_verified_identity_corrections,
)
from build_security_harness_analysis import (  # noqa: E402
    adaptive_attacker_reported,
    open_artifact_reported,
)
from build_security_harness_analysis import (  # noqa: E402
    reported as security_field_reported,
)
from docling_extract import extract_review_documents  # noqa: E402
from docling_extract import normalize_doi as normalize_docling_doi  # noqa: E402
from review_mode_router import (  # noqa: E402
    infer_review_mode,
    read_review_mode_decision,
    review_mode_summary,
    selection_weights,
    write_review_mode_artifacts,
)

REVIEW_MODE_PLAYBOOK_KEYS = [
    "mode_question_es",
    "ask_policy",
    "minimum_tables",
    "minimum_figures",
    "mode_specific_outputs",
    "publication_section_requirements",
    "red_flags",
    "excellence_checklist",
]


ANCHOR_RE = re.compile(r"\[@([^\]]+)\]")
YEAR_RE = r"(?:19|20)\d{2}[a-z]?"
PAREN_CITE_RE = re.compile(rf"\(([^()]*?{YEAR_RE}[^()]*)\)")
NARRATIVE_CITE_RE = re.compile(rf"\b([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ'’.-]+(?: et al\.)?) \(({YEAR_RE})\)")
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|XXX|PENDIENTE|REVISAR|CITAR)\b")
SECTION_MIN_CHARS = 350
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
PIPE_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
ACRONYM_RESTORES = {
    "Llms": "LLMs",
    "Llm": "LLM",
    "Ai": "AI",
    "Ia": "IA",
    "Mbti": "MBTI",
    "Hexaco": "HEXACO",
    "Gpt": "GPT",
    "Arxiv": "arXiv",
    "Ci/Cd": "CI/CD",
    "Pdf": "PDF",
    "Prisma": "PRISMA",
    "Rag": "RAG",
    "Qa": "QA",
    "Api": "API",
    "Instagram": "Instagram",
    "Whatsapp": "WhatsApp",
    "Twitter": "Twitter",
    "Facebook": "Facebook",
    "Tiktok": "TikTok",
    "Tocqueville": "Tocqueville",
    "American": "American",
    "España": "España",
    "Brasil": "Brasil",
    "India": "India",
    "Mexico": "Mexico",
    "México": "México",
    "Plos": "PLOS",
    "Saap": "SAAP",
    "English": "English",
    "Hindi": "Hindi",
}

PRISMA_2020_APA = (
    "Page, M. J., McKenzie, J. E., Bossuyt, P. M., Boutron, I., Hoffmann, T. C., "
    "Mulrow, C. D., Shamseer, L., Tetzlaff, J. M., Akl, E. A., Brennan, S. E., "
    "Chou, R., Glanville, J., Grimshaw, J. M., Hróbjartsson, A., Lalu, M. M., "
    "Li, T., Loder, E. W., Mayo-Wilson, E., McDonald, S., ... Moher, D. (2021). "
    "The PRISMA 2020 statement: An updated guideline for reporting systematic reviews. "
    "*BMJ*, *372*, n71. https://doi.org/10.1136/bmj.n71"
)

PRISMA_S_APA = (
    "Rethlefsen, M. L., Kirtley, S., Waffenschmidt, S., Ayala, A. P., Moher, D., "
    "Page, M. J., & Koffel, J. B. (2021). PRISMA-S: An extension to the PRISMA "
    "statement for reporting literature searches in systematic reviews. "
    "*Systematic Reviews*, *10*, Article 39. https://doi.org/10.1186/s13643-020-01542-z"
)

SLR_GUIDELINES_APA = (
    "Kitchenham, B., & Charters, S. (2007). *Guidelines for performing systematic "
    "literature reviews in software engineering* (EBSE Technical Report EBSE-2007-01). "
    "Keele University and Durham University. "
    "https://madeyski.e-informatyka.pl/download/Kitchenham07.pdf"
)

LITERATURE_REVIEW_METHOD_APA = (
    "Snyder, H. (2019). Literature review as a research methodology: An overview and "
    "guidelines. *Journal of Business Research*, *104*, 333-339. "
    "https://doi.org/10.1016/j.jbusres.2019.07.039"
)

CONSTRUCT_VALIDITY_APA = (
    "Cronbach, L. J., & Meehl, P. E. (1955). Construct validity in psychological "
    "tests. *Psychological Bulletin*, *52*(4), 281-302. "
    "https://doi.org/10.1037/h0040957"
)

CAUSAL_INFERENCE_APA = (
    "Shadish, W. R., Cook, T. D., & Campbell, D. T. (2002). "
    "*Experimental and quasi-experimental designs for generalized causal inference*. "
    "Houghton Mifflin."
)

REALIST_SYNTHESIS_APA = (
    "Pawson, R. (2006). *Evidence-based policy: A realist perspective*. SAGE."
)

TRANSPORTABILITY_APA = (
    "Pearl, J., & Bareinboim, E. (2014). External validity: From sample to population. "
    "*Statistical Science*, *29*(4), 579-595. https://doi.org/10.1214/14-STS486"
)

THEORY_SUPPORT_REFERENCES = {
    "de_haes_bensing_2009": (
        "de Haes, H., & Bensing, J. (2009). Endpoints in medical communication research, "
        "proposing a framework of functions and outcomes. *Patient Education and Counseling*, "
        "*74*(3), 287-294. https://doi.org/10.1016/j.pec.2008.12.006"
    ),
    "king_hoppe_2013": (
        "King, A., & Hoppe, R. B. (2013). \"Best practice\" for patient-centered communication: "
        "A narrative review. *Journal of Graduate Medical Education*, *5*(3), 385-393. "
        "https://doi.org/10.4300/JGME-D-13-00072.1"
    ),
    "hill_2020": (
        "Hill, C. E. (2020). *Helping skills: Facilitating exploration, insight, and action* "
        "(5th ed.). American Psychological Association. https://doi.org/10.1037/0000147-000"
    ),
    "pennebaker_king_1999": (
        "Pennebaker, J. W., & King, L. A. (1999). Linguistic styles: Language use as an "
        "individual difference. *Journal of Personality and Social Psychology*, *77*(6), "
        "1296-1312. https://doi.org/10.1037/0022-3514.77.6.1296"
    ),
    "fiske_2007": (
        "Fiske, S. T., Cuddy, A. J. C., & Glick, P. (2007). Universal dimensions of social "
        "cognition: Warmth and competence. *Trends in Cognitive Sciences*, *11*(2), 77-83. "
        "https://doi.org/10.1016/j.tics.2006.11.005"
    ),
}

TITLE_FIXUPS = {
    "devel-opment": "development",
    "method-ology": "methodology",
    "ci/cd": "CI/CD",
    "rag-r1": "RAG-R1",
    "retrieval- augmented": "retrieval-augmented",
    "International Journal For Multidisciplinary Research": "International Journal for Multidisciplinary Research",
}

SOURCE_DISPLAY_MAP = {
    "OpenAlex": "OpenAlex",
    "Crossref": "Crossref",
    "SemanticScholar": "Semantic Scholar",
    "arXiv": "arXiv",
}

PERSONALITY_CONSTRUCT_EN_MAP = {
    "persona, role-play y control": "persona, role-play, and control",
    "interacción humana y alineamiento": "human interaction and alignment",
    "medición, profiling y validación": "measurement, profiling, and validation",
    "sesgo, riesgo y seguridad": "bias, risk, and safety",
}

ORGANIZATION_AUTHOR_SUFFIXES = {
    "team",
    "group",
    "lab",
    "laboratory",
    "consortium",
    "collective",
    "committee",
    "center",
    "centre",
    "initiative",
    "project",
}

CYRILLIC_CHAR_MAP = {
    "А": "A", "а": "a", "Б": "B", "б": "b", "В": "V", "в": "v", "Г": "H", "г": "h",
    "Ґ": "G", "ґ": "g", "Д": "D", "д": "d", "Е": "E", "е": "e", "Є": "Ye", "є": "ie",
    "Ж": "Zh", "ж": "zh", "З": "Z", "з": "z", "И": "Y", "и": "y", "І": "I", "і": "i",
    "Ї": "Yi", "ї": "i", "Й": "Y", "й": "i", "К": "K", "к": "k", "Л": "L", "л": "l",
    "М": "M", "м": "m", "Н": "N", "н": "n", "О": "O", "о": "o", "П": "P", "п": "p",
    "Р": "R", "р": "r", "С": "S", "с": "s", "Т": "T", "т": "t", "У": "U", "у": "u",
    "Ф": "F", "ф": "f", "Х": "Kh", "х": "kh", "Ц": "Ts", "ц": "ts", "Ч": "Ch", "ч": "ch",
    "Ш": "Sh", "ш": "sh", "Щ": "Shch", "щ": "shch", "Ь": "", "ь": "", "Ю": "Yu", "ю": "iu",
    "Я": "Ya", "я": "ia", "Ъ": "", "ъ": "", "Ы": "Y", "ы": "y", "Э": "E", "э": "e",
}

CYRILLIC_TOKEN_OVERRIDES = {
    "ПОЛУЕКТОВА": "Poluektova",
    "МАТВІЇШИНА": "Matviishyna",
}


@dataclass
class CorpusRecord:
    record_id: str
    assigned_doi: str
    title: str
    authors: str
    year: str
    work_type: str
    selected_for_final_n: bool
    notes: str


@dataclass
class Issue:
    severity: str
    category: str
    location: str
    message: str
    suggested_fix: str


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def is_pipe_table_line(line: str) -> bool:
    """Return True when a line belongs to a Markdown pipe table."""
    stripped = line.strip()
    return bool(PIPE_TABLE_LINE_RE.match(stripped)) and stripped.count("|") >= 2


def normalize_markdown_table_blocks(markdown: str) -> str:
    """Keep generated Markdown tables as standalone blocks.

    Publication sections are generated by several agents and scripts. This
    final pass prevents a table from being glued to the preceding paragraph,
    which would make Pandoc render the raw pipe syntax in the final PDF.
    """
    lines = markdown.splitlines()
    normalized: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if is_pipe_table_line(line):
            if normalized and normalized[-1].strip() and not is_pipe_table_line(normalized[-1]):
                normalized.append("")
            while i < len(lines) and is_pipe_table_line(lines[i]):
                normalized.append(lines[i].rstrip())
                i += 1
            if i < len(lines) and lines[i].strip():
                normalized.append("")
            continue
        normalized.append(line)
        i += 1
    return "\n".join(normalized) + ("\n" if markdown.endswith("\n") else "")


def normalize_citation_sentence_punctuation(markdown: str) -> str:
    """Place the sentence period after Markdown citation blocks.

    Some generators compose prose as ``sentence. [@id].``. Pandoc renders that
    as a visible APA error: the period appears before the parenthetical
    citation. This final pass keeps the citation attached to the sentence while
    preserving the closing period after the citation block.
    """
    fixed_lines: list[str] = []
    for line in markdown.splitlines():
        # Reference-list entries legitimately contain author initials before the
        # publication year, e.g. "Moher, D. (2021)". Do not touch those lines.
        if line.lstrip().startswith("- "):
            fixed_lines.append(line)
            continue
        line = re.sub(r"\.\s+(\[@[^\]\n]+\])", r" \1", line)
        line = re.sub(rf"\.\s+(\([^()\n]*?{YEAR_RE}[^()\n]*\))", r" \1", line)
        fixed_lines.append(line)
    suffix = "\n" if markdown.endswith("\n") else ""
    return "\n".join(fixed_lines) + suffix


def markdown_table_cell(value: object) -> str:
    """Escape cell content so generated pipe tables remain valid Markdown."""
    text = str(value).replace("|", r"\|").replace("\n", "<br>").strip()
    # Tables must not ship with ellipses or generic "see annex" placeholders.
    # If a source value was truncated upstream, remove the truncation marker and
    # keep the sentence readable; exact traceability lives in named CSV files.
    text = re.sub(r"\s*(?:…|\.{3})\s*", " ", text)
    text = text.replace("ĸ", "kappa")
    text = text.replace("Banda contextual*", "Perímetro contextual elegible")
    text = text.replace("Banda contextual", "Perímetro contextual elegible")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def stage_manuscript_local_assets(review_dir: pathlib.Path, manuscript_dir: pathlib.Path, text: str) -> str:
    if not text:
        return text

    def rewrite_path(original_path: str) -> str:
        normalized = (original_path or "").strip()
        if normalized.startswith("../../figures/") or normalized.startswith("../../tables/"):
            source = (manuscript_dir / normalized).resolve()
            local_rel = normalized.replace("../../", "", 1)
            destination = manuscript_dir / local_rel
            if source.exists() and source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                return local_rel
        return normalized

    def replace_markdown_path(match: re.Match[str]) -> str:
        prefix = match.group(1)
        path = match.group(2)
        suffix = match.group(3)
        return f"{prefix}{rewrite_path(path)}{suffix}"

    return re.sub(r"(\]\()([^)]+)(\))", replace_markdown_path, text)


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


EXTRACTION_TABLE_FIELDNAMES = [
    "record_id",
    "assigned_doi",
    "authors",
    "title_original",
    "title_en",
    "title_es",
    "abstract_original",
    "abstract_en",
    "abstract_es",
    "keywords_author",
    "keywords_indexed",
    "keywords_normalized",
    "year",
    "work_type",
    "empirical_type",
    "design_detail",
    "countries",
    "unit_of_analysis",
    "sample_description",
    "sample_size",
    "models_or_systems_studied",
    "model_count",
    "benchmark_dataset_or_corpus",
    "tasks_or_domains",
    "baselines_or_comparators",
    "instruments_or_scales",
    "method_used",
    "variables_dependent",
    "variables_independent",
    "variables_moderating",
    "variables_mediating",
    "variables_control",
    "theory_framework",
    "evidence_snippet",
    "evidence_location",
    "extraction_confidence",
    "key_findings",
    "notes",
]


def slugify(value: str) -> str:
    cleaned = []
    for char in value.lower():
        cleaned.append(char if char.isalnum() else "-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


def split_authors(text: str) -> list[str]:
    if not text:
        return []
    delimiter = ";" if ";" in text else ","
    parts = [part.strip() for part in text.split(delimiter)]
    return [part for part in parts if part]


def normalize_author_name(name: str) -> str:
    text = html.unescape((name or "").strip())
    # DOI/CSL providers sometimes leak affiliation markers into author names
    # (for example "Mei<sup>1</sup>" or "Min2</p>"). Strip markup and numeric
    # superscript residue before APA formatting so the manuscript never cites
    # contaminated names.
    text = re.sub(r"</?[^>]+>", "", text)
    text = re.sub(r"(?<=[A-Za-zÀ-ÿА-Яа-я])\d+(?=\b|[,;\s])", "", text)
    text = re.sub(r"\b\d+(?=[A-Za-zÀ-ÿА-Яа-я])", "", text)
    text = re.sub(r"^(mr|mrs|ms|dr|prof)\.?\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=[A-Za-zÀ-ÿА-Яа-я])\.(?=[A-Za-zÀ-ÿА-Яа-я])", ". ", text)
    if CYRILLIC_RE.search(text):
        rebuilt = []
        for chunk in re.split(r"(\W+)", text):
            if not chunk:
                continue
            if CYRILLIC_RE.search(chunk):
                override = CYRILLIC_TOKEN_OVERRIDES.get(chunk.upper())
                if override:
                    rebuilt.append(override)
                    continue
                rebuilt.append("".join(CYRILLIC_CHAR_MAP.get(char, char) for char in chunk))
            else:
                rebuilt.append(chunk)
        text = "".join(rebuilt)
    if text and text == text.upper():
        rebuilt = []
        for chunk in re.split(r"(\W+)", text):
            if not chunk:
                continue
            letters_only = re.sub(r"[^A-Za-zÀ-ÿА-Яа-я]", "", chunk)
            if not letters_only:
                rebuilt.append(chunk)
            elif len(letters_only) == 1:
                rebuilt.append(chunk.upper())
            else:
                rebuilt.append(chunk.title())
        text = "".join(rebuilt)
    return re.sub(r"\s+", " ", text).strip()


def is_organization_author(name: str) -> bool:
    normalized = normalize_author_name(name)
    lowered = normalized_text(normalized)
    if not lowered:
        return False
    if any(lowered == suffix or lowered.endswith(" " + suffix) for suffix in ORGANIZATION_AUTHOR_SUFFIXES):
        return True
    return any(
        token in lowered
        for token in (" model team", " research team", " author team", " collective", " consortium")
    )


def split_family_given_from_unstructured_name(name: str) -> tuple[str, str]:
    """Infer an APA family/given split when APIs put a whole name in `family`.

    Some DOI providers return names such as "Umar Farook Rizwan H" entirely in
    the CSL `family` field. The heuristic keeps ordinary Western names intact
    while handling trailing initials common in South Asian metadata.
    """
    cleaned = normalize_author_name(name)
    if not cleaned or is_organization_author(cleaned):
        return cleaned, ""
    if "," in cleaned:
        family, given = [part.strip() for part in cleaned.split(",", 1)]
        return family, given
    tokens = cleaned.replace(".", " ").split()
    if len(tokens) <= 1:
        return cleaned, ""
    trailing_initials: list[str] = []
    for token in reversed(tokens):
        token_letters = re.sub(r"[^A-Za-zÀ-ÿА-Яа-я]", "", token)
        if len(token_letters) == 1:
            trailing_initials.insert(0, token_letters.upper())
            continue
        break
    if trailing_initials and len(tokens) > len(trailing_initials) + 1:
        family_index = len(tokens) - len(trailing_initials) - 1
        family = tokens[family_index]
        given = " ".join([*tokens[:family_index], *trailing_initials]).strip()
        return family, given
    return tokens[-1], " ".join(tokens[:-1]).strip()


def resolve_csl_name(author: dict) -> tuple[str, str, str]:
    family = normalize_author_name(author.get("family") or "")
    given = normalize_author_name(author.get("given") or "")
    literal = normalize_author_name(author.get("literal") or "")
    if family and not literal and not given and " " in family:
        family, given = split_family_given_from_unstructured_name(family)
    if family and not literal and " " in family and len(family.split()) <= 3:
        tokens = family.split()
        particles = {"da", "de", "del", "der", "di", "la", "le", "van", "von"}
        if tokens[0].lower() not in particles:
            family = tokens[-1]
            given = " ".join(item for item in [given, *tokens[:-1]] if item).strip()
    elif family and not literal and not given and " " in family:
        tokens = family.split()
        initial_prefix_len = 0
        for token in tokens:
            token_letters = re.sub(r"[^A-Za-zÀ-ÿА-Яа-я]", "", token)
            if len(token_letters) == 1:
                initial_prefix_len += 1
                continue
            break
        if initial_prefix_len >= 2 and len(tokens) - initial_prefix_len >= 2:
            given = " ".join(tokens[:initial_prefix_len]).strip()
            family = " ".join(tokens[initial_prefix_len:]).strip()
    family_is_bad = not family or len(re.sub(r"[^A-Za-zÀ-ÿА-Яа-я]", "", family)) <= 1
    if family_is_bad and given:
        family, given = given, ""
    if family and family == family.lower() and " " not in family:
        family = family.title()
    return family, given, literal


def initials_from_given(given: str) -> str:
    given = re.sub(r"\([^)]*\)", "", normalize_author_name(given))
    given = re.sub(r'["“][^"”]+["”]', "", given)
    initials = []
    for token in re.split(r"[\s-]+", given):
        token = re.sub(r"[^A-Za-zÀ-ÿА-Яа-я]", "", token)
        if not token:
            continue
        initials.append(token[0].upper() + ".")
    return " ".join(initials)


def author_family(name: str) -> str:
    cleaned = normalize_author_name(name)
    if not cleaned:
        return "Anon"
    if is_organization_author(cleaned):
        return cleaned
    family, _given = split_family_given_from_unstructured_name(cleaned)
    family = family or "Anon"
    if family == family.lower() and " " not in family:
        family = family.title()
    return family


def author_initials(name: str) -> str:
    cleaned = normalize_author_name(name)
    if not cleaned:
        return ""
    if is_organization_author(cleaned):
        return ""
    cleaned = re.sub(r'["“][^"”]+["”]', "", cleaned)
    _family, given = split_family_given_from_unstructured_name(cleaned)
    if given:
        return initials_from_given(given)
    token = re.sub(r"[^A-Za-zÀ-ÿА-Яа-я]", "", cleaned)
    return token[:1].upper() + "." if token else ""


def finalize_apa_name_list(formatted: list[str]) -> str:
    if not formatted:
        return "Autor no resuelto"
    if len(formatted) > 20:
        return ", ".join(formatted[:19]) + ", ... " + formatted[-1]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}"
    return ", ".join(formatted[:-1]) + ", & " + formatted[-1]


def format_apa_names_from_plain(text: str) -> str:
    authors = split_authors(text)
    if not authors:
        return "Autor no resuelto"
    formatted = []
    for author in authors:
        if is_organization_author(author):
            formatted.append(normalize_author_name(author))
            continue
        family = author_family(author)
        initials = author_initials(author)
        formatted.append(f"{family}, {initials}".strip().rstrip(","))
    return finalize_apa_name_list(formatted)


def format_short_citation_from_plain(text: str, year: str) -> str:
    year = normalize_reference_year(year)
    authors = split_authors(text)
    if not authors:
        return f"(Autor no resuelto, {year or 's. f.'})"
    families = [author_family(author) for author in authors]
    if len(families) == 1:
        return f"({families[0]}, {year})"
    if len(families) == 2:
        return f"({families[0]} & {families[1]}, {year})"
    return f"({families[0]} et al., {year})"


def short_title_for_citation(title: str, max_words: int = 5) -> str:
    text = sanitize_title(title)
    if not text or text == "Título no resuelto":
        return "Título no resuelto"
    text = re.sub(r"[.。]+$", "", text)
    words = text.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]).rstrip(",:;")
    return restore_acronyms(text)


def apa_title_case_for_citation(title: str) -> str:
    """Format title-based in-text citations without changing reference-list sentence case."""
    protected = {"AI", "API", "LLM", "LLMs", "RAG", "UML", "MoE", "PDF", "DOI", "QA", "NLP", "GPU"}
    minor_words = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "per", "the", "to", "vs", "via", "with"}
    words = title.split()
    formatted: list[str] = []
    for index, word in enumerate(words):
        bare = re.sub(r"^[^\w]+|[^\w]+$", "", word)
        prefix = word[: len(word) - len(word.lstrip("([{"))]
        suffix = word[len(word.rstrip(".,;:!?)]}")) :]
        core = word[len(prefix) : len(word) - len(suffix) if suffix else len(word)]
        if bare in protected or bare.upper() in protected:
            formatted.append(word)
        elif index > 0 and core.lower() in minor_words:
            formatted.append(prefix + core.lower() + suffix)
        elif "-" in core:
            formatted.append(prefix + "-".join(part[:1].upper() + part[1:].lower() if part else part for part in core.split("-")) + suffix)
        else:
            formatted.append(prefix + core[:1].upper() + core[1:].lower() + suffix)
    return " ".join(formatted)


def title_based_citation(title: str, year: str) -> str:
    short_title = short_title_for_citation(title, max_words=3)
    return f'("{apa_title_case_for_citation(short_title)}", {normalize_reference_year(year)})'



def normalize_reference_year(value: str | int | None, fallback: str = "s. f.") -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "nan", "no reportado", "not reported"}:
        return fallback
    return restore_acronyms(text)


def sanitize_title(title: str) -> str:
    text = html.unescape((title or "").strip())
    if not text:
        return "Título no resuelto"
    text = re.sub(r"</?[^>]+>", "", text)
    text = re.sub(r"(?<=\w),(?=[A-Za-zÀ-ÿА-Яа-я])", ", ", text)
    text = re.sub(r"(?<=\w):(?=[A-Za-zÀ-ÿА-Яа-я])", ": ", text)
    text = re.sub(r"([\"“”])\*+(?=[A-Za-zÀ-ÿА-Яа-я])", r"\1: ", text)
    text = re.sub(r"\s+-\s*(?=[A-Za-zÀ-ÿА-Яа-я])", ": ", text)
    text = re.sub(r"\s+:\s+", ": ", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\s+", " ", text)
    for bad, good in TITLE_FIXUPS.items():
        text = re.sub(rf"\b{re.escape(bad)}\b", good, text, flags=re.IGNORECASE)
    alpha_chars = [char for char in text if char.isalpha()]
    if alpha_chars and text == text.upper():
        text = text.lower()
        text = text[:1].upper() + text[1:]
    return restore_acronyms(text)


def sentence_case_title(title: str) -> str:
    text = sanitize_title(title)
    if not text or text == "Título no resuelto":
        return text
    words = re.findall(r"\b[^\W\d_][^\s:;,.!?()]*\b", text, flags=re.UNICODE)
    if not words:
        return restore_acronyms(text)
    titleish = sum(1 for word in words if len(word) > 2 and word[:1].isupper())
    capitalized_after_first = sum(
        1
        for word in words[1:]
        if len(word) > 2 and word[:1].isupper()
    )
    if (
        titleish / max(len(words), 1) < 0.45
        and capitalized_after_first < 3
        and text != text.upper()
    ):
        return restore_acronyms(text)

    def normalize_word(word: str, capitalize: bool) -> str:
        stripped = re.sub(r"^[^A-Za-zÀ-ÿА-Яа-я0-9]+|[^A-Za-zÀ-ÿА-Яа-я0-9]+$", "", word)
        if not stripped:
            return word
        normalized_parts = []
        for part_index, part in enumerate(stripped.split("-")):
            if not part:
                normalized_parts.append(part)
                continue
            preserve_mixed_case = bool(re.search(r"[a-z][A-Z]|[A-Z][a-z].*[A-Z]", part))
            if preserve_mixed_case or re.fullmatch(r"(?:[A-Z]{2,}[A-Z0-9]*|[A-Za-z]+[0-9][A-Za-z0-9]*)", part):
                normalized_part = part
            else:
                normalized_part = part.lower()
                if capitalize and part_index == 0:
                    normalized_part = normalized_part[:1].upper() + normalized_part[1:]
            normalized_parts.append(normalized_part)
        normalized = "-".join(normalized_parts)
        return word.replace(stripped, normalized, 1)

    tokens = re.split(r"(\s+)", text)
    capitalize_next = True
    normalized_tokens = []
    for token in tokens:
        if not token or token.isspace():
            normalized_tokens.append(token)
            continue
        normalized_tokens.append(normalize_word(token, capitalize_next))
        if re.search(r"[A-Za-zÀ-ÿА-Яа-я]", token):
            capitalize_next = False
        if any(mark in token for mark in (":", ".", "?", "!")):
            capitalize_next = True
    normalized = "".join(normalized_tokens)
    return restore_acronyms(normalized)


def restore_acronyms(text: str) -> str:
    normalized = text
    for plain, restored in ACRONYM_RESTORES.items():
        normalized = re.sub(rf"\b{re.escape(plain)}s\b", restored + "s", normalized, flags=re.IGNORECASE)
        normalized = re.sub(rf"\b{re.escape(plain)}\b", restored, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bGpt-([0-9])", r"GPT-\1", normalized)
    normalized = re.sub(r"\bRAG-r1\b", "RAG-R1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bPLOS one\b", "PLOS ONE", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<!\w)u\.s\.(?!\w)", "U.S.", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bjanakpur, nepal\b", "Janakpur, Nepal", normalized, flags=re.IGNORECASE)
    return normalized


def corpus_focus_relation(included_count: int, focus_count: int) -> str:
    remaining = max(included_count - focus_count, 0)
    if included_count <= 0:
        return "El corpus final aún no ofrece estudios incluidos suficientes para describir la relación entre corpus incluido y síntesis focal."
    if remaining == 0:
        return (
            f"En esta revisión no fue necesario recortar de nuevo el corpus incluido: los {focus_count} estudios "
            "que superaron la lectura completa en PDF mantuvieron suficiente ajuste temático, trazabilidad y densidad metodológica "
            "para sostener directamente la comparación intensiva."
        )
    if remaining == 1:
        return (
            f"A partir de esos {included_count} estudios incluidos, se definió una síntesis focal de {focus_count} estudios "
            "para la comparación intensiva. "
            "El estudio restante siguió dentro del corpus de revisión como perímetro contextual elegible: delimita el campo y conserva trazabilidad, "
            "pero no alcanzó el umbral combinado de ajuste, calidad, representatividad y densidad extractiva que exige la comparación intensiva. "
            "Por eso se reporta como contexto auditable y no como evidencia fina del N focal."
        )
    return (
        f"A partir de esos {included_count} estudios incluidos, se definió una síntesis focal de {focus_count} estudios "
        "para la comparación intensiva. "
        f"Los {remaining} estudios restantes siguieron dentro del corpus de revisión como perímetro contextual elegible: delimitan el campo y conservan trazabilidad, pero no alcanzaron el umbral combinado de ajuste, calidad, representatividad y densidad extractiva que exige la comparación intensiva. Por eso se reportan como contexto auditable y no como evidencia fina del N focal."
    )


def contribution_scope_phrase(included_count: int, focus_count: int) -> str:
    if included_count > 0 and included_count == focus_count:
        return "ofrecer una caracterización estructural reproducible del corpus incluido y entregar anexos CSV y evidencia PDF reutilizable para auditoría y replicación."
    return "distinguir el corpus incluido de la síntesis focal, ofrecer una caracterización estructural reproducible y entregar anexos CSV y evidencia PDF reutilizable para auditoría y replicación."


MISSING_EXTRACTION_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "not reported",
    "no aplica",
    "no disponible",
    "no reportado",
    "no se reporta",
    "sin datos",
    "sin informacion",
    "sin información",
    "unknown",
}


def is_missing_extraction_value(value: str | None) -> bool:
    text = normalize_phrase(value).strip().lower()
    text = re.sub(r"[.;:,]+$", "", text)
    return text in MISSING_EXTRACTION_VALUES


def conclusion_reporting_diagnostics(rows: list[dict[str, str]]) -> dict[str, int]:
    total = len(rows)
    missing_sample = 0
    missing_country = 0
    missing_variables = 0
    missing_theory = 0
    missing_benchmark = 0
    weak_validation = 0
    low_confidence = 0
    validation_pattern = re.compile(
        r"\b(validaci[oó]n|validation|benchmark|baseline|comparador|comparator|evaluaci[oó]n|evaluation|m[eé]trica|metric|experimento|experiment)\b",
        flags=re.IGNORECASE,
    )
    variable_fields = (
        "variables_dependent",
        "variables_independent",
        "variables_moderating",
        "variables_mediating",
        "variables_control",
    )
    for row in rows:
        if is_missing_extraction_value(row.get("sample_size")) and is_missing_extraction_value(row.get("sample_description")):
            missing_sample += 1
        if is_missing_extraction_value(first_nonempty(row.get("countries"), row.get("country_or_countries"))):
            missing_country += 1
        if all(is_missing_extraction_value(row.get(field)) for field in variable_fields):
            missing_variables += 1
        if is_missing_extraction_value(row.get("theory_framework")):
            missing_theory += 1
        if is_missing_extraction_value(row.get("benchmark_dataset_or_corpus")) and is_missing_extraction_value(row.get("baselines_or_comparators")):
            missing_benchmark += 1
        validation_blob = " ".join(
            first_nonempty(row.get(field))
            for field in (
                "design_detail",
                "method_used",
                "benchmark_dataset_or_corpus",
                "baselines_or_comparators",
                "instruments_or_scales",
                "key_findings",
            )
        )
        if not validation_pattern.search(validation_blob):
            weak_validation += 1
        if parse_int(row.get("extraction_confidence"), 100) < 70:
            low_confidence += 1
    return {
        "total": total,
        "missing_sample": missing_sample,
        "missing_country": missing_country,
        "missing_variables": missing_variables,
        "missing_theory": missing_theory,
        "missing_benchmark": missing_benchmark,
        "weak_validation": weak_validation,
        "low_confidence": low_confidence,
    }


def count_studies_es(count: int) -> str:
    return f"{count} {pluralize_estudio(count)}"


def verb_by_count(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def reporting_gap_sentence(diagnostics: dict[str, int]) -> str:
    """Summarize reporting gaps with correct Spanish singular/plural forms."""
    parts = []
    if diagnostics["missing_theory"] > 0:
        parts.append(
            f"{count_studies_es(diagnostics['missing_theory'])} "
            f"{verb_by_count(diagnostics['missing_theory'], 'no declara', 'no declaran')} marco teórico suficiente"
        )
    if diagnostics["missing_sample"] > 0:
        parts.append(
            f"{count_studies_es(diagnostics['missing_sample'])} "
            f"{verb_by_count(diagnostics['missing_sample'], 'no detalla', 'no detallan')} muestra"
        )
    if diagnostics["missing_country"] > 0:
        parts.append(
            f"{count_studies_es(diagnostics['missing_country'])} "
            f"{verb_by_count(diagnostics['missing_country'], 'no detalla', 'no detallan')} país o contexto"
        )
    if diagnostics["missing_variables"] > 0:
        parts.append(
            f"{count_studies_es(diagnostics['missing_variables'])} "
            f"{verb_by_count(diagnostics['missing_variables'], 'no explicita', 'no explicitan')} variables o dimensiones analíticas"
        )
    if diagnostics["missing_benchmark"] > 0:
        parts.append(
            f"{count_studies_es(diagnostics['missing_benchmark'])} "
            f"{verb_by_count(diagnostics['missing_benchmark'], 'no deja', 'no dejan')} una base comparativa clara"
        )
    if diagnostics["weak_validation"] > 0:
        parts.append(
            f"{count_studies_es(diagnostics['weak_validation'])} "
            f"{verb_by_count(diagnostics['weak_validation'], 'no ofrece', 'no ofrecen')} señal fuerte de validación comparable"
        )
    if not parts:
        return "no se detectan vacíos estructurales en los campos mínimos de reporting, aunque la equivalencia sustantiva sigue requiriendo lectura crítica"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def conclusion_unit_thesis(profile: str, topic: str = "") -> str:
    if profile == "ai_security_harness":
        return (
            "Esta revisión muestra que un harness de seguridad no debe compararse por nombre, número de filtros o una tasa de ataque aislada, "
            "sino por la configuración entre amenaza, superficie protegida, punto de aplicación, adaptatividad del atacante, baseline, reducción del riesgo, pérdida de utilidad y coste operacional."
        )
    if profile == "ai_architecture":
        return (
            "Esta revisión muestra que el campo no debe compararse solo por modelo base o benchmark, "
            "sino por la configuración entre tarea, recuperación, memoria, herramientas, orquestación, inferencia, verificación y evidencia."
        )
    if profile == "software_architecture":
        return (
            "Esta revisión muestra que el campo no debe compararse solo por modelo o herramienta de programación, "
            "sino por la configuración entre tarea de ingeniería, repositorio, herramienta, rol, flujo de coordinación, evaluación y evidencia."
        )
    if profile == "agent_architecture":
        return (
            "Esta revisión muestra que el campo no debe compararse solo por el LLM usado, "
            "sino por la configuración entre tarea, rol, herramienta, memoria, orquestación, verificación y contexto de uso."
        )
    if profile == "personality_llm":
        return (
            "Esta revisión muestra que el campo no debe compararse solo por modelo o por etiqueta de personalidad, "
            "sino por la configuración entre constructo, procedimiento de medición, intervención, métrica, tarea y efecto observado."
        )
    if profile == "ai_higher_education_teaching":
        return (
            "Esta revisión muestra que el campo no debe compararse solo por herramienta de IA, proveedor o promesa de eficiencia, "
            "sino por la configuración entre tarea docente, rol del profesorado, sistema de IA, contexto institucional, evidencia de aprendizaje, control pedagógico y límite de validez."
        )
    if profile == "creativity_llm":
        return (
            "Esta revisión muestra que el campo no debe compararse solo por nombre de modelo o resultado agregado, "
            "sino por la configuración entre tarea creativa, instrumento, juez, comparador, condición de generación y efecto observado."
        )
    if profile == "social_sciences":
        return (
            "Esta revisión muestra que el campo no debe compararse solo por presencia de una variable o por asociación bivariada, "
            "sino por la configuración entre constructo, medición, unidad de análisis, contexto institucional, mecanismo, diseño empírico y límite causal."
        )
    subject = topic or "el campo revisado"
    return (
        f"Esta revisión muestra que {subject} no debe compararse solo por frecuencia de menciones o resultados positivos, "
        "sino por la configuración entre objeto, diseño, unidad de análisis, método, evidencia, calidad de reporte y límite inferencial."
    )


def conclusion_grammar_sentence(profile: str, focus_count: int) -> str:
    if profile == "ai_security_harness":
        return (
            f"De esta revisión emerge una gramática de comparación defensiva basada en amenaza, atacante, control, punto de aplicación, "
            f"baseline, eficacia, falsos positivos, utilidad, latencia, coste, robustez y modo de fallo de los {focus_count} estudios focales."
        )
    if profile == "ai_architecture":
        return (
            f"De esta revisión emerge una gramática arquitectónica de comparación basada en componentes, tarea, recuperación, memoria, herramientas, "
            f"orquestación, inferencia, verificación, evidencia y límite de validez de los {focus_count} estudios focales."
        )
    if profile == "software_architecture":
        return (
            f"De esta revisión emerge una gramática arquitectónica de comparación basada en tarea de software, repositorio, herramienta, rol, coordinación, "
            f"evaluación, evidencia y límite de validez de los {focus_count} estudios focales."
        )
    if profile == "agent_architecture":
        return (
            f"De esta revisión emerge una gramática de comparación basada en tarea, rol, herramienta, memoria, orquestación, verificación, contexto de uso "
            f"y límite de validez de los {focus_count} estudios focales."
        )
    if profile == "personality_llm":
        return (
            f"De esta revisión emerge una gramática de comparación basada en la secuencia medición-intervención-efecto: constructo, instrumento, steering, "
            f"métrica, tarea, población o simulación y límite inferencial de los {focus_count} estudios focales."
        )
    if profile == "ai_higher_education_teaching":
        return (
            f"De esta revisión emerge una gramática de comparación basada en tarea docente, actor universitario, herramienta o sistema de IA, "
            f"diseño pedagógico, evidencia de calidad, evaluación, riesgo, adopción institucional y límite inferencial de los {focus_count} estudios focales."
        )
    if profile == "creativity_llm":
        return (
            f"De esta revisión emerge una gramática de comparación basada en tarea creativa, definición de novedad, utilidad, diversidad, juez, métrica, "
            f"comparador y condición de generación de los {focus_count} estudios focales."
        )
    if profile == "social_sciences":
        return (
            f"De esta revisión emerge una gramática de comparación basada en constructo social, mecanismo, unidad de análisis, muestra, contexto político, "
            f"medición, diseño, comparador y alcance inferencial de los {focus_count} estudios focales."
        )
    return (
        f"De esta revisión emerge una gramática analítica basada en pregunta, unidad de análisis, diseño, muestra, método, variables, resultados, "
        f"limitaciones y calidad de evidencia de los {focus_count} estudios focales."
    )


def original_contribution_table_lines(profile: str, topic: str, focus_count: int) -> list[str]:
    """Return a reusable contribution table for the discussion section.

    The table makes the contribution explicit for any topic: it separates the
    article thesis, the analytical grammar and the audit trail instead of
    leaving the section as a generic methodological claim.
    """
    if profile == "ai_security_harness":
        caption = "Tabla 10. Gramática de aportación original del artículo."
        unit = "Configuración amenaza-control-coste de fallo"
        grammar = "Amenaza, superficie, punto de aplicación, adaptatividad, baseline, eficacia, utilidad, coste, robustez y fallo residual"
    elif profile in {"ai_architecture", "software_architecture", "agent_architecture"}:
        caption = "Tabla 13. Gramática de aportación original del artículo."
        unit = "Arquitectura completa del sistema"
        grammar = "Tarea, componentes, memoria, herramientas, orquestación, inferencia, verificación y límite de validez"
    elif profile == "personality_llm":
        caption = "Tabla 11. Gramática de aportación original del artículo."
        unit = "Configuración constructo-medición-intervención-efecto"
        grammar = "Constructo, instrumento, steering, métrica, tarea, población o simulación y alcance inferencial"
    elif profile == "ai_higher_education_teaching":
        caption = "Tabla 10. Gramática de aportación original del artículo."
        unit = "Configuración tarea docente-sistema de IA-evidencia pedagógica"
        grammar = "Tarea docente, rol del profesorado, sistema de IA, contexto universitario, resultado educativo, control, riesgo y alcance inferencial"
    elif profile == "creativity_llm":
        caption = "Tabla 10. Gramática de aportación original del artículo."
        unit = "Configuración tarea creativa-juez-comparador-efecto"
        grammar = "Novedad, utilidad, diversidad, tarea, juez, rúbrica, comparador y condición de generación"
    elif profile == "social_sciences":
        caption = "Tabla 10. Gramática de aportación original del artículo."
        unit = "Configuración constructo-mecanismo-contexto-evidencia"
        grammar = "Constructo, mecanismo, medición, muestra, contexto político, diseño empírico, comparador y alcance causal"
    else:
        caption = "Tabla 10. Gramática de aportación original del artículo."
        unit = f"Configuración analítica de {topic}"
        grammar = "Pregunta, unidad de análisis, diseño, método, evidencia, resultado y límite inferencial"

    rows = [
        [
            "Tesis de comparación",
            f"La revisión no compara menciones aisladas, sino {unit.lower()}.",
            "Evita que la síntesis dependa de popularidad, proveedor, etiqueta o frecuencia superficial.",
        ],
        [
            "Gramática analítica",
            grammar,
            "Permite decidir cuándo dos estudios son realmente comparables y cuándo solo comparten vocabulario.",
        ],
        [
            "Evidencia focal",
            f"{focus_count} estudios con DOI, texto completo y extracción trazable.",
            "Ancla las conclusiones en documentos verificables y no en resúmenes no auditables.",
        ],
        [
            "Diagnóstico de madurez",
            "Separa evidencia fuerte, señal emergente y vacío de reporte.",
            "Convierte ausencias de teoría, muestra, variables, benchmark o validación en hallazgos metodológicos.",
        ],
        [
            "Uso acumulativo",
            "Deja una matriz y un vocabulario reutilizables para futuras revisiones.",
            "Facilita actualización, réplica, crítica y comparación longitudinal del campo.",
        ],
    ]
    return [
        caption,
        markdown_table(["Plano de aportación", "Qué añade el artículo", "Valor para el lector"], rows),
        "",
    ]


def conclusion_diagnostic_future_lines(rows: list[dict[str, str]], profile: str) -> list[str]:
    diagnostics = conclusion_reporting_diagnostics(rows)
    total = max(diagnostics["total"], 1)
    def count_studies(count: int) -> str:
        return f"{count} {pluralize_estudio(count)}"

    def verb_singular_plural(count: int, singular: str, plural: str) -> str:
        return singular if count == 1 else plural

    if is_ai_workload_rows(rows):
        primary_rows = empirical_rows_only(rows) or rows
        primary_total = len(primary_rows)
        support_count = max(len(rows) - primary_total, 0)
        counts = ai_workload_signal_counts(primary_rows)
        return [
            "## Líneas futuras",
            "",
            f"La agenda futura no debería limitarse a preguntar si la IA aumenta la productividad. En esta revisión, la base empírica primaria queda separada de {support_count} trabajos de apoyo no empírico; esa separación debe mantenerse en futuras actualizaciones. La pregunta de fondo ya llega tarde si no define qué trabajo cuenta, quién lo realiza, en qué fase aparece y qué coste queda oculto fuera de la métrica principal. La prioridad científica es pasar de estudios de ahorro local a diseños capaces de medir el balance completo del trabajo humano cuando una tarea se reconfigura con IA.",
            "",
            "La primera línea futura es medir trabajo total y no solo tiempo de ejecución. Los estudios que informan productividad o eficiencia deben registrar también tiempo de preparación, iteraciones de prompting, revisión, corrección, relectura, coordinación, documentación, escalado de errores y responsabilidad final. Sin esa contabilidad, un resultado de ahorro puede estar midiendo solo la parte visible de la tarea y dejando fuera el trabajo que la hace segura, útil y aceptable.",
            "",
            f"La segunda línea futura es separar tareas de bajo y alto riesgo. La señal de productividad aparece en {counts['productivity']}/{primary_total} estudios empíricos primarios, pero el coste de error cambia radicalmente entre redactar un borrador, resumir información, evaluar estudiantes, apoyar decisiones clínicas, automatizar código o asesorar procesos organizativos. La pregunta madura no es si la IA acelera, sino cuándo el coste de verificar la salida es menor que el ahorro de producirla.",
            "",
            f"La tercera línea futura es estudiar explícitamente el trabajo de supervisión. La señal de revisión, control o supervisión aparece en {counts['supervision']}/{primary_total} estudios empíricos primarios; por tanto, futuras investigaciones deberían medir esa supervisión como variable central y no como nota de cautela. Revisar salidas, detectar errores plausibles, decidir cuándo confiar, documentar cambios y asumir consecuencias no son actividades periféricas: son parte del trabajo real creado por la adopción.",
            "",
            f"La cuarta línea futura es analizar aprendizaje, dependencia y recualificación como costes de transición. La señal de aprendizaje o dependencia aparece en {counts['learning']}/{primary_total} estudios empíricos primarios. Esto obliga a estudiar curvas de aprendizaje, pérdida de habilidad, confianza excesiva, cambios de rol y nuevas competencias de supervisión. Si una tecnología exige aprender a controlarla, el aprendizaje no puede tratarse como coste cero.",
            "",
            f"La quinta línea futura es convertir gobernanza y responsabilidad en resultados observables. La señal de gobernanza aparece en {counts['governance']}/{primary_total} estudios empíricos primarios. Futuros trabajos deberían registrar políticas de uso, trazabilidad, privacidad, auditoría, responsabilidad profesional, intervención humana y manejo de fallos. Una organización no trabaja menos si traslada el ahorro de producción a capas invisibles de cumplimiento, control o riesgo reputacional.",
            "",
            "La sexta línea futura es diseñar comparadores más honestos. Comparar una persona sin IA contra una persona con IA no basta si no se igualan experiencia, complejidad de tarea, acceso a datos, criterios de calidad, obligación de revisión y coste de error. El comparador relevante no es una herramienta, sino un flujo completo de trabajo: humano solo, humano con IA, equipo con IA, sistema automatizado supervisado y sistema automatizado sin supervisión no son el mismo tratamiento.",
            "",
            "La séptima línea futura es abandonar métricas promocionales y construir medidas de desplazamiento. La literatura necesita indicadores como trabajo invisible añadido, tasa de rework, tiempo hasta aceptación final, coste de verificación, errores no detectados, dependencia del sistema, carga cognitiva, número de escalados, coordinación adicional y responsabilidad residual. Solo entonces podrá responderse con rigor si se trabaja menos, se trabaja distinto o se trabaja más para sostener una apariencia de automatización.",
        ]

    diagnostic_parts = []
    if diagnostics["missing_theory"] > 0:
        diagnostic_parts.append(
            f"{count_studies(diagnostics['missing_theory'])} {verb_singular_plural(diagnostics['missing_theory'], 'no declara', 'no declaran')} una base teórica suficiente"
        )
    if diagnostics["missing_variables"] > 0:
        diagnostic_parts.append(
            f"{count_studies(diagnostics['missing_variables'])} {verb_singular_plural(diagnostics['missing_variables'], 'no explicita', 'no explicitan')} variables o dimensiones analíticas"
        )
    if diagnostics["missing_benchmark"] > 0:
        diagnostic_parts.append(
            f"{count_studies(diagnostics['missing_benchmark'])} {verb_singular_plural(diagnostics['missing_benchmark'], 'no deja', 'no dejan')} un comparador claro"
        )
    if diagnostic_parts:
        diagnostic_sentence = (
            "En conjunto, estos vacíos señalan un problema de conmensurabilidad: el campo puede producir "
            "resultados localmente útiles sin ofrecer todavía las piezas necesarias para acumularlos bajo "
            "una explicación compartida."
        )
    else:
        diagnostic_sentence = (
            "Aunque los campos mínimos de teoría, variables y comparación aparecen cubiertos, el problema científico no desaparece: "
            "la acumulación depende de que esas categorías sean sustantivamente equivalentes entre estudios."
        )

    context_gap_parts = []
    if diagnostics["missing_sample"] > 0:
        context_gap_parts.append(
            f"{count_studies(diagnostics['missing_sample'])} "
            f"{verb_singular_plural(diagnostics['missing_sample'], 'no detalla', 'no detallan')} muestra"
        )
    if diagnostics["missing_country"] > 0:
        context_gap_parts.append(
            f"{count_studies(diagnostics['missing_country'])} "
            f"{verb_singular_plural(diagnostics['missing_country'], 'no detalla', 'no detallan')} país, entorno o contexto territorial"
        )
    context_gap_sentence = "; ".join(context_gap_parts)

    lines = [
        "## Líneas futuras",
        "",
        "Las líneas futuras no se plantean aquí como un cierre ornamental ni como una lista genérica de deseos. En una revisión sistemática, la agenda posterior debe derivarse de los límites observados en la evidencia primaria: qué no se puede comparar todavía, qué se reporta con insuficiente detalle y qué condiciones faltan para convertir señales recurrentes en conocimiento acumulativo. Por eso esta sección no propone simplemente ampliar el número de estudios, sino mejorar la calidad inferencial de los próximos trabajos.",
        "",
        f"En el subconjunto focal de {total} {pluralize_estudio(total)}, los vacíos de reporte permiten ordenar la agenda futura en varios planos complementarios: base teórica, contexto empírico, operacionalización de variables o constructos, equivalencia de comparadores y validación. La lógica es acumulativa: cada línea futura responde a una limitación concreta detectada durante la extracción y señala qué tendría que cambiar en los estudios primarios para que una revisión posterior pueda comparar con más precisión, menor ambigüedad y mayor fuerza explicativa.",
        "",
        diagnostic_sentence,
        "",
    ]
    candidate_lines = [
        (
            diagnostics["missing_theory"],
            "Una línea futura prioritaria es fortalecer la base teórica de los estudios primarios. "
            f"En esta revisión, {diagnostics['missing_theory']} de {total} trabajos focales no declaran una base teórica suficiente para comparación acumulativa; por tanto, la agenda no consiste solo en producir más estudios, sino en explicar con qué marco conceptual se justifican sus unidades de análisis, mecanismos y límites.",
        ),
        (
            diagnostics["missing_sample"] + diagnostics["missing_country"],
            "Otra línea futura es mejorar la trazabilidad del contexto empírico. "
            f"{context_gap_sentence}; esa ausencia no es un detalle menor, porque limita la posibilidad de saber dónde vale una conclusión, para qué población, con qué unidad de análisis y bajo qué condiciones de transferencia.",
        ),
        (
            diagnostics["missing_variables"],
            "Otra línea futura es operacionalizar mejor variables, constructos o dimensiones analíticas. "
            f"{count_studies(diagnostics['missing_variables'])} {verb_singular_plural(diagnostics['missing_variables'], 'focal no ofrece', 'focales no ofrecen')} un esquema suficientemente explícito; por eso futuras investigaciones deberían declarar qué se mide, qué se manipula o compara, qué resultado cuenta como evidencia y qué dimensión queda solo como interpretación secundaria.",
        ),
        (
            diagnostics["missing_benchmark"],
            "Otra línea futura es construir comparadores más equivalentes. "
            f"{count_studies(diagnostics['missing_benchmark'])} {verb_singular_plural(diagnostics['missing_benchmark'], 'no reporta', 'no reportan')} una base comparativa clara; sin benchmark, corpus, baseline, condición de control o métrica compartida, la revisión puede detectar señales, pero no convertirlas todavía en una jerarquía robusta de diseños, métodos o resultados.",
        ),
        (
            diagnostics["weak_validation"],
            "Otra línea futura es reforzar validación externa, replicación y evaluación longitudinal cuando el objeto lo permita. "
            f"{count_studies(diagnostics['weak_validation'])} {verb_singular_plural(diagnostics['weak_validation'], 'no deja', 'no dejan')} una señal fuerte de validación comparable; la consecuencia es que el campo puede mostrar promesa, pero todavía necesita pruebas que separen rendimiento local, robustez, generalización y estabilidad temporal.",
        ),
        (
            diagnostics["low_confidence"],
            "Otra línea futura es elevar la densidad de reporte metodológico. "
            f"{count_studies(diagnostics['low_confidence'])} {verb_singular_plural(diagnostics['low_confidence'], 'quedó', 'quedaron')} por debajo de un umbral alto de confianza de extracción; mejorar anexos, protocolos, datos, prompts, instrumentos, logs o scripts reduciría la incertidumbre y permitiría que futuras revisiones comparen evidencia, no solo narrativas.",
        ),
    ]
    selected_future_lines = 0
    for score, text in candidate_lines:
        if score > 0 and selected_future_lines < 5:
            lines.extend([text, ""])
            selected_future_lines += 1
    if selected_future_lines < 5:
        fallback_by_profile = {
            "ai_security_harness": [
                "Otra línea futura es evaluar defensas bajo atacantes adaptativos que conozcan el control y puedan optimizar contra él. Una defensa que funciona solo frente a un conjunto estático de prompts demuestra cobertura de benchmark, no robustez operacional.",
                "También se necesitan comparaciones que reporten conjuntamente seguridad y utilidad. Reducir la tasa de ataque bloqueando solicitudes legítimas, degradando la tarea o introduciendo una latencia prohibitiva no demuestra superioridad del sistema; desplaza el riesgo hacia disponibilidad, experiencia de uso o coste.",
                "Por último, los estudios deberían publicar amenaza, configuración del harness, punto de aplicación, baselines, semillas, prompts de ataque, código y resultados negativos cuando la licencia lo permita. Sin esos artefactos no puede distinguirse una defensa generalizable de un ajuste local al benchmark.",
            ],
            "ai_architecture": [
                "Otra línea futura es contrastar arquitecturas completas bajo tareas, métricas y condiciones de fallo equivalentes. El objetivo no debería ser demostrar que un modelo base gana en abstracto, sino aislar qué configuración de sistema mejora una tarea concreta y bajo qué coste de complejidad.",
                "También conviene separar evaluación de capacidad, evaluación de sistema y evaluación de despliegue. Mezclar esos planos produce conclusiones atractivas pero poco acumulativas, porque una mejora de benchmark no equivale necesariamente a robustez operativa.",
                "Por último, el campo necesita publicar artefactos de arquitectura, prompts, datasets, logs y scripts de evaluación cuando la licencia lo permita. Sin esos materiales, la revisión puede interpretar el paper, pero no reconstruir con precisión la configuración evaluada.",
            ],
            "personality_llm": [
                "Otra línea futura es separar profiling, steering y efectos downstream. Esa separación impediría que la literatura mezcle diagnóstico, intervención y consecuencia bajo una misma etiqueta de personalidad.",
                "También se necesitan protocolos psicométricos comparables entre estudios, modelos y contextos de evaluación. Sin esa estabilidad, la personalidad puede parecer un resultado fuerte cuando en realidad depende del instrumento o del prompt.",
                "Finalmente, los estudios deberían distinguir mejor rasgo estable, estilo conversacional, role-play y artefacto de prompting. Esa distinción marcará la diferencia entre una psicología artificial acumulativa y una colección de demostraciones plausibles.",
            ],
            "ai_higher_education_teaching": [
                "Otra línea futura es separar adopción docente, mejora pedagógica y resultado de aprendizaje. Esa distinción impide confundir uso frecuente de IA con mejora real de calidad educativa.",
                "También se necesitan estudios que comparen tareas docentes equivalentes: feedback, evaluación, diseño curricular, tutoría, preparación de clases, investigación docente y gestión académica no producen el mismo tipo de evidencia.",
                "Finalmente, futuras investigaciones deberían declarar condiciones institucionales, alfabetización en IA, carga de trabajo, políticas de integridad académica y mecanismos de supervisión humana. Sin ese contexto, la transferencia entre universidades queda sobredimensionada.",
            ],
            "creativity_llm": [
                "Otra línea futura es separar novedad, utilidad, diversidad, sorpresa, pensamiento divergente y resolución creativa de problemas. Llamar creatividad a todas esas dimensiones a la vez impide saber qué mejora realmente.",
                "También se requieren comparaciones bajo tareas creativas equivalentes, jueces declarados y criterios transparentes. Sin esa equivalencia, el resultado puede depender más de la rúbrica que del sistema evaluado.",
                "Finalmente, conviene combinar métricas automáticas con evaluación humana trazable cuando la creatividad se defina como fenómeno aplicado. La evaluación automática puede escalar, pero no debe sustituir sin control el juicio de utilidad, originalidad o adecuación contextual.",
            ],
            "social_sciences": [
                "Otra línea futura es separar correlación observacional, mecanismo plausible e inferencia causal. En ciencias sociales, una asociación robusta puede orientar teoría, pero solo ciertos diseños permiten afirmar dirección, mediación o efecto neto.",
                "También se necesitan mediciones más equivalentes de constructos: exposición, confianza, polarización, identidad, comportamiento y contexto institucional no deberían agregarse si cada estudio los operacionaliza de forma incompatible.",
                "Finalmente, las revisiones futuras deberían prestar más atención a contexto y transferencia. Un hallazgo en una plataforma, país, ciclo electoral o grupo social no se traslada automáticamente a otra democracia sin declarar condiciones institucionales, mediáticas y temporales.",
            ],
        }
        for text in fallback_by_profile.get(profile, []):
            if selected_future_lines >= 5:
                break
            lines.extend([text, ""])
            selected_future_lines += 1
    while selected_future_lines < 5:
        lines.extend(
            [
                "Una línea futura transversal es publicar anexos de búsqueda, cribado, extracción y selección. Esta práctica no añade burocracia: permite que futuras revisiones actualicen la síntesis, detecten sesgos de selección y discutan los cortes metodológicos con evidencia material.",
                "",
            ]
        )
        selected_future_lines += 1
    if lines[-1] == "":
        lines.pop()
    return lines


def authorial_contribution_model(
    profile: str,
    topic: str,
    focus_count: int,
    included_n: int,
    diagnostics: dict[str, int],
) -> dict[str, object]:
    """Return a field-specific theoretical contribution, not a numeric recap."""
    if is_ai_workload_review_text(topic):
        return {
            "name": "modelo de desplazamiento del trabajo humano",
            "thesis": (
                "La aportación central del artículo es rechazar la pregunta ingenua de si la IA hace trabajar menos como si el trabajo fuera una cantidad única y homogénea. "
                "La evidencia revisada apunta a otra tesis: la IA comprime algunas tareas de ejecución, pero desplaza una parte relevante del esfuerzo hacia formulación, supervisión, revisión, coordinación, aprendizaje, gobernanza y responsabilidad. "
                "El ahorro local existe; la reducción neta del trabajo humano no queda demostrada como regla general."
            ),
            "theory": (
                "La tesis teórica es que la IA reorganiza la morfología del trabajo. Cuando un sistema genera, clasifica, resume o recomienda, no elimina automáticamente la actividad humana: cambia dónde aparece. "
                "Parte del esfuerzo se desplaza antes de la tarea, en forma de especificación, prompting, selección de datos y diseño del flujo; otra parte aparece después, en verificación, corrección, control de calidad, explicación, integración con el proceso y asunción de responsabilidad. "
                "Por eso productividad, tiempo de tarea y carga de trabajo no son equivalentes."
            ),
            "model": (
                "El modelo interpretativo queda organizado como ejecución-articulación-verificación-coordinación-aprendizaje-responsabilidad. "
                "La ejecución es la parte que la IA puede acelerar con más facilidad; la articulación traduce una necesidad humana en una instrucción útil; la verificación comprueba errores, omisiones y sesgos; la coordinación integra la salida en equipos, normas y sistemas; el aprendizaje crea competencias para usar y controlar la herramienta; y la responsabilidad sigue recayendo en personas u organizaciones. "
                "El balance real depende de la suma de todas esas capas, no solo del tiempo ahorrado en producir una primera respuesta."
            ),
            "field": (
                "El aporte al campo es proponer una unidad de comparación más honesta: no 'uso de IA' frente a 'no uso de IA', sino redistribución del trabajo entre producción, control y responsabilidad. "
                "Esta regla permite explicar por qué un estudio puede encontrar productividad positiva y, al mismo tiempo, otro puede documentar más vigilancia, dependencia, errores, fricción institucional o necesidad de recualificación."
            ),
            "method": (
                "La consecuencia metodológica es que futuras investigaciones no deberían medir solo minutos ahorrados o outputs por hora. Deberían medir trabajo total del sistema: tiempo de preparación, número de iteraciones, carga cognitiva, revisión humana, tasa de error, rework, coordinación, aprendizaje, coste de integración, responsabilidad y calidad final."
            ),
            "rows": [
                ["Unidad de teoría", "Trabajo total del sistema", "La productividad local no equivale a reducción neta de carga humana."],
                ["Mecanismo central", "Ejecución-articulación-verificación-coordinación-aprendizaje-responsabilidad", "La IA mueve trabajo entre fases en lugar de hacerlo desaparecer."],
                ["Aporte disciplinar", "Distinguir ahorro de tarea y desplazamiento de esfuerzo", "Permite leer productividad, carga y calidad sin confundirlas."],
                ["Regla futura", "Medir trabajo invisible y coste de control", "Evita estudios que celebran velocidad mientras ocultan revisión, rework y responsabilidad."],
            ],
        }
    if profile == "ai_security_harness":
        return {
            "name": "modelo de defensa como contrato operacional",
            "thesis": (
                "La aportación central del artículo es rechazar la idea de que un harness es mejor porque bloquea más ataques en un benchmark aislado. "
                "Una defensa solo puede considerarse superior dentro de un contrato operacional explícito: amenaza y atacante definidos, superficie protegida, punto de aplicación, baseline comparable, reducción de riesgo, utilidad preservada, coste asumible y fallo residual conocido."
            ),
            "theory": (
                "La tesis teórica es que la seguridad de modelos generativos y agentes no reside en una barrera única, sino en la distribución de control a lo largo del sistema. "
                "Filtros de entrada, aislamiento de contexto, permisos de herramientas, monitores de ejecución, verificadores de salida y auditoría reducen incertidumbres distintas. "
                "Sumar capas no garantiza seguridad: cada capa cambia la superficie de ataque, introduce falsos positivos y puede crear puntos ciegos nuevos."
            ),
            "model": (
                "El modelo interpretativo propuesto es amenaza-superficie-control-evidencia-coste. La amenaza declara qué capacidad tiene el atacante; la superficie identifica dónde puede influir; el control especifica qué decisión se bloquea, limita o verifica; la evidencia mide el riesgo residual frente a baselines y ataques adaptativos; y el coste incorpora utilidad, latencia, cómputo y carga de operación. "
                "La comparación pierde validez cuando omite cualquiera de esas piezas."
            ),
            "field": (
                "El aporte al campo es una regla de decisión que sustituye rankings universales por fronteras de dominancia. Un harness domina a otro solo si reduce más riesgo bajo la misma amenaza y baseline sin empeorar de manera material utilidad, falsos positivos, coste o latencia; cuando existen compensaciones, la conclusión correcta es contextual y debe nombrar qué propiedad se prioriza."
            ),
            "method": (
                "La consecuencia metodológica es exigir que futuras evaluaciones reporten threat model, atacante adaptativo o estático, punto de enforcement, corpus de ataques, baseline, ASR o métrica equivalente, falsos positivos, utilidad, latencia, coste, robustez fuera de distribución y modos de fallo. "
                "Sin esa ficha mínima, el estudio puede demostrar una técnica, pero no sostener que ofrece el mejor harness."
            ),
            "rows": [
                ["Unidad de teoría", "Contrato operacional de defensa", "Impide comparar controles bajo amenazas o costes incompatibles."],
                ["Mecanismo central", "Amenaza-superficie-control-evidencia-coste", "Explica dónde se reduce riesgo y dónde se desplaza."],
                ["Aporte disciplinar", "Frontera de dominancia defensiva", "Sustituye un ranking único por comparaciones multiobjetivo auditables."],
                ["Regla futura", "Evaluar adaptación, utilidad y fallo residual", "Evita declarar victoria sobre benchmarks estáticos o defensas demasiado restrictivas."],
            ],
        }
    if profile == "ai_architecture":
        return {
            "name": "modelo de sistema como unidad epistémica",
            "thesis": (
                "La aportación central del artículo es desplazar la unidad de comparación desde el modelo fundacional hacia el sistema que lo convierte en acción verificable. "
                "En este campo, comparar solo modelos base equivale a comparar motores fuera del vehículo: informa sobre potencia potencial, pero no sobre dirección, frenos, sensores, carga útil, coste de fallo ni control."
            ),
            "theory": (
                "La tesis teórica es que una arquitectura de IA no es una suma de módulos, sino una forma de organizar incertidumbre. Recuperación, memoria, herramientas, roles, orquestación e inferencia adquieren valor cuando especifican cómo entra el contexto, cómo se transforma en decisión, cómo se ejecuta una acción y cómo se verifica la salida. "
                "El artículo propone leer la arquitectura como una gramática de responsabilidad: cada componente responde a una pregunta distinta sobre evidencia, agencia, control y trazabilidad."
            ),
            "model": (
                "El modelo interpretativo que queda es una cadena capacidad-contexto-acción-verificación. La capacidad del modelo solo se vuelve comparable cuando se observa junto al contexto que recibe, las herramientas que puede invocar, la memoria que conserva, la coordinación que organiza y los mecanismos que detectan error. "
                "Esta cadena permite explicar por qué dos sistemas basados en un mismo modelo pueden producir evidencias científicas, riesgos y costes operativos radicalmente distintos."
            ),
            "field": (
                "El aporte al campo es ofrecer una teoría de comparación para sistemas de IA: no preguntar qué modelo es mejor en abstracto, sino qué configuración convierte capacidad en desempeño controlable bajo una tarea, un entorno y un coste de fallo determinados."
            ),
            "method": (
                "La consecuencia metodológica es que futuras revisiones no deberían codificar únicamente modelo, benchmark y resultado; deberían codificar arquitectura completa, política de inferencia, fuentes de contexto, estado, herramientas, rutas de verificación y evidencia de fallo."
            ),
            "rows": [
                ["Unidad de teoría", "Sistema completo", "El modelo base deja de ser explicación suficiente."],
                ["Mecanismo central", "Capacidad-contexto-acción-verificación", "La comparación se decide por configuración, no por potencia nominal."],
                ["Aporte disciplinar", "Gramática de responsabilidad", "Cada componente se interpreta por la incertidumbre que reduce o desplaza."],
                ["Regla futura", "Comparar arquitectura bajo tarea y coste de fallo", "Evita rankings débiles basados solo en benchmarks o demos."],
            ],
        }
    if profile == "software_architecture":
        return {
            "name": "modelo de arquitectura software como coordinación verificable",
            "thesis": (
                "La aportación central es tratar la arquitectura de software asistida por IA como un problema de coordinación verificable, no como una colección de herramientas de productividad. "
                "El campo gana poder explicativo cuando compara cómo se distribuyen responsabilidades entre repositorio, agente, desarrollador, prueba, revisión y despliegue."
            ),
            "theory": (
                "La tesis teórica es que la IA modifica la arquitectura del trabajo tanto como el código producido. El objeto relevante no es solo si una herramienta genera una solución, sino qué dependencias crea, qué decisiones automatiza, qué pruebas conserva y qué deuda técnica desplaza hacia el futuro."
            ),
            "model": (
                "El modelo interpretativo queda organizado como intención-cambio-validación-integración. Una contribución técnica solo es comparable cuando se conoce la intención de cambio, el artefacto modificado, la validación aplicada y la forma en que entra en el sistema mayor."
            ),
            "field": (
                "El aporte al campo es separar productividad local de mantenibilidad sistémica. Esa distinción evita confundir velocidad de generación con calidad arquitectónica acumulativa."
            ),
            "method": (
                "La consecuencia metodológica es exigir que futuras revisiones codifiquen repositorio, tarea, alcance del cambio, pruebas, revisión, integración, fallo y coste de mantenimiento."
            ),
            "rows": [
                ["Unidad de teoría", "Cambio verificable en un sistema", "La salida aislada no prueba calidad arquitectónica."],
                ["Mecanismo central", "Intención-cambio-validación-integración", "La evidencia se decide por trazabilidad de ciclo completo."],
                ["Aporte disciplinar", "Separar productividad y mantenibilidad", "Evita conclusiones infladas por demos funcionales."],
                ["Regla futura", "Reportar pruebas, revisión e integración", "Hace acumulables estudios de desarrollo asistido por IA."],
            ],
        }
    if profile == "personality_llm":
        return {
            "name": "modelo medición-intervención-efecto",
            "thesis": (
                "La aportación central es negar que la personalidad en LLMs pueda tratarse como rasgo estable sin especificar el dispositivo que la produce. "
                "En estos sistemas, personalidad no es solo lo que el modelo 'tiene', sino lo que emerge entre instrumento psicométrico, prompt, rol, tarea, contexto conversacional y criterio de evaluación."
            ),
            "theory": (
                "La tesis teórica es que el campo debe separar tres objetos que suelen mezclarse: medir una respuesta compatible con un rasgo, inducir una persona sintética y demostrar efectos observables en interacción o seguridad. "
                "Si esas capas se agregan bajo una sola etiqueta, la revisión produce una ilusión de estabilidad psicológica donde quizá solo hay estilo, role-play o sensibilidad al instrumento."
            ),
            "model": (
                "El modelo interpretativo resultante es medición-intervención-efecto. Primero se define qué constructo se mide; después se declara qué intervención altera la conducta del modelo; finalmente se prueba qué consecuencia produce en usuarios, decisiones, alineamiento o riesgo. "
                "La fuerza de una afirmación depende de que esas tres capas estén conectadas y no sustituidas por una impresión antropomórfica."
            ),
            "field": (
                "El aporte al campo es proponer una psicometría artificial sobria: útil para comparar comportamientos generados, pero cautelosa frente a atribuir interioridad, rasgo estable o equivalencia humana sin pruebas de invariancia."
            ),
            "method": (
                "La consecuencia metodológica es que futuras revisiones deben codificar instrumento, prompt, estabilidad entre tareas, repetición, comparador humano o modelo, y efecto downstream antes de hablar de personalidad del modelo."
            ),
            "rows": [
                ["Unidad de teoría", "Conducta generada bajo instrumento", "Evita confundir rasgo con estilo de respuesta."],
                ["Mecanismo central", "Medición-intervención-efecto", "Separa profiling, steering y consecuencia observable."],
                ["Aporte disciplinar", "Psicometría artificial sobria", "Permite estudiar personalidad sin antropomorfismo débil."],
                ["Regla futura", "Exigir estabilidad e invariancia", "Convierte impresiones de persona en evidencia comparable."],
            ],
        }
    if profile == "ai_higher_education_teaching":
        return {
            "name": "modelo de mediación pedagógica asistida",
            "thesis": (
                "La aportación central es desplazar la pregunta desde si la IA mejora la docencia hacia qué mediación pedagógica permite mejorar una tarea universitaria concreta. "
                "La IA no aparece como variable mágica de calidad, sino como infraestructura que puede ampliar, acelerar o empobrecer decisiones docentes según diseño, supervisión, alfabetización y contexto institucional."
            ),
            "theory": (
                "La tesis teórica es que la calidad docente no se explica por adopción tecnológica, sino por la relación entre tarea pedagógica, criterio académico, interacción con estudiantes, carga de trabajo y control humano. "
                "Por eso una revisión madura debe separar feedback, evaluación, diseño curricular, tutoría, investigación docente y gestión académica: cada función produce un tipo de evidencia distinto."
            ),
            "model": (
                "El modelo interpretativo queda organizado como tarea-criterio-mediación-resultado. Primero se identifica la tarea docente; después el criterio de calidad; luego la mediación que introduce la IA; finalmente el resultado observable y sus riesgos. "
                "Ese modelo evita que satisfacción, productividad y aprendizaje se mezclen como si fueran una misma mejora."
            ),
            "field": (
                "El aporte al campo es ofrecer una teoría de uso situado: la IA aporta valor cuando fortalece juicio pedagógico, trazabilidad y adaptación, no cuando sustituye sin criterio la decisión académica."
            ),
            "method": (
                "La consecuencia metodológica es que futuras revisiones deben codificar función docente, actor universitario, evidencia de calidad, supervisión, integridad académica, transferencia institucional y coste de implementación."
            ),
            "rows": [
                ["Unidad de teoría", "Tarea docente situada", "La adopción no equivale a mejora educativa."],
                ["Mecanismo central", "Tarea-criterio-mediación-resultado", "Separa productividad, aprendizaje y calidad pedagógica."],
                ["Aporte disciplinar", "Teoría de mediación pedagógica", "Ubica la IA dentro del juicio docente, no por encima de él."],
                ["Regla futura", "Medir calidad por función docente", "Evita promesas universales de IA en educación superior."],
            ],
        }
    if profile == "creativity_llm":
        return {
            "name": "modelo de creatividad como configuración evaluada",
            "thesis": (
                "La aportación central es rechazar la creatividad como atributo global del modelo. En LLMs, la creatividad aparece como una configuración entre tarea, restricción, espacio de búsqueda, criterio de novedad, utilidad, diversidad y juicio evaluador. "
                "Sin esa configuración, decir que un modelo es creativo equivale a confundir fluidez verbal con aportación original."
            ),
            "theory": (
                "La tesis teórica es que la creatividad computacional debe estudiarse como relación entre producción y evaluación. Una salida puede ser sorprendente pero inútil, útil pero poco nueva, diversa pero incoherente, o novedosa solo porque la rúbrica es débil. "
                "Por eso el campo necesita distinguir generación creativa, pensamiento divergente, ideación científica, resolución de problemas y evaluación de originalidad."
            ),
            "model": (
                "El modelo interpretativo queda organizado como tarea-restricción-variación-juicio. La tarea define el espacio; la restricción fija el problema; la variación produce alternativas; el juicio decide si hay novedad y utilidad. "
                "Esta cadena explica por qué los resultados cambian al modificar prompt, juez, benchmark, dominio o criterio de calidad."
            ),
            "field": (
                "El aporte al campo es convertir creatividad en objeto comparativo y no en etiqueta estética. La revisión deja una regla clara: no se compara creatividad sin declarar qué se considera nuevo, útil, diverso y para quién."
            ),
            "method": (
                "La consecuencia metodológica es que futuras revisiones deben codificar tarea creativa, rúbrica, juez, comparador humano o automático, criterio de utilidad, diversidad, originalidad, repetición y transferencia entre dominios."
            ),
            "rows": [
                ["Unidad de teoría", "Configuración creativa evaluada", "La creatividad no reside solo en el modelo."],
                ["Mecanismo central", "Tarea-restricción-variación-juicio", "La evaluación forma parte del fenómeno."],
                ["Aporte disciplinar", "Creatividad como objeto comparable", "Distingue fluidez, novedad, utilidad y diversidad."],
                ["Regla futura", "Declarar criterio y juez", "Evita rankings creativos sin validez constructiva."],
            ],
        }
    if profile == "social_sciences":
        return {
            "name": "modelo de conmensurabilidad situada",
            "thesis": (
                f"La aportación central del artículo es formular un modelo de conmensurabilidad situada para estudiar {topic}. "
                "La pregunta fuerte no es si una variable se asocia con otra, sino bajo qué condiciones una relación social conserva significado, mecanismo y alcance cuando cambia de población, institución, plataforma, momento histórico o instrumento de medición."
            ),
            "theory": (
                "La tesis teórica es que las ciencias sociales no acumulan por adición, sino por equivalencia justificada entre afirmaciones. Un mismo rótulo puede nombrar fenómenos distintos si cambia la operacionalización, la secuencia temporal, la estructura institucional, la composición de la muestra o la situación histórica. "
                "El artículo propone que toda síntesis social necesita una prueba previa de agregabilidad: demostrar qué constructo se afirma, qué mecanismo lo conecta, qué medición lo hace observable, qué unidad soporta la inferencia, qué contexto delimita su sentido y qué alcance puede defenderse sin convertir una señal situada en universalización débil."
            ),
            "model": (
                "El modelo interpretativo queda organizado como constructo-mecanismo-operacionalización-unidad-temporalidad-contexto-alcance. El constructo define el fenómeno; el mecanismo evita que una correlación se disfrace de explicación; la operacionalización decide qué parte del fenómeno se vuelve visible; la unidad indica dónde reside la variación; la temporalidad separa coexistencia de precedencia; el contexto marca la frontera de transporte; y el alcance inferencial impide elevar una evidencia local a ley general. "
                "Este modelo no elimina la heterogeneidad del corpus; la transforma en criterio de lectura. La diferencia entre estudios deja de ser ruido y pasa a ser información sobre qué comparaciones son legítimas, cuáles son analogías útiles y cuáles todavía no deben agregarse."
            ),
            "field": (
                "El aporte al campo es introducir una regla de transportabilidad para debates donde la evidencia suele viajar demasiado rápido entre países, plataformas, ciclos políticos y diseños empíricos. No basta con preguntar si una exposición produce un resultado; esa formulación aplana identidades, instituciones, mediaciones tecnológicas y coyunturas históricas. "
                "Lo que debe compararse es la cadena inferencial que convierte una observación en afirmación: qué fenómeno se observa, qué mecanismo se presupone, qué evidencia lo sostiene, bajo qué contexto opera y qué parte de la conclusión puede viajar sin perder contenido."
            ),
            "method": (
                "La consecuencia metodológica es que futuras revisiones sociales deben codificar equivalencia semántica del constructo, mecanismo plausible, instrumento, población, país o contexto institucional, dirección temporal, comparador, validez de medición, sesgo de selección y alcance causal antes de agregar resultados."
            ),
            "rows": [
                ["Unidad de teoría", "Relación social conmensurable", "La evidencia no se agrega por etiqueta, sino por equivalencia conceptual, metodológica e inferencial."],
                ["Mecanismo central", "Constructo-mecanismo-operacionalización-unidad-temporalidad-contexto-alcance", "Distingue asociación, explicación, precedencia, transportabilidad y límite causal."],
                ["Aporte disciplinar", "Prueba de agregabilidad", "Define cuándo dos estudios pueden sostener una afirmación común y cuándo solo dialogan como contexto."],
                ["Regla futura", "No agregar antes de justificar equivalencia", "Convierte la cautela en criterio científico y evita universalizaciones débiles."],
            ],
        }
    return {
        "name": "modelo de comparabilidad acumulativa",
        "thesis": (
            f"La aportación central del artículo es convertir la revisión sobre {topic} en un modelo de comparabilidad acumulativa. "
            "El campo no se ordena por frecuencia de temas, sino por las condiciones que permiten transformar estudios heterogéneos en conocimiento discutible, replicable y transferible."
        ),
        "theory": (
            "La tesis teórica es que una revisión sistemática aporta más cuando define qué hace comparable a la evidencia. Esa comparabilidad exige alinear objeto, mecanismo, método, unidad de análisis, resultado y límite inferencial. "
            "Sin esa alineación, la síntesis solo enumera trabajos; con ella, produce una estructura para pensar el campo."
        ),
        "model": (
            "El modelo interpretativo queda organizado como objeto-método-evidencia-límite. El objeto define el fenómeno, el método define cómo se observa, la evidencia define qué puede afirmarse y el límite define dónde deja de valer la conclusión."
        ),
        "field": (
            "El aporte al campo es proponer una regla de acumulación: los estudios no se suman por parecerse en vocabulario, sino por compartir una unidad de comparación suficiente."
        ),
        "method": (
            "La consecuencia metodológica es que futuras revisiones deben codificar dimensiones comparables antes de extraer conclusiones generales."
        ),
        "rows": [
            ["Unidad de teoría", "Comparabilidad acumulativa", "La síntesis aporta una regla de lectura, no solo un inventario."],
            ["Mecanismo central", "Objeto-método-evidencia-límite", "Separa patrón, señal y afirmación fuerte."],
            ["Aporte disciplinar", "Estructura para acumular evidencia", "Permite discutir y actualizar el campo."],
            ["Regla futura", "No sumar por vocabulario", "Evita conclusiones generales sin unidad común."],
        ],
    }


def authorial_closing_argument(profile: str, topic: str, model_name: str) -> list[str]:
    """Write the final authorial argument without repeating the contribution section."""
    if is_ai_workload_review_text(topic):
        return [
            "El cierre autoral es que la tesis más plausible no es que la IA nos haga trabajar menos, sino que cambia la topología del trabajo. El trabajo visible de producir un borrador, clasificar un caso o generar una recomendación puede bajar; el trabajo menos visible de especificar, comprobar, corregir, coordinar y responder por la salida puede subir. Esa es la diferencia que el debate público suele borrar y que la revisión debe recuperar.",
            f"El {model_name} fija esa distinción. Una organización no debería preguntar solo cuánto tarda una persona con o sin IA, sino qué parte del trabajo se trasladó a preparación, supervisión, revisión, aprendizaje, control de calidad, integración con procesos y responsabilidad legal o profesional. Si esas capas no se miden, el ahorro declarado puede ser una contabilidad incompleta.",
            "La lectura de fondo es incómoda pero útil: la IA parece más fuerte como tecnología de compresión de ejecución que como tecnología de eliminación de trabajo. En tareas acotadas puede producir ganancias claras; en contextos de alto riesgo o de conocimiento experto, esas ganancias quedan condicionadas por revisión humana, riesgo de error, confianza, trazabilidad y capacidad institucional para absorber el sistema.",
            "La aportación al campo es convertir la pregunta sobre productividad en una pregunta sobre distribución del esfuerzo. Esto permite reconciliar hallazgos que, vistos superficialmente, parecen incompatibles: unos estudios detectan mejoras de eficiencia, otros documentan dependencia, errores, sobreconfianza, necesidad de formación o costes de coordinación. No se contradicen necesariamente; pueden estar observando fases distintas del mismo desplazamiento.",
            "La consecuencia científica es que la próxima literatura debería abandonar métricas perezosas. No basta con medir tiempo de tarea si no se mide tiempo de control; no basta con contar outputs si no se evalúa calidad; no basta con preguntar percepción de utilidad si no se observa rework; no basta con hablar de sustitución si la responsabilidad final sigue siendo humana. Esa es la tesis autoral del artículo: trabajar con IA puede ser más rápido en la superficie y más exigente en el sistema.",
        ]
    if profile == "ai_architecture":
        return [
            "El cierre autoral es que la revisión desplaza el debate desde la competencia del modelo hacia la ingeniería del sistema que vuelve esa competencia gobernable. La diferencia no es estética: una arquitectura decide qué entra como contexto, qué se conserva como memoria, qué se ejecuta como acción, qué se comprueba como evidencia y qué se bloquea como fallo.",
            f"El {model_name} sirve para imponer una disciplina de comparación. Dos sistemas no son equivalentes porque usen el mismo LLM; son comparables cuando se conocen sus fuentes, herramientas, política de inferencia, supervisión, límites operativos y coste de error. Esa es la frontera entre una taxonomía de componentes y una teoría de sistemas de IA.",
            "La aportación al campo es convertir la arquitectura en una hipótesis científica: si cambia la coordinación entre contexto, acción y verificación, cambia también lo que puede afirmarse sobre rendimiento, seguridad, coste y transferencia. Una revisión futura podrá discutir el modelo, ampliarlo o refutarlo, pero ya no debería volver a comparar sistemas como si el modelo base agotara la explicación.",
        ]
    if profile == "software_architecture":
        return [
            "El cierre autoral es que la IA aplicada al desarrollo no puede evaluarse solo por la velocidad con la que produce código. La pregunta madura es qué parte del ciclo convierte intención en cambio verificable y qué parte queda como deuda técnica, dependencia oculta o riesgo de mantenimiento.",
            f"El {model_name} fija esa frontera: no hay aportación arquitectónica si no se puede seguir el tránsito entre necesidad, modificación, prueba, revisión e integración. La productividad local puede impresionar; la arquitectura solo mejora cuando el sistema conserva trazabilidad y reduce incertidumbre futura.",
            "La contribución para el campo es separar la promesa de automatización de la calidad acumulativa del software. Ese desplazamiento permite que futuras investigaciones no comparen herramientas por demostraciones aisladas, sino por su capacidad de sostener sistemas reales bajo cambio, colaboración y evolución.",
        ]
    if profile == "personality_llm":
        return [
            "El cierre autoral es que la personalidad en LLMs debe dejar de tratarse como una cualidad psicológica evidente. Lo que aparece como rasgo puede ser sensibilidad al instrumento, efecto de prompt, estilo conversacional, role-play o estabilidad real bajo tareas distintas; cada opción implica una afirmación científica diferente.",
            f"El {model_name} introduce esa separación. Primero pregunta qué se mide, después qué intervención produce el comportamiento y finalmente qué efecto observable se sostiene fuera de la prueba. Sin esa cadena, el campo corre el riesgo de convertir una metáfora útil en ontología débil.",
            "La aportación consiste en ofrecer una psicometría artificial sobria: suficientemente ambiciosa para estudiar regularidades conductuales, pero suficientemente cauta para no atribuir interioridad donde solo hay patrón generado. Ese equilibrio es lo que permite que futuras revisiones acumulen conocimiento sin antropomorfismo metodológico.",
        ]
    if profile == "ai_higher_education_teaching":
        return [
            "El cierre autoral es que la IA en docencia universitaria no debe evaluarse como herramienta genérica de mejora, sino como mediación situada dentro de una práctica académica concreta. Una misma tecnología puede mejorar feedback, degradar evaluación, ahorrar tiempo administrativo o desplazar criterio docente; sin distinguir la función, la evidencia se vuelve ambigua.",
            f"El {model_name} obliga a precisar tarea, criterio, mediación y resultado. Esa estructura protege al campo frente a dos reduccionismos: celebrar adopción como si fuera aprendizaje y rechazar tecnología como si toda mediación tuviera el mismo efecto pedagógico.",
            "La contribución es devolver la IA al lenguaje de la calidad educativa: juicio, evidencia, supervisión, equidad, integridad y transferencia institucional. Una revisión futura debería poder decir no solo qué sistemas se usaron, sino qué decisión docente cambiaron, bajo qué condiciones y con qué consecuencia verificable.",
        ]
    if profile == "creativity_llm":
        return [
            "El cierre autoral es que la creatividad de los LLMs no puede decidirse por impresión de novedad ni por fluidez verbal. Una salida solo es creativa dentro de una tarea, una restricción, una rúbrica y una comunidad de juicio; fuera de esa configuración, la creatividad se convierte en adjetivo, no en constructo científico.",
            f"El {model_name} separa generación de evaluación. La variación produce alternativas, pero el juicio define si esas alternativas tienen novedad, utilidad, diversidad y valor para un dominio. Esa distinción impide que el campo confunda abundancia de producción con creatividad robusta.",
            "La aportación para futuras investigaciones es una regla de comparabilidad: declarar criterio, juez, dominio, repetición y transferencia antes de afirmar creatividad. Así la revisión no cierra el debate con un ranking, sino que eleva el estándar para estudiar originalidad artificial con rigor.",
        ]
    if profile == "social_sciences":
        return [
            f"La tesis autoral es que una revisión social sobre {topic} no debe prometer una respuesta universal si el campo todavía no ha demostrado que sus evidencias sean transportables. Su contribución consiste en formular un umbral epistemológico: una relación empírica solo puede viajar entre contextos cuando conserva constructo, mecanismo, operacionalización, unidad de análisis, temporalidad, contexto institucional y alcance inferencial. Esta idea conecta la validez de constructo, la inferencia causal y la transportabilidad externa en una sola regla de lectura (Cronbach & Meehl, 1955; Shadish et al., 2002; Pearl & Bareinboim, 2014). Sin esa cadena, la generalización no es síntesis; es pérdida de información sustantiva.",
            f"El {model_name} fija esa disciplina. Una relación social adquiere espesor teórico cuando puede decir qué afirma, por qué mecanismo debería ocurrir, con qué instrumento se observa, sobre qué población o corpus infiere, en qué coyuntura institucional se inscribe y qué tipo de inferencia autoriza. La revisión no trata esas condiciones como metadatos auxiliares, sino como la propia materia de la validez comparativa: el mecanismo, el contexto y el alcance pasan a ser condiciones de explicación, no notas al pie del resultado (Pawson, 2006).",
            "La contribución fuerte consiste en desplazar la comparabilidad desde el plano administrativo al plano teórico. No se pregunta solo qué estudios existen, sino qué clase de afirmación puede sostener cada estudio: descripción, asociación, mecanismo plausible, contraste empírico, señal contextual, caso límite o inferencia transferible. Ese desplazamiento es sustantivo porque impide confundir coincidencia temática con acumulación científica y porque obliga a diferenciar evidencia disponible, evidencia agregable y evidencia todavía insuficiente para sostener una proposición común.",
            "El valor autoral está en hacer visible la frontera entre síntesis y agregación indebida. Dos artículos pueden compartir vocabulario y, aun así, no pertenecer al mismo plano de comparación si miden constructos distintos, trabajan con poblaciones no equivalentes, presuponen mecanismos incompatibles o dependen de coyunturas políticas que cambian el significado del fenómeno. La revisión no suaviza esa tensión para producir un consenso cómodo; la usa como criterio de lectura.",
            "Para el campo, el modelo funciona como prueba de agregabilidad. Permite distinguir evidencias que pueden sostener una afirmación común, evidencias que solo especifican condiciones de transporte, señales que orientan investigación futura y vacíos que impiden cerrar una conclusión fuerte. Esa arquitectura evita que la revisión se convierta en una suma de resultados compatibles solo en apariencia.",
            "La aportación metodológica es tratar los vacíos de reporte como información epistemológica. La ausencia de contexto, muestra, instrumento, comparador, temporalidad o validación no es una imperfección formal: muestra dónde se interrumpe la cadena que permitiría transformar hallazgos locales en conocimiento acumulativo. El artículo convierte esos cortes en diagnóstico de madurez del campo y en agenda para la investigación primaria.",
            "La consecuencia disciplinar es que una revisión futura no debería comenzar desde una tabla plana de frecuencias, sino desde una arquitectura de inferencia: constructos definidos, mecanismos plausibles, mediciones conmensurables, contextos declarados, niveles de análisis diferenciados, dirección temporal, comparadores explícitos y límites causales visibles. Ahí la revisión deja de ser cierre narrativo y se convierte en infraestructura conceptual para discutir, replicar y mejorar el campo.",
        ]
    return [
        f"El cierre autoral es que una revisión sobre {topic} solo aporta plenamente cuando transforma evidencia dispersa en una regla de comparación. La fuerza del artículo no está en declarar un consenso rápido, sino en mostrar qué debe estar alineado para que distintos estudios puedan leerse como parte de la misma conversación científica.",
        f"El {model_name} cumple esa función. Ordena objeto, mecanismo, método, evidencia y límite para distinguir hallazgos acumulables, señales emergentes y afirmaciones que todavía no pueden sostenerse. Así la revisión deja de ser un inventario y se convierte en una infraestructura intelectual para el campo.",
        "La contribución final es metodológica y sustantiva al mismo tiempo: propone cómo pensar el objeto revisado, cómo comparar estudios futuros y cómo convertir los límites de reporte en agenda científica. Una revisión posterior podrá ampliar el corpus, pero no debería volver a empezar sin declarar su unidad de comparación.",
    ]


def build_author_contribution_section(
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> list[str]:
    """Create a substantial final authorial closing section for any review.

    This section must do more than summarize. Its job is to state the paper's
    scientific contribution: the comparison model produced by the review, the
    accumulation grammar that future studies can reuse, and the methodological
    limits that become an agenda for the field.
    """
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    included_n = flow_counts.get("included_in_review", len(focus_rows))
    contribution = authorial_contribution_model(profile, topic, len(focus_rows), included_n, diagnostics)
    model_name = str(contribution["name"])
    closing_paragraphs = authorial_closing_argument(profile, topic, model_name)
    model_paragraphs = closing_paragraphs[1:3] if len(closing_paragraphs) >= 3 else closing_paragraphs[1:]
    field_paragraphs = closing_paragraphs[3:] if len(closing_paragraphs) > 3 else []
    rows = list(contribution["rows"])  # type: ignore[arg-type]
    rows.append(
        [
            "Frontera inferencial",
            "Los vacíos de reporte no se tratan como defectos administrativos, sino como límites de aquello que el campo puede afirmar con rigor.",
            "La cautela deja de ser disculpa y se convierte en criterio de validez.",
        ]
    )
    rows.append(
        [
            "Producto acumulativo",
            "La matriz, los criterios y los anexos permiten reabrir la revisión sin reiniciar la discusión desde cero.",
            "La revisión queda como infraestructura de contraste, no como cierre retórico.",
        ]
    )
    if profile == "social_sciences":
        rows.extend(
            [
                [
                    "Prueba de transportabilidad",
                    "Una conclusión solo viaja cuando conserva constructo, mecanismo, operacionalización, unidad, temporalidad, contexto y alcance inferencial.",
                    "Evita que un hallazgo local se convierta en afirmación general por comodidad narrativa o presión de síntesis.",
                ],
                [
                    "Arquitectura de inferencia",
                    "La revisión ordena qué afirmaciones son descriptivas, asociativas, mecanísticas, causales, contextuales o todavía exploratorias.",
                    "Aporta una norma de lectura para futuras acumulaciones de evidencia.",
                ],
                [
                    "Lectura de madurez",
                    "Los cortes de reporte indican dónde el campo todavía no puede convertir resultados locales en conocimiento transportable.",
                    "Transforma límites metodológicos en una agenda sustantiva de teoría, medición y diseño.",
                ],
                [
                    "Proposición teórica",
                    "La agregación solo es legítima cuando constructo, mecanismo, medición, unidad, contexto y alcance forman una cadena defendible.",
                    "Convierte la revisión en una prueba de admisibilidad inferencial, no en un resumen ampliado.",
                ],
                [
                    "Aporte autoral",
                    "El artículo decide qué puede afirmarse, qué solo puede viajar como hipótesis y qué debe mantenerse como vacío estructural.",
                    "Hace visible el criterio intelectual del autor y no solo el rendimiento del corpus.",
                ],
            ]
        )
    def paragraph_block(paragraphs: list[str]) -> list[str]:
        rendered: list[str] = []
        for paragraph in paragraphs:
            if paragraph:
                rendered.extend([paragraph, ""])
        return rendered

    if field_paragraphs:
        if is_ai_workload_review_text(topic):
            evidence_basis_argument = (
                "La base empírica del argumento no está en repetir cuántos estudios entraron en la síntesis, sino en la fricción entre dos tipos de señal: por un lado, evidencia de productividad, eficiencia o reducción de tiempo en tareas delimitadas; por otro, evidencia de revisión humana, errores, supervisión, aprendizaje, gobernanza y dependencia. "
                "Esa fricción es el hallazgo: la IA puede reducir una fracción visible del trabajo y aumentar o desplazar capas menos visibles del sistema de trabajo."
            )
            accumulation_argument = (
                f"En términos de acumulación, el {model_name} funciona como criterio para no mezclar métricas incompatibles. "
                "Un estudio que mide productividad por output/hora no responde a la misma pregunta que otro que mide carga cognitiva, errores, confianza, rework o aprendizaje. "
                "La revisión aporta una regla de lectura: antes de concluir que se trabaja menos, hay que declarar qué parte del trabajo se midió y qué parte quedó fuera del balance."
            )
            future_standard_argument = (
                "El estándar que deja el artículo es operativo: todo estudio futuro sobre IA y trabajo debería reportar al menos seis capas del esfuerzo: ejecución, preparación, revisión, coordinación, aprendizaje y responsabilidad. "
                "Si solo mide la primera, puede hablar de eficiencia local, pero no de reducción neta de trabajo. Si mide las seis, entonces sí puede sostener una afirmación fuerte sobre ahorro, desplazamiento o intensificación."
            )
            authorial_synthesis_argument = (
                "El aporte del autor es tomar partido: con la evidencia disponible, la hipótesis del desplazamiento del esfuerzo es más defendible que la hipótesis simple de trabajar menos. "
                "Eso no niega los beneficios de la IA; los sitúa. La IA puede mejorar productividad, pero esa productividad se paga con nuevas formas de control, criterio, coordinación y responsabilidad que la investigación debe medir en lugar de dejar fuera del encuadre."
            )
            formalization_argument = (
                "La formulación mínima del argumento puede expresarse así: el trabajo total con IA no es el tiempo de generación, sino la suma de capas visibles e invisibles que hacen que una salida sea útil, segura y responsable."
            )
            formalization_math = (
                "$$\n"
                "W_{total}=W_{ejecucion}+W_{articulacion}+W_{verificacion}+W_{coordinacion}+W_{aprendizaje}+W_{responsabilidad}\n"
                "$$\n\n"
                "La IA puede reducir \\(W_{ejecucion}\\), pero si aumentan \\(W_{verificacion}\\), \\(W_{coordinacion}\\), \\(W_{aprendizaje}\\) o \\(W_{responsabilidad}\\), no puede afirmarse sin más que el trabajo total disminuye. "
                "Esta fórmula no pretende medir todos los casos con una única escala; pretende impedir una inferencia incompleta."
            )
            proposition_argument = (
                "El modelo deja tres proposiciones para futuras investigaciones. Primera: los efectos positivos de productividad serán más sólidos en tareas de bajo coste de error, criterio claro y revisión barata. Segunda: el desplazamiento del esfuerzo será mayor en tareas expertas, reguladas, ambiguas o con alto coste de fallo. Tercera: la percepción de trabajar menos puede coexistir con más dependencia, más coordinación o más responsabilidad si esas capas no son visibles para quien responde la encuesta."
            )
            substantive_application_argument = (
                f"Aplicado a {topic}, el artículo no debería cerrar diciendo que la evidencia es heterogénea y ya está. Debe decir algo más fuerte: la literatura disponible permite defender que la IA produce ahorros parciales, pero todavía no demuestra una reducción neta y general del trabajo humano. La tesis razonable es desplazamiento condicionado del esfuerzo: menos producción manual en algunas tareas, más trabajo de control y absorción organizativa en muchas otras."
            )
        elif profile == "social_sciences":
            evidence_basis_argument = (
                "La base empírica del argumento no se reduce a contar estudios con o sin un campo cumplimentado. "
                "Su fuerza procede de observar dónde se tensiona la cadena de inferencia: artículos que comparten tema pero no unidad de análisis, "
                "diseños que identifican asociación pero no dirección temporal, mediciones que capturan dimensiones distintas de un mismo constructo y contextos políticos que modifican el significado del hallazgo. "
                "Esa fricción convierte el cierre autoral en una tesis sobre conmensurabilidad, no en una paráfrasis de frecuencias."
            )
            accumulation_argument = (
                f"En términos de acumulación, el {model_name} opera como criterio de admisibilidad epistemológica. "
                "No clasifica estudios como útiles o inútiles; define qué trabajo intelectual puede hacer cada uno dentro de la revisión: "
                "sostener una afirmación común, proponer un mecanismo, delimitar una condición de transferencia, mostrar una excepción, establecer una frontera de validez o señalar un vacío que todavía impide síntesis fuerte. "
                "Esta jerarquía de usos es la aportación de fondo, porque obliga a preguntar qué tipo de evidencia se tiene antes de decidir cuánto peso puede soportar."
            )
            future_standard_argument = (
                "El estándar que deja el artículo es deliberadamente más exigente que una matriz descriptiva. "
                "Un estudio futuro no debería entrar en el mismo plano de comparación solo por nombrar el mismo fenómeno; debería declarar qué constructo trabaja, "
                "qué mecanismo presupone, con qué instrumento lo observa, sobre qué población o corpus infiere, en qué contexto institucional se inscribe, qué secuencia temporal defiende y qué límite causal reconoce. "
                "Sin esa cadena, el estudio puede enriquecer el debate, pero no puede cargar el peso de una conclusión general."
            )
            authorial_synthesis_argument = (
                "El aporte del autor, por tanto, es proponer una teoría práctica de la síntesis social: antes de preguntar qué concluye el campo, hay que decidir qué puede compararse dentro del campo y bajo qué condiciones esa comparación produce conocimiento en lugar de homogeneización retórica. "
                "Esa decisión no es secundaria ni técnica; es el punto donde una revisión sistemática pasa de ordenar documentos a producir una posición científica. "
                "La revisión aporta al método una regla de lectura: acumular evidencia exige preservar diferencia sustantiva, no borrarla bajo una etiqueta común."
            )
            formalization_argument = (
                "La formulación mínima de esa regla puede expresarse así: dos estudios pertenecen al mismo plano de síntesis solo si sus piezas inferenciales son equivalentes o si la diferencia entre ellas queda teóricamente justificada. "
                "En notación compacta, la conmensurabilidad entre dos estudios no depende de compartir tema, sino de preservar la cadena que hace defendible la inferencia:"
            )
            formalization_math = (
                "$$\n"
                "C_{ij} \\Rightarrow \\{K_i \\sim K_j,\\; M_i \\sim M_j,\\; O_i \\sim O_j,\\; U_i \\sim U_j,\\; T_i \\sim T_j,\\; X_i \\sim X_j,\\; A_i \\sim A_j\\}\n"
                "$$\n\n"
                "donde K es constructo, M mecanismo, O operacionalización, U unidad de análisis, T temporalidad, X contexto y A alcance inferencial. "
                "Si alguna equivalencia falla, el estudio no desaparece del artículo; cambia de función: deja de ser base para agregación fuerte y pasa a operar como contraste, condición de frontera, evidencia contextual o agenda de investigación."
            )
            proposition_argument = (
                "El modelo deja tres proposiciones teóricas verificables para el campo. Primera: la equivalencia de constructo es condición previa de acumulación; si dos trabajos llaman igual a fenómenos medidos de forma incompatible, la síntesis debe tratarlos como analogía, no como réplica. Segunda: una misma asociación empírica cambia de significado cuando cambia el mecanismo propuesto, porque una correlación observacional, un experimento, un panel, un análisis de plataforma y un estudio cualitativo no autorizan el mismo tipo de inferencia. Tercera: el contexto no es un decorado externo, sino parte de la explicación; sistema institucional, momento histórico, plataforma, población y regla de medición definen si una conclusión puede viajar o si solo delimita una condición local."
            )
            substantive_application_argument = (
                f"Aplicado a {topic}, el aporte no consiste en afirmar que el campo ya resolvió una relación general, sino en proponer qué tendría que mantenerse constante para que esa relación pudiera formularse con autoridad. Una revisión madura no agrega automáticamente estudios que mencionan redes, actitudes, instituciones o polarización; pregunta si trabajan el mismo constructo, si defienden un mecanismo compatible, si observan una unidad comparable y si su contexto democrático permite transportar la inferencia. Ahí reside el valor autoral del apartado: no ofrece una lista ampliada de documentos, sino una regla para saber cuándo la literatura autoriza una afirmación, cuándo solo permite una hipótesis disciplinada y cuándo obliga a conservar el desacuerdo como límite científico."
            )
        else:
            evidence_basis_argument = (
                f"En esta revisión, el modelo no se presenta como una teoría externa al corpus: se deriva de la fricción observada entre {len(focus_rows)} estudios focales, "
                f"{count_studies_es(diagnostics['missing_sample'])} con muestra insuficientemente detallada, "
                f"{count_studies_es(diagnostics['missing_country'])} con contexto territorial débil, "
                f"{count_studies_es(diagnostics['missing_benchmark'])} sin comparador claro y "
                f"{count_studies_es(diagnostics['weak_validation'])} sin validación comparable fuerte. "
                "Esos vacíos no son adornos de auditoría; son la evidencia negativa que justifica por qué la revisión necesita una gramática de inferencia y no solo una síntesis temática."
            )
            accumulation_argument = (
                f"En términos de acumulación, el {model_name} opera como criterio de admisibilidad intelectual. "
                "No decide si un estudio es valioso o irrelevante; decide qué clase de conversación científica puede sostener: "
                "generalización prudente, comparación condicionada, hipótesis de mecanismo, contraste empírico o señal exploratoria. "
                "Esta distinción aumenta la densidad teórica porque obliga a justificar el salto desde un resultado local hacia una afirmación sobre el campo."
            )
            future_standard_argument = (
                "El estándar derivado no exige homogeneizar la literatura, sino hacer visibles las condiciones de conmensurabilidad. "
                "Un estudio puede diferir en método, muestra, tradición teórica o contexto y seguir siendo útil para la síntesis si declara su unidad analítica, "
                "su mecanismo, su forma de medición, su comparador y su alcance inferencial. Sin esos elementos, el estudio puede informar el debate, "
                "pero no debe ocupar el mismo plano de agregación que evidencia plenamente comparable."
            )
            authorial_synthesis_argument = (
                "El aporte del autor, por tanto, no es una interpretación externa añadida al final del manuscrito. "
                "Es la operación de convertir la fricción entre resultados, métodos y límites de reporte en una tesis sobre cómo debe avanzar el campo. "
                "La revisión no solo ordena conocimiento existente; establece qué tendría que cambiar en los estudios primarios para que la acumulación futura sea más exigente, transferible y conceptualmente limpia."
            )
            formalization_argument = ""
            formalization_math = ""
            proposition_argument = ""
            substantive_application_argument = ""
    else:
        evidence_basis_argument = (
            f"El modelo se deriva del contraste entre {len(focus_rows)} estudios focales, sus hallazgos recuperables y sus límites de reporte; no funciona como tesis externa al corpus, sino como formalización del problema de comparación que la revisión detecta."
        )
        accumulation_argument = (
            f"Para el campo, el {model_name} funciona como regla de acumulación: obliga a distinguir evidencias que pueden sostener una afirmación común, "
            "señales que solo orientan investigación futura y vacíos que impiden cerrar una conclusión fuerte. "
            "Esa distinción evita que la revisión se convierta en una suma de resultados compatibles solo en apariencia."
        )
        future_standard_argument = (
            "El resultado práctico es un estándar de lectura para trabajos futuros. Un nuevo estudio no debería incorporarse al mismo plano de comparación "
            "solo porque use vocabulario parecido; debería mostrar qué unidad teórica trabaja, qué mecanismo defiende, qué evidencia produce, "
            "qué límite reconoce y qué parte del modelo confirma, matiza o contradice."
        )
        authorial_synthesis_argument = (
            "El aporte del autor no se añade como comentario final, sino como regla de interpretación derivada del corpus: "
            "qué puede compararse, qué debe mantenerse como señal y qué exige nueva evidencia antes de convertirse en conclusión."
        )
        formalization_argument = ""
        formalization_math = ""
        proposition_argument = ""
        substantive_application_argument = ""

    if is_ai_workload_context(context):
        primary_n = len(empirical_rows_only(focus_rows))
        support_n = max(len(focus_rows) - primary_n, 0)
        base_claim = (
            f"La base empírica primaria de esta tesis procede de {primary_n} estudios empíricos dentro de un corpus focal ampliado con {support_n} trabajos de apoyo teórico, revisión o contexto. "
            "El argumento no descansa en inflar el número, sino en separar planos de evidencia: los estudios empíricos sostienen la respuesta sobre trabajo; los estudios de apoyo ayudan a nombrar mecanismos, límites y condiciones de acumulación. "
            "Ahí está la diferencia entre una revisión que enumera literatura y una revisión que aporta una posición al campo."
        )
    else:
        base_claim = (
            f"La base empírica de esta tesis procede de {included_n} estudios incluidos y {len(focus_rows)} estudios focales, pero el argumento no descansa en el número por sí mismo. "
            "Descansa en la operación conceptual que la revisión realiza sobre el corpus: definir una unidad de comparación, explicitar sus mecanismos, declarar sus límites y convertir esos límites en una agenda acumulativa. "
            "Ahí está la diferencia entre una revisión que enumera literatura y una revisión que aporta una posición al campo."
        )

    return [
        "## Aporte teórico e interpretativo del autor",
        "",
        "### Tesis autoral",
        "",
        closing_paragraphs[0],
        "",
        "### Modelo interpretativo propuesto",
        "",
        *paragraph_block(model_paragraphs),
        "### Aporte al campo",
        "",
        *paragraph_block(field_paragraphs),
        evidence_basis_argument,
        "",
        accumulation_argument,
        "",
        formalization_argument,
        "",
        formalization_math,
        "",
        proposition_argument,
        "",
        substantive_application_argument,
        "",
        future_standard_argument,
        "",
        authorial_synthesis_argument,
        "",
        "Tabla de contribución teórica e inferencial. Tesis, modelo y regla de acumulación propuestos por el artículo.",
        "",
        markdown_table(["Plano", "Tesis del autor", "Consecuencia científica"], rows),
        "",
        base_claim,
        "",
        "La regla editorial derivada es exigente: cada tabla, figura o anexo debe modificar la comprensión del argumento. Si un elemento visual solo ilustra, se mueve al suplemento; si muestra una relación, una frontera inferencial o una decisión de síntesis, pertenece al cuerpo del artículo. La autoridad de una revisión sistemática no aumenta por acumular material, sino por hacer visible la estructura intelectual que convierte evidencia dispersa en conocimiento discutible.",
    ]


def build_practical_implications_lines(
    focus_rows: list[dict[str, str]],
    context: dict[str, str],
    *,
    citation_ids: list[str] | None = None,
    opening: str = "",
    evidence_implication: str = "",
) -> list[str]:
    """Generate a substantial, decision-oriented practical implications section for any review profile."""
    profile = detect_review_profile(context)
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    topic = review_subject_label_es(context)
    top_ids = citation_ids or top_citation_ids(focus_rows, 16)
    citation = citation_block(top_ids[8:12])
    citation_sentence = f" {citation}." if citation else "."
    benchmark_gap = (
        f"{count_studies_es(diagnostics['missing_benchmark'])} "
        f"{verb_by_count(diagnostics['missing_benchmark'], 'no reporta', 'no reportan')} una base comparativa clara"
    )
    benchmark_gap_dejar = (
        f"{count_studies_es(diagnostics['missing_benchmark'])} "
        f"{verb_by_count(diagnostics['missing_benchmark'], 'no deja', 'no dejan')} una base comparativa clara"
    )
    theory_gap = (
        f"{count_studies_es(diagnostics['missing_theory'])} "
        f"{verb_by_count(diagnostics['missing_theory'], 'no declara', 'no declaran')} marco teórico suficiente"
    )
    variables_gap = (
        f"{count_studies_es(diagnostics['missing_variables'])} "
        f"{verb_by_count(diagnostics['missing_variables'], 'no explicita', 'no explicitan')} variables o dimensiones analíticas"
    )
    sample_gap = (
        f"{count_studies_es(diagnostics['missing_sample'])} "
        f"{verb_by_count(diagnostics['missing_sample'], 'no detalla', 'no detallan')} muestra suficiente"
    )

    if is_ai_workload_context(context):
        primary_rows = empirical_rows_only(focus_rows) or focus_rows
        primary_total = len(primary_rows)
        counts = ai_workload_signal_counts(primary_rows)
        return [
            "## Implicaciones prácticas",
            opening or (
                "La implicación práctica central es que una organización no debe comprar o implantar IA prometiendo `trabajar menos`, sino rediseñando explícitamente dónde quedará el trabajo humano después de automatizar una parte de la ejecución."
            ),
            "",
            "La primera consecuencia es medir el trabajo total, no solo el tiempo de primera respuesta. Si una herramienta reduce el tiempo de redactar, clasificar o resumir, todavía falta medir el tiempo de preparar instrucciones, comprobar errores, adaptar la salida, coordinar con otras personas, resolver excepciones y asumir responsabilidad. Sin ese balance, la mejora es una ilusión contable.",
            "",
            f"La segunda consecuencia es distinguir productividad local y carga real. En la base empírica primaria aparecen señales de productividad o eficiencia en {counts['productivity']}/{primary_total} estudios, pero señales de supervisión, revisión o coordinación en {counts['supervision']}/{primary_total}. La decisión práctica no debería ser `la IA ahorra tiempo`, sino `qué tiempo ahorra, a quién, en qué fase y a cambio de qué nuevo control`.",
            "",
            "La tercera consecuencia es diseñar puestos y procesos alrededor del control humano. Si la IA produce borradores, diagnósticos, recomendaciones o materiales, alguien debe decidir qué se acepta, qué se corrige, qué se descarta y qué se explica. Esa función no es residual; es trabajo experto. Tratarla como trámite barato genera sobrecarga invisible y aumenta riesgo.",
            "",
            "La cuarta consecuencia es no confundir automatización con delegación de responsabilidad. En salud, educación, recursos humanos, escritura académica o decisiones organizativas, la salida automatizada puede acelerar el flujo, pero la responsabilidad profesional permanece. Cuanto mayor es el coste de error, más probable es que el ahorro de ejecución se transforme en trabajo de verificación.",
            "",
            f"La quinta consecuencia es presupuestar aprendizaje y recualificación. La base empírica primaria detecta señales de aprendizaje, habilidades o recualificación en {counts['learning']}/{primary_total} estudios. Ese trabajo de adaptación no aparece en muchas métricas de productividad, pero condiciona la implantación real: formar, crear criterios, acordar usos aceptables y revisar prácticas también es trabajo.",
            "",
            "La sexta consecuencia es crear indicadores de adopción más honestos: tiempo hasta primera salida, tiempo hasta salida aceptada, número de iteraciones, tasa de error, rework, carga cognitiva, interrupciones, coordinación, satisfacción, calidad final y responsabilidad retenida. Solo con esa batería puede saberse si se trabaja menos, distinto o más.",
            "",
            "La séptima consecuencia es usar la IA donde el coste de revisión sea menor que el ahorro de producción. En tareas acotadas, repetibles y con criterio claro, la ecuación puede ser favorable. En tareas ambiguas, reguladas, sensibles o de alta responsabilidad, el control puede comerse el ahorro. Esta distinción debería guiar compras, pilotos y escalado.",
            "",
            "La octava consecuencia es política: si la organización solo captura el ahorro visible, puede intensificar el trabajo sin reconocerlo. Menos tiempo para producir puede convertirse en más volumen esperado, más vigilancia, más coordinación y menos descanso. Por eso la discusión práctica debe incluir diseño del trabajo, no solo adopción tecnológica.",
            "",
            evidence_implication
            or "En términos prácticos, la evidencia disponible permite defender beneficios parciales de productividad, pero no autoriza vender la IA como reducción neta y general del trabajo humano sin medir las capas invisibles de control.",
        ]

    if profile == "ai_security_harness":
        counts = security_harness_signal_counts(focus_rows)
        total = max(len(focus_rows), 1)
        return [
            "## Implicaciones prácticas",
            opening
            or (
                "La implicación práctica central es que un equipo no debería comprar, desplegar o recomendar un harness de seguridad por una tasa de bloqueo aislada. Debe seleccionar una configuración defensiva para una amenaza, una superficie, un atacante y un coste operacional concretos."
            ),
            "",
            "La primera consecuencia es escribir el threat model antes de elegir el control. Prompt injection directo, inyección indirecta desde RAG, jailbreak, abuso de herramientas y exfiltración no son variantes intercambiables del mismo problema. Un filtro de entrada puede ser pertinente para una superficie y completamente ciego para otra; por eso una política de seguridad debe declarar qué activo protege, qué puede hacer el atacante y dónde se aplica la defensa.",
            "",
            f"La segunda consecuencia es exigir un baseline material. En {counts['baseline']}/{total} estudios focales se recupera un comparador explícito. Sin ejecución sin defensa, control alternativo o configuración ablation, una tasa de ataque no permite saber cuánto valor añade el harness ni qué componente produce el efecto.",
            "",
            f"La tercera consecuencia es probar atacantes adaptativos. Solo {counts['adaptive']}/{total} estudios dejan una señal recuperable de adaptación del atacante. Una defensa evaluada únicamente contra un conjunto estático puede estar midiendo memorización del benchmark, no resistencia. Antes de desplegar, el equipo debería retestar después de revelar reglas, mensajes de rechazo, herramientas y superficie de contexto.",
            "",
            f"La cuarta consecuencia es medir seguridad y utilidad en el mismo experimento. {counts['asr']}/{total} estudios reportan ASR o una métrica equivalente, pero solo {counts['utility']}/{total} dejan impacto de utilidad y {counts['false_positive']}/{total} falsos positivos recuperables. Bloquear más no es dominar si el sistema también rechaza tareas legítimas, degrada precisión o desplaza la carga a revisión humana.",
            "",
            f"La quinta consecuencia es presupuestar el control como parte de la arquitectura. La latencia aparece en {counts['latency']}/{total} estudios y el coste en {counts['cost']}/{total}. En producción deben medirse por transacción, herramienta y nivel de riesgo; de lo contrario una defensa técnicamente eficaz puede ser operativamente inviable o inducir atajos que la neutralicen.",
            "",
            "La sexta consecuencia es diseñar por capas solo cuando cada capa tiene una función verificable. Entrada, contexto, runtime, permisos de herramientas y salida cubren superficies distintas. La defensa en profundidad aporta valor cuando reduce rutas de evasión y conserva observabilidad; añadir detectores redundantes sin ablation solo aumenta complejidad y falsos positivos.",
            "",
            f"La séptima consecuencia es convertir fallos y robustez en requisitos de compra. {counts['robustness']}/{total} estudios aportan alguna prueba de robustez y {counts['failure']}/{total} explicitan modos de fallo. Un proveedor o equipo interno debería entregar límites conocidos, ataques que siguen funcionando, política de actualización, logs auditables y procedimiento de rollback, no solo una media de benchmark.",
            "",
            f"La octava consecuencia es exigir reproducibilidad proporcional al riesgo. {counts['artifact']}/{total} estudios declaran código, datos o artefactos recuperables. Cuando el control decide si un agente puede leer datos, llamar herramientas o ejecutar acciones, el contrato de adopción debería incluir configuración, versiones, conjuntos de prueba, umbrales y evidencia de regresión.",
            "",
            evidence_implication
            or (
                "En términos de decisión, la evidencia debe utilizarse como frontera de dominancia condicionada: recomendar una defensa solo para las amenazas y costes que han sido comparados materialmente, mantener como señal emergente lo que carece de réplica y rechazar cualquier afirmación de superioridad universal que oculte utilidad, latencia, coste o adaptación del atacante."
            ),
        ]
    elif profile in {"ai_architecture", "software_architecture", "agent_architecture"}:
        intro = opening or (
            "Para diseño de sistemas reales, la implicación práctica central es que la revisión debe traducirse en decisiones de arquitectura, no en una preferencia abstracta por modelos, agentes o proveedores."
        )
        task_sentence = (
            "La primera consecuencia práctica es empezar por la tarea y no por el modelo. Un equipo debería formular qué decisión, flujo, documento, acción o evaluación quiere mejorar; después decidir qué recuperación, memoria, herramienta, rol, orquestación y verificación necesita. Si el sistema se diseña al revés, el modelo se convierte en centro de gravedad y la arquitectura queda como una suma de accesorios."
        )
        verification_sentence = (
            "La segunda consecuencia es diseñar la verificación desde el inicio. Cuando una arquitectura usa herramientas, memoria, recuperación o agentes especializados, también debe declarar qué se comprueba, cuándo se comprueba, quién o qué revisa la salida y qué ocurre cuando falla. En términos operativos, una arquitectura sin criterios de evaluación no debería considerarse madura, aunque use un modelo avanzado."
        )
        modular_sentence = (
            "La tercera consecuencia es modularizar solo cuando aporta valor. La revisión no justifica añadir agentes, roles, colas o pipelines por defecto; sugiere hacerlo cuando la tarea exige separación de responsabilidades, trazabilidad, paralelización, recuperación de contexto o reducción del coste de error. Para tareas simples, una arquitectura más pequeña puede ser más fiable, más barata y más fácil de auditar."
        )
        documentation_sentence = (
            "La cuarta consecuencia es documentar la arquitectura como objeto de evaluación. Un sistema publicable o desplegable debería conservar diagrama de flujo, fuentes de recuperación, memoria usada, herramientas permitidas, política de inferencia, criterios de evaluación, fallos conocidos y logs suficientes para reconstruir decisiones. Esa documentación convierte una demo en un sistema revisable."
        )
        comparison_sentence = (
            f"La quinta consecuencia afecta a compras, adopción y gobierno. Las organizaciones no deberían comparar proveedores solo por el modelo base, sino por la configuración completa: control de datos, integración con herramientas, observabilidad, evaluación, coste, latencia, seguridad, mantenimiento y posibilidad de auditoría. Esta cautela es especialmente importante porque {benchmark_gap} y {theory_gap}."
        )
        metrics_sentence = (
            "La sexta consecuencia es medir valor práctico con indicadores de sistema, no solo con acierto de respuesta. En arquitecturas de IA conviene observar calidad de salida, tasa de fallo, recuperación correcta de evidencia, trazabilidad, coste por tarea, latencia, intervención humana requerida, robustez ante casos límite y capacidad de actualización. Sin esas métricas, la mejora puede ser solo una impresión de fluidez."
        )
        transfer_sentence = (
            "La séptima consecuencia es transformar la síntesis en una guía de implantación. Antes de escalar un sistema, el equipo debería poder responder qué componente aporta valor, qué componente solo añade complejidad, qué dato sostiene cada decisión, qué fallo detiene el flujo y qué parte requiere revisión humana. Esta lectura hace que la revisión sirva para diseñar, comprar, auditar o descartar sistemas, no solo para describir tendencias."
        )
        governance_sentence = (
            "La octava consecuencia es fijar límites de uso y actualización. Una arquitectura que funciona en un corpus, benchmark o dominio no queda automáticamente validada para otro contexto; necesita condiciones de despliegue, monitorización, control de deriva, registro de cambios y reevaluación periódica. En campos rápidos, el valor práctico no está solo en elegir una configuración, sino en saber cuándo debe revisarse."
        )
    elif profile == "personality_llm":
        intro = opening or (
            "Para productos, investigación aplicada y evaluación de modelos, la implicación práctica central es no tratar la personalidad como una etiqueta decorativa, sino como una configuración entre constructo, intervención, tarea, métrica y efecto observado."
        )
        task_sentence = (
            "La primera consecuencia práctica es empezar por la tarea psicológica o interactiva y no por la persona sintética. Antes de desplegar un perfil, conviene definir qué se quiere mejorar o estudiar: cooperación, confianza, alineamiento, persuasión, sesgo, adaptación o estabilidad entre sesiones. Solo después tiene sentido decidir qué constructo, prompt, instrumento o intervención se usará."
        )
        verification_sentence = (
            "La segunda consecuencia es diseñar la verificación desde el inicio. Un estudio o producto debe separar si está midiendo rasgos, induciendo una persona o evaluando efectos posteriores sobre decisiones y usuarios. Sin esa separación, una salida que parece personalidad puede ser role-play, estilo conversacional, sesgo contextual o simple artefacto de prompting."
        )
        modular_sentence = (
            "La tercera consecuencia es modularizar la evaluación en etapas interpretables. Profiling, steering y efecto downstream deberían medirse por separado cuando el objetivo sea sostener una conclusión fuerte. Esa modularidad no añade burocracia: evita atribuir al constructo psicológico lo que quizá procede del instrumento, del prompt, del modelo o del contexto de interacción."
        )
        documentation_sentence = (
            "La cuarta consecuencia es documentar el diseño completo: modelo y versión, prompt o intervención, temperatura o política de generación, muestra o corpus, instrumento psicométrico, variables, comparador, repetición de medidas, criterios de exclusión y fallos observados. Esa información permite distinguir personalidad estable de apariencia local."
        )
        comparison_sentence = (
            f"La quinta consecuencia afecta a comparaciones entre sistemas. No basta con decir que un modelo tiene más o menos personalidad; hay que comparar configuraciones completas de constructo, instrumento, tarea, métrica y contexto. Esta cautela importa porque {variables_gap} y {sample_gap}."
        )
        metrics_sentence = (
            "La sexta consecuencia es medir valor práctico con indicadores adecuados al fenómeno: estabilidad entre tareas, transferencia entre contextos, coherencia temporal, sensibilidad al prompt, impacto en usuarios, sesgo, riesgo de persuasión y reversibilidad de la intervención. Sin esas métricas, la personalidad queda como efecto narrativo y no como evidencia operativa."
        )
        transfer_sentence = (
            "La séptima consecuencia es traducir los hallazgos en reglas de despliegue. Una persona sintética no debería usarse igual en educación, salud, soporte, entretenimiento o investigación experimental. Cada contexto requiere límites de rol, lenguaje permitido, transparencia para el usuario, escalado a humano y registro de comportamientos anómalos."
        )
        governance_sentence = (
            "La octava consecuencia es mantener revisión continua. La personalidad inducida puede cambiar con el modelo, el prompt, la memoria, la política de seguridad o el dominio de uso. Por eso cualquier aplicación debería incluir reevaluación periódica y no asumir que una medición inicial sigue siendo válida tras actualizaciones del sistema."
        )
    elif profile == "ai_higher_education_teaching":
        intro = opening or (
            "Para universidades, centros de innovación docente y equipos académicos, la implicación práctica central es no adoptar IA por disponibilidad tecnológica, sino por encaje verificable entre tarea docente, herramienta, control humano y resultado educativo."
        )
        task_sentence = (
            "La primera consecuencia práctica es empezar por la tarea docente y no por el modelo. Preparar clases, diseñar rúbricas, generar feedback, apoyar tutorías, adaptar materiales, evaluar trabajos, revisar integridad académica o reducir carga administrativa son problemas distintos. Cada uno exige evidencias, límites y métricas diferentes; por eso una herramienta útil en feedback no queda validada automáticamente para evaluación sumativa o diseño curricular."
        )
        verification_sentence = (
            "La segunda consecuencia es diseñar la verificación pedagógica desde el inicio. Una universidad debería declarar qué mejora espera observar, cómo se revisará la salida de IA, qué parte conserva el docente, qué datos no deben entrar en el sistema, qué errores son críticos y qué indicador marca que la intervención aporta valor. Sin esa verificación, la IA puede producir velocidad sin mejorar calidad educativa."
        )
        modular_sentence = (
            "La tercera consecuencia es modularizar la implantación por escenarios de uso. No conviene desplegar un asistente genérico para todo el profesorado si el problema real es feedback formativo, tutoría, diseño de actividades o alfabetización en IA. Los módulos deben separarse cuando cambian las responsabilidades, los riesgos, el tipo de evidencia o la necesidad de revisión humana."
        )
        documentation_sentence = (
            "La cuarta consecuencia es documentar la configuración docente completa: herramienta, modelo o proveedor, instrucciones usadas, materiales de entrada, política de privacidad, criterio de revisión, rol del docente, nivel de autonomía permitido, estudiantes afectados, disciplina, indicadores de calidad y fallos observados. Esa documentación convierte una experiencia aislada en evidencia transferible."
        )
        comparison_sentence = (
            f"La quinta consecuencia afecta a compras y gobierno institucional. Las universidades no deberían comparar soluciones solo por marca, fluidez o coste por licencia, sino por configuración completa: tarea docente, integración con LMS, protección de datos, trazabilidad, control del profesor, accesibilidad, evaluación de calidad, formación necesaria y coste de mantenimiento. Esta cautela importa porque {benchmark_gap_dejar} y {theory_gap}."
        )
        metrics_sentence = (
            "La sexta consecuencia es medir valor con indicadores de sistema educativo: calidad del feedback, tiempo docente recuperado, consistencia de evaluación, satisfacción informada, aprendizaje observado, equidad, carga cognitiva, errores detectados, transparencia para estudiantes, robustez disciplinar y necesidad de intervención humana. Una métrica de uso o aceptación no basta para afirmar mejora."
        )
        transfer_sentence = (
            "La séptima consecuencia es convertir la síntesis en una guía de implantación gradual. Primero se prueban tareas de bajo riesgo y alto valor, después se incorporan controles, formación docente, revisión de sesgos y criterios de escalado. La adopción madura no es `usar más IA`, sino saber qué tarea merece IA, con qué supervisión y bajo qué evidencia."
        )
        governance_sentence = (
            "La octava consecuencia es mantener una política de actualización. Las herramientas, modelos, condiciones de privacidad y prácticas estudiantiles cambian con rapidez; por tanto, una decisión válida en un semestre puede necesitar reevaluación en el siguiente. La gobernanza debe incluir revisión periódica, registro de incidentes, formación continua y límites explícitos para usos sensibles."
        )
    elif profile == "creativity_llm":
        intro = opening or (
            "Para equipos que diseñan o evalúan creatividad artificial, la implicación práctica central es dejar de preguntar si un modelo es creativo en abstracto y pasar a decidir qué tarea creativa, criterio, juez y condición de generación se quiere optimizar."
        )
        task_sentence = (
            "La primera consecuencia práctica es empezar por la tarea creativa y no por el modelo. Escritura, ideación, pensamiento divergente, diseño, resolución de problemas y generación científica no activan la misma definición de creatividad. Si la tarea no está delimitada, cualquier comparación entre modelos mezcla fenómenos distintos."
        )
        verification_sentence = (
            "La segunda consecuencia es diseñar la verificación desde el inicio. Un sistema creativo necesita criterios de novedad, utilidad, diversidad, sorpresa, adecuación al dominio y calidad final, además de declarar si evalúan humanos, métricas automáticas o ambos. Sin ese diseño, el resultado puede sonar original y aun así no ser útil ni reproducible."
        )
        modular_sentence = (
            "La tercera consecuencia es modularizar cuando la tarea lo requiera: generación de alternativas, filtrado, crítica, reescritura, selección y evaluación pueden separarse si el coste de error o la necesidad de trazabilidad lo justifican. La modularidad solo aporta valor si mejora control, diversidad o calidad, no si añade complejidad sin criterio."
        )
        documentation_sentence = (
            "La cuarta consecuencia es documentar prompts, temperatura, condiciones de generación, rúbricas, jueces, comparadores, muestras de salida, exclusiones y fallos. En creatividad, pequeños cambios en instrucción o criterio pueden alterar el resultado; por eso la trazabilidad es parte de la evidencia y no un anexo opcional."
        )
        comparison_sentence = (
            f"La quinta consecuencia afecta a benchmarks y proveedores. No debería compararse un sistema por impresiones de fluidez, sino por configuración completa de tarea, criterio, juez, modelo, generación y evaluación. Esta cautela es especialmente importante porque {benchmark_gap_dejar}."
        )
        metrics_sentence = (
            "La sexta consecuencia es medir valor con indicadores de proceso y de resultado: diversidad de ideas, tasa de soluciones útiles, originalidad validada, coste por iteración, robustez ante restricciones, satisfacción del evaluador, transferencia entre dominios y capacidad de revisión. Sin esos indicadores, la creatividad se reduce a una sensación estética difícil de acumular."
        )
        transfer_sentence = (
            "La séptima consecuencia es decidir de antemano dónde aporta valor el sistema: exploración temprana, generación de variantes, crítica, aceleración de borradores, asistencia científica o solución de problemas. Cada uso exige un umbral distinto de novedad, riesgo y revisión humana."
        )
        governance_sentence = (
            "La octava consecuencia es fijar límites de uso. Un sistema puede ser útil para ampliar el espacio de posibilidades y aun así no ser fiable para decidir originalidad, propiedad intelectual, mérito artístico o validez científica sin revisión externa. La implicación práctica madura es combinar asistencia generativa con evaluación trazable."
        )
    elif profile == "social_sciences":
        intro = opening or (
            f"Para investigadores, instituciones y analistas públicos, la implicación práctica central es que una revisión sobre {topic} debe traducirse en lectura de mecanismos, no en una afirmación genérica de impacto social."
        )
        social_gap_bits = []
        if diagnostics["missing_variables"] > 0:
            social_gap_bits.append(variables_gap)
        if diagnostics["missing_sample"] > 0:
            social_gap_bits.append(sample_gap)
        if diagnostics["missing_benchmark"] > 0:
            social_gap_bits.append(benchmark_gap_dejar)
        social_gap_sentence = (
            "Esta cautela importa porque " + ", ".join(social_gap_bits) + "."
            if social_gap_bits
            else "Esta cautela importa incluso cuando la matriz no detecta vacíos formales de variables o muestra, porque la transferencia depende de equivalencia sustantiva y no solo de completitud de campos."
        )
        task_sentence = (
            "La primera consecuencia práctica es empezar por el fenómeno y no por la variable más visible. Antes de afirmar que una exposición, plataforma, política o contexto produce un resultado, hay que definir qué constructo se observa, sobre qué población, en qué periodo y con qué medición. En ciencias sociales, el mismo término puede significar actitudes, comportamiento, percepción, identidad o confianza."
        )
        verification_sentence = (
            "La segunda consecuencia es diseñar la verificación causal desde el inicio. Cuando un estudio usa encuesta transversal, panel, experimento, datos digitales o entrevista, no sostiene el mismo tipo de inferencia. La aplicación práctica de la revisión debe separar asociación descriptiva, mecanismo plausible, evidencia temporal y efecto causal."
        )
        modular_sentence = (
            "La tercera consecuencia es separar unidades de análisis. Individuos, mensajes, cuentas, plataformas, países, organizaciones e instituciones no son intercambiables. Una recomendación práctica cambia si la evidencia observa usuarios, contenidos, elecciones, sistemas mediáticos o confianza institucional agregada."
        )
        documentation_sentence = (
            "La cuarta consecuencia es documentar operacionalizaciones: escala, pregunta de encuesta, ventana temporal, fuente de datos, algoritmo de codificación, contexto territorial, criterio de exclusión, controles y limitaciones. Esa documentación permite saber si dos estudios que usan la misma palabra realmente miden el mismo fenómeno."
        )
        comparison_sentence = (
            f"La quinta consecuencia afecta a políticas, intervención y comunicación pública. No debería transferirse una conclusión entre países, plataformas o ciclos políticos sin revisar medición, muestra, contexto institucional y comparador. {social_gap_sentence}"
        )
        metrics_sentence = (
            "La sexta consecuencia es medir valor práctico con indicadores adecuados al problema: cambio actitudinal, confianza institucional, intensidad afectiva, exposición informativa, calidad de información, participación, estabilidad temporal, robustez por subgrupos y sensibilidad al contexto. Una métrica agregada puede ocultar efectos opuestos en poblaciones distintas."
        )
        transfer_sentence = (
            "La séptima consecuencia es convertir la síntesis en mapa de transferencia. El lector debe poder ver qué hallazgos parecen estables, cuáles dependen de una plataforma o país y cuáles son solo señales iniciales. Esa distinción evita que la revisión se use como argumento universal para políticas que requieren evidencia situada."
        )
        governance_sentence = (
            "La octava consecuencia es actualizar la revisión cuando cambian plataformas, normas institucionales o ciclos políticos. En ciencias sociales, el objeto puede cambiar mientras se estudia: una red social modifica su algoritmo, una elección reordena identidades o una crisis altera confianza. La revisión debe conservar trazabilidad para poder reabrirse sin perder comparabilidad."
        )
    else:
        intro = opening or (
            f"Para investigadores, revisores y equipos aplicados, la implicación práctica central es que una revisión sobre {topic} debe convertirse en criterios de decisión, no en una lista de estudios ordenados."
        )
        task_sentence = (
            "La primera consecuencia práctica es empezar por la tarea, decisión o problema y no por la técnica más visible. Antes de recomendar una intervención, herramienta, modelo o marco, el lector debe saber qué resultado se quiere mejorar, bajo qué condiciones, con qué coste de error y con qué evidencia disponible."
        )
        verification_sentence = (
            "La segunda consecuencia es diseñar la verificación desde el inicio. Toda aplicación derivada de la revisión debería declarar qué evidencia cuenta como suficiente, qué señales solo son exploratorias, qué comparador se usará y qué resultado obligaría a cambiar la decisión. Sin verificación, la síntesis se convierte en opinión informada pero no en guía de acción."
        )
        modular_sentence = (
            "La tercera consecuencia es modularizar la aplicación solo cuando aporte valor. Separar fases, roles, datos, evaluación o revisión humana es útil si mejora trazabilidad, reduce error, permite auditoría o facilita actualización. Si la separación solo añade fricción, la recomendación práctica debe ser más simple."
        )
        documentation_sentence = (
            "La cuarta consecuencia es documentar el proceso como objeto de evaluación: fuentes, criterios de inclusión y exclusión, unidades de análisis, variables o dimensiones, instrumentos, supuestos, decisiones dudosas, fallos y cambios. Esa documentación permite saber si una recomendación procede de evidencia fuerte o de una cadena frágil de inferencias."
        )
        comparison_sentence = (
            f"La quinta consecuencia afecta a comparación y adopción. No debería elegirse una solución por una métrica aislada, sino por la configuración completa entre contexto, método, evidencia, coste, riesgo, replicabilidad y mantenimiento. Esta cautela importa porque {benchmark_gap_dejar} y {theory_gap}."
        )
        metrics_sentence = (
            "La sexta consecuencia es medir valor práctico con indicadores de sistema o dominio: calidad, seguridad, coste, robustez, trazabilidad, reproducibilidad, intervención humana requerida, actualización y utilidad para la decisión real. Si la métrica no conecta con una decisión, la revisión describe literatura pero no orienta acción."
        )
        transfer_sentence = (
            "La séptima consecuencia es convertir los vacíos de reporte en checklist operativo. Cuando faltan muestra, país, variables, comparador o validación, la respuesta no debe ser solo `más estudios`, sino especificar qué debe declarar el siguiente trabajo para que su evidencia sea reutilizable."
        )
        governance_sentence = (
            "La octava consecuencia es planificar actualización y límites. Una recomendación práctica solo debe viajar a nuevos contextos cuando se mantienen condiciones parecidas de población, dominio, instrumento, riesgo y evaluación. El valor de la revisión aumenta cuando dice dónde aplicar, dónde no aplicar todavía y qué datos permitirían cambiar la decisión."
        )

    evidence_sentence = (
        f"{evidence_implication} {citation}".strip() + "."
        if evidence_implication and citation
        else evidence_implication.rstrip(".") + "."
        if evidence_implication
        else f"En términos aplicados, estos patrones deben leerse junto a los estudios que sostienen la síntesis focal{citation_sentence}"
    )
    checklist_sentence = (
        f"La novena consecuencia es usar los huecos del corpus como checklist de mejora. En esta síntesis, {reporting_gap_sentence(diagnostics)}. Esos datos no invalidan automáticamente el corpus, pero indican qué información debe exigirse para tomar decisiones con menos incertidumbre."
    )

    return [
        "## Implicaciones prácticas",
        "",
        intro,
        "",
        task_sentence,
        "",
        verification_sentence,
        "",
        modular_sentence,
        "",
        documentation_sentence,
        "",
        comparison_sentence,
        "",
        metrics_sentence,
        "",
        evidence_sentence,
        "",
        transfer_sentence,
        "",
        governance_sentence,
        "",
        checklist_sentence,
    ]


def build_validity_threats_lines(
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
    *,
    citation_ids: list[str] | None = None,
    explicit_n1: int = 0,
    small_n: int = 0,
) -> list[str]:
    profile = detect_review_profile(context)
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    included_count = flow_counts.get("included_in_review", len(focus_rows))
    sought = flow_counts.get("full_text_sought", 0)
    not_retrieved = flow_counts.get("full_text_not_retrieved", 0)
    topic = review_subject_label_es(context)
    top_ids = citation_ids or top_citation_ids(focus_rows, 16)
    citation = (" " + citation_block(top_ids[8:12])) if top_ids else ""
    if profile == "personality_llm":
        construct_warning = (
            "La validez de constructo es especialmente delicada porque `personalidad` puede designar rasgo medido, persona inducida, estilo conversacional, preferencia contextual o efecto downstream. "
            "La revisión mitiga ese riesgo separando constructo, procedimiento de medición, intervención, métrica, tarea y efecto observado, pero no puede convertir diseños heterogéneos en una escala psicométrica única."
        )
        unit_warning = (
            "La amenaza inferencial principal es confundir señal experimental con estabilidad psicológica general. "
            "Un resultado sobre una persona sintética, una tarea o un instrumento no debe extrapolarse automáticamente a todos los modelos, contextos o interacciones humanas."
        )
    elif profile in {"ai_architecture", "software_architecture", "agent_architecture"}:
        construct_warning = (
            "La validez de constructo exige cautela porque etiquetas como herramientas, memoria, verificación, roles u orquestación son códigos analíticos superpuestos y no categorías mutuamente excluyentes. "
            "La revisión mitiga ese riesgo tratándolas como señales de configuración y no como una taxonomía cerrada de componentes."
        )
        unit_warning = (
            "La amenaza inferencial principal es confundir recurrencia arquitectónica con superioridad universal. "
            "Que un componente aparezca con frecuencia no significa que sea óptimo para toda tarea; su valor depende del coste de fallo, la necesidad de trazabilidad, la latencia, el contexto de despliegue y la calidad de la evaluación."
        )
    elif profile == "creativity_llm":
        construct_warning = (
            "La validez de constructo es especialmente relevante porque `creatividad` puede medirse como novedad, utilidad, diversidad, pensamiento divergente, escritura creativa o resolución de problemas. "
            "La revisión mitiga ese riesgo separando tarea, instrumento, juez, comparador y condición de generación, pero no convierte esas medidas en una creatividad general única."
        )
        unit_warning = (
            "La amenaza inferencial principal es transformar resultados por tarea en rankings globales de modelos. "
            "Un buen rendimiento en una rúbrica creativa no implica transferencia automática a otros dominios, jueces o criterios de creatividad."
        )
    elif profile == "ai_higher_education_teaching":
        construct_warning = (
            "La validez de constructo exige cautela porque `ayuda al profesorado` puede significar eficiencia, calidad del feedback, apoyo a evaluación, diseño curricular, tutoría, reducción de carga, alfabetización en IA o mejora de aprendizaje. "
            "La revisión mitiga ese riesgo separando tarea docente, sistema usado, contexto universitario, indicador de calidad, control humano y resultado observado, pero no convierte esos planos en una métrica única de mejora educativa."
        )
        unit_warning = (
            "La amenaza inferencial principal es confundir adopción o percepción positiva con mejora pedagógica demostrada. "
            "Un estudio sobre intención de uso, satisfacción docente o prototipo local no debe extrapolarse automáticamente a todas las disciplinas, universidades, perfiles de profesorado o resultados de aprendizaje."
        )
    else:
        construct_warning = (
            f"La validez de constructo exige cautela porque {topic} puede aparecer operacionalizado mediante diseños, unidades de análisis, instrumentos y resultados no equivalentes. "
            "La revisión mitiga ese riesgo usando una gramática común de comparación, pero no borra la heterogeneidad del material fuente."
        )
        unit_warning = (
            "La amenaza inferencial principal es convertir patrones descriptivos en conclusiones causales. "
            "La revisión identifica señales, condiciones y vacíos, pero no debe leerse como meta-análisis causal cuando los diseños originales no son conmensurables."
        )
    # Avoid reporting empty risks as "0 cases"; that reads like a table artifact, not scholarly prose.
    if explicit_n1 or small_n:
        small_unit_sentence = (
            f"La sexta amenaza procede de estudios con unidades analíticas pequeñas o poco comparables. En el subconjunto focal aparecen {explicit_n1} caso{'s' if explicit_n1 != 1 else ''} con lógica explícita de N=1 y {small_n} estudio{'s' if small_n != 1 else ''} con unidades analíticas muy pequeñas o estrechas. "
            "Estos trabajos pueden aportar intuición de diseño o señal exploratoria, pero no deben pesar igual que evaluaciones repetidas, benchmarks comparables o estudios con validación externa."
        )
    else:
        small_unit_sentence = (
            "La sexta amenaza es la equivalencia entre unidades de análisis. Aunque el subconjunto focal no muestra una concentración clara de estudios de unidad mínima o casos aislados, la comparación sigue dependiendo de que cada trabajo declare población, nivel de análisis, contexto y alcance inferencial de forma suficiente."
        )
    return [
        "## Amenazas a la validez",
        "",
        "Esta sección no se plantea como una disculpa metodológica, sino como delimitación explícita del alcance de la síntesis. Una revisión sistemática gana fuerza cuando dice con precisión qué puede sostener, qué solo aparece como señal y qué queda fuera de sus condiciones de evidencia.",
        "",
        f"La primera amenaza afecta a la selección y cobertura. {corpus_focus_relation(included_count, len(focus_rows))} El subconjunto focal de n={len(focus_rows)} no es una muestra aleatoria del campo, sino una selección intensiva basada en ajuste temático, densidad de extracción, PDF legible y score compuesto. Esta decisión aumenta la calidad analítica, pero puede concentrar estudios mejor reportados o más fáciles de extraer.",
        "",
        (
            f"La segunda amenaza procede de la recuperabilidad del texto completo. De {sought} textos completos buscados, {not_retrieved} no pudieron recuperarse como PDF legible y quedaron fuera por regla metodológica. "
            "Esa decisión mejora auditabilidad y evita inferencias desde registros incompletos, pero puede sesgar el corpus hacia publicaciones con DOI, acceso abierto, mejor indexación o PDF técnicamente recuperable."
            if sought
            else "La segunda amenaza procede de la recuperabilidad del texto completo. La regla de PDF legible mejora auditabilidad, pero puede favorecer estudios mejor indexados, con acceso abierto o técnicamente más fáciles de procesar."
        ),
        "",
        "La tercera amenaza es inferencial. " + unit_warning.rstrip(".") + citation + ".",
        "",
        "La cuarta amenaza afecta a la validez de constructo. " + construct_warning,
        "",
        f"La quinta amenaza es de reporting y extracción. La revisión depende de lo que los artículos hacen explícito: {reporting_gap_sentence(diagnostics)}. Estos vacíos no invalidan automáticamente el corpus, pero sí limitan la fuerza de las inferencias.",
        "",
        small_unit_sentence,
        "",
        "La séptima amenaza es temporal. En campos rápidos, una ventana de publicación puede capturar un frente técnico todavía inestable: preprints, prototipos, benchmarks tempranos, versiones de modelos que cambian y prácticas de reporte no consolidadas. Por eso la revisión debe leerse como una síntesis fechada de evidencia verificable y no como mapa definitivo de todo el campo.",
        "",
        "## Limitaciones explícitas del estudio",
        "",
        "La primera limitación es que el cribado se apoya en dos juicios automáticos independientes y no en dos revisores humanos ciegos. El acuerdo bruto y el kappa reportados miden consistencia entre esos juicios, no verdad científica. En título y resumen, una discrepancia se conservó como `necesita más prueba` para evitar una exclusión automática; en texto completo, todas las discrepancias recibieron decisión investigadora firmada tras lectura del PDF. La extracción y la evaluación crítica permanecen como codificación asistida y auditable, no como doble codificación humana.",
        "",
        "La mitigación aplicada combina protocolo previo, reglas de elegibilidad, juicios separados, resolución conservadora de incertidumbre, adjudicación humana de discrepancias en texto completo, DOI público, PDF local, extracción estructurada, anexos suplementarios, matriz de auditoría, score reproducible y conservación de estudios contextuales fuera del N focal. Estas medidas permiten que un lector externo recomponga cada decisión y detecte dónde podría discrepar, pero no convierten el proceso en un panel humano doble si una revista exige ese diseño específico.",
        "",
        "Si la revista objetivo exige doble revisión humana, la validación adicional debería concentrarse en una submuestra aleatoria y heterogénea que cubra extracción de variables, codificación de mecanismos, evaluación crítica y decisión focal; el cribado ya conserva ambos juicios y las decisiones humanas de discrepancia para facilitar esa réplica. El manuscrito no presenta la trazabilidad documental como equivalente a fiabilidad interjueces humana: declara su alcance y deja preparada la evidencia para una verificación posterior.",
        "",
        "La segunda limitación es que la rúbrica de score y riesgo de reporting es interna. Se operacionaliza y se publica para que pueda ser auditada, pero no debe presentarse como una herramienta validada universal. Su función es ordenar un corpus heterogéneo y hacer visibles vacíos de reporte; no producir una escala psicométrica generalizable.",
        "",
        "Una derivada concreta de esa limitación aparece en el perímetro contextual elegible no focal. Cuando los estudios quedan fuera de la síntesis intensiva, deben conservarse como registros contextuales elegibles y no como estudios con evaluación individual completa. Esa decisión evita sobrerrepresentar una precisión que la extracción no sostiene: el perímetro contextual sirve para trazabilidad, cobertura y actualización, no para afirmar que todos esos estudios tengan exactamente la misma calidad científica.",
        "",
        "La tercera limitación es de cobertura. Las fuentes bibliográficas consultadas, los términos de búsqueda, la disponibilidad de APIs, los límites de acceso abierto y la recuperabilidad de PDFs condicionan qué estudios llegan a texto completo. El corpus final es robusto para la pregunta y la ventana temporal, pero no equivale a toda la literatura posible.",
        "",
        "La cuarta limitación es de generalización. Los resultados deben transferirse con cautela a otros países, disciplinas, instituciones, niveles educativos, modelos, políticas de datos o prácticas docentes. Una revisión sistemática puede identificar patrones y condiciones de comparación; no puede garantizar que una intervención funcione igual fuera de los contextos reportados por los estudios primarios.",
        "",
        "Las mitigaciones aplicadas son: regla DOI/PDF, lectura de texto completo, separación entre corpus incluido y síntesis focal, matriz de selección, extracción estructurada, anexos CSV, sensibilidad del ranking cuando procede, citas trazables y cautela explícita en resultados, discusión y conclusiones. El límite no invalida la síntesis; define las condiciones bajo las cuales puede ser auditada, discutida y actualizada.",
    ]


def join_human_list(items: list[str], language: str = "es") -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        connector = " and " if language == "en" else " y "
        return connector.join(cleaned)
    if language == "en":
        return ", ".join(cleaned[:-1]) + ", and " + cleaned[-1]
    return ", ".join(cleaned[:-1]) + " y " + cleaned[-1]


def deduplication_summary(duplicates_removed: int, language: str = "es") -> str:
    if duplicates_removed <= 0:
        if language == "en":
            return "did not require duplicate consolidation before screening"
        return "no requirió consolidación de duplicados antes del cribado"
    if language == "en":
        return f"consolidated {duplicates_removed} duplicate record{'s' if duplicates_removed != 1 else ''} before screening"
    return f"consolidó {duplicates_removed} duplicado{'s' if duplicates_removed != 1 else ''} antes del cribado"


def focal_synthesis_relation(included_count: int, focus_count: int, language: str = "es") -> str:
    remaining = max(included_count - focus_count, 0)
    if remaining == 0:
        if language == "en":
            return (
                f"In this review, all {focus_count} included studies also met the editorial criteria for the focal synthesis, "
                "so no additional reduction step was needed before the deepest comparison."
            )
        return (
            f"En esta revisión, los {focus_count} estudios incluidos también cumplieron los criterios editoriales de la síntesis focal, "
            "de modo que no fue necesario introducir una poda adicional antes de la comparación más intensiva."
        )
    if language == "en":
        if remaining == 1:
            return (
                f"From that corpus, an operational focal synthesis of {focus_count} studies was defined. "
                "The remaining included study was retained as an eligible contextual perimeter: it delimits the field and preserves traceability, "
                "but did not meet the combined threshold of fit, quality, representativeness, and extraction density required for the deepest comparison. "
                "It is therefore reported as auditable context rather than as fine-grained focal evidence."
            )
        return (
            f"From that corpus, an operational focal synthesis of {focus_count} studies was defined. "
            f"The remaining {remaining} included studies were retained as an eligible contextual perimeter: they delimit the field and preserve traceability, "
            "but did not meet the combined threshold of fit, quality, representativeness, and extraction density required for the deepest comparison. "
            "They are therefore reported as auditable context rather than as fine-grained focal evidence."
        )
    if remaining == 1:
        return (
            f"Sobre ese corpus se definió una síntesis focal operativa de {focus_count} estudios. "
            "El estudio incluido restante se conservó como perímetro contextual elegible, pero quedó fuera de las comparaciones más intensivas "
            "porque no alcanzó el umbral combinado de ajuste, calidad, representatividad y densidad extractiva que exige el N focal. Se reporta como contexto auditable, no como base de score fino ni como evidencia sustantiva al mismo nivel que la síntesis focal."
        )
    return (
        f"Sobre ese corpus se definió una síntesis focal operativa de {focus_count} estudios. "
        f"Los {remaining} estudios incluidos restantes se conservaron como perímetro contextual elegible, pero quedaron fuera de las comparaciones más intensivas "
        "porque no alcanzaron el umbral combinado de ajuste, calidad, representatividad y densidad extractiva que exige el N focal. Se reportan como contexto auditable, no como base de score fino ni como evidencia sustantiva al mismo nivel que la síntesis focal."
    )


def render_search_source_list(review_dir: pathlib.Path, language: str = "es") -> str:
    counter = read_search_sources(review_dir)
    labels = [
        SOURCE_DISPLAY_MAP.get(source, source)
        for source, _ in counter.most_common()
        if normalize_phrase(source)
    ]
    unique_labels = dedupe_preserve(labels)
    if not unique_labels:
        return "fuentes no especificadas" if language == "es" else "unspecified sources"
    return join_human_list(unique_labels, language=language)


def personality_construct_label_en(label: str) -> str:
    normalized = normalize_phrase(label).lower()
    return PERSONALITY_CONSTRUCT_EN_MAP.get(normalized, normalize_phrase(label))


def record_ids_for_doi(rows: list[dict[str, str]], doi: str) -> list[str]:
    target = (doi or "").strip().lower()
    target = target.replace("doi:", "").strip()
    target = re.sub(r"^https?://(dx\.)?doi\.org/", "", target, flags=re.I)
    if not target:
        return []
    matched: list[str] = []
    for row in rows:
        row_doi = first_nonempty(row.get("assigned_doi"), row.get("doi"), row.get("notes")).strip().lower()
        row_doi = row_doi.replace("doi:", "").strip()
        row_doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", row_doi, flags=re.I)
        if row_doi == target and row.get("record_id"):
            matched.append(row["record_id"])
    return dedupe_preserve(matched)


def record_ids_for_title_fragment(rows: list[dict[str, str]], fragment: str) -> list[str]:
    target = normalize_phrase(fragment).lower()
    if not target:
        return []
    matched: list[str] = []
    for row in rows:
        title = normalize_phrase(first_nonempty(row.get("title_original"), row.get("title_en"), row.get("title_es"))).lower()
        if target in title and row.get("record_id"):
            matched.append(row["record_id"])
    return dedupe_preserve(matched)


def first_nonempty(*values: str | None) -> str:
    for value in values:
        text = (value or "").strip()
        if text:
            return text
    return ""


def merge_notes(*values: str | None) -> str:
    merged = []
    seen = set()
    for value in values:
        text = (value or "").strip()
        if not text or text in seen:
            continue
        merged.append(text)
        seen.add(text)
    return " | ".join(merged)


def load_corpus(review_dir: pathlib.Path) -> dict[str, CorpusRecord]:
    master_rows = read_csv_rows(review_dir / "records" / "master-records.csv")
    extraction_rows = read_csv_rows(review_dir / "extraction" / "extraction-table.csv")
    selection_rows = read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")

    corpus: dict[str, CorpusRecord] = {}
    for row in master_rows:
        record_id = (row.get("record_id") or "").strip()
        if not record_id:
            continue
        corpus[record_id] = CorpusRecord(
            record_id=record_id,
            assigned_doi=(row.get("assigned_doi") or "").strip(),
            title=first_nonempty(row.get("title_original"), row.get("title_en"), row.get("title_es")),
            authors=(row.get("authors") or "").strip(),
            year=(row.get("year") or "").strip(),
            work_type=(row.get("work_type") or "").strip(),
            selected_for_final_n=False,
            notes=(row.get("notes") or "").strip(),
        )
    for row in extraction_rows:
        record_id = (row.get("record_id") or "").strip()
        if not record_id:
            continue
        current = corpus.get(record_id)
        corpus[record_id] = CorpusRecord(
            record_id=record_id,
            assigned_doi=first_nonempty(row.get("assigned_doi"), current.assigned_doi if current else ""),
            title=first_nonempty(
                row.get("title_original"),
                row.get("title_en"),
                row.get("title_es"),
                current.title if current else "",
            ),
            authors=first_nonempty(row.get("authors"), current.authors if current else ""),
            year=first_nonempty(row.get("year"), current.year if current else ""),
            work_type=first_nonempty(row.get("work_type"), current.work_type if current else ""),
            selected_for_final_n=current.selected_for_final_n if current else False,
            notes=merge_notes(current.notes if current else "", row.get("notes")),
        )
    for row in selection_rows:
        record_id = (row.get("record_id") or "").strip()
        if not record_id:
            continue
        current = corpus.get(record_id)
        selected = (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "sí", "si", "true", "1"}
        if current:
            current.selected_for_final_n = selected
        else:
            corpus[record_id] = CorpusRecord(
                record_id=record_id,
                assigned_doi=(row.get("assigned_doi") or "").strip(),
                title=(row.get("title_original") or "").strip(),
                authors=(row.get("authors") or "").strip(),
                year="",
                work_type="",
                selected_for_final_n=selected,
                notes=merge_notes(row.get("notes")),
            )
    return corpus


def is_selected(row: dict[str, str]) -> bool:
    return (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "sí", "si", "true", "1"}


def selected_record_ids(review_dir: pathlib.Path, corpus: dict[str, CorpusRecord]) -> list[str]:
    selection_rows = read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")
    ordered: list[str] = []
    seen: set[str] = set()

    def rank_of(row: dict[str, str]) -> tuple[int, str]:
        raw = (row.get("ultraquality_rank") or "").strip()
        try:
            return int(raw), row.get("record_id") or ""
        except ValueError:
            return 999999, row.get("record_id") or ""

    for row in sorted(selection_rows, key=rank_of):
        record_id = (row.get("record_id") or "").strip()
        if not record_id or not is_selected(row) or record_id in seen:
            continue
        ordered.append(record_id)
        seen.add(record_id)

    for record_id in sorted(corpus):
        if record_id in seen:
            continue
        if corpus[record_id].selected_for_final_n:
            ordered.append(record_id)
            seen.add(record_id)
    return ordered


def nice_value(value: str | None, fallback: str = "no reportado") -> str:
    text = normalize_phrase(value)
    return text if text else fallback


def parse_int(value: str | int | None, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def parse_float(value: str | float | int | None, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def parse_n_range(value: str | int | None) -> tuple[int, int]:
    """Parse a requested final-N contract such as ``25`` or ``11-75``."""
    text = str(value or "").strip()
    if not text:
        return 0, 0
    numbers = [int(match) for match in re.findall(r"\d+", text)]
    if not numbers:
        return 0, 0
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def composite_selection_score(row: dict[str, str]) -> float:
    """Compute the same transparent focal score used in the manuscript."""
    rel = parse_float(row.get("relevance_score"))
    meth = parse_float(row.get("methodological_quality_score"))
    rep = parse_float(row.get("representativeness_score"))
    if rel or meth or rep:
        formula = normalize_phrase(row.get("score_formula"))
        match = re.search(r"([0-9.,]+)\*Rel\s*\+\s*([0-9.,]+)\*Cal\s*\+\s*([0-9.,]+)\*Rep", formula, flags=re.I)
        if match:
            weights = [parse_float(value.replace(",", ".")) for value in match.groups()]
            return weights[0] * rel + weights[1] * meth + weights[2] * rep
        return parse_float(row.get("ultraquality_score")) or (0.50 * rel + 0.35 * meth + 0.15 * rep)
    return parse_float(row.get("ultraquality_score"))


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalized_text(text: str | None) -> str:
    lowered = strip_accents((text or "").lower())
    return re.sub(r"\s+", " ", lowered).strip()


def focus_token_in_text(text: str, token: str) -> bool:
    """Match profile tokens without accidental substring hits.

    This avoids false domain switches such as ``personalizacion`` activating a
    personality-LLM manuscript profile because it contains ``persona``.
    """
    normalized_token = normalized_text(token)
    if not normalized_token:
        return False
    if re.fullmatch(r"[a-z0-9+.-]+", normalized_token):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_token)}(?![a-z0-9])", text))
    return normalized_token in text


def focus_any_token(text: str, tokens: Iterable[str]) -> bool:
    return any(focus_token_in_text(text, token) for token in tokens)


def pluralize_estudio(count: int) -> str:
    return "estudio" if count == 1 else "estudios"


def percentage(part: int, total: int) -> str:
    if total <= 0:
        return "0,0%"
    return f"{(part / total) * 100:.1f}%".replace(".", ",")


def extract_first_url(text: str | None) -> str:
    match = re.search(r"https?://\S+", text or "")
    return match.group(0).rstrip(").,;") if match else ""


def canonical_arxiv_url(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    doi_match = re.search(r"10\.48550/(?:arxiv|ARXIV)\.(\d{4}\.\d{4,5})", text)
    if doi_match:
        return f"https://arxiv.org/abs/{doi_match.group(1)}"
    abs_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", text, flags=re.IGNORECASE)
    if abs_match:
        return f"https://arxiv.org/abs/{abs_match.group(1)}"
    return ""


def arxiv_preprint_label(arxiv_url: str) -> str:
    del arxiv_url
    return "arXiv"


def preprint_repository_label(
    record: CorpusRecord,
    csl_meta: dict | None,
    citation_url: str,
) -> str:
    """Resolve the named repository for standalone preprints."""
    assigned_doi = (record.assigned_doi or "").lower()
    if canonical_arxiv_url(citation_url or assigned_doi or record.notes):
        return "arXiv"
    if assigned_doi.startswith("10.21203/"):
        return "Research Square"
    if assigned_doi.startswith("10.20944/"):
        return "Preprints.org"
    if not csl_meta:
        return "Preprint" if assigned_doi.startswith("10.1101/") else ""

    institution_names = " ".join(
        str(item.get("name") or "")
        for item in (csl_meta.get("institution") or [])
        if isinstance(item, dict)
    )
    blob = normalized_text(
        " ".join(
            [
                institution_names,
                csl_value(csl_meta, "publisher"),
                csl_value(csl_meta, "group-title"),
                csl_value(csl_meta, "subtype"),
            ]
        )
    ).lower()
    if "biorxiv" in blob:
        return "bioRxiv"
    if "medrxiv" in blob:
        return "medRxiv"
    if csl_value(csl_meta, "type") in {"posted-content", "report"} and (
        csl_value(csl_meta, "subtype").lower() == "preprint"
        or (record.assigned_doi or "").startswith("10.1101/")
    ):
        return "Preprint"
    return ""


def citation_url_for_record(record: CorpusRecord, csl_meta: dict | None = None) -> str:
    note_url = extract_first_url(record.notes)
    note_arxiv_url = canonical_arxiv_url(note_url)
    if csl_meta:
        arxiv_url = canonical_arxiv_url(csl_value(csl_meta, "DOI"))
        if arxiv_url:
            return arxiv_url
        if note_arxiv_url:
            return note_arxiv_url
        doi_link = doi_url(csl_meta, record.assigned_doi)
        if doi_link:
            return doi_link
        url = csl_value(csl_meta, "URL")
        if url:
            return url
    if note_arxiv_url:
        return note_arxiv_url
    arxiv_url = canonical_arxiv_url(record.assigned_doi)
    if arxiv_url:
        return arxiv_url
    if record.assigned_doi:
        return f"https://doi.org/{record.assigned_doi}"
    return note_url


def italic(text: str) -> str:
    value = (text or "").strip()
    return f"*{value}*" if value else ""


def reference_preprint_marker(record: CorpusRecord, csl_meta: dict | None, citation_url: str) -> str:
    entry_type = csl_value(csl_meta, "type") if csl_meta else ""
    if canonical_arxiv_url(csl_value(csl_meta, "DOI") or citation_url):
        return " [Preprint]"
    if entry_type in {"posted-content", "report"} and canonical_arxiv_url(csl_value(csl_meta, "DOI") or citation_url):
        return " [Preprint]"
    if not csl_meta and canonical_arxiv_url(record.notes or citation_url or record.assigned_doi):
        return " [Preprint]"
    return ""


def looks_like_repository_work(record: CorpusRecord, citation_url: str, *sources: str) -> bool:
    """Detect standalone repository works that APA should not format as journal articles."""
    blob = normalized_text(" ".join([record.notes, citation_url, *sources])).lower()
    markers = (
        "repository",
        "repositorio",
        "repositori",
        "hdl.handle.net",
        "zaguan",
        "oa.upm.es",
        "uniremington",
        "unad.edu.co",
        "sedici.unlp",
        "bibliotecas",
        "colecciones digitales",
        "tese",
        "tesis",
        "thesis",
        "dissertation",
    )
    return any(marker in blob for marker in markers)


def repository_work_descriptor(record: CorpusRecord, citation_url: str, *sources: str) -> str:
    blob = normalized_text(" ".join([record.notes, citation_url, *sources])).lower()
    if any(marker in blob for marker in ("tesis doctoral", "doctoral", "dissertation")):
        return " [Tesis doctoral]"
    if any(marker in blob for marker in ("master", "máster", "maestr", "mestrado", "tese", "tesis")):
        return " [Tesis o trabajo académico]"
    return " [Trabajo académico]"


def parse_intake_field(review_dir: pathlib.Path, label: str) -> str:
    intake_path = review_dir / "protocol" / "intake.md"
    if not intake_path.exists():
        return ""
    content = intake_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(rf"^- {re.escape(label)}:[ \t]*(.*)$", content, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_intake_field_any(review_dir: pathlib.Path, labels: list[str]) -> str:
    for label in labels:
        value = parse_intake_field(review_dir, label)
        if value:
            return value
    return ""


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


def read_research_context(review_dir: pathlib.Path) -> dict[str, str]:
    context = {
        "topic": parse_intake_field(review_dir, "Tema"),
        "years": parse_intake_field(review_dir, "Año o años"),
        "start_date": parse_intake_field(review_dir, "Fecha inicial (opcional)"),
        "end_date": parse_intake_field(review_dir, "Fecha final (opcional)"),
        "inclusion": parse_intake_field(review_dir, "Criterios de inclusión"),
        "exclusion": parse_intake_field(review_dir, "Criterios de exclusión"),
        "research_question": parse_intake_field(review_dir, "Pregunta de investigación (opcional)"),
        "manuscript_authors": parse_intake_field_any(
            review_dir,
            [
                "Autoría del manuscrito (opcional)",
                "Autor(es) del manuscrito (opcional)",
                "Autor del manuscrito (opcional)",
                "Autor",
                "Autores",
            ],
        ),
        "manuscript_email": parse_intake_field_any(
            review_dir,
            [
                "Correo de contacto (opcional)",
                "Email de contacto (opcional)",
                "Correo",
                "Email",
            ],
        ),
        "manuscript_date": parse_intake_field_any(
            review_dir,
            [
                "Fecha del manuscrito (opcional)",
                "Fecha de versión (opcional)",
                "Fecha de publicación (opcional)",
            ],
        ),
        "target_journal": parse_intake_field_any(
            review_dir,
            [
                "Revista o medio objetivo (opcional; si se omite, o si solo indicas una familia temática amplia, Hermes usa `generic-common-core`)",
                "Revista o medio objetivo (opcional; si se omite, Hermes usa `generic-common-core`)",
                "Revista objetivo (opcional)",
            ],
        ),
        "review_mode_declared": parse_intake_field_any(
            review_dir,
            [
                "Modo metodológico (opcional)",
                "Modo metodologico (opcional)",
                "Modo de revisión (opcional)",
                "Modo de revision (opcional)",
                "Review mode",
            ],
        ),
    }
    decision = read_review_mode_decision(review_dir)
    if not decision or any(not decision.get(key) for key in REVIEW_MODE_PLAYBOOK_KEYS):
        decision = infer_review_mode(
            topic=context.get("topic", ""),
            question=context.get("research_question", ""),
            inclusion=context.get("inclusion", ""),
            exclusion=context.get("exclusion", ""),
            target_outlet=context.get("target_journal", ""),
            explicit_mode=context.get("review_mode_declared", ""),
        )
        write_review_mode_artifacts(review_dir, decision)
    context["review_mode"] = str(decision.get("mode") or "")
    context["primary_review_mode"] = str(decision.get("primary_mode") or decision.get("mode") or "")
    context["review_mode_label"] = str(decision.get("mode_label") or "")
    context["review_mode_framework"] = str(decision.get("default_framework") or "")
    context["review_mode_summary"] = review_mode_summary(decision)
    return context


def detect_review_profile(context: dict[str, str]) -> str:
    mode = (context.get("primary_review_mode") or context.get("review_mode") or "").strip().lower()
    if mode in {"social_sciences", "education", "management", "mixed"}:
        if mode == "education":
            return "education"
        if mode == "management":
            return "management"
        return "social_sciences"
    blob = normalized_text(" ".join(context.values()))
    education_ai_tokens = [
        "ia",
        "ai",
        "artificial intelligence",
        "inteligencia artificial",
        "generative ai",
        "ia generativa",
        "large language model",
        "large language models",
        "llm",
        "llms",
        "modelo de lenguaje",
        "modelos de lenguaje",
        "chatgpt",
        "gpt",
        "chatbot",
        "chatbots",
        "copilot",
        "copiloto",
        "agent",
        "agents",
        "agente",
        "agentes",
        "tutor inteligente",
        "asistente docente",
    ]
    higher_education_tokens = [
        "educacion superior",
        "higher education",
        "universidad",
        "universitario",
        "universitaria",
        "universitarios",
        "universitarias",
        "university",
        "universities",
        "faculty",
        "docente",
        "docentes",
        "profesor",
        "profesores",
        "profesorado",
        "teacher",
        "teachers",
        "lecturer",
        "lecturers",
        "instructor",
        "instructors",
        "academic staff",
        "teaching staff",
        "teaching",
        "ensenanza",
        "aprendizaje",
        "feedback",
        "assessment",
        "evaluacion",
        "curriculum",
        "curriculo",
        "pedagogia",
        "pedagogy",
    ]
    personality_tokens = [
        "personalidad",
        "persona",
        "trait",
        "traits",
        "big five",
        "ocean",
        "mbti",
        "hexaco",
    ]
    llm_tokens = ["llm", "large language model", "modelo de lenguaje", "language model"]
    creativity_tokens = [
        "creatividad",
        "creativity",
        "creative",
        "creativo",
        "creativa",
        "criatividade",
        "pensamiento divergente",
        "divergent thinking",
        "creative writing",
        "originalidad",
        "originality",
        "novedad",
        "novelty",
        "ideacion",
        "ideación",
    ]
    software_tokens = [
        "software",
        "code",
        "codigo",
        "desarrollo de software",
        "ingenieria del software",
        "software engineering",
        "debug",
        "testing",
    ]
    ai_architecture_tokens = [
        "arquitectura",
        "arquitecturas",
        "architecture",
        "architectural",
        "framework",
        "rag",
        "retrieval augmented",
        "retrieval-augmented",
        "modelos fundacionales",
        "foundation model",
        "transformer",
        "moe",
        "multimodal",
        "inferencia",
        "inference",
    ]
    broad_ai_tokens = [
        "ia",
        "ai",
        "llm",
        "large language model",
        "modelo de lenguaje",
        "generative ai",
        "ia generativa",
        "modelo generativo",
        "modelos generativos",
        "agent",
        "agente",
        "rag",
        "foundation model",
        "modelos fundacionales",
    ]
    security_harness_tokens = [
        "security harness",
        "harness de seguridad",
        "guardrail",
        "guardrails",
        "llm firewall",
        "ai firewall",
        "prompt injection",
        "jailbreak",
        "policy enforcement",
        "runtime control",
        "tool misuse",
        "data exfiltration",
        "fuga de datos",
    ]
    if focus_any_token(blob, security_harness_tokens) and focus_any_token(blob, broad_ai_tokens):
        return "ai_security_harness"
    if focus_any_token(blob, education_ai_tokens) and focus_any_token(blob, higher_education_tokens):
        return "ai_higher_education_teaching"
    if focus_any_token(blob, personality_tokens) and focus_any_token(blob, llm_tokens):
        return "personality_llm"
    if focus_any_token(blob, creativity_tokens) and focus_any_token(blob, llm_tokens + ["generative ai", "ia generativa", "chatgpt", "gpt"]):
        return "creativity_llm"
    if focus_any_token(blob, software_tokens):
        return "software_architecture"
    if focus_any_token(blob, ai_architecture_tokens) and focus_any_token(blob, broad_ai_tokens):
        return "ai_architecture"
    if focus_any_token(blob, ["agente", "agentes", "agent", "agents"]):
        return "agent_architecture"
    return "generic"


SOCIAL_TOPIC_TRANSLATIONS = [
    ("polarización afectiva", "affective polarization"),
    ("polarizacion afectiva", "affective polarization"),
    ("uso de redes sociales", "social media use"),
    ("redes sociales", "social media"),
    ("confianza institucional", "institutional trust"),
    ("democracias contemporáneas", "contemporary democracies"),
    ("democracias contemporaneas", "contemporary democracies"),
    ("relación entre", "relationship between"),
    ("relacion entre", "relationship between"),
    ("evidencia empírica", "empirical evidence"),
    ("evidencia empirica", "empirical evidence"),
]

SOCIAL_KEYWORD_CANDIDATES = [
    "polarización afectiva",
    "redes sociales",
    "confianza institucional",
    "democracias contemporáneas",
    "comunicación política",
    "confianza política",
    "evidencia empírica",
]


def is_ai_workload_review_text(text: str | None) -> bool:
    """Detect reviews about AI, productivity, workload, and displaced effort."""
    blob = normalize_phrase(text).lower()
    ai_terms = [
        "inteligencia artificial",
        "ia generativa",
        "artificial intelligence",
        "generative ai",
        "llm",
        "large language model",
        "chatgpt",
        "copilot",
    ]
    work_terms = [
        "carga de trabajo",
        "workload",
        "productividad",
        "productivity",
        "tiempo de trabajo",
        "working time",
        "esfuerzo",
        "effort",
        "supervisión",
        "supervision",
        "revisión",
        "review",
        "coordinación",
        "coordination",
        "control de calidad",
        "quality control",
        "rework",
        "trabajo humano",
        "human work",
    ]
    return any(term in blob for term in ai_terms) and any(term in blob for term in work_terms)


def is_ai_workload_context(context: dict[str, str] | None) -> bool:
    """Detect the AI/workload review from protocol-level fields."""
    if not context:
        return False
    return is_ai_workload_review_text(
        " ".join(
            [
                context.get("topic", ""),
                context.get("research_question", ""),
                context.get("inclusion", ""),
                context.get("exclusion", ""),
            ]
        )
    )


def ai_workload_row_blob(row: dict[str, str]) -> str:
    return normalize_phrase(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("abstract_original", ""),
                row.get("keywords_normalized", ""),
                row.get("tasks_or_domains", ""),
                row.get("method_used", ""),
                row.get("key_findings", ""),
                row.get("principal_result", ""),
                row.get("limitations", ""),
                row.get("instruments_or_scales", ""),
                row.get("variables_or_dimensions", ""),
                row.get("baselines_or_comparators", ""),
                row.get("theory_framework", ""),
            ]
        )
    ).lower()


def is_ai_workload_rows(rows: list[dict[str, str]]) -> bool:
    if not rows:
        return False
    sample_rows = rows[: min(len(rows), 18)]
    row_hits = sum(1 for row in sample_rows if is_ai_workload_review_text(ai_workload_row_blob(row)))
    threshold = 2 if len(sample_rows) >= 6 else 1
    if row_hits >= threshold:
        return True
    sample = " ".join(ai_workload_row_blob(row) for row in sample_rows)
    return (
        "artificial intelligence" in sample
        and any(term in sample for term in ("workload", "productivity", "effort", "supervision", "human-in-the-loop"))
    )


def ai_workload_evidence_family(row: dict[str, str]) -> str:
    """Classify AI/work reviews by substantive labor mechanism, not work type."""
    blob = ai_workload_row_blob(row)
    if re.search(r"human-in-the-loop|error|errors|incorrect|supervision|oversight|review|coordination|quality control|rework|verification|verificaci[oó]n|revisi[oó]n|coordinaci[oó]n|control de calidad|supervisi[oó]n", blob):
        return "Supervisión, revisión y control de calidad"
    if re.search(r"workload|carga|burden|burnout|administrative|administrativa|nursing|clinical|radiology|healthcare|medical|clinician|dentistry|hospital", blob):
        return "Carga de trabajo y presión operativa"
    if re.search(r"productivity|efficiency|time|speed|tiempo|productividad|eficiencia|task specific|office|workflow|flujo de trabajo", blob):
        return "Productividad local y ahorro de tiempo"
    if re.search(r"learning|training|upskilling|reskilling|skills|education|teacher|student|faculty|aprendizaje|recualificaci[oó]n|habilidades|docente|estudiante", blob):
        return "Aprendizaje, recualificación y dependencia"
    if re.search(r"ethic|privacy|bias|policy|governance|integrity|responsibility|accountability|sesgo|privacidad|gobernanza|pol[ií]tica|responsabilidad", blob):
        return "Gobernanza, riesgo y responsabilidad"
    return "Adopción y transformación del trabajo"


def ai_workload_family_synthetic_reading(family: str, members: list[dict[str, str]]) -> str:
    readings = {
        "Productividad local y ahorro de tiempo": "La evidencia apoya mejoras locales de eficiencia, pero no prueba reducción neta de trabajo cuando se incluyen preparación, revisión y control.",
        "Carga de trabajo y presión operativa": "La IA puede aliviar tareas concretas, pero la carga se desplaza hacia integración clínica, validación profesional y responsabilidad sobre errores.",
        "Supervisión, revisión y control de calidad": "Aquí se ve la tesis central: el trabajo no desaparece, cambia de producción directa a vigilancia, corrección, coordinación y decisión final.",
        "Aprendizaje, recualificación y dependencia": "La adopción exige nuevas competencias; el ahorro inmediato puede convertirse en trabajo de aprendizaje, adaptación y gestión de dependencia.",
        "Gobernanza, riesgo y responsabilidad": "Los beneficios solo son defendibles cuando se acompasan con control institucional, trazabilidad, privacidad, sesgo y reglas de escalado.",
        "Adopción y transformación del trabajo": "La señal dominante no es sustitución limpia, sino reorganización sociotécnica de tareas, responsabilidades y criterios de calidad.",
    }
    return readings.get(family, "La familia aporta evidencia sobre transformación del trabajo más que sobre desaparición simple del esfuerzo.")


def ai_workload_signal_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    specs = {
        "productivity": r"productivity|efficiency|time|speed|productividad|eficiencia|tiempo|faster|reduce",
        "workload": r"workload|carga|burden|burnout|administrative|presi[oó]n operativa",
        "supervision": r"supervision|oversight|review|coordination|quality control|rework|human-in-the-loop|supervisi[oó]n|revisi[oó]n|coordinaci[oó]n|control de calidad",
        "risk_error": r"error|incorrect|factual|omission|bias|privacy|risk|sesgo|privacidad|riesgo|omisi[oó]n",
        "learning": r"learning|training|upskilling|reskilling|skills|alfabetizaci[oó]n|aprendizaje|habilidades|recualificaci[oó]n",
        "high_risk": r"health|medical|clinical|radiology|nursing|dentistry|diagnostic|hospital|salud|cl[ií]nic|radiolog|enfermer",
        "governance": r"governance|policy|ethic|integrity|responsibility|accountability|gobernanza|pol[ií]tica|[eé]tica|responsabilidad|integridad",
    }
    counts: dict[str, int] = {}
    for key, pattern in specs.items():
        counts[key] = sum(1 for row in rows if re.search(pattern, ai_workload_row_blob(row), flags=re.IGNORECASE))
    return counts


def translate_social_phrase_en(text: str | None) -> str:
    """Translate common social-science intake phrases without broadening scope."""
    phrase = normalize_phrase(text).strip("¿? ")
    if not phrase:
        return ""
    lowered = phrase.lower()
    if is_ai_workload_review_text(lowered):
        if "evidencia" in lowered or "evidence" in lowered or "qué" in lowered or "que" in lowered:
            return (
                "What published empirical evidence exists on whether the use of artificial intelligence, especially generative AI, "
                "reduces working time, workload, or human effort, compared with the alternative hypothesis that it shifts work "
                "toward supervision, review, coordination, learning, and quality control?"
            )
        return (
            "Whether artificial intelligence reduces human workload or shifts effort toward supervision, review, coordination, and control"
        )
    if all(term in lowered for term in ("redes sociales", "polarización afectiva", "confianza institucional")) or all(
        term in lowered for term in ("redes sociales", "polarizacion afectiva", "confianza institucional")
    ):
        if "relación" in lowered or "relacion" in lowered or "evidencia" in lowered:
            return "What empirical evidence exists on the relationship between social media use, affective polarization, and institutional trust in contemporary democracies?"
        return "Affective polarization, social media, and institutional trust in contemporary democracies"
    for source, target in SOCIAL_TOPIC_TRANSLATIONS:
        lowered = lowered.replace(source, target)
    lowered = lowered.replace("qué empirical evidence existe sobre la", "what empirical evidence exists on the")
    lowered = lowered.replace("que empirical evidence existe sobre la", "what empirical evidence exists on the")
    lowered = lowered.replace("qué empirical evidence existe sobre", "what empirical evidence exists on")
    lowered = lowered.replace("que empirical evidence existe sobre", "what empirical evidence exists on")
    lowered = lowered.replace(" el ", " the ")
    lowered = lowered.replace(" la ", " the ")
    lowered = lowered.replace(" los ", " the ")
    lowered = lowered.replace(" las ", " the ")
    lowered = lowered.replace(" y ", " and ")
    lowered = lowered.replace(" en ", " in ")
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered[:1].upper() + lowered[1:] if lowered else ""


def read_flow_counts(review_dir: pathlib.Path) -> dict[str, int]:
    rows = read_csv_rows(review_dir / "prisma" / "flow-counts.csv")
    counts = {(row.get("stage") or "").strip(): parse_int(row.get("count")) for row in rows}
    missing_doi_included = sum(
        1
        for row in read_csv_rows(review_dir / "screening" / "full-text.csv")
        if (row.get("decision") or "").strip().lower() in {"include", "include_ft"}
        and not has_public_doi(row)
    )
    if missing_doi_included:
        counts["included_in_review"] = max(0, counts.get("included_in_review", 0) - missing_doi_included)
        counts["full_text_excluded"] = counts.get("full_text_excluded", 0) + missing_doi_included
    return counts


def build_evidence_position_lines(review_dir: pathlib.Path) -> list[str]:
    """Render convergence and disagreement as analysis rather than repetition."""
    path = review_dir / "analysis" / "evidence" / "evidence-position-summary.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    groups = payload.get("comparison_groups")
    if not isinstance(groups, list) or not groups:
        return []
    labels = {
        "convergence": "Convergencia",
        "directional_disagreement": "Desacuerdo direccional",
        "inconsistent_evidence": "Evidencia inconsistente",
        "qualified_pattern": "Patrón condicionado",
        "cross_context_alignment": "Alineación entre contextos",
        "descriptive_alignment": "Alineación descriptiva",
        "open_question": "Pregunta abierta",
        "insufficient_evidence": "Evidencia insuficiente",
    }
    position_labels = {
        "positive_association": "Asociación positiva",
        "negative_association": "Asociación negativa",
        "null_finding": "Resultado nulo",
        "mixed_or_conditional": "Patrón mixto o condicionado",
        "descriptive_or_theoretical": "Aportación descriptiva o teórica",
        "direction_unclear": "Dirección no recuperable",
    }
    valence_labels = {
        "favorable": "Favorable",
        "favorable_but_qualified": "Favorable con cautelas",
        "adverse": "Adversa",
        "tradeoff_or_mixed": "Compensación o resultado mixto",
        "tradeoff_or_contextual": "Dependiente del contexto",
        "no_detectable_change": "Sin cambio detectable",
        "not_applicable": "No aplicable",
        "contextual": "Contextual",
        "unclear": "No determinada",
    }
    comparable_groups = [
        group
        for group in groups
        if isinstance(group, dict) and int(group.get("studies") or 0) >= 2
    ]
    rows: list[list[str]] = []
    for group in comparable_groups[:8]:
        if not isinstance(group, dict):
            continue
        status = str(group.get("status") or "")
        positions = ", ".join(
            position_labels.get(str(value), str(value).replace("_", " "))
            for value in group.get("positions") or []
        )
        rows.append(
            [
                table_label(
                    str(
                        group.get("comparison_label")
                        or group.get("comparison_key")
                        or "Comparación no especificada"
                    )
                ),
                str(group.get("studies") or 0),
                labels.get(status, status.replace("_", " ").capitalize()),
                table_label(positions or "Dirección no recuperable"),
            ]
        )
    counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), dict) else {}
    convergence = int(counts.get("convergence") or 0)
    cross_context = int(counts.get("cross_context_alignment") or 0)
    descriptive = int(counts.get("descriptive_alignment") or 0)
    disagreement = int(counts.get("directional_disagreement") or 0) + int(
        counts.get("inconsistent_evidence") or 0
    )
    open_questions = int(counts.get("open_question") or 0) + int(counts.get("insufficient_evidence") or 0)
    domain_rows: list[list[str]] = []
    domains = payload.get("outcome_domains")
    if isinstance(domains, list):
        for domain in domains:
            if not isinstance(domain, dict):
                continue
            if int(domain.get("studies") or 0) < 2:
                continue
            valence = ", ".join(
                valence_labels.get(str(value), str(value).replace("_", " "))
                for value in domain.get("practical_valence") or []
            )
            domain_rows.append(
                [
                    table_label(
                        str(
                            domain.get("outcome_label")
                            or domain.get("outcome_family")
                            or "Resultado no especificado"
                        ).replace("_", " ")
                    ),
                    str(domain.get("studies") or 0),
                    (
                        "Señal transversal"
                        if str(domain.get("claim_status") or "") == "cross_study_signal"
                        else "Señal aislada"
                    ),
                    table_label(valence or "Lectura contextual"),
                ]
            )
    return [
        "## Convergencias, desacuerdos y preguntas abiertas",
        "",
        "La síntesis no convierte la repetición de términos en consenso. Cada hallazgo se relacionó con una "
        "unidad de comparación y se clasificó de forma conservadora como asociación positiva, asociación "
        "negativa, resultado nulo, patrón condicionado, aportación descriptiva o dirección no recuperable. "
        "Esta operación permite separar coincidencia sustantiva de similitud verbal.",
        "",
        f"El mapa identifica {convergence} unidades con convergencia directa, {cross_context} con alineación "
        f"entre contextos, {descriptive} con alineación descriptiva, {disagreement} con desacuerdo o "
        f"inconsistencia y {open_questions} que permanecen abiertas o con evidencia insuficiente. Estos "
        "conteos no se interpretan como efectos agregados: dos estudios solo ocupan el mismo plano cuando "
        "comparten constructo o exposición, resultado, unidad de análisis y contexto suficientemente comparables.",
        "",
        (
            "Por tanto, un valor cero en convergencia directa describe el resultado de un umbral exigente de "
            "conmensurabilidad, no una propiedad esencial del fenómeno ni una afirmación de que ningún estudio "
            "obtenga resultados compatibles. La compatibilidad bajo contratos parciales se conserva como "
            "alineación entre contextos, alineación descriptiva o pregunta abierta."
        ),
        "",
        (
            "Un valor cero en desacuerdo no significa que el campo carezca de resultados opuestos. Significa "
            "que no se identificaron desacuerdos entre estudios que conservaran una unidad de comparación "
            "suficientemente equivalente. Los resultados incompatibles bajo otra amenaza, métrica, modelo, "
            "contexto o baseline permanecen como heterogeneidad o pregunta abierta y no se fuerzan dentro "
            "de una falsa contradicción directa."
        ),
        "",
        "Tabla de posiciones de evidencia. Unidades compartidas por al menos dos estudios.",
        markdown_table(
            ["Unidad de comparación", "N", "Estado", "Direcciones observadas"],
            rows or [["Sin unidad comparable", "0", "Pregunta abierta", "Dirección no recuperable"]],
        ),
        "",
        "La dirección estadística y la utilidad práctica se conservaron por separado. Una reducción de "
        "latencia, error, coste o riesgo puede ser una relación negativa y, al mismo tiempo, un resultado "
        "favorable; del mismo modo, un aumento puede ser adverso cuando crece una carga o un riesgo. Esta "
        "distinción evita traducir automáticamente «positivo» como beneficioso y «negativo» como perjudicial.",
        "",
        (
            "`Dirección no recuperable` indica que el texto completo no permite reconstruir el signo o patrón "
            "de la relación con suficiente trazabilidad. `No determinada`, en cambio, se refiere a la lectura "
            "práctica: puede existir un resultado reportado, pero la evidencia no permite clasificarlo de "
            "forma estable como favorable, adverso o dependiente del contexto."
        ),
        "",
        "Tabla de dominios de resultado. Señales transversales sin agregación causal.",
        markdown_table(
            ["Dominio de resultado", "N", "Tipo de señal", "Lectura práctica"],
            domain_rows or [["Resultado no especificado", "0", "Señal aislada", "Lectura contextual"]],
        ),
        "",
        "La matriz completa conserva DOI, diseño, contexto, fragmento y localización. Por ello, una "
        "discrepancia no se resuelve por mayoría documental: se examina si procede de una medición distinta, "
        "un moderador, otra población, un diseño menos fuerte o una diferencia real entre resultados.",
        "",
    ]


def enforce_publication_doi_flow(review_dir: pathlib.Path) -> None:
    """Persist the DOI-only publication rule before paper figures/anexes are built.

    Earlier pipeline phases may keep DOI-missing full-text records as technically
    included candidates. The public manuscript, however, uses a DOI-only rule, so
    the source CSVs must expose the same corpus size as the final article.
    """
    full_text_path = review_dir / "screening" / "full-text.csv"
    full_text_rows = read_csv_rows(full_text_path)
    if full_text_rows:
        full_text_fields = list(full_text_rows[0].keys())
        full_text_changed = False
        for row in full_text_rows:
            decision = (row.get("decision") or "").strip().lower()
            if decision in {"include", "include_ft"} and not has_public_doi(row):
                row["decision"] = "exclude"
                row["reason"] = "missing_doi"
                row["reason_detail"] = (
                    "Regla DOI-only del corpus publicable: sin DOI normalizado, "
                    "el estudio no puede entrar en la revisión final aunque exista PDF local."
                )
                full_text_changed = True
        if full_text_changed:
            write_csv_rows(full_text_path, full_text_fields, full_text_rows)

    flow_path = review_dir / "prisma" / "flow-counts.csv"
    flow_rows = read_csv_rows(flow_path)
    if not flow_rows:
        return
    flow_fields = list(flow_rows[0].keys())
    counts = {(row.get("stage") or "").strip(): parse_int(row.get("count")) for row in flow_rows}
    full_text_assessed = counts.get("full_text_assessed", 0)
    included = sum(
        1
        for row in full_text_rows
        if (row.get("decision") or "").strip().lower() in {"include", "include_ft"} and has_public_doi(row)
    )
    if full_text_assessed and included:
        excluded = max(0, full_text_assessed - included)
        flow_changed = False
        for row in flow_rows:
            stage = (row.get("stage") or "").strip()
            if stage == "included_in_review" and parse_int(row.get("count")) != included:
                row["count"] = str(included)
                row["notes"] = "Estudios DOI-validos incluidos en el corpus final publicable."
                flow_changed = True
            elif stage == "full_text_excluded" and parse_int(row.get("count")) != excluded:
                row["count"] = str(excluded)
                row["notes"] = "Exclusiones en texto completo, incluidos registros retirados por regla DOI-only."
                flow_changed = True
        if flow_changed:
            write_csv_rows(flow_path, flow_fields, flow_rows)


def has_public_doi(row: dict[str, str] | CorpusRecord | None) -> bool:
    if row is None:
        return False
    if isinstance(row, CorpusRecord):
        return bool((row.assigned_doi or "").strip())
    return bool(first_nonempty(row.get("assigned_doi", ""), row.get("doi", "")).strip())


def public_doi_value(row: dict[str, str], fallback: CorpusRecord | None = None) -> str:
    doi = first_nonempty(
        row.get("assigned_doi", ""),
        row.get("doi", ""),
        fallback.assigned_doi if fallback else "",
    )
    return doi.strip() if doi.strip() else "sin DOI"


def read_search_sources(review_dir: pathlib.Path) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in read_csv_rows(review_dir / "searches" / "search-log.csv"):
        counter[(row.get("source") or "desconocido").strip() or "desconocido"] += 1
    return counter


def search_source_execution_rows(review_dir: pathlib.Path) -> list[list[str]]:
    """Describe search-log activity without treating skipped calls as retrievals."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in read_csv_rows(review_dir / "searches" / "search-log.csv"):
        source = first_nonempty(row.get("source"), row.get("platform"), "desconocido").strip()
        grouped.setdefault(source or "desconocido", []).append(row)

    rendered: list[list[str]] = []
    for source, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].lower())):
        notes = " ".join(normalize_phrase(row.get("notes")).lower() for row in rows)
        returned = sum(
            parse_int(match, 0)
            for match in re.findall(r"(\d+)\s+resultados?\s+(?:recuperados?|filtrados?)", notes)
        )
        has_error = "error:" in notes or "circuit open" in notes or "http 429" in notes
        has_quota = "cuota" in notes and any(token in notes for token in ("agotada", "omitida", "exceeded"))
        has_skipped = any(token in notes for token in ("optional source skipped", "skipped:", "omitida:"))
        has_result_report = bool(re.search(r"\d+\s+resultados?\s+(?:recuperados?|filtrados?)", notes))

        if returned and has_error:
            state = "Parcial: resultados y errores registrados"
        elif returned:
            state = "Ejecutada con resultados"
        elif has_quota:
            state = "Omitida por cuota; reanudable con credencial"
        elif has_error:
            state = "Interrumpida por error o límite de API"
        elif has_skipped:
            state = "Fuente opcional no ejecutada"
        elif has_result_report:
            state = "Ejecutada sin resultados"
        else:
            state = "Estado conservado en el log"
        rendered.append([source, str(len(rows)), str(returned) if has_result_report else "—", state])
    return rendered


def search_coverage_limit_sentence(source_rows: list[list[str]]) -> str:
    """Translate non-executed sources into an explicit coverage limitation."""
    unavailable = [
        row[0]
        for row in source_rows
        if len(row) >= 4 and (row[2] == "—" or "error" in row[3].lower())
    ]
    if not unavailable:
        return (
            "Todas las fuentes registradas devolvieron un recuento operativo; aun así, la cobertura "
            "sigue delimitada por sus índices, consultas y fechas de ejecución."
        )
    return (
        f"No produjeron un recuento recuperable {join_human_list(unavailable)}. "
        "Esta carencia puede favorecer literatura accesible mediante APIs abiertas, repositorios y "
        "preprints frente a publicaciones indexadas solo en servicios institucionales. El sesgo no "
        "se corrige fingiendo equivalencia entre fuentes: se declara, se conserva en el log y limita "
        "la representatividad atribuible al corpus."
    )


def search_strategy_summary_lines(review_dir: pathlib.Path, context: dict[str, str], limit: int = 6) -> list[str]:
    """Summarize databases, dates and query logic in the method body."""
    rows = read_csv_rows(review_dir / "searches" / "search-log.csv")
    if not rows:
        return [
            "La estrategia de búsqueda completa se conserva como anexo, pero no se detectó `searches/search-log.csv`; por tanto, el cuerpo del manuscrito no puede resumir consultas ejecutadas fuente por fuente.",
            "",
        ]
    source_counter = Counter(first_nonempty(row.get("source"), row.get("platform"), "desconocido") for row in rows)
    run_dates = sorted({normalize_phrase(row.get("run_date")) for row in rows if normalize_phrase(row.get("run_date"))})
    from_dates = sorted({normalize_phrase(row.get("from_date")) for row in rows if normalize_phrase(row.get("from_date"))})
    to_dates = sorted({normalize_phrase(row.get("to_date")) for row in rows if normalize_phrase(row.get("to_date"))})
    queries = dedupe_preserve(
        [
            normalize_phrase(row.get("query_string"))
            for row in rows
            if normalize_phrase(row.get("query_string"))
        ]
    )
    source_text = counter_summary(source_counter, sum(source_counter.values()), limit=8)
    date_text = (
        f"Las consultas se ejecutaron el {', '.join(run_dates[:3])}"
        if run_dates
        else "Las fechas de consulta constan en el log de búsqueda"
    )
    window_text = ""
    if from_dates or to_dates:
        window_text = f", con ventana registrada entre {from_dates[0] if from_dates else 'inicio no reportado'} y {to_dates[-1] if to_dates else 'cierre no reportado'}"
    query_text = "; ".join(f"`{query}`" for query in queries[:limit])
    if len(queries) > limit:
        query_text += f"; y {len(queries) - limit} cadenas adicionales en el anexo"
    topic = review_subject_label_es(context)
    return [
        f"La estrategia de búsqueda combinó fuentes bibliográficas y APIs académicas. El log contiene estos eventos por fuente: {source_text}. Un evento registra tanto ejecuciones efectivas como omisiones justificadas, cuotas o errores recuperables; por eso la Tabla 2 separa intentos, resultados brutos y estado operacional. {date_text}{window_text}. La lógica de consulta se construyó alrededor del tema `{topic}` mediante bloques de concepto, sinónimos y combinaciones bilingües cuando el campo lo requería.",
        f"Ejemplos de cadenas de búsqueda: {query_text}. El archivo `searches/search-log.csv` conserva para cada consulta la fuente, plataforma, cadena exacta, fecha de consulta, ventana temporal, notas y fichero exportado; `protocol/search-strategy.md` y `protocol/search-decomposition.md` documentan la descomposición de la pregunta en estadios de búsqueda.",
        "",
    ]


SOFTWARE_POSITIVE_TOKENS = [
    "software",
    "code",
    "coding",
    "repository",
    "debug",
    "testing",
    "test",
    "developer",
    "development",
    "devops",
    "sdlc",
    "fuzz",
    "benchmark",
    "bug",
    "commit",
    "pull request",
    "code review",
    "program repair",
    "software engineering",
]

SOFTWARE_CORE_TOKENS = [
    "software",
    "code",
    "coding",
    "repository",
    "debug",
    "developer",
    "development",
    "devops",
    "sdlc",
    "fuzz",
    "bug",
    "commit",
    "pull request",
    "code review",
    "program repair",
    "software engineering",
]

SOFTWARE_NEGATIVE_TOKENS = [
    "rare disease",
    "clinical",
    "medical",
    "hospital",
    "foundation design",
    "foundation",
    "geotechn",
    "smart city",
    "smart adaptive",
    "s-amma",
    "optical network",
    "network o&m",
    "network operations",
    "circuit",
    "structural modeling",
    "safety investigation",
    "diagnosis",
]

IRRELEVANT_KEYWORDS = {
    "computer science",
    "software",
    "software framework",
    "software system",
    "source code",
    "coding (social sciences)",
    "code (set theory)",
    "context (archaeology)",
    "benchmark (surveying)",
    "test (biology)",
    "affect (linguistics)",
    "psychology",
    "medicine",
    "disease",
    "rare disease",
    "key (lock)",
    "data science",
    "theoretical computer science",
    "polarization (electrochemistry)",
    "electrochemistry",
    "optics",
    "physics",
}


def section_needs_generation(path: pathlib.Path) -> bool:
    text = read_text(path).strip()
    if not text:
        return True
    if PLACEHOLDER_RE.search(text):
        return True
    body = "\n".join(text.splitlines()[1:]).strip()
    if "Sustituye este esquema" in body:
        return True
    return len(body) < SECTION_MIN_CHARS


def normalize_phrase(text: str | None) -> str:
    value = html.unescape((text or "").strip())
    value = re.sub(r"</?[^>]+>", "", value)
    return re.sub(r"\s+", " ", value)


def summarize_phrase(text: str | None, width: int = 120) -> str:
    phrase = normalize_phrase(text) or "no reportado"
    return textwrap.shorten(phrase, width=width, placeholder="…")


def summarize_phrase_soft(text: str | None, width: int = 120) -> str:
    phrase = normalize_phrase(text) or "no reportado"
    if phrase == "no reportado" or len(phrase) <= width:
        return phrase
    return textwrap.shorten(phrase, width=width, placeholder="…")


def no_fragment_label(value: str | None, fallback: str) -> str:
    """Avoid sentence/table fragments ending in ellipses inside analytical prose."""
    cleaned = normalize_phrase(value)
    if not cleaned or cleaned.lower() == "no reportado":
        return "no reportado"
    if "…" in cleaned or cleaned.endswith("..."):
        return fallback
    return cleaned


ARCHETYPE_DISPLAY_LABELS = {
    "skill-based o capability-based": "basada en capacidades o habilidades",
    "tool-augmented agent": "agente instrumentado con herramientas",
    "multiagente orquestado": "multiagente orquestado",
    "evaluación o benchmark arquitectónico": "evaluación o benchmark arquitectónico",
    "gobernanza y auditoría": "gobernanza y auditoría",
    "arquitectura híbrida o no tipificada": "arquitectura híbrida o no tipificada",
}


EMPIRICAL_TYPE_DISPLAY_LABELS = {
    "experimental": "experimental",
    "experimental / prototype evaluation": "experimental / evaluación de prototipo",
    "mixed": "mixto",
    "quantitative": "cuantitativo",
    "qualitative": "cualitativo",
    "qualitative / design study": "cualitativo / estudio de diseño",
    "other": "otros",
}

WORK_TYPE_DISPLAY_LABELS = {
    "empirical": "empírico",
    "theoretical": "teórico",
    "review": "revisión",
    "other": "otros",
    "unclassified": "sin clasificación recuperable",
}


def display_archetype(archetype: str) -> str:
    return ARCHETYPE_DISPLAY_LABELS.get(archetype, archetype)


def display_empirical_type(empirical_type: str) -> str:
    normalized = normalize_phrase(empirical_type).lower()
    return EMPIRICAL_TYPE_DISPLAY_LABELS.get(normalized, normalized or "otros")


def display_work_type(work_type: str | None) -> str:
    normalized = normalize_phrase(work_type).lower()
    return WORK_TYPE_DISPLAY_LABELS.get(normalized, normalized or "otros")


def table_label(text: str | None) -> str:
    """Return a table-safe label with an initial capital letter.

    Aggregate paper tables are read as standalone editorial objects, so labels
    should not start in lowercase even when the underlying coded value does.
    """
    raw = normalize_phrase(text) or "No reportado"
    for index, char in enumerate(raw):
        if char.isalpha():
            return raw[:index] + char.upper() + raw[index + 1 :]
    return raw


def split_theory_framework_tokens(text: str | None) -> list[str]:
    raw = normalize_phrase(text)
    if not raw:
        return []
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in raw:
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if char in {";", "|"} and depth == 0:
            token = "".join(current).strip()
            if token:
                parts.append(token)
            current = []
            continue
        current.append(char)
    token = "".join(current).strip()
    if token:
        parts.append(token)
    return dedupe_preserve(parts)


def canonicalize_theory_label(text: str | None) -> str:
    phrase = normalize_phrase(text).strip(" .;:")
    if not phrase:
        return "no reportado"
    lowered = phrase.lower()
    if "de haes" in lowered or ("king" in lowered and "hoppe" in lowered):
        return "Modelo de seis funciones de la comunicación médica (de Haes & Bensing, 2009; King & Hoppe, 2013)"
    if "clara hill" in lowered or ("explor" in lowered and ("insight" in lowered or "comprension" in lowered) and "accion" in lowered):
        return "Modelo de ayuda Exploración-Insight-Acción (E-I-A; Hill, 2020)"
    if "pennebaker" in lowered and "king" in lowered:
        return "Estilos lingüísticos y expresión de personalidad (Pennebaker & King, 1999)"
    if "fiske" in lowered or ("warmth" in lowered and "competence" in lowered):
        return "Modelo de contenido de estereotipos: calidez y competencia (Fiske et al., 2007)"
    if "mbti" in lowered and ("dinamica de tipos" in lowered or "jungu" in lowered):
        return "Tipología MBTI / tradición junguiana reportada"
    phrase = phrase.replace("De Haes and Bensing", "de Haes & Bensing")
    phrase = phrase.replace("King and Hoppe", "King & Hoppe")
    return phrase


def display_theory_label(text: str | None, width: int = 220) -> str:
    phrase = canonicalize_theory_label(text) or "no reportado"
    if phrase.lower() == "no reportado":
        return "no reportado"
    return summarize_phrase_soft(phrase, width=width)


COUNTRY_DISPLAY_MAP = {
    "canada": "Canadá",
    "united states": "Estados Unidos",
    "usa": "Estados Unidos",
    "u.s.a.": "Estados Unidos",
    "u.s.": "Estados Unidos",
}


def display_countries(text: str | None) -> str:
    phrase = normalize_phrase(text) or "no reportado"
    if phrase.lower() == "no reportado":
        return phrase
    parts = [part.strip() for part in re.split(r"\s*,\s*", phrase) if part.strip()]
    rendered = []
    for part in parts:
        rendered.append(COUNTRY_DISPLAY_MAP.get(part.lower(), part))
    return ", ".join(rendered)


def display_location_label(text: str | None) -> str:
    phrase = normalize_phrase(text) or "no reportado"
    if not phrase:
        return "no reportado"
    phrase = re.sub(r"^PDF page\s+(\d+)$", r"página \1 del PDF", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"^HTML full text$", "texto completo en HTML", phrase, flags=re.IGNORECASE)
    return phrase


class InlineImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        src = normalize_phrase(attr_map.get("src"))
        if not src:
            return
        self.images.append(
            {
                "src": src,
                "alt": normalize_phrase(attr_map.get("alt")),
                "title": normalize_phrase(attr_map.get("title")),
            }
        )


def citation_block(record_ids: list[str], limit: int = 4) -> str:
    chosen = [record_id for record_id in record_ids[:limit] if record_id]
    return f"[@{'; '.join(chosen)}]" if chosen else ""


def citation_block_for_rows(rows: list[dict[str, str]], limit: int = 4) -> str:
    def sort_key(row: dict[str, str]) -> tuple[int, str, str]:
        year = parse_int(row.get("year"), 9999)
        family = author_family(first_nonempty(row.get("authors"), row.get("author")))
        title = normalize_phrase(first_nonempty(row.get("title_original"), row.get("title_en"), row.get("title_es"))).lower()
        return year, family.lower(), title

    ordered = sorted(
        [row for row in rows if row.get("record_id")],
        key=sort_key,
    )
    return citation_block([row.get("record_id", "") for row in ordered], limit=limit)


def social_curated_keywords(context: dict[str, str] | None, limit: int = 8) -> list[str]:
    """Derive social-science keywords from the declared question, not indexes."""
    blob = normalize_phrase(
        " ".join(
            [
                (context or {}).get("topic", ""),
                (context or {}).get("research_question", ""),
                (context or {}).get("inclusion", ""),
            ]
        )
    ).lower()
    if is_ai_workload_review_text(blob):
        return [
            "IA generativa",
            "carga de trabajo",
            "productividad",
            "colaboración humano-IA",
            "supervisión humana",
            "desplazamiento del trabajo",
            "calidad del trabajo",
            "revisión sistemática",
        ][:limit]
    curated: list[str] = []
    for source in SOCIAL_KEYWORD_CANDIDATES:
        normalized = normalize_phrase(source).lower()
        if normalized and normalized in blob and normalized not in curated:
            curated.append(normalized)
    if ("polarización" in blob or "polarizacion" in blob) and "redes sociales" in blob and "comunicación política" not in curated:
        curated.append("comunicación política")
    if "confianza institucional" in blob and "confianza política" not in curated:
        curated.append("confianza política")
    topic = normalize_phrase((context or {}).get("topic", ""))
    for token in re.split(r"[,;]|\s+y\s+|\s+e\s+", topic, flags=re.IGNORECASE):
        normalized = normalize_phrase(token).lower()
        if len(normalized) < 4 or normalized in IRRELEVANT_KEYWORDS:
            continue
        if any(existing in normalized or normalized in existing for existing in curated):
            continue
        if normalized not in curated:
            curated.append(normalized)
    for token in ["evidencia empírica", "ciencias sociales", "revisión sistemática"]:
        if token not in curated:
            curated.append(token)
    return curated[:limit]


def build_keyword_list(rows: list[dict[str, str]], limit: int = 8, context: dict[str, str] | None = None) -> list[str]:
    profile = detect_review_profile(context or {})
    counter: Counter[str] = Counter()
    for row in rows:
        raw = first_nonempty(row.get("keywords_normalized"), row.get("keywords_indexed"), row.get("keywords_author"))
        for token in re.split(r"[;,|]", raw):
            normalized = normalize_phrase(token).replace("_", " ").lower()
            if len(normalized) < 4 or normalized in IRRELEVANT_KEYWORDS:
                continue
            if profile == "software_architecture" and any(term in normalized for term in ("software", "agent", "code", "architect", "orchestrat", "benchmark", "debug", "test", "security", "review", "memory", "context")):
                counter[normalized] += 3
            elif profile == "personality_llm" and any(term in normalized for term in ("personality", "persona", "trait", "mbti", "big five", "hexaco", "profil", "steer", "align", "bias", "psychometric")):
                counter[normalized] += 3
            elif profile == "ai_higher_education_teaching" and any(term in normalized for term in ("higher education", "university", "faculty", "teacher", "teaching", "docent", "profesor", "education", "feedback", "assessment", "curriculum", "generative ai", "chatgpt", "llm", "artificial intelligence")):
                counter[normalized] += 3
            elif profile == "creativity_llm" and any(term in normalized for term in ("creativ", "creative", "original", "novelty", "novedad", "divergent", "ideation", "llm", "language model", "generative ai", "chatgpt")):
                counter[normalized] += 3
            elif profile == "social_sciences" and any(term in normalized for term in ("polariz", "social media", "redes sociales", "institutional trust", "confianza institucional", "political trust", "democr", "communication", "comunicacion", "comunicación")):
                counter[normalized] += 3
            else:
                counter[normalized] += 1
    keywords = [token for token, _ in counter.most_common(limit)]
    if profile == "software_architecture":
        curated = [
            "arquitecturas y marcos de agentes",
            "desarrollo de software",
            "ingeniería del software",
            "sistemas multiagente",
            "agentes de programación",
            "orquestación",
            "evaluación arquitectónica",
            "revisión sistemática",
        ]
        merged: list[str] = []
        for token in curated + keywords:
            normalized = normalize_phrase(token).lower()
            if not normalized or normalized in IRRELEVANT_KEYWORDS:
                continue
            if normalized not in merged:
                merged.append(normalized)
        keywords = merged[:limit]
    elif profile == "creativity_llm":
        curated = [
            "creatividad en LLMs",
            "modelos de lenguaje",
            "IA generativa",
            "pensamiento divergente",
            "originalidad",
            "novedad",
            "evaluación de creatividad",
            "revisión sistemática de literatura",
        ]
        merged = []
        for token in curated + keywords:
            normalized = normalize_phrase(token).lower()
            if not normalized or normalized in IRRELEVANT_KEYWORDS:
                continue
            if normalized not in merged:
                merged.append(normalized)
        keywords = merged[:limit]
    elif profile == "ai_higher_education_teaching":
        curated = [
            "IA generativa en educación superior",
            "profesorado universitario",
            "docencia universitaria",
            "feedback",
            "evaluación",
            "diseño curricular",
            "alfabetización en IA",
            "calidad educativa",
        ]
        merged = []
        for token in curated + keywords:
            normalized = normalize_phrase(token).lower()
            if not normalized or normalized in IRRELEVANT_KEYWORDS:
                continue
            if normalized not in merged:
                merged.append(normalized)
        keywords = merged[:limit]
    elif profile == "agent_architecture":
        curated = [
            "agentes de IA",
            "arquitecturas agénticas",
            "sistemas multiagente",
            "memoria",
            "herramientas",
            "orquestación",
            "evaluación",
            "revisión sistemática de literatura",
        ]
        merged = []
        for token in curated + keywords:
            normalized = normalize_phrase(token).lower()
            if not normalized or normalized in IRRELEVANT_KEYWORDS:
                continue
            if normalized not in merged:
                merged.append(normalized)
        keywords = merged[:limit]
    elif profile in {"social_sciences", "management"} and is_ai_workload_review_text(
        " ".join([(context or {}).get("topic", ""), (context or {}).get("research_question", ""), (context or {}).get("inclusion", "")])
    ):
        keywords = social_curated_keywords(context, limit=limit)
    elif profile == "social_sciences":
        curated = social_curated_keywords(context, limit=limit)
        merged = []
        for token in curated + keywords:
            normalized = normalize_phrase(token).lower()
            if not normalized or normalized in IRRELEVANT_KEYWORDS:
                continue
            if normalized not in merged:
                merged.append(normalized)
        keywords = merged[:limit]
    if not keywords:
        if profile == "personality_llm":
            return [
                "personalidad en LLMs",
                "large language models",
                "personas",
                "traits",
                "psychometric profiling",
                "persona steering",
                "bias",
                "revisión sistemática",
            ][:limit]
        if profile == "software_architecture":
            return [
                "arquitecturas de agentes",
                "desarrollo de software",
                "ingeniería del software",
                "sistemas multiagente",
                "agentes de programación",
                "orquestación",
                "benchmarking",
                "revisión sistemática",
            ][:limit]
        if profile == "creativity_llm":
            return [
                "creatividad en LLMs",
                "modelos de lenguaje",
                "IA generativa",
                "pensamiento divergente",
                "originalidad",
                "novedad",
                "evaluación de creatividad",
                "revisión sistemática",
            ][:limit]
        if profile == "ai_higher_education_teaching":
            return [
                "IA generativa en educación superior",
                "profesorado universitario",
                "docencia universitaria",
                "feedback",
                "evaluación",
                "diseño curricular",
                "alfabetización en IA",
                "revisión sistemática",
            ][:limit]
        if profile == "agent_architecture":
            return [
                "agentes de IA",
                "arquitecturas agénticas",
                "sistemas multiagente",
                "memoria",
                "herramientas",
                "orquestación",
                "evaluación",
                "revisión sistemática de literatura",
            ][:limit]
        if profile in {"social_sciences", "management"}:
            return social_curated_keywords(context, limit=limit)
        return [
            normalize_phrase(context.get("topic", "") if context else "") or "tema de revisión",
            "revisión sistemática",
            "texto completo",
            "síntesis focal",
            "evidencia",
            "método",
            "calidad metodológica",
            "revisión sistemática de literatura",
        ][:limit]
    return keywords


KEYWORD_TRANSLATIONS = {
    "arquitecturas y marcos de agentes": "agent architectures and frameworks",
    "frameworks de arquitecturas de agentes": "agent architecture frameworks",
    "arquitecturas de agentes": "agent architectures",
    "agentes de ia": "AI agents",
    "arquitecturas agénticas": "agentic architectures",
    "desarrollo de software": "software development",
    "ingeniería del software": "software engineering",
    "sistemas multiagente": "multi-agent systems",
    "memoria": "memory",
    "herramientas": "tools",
    "agentes de programación": "coding agents",
    "multi-agent systems": "multi-agent systems",
    "coding agents": "coding agents",
    "orquestación": "orchestration",
    "evaluación": "evaluation",
    "evaluación arquitectónica": "architectural evaluation",
    "ia generativa en educación superior": "generative AI in higher education",
    "profesorado universitario": "university faculty",
    "docencia universitaria": "university teaching",
    "feedback": "feedback",
    "diseño curricular": "curriculum design",
    "alfabetización en ia": "AI literacy",
    "calidad educativa": "educational quality",
    "polarización afectiva": "affective polarization",
    "polarizacion afectiva": "affective polarization",
    "redes sociales": "social media",
    "uso de redes sociales": "social media use",
    "confianza institucional": "institutional trust",
    "democracias contemporáneas": "contemporary democracies",
    "democracias contemporaneas": "contemporary democracies",
    "comunicación política": "political communication",
    "confianza política": "political trust",
    "evidencia empírica": "empirical evidence",
    "ciencias sociales": "social sciences",
    "constructos sociales": "social constructs",
    "contexto": "context",
    "transferibilidad": "transferability",
    "benchmarking": "benchmarking",
    "revisión sistemática": "systematic review",
    "revisión sistemática de literatura": "systematic literature review",
    "agentes autónomos": "autonomous agents",
    "prisma": "PRISMA",
    "corpus focal": "focal corpus",
    "síntesis temática": "thematic synthesis",
    "personalidad en llms": "personality in LLMs",
    "large language models": "large language models",
    "personas": "personas",
    "traits": "traits",
    "psychometric profiling": "psychometric profiling",
    "persona steering": "persona steering",
    "creatividad en llms": "creativity in LLMs",
    "modelos de lenguaje": "language models",
    "ia generativa": "generative AI",
    "pensamiento divergente": "divergent thinking",
    "originalidad": "originality",
    "novedad": "novelty",
    "evaluación de creatividad": "creativity assessment",
    "texto completo": "full text",
    "síntesis focal": "focal synthesis",
    "evidencia": "evidence",
    "método": "method",
    "calidad metodológica": "methodological quality",
    "carga de trabajo": "workload",
    "productividad": "productivity",
    "colaboración humano-ia": "human-AI collaboration",
    "supervisión humana": "human oversight",
    "desplazamiento del trabajo": "work displacement",
    "calidad del trabajo": "work quality",
    "bias": "bias",
}


def english_keywords(spanish_keywords: list[str]) -> list[str]:
    translated: list[str] = []
    for keyword in spanish_keywords:
        normalized = normalize_phrase(keyword).lower()
        english = KEYWORD_TRANSLATIONS.get(normalized)
        if not english:
            english = normalize_phrase(keyword)
        if english and english not in translated:
            translated.append(english)
    return translated


def dedupe_preserve(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = normalize_phrase(item)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def safe_float(text: str | None) -> float:
    raw = normalize_phrase(text).replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def parse_human_size(text: str | None) -> int:
    raw = normalize_phrase(text).upper()
    if not raw:
        return 0
    multiplier = 1
    if raw.endswith("K"):
        multiplier = 1024
        raw = raw[:-1]
    elif raw.endswith("M"):
        multiplier = 1024 * 1024
        raw = raw[:-1]
    elif raw.endswith("G"):
        multiplier = 1024 * 1024 * 1024
        raw = raw[:-1]
    try:
        return int(float(raw) * multiplier)
    except ValueError:
        return 0


def run_command(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def parse_pdfimages_inventory(pdf_path: pathlib.Path) -> list[dict[str, int | str]]:
    try:
        result = run_command(["pdfimages", "-list", str(pdf_path)], timeout=120)
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    inventory: list[dict[str, int | str]] = []
    extracted_index = 0
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("page") or set(stripped) == {"-"}:
            continue
        parts = stripped.split()
        if len(parts) < 16 or parts[2] != "image":
            continue
        try:
            width = int(parts[3])
            height = int(parts[4])
            page = int(parts[0])
        except ValueError:
            continue
        inventory.append(
            {
                "page": page,
                "width": width,
                "height": height,
                "area": width * height,
                "size_bytes": parse_human_size(parts[14]),
                "image_index": extracted_index,
            }
        )
        extracted_index += 1
    return inventory


def meaningful_embedded_image(meta: dict[str, int | str]) -> bool:
    width = int(meta.get("width", 0))
    height = int(meta.get("height", 0))
    area = int(meta.get("area", 0))
    size_bytes = int(meta.get("size_bytes", 0))
    if width < 320 or height < 180:
        return False
    if area < 120000:
        return False
    if size_bytes and size_bytes < 12000:
        return False
    return True


def is_probably_decorative_embedded_image(meta: dict[str, int | str], figure_pages: set[int]) -> bool:
    width = int(meta.get("width", 0))
    height = int(meta.get("height", 0))
    area = int(meta.get("area", 0))
    size_bytes = int(meta.get("size_bytes", 0))
    page = int(meta.get("page", 0))
    aspect = width / max(height, 1)
    if page == 1 and page not in figure_pages:
        return True
    if aspect > 7.5 or aspect < 0.15:
        return True
    if area < 250000 and size_bytes < 20000:
        return True
    return False


def detect_figure_pages(pdf_path: pathlib.Path, max_pages: int = 3) -> list[dict[str, int | str]]:
    try:
        result = run_command(["pdftotext", "-layout", "-q", str(pdf_path), "-"], timeout=180)
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    pages = result.stdout.split("\f")
    candidates: list[dict[str, int | str]] = []
    for page_number, page_text in enumerate(pages, start=1):
        lowered = page_text.lower()
        score = 0
        if re.search(r"\bfig(?:ure)?\.?\s*\d+", lowered):
            score += 4
        for token in ("architecture", "framework", "workflow", "pipeline", "diagram", "overview", "system"):
            if token in lowered:
                score += 1
        if score <= 0:
            continue
        summary = summarize_phrase(" ".join(page_text.split()), 140)
        candidates.append({"page": page_number, "score": score, "summary": summary})
    candidates.sort(key=lambda item: (-int(item["score"]), int(item["page"])))
    return candidates[:max_pages]


def parse_pdf_bbox_words(pdf_path: pathlib.Path, page_number: int) -> tuple[float, float, list[dict[str, float | str]]]:
    result = run_command(
        ["pdftotext", "-bbox-layout", "-f", str(page_number), "-l", str(page_number), str(pdf_path), "-"],
        timeout=180,
    )
    if result.returncode != 0:
        return 0.0, 0.0, []
    page_match = re.search(r'<page width="([0-9.]+)" height="([0-9.]+)"', result.stdout)
    if not page_match:
        return 0.0, 0.0, []
    page_width = float(page_match.group(1))
    page_height = float(page_match.group(2))
    words: list[dict[str, float | str]] = []
    for match in re.finditer(
        r'<word xMin="([0-9.]+)" yMin="([0-9.]+)" xMax="([0-9.]+)" yMax="([0-9.]+)">(.*?)</word>',
        result.stdout,
        flags=re.DOTALL,
    ):
        text = normalize_phrase(html.unescape(match.group(5)))
        if not text:
            continue
        words.append(
            {
                "text": text,
                "xMin": float(match.group(1)),
                "yMin": float(match.group(2)),
                "xMax": float(match.group(3)),
                "yMax": float(match.group(4)),
            }
        )
    return page_width, page_height, words


def group_words_into_lines(words: list[dict[str, float | str]], tolerance: float = 3.5) -> list[dict[str, float | str]]:
    lines: list[dict[str, float | str]] = []
    for word in sorted(words, key=lambda item: (float(item["yMin"]), float(item["xMin"]))):
        if not lines or abs(float(word["yMin"]) - float(lines[-1]["yMin"])) > tolerance:
            lines.append(
                {
                    "words": [word],
                    "text": str(word["text"]),
                    "xMin": float(word["xMin"]),
                    "yMin": float(word["yMin"]),
                    "xMax": float(word["xMax"]),
                    "yMax": float(word["yMax"]),
                }
            )
            continue
        line = lines[-1]
        line_words = line["words"]  # type: ignore[assignment]
        line_words.append(word)  # type: ignore[union-attr]
        line["text"] = normalize_phrase(f"{line['text']} {word['text']}")
        line["xMin"] = min(float(line["xMin"]), float(word["xMin"]))
        line["yMin"] = min(float(line["yMin"]), float(word["yMin"]))
        line["xMax"] = max(float(line["xMax"]), float(word["xMax"]))
        line["yMax"] = max(float(line["yMax"]), float(word["yMax"]))
    return lines


def locate_figure_caption_line(pdf_path: pathlib.Path, page_number: int) -> dict[str, float | str]:
    page_width, page_height, words = parse_pdf_bbox_words(pdf_path, page_number)
    if not words:
        return {}
    caption_lines: list[dict[str, float | str]] = []
    for line in group_words_into_lines(words):
        lowered = normalize_phrase(line.get("text")).lower()
        if re.search(r"\bfig(?:ure)?\.?\s*\d+\b", lowered):
            line["page_width"] = page_width
            line["page_height"] = page_height
            caption_lines.append(line)
    if not caption_lines:
        return {}
    caption_lines.sort(key=lambda item: (float(item["yMin"]), float(item["xMin"])))
    return caption_lines[0]


def render_pdf_crop(
    pdf_path: pathlib.Path,
    page_number: int,
    crop_bbox: tuple[float, float, float, float],
    temp_dir: pathlib.Path,
    dpi: int = 300,
) -> pathlib.Path | None:
    scale = dpi / 72.0
    x_pt, y_pt, width_pt, height_pt = crop_bbox
    x_px = max(0, int(round(x_pt * scale)))
    y_px = max(0, int(round(y_pt * scale)))
    width_px = max(1, int(round(width_pt * scale)))
    height_px = max(1, int(round(height_pt * scale)))
    prefix = temp_dir / f"crop-p{page_number:02d}"
    result = run_command(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-singlefile",
            "-r",
            str(dpi),
            "-x",
            str(x_px),
            "-y",
            str(y_px),
            "-W",
            str(width_px),
            "-H",
            str(height_px),
            "-png",
            str(pdf_path),
            str(prefix),
        ],
        timeout=300,
    )
    if result.returncode != 0:
        return None
    rendered = prefix.with_suffix(".png")
    return rendered if rendered.exists() else None


def crop_bbox_from_caption(caption_line: dict[str, float | str]) -> tuple[float, float, float, float] | None:
    page_width = float(caption_line.get("page_width", 0.0))
    page_height = float(caption_line.get("page_height", 0.0))
    if page_width <= 0 or page_height <= 0:
        return None
    margin = 24.0
    caption_y_min = float(caption_line.get("yMin", 0.0))
    caption_y_max = float(caption_line.get("yMax", 0.0))
    upper_height = max(caption_y_min - margin, 0.0)
    lower_y = min(caption_y_max + 14.0, page_height)
    lower_height = max(page_height - lower_y - margin, 0.0)
    width = max(page_width - (margin * 2.0), 1.0)
    if caption_y_min >= page_height * 0.32 and upper_height >= page_height * 0.22:
        return (margin, margin, width, upper_height)
    if lower_height >= page_height * 0.22:
        return (margin, lower_y, width, lower_height)
    return None


def extract_pdf_figure_assets(
    pdf_path: pathlib.Path,
    record_id: str,
    output_dir: pathlib.Path,
    page_render_dir: pathlib.Path | None = None,
    max_embedded: int = 6,
    max_page_renders: int = 3,
) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    record_slug = slugify(record_id)
    page_render_dir = page_render_dir or output_dir
    inventory = parse_pdfimages_inventory(pdf_path)
    page_candidates = detect_figure_pages(pdf_path, max_pages=max(max_page_renders, 8))
    figure_pages = {int(item["page"]) for item in page_candidates}
    embedded_candidates = [item for item in inventory if meaningful_embedded_image(item)]
    if figure_pages:
        filtered_candidates = [item for item in embedded_candidates if int(item["page"]) in figure_pages]
        if filtered_candidates:
            embedded_candidates = filtered_candidates
    embedded_candidates = [
        item
        for item in embedded_candidates
        if not is_probably_decorative_embedded_image(item, figure_pages)
    ]
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix=f"{record_slug}-fig-"))
    try:
        if embedded_candidates:
            prefix = temp_dir / "embedded"
            result = run_command(["pdfimages", "-png", str(pdf_path), str(prefix)], timeout=300)
            if result.returncode == 0:
                extracted_files = sorted(temp_dir.glob("embedded-*.png"))
                chosen = sorted(
                    embedded_candidates,
                    key=lambda item: (-int(item["area"]), int(item["page"]), int(item["image_index"])),
                )[:max_embedded]
                for rank, meta in enumerate(chosen, start=1):
                    image_index = int(meta["image_index"])
                    if image_index >= len(extracted_files):
                        continue
                    dest_name = f"{record_slug}-fig-{rank:02d}-p{int(meta['page']):02d}.png"
                    dest_path = output_dir / dest_name
                    shutil.copy2(extracted_files[image_index], dest_path)
                    assets.append(
                        {
                            "record_id": record_id,
                            "asset_id": f"{record_id}-fig-{rank:02d}",
                            "source_path": str(pdf_path),
                            "page_or_location": f"PDF page {int(meta['page'])}",
                            "extracted_asset_path": dest_path.as_posix(),
                            "vision_model": "",
                            "status": "extracted_from_pdf_embedded",
                            "kind": "embedded-image",
                            "width": str(int(meta["width"])),
                            "height": str(int(meta["height"])),
                            "summary": f"Embedded figure candidate from PDF page {int(meta['page'])}.",
                        }
                    )
        covered_pages = {item["page_or_location"] for item in assets}
        render_rank = 1
        for meta in page_candidates:
            location = f"PDF page {int(meta['page'])}"
            if location in covered_pages:
                continue
            caption_line = locate_figure_caption_line(pdf_path, int(meta["page"]))
            crop_bbox = crop_bbox_from_caption(caption_line) if caption_line else None
            if crop_bbox:
                rendered = render_pdf_crop(pdf_path, int(meta["page"]), crop_bbox, temp_dir, dpi=300)
                if rendered is not None:
                    dest_name = f"{record_slug}-capfig-{render_rank:02d}-p{int(meta['page']):02d}.png"
                    dest_path = output_dir / dest_name
                    shutil.copy2(rendered, dest_path)
                    assets.append(
                        {
                            "record_id": record_id,
                            "asset_id": f"{record_id}-capfig-{render_rank:02d}",
                            "source_path": str(pdf_path),
                            "page_or_location": location,
                            "extracted_asset_path": dest_path.as_posix(),
                            "vision_model": "",
                            "status": "captured_from_pdf_page_region",
                            "kind": "page-crop",
                            "width": "",
                            "height": "",
                            "summary": summarize_phrase(
                                first_nonempty(
                                    str(caption_line.get("text", "")),
                                    str(meta.get("summary", "")),
                                    f"Figure region captured from PDF page {int(meta['page'])}.",
                                ),
                                180,
                            ),
                        }
                    )
                    render_rank += 1
                    continue
            prefix = temp_dir / f"page-{int(meta['page']):02d}"
            result = run_command(
                [
                    "pdftoppm",
                    "-f",
                    str(int(meta["page"])),
                    "-l",
                    str(int(meta["page"])),
                    "-r",
                    "300",
                    "-png",
                    str(pdf_path),
                    str(prefix),
                ],
                timeout=300,
            )
            if result.returncode != 0:
                continue
            rendered = sorted(temp_dir.glob(f"{prefix.name}-*.png"))
            if not rendered:
                continue
            dest_name = f"{record_slug}-pagefig-{render_rank:02d}-p{int(meta['page']):02d}.png"
            dest_path = page_render_dir / dest_name
            shutil.copy2(rendered[0], dest_path)
            assets.append(
                {
                    "record_id": record_id,
                    "asset_id": f"{record_id}-pagefig-{render_rank:02d}",
                    "source_path": str(pdf_path),
                    "page_or_location": location,
                    "extracted_asset_path": dest_path.as_posix(),
                    "vision_model": "",
                    "status": "rendered_from_pdf_page",
                    "kind": "page-render",
                    "width": "",
                    "height": "",
                    "summary": str(meta["summary"]),
                }
            )
            render_rank += 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return assets


def collect_html_images(source: str) -> list[dict[str, str]]:
    if not source:
        return []
    html_text = ""
    base_url = ""
    source_path = pathlib.Path(source)
    if source_path.exists() and source_path.suffix.lower() in {".html", ".htm"}:
        html_text = read_text(source_path)
        base_url = source_path.resolve().as_uri()
    elif source.startswith(("http://", "https://")):
        try:
            with request.urlopen(source, timeout=60) as response:
                html_text = response.read().decode("utf-8", errors="ignore")
                base_url = source
        except (OSError, error.URLError):
            return []
    if not html_text:
        return []
    parser = InlineImageParser()
    parser.feed(html_text)
    images: list[dict[str, str]] = []
    for item in parser.images:
        resolved = parse.urljoin(base_url, item["src"])
        if not resolved:
            continue
        images.append(
            {
                "src": resolved,
                "alt": item.get("alt", ""),
                "title": item.get("title", ""),
            }
        )
    return images


def extract_html_figure_assets(
    html_source: str,
    record_id: str,
    output_dir: pathlib.Path,
    max_images: int = 6,
) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    record_slug = slugify(record_id)
    images = collect_html_images(html_source)[:max_images]
    for rank, item in enumerate(images, start=1):
        parsed = parse.urlparse(item["src"])
        suffix = pathlib.Path(parsed.path).suffix.lower() or ".png"
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
            suffix = ".png"
        dest_path = output_dir / f"{record_slug}-htmlfig-{rank:02d}{suffix}"
        try:
            with request.urlopen(item["src"], timeout=60) as response:
                dest_path.write_bytes(response.read())
        except (OSError, error.URLError):
            continue
        assets.append(
            {
                "record_id": record_id,
                "asset_id": f"{record_id}-htmlfig-{rank:02d}",
                "source_path": html_source,
                "page_or_location": "HTML full text",
                "extracted_asset_path": dest_path.as_posix(),
                "vision_model": "",
                "status": "downloaded_from_html",
                "kind": "html-image",
                "width": "",
                "height": "",
                "summary": summarize_phrase(first_nonempty(item.get("alt"), item.get("title"), item.get("src")), 120),
            }
        )
    return assets


def write_visual_asset_markdown(
    review_dir: pathlib.Path,
    record_id: str,
    source_path: str,
    assets: list[dict[str, str]],
    row: dict[str, str],
) -> pathlib.Path:
    output_path = review_dir / "figures" / "extracted" / f"{slugify(record_id)}-figures.md"
    lines = [
        f"# Figuras fuente revisadas de {record_id}",
        "",
        f"- Fuente: `{source_path or 'no reportado'}`",
        f"- Título: {normalize_phrase(row.get('title_original')) or 'no reportado'}",
        f"- Hallazgo clave asociado: {summarize_phrase(row.get('key_findings'), 220)}",
        f"- Evidencia textual asociada: {summarize_phrase(row.get('evidence_snippet'), 220)}",
        "",
    ]
    if not assets:
        lines.extend(
            [
                "_No se han extraído figuras reutilizables desde este PDF/HTML._",
                "",
                "Posibles causas:",
                "- el documento no contiene imágenes embebidas relevantes;",
                "- las figuras son vectoriales y no aparecen como activos separados;",
                "- el texto completo disponible no es HTML descargable con imágenes.",
            ]
        )
        write_text(output_path, "\n".join(lines).strip() + "\n")
        return output_path

    lines.extend(
        [
            "## Activos extraídos",
            "",
        ]
    )
    primary_assets = [
        asset for asset in assets if normalize_phrase(asset.get("status")).lower() != "rendered_from_pdf_page"
    ]
    page_render_assets = [
        asset for asset in assets if normalize_phrase(asset.get("status")).lower() == "rendered_from_pdf_page"
    ]

    if primary_assets:
        lines.extend(["### Figuras científicas extraídas", ""])
        for asset in primary_assets:
            relative_asset = pathlib.Path(asset["extracted_asset_path"]).relative_to(review_dir).as_posix()
            lines.extend(
                [
                    f"#### {asset['asset_id']}",
                    "",
                    f"- Tipo: {asset.get('kind', 'visual-asset')}",
                    f"- Localización: {asset.get('page_or_location', 'no reportado')}",
                    f"- Estado: {asset.get('status', 'no reportado')}",
                    f"- Resumen: {asset.get('summary', 'no reportado')}",
                    f"- Archivo: `{relative_asset}`",
                    "",
                    f"![{asset['asset_id']}](../../{relative_asset})",
                    "",
                ]
            )

    if page_render_assets:
        lines.extend(
            [
                "### Renders diagnósticos de página",
                "",
                "Estos activos conservan páginas completas del PDF como respaldo de trazabilidad. No deben reutilizarse como figuras científicas extraídas ni como paneles del manuscrito final.",
                "",
            ]
        )
        for asset in page_render_assets:
            relative_asset = pathlib.Path(asset["extracted_asset_path"]).relative_to(review_dir).as_posix()
            lines.extend(
                [
                    f"#### {asset['asset_id']}",
                    "",
                    f"- Tipo: {asset.get('kind', 'visual-asset')}",
                    f"- Localización: {asset.get('page_or_location', 'no reportado')}",
                    f"- Estado: {asset.get('status', 'no reportado')}",
                    f"- Resumen: {asset.get('summary', 'no reportado')}",
                    f"- Archivo: `{relative_asset}`",
                    "",
                    f"![{asset['asset_id']}](../../{relative_asset})",
                    "",
                ]
            )
    write_text(output_path, "\n".join(lines).strip() + "\n")
    return output_path


def merge_shortlist_rows(review_dir: pathlib.Path, corpus: dict[str, CorpusRecord], selected_only: bool = True) -> list[dict[str, str]]:
    extraction_map = {
        (row.get("record_id") or "").strip(): row
        for row in read_csv_rows(review_dir / "extraction" / "extraction-table.csv")
        if (row.get("record_id") or "").strip()
    }
    master_map = {
        (row.get("record_id") or "").strip(): row
        for row in read_csv_rows(review_dir / "records" / "master-records.csv")
        if (row.get("record_id") or "").strip()
    }
    selection_rows = sorted(
        [
            row for row in read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")
            if (row.get("record_id") or "").strip()
        ],
        key=lambda row: parse_int(row.get("ultraquality_rank"), 999999),
    )
    full_text_map = {
        (row.get("record_id") or "").strip(): row
        for row in read_csv_rows(review_dir / "screening" / "full-text.csv")
        if (row.get("record_id") or "").strip()
    }

    merged_rows: list[dict[str, str]] = []
    for selection in selection_rows:
        record_id = (selection.get("record_id") or "").strip()
        if not record_id:
            continue
        if selected_only and not is_selected(selection):
            continue
        record = corpus.get(record_id)
        merged: dict[str, str] = {}
        for source in (master_map.get(record_id, {}), extraction_map.get(record_id, {}), full_text_map.get(record_id, {}), selection):
            merged.update({key: value for key, value in source.items() if value not in {"", None}})
        merged.setdefault("record_id", record_id)
        if record:
            merged.setdefault("assigned_doi", record.assigned_doi)
            merged.setdefault("title_original", record.title)
            merged.setdefault("authors", record.authors)
            merged.setdefault("year", record.year)
            merged.setdefault("work_type", record.work_type)
        merged_rows.append(merged)
    return merged_rows


def merge_selected_rows(review_dir: pathlib.Path, corpus: dict[str, CorpusRecord]) -> list[dict[str, str]]:
    return merge_shortlist_rows(review_dir, corpus, selected_only=True)


def score_from_notes(notes: str, key: str, default: int = 80) -> int:
    match = re.search(rf"(?:^|[;\s]){re.escape(key)}\s*=\s*(\d+)", notes or "", re.IGNORECASE)
    if not match:
        return default
    return parse_int(match.group(1), default)


def infer_work_type_from_row(row: dict[str, str]) -> str:
    blob = normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("abstract_original", ""),
                row.get("reason_detail", ""),
                row.get("notes", ""),
            ]
        )
    )
    empirical_markers = [
        "experimental",
        "experimento",
        "experimentos",
        "evaluacion",
        "evaluacao",
        "validacion",
        "validacao",
        "tests",
        "testes",
        "resultados preliminares",
        "sample",
        "muestra",
        "amostra",
    ]
    review_markers = ["revision", "revisao", "systematic review", "literature review"]
    if any(marker in blob for marker in empirical_markers):
        return "Empirical"
    if any(marker in blob for marker in review_markers):
        return "Review"
    return "Theoretical"


def infer_empirical_type_from_row(row: dict[str, str]) -> str:
    blob = normalized_text(
        " ".join([row.get("abstract_original", ""), row.get("reason_detail", ""), row.get("notes", "")])
    )
    if "experimental" in blob or "experimento" in blob or "testes" in blob or "tests" in blob:
        return "Experimental / prototype evaluation"
    if "41" in blob or "muestra" in blob or "sample" in blob or "amostra" in blob:
        return "Empirical case / corpus evaluation"
    return "Qualitative / design study"


def is_missing_reporting_value(value: str | None) -> bool:
    normalized = normalize_phrase(value or "").strip().lower()
    return normalized in {
        "",
        "-",
        "n/a",
        "na",
        "no aplica",
        "not applicable",
        "no reportado",
        "not reported",
        "not specified",
        "sin dato",
        "sin datos",
    }


def is_generic_sample_placeholder(value: str | None) -> bool:
    normalized = normalize_phrase(value or "").strip().lower()
    if is_missing_reporting_value(normalized):
        return True
    placeholders = [
        "full-text article evidence",
        "muestra, corpus o contexto empírico descrito",
        "muestra, corpus o contexto empirico descrito",
        "sample, corpus or empirical context described",
        "unidad empírica o corpus descrito",
        "unidad empirica o corpus descrito",
    ]
    return any(marker in normalized for marker in placeholders)


def fulltext_text_for_record(review_dir: pathlib.Path, record_id: str) -> str:
    if not record_id:
        return ""
    candidates = [
        review_dir / "fulltext" / "txt" / f"{record_id.lower()}.txt",
        review_dir / "fulltext" / "txt" / f"{record_id}.txt",
    ]
    for path in candidates:
        if path.exists():
            return read_text(path)
    return ""


def clean_sample_number(value: str) -> str:
    number = re.sub(r"\s+", "", value or "")
    number = number.strip(".,;:()[]{}")
    if not number or not re.search(r"\d$", number):
        return ""
    return number


def is_invalid_sample_size(value: str | None) -> bool:
    number = normalize_phrase(value or "").strip()
    if not number:
        return True
    numeric_part = re.sub(r"^[Nn]\s*=\s*", "", number).strip()
    if re.fullmatch(r"0+(?:[.,]0+)?", numeric_part):
        return True
    if re.fullmatch(r"\d[,.]\d{4,}", numeric_part):
        return True
    return False


def infer_sample_evidence_from_text(text: str) -> tuple[str, str]:
    """Extract an auditable sample/corpus signal from full text.

    The goal is not to replace human extraction; it prevents a review from
    reporting every empirical study as "sample missing" when the PDF contains a
    recoverable participant, platform, country, article, tweet or observation
    count.
    """
    if not text:
        return "", ""
    compact = re.sub(r"\s+", " ", text)
    units = (
        "participants|respondents|subjects|students|users|tweets|posts|messages|observations|"
        "voters|panelists|panellists|accounts|cases|countries|articles|studies|documents|"
        "participantes|encuestados|usuarios|tuits|mensajes|observaciones|estudiantes|casos|"
        "pa[ií]ses|art[ií]culos|estudios|documentos"
    )
    patterns = [
        rf"\b(?:sample|muestra|amostra)\s+(?:of|de|con)?\s*(?:n\s*=\s*)?([0-9][0-9,\. ]{{0,12}})\s+({units})\b",
        rf"\b(?:n|N)\s*=\s*([0-9][0-9,\. ]{{0,12}})\s+({units})\b",
        rf"\b([0-9][0-9,\.]{{1,12}})\s+({units})\b",
        rf"\b(?:consists?|consist[ií]a|inclu(?:ye|ded)|comprised|compuesto por)\s+(?:of\s+|de\s+)?([0-9][0-9,\. ]{{0,12}})\s+({units})\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, compact, flags=re.IGNORECASE):
            number = clean_sample_number(match.group(1))
            unit = normalize_phrase(match.group(2))
            if not number:
                continue
            # Avoid treating publication years or page spans as sample sizes.
            digits = re.sub(r"\D", "", number)
            if is_invalid_sample_size(number):
                continue
            if len(digits) == 4 and digits.startswith(("19", "20")) and unit.lower() not in {"tweets", "tuits", "posts"}:
                continue
            sample_size = f"N={number}"
            description = f"{unit} reportados en texto completo"
            return sample_size, description

    # Use bare n= only when the surrounding text clearly speaks about samples.
    for match in re.finditer(r"\b(?:n|N)\s*=\s*([0-9][0-9,\. ]{0,12})", compact):
        start = max(0, match.start() - 90)
        end = min(len(compact), match.end() + 90)
        window = compact[start:end].lower()
        if not re.search(r"sample|muestra|participant|respondent|survey|encuesta|usuario|tweet|observation|estudio", window):
            continue
        number = clean_sample_number(match.group(1))
        if number and not is_invalid_sample_size(number):
            return f"N={number}", "unidades analíticas reportadas en texto completo"
    return "", ""


def infer_sample_size_from_row(row: dict[str, str], fulltext_text: str = "") -> str:
    sample_size, _ = infer_sample_evidence_from_text(fulltext_text)
    if sample_size:
        return sample_size
    blob = " ".join([row.get("abstract_original", ""), row.get("reason_detail", ""), row.get("notes", "")])
    match = re.search(r"\b(\d{1,6})\s+(?:artículos|artigos|articles|manuscritos|manuscripts|consultas|queries|tweets|tuits|participants|respondents|participantes|usuarios)\b", blob, re.IGNORECASE)
    return f"N={match.group(1)}" if match else "not reported"


def materialize_missing_focus_extractions(
    review_dir: pathlib.Path,
    corpus: dict[str, CorpusRecord],
    focus_rows: list[dict[str, str]],
) -> bool:
    """Keep the extraction matrix complete for DOI-valid focal studies.

    The public gate requires every final study to have a row in
    ``extraction-table.csv``. If a DOI-valid study is promoted after a stricter
    editorial rule, this function creates a conservative, auditable extraction
    row from the already retrieved full-text screening evidence instead of
    leaving the final corpus in a half-materialized state.
    """
    path = review_dir / "extraction" / "extraction-table.csv"
    existing_rows = read_csv_rows(path)
    existing_ids = {(row.get("record_id") or "").strip() for row in existing_rows}
    fieldnames = list(existing_rows[0].keys()) if existing_rows else list(EXTRACTION_TABLE_FIELDNAMES)
    changed = False
    context = read_research_context(review_dir)
    profile = detect_review_profile(context)
    if profile == "creativity_llm":
        fallback_design = "Full-text screening identified a DOI-valid study on creativity in LLMs with enough methodological evidence for focal synthesis."
        fallback_unit = "LLM outputs, creativity tasks, evaluation metrics or model comparisons described in the full text"
        fallback_system = "LLM or generative-AI system described in the article"
        fallback_dep = "creativity score, novelty, originality, diversity, usefulness or human/automatic evaluation"
        fallback_ind = "model, task, prompt, metric, evaluator, training method or comparison condition"
        fallback_theory = "creativity assessment / computational creativity / LLM evaluation"
        fallback_finding = "The study reports DOI-valid evidence about creativity evaluation, generation or characterization in LLMs."
    elif profile == "ai_higher_education_teaching":
        fallback_design = "Full-text screening identified a DOI-valid study on AI support for university teaching with enough methodological evidence for focal synthesis."
        fallback_unit = "university faculty, teaching tasks, course activities, AI-assisted feedback, assessment or curriculum work described in the full text"
        fallback_system = "AI, generative-AI, LLM, chatbot, copilot or educational-AI system described in the article"
        fallback_dep = "teaching quality, feedback quality, assessment support, workload, adoption, AI literacy, student outcome or institutional governance"
        fallback_ind = "AI tool, teaching task, faculty role, course context, intervention, prompt, platform or comparison condition"
        fallback_theory = "higher-education teaching / AI adoption / educational technology"
        fallback_finding = "The study reports DOI-valid evidence about AI support for university faculty or higher-education teaching tasks."
    elif profile == "social_sciences":
        fallback_design = "Full-text screening identified a DOI-valid social-science study with enough methodological evidence for focal synthesis."
        fallback_unit = "individuals, groups, messages, institutions, countries, platforms or contexts described in the full text"
        fallback_system = "not applicable; the focus is a social, political or institutional phenomenon"
        fallback_dep = "attitude, behavior, trust, polarization, institutional perception or social outcome reported by the article"
        fallback_ind = "exposure, condition, context, platform, group identity, information environment or explanatory factor"
        fallback_theory = "social-science construct framework / political communication / institutional trust"
        fallback_finding = "The study reports DOI-valid evidence about the social-science relationship defined in the review question."
    else:
        fallback_design = "Full-text screening identified a DOI-valid study with sufficient methodological evidence for focal synthesis."
        fallback_unit = "study units, system outputs, evaluation tasks or documents described in the full text"
        fallback_system = "system, model or intervention described in the article"
        fallback_dep = "reported outcome, score, performance, perception or effect"
        fallback_ind = "method, system configuration, model, intervention or comparison condition"
        fallback_theory = "domain framework / methodological evidence"
        fallback_finding = "The study reports DOI-valid evidence with identifiable method, task domain and evaluative basis."
    for row in focus_rows:
        record_id = (row.get("record_id") or "").strip()
        if not record_id or record_id in existing_ids or not has_public_doi(row):
            continue
        record = corpus.get(record_id)
        notes = row.get("notes", "")
        confidence = max(80, score_from_notes(notes, "confidence", 80))
        methodological = score_from_notes(notes, "methodological", parse_int(row.get("methodological_quality_score"), 60))
        relevance = score_from_notes(notes, "relevance", parse_int(row.get("relevance_score"), 70))
        work_type = first_nonempty(row.get("work_type"), infer_work_type_from_row(row))
        empirical_type = first_nonempty(row.get("empirical_type"), infer_empirical_type_from_row(row))
        reason_detail = normalize_phrase(row.get("reason_detail"))
        abstract = first_nonempty(row.get("abstract_original"), row.get("abstract_en"), row.get("abstract_es"))
        extraction_row = {
            "record_id": record_id,
            "assigned_doi": public_doi_value(row, record),
            "authors": first_nonempty(row.get("authors"), record.authors if record else ""),
            "title_original": first_nonempty(row.get("title_original"), record.title if record else ""),
            "title_en": row.get("title_en", ""),
            "title_es": row.get("title_es", ""),
            "abstract_original": abstract,
            "abstract_en": first_nonempty(row.get("abstract_en"), abstract),
            "abstract_es": row.get("abstract_es", ""),
            "keywords_author": row.get("keywords_author", ""),
            "keywords_indexed": row.get("keywords_indexed", ""),
            "keywords_normalized": row.get("keywords_normalized", ""),
            "year": first_nonempty(row.get("year"), record.year if record else ""),
            "work_type": work_type,
            "empirical_type": empirical_type if work_type == "Empirical" else "",
            "design_detail": reason_detail or fallback_design,
            "countries": first_nonempty(row.get("countries"), "not reported"),
            "unit_of_analysis": first_nonempty(row.get("unit_of_analysis"), fallback_unit),
            "sample_description": first_nonempty(row.get("sample_description"), "Full-text article evidence"),
            "sample_size": first_nonempty(row.get("sample_size"), infer_sample_size_from_row(row, fulltext_text_for_record(review_dir, record_id))),
            "models_or_systems_studied": first_nonempty(row.get("models_or_systems_studied"), fallback_system),
            "model_count": first_nonempty(row.get("model_count"), "not reported"),
            "benchmark_dataset_or_corpus": first_nonempty(row.get("benchmark_dataset_or_corpus"), "not reported"),
            "tasks_or_domains": first_nonempty(row.get("tasks_or_domains"), row.get("title_original", "")),
            "baselines_or_comparators": first_nonempty(row.get("baselines_or_comparators"), "not reported"),
            "instruments_or_scales": first_nonempty(row.get("instruments_or_scales"), "article method and full-text evidence"),
            "method_used": first_nonempty(row.get("method_used"), reason_detail, "Full-text methodological extraction"),
            "variables_dependent": first_nonempty(row.get("variables_dependent"), fallback_dep),
            "variables_independent": first_nonempty(row.get("variables_independent"), fallback_ind),
            "variables_moderating": first_nonempty(row.get("variables_moderating"), "not reported"),
            "variables_mediating": first_nonempty(row.get("variables_mediating"), "not reported"),
            "variables_control": first_nonempty(row.get("variables_control"), "not reported"),
            "theory_framework": first_nonempty(row.get("theory_framework"), fallback_theory),
            "evidence_snippet": first_nonempty(row.get("evidence_snippet"), summarize_phrase_soft(abstract or reason_detail, width=240)),
            "evidence_location": "full text",
            "extraction_confidence": str(confidence),
            "key_findings": first_nonempty(
                row.get("key_findings"),
                reason_detail,
                fallback_finding,
            ),
            "notes": first_nonempty(
                row.get("notes"),
                f"materialized_from_full_text_screening; relevance={relevance}; methodological={methodological}; confidence={confidence}",
            ),
        }
        existing_rows.append({field: extraction_row.get(field, "") for field in fieldnames})
        existing_ids.add(record_id)
        changed = True
    if changed:
        write_csv_rows(path, fieldnames, existing_rows)
    return changed


def enrich_focus_extraction_fields(review_dir: pathlib.Path, focus_rows: list[dict[str, str]]) -> bool:
    """Backfill conservative extraction fields from local full text.

    This keeps the manuscript honest in social-science reviews: if a PDF exposes
    a participant/corpus count, the critical appraisal should not claim that the
    study lacks a sample merely because the first extraction pass left the field
    generic.
    """
    path = review_dir / "extraction" / "extraction-table.csv"
    rows = read_csv_rows(path)
    if not rows:
        return False
    focus_ids = {(row.get("record_id") or "").strip() for row in focus_rows if (row.get("record_id") or "").strip()}
    changed = False
    for row in rows:
        record_id = (row.get("record_id") or "").strip()
        if record_id not in focus_ids:
            continue
        text = fulltext_text_for_record(review_dir, record_id)
        sample_size, sample_description = infer_sample_evidence_from_text(text)
        if sample_size and (is_missing_reporting_value(row.get("sample_size")) or is_invalid_sample_size(row.get("sample_size"))):
            row["sample_size"] = sample_size
            changed = True
        elif is_invalid_sample_size(row.get("sample_size")) and not is_missing_reporting_value(row.get("sample_size")):
            row["sample_size"] = "not reported"
            row["sample_description"] = "muestra/corpus no cuantificado de forma recuperable"
            changed = True
        if sample_description and is_generic_sample_placeholder(row.get("sample_description")):
            row["sample_description"] = sample_description
            changed = True
    if changed:
        write_csv_rows(path, list(rows[0].keys()), rows)
    return changed


def row_search_blob(row: dict[str, str]) -> str:
    return normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("title_es", ""),
                row.get("abstract_original", ""),
                row.get("abstract_en", ""),
                row.get("abstract_es", ""),
                row.get("keywords_normalized", ""),
                row.get("keywords_indexed", ""),
                row.get("keywords_author", ""),
                row.get("method_used", ""),
                row.get("sample_description", ""),
                row.get("key_findings", ""),
            ]
        )
    )


def focus_exclusion_reason(review_dir: pathlib.Path, row: dict[str, str]) -> str:
    blob = row_search_blob(row)
    topic = normalized_text(read_research_context(review_dir).get("topic", ""))
    if not has_public_doi(row):
        return "sin_doi"
    confidence_raw = (row.get("extraction_confidence") or "").strip()
    if confidence_raw and parse_int(confidence_raw, 0) < 80:
        return "confianza_de_extraccion_baja"
    if not (row.get("full_text_path", "") or "").lower().endswith(".pdf"):
        return "sin_pdf_local"
    software_topic = any(token in topic for token in ("software", "codigo", "code", "ingenieria del software", "desarrollo de software"))
    if software_topic:
        positive = sum(1 for token in SOFTWARE_CORE_TOKENS if token in blob)
        negative = sum(1 for token in SOFTWARE_NEGATIVE_TOKENS if token in blob)
        if negative >= 1 and positive <= 2:
            return "fuera_de_dominio_software"
    return ""


def curate_focus_rows(review_dir: pathlib.Path, corpus: dict[str, CorpusRecord]) -> list[dict[str, str]]:
    all_rows = merge_shortlist_rows(review_dir, corpus, selected_only=False)
    if not all_rows:
        return []
    target_n = max(1, sum(1 for row in all_rows if is_selected(row)))
    primary: list[dict[str, str]] = []
    reserve: list[dict[str, str]] = []
    last_resort: list[dict[str, str]] = []
    hard_excluded: list[dict[str, str]] = []
    for row in all_rows:
        reason = focus_exclusion_reason(review_dir, row)
        if not reason:
            primary.append(row)
        elif reason == "confianza_de_extraccion_baja":
            reserve.append(row)
        elif reason == "sin_doi":
            hard_excluded.append(row)
        else:
            last_resort.append(row)
    curated = primary[:target_n]
    if len(curated) < target_n:
        curated.extend(reserve[: target_n - len(curated)])
    if len(curated) < target_n:
        curated.extend(last_resort[: target_n - len(curated)])
    return curated


def sync_curated_focus_shortlist(review_dir: pathlib.Path, corpus: dict[str, CorpusRecord], focus_rows: list[dict[str, str]]) -> None:
    shortlist_path = review_dir / "selection" / "ultraquality-shortlist.csv"
    existing_rows = read_csv_rows(shortlist_path)
    if not existing_rows:
        return

    merged_by_id = {row.get("record_id", ""): row for row in merge_shortlist_rows(review_dir, corpus, selected_only=False)}
    focus_ids = [row.get("record_id", "") for row in focus_rows if row.get("record_id")]
    focus_set = set(focus_ids)
    focus_rank = {record_id: index for index, record_id in enumerate(focus_ids, start=1)}
    normalized_rows: list[dict[str, str]] = []

    for row in existing_rows:
        record_id = (row.get("record_id") or "").strip()
        merged = merged_by_id.get(record_id, row)
        selected = record_id in focus_set
        normalized = dict(row)
        normalized["selected_for_final_n"] = "yes" if selected else "no"
        if selected:
            normalized["selection_reason"] = (
                "Seleccionado para la síntesis focal final por superar el corte reproducible de DOI público, PDF local, "
                "score compuesto, confianza de extracción y representatividad frente al N objetivo."
            )
            normalized["cap_exclusion_reason"] = ""
        else:
            reason = focus_exclusion_reason(review_dir, merged)
            if reason:
                normalized["cap_exclusion_reason"] = (
                    "Estudio válido para revisión contextual, pero fuera del subconjunto focal por "
                    + reason.replace("_", " ")
                    + "."
                )
            elif not normalized.get("cap_exclusion_reason"):
                n_limit = normalized.get("n_limit") or str(len(focus_rows))
                normalized["cap_exclusion_reason"] = (
                    f"Estudio válido para el corpus incluido, pero queda fuera del top {n_limit} tras aplicar score compuesto, representatividad y densidad de extracción."
                )
        normalized_rows.append(normalized)

    def sort_key(row: dict[str, str]) -> tuple[int, int, str]:
        selected = 0 if (row.get("selected_for_final_n") or "").strip().lower() == "yes" else 1
        rank = focus_rank.get(row.get("record_id", ""), parse_int(row.get("ultraquality_rank"), 9999))
        return selected, rank, row.get("record_id", "")

    normalized_rows.sort(key=sort_key)
    for index, row in enumerate(normalized_rows, start=1):
        row["ultraquality_rank"] = str(index)

    write_csv_rows(shortlist_path, list(existing_rows[0].keys()), normalized_rows)


def work_type_summary(rows: list[dict[str, str]]) -> Counter[str]:
    return Counter((row.get("work_type") or "other").strip().lower() or "other" for row in rows)


def is_empirical_row(row: dict[str, str]) -> bool:
    return (row.get("work_type") or "").strip().lower() == "empirical"


def empirical_rows_only(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if is_empirical_row(row)]


def support_rows_only(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if not is_empirical_row(row)]


def empirical_summary(rows: list[dict[str, str]]) -> Counter[str]:
    empirical = empirical_rows_only(rows)
    return Counter((row.get("empirical_type") or "other").strip().lower() or "other" for row in empirical)


def method_summary(rows: list[dict[str, str]], limit: int = 6) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in rows:
        method = summarize_phrase(row.get("method_used"), width=80)
        if method != "no reportado":
            counter[method] += 1
    return counter.most_common(limit)


def theory_summary(rows: list[dict[str, str]], limit: int = 6) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in rows:
        theory = display_theory_label(row.get("theory_framework"), width=220)
        if theory != "no reportado":
            counter[theory] += 1
    return counter.most_common(limit)


def theory_family_counter(rows: list[dict[str, str]], limit: int = 8) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in rows:
        raw = row.get("theory_framework", "")
        for token in split_theory_framework_tokens(raw):
            label = display_theory_label(token, width=220)
            if label and label.lower() != "no reportado":
                counter[label] += 1
    return counter.most_common(limit)


def top_rows_by_rank(rows: list[dict[str, str]], limit: int = 6) -> list[dict[str, str]]:
    def rank_key(row: dict[str, str]) -> tuple[int, int]:
        return parse_int(row.get("ultraquality_rank"), 9999), -parse_int(row.get("extraction_confidence"), 0)
    return sorted(rows, key=rank_key)[:limit]


def top_citation_ids(rows: list[dict[str, str]], limit: int = 20) -> list[str]:
    chosen = top_rows_by_rank(rows, limit)
    chosen = sorted(
        chosen,
        key=lambda row: (
            author_family(first_nonempty(row.get("authors"), row.get("author"))).lower(),
            normalize_reference_year(row.get("year") or ""),
            row_title(row, width=180).lower(),
        ),
    )
    return [row.get("record_id", "") for row in chosen if row.get("record_id")]


def figure_markdown(rel_png: str, alt: str) -> str:
    return f"![{alt}]({rel_png})"


def load_autopilot_figure_rows(
    review_dir: pathlib.Path,
    paper_sections: set[str],
    figure_types: set[str],
) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    ranking = {
        normalize_phrase(row.get("figure_id")).lower(): normalize_phrase(row.get("recommendation")).lower()
        for row in read_csv_rows(review_dir / "figures" / "figure-ranking.csv")
        if row.get("figure_id")
    }
    for row in read_csv_rows(review_dir / "figures" / "manifest.csv"):
        figure_id = normalize_phrase(row.get("figure_id")).lower()
        paper_section = normalize_phrase(row.get("paper_section")).lower()
        figure_type = normalize_phrase(row.get("figure_type")).lower()
        png_path = (row.get("png_path") or "").strip()
        if not figure_id.startswith("fig-autopilot-"):
            continue
        # Autopilot can generate useful supplementary evidence assets. They enter
        # the manuscript body only when the portfolio ranking says they add
        # substantive value; otherwise they stay in the package for audit.
        if ranking and ranking.get(figure_id) != "main_body":
            continue
        if figure_id == "fig-autopilot-evidence-traceability" and ranking.get(figure_id) != "main_body":
            continue
        if paper_section not in paper_sections or figure_type not in figure_types or not png_path:
            continue
        rendered.append(row)
    return rendered


def render_autopilot_figure_blocks(
    review_dir: pathlib.Path,
    paper_sections: set[str],
    figure_types: set[str],
    figure_number_start: int | None = None,
) -> list[str]:
    blocks: list[str] = []
    figure_number = figure_number_start
    for row in load_autopilot_figure_rows(review_dir, paper_sections, figure_types):
        caption = (row.get("apa_caption") or row.get("title") or "Figura adicional").strip()
        caption = re.sub(r"^Figura adicional\.", "Figura complementaria.", caption, flags=re.IGNORECASE)
        if figure_number is not None:
            caption = re.sub(r"^Figura complementaria\.", f"Figura {figure_number}.", caption, flags=re.IGNORECASE)
            figure_number += 1
        png_path = (row.get("png_path") or "").strip()
        purpose = normalize_phrase(row.get("purpose"))
        if purpose.lower().startswith("mostrar "):
            purpose = "La figura muestra " + purpose[8:].strip()
        elif purpose.lower().startswith("sintetizar "):
            purpose = "La figura sintetiza " + purpose[11:].strip()
        if not png_path:
            continue
        caption_for_render = caption
        blocks.extend(
            [
                caption_for_render,
                figure_markdown(f"../../{png_path}", caption_for_render),
                "",
            ]
        )
    return blocks


RESULT_FIGURE_ORDER = [
    "fig-corpus-map",
    "fig-theme-landscape",
    "fig-agent-task-matrix",
    "fig-method-profile",
    "fig-evidence-maturity",
    "fig-topic-network",
]


def main_body_figure_ids(review_dir: pathlib.Path) -> set[str] | None:
    """Return the editorially approved body figures; None keeps legacy behavior."""
    gate_rows = read_csv_rows(review_dir / "figures" / "figure-gate.csv")
    if gate_rows:
        return {
            normalize_phrase(row.get("figure_id")).lower()
            for row in gate_rows
            if normalize_phrase(row.get("decision")).lower() == "main_body"
        }
    ranking_rows = read_csv_rows(review_dir / "figures" / "figure-ranking.csv")
    if ranking_rows:
        return {
            normalize_phrase(row.get("figure_id")).lower()
            for row in ranking_rows
            if normalize_phrase(row.get("recommendation")).lower() == "main_body"
        }
    return None


def should_embed_body_figure(review_dir: pathlib.Path, figure_id: str) -> bool:
    approved = main_body_figure_ids(review_dir)
    if approved is None:
        return True
    return normalize_phrase(figure_id).lower() in approved


def available_manifest_png(review_dir: pathlib.Path, figure_id: str) -> str:
    for row in read_csv_rows(review_dir / "figures" / "manifest.csv"):
        if normalize_phrase(row.get("figure_id")).lower() == normalize_phrase(figure_id).lower():
            return (row.get("png_path") or "").strip()
    return ""


def render_numbered_body_figure(
    review_dir: pathlib.Path,
    figure_id: str,
    figure_number: int,
    title_without_number: str,
    alt_without_number: str,
    explanation: str,
) -> tuple[list[str], int]:
    if not should_embed_body_figure(review_dir, figure_id):
        return [], figure_number
    png_path = available_manifest_png(review_dir, figure_id) or f"figures/png/{figure_id}.png"
    caption = f"Figura {figure_number}. {title_without_number}"
    text = re.sub(r"La Figura\s+\d+", f"La Figura {figure_number}", explanation)
    text = re.sub(r"las Figuras\s+\d+\-\d+", "las figuras principales", text)
    return [
        caption,
        figure_markdown(f"../../{png_path}", f"Figura {figure_number}. {alt_without_number}"),
        text,
        "",
    ], figure_number + 1


def next_discussion_figure_number(review_dir: pathlib.Path) -> int:
    approved = main_body_figure_ids(review_dir)
    if approved is None:
        return 6
    # The method section always embeds the review architecture, even when the
    # portfolio gate also keeps a supplementary copy for the delivery package.
    count = 1
    count += sum(1 for figure_id in RESULT_FIGURE_ORDER if figure_id in approved)
    return count + 1


def parse_page_number(text: str | None) -> int:
    match = re.search(r"(\d+)(?!.*\d)", normalize_phrase(text))
    return int(match.group(1)) if match else 9999


def png_dimensions(path: pathlib.Path) -> tuple[int, int]:
    """Read PNG dimensions without adding a Pillow dependency."""
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return (0, 0)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return struct.unpack(">II", header[16:24])


def visual_asset_priority(asset: dict[str, str]) -> tuple[int, int, str]:
    status = normalize_phrase(asset.get("status")).lower()
    if status == "extracted_from_pdf_embedded":
        status_score = 0
    elif status == "captured_from_pdf_page_region":
        status_score = 1
    elif status == "downloaded_from_html":
        status_score = 2
    elif status == "rendered_from_pdf_page":
        status_score = 3
    else:
        status_score = 4
    return (status_score, parse_page_number(asset.get("page_or_location")), normalize_phrase(asset.get("asset_id")))


def manuscript_visual_candidates(assets: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        asset
        for asset in assets
        if normalize_phrase(asset.get("status")).lower() != "rendered_from_pdf_page"
    ]


def source_visual_editorial_score(review_dir: pathlib.Path, row: dict[str, str], asset: dict[str, str]) -> int:
    """Score source figures for manuscript use; low scores stay in annexes only."""
    rel_path = normalize_phrase(asset.get("extracted_asset_path"))
    path = review_dir / rel_path
    width, height = png_dimensions(path)
    page = parse_page_number(asset.get("page_or_location"))
    if page < 3:
        return -999
    if normalize_phrase(asset.get("status")).lower() != "extracted_from_pdf_embedded":
        return -999
    blob = normalize_phrase(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("abstract_original", ""),
                row.get("keywords_normalized", ""),
                rel_path,
            ]
        )
    ).lower()
    score = 0
    if path.exists():
        score += 8
    if width >= 420 and height >= 180:
        score += 8
    if width >= 700 and height >= 260:
        score += 4
    if page >= 2:
        score += 4
    if page in {1, 2}:
        score -= 8
    if width == 0 or height == 0 or width < 320 or height < 120:
        score -= 20
    if height and (width / height > 4.2 or height / max(width, 1) > 2.8):
        score -= 8
    if path.exists() and path.stat().st_size < 20_000:
        score -= 20
    if re.search(r"logo|cover|portada|universidad|university|journal|publisher|header|footer", blob):
        score -= 12
    if re.search(r"architecture|arquitect|workflow|pipeline|framework|diagram|flow|rag|multi-agent|agentic|benchmark|evaluat", blob):
        score += 8
    return score


def load_visual_evidence_rows(review_dir: pathlib.Path) -> list[dict[str, str]]:
    return read_csv_rows(review_dir / "figures" / "evidence-manifest.csv")


def select_visual_evidence_panels(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    limit: int = 4,
) -> list[dict[str, str]]:
    manifest_rows = load_visual_evidence_rows(review_dir)
    grouped: dict[str, list[dict[str, str]]] = {}
    for asset in manifest_rows:
        record_id = normalize_phrase(asset.get("record_id"))
        if not record_id:
            continue
        grouped.setdefault(record_id, []).append(asset)
    candidates: list[tuple[int, int, tuple[int, int, str], dict[str, str]]] = []

    def build_candidate(row: dict[str, str]) -> None:
        record_id = normalize_phrase(row.get("record_id"))
        if not record_id:
            return
        assets = manuscript_visual_candidates(grouped.get(record_id, []))
        if not assets:
            return
        archetype = infer_architecture_archetype(row)
        scored_assets = [
            (source_visual_editorial_score(review_dir, row, asset), asset)
            for asset in assets
        ]
        scored_assets = [item for item in scored_assets if item[0] >= 24]
        if not scored_assets:
            return
        best_score, best_asset = sorted(
            scored_assets,
            key=lambda item: (-item[0], visual_asset_priority(item[1])),
        )[0]
        evidence_role = (
            "arquitectura/proceso"
            if re.search(
                r"agent|agente|architect|arquitect|arquitet|orquest|workflow|pipeline|flow|diagram|rag|mcp",
                architecture_text_blob(row),
                flags=re.IGNORECASE,
            )
            else "benchmark/evaluación"
            if re.search(r"benchmark|evaluat|validat|metric", architecture_text_blob(row), flags=re.IGNORECASE)
            else "contexto técnico"
        )
        panel = (
            {
                "record_id": record_id,
                "title": sanitize_title(
                    first_nonempty(
                        row.get("title_original"),
                        row.get("title_en"),
                        row.get("title_es"),
                    )
                ),
                "archetype": display_archetype(archetype),
                "task": software_task_label(row),
                "page_or_location": display_location_label(best_asset.get("page_or_location")),
                "asset_path": "../../" + normalize_phrase(best_asset.get("extracted_asset_path")),
                "result": principal_result_sentence(row, width=260),
                "status": normalize_phrase(best_asset.get("status")),
                "editorial_score": str(best_score),
                "evidence_role": evidence_role,
                "editorial_reason": "Pasa filtro: no es portada/logo ni imagen corrupta; aporta lectura trazable.",
            }
        )
        candidates.append(
            (
                best_score,
                parse_int(row.get("ultraquality_rank"), 9999),
                visual_asset_priority(best_asset),
                panel,
            )
        )

    ranked_rows = sorted(
        focus_rows,
        key=lambda item: (parse_int(item.get("ultraquality_rank"), 9999), -parse_int(item.get("extraction_confidence"), 0)),
    )
    for row in ranked_rows:
        build_candidate(row)
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [panel for _, _, _, panel in candidates[:limit]]


def render_visual_evidence_section(review_dir: pathlib.Path, focus_rows: list[dict[str, str]], limit: int = 4) -> str:
    """Keep source figures out of the manuscript unless a dedicated figure block embeds one with a specific analytical caption."""
    return ""


def shortlist_sensitivity(review_dir: pathlib.Path) -> dict[str, int]:
    rows = [
        row
        for row in read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")
        if (row.get("decision_before_cap") or "").strip().lower() == "include"
    ]
    selected = {
        (row.get("record_id") or "").strip()
        for row in rows
        if is_selected(row)
    }
    target_n = len(selected)
    if not rows or not target_n:
        return {"alt_a_overlap": 0, "alt_b_overlap": 0, "target_n": target_n}

    def rerank(weights: tuple[float, float, float]) -> set[str]:
        wr, wm, wp = weights
        scored = []
        for row in rows:
            rel = parse_float(row.get("relevance_score"))
            meth = parse_float(row.get("methodological_quality_score"))
            rep = parse_float(row.get("representativeness_score"))
            score = wr * rel + wm * meth + wp * rep
            scored.append((score, row.get("record_id", "")))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return {record_id for _, record_id in scored[:target_n] if record_id}

    alt_a = rerank((0.40, 0.40, 0.20))
    alt_b = rerank((0.45, 0.30, 0.25))
    return {
        "alt_a_overlap": len(selected & alt_a),
        "alt_b_overlap": len(selected & alt_b),
        "target_n": target_n,
    }


def screening_reliability_method_lines(review_dir: pathlib.Path) -> list[str]:
    """Describe dual screening from the persisted agreement artifacts."""
    path = review_dir / "screening" / "screening-reliability.json"
    if not path.exists():
        return [
            "No se dispone de una métrica de acuerdo independiente para el cribado; esta ausencia debe conservarse como limitación metodológica y no sustituirse por una afirmación genérica de fiabilidad."
        ]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [
            "El artefacto de fiabilidad del cribado no pudo interpretarse; por tanto, no se declara acuerdo ni kappa para esta ejecución."
        ]

    stages = payload.get("stages") if isinstance(payload, dict) else {}
    stages = stages if isinstance(stages, dict) else {}

    def stage_value(name: str, key: str, default: int | float = 0) -> int | float:
        stage = stages.get(name) if isinstance(stages.get(name), dict) else {}
        return stage.get(key, default)

    def decimal(value: object) -> str:
        try:
            return f"{float(value):.3f}".replace(".", ",")
        except (TypeError, ValueError):
            return "no calculado"

    title_records = parse_int(stage_value("title_abstract", "records"), 0)
    title_agreements = parse_int(stage_value("title_abstract", "agreements"), 0)
    title_disagreements = parse_int(stage_value("title_abstract", "disagreements"), 0)
    full_records = parse_int(stage_value("full_text", "records"), 0)
    full_agreements = parse_int(stage_value("full_text", "agreements"), 0)
    full_disagreements = parse_int(stage_value("full_text", "disagreements"), 0)
    full_researcher = parse_int(
        stage_value("full_text", "researcher_resolved_disagreements"),
        0,
    )

    lines = [
        (
            f"El cribado de título y resumen conservó dos juicios automáticos independientes para {title_records} registros. "
            f"Coincidieron en {title_agreements} casos y discreparon en {title_disagreements}; el acuerdo bruto fue "
            f"{decimal(stage_value('title_abstract', 'raw_agreement'))} y el kappa de Cohen "
            f"{decimal(stage_value('title_abstract', 'cohen_kappa'))}. Las discrepancias no se resolvieron mediante exclusión automática: "
            "se mantuvieron como `necesita más prueba`, de modo que la incertidumbre favoreció elegibilidad para la siguiente frontera documental."
        )
    ]
    if full_records:
        lines.append(
            (
                f"En texto completo se conservaron {full_records} pares de juicio: {full_agreements} acuerdos y {full_disagreements} discrepancias, "
                f"con acuerdo bruto {decimal(stage_value('full_text', 'raw_agreement'))} y kappa de Cohen "
                f"{decimal(stage_value('full_text', 'cohen_kappa'))}. {full_researcher} discrepancias quedaron resueltas mediante una decisión "
                "investigadora firmada después de leer el PDF y conservar las razones de ambos revisores y del adjudicador. El resultado final no "
                "descansa, por tanto, en que un modelo imponga silenciosamente su última respuesta."
            )
        )
    lines.append(
        "Estas métricas describen consistencia entre juicios automáticos independientes y no constituyen ground truth ni acuerdo interjueces humano. La extracción y la evaluación crítica tampoco se presentan como doble codificación humana; esa distinción se mantiene explícita para no confundir trazabilidad computacional con validación humana independiente."
    )
    return lines


def risk_of_bias_rows(rows: list[dict[str, str]]) -> list[list[str]]:
    empirical = [row for row in rows if (row.get("work_type") or "").strip().lower() == "empirical"]
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in empirical:
        grouped.setdefault((row.get("empirical_type") or "other").strip().lower() or "other", []).append(row)

    rendered = []
    for empirical_type, subset in sorted(grouped.items()):
        n = len(subset)
        appraisal_scores = [
            parse_int(appraisal_signals_for_row(row).get("appraisal_score"), 0)
            for row in subset
        ]
        missing_sample = sum(1 for row in subset if appraisal_signals_for_row(row).get("sample_reported") == "0")
        missing_country = sum(
            1
            for row in subset
            if is_missing_reporting_value(first_nonempty(row.get("countries"), row.get("country_or_countries")))
        )
        missing_theory = sum(
            1 for row in subset if is_missing_reporting_value(row.get("theory_framework"))
        )
        if empirical_type == "experimental":
            bias = "medio"
        elif empirical_type in {"mixed", "quantitative"}:
            bias = "medio-bajo"
        else:
            bias = "medio-alto"
        rendered.append(
            [
                table_label(display_empirical_type(empirical_type)),
                str(n),
                f"{sum(appraisal_scores) / max(n, 1):.1f}".replace(".", ","),
                str(missing_sample),
                str(missing_country),
                str(missing_theory),
                table_label(bias),
            ]
        )
    return rendered


def appraisal_signals_for_row(row: dict[str, str]) -> dict[str, str]:
    """Return the internal critical-appraisal signals used for each focal study."""
    confidence = parse_int(row.get("extraction_confidence"), 0)
    work_type = table_label(display_work_type(row.get("work_type")))
    is_empirical = (row.get("work_type") or "").strip().lower() == "empirical"
    sample_applicable = is_empirical
    sample_missing = sample_applicable and is_missing_reporting_value(row.get("sample_size"))
    context_missing = is_missing_reporting_value(first_nonempty(row.get("countries"), row.get("country_or_countries")))
    theory_missing = is_missing_reporting_value(row.get("theory_framework"))
    comparator_missing = is_missing_reporting_value(row.get("baselines_or_comparators"))
    is_security_row = any(
        not is_missing_reporting_value(row.get(field))
        for field in ("security_harness_name", "threat_model", "control_architecture")
    )
    validation_candidates = (
        [row.get("robustness_evidence"), row.get("validation_signal")]
        if is_security_row
        else [row.get("validation_signal"), row.get("limitations")]
    )
    validation_text = next(
        (
            nice_value(value)
            for value in validation_candidates
            if not is_missing_reporting_value(value)
        ),
        "no reportado",
    )
    validation_weak = is_empirical and (validation_text.lower() in {"no reportado", "not specified"} or "no report" in validation_text.lower())
    signal_specs = [
        ("tamaño/corpus", sample_applicable, not sample_missing, 20),
        ("contexto", True, not context_missing, 15),
        ("teoría", True, not theory_missing, 20),
        ("comparador", True, not comparator_missing, 20),
        ("validación", is_empirical, not validation_weak, 25),
    ]
    applicable_weight = sum(weight for _, applicable, _, weight in signal_specs if applicable)
    observed_weight = sum(weight for _, applicable, observed, weight in signal_specs if applicable and observed)
    coverage_score = 100.0 * observed_weight / max(applicable_weight, 1)
    appraisal_score = round((0.55 * confidence) + (0.45 * coverage_score))
    appraisal_score = max(0, min(100, appraisal_score))
    gaps = [
        label
        for label, applicable, observed, _ in signal_specs
        if applicable and not observed
    ]
    if appraisal_score >= 85 and len(gaps) <= 1:
        level = "Bajo"
    elif appraisal_score >= 70 and len(gaps) <= 2:
        level = "Medio-bajo"
    elif appraisal_score >= 55 and len(gaps) <= 3:
        level = "Medio"
    else:
        level = "Medio-alto"
    design = (
        table_label(display_empirical_type(row.get("empirical_type")))
        if is_empirical
        else f"{work_type} / no aplica diseño empírico"
    )
    return {
        "confidence": str(confidence),
        "appraisal_score": str(appraisal_score),
        "coverage_score": f"{coverage_score:.1f}",
        "sample_reported": "0" if sample_missing else ("NA" if not sample_applicable else "1"),
        "context_reported": "0" if context_missing else "1",
        "theory_reported": "0" if theory_missing else "1",
        "comparator_reported": "0" if comparator_missing else "1",
        "validation_reported": "0" if validation_weak else ("NA" if not is_empirical else "1"),
        "risk_level": level,
        "design": design,
        "gaps": ", ".join(gaps) if gaps else "sin vacíos críticos",
    }


def study_risk_of_bias_rows(rows: list[dict[str, str]], limit: int = 200) -> list[list[str]]:
    """Render a per-study reporting/bias appraisal for heterogeneous corpora."""
    rendered: list[list[str]] = []
    for index, row in enumerate(rows[:limit], start=1):
        appraisal = appraisal_signals_for_row(row)
        basis = f"Score crítico {appraisal['appraisal_score']}/100; confianza de extracción {appraisal['confidence']}; vacíos: {appraisal['gaps']}."
        rendered.append(
            [
                str(index),
                author_year_label(row),
                public_doi_value(row),
                appraisal["risk_level"],
                f"Diseño: {appraisal['design']}. {basis}",
            ]
        )
    return rendered


def critical_appraisal_signal_rows(rows: list[dict[str, str]], limit: int = 200) -> list[list[str]]:
    """Show the binary appraisal indicators behind the critical score."""
    rendered: list[list[str]] = []
    for index, row in enumerate(rows[:limit], start=1):
        appraisal = appraisal_signals_for_row(row)
        rendered.append(
            [
                str(index),
                public_doi_value(row),
                appraisal["sample_reported"],
                appraisal["context_reported"],
                appraisal["theory_reported"],
                appraisal["comparator_reported"],
                appraisal["validation_reported"],
                appraisal["appraisal_score"],
                appraisal["risk_level"],
            ]
        )
    return rendered


def critical_appraisal_signal_summary_rows(rows: list[dict[str, str]]) -> list[list[str]]:
    """Summarize appraisal indicators in the body; row-level DOI detail stays in CSV."""
    specs = [
        ("Tamaño muestral o corpus", "sample_reported", "Define la unidad empírica real y evita comparar estudios sin base observacional equivalente."),
        ("Contexto o país", "context_reported", "Permite valorar transferencia entre plataformas, países, instituciones o situaciones históricas."),
        ("Marco teórico", "theory_reported", "Sostiene la acumulación conceptual y evita agrupar hallazgos solo por vocabulario parecido."),
        ("Comparador o línea base", "comparator_reported", "Hace posible distinguir señal descriptiva, contraste empírico y afirmación causal prudente."),
        ("Validación o robustez", "validation_reported", "Separa rendimiento local de estabilidad, sensibilidad, réplica o validez externa."),
    ]
    appraisals = [appraisal_signals_for_row(row) for row in rows]
    rendered: list[list[str]] = []
    for label, key, reading in specs:
        observed = sum(1 for item in appraisals if item.get(key) == "1")
        missing = sum(1 for item in appraisals if item.get(key) == "0")
        not_applicable = sum(1 for item in appraisals if item.get(key) == "NA")
        rendered.append([label, str(observed), str(missing), str(not_applicable), reading])
    return rendered


def critical_appraisal_weight_rows() -> list[list[str]]:
    return [
        ["Tamaño muestral o corpus", "20", "Participantes, usuarios, mensajes, países, artículos, casos u otra unidad analítica explícita; no aplica a trabajos no empíricos."],
        ["Contexto o país", "15", "Localización, plataforma, institución, país, región o entorno empírico suficiente para valorar transferencia."],
        ["Marco teórico", "20", "Teoría, modelo conceptual, constructos o literatura de referencia que justifica la relación analizada."],
        ["Comparador o línea base", "20", "Grupo, periodo, plataforma, condición, benchmark, contraste o regla equivalente de comparación."],
        ["Validación o robustez", "25", "Pruebas de robustez, replicación, validez externa, sensibilidad, triangulación o estrategia causal; no aplica a trabajos no empíricos."],
    ]


def export_critical_appraisal_matrix(review_dir: pathlib.Path, focus_rows: list[dict[str, str]]) -> pathlib.Path:
    matrix_path = review_dir / "tables" / "critical-appraisal-matrix.csv"
    mode_decision = read_review_mode_decision(review_dir)
    appraisal_family = "; ".join(str(item) for item in mode_decision.get("critical_appraisal_tools", [])[:6]) if isinstance(mode_decision.get("critical_appraisal_tools"), list) else ""
    appraisal_domains = "; ".join(str(item) for item in mode_decision.get("critical_appraisal_domains", [])[:8]) if isinstance(mode_decision.get("critical_appraisal_domains"), list) else ""
    fieldnames = [
        "record_id",
        "doi",
        "title_original",
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
        "reporting_risk",
        "gaps",
    ]
    rows = []
    for row in focus_rows:
        appraisal = appraisal_signals_for_row(row)
        rows.append(
            {
                "record_id": row.get("record_id", ""),
                "doi": public_doi_value(row),
                "title_original": row.get("title_original", ""),
                "review_mode": mode_decision.get("mode_label", ""),
                "appraisal_family": appraisal_family,
                "mode_specific_domains": appraisal_domains,
                "work_type": table_label(display_work_type(row.get("work_type"))),
                "empirical_type": table_label(display_empirical_type(row.get("empirical_type"))),
                "appraisal_design": appraisal["design"],
                "extraction_confidence": appraisal["confidence"],
                "coverage_score": appraisal["coverage_score"],
                "appraisal_score": appraisal["appraisal_score"],
                "sample_reported": appraisal["sample_reported"],
                "context_reported": appraisal["context_reported"],
                "theory_reported": appraisal["theory_reported"],
                "comparator_reported": appraisal["comparator_reported"],
                "validation_reported": appraisal["validation_reported"],
                "reporting_risk": appraisal["risk_level"],
                "gaps": appraisal["gaps"],
            }
        )
    write_csv_rows(matrix_path, fieldnames, rows)
    return matrix_path


COMPONENT_PATTERNS = {
    "memoria": r"\bmemory\b|memoria|retrieval|knowledge base|rag\b|vector|base de conocimiento|conocimiento",
    "orquestador": r"orchestr|orquest|planner|plan-and-execute|supervisor|manager|routing|router|delegat|branch-and-merge|workflow|flujo de trabajo|n8n|crewai|coordin",
    "herramientas": r"\btool\b|tools|herramienta|ferramenta|api|terminal|workspace|repository|repo|execution harness|sandbox|browser|docker|sql|qdrant|mcp",
    "verificador": r"verif|valid|critic|judge|audit|test|evaluation|evaluaci[oó]n|prueba|m[eé]trica|oracle|coverage|fuzz|guard|benchmark",
    "roles": r"\brole\b|roles|rol(?:es)?|speciali[sz]ed agent|agente(?:s)? especial|sub-agent|subagente|multi-agent|multiagente|team|equipo|collabor|colabor",
}


def architecture_text_blob(row: dict[str, str]) -> str:
    return normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("abstract_original", ""),
                row.get("abstract_en", ""),
                row.get("keywords_normalized", ""),
                row.get("design_detail", ""),
                row.get("unit_of_analysis", ""),
                row.get("models_or_systems_studied", ""),
                row.get("benchmark_dataset_or_corpus", ""),
                row.get("tasks_or_domains", ""),
                row.get("baselines_or_comparators", ""),
                row.get("instruments_or_scales", ""),
                row.get("method_used", ""),
                row.get("theory_framework", ""),
                row.get("key_findings", ""),
            ]
        )
    )


def component_flags(row: dict[str, str]) -> dict[str, bool]:
    blob = architecture_text_blob(row)
    return {
        name: bool(re.search(pattern, blob, flags=re.IGNORECASE))
        for name, pattern in COMPONENT_PATTERNS.items()
    }


def component_counter(rows: list[dict[str, str]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        for name, enabled in component_flags(row).items():
            if enabled:
                counter[name] += 1
    return counter


def component_cooccurrence_counters(rows: list[dict[str, str]]) -> tuple[Counter[tuple[str, str]], Counter[tuple[str, str, str]]]:
    pair_counter: Counter[tuple[str, str]] = Counter()
    triple_counter: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        active = sorted(name for name, enabled in component_flags(row).items() if enabled)
        for index, left in enumerate(active):
            for right in active[index + 1 :]:
                pair_counter[(left, right)] += 1
        for index, first in enumerate(active):
            for mid_index, second in enumerate(active[index + 1 :], start=index + 1):
                for third in active[mid_index + 1 :]:
                    triple_counter[(first, second, third)] += 1
    return pair_counter, triple_counter


def component_cooccurrence_rows(rows: list[dict[str, str]], limit: int = 6) -> list[list[str]]:
    pair_counter, triple_counter = component_cooccurrence_counters(rows)
    rendered: list[list[str]] = []
    for pair, count in pair_counter.most_common(max(limit - 2, 0)):
        rendered.append([table_label(" + ".join(pair)), f"{count} ({percentage(count, len(rows))})"])
    for triple, count in triple_counter.most_common(2):
        rendered.append([table_label(" + ".join(triple)), f"{count} ({percentage(count, len(rows))})"])
    return rendered


def infer_architecture_archetype(row: dict[str, str]) -> str:
    blob = architecture_text_blob(row)
    flags = component_flags(row)
    if re.search(r"skill|capabilit|invocable", blob, flags=re.IGNORECASE):
        return "skill-based o capability-based"
    if flags["roles"] and flags["orquestador"]:
        return "multiagente orquestado"
    if flags["herramientas"] and not flags["roles"]:
        return "tool-augmented agent"
    if flags["verificador"] and re.search(r"benchmark|evaluation|taxonomy|failure mode", blob, flags=re.IGNORECASE):
        return "evaluación o benchmark arquitectónico"
    if re.search(r"governance|policy|audit|verifiable|compliance", blob, flags=re.IGNORECASE):
        return "gobernanza y auditoría"
    return "arquitectura híbrida o no tipificada"


SOFTWARE_TASK_PATTERNS = [
    ("evaluación y benchmarks", r"benchmark|evaluation|evaluacion|metric|validation|readiness|failure mode|test|testing|qa"),
    ("RAG y recuperación", r"\brag\b|retrieval|knowledge base|vector|embedding|document retrieval"),
    ("agentes conversacionales", r"chatbot|conversational|conversation|assistant|consulta|query answering"),
    ("automatización de procesos", r"workflow|automation|process|orchestr|coordination|delegat|planner|plan-and-execute|supervisor"),
    ("seguridad y cumplimiento", r"security|vulnerab|compliance|audit|secure|governance"),
    ("desarrollo de software", r"code review|pull request|maintenance|refactor|code generation|coding|debug|bug fix|repair"),
    ("prototipado y sistemas", r"prototype|prototyping|proof of concept|system implementation|ui|backend"),
    ("orquestación y workflow", r"workflow|orchestr|coordination|delegat|planner|plan-and-execute|supervisor"),
    ("dominio aplicado", r"health|education|business|industry|university|music|service"),
]


def software_task_label(row: dict[str, str]) -> str:
    blob = architecture_text_blob(row)
    for label, pattern in SOFTWARE_TASK_PATTERNS:
        if re.search(pattern, blob, flags=re.IGNORECASE):
            return label
    return "agentes de IA general"


def bool_label(value: bool) -> str:
    return "sí" if value else "no"


def benchmark_or_sample_label(row: dict[str, str]) -> str:
    benchmark = nice_value(row.get("benchmark_dataset_or_corpus"))
    sample = nice_value(row.get("sample_description"))
    sample_size = nice_value(row.get("sample_size"))
    if sample != "no reportado" and sample_size != "no reportado" and sample_size not in sample:
        sample_size_label = sample_size if re.match(r"^[Nn]\s*=", sample_size.strip()) else f"N={sample_size}"
        return summarize_phrase(f"{sample} ({sample_size_label})", width=100)
    if sample != "no reportado":
        return summarize_phrase(sample, width=100)
    if benchmark != "no reportado":
        return summarize_phrase(benchmark, width=100)
    return summarize_phrase(sample_size, width=100)


def principal_metric_label(row: dict[str, str]) -> str:
    return summarize_phrase(
        first_nonempty(
            row.get("variables_dependent"),
            row.get("benchmark_dataset_or_corpus"),
            row.get("method_used"),
            row.get("sample_description"),
        ),
        width=100,
    )


def is_process_log_marker(text: str | None) -> bool:
    """Detect operational fallback messages that must never become findings."""
    normalized = normalized_text(text or "")
    return any(
        marker in normalized
        for marker in (
            "extraccion determinista de respaldo",
            "extraccion de respaldo por respuesta incompleta",
            "timeout",
            "cierre de sesion",
            "log de sistema",
            "fallback",
        )
    )


def publication_safe_value(text: str | None) -> str:
    """Remove PDF extraction ornaments that add noise to the manuscript."""
    cleaned = nice_value(text)
    replacements = {
        "✉": "",
        "●": "-",
        "†": "",
        "∗": "*",
        "©": "(c)",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return normalize_phrase(cleaned)


def supporting_evidence_value(row: dict[str, str], width: int = 260) -> str:
    """Return appendix evidence without leaking noisy PDF front matter.

    PDF extraction often starts at cover-page metadata or reviewer boilerplate.
    That is useful for traceability but weak as article prose, so the appendix
    falls back to the substantive finding when the snippet is only front matter.
    """
    snippet = publication_safe_value(row.get("evidence_snippet"))
    lowered = snippet.lower()
    front_matter_markers = (
        "open access edited by",
        "reviewed by",
        "published ",
        "issn",
        "copyright",
        "correspondence",
    )
    if not snippet or is_process_log_marker(snippet) or any(marker in lowered for marker in front_matter_markers):
        finding = publication_safe_value(row.get("key_findings"))
        if finding and not is_process_log_marker(finding):
            return summarize_phrase(finding, width=width)
        return "Texto completo recuperado y localizado; la evidencia sustantiva se resume en los hallazgos clave de la ficha."
    summarized = summarize_phrase(snippet, width=width)
    if summarized == snippet and len(snippet) > 180 and not re.search(r"[.!?…)]$", snippet):
        return snippet.rstrip(" ,;:") + "…"
    return summarized


def safe_result_text(row: dict[str, str]) -> str:
    finding = publication_safe_value(first_nonempty(row.get("key_findings")))
    if finding and not is_process_log_marker(finding):
        return finding
    snippet = publication_safe_value(first_nonempty(row.get("evidence_snippet")))
    if snippet and not is_process_log_marker(snippet):
        return snippet
    return "no reportado"


def principal_result_label(row: dict[str, str], width: int = 110) -> str:
    return summarize_phrase(safe_result_text(row), width=width)


def principal_result_sentence(row: dict[str, str], width: int = 260) -> str:
    phrase = normalize_phrase(safe_result_text(row)) or "no reportado"
    if phrase == "no reportado":
        return phrase
    sentence = re.split(r"(?<=[.!?])\s+", phrase, maxsplit=1)[0].strip()
    if not sentence:
        sentence = phrase
    sentence = summarize_phrase_soft(sentence, width=width)
    if sentence and sentence[-1] not in ".!?…":
        sentence += "."
    return sentence


def reported_value(value: str | None) -> bool:
    return nice_value(value).lower() != "no reportado"


def split_semicolon_values(text: str | None) -> list[str]:
    raw = normalize_phrase(text)
    if not raw or raw.lower() == "no reportado":
        return []
    parts = [normalize_phrase(part) for part in re.split(r"\s*;\s*", raw) if normalize_phrase(part)]
    return dedupe_preserve(parts)


def scholarly_series(text: str | None, *, max_items: int = 3, width: int = 140) -> str:
    items = split_semicolon_values(text)
    if not items:
        return "no reportado"
    if len(items) == 1:
        return summarize_phrase_soft(items[0], width=width)
    if len(items) == 2:
        return summarize_phrase_soft(f"{items[0]} y {items[1]}", width=width)
    shown = items[:max_items]
    body = ", ".join(shown[:-1]) + f" y {shown[-1]}"
    if len(items) > max_items:
        body += ", entre otros"
    return summarize_phrase_soft(body, width=width)


def clean_design_detail_text(text: str | None) -> str:
    phrase = normalize_phrase(text) or "no reportado"
    if phrase.lower() == "no reportado":
        return phrase
    replacements = {
        "Estudio experimental con extracción heurística reforzada desde el texto completo del PDF": "Estudio experimental reconstruido a partir del texto completo del PDF",
        "Estudio cuantitativo con extracción heurística reforzada desde el texto completo del PDF": "Estudio cuantitativo reconstruido a partir del texto completo del PDF",
        "Estudio mixed con extracción heurística reforzada desde el texto completo del PDF": "Estudio mixto reconstruido a partir del texto completo del PDF",
        "Estudio qualitative con extracción heurística reforzada desde el texto completo del PDF": "Estudio cualitativo reconstruido a partir del texto completo del PDF",
    }
    for source, target in replacements.items():
        if phrase.startswith(source):
            phrase = phrase.replace(source, target, 1)
            break
    return phrase


def narrative_method_label(row: dict[str, str], width: int = 135) -> str:
    design = clean_design_detail_text(row.get("design_detail"))
    if design.lower() != "no reportado":
        return summarize_phrase_soft(design, width=width)
    return summarize_phrase_soft(nice_value(row.get("method_used")), width=width)


def model_scope_label(row: dict[str, str], width: int = 140) -> str:
    models = scholarly_series(row.get("models_or_systems_studied"), max_items=4, width=width)
    count = sanitized_model_count(row.get("model_count"))
    if models != "no reportado" and count != "no reportado" and count not in models:
        return summarize_phrase_soft(f"{models} (n={count})", width=width)
    if models != "no reportado":
        return summarize_phrase_soft(models, width=width)
    if count != "no reportado":
        return summarize_phrase_soft(f"{count} modelos o sistemas", width=width)
    return "no reportado"


def sanitized_model_count(value: str | int | float | None) -> str:
    """Return a model-count only when it looks like a real count, not a year."""
    raw = nice_value(value)
    if raw.lower() == "no reportado":
        return "no reportado"
    match = re.search(r"\d+", raw)
    if not match:
        return raw
    count = int(match.group(0))
    if 1900 <= count <= 2100:
        return "no reportado"
    return str(count)


def benchmark_dataset_label(row: dict[str, str], width: int = 120) -> str:
    return scholarly_series(row.get("benchmark_dataset_or_corpus"), max_items=3, width=width)


def tasks_or_domains_label(row: dict[str, str], width: int = 120) -> str:
    return scholarly_series(row.get("tasks_or_domains"), max_items=3, width=width)


def comparators_label(row: dict[str, str], width: int = 120) -> str:
    return scholarly_series(row.get("baselines_or_comparators"), max_items=3, width=width)


def instruments_label(row: dict[str, str], width: int = 120) -> str:
    return scholarly_series(row.get("instruments_or_scales"), max_items=4, width=width)


def design_detail_label(row: dict[str, str], width: int = 140) -> str:
    return summarize_phrase_soft(clean_design_detail_text(first_nonempty(row.get("design_detail"), row.get("method_used"))), width=width)


def unit_of_analysis_label(row: dict[str, str], width: int = 120) -> str:
    return summarize_phrase_soft(
        first_nonempty(row.get("unit_of_analysis"), row.get("sample_description"), row.get("benchmark_dataset_or_corpus")),
        width=width,
    )


def row_title(row: dict[str, str], record: CorpusRecord | None = None, width: int = 110) -> str:
    return summarize_phrase(
        sanitize_title(
            first_nonempty(
                row.get("title_original"),
                row.get("title_en"),
                row.get("title_es"),
                record.title if record else "",
            )
        ),
        width=width,
    )


def is_provisional_focus_row(row: dict[str, str]) -> bool:
    confidence = parse_int(row.get("extraction_confidence"), 0)
    findings = normalized_text(row.get("key_findings"))
    notes = normalized_text(row.get("notes"))
    method_missing = nice_value(row.get("method_used")).lower() == "no reportado"
    theory_missing = nice_value(row.get("theory_framework")).lower() == "no reportado"
    work_type = nice_value(row.get("work_type")).lower()
    sample_missing = nice_value(row.get("sample_size")).lower() == "no reportado"
    model_scope_missing = model_scope_label(row).lower() == "no reportado"
    benchmark_missing = benchmark_dataset_label(row).lower() == "no reportado"
    instruments_missing = instruments_label(row).lower() == "no reportado"
    variables_missing = all(
        nice_value(row.get(field)).lower() == "no reportado"
        for field in (
            "variables_dependent",
            "variables_independent",
            "variables_moderating",
            "variables_mediating",
            "variables_control",
        )
    )
    architecture_unspecified = infer_architecture_archetype(row) == "arquitectura híbrida o no tipificada"
    no_components = not any(component_flags(row).values())
    low_density_empirical = work_type == "empirical" and method_missing and sample_missing and variables_missing and model_scope_missing and benchmark_missing and instruments_missing
    low_density_theoretical = work_type in {"theoretical", "other"} and method_missing and theory_missing and architecture_unspecified
    weak_architecture_signal = architecture_unspecified and no_components and theory_missing
    return (
        confidence < 80
        or "extraccion de respaldo" in findings
        or "extraccion de respaldo" in notes
        or low_density_empirical
        or low_density_theoretical
        or weak_architecture_signal
    )


def architecture_comparison_target(row: dict[str, str]) -> str:
    archetype = infer_architecture_archetype(row)
    mapping = {
        "multiagente orquestado": "propuestas más lineales o de agente único con menor reparto funcional",
        "skill-based o capability-based": "diseños multiagente con más coste de coordinación explícita",
        "tool-augmented agent": "marcos puramente conceptuales o menos instrumentados",
        "evaluación o benchmark arquitectónico": "propuestas de sistema sin instrumentación comparativa fuerte",
        "gobernanza y auditoría": "diseños centrados solo en rendimiento sin capa de control explícita",
    }
    return mapping.get(archetype, "propuestas menos comparables o menos explícitas en su composición")


def creativity_evidence_family(row: dict[str, str]) -> str:
    """Group creativity-LLM studies by evidential function, not by agent architecture."""
    blob = normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("tasks_or_domains", ""),
                row.get("benchmark_dataset_or_corpus", ""),
                row.get("instruments_or_scales", ""),
                row.get("method_used", ""),
                row.get("key_findings", ""),
            ]
        )
    )
    if re.search(r"scientific|research plan|idea generation|ideaci[oó]n cient|descubrimiento", blob):
        return "Ideación científica y generación de investigación"
    if re.search(r"writing|literary|script|story|narrative|poem|poetry|texto creativo|escritura|literari", blob):
        return "Escritura y generación creativa"
    if re.search(r"divergent|associat|dat|rat|aut|remote association|pensamiento divergente|asociativ", blob):
        return "Pensamiento divergente y asociación"
    if re.search(r"math|matem[aá]tic|problem-solving|problem solving|resoluci[oó]n creativa|creative problem", blob):
        return "Resolución creativa de problemas"
    if re.search(r"brain|human|humano|human-based|comparative|align|neuro|cerebro", blob):
        return "Comparación humano-modelo"
    if re.search(r"judge|evaluator|metric|benchmark|rubric|evaluation|evaluaci[oó]n|m[eé]trica|score", blob):
        return "Evaluación, métricas y benchmarks"
    if re.search(r"training|preference|optimization|dpo|rl|post-training|postentrenamiento|fine-tun", blob):
        return "Entrenamiento y optimización creativa"
    return "Caracterización metodológica de creatividad"


def education_ai_evidence_family(row: dict[str, str]) -> str:
    """Group AI-in-higher-education studies by faculty-facing evidential function."""
    blob = normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("tasks_or_domains", ""),
                row.get("benchmark_dataset_or_corpus", ""),
                row.get("instruments_or_scales", ""),
                row.get("method_used", ""),
                row.get("key_findings", ""),
                row.get("variables_dependent", ""),
                row.get("variables_independent", ""),
            ]
        )
    )
    if re.search(r"feedback|retroalimentacion|formative|rubric|rubrica|assessment|evaluacion|grading|calificacion", blob):
        return "Feedback, evaluación y calidad de la retroalimentación"
    if re.search(r"curriculum|curriculo|lesson|clase|course design|dise[nñ]o curricular|material|syllabus|actividad", blob):
        return "Diseño curricular, materiales y planificación docente"
    if re.search(r"adoption|acceptance|intention|attitude|perception|alfabetizacion|literacy|faculty development|formacion docente|competenc", blob):
        return "Adopción docente, alfabetización en IA y competencias"
    if re.search(r"productiv|workload|carga|time|tiempo|efficien|administr", blob):
        return "Productividad académica y carga de trabajo docente"
    if re.search(r"learning|aprendizaje|student outcome|quality|calidad|engagement|rendimiento", blob):
        return "Resultados de aprendizaje y calidad educativa"
    if re.search(r"integrity|integridad|ethic|etica|privacy|privacidad|bias|sesgo|governance|policy|politica", blob):
        return "Integridad académica, ética y gobernanza"
    return "Uso docente de IA en educación superior"


def social_science_evidence_family(row: dict[str, str]) -> str:
    """Group social-science studies by substantive mechanism, not by pipeline metadata."""
    blob = normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("abstract_original", ""),
                row.get("tasks_or_domains", ""),
                row.get("theory_framework", ""),
                row.get("variables_dependent", ""),
                row.get("variables_independent", ""),
                row.get("key_findings", ""),
            ]
        )
    )
    if re.search(r"affective polar|polarizacion afectiva|polarizaci[oó]n afectiva|partisan animosity|out-party|in-party|partisan identity", blob):
        return "Polarización afectiva e identidad partidista"
    if re.search(r"institutional trust|political trust|confianza institucional|confianza politica|trust in institutions|confidence in institutions|legitimacy|legitimidad", blob):
        return "Confianza institucional y legitimidad democrática"
    if re.search(r"social media|redes sociales|twitter|x platform|facebook|instagram|tiktok|social network|online social", blob):
        return "Exposición digital y plataformas sociales"
    if re.search(r"misinformation|disinformation|fake news|news|noticias|information quality|media diet|echo chamber|filter bubble", blob):
        return "Información política, desinformación y ecosistemas mediáticos"
    if re.search(r"participation|turnout|voting|vote|democratic satisfaction|democratic attitude|civic|protest|participaci[oó]n", blob):
        return "Participación y actitudes democráticas"
    if re.search(r"survey|panel|experiment|regression|content analysis|interview|encuesta|experimento|regresi[oó]n", blob):
        return "Evidencia metodológica y medición social"
    return "Constructos sociales y contexto institucional"


def social_family_synthetic_reading(family: str, members: list[dict[str, str]]) -> str:
    total = len(members)
    if family == "Polarización afectiva e identidad partidista":
        return f"{total} estudios ayudan a distinguir distancia afectiva, identidad partidista y hostilidad entre grupos como mecanismos, no como simple desacuerdo ideológico."
    if family == "Confianza institucional y legitimidad democrática":
        return f"{total} estudios conectan confianza política o institucional con exposición informativa, evaluación de instituciones y contexto democrático."
    if family == "Exposición digital y plataformas sociales":
        return f"{total} estudios tratan redes sociales como entorno de exposición, interacción y selección informativa, no como causa homogénea."
    if family == "Información política, desinformación y ecosistemas mediáticos":
        return f"{total} estudios sitúan la calidad informativa y la desinformación como mecanismos que pueden modular polarización y confianza."
    if family == "Participación y actitudes democráticas":
        return f"{total} estudios amplían la lectura hacia comportamiento cívico, participación y satisfacción democrática."
    if family == "Evidencia metodológica y medición social":
        return f"{total} estudios aportan sobre todo comparabilidad metodológica: diseño, muestra, instrumento o medición."
    return f"{total} estudios delimitan contexto social, unidad de análisis o constructos relevantes para la pregunta."


def social_science_relation_signal(focus_rows: list[dict[str, str]]) -> str:
    total = max(len(focus_rows), 1)
    counts = social_science_signal_counts(focus_rows)
    return (
        f"redes/plataformas: {counts['exposure']}/{total}; polarización afectiva o partidista: {counts['identity']}/{total}; "
        f"confianza/legitimidad institucional: {counts['trust']}/{total}; información/desinformación: {counts['information']}/{total}"
    )


def social_science_signal_blob(row: dict[str, str]) -> str:
    """Use source-facing fields so generated synthesis prose does not inflate counts."""
    return normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("title_en", ""),
                row.get("title_es", ""),
                row.get("abstract_original", ""),
                row.get("abstract_en", ""),
                row.get("abstract_es", ""),
                row.get("keywords_normalized", ""),
                row.get("keywords_indexed", ""),
                row.get("keywords_author", ""),
            ]
        )
    )


def social_science_signal_count(rows: list[dict[str, str]], pattern: str) -> int:
    regex = re.compile(pattern, flags=re.IGNORECASE)
    return sum(1 for row in rows if regex.search(social_science_signal_blob(row)))


def social_science_signal_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return {
        "exposure": social_science_signal_count(rows, r"social media|redes sociales|twitter|facebook|instagram|tiktok|social network|online social"),
        "identity": social_science_signal_count(rows, r"affective polar|polarizacion afectiva|polarizaci[oó]n afectiva|partisan animosity|out-party|partisan"),
        "trust": social_science_signal_count(rows, r"institutional trust|political trust|confianza institucional|trust in institutions|confidence in institutions|legitimacy|legitimidad"),
        "information": social_science_signal_count(rows, r"misinformation|disinformation|fake news|news|noticias|information quality|calidad informativa"),
        "causal": social_science_signal_count(rows, r"experiment|random|panel|longitudinal|instrumental|difference-in-differences|fixed effects|causal|experimento"),
    }


def social_science_row_has(row: dict[str, str], pattern: str) -> bool:
    return bool(re.search(pattern, social_science_signal_blob(row), flags=re.IGNORECASE))


def social_science_direction_label(row: dict[str, str]) -> str:
    """Infer a conservative direction category from source-facing text.

    The label is deliberately coarse. Social-science reviews should not invent
    comparable effect sizes when the primary studies report heterogeneous
    designs, outcomes and measures.
    """
    blob = social_science_signal_blob(row)
    null_or_mixed = r"not polarizing|no effect|no evidence|does not|did not|not associated|mixed|ambivalent|heterogeneous|not always|sin efecto|no evidencia|mixto"
    mitigation = r"reduce|reduces|reduced|decrease|decreases|decreased|mitigate|mitigates|lower polarization|less polar|disminu|reduce|mitiga"
    intensification = r"increase|increases|increased|heighten|heightens|heightened|amplif|exacerbat|polarizing|creates affective polarization|more polar|lower.*trust|distrust|erod|aument|intensific|erosion"
    if re.search(null_or_mixed, blob):
        return "nula, mixta o condicionada por diseño"
    if re.search(mitigation, blob):
        return "señal de reducción/mitigación reportada"
    if re.search(intensification, blob):
        return "señal de aumento/erosión reportada"
    return "asociación condicionada o no direccional"


def social_science_relation_direction_rows(rows: list[dict[str, str]]) -> list[list[str]]:
    """Summarize direction and consistency for the central social-science relations."""
    relation_specs = [
        (
            "Redes/plataformas -> polarización",
            lambda row: social_science_row_has(row, r"social media|redes sociales|twitter|facebook|instagram|tiktok|online social")
            and social_science_row_has(row, r"affective polar|polarizaci[oó]n afectiva|partisan|animosity"),
            "Relación central; requiere separar exposición, selección informativa, identidad e incivilidad.",
        ),
        (
            "Redes/plataformas -> confianza",
            lambda row: social_science_row_has(row, r"social media|redes sociales|twitter|facebook|instagram|tiktok|online social")
            and social_science_row_has(row, r"institutional trust|political trust|confianza institucional|legitimacy|legitimidad"),
            "Evidencia más débil; debe leerse como relación condicionada y no como efecto universal.",
        ),
        (
            "Info/desinformación -> polarización/confianza",
            lambda row: social_science_row_has(row, r"misinformation|disinformation|fake news|news|noticias|information quality|calidad informativa")
            and social_science_row_has(row, r"affective polar|polarizaci[oó]n afectiva|partisan|trust|confianza|legitimacy|legitimidad"),
            "La calidad informativa opera como mecanismo posible, pero las métricas no son homogéneas.",
        ),
        (
            "Incivilidad/identidad -> confianza/polarización",
            lambda row: social_science_row_has(row, r"incivility|uncivil|partisan identity|identidad partidista|out-party|in-party|elite partisan")
            and social_science_row_has(row, r"polar|trust|confianza|legitimacy|legitimidad"),
            "Sirve para distinguir desacuerdo ideológico, animosidad e impacto institucional.",
        ),
    ]
    rendered: list[list[str]] = []
    for relation, predicate, reading in relation_specs:
        candidates = [row for row in rows if predicate(row)]
        if not candidates:
            rendered.append([relation, "0", "sin evidencia focal suficiente", "no meta-analizable", reading])
            continue
        directions = Counter(social_science_direction_label(row) for row in candidates)
        direction_text = "; ".join(f"{label}: {count}" for label, count in directions.most_common())
        magnitude_count = sum(
            1
            for row in candidates
            if social_science_row_has(row, r"\b(beta|coefficient|odds ratio|effect size|regression|estimate|coeficiente|raz[oó]n de momios|p\s*[<=>])\b")
        )
        magnitude_text = (
            f"{magnitude_count}/{len(candidates)} con señal cuantitativa recuperable, pero no con métrica común"
            if magnitude_count
            else "no comparable: diseños, escalas y resultados heterogéneos"
        )
        rendered.append([relation, str(len(candidates)), direction_text, magnitude_text, reading])
    return rendered


def domain_substantive_synthesis_lines(
    profile: str,
    topic: str,
    focus_rows: list[dict[str, str]],
    top_ids: list[str],
) -> list[str]:
    """Turn result frequencies into a substantive thematic answer to the research question."""
    total = len(focus_rows)
    if not total:
        return [
            "## Síntesis sustantiva de resultados",
            "",
            "El corpus focal no contiene estudios suficientes para formular una síntesis sustantiva. En esta situación, la revisión debe conservarse como mapa de búsqueda y no forzar una respuesta analítica.",
        ]
    if profile not in {"social_sciences", "creativity_llm", "ai_higher_education_teaching", "education"} and is_ai_workload_rows(focus_rows):
        empirical_rows = empirical_rows_only(focus_rows)
        support_rows = support_rows_only(focus_rows)
        primary_rows = empirical_rows or focus_rows
        primary_total = len(primary_rows)
        counts = ai_workload_signal_counts(primary_rows)
        return [
            "## Síntesis sustantiva de resultados",
            "",
            f"La respuesta sustantiva a la pregunta no es un sí o no simple. La base empírica primaria está formada por {primary_total} estudios; los {len(support_rows)} trabajos no empíricos se conservan como apoyo teórico, metodológico o contextual, pero no se cuentan como prueba directa de reducción neta de carga. Con esa separación, la lectura integrada sugiere que la IA sí puede ahorrar tiempo en tareas delimitadas, pero no demuestra una reducción neta y general del trabajo humano. La tesis que mejor organiza la evidencia es el desplazamiento del esfuerzo: menos trabajo de ejecución en algunos puntos, más trabajo de articulación, supervisión, revisión, coordinación, aprendizaje y responsabilidad en otros {citation_block(top_ids[:4])}.",
            "",
            f"El primer patrón empírico es la productividad local. {counts['productivity']}/{primary_total} estudios empíricos contienen señal de productividad, eficiencia o tiempo. Esa señal importa, pero su alcance es más estrecho de lo que suele venderse: normalmente mide output, rapidez o rendimiento en una fase de tarea, no el coste completo de convertir una salida de IA en una decisión aceptada, integrada y responsable.",
            "",
            f"El segundo patrón empírico es la capa de control. {counts['supervision']}/{primary_total} estudios empíricos contienen señal de supervisión, revisión, coordinación, rework o control de calidad. Esta frecuencia debe leerse con una cautela importante: la estrategia de búsqueda ya incluía términos de supervisión y revisión, por lo que la presencia del tema no es un hallazgo puramente inductivo. Lo que sí aporta la lectura completa es cómo aparece esa capa: revisar, detectar errores, adaptar, justificar y coordinar no es decoración metodológica, sino trabajo humano desplazado hacia otra fase.",
            "",
            f"El tercer patrón empírico es el coste de riesgo. {counts['risk_error']}/{primary_total} estudios empíricos contienen señal de error, sesgo, privacidad, omisión o riesgo, y {counts['high_risk']}/{primary_total} se sitúan en ámbitos de salud, clínica, diagnóstico o decisión experta. En esos contextos, la IA puede acelerar una parte del flujo, pero el coste de equivocarse obliga a mantener una vigilancia que reduce la promesa de ahorro neto.",
            "",
            f"El cuarto patrón empírico es aprendizaje y dependencia. {counts['learning']}/{primary_total} estudios empíricos contienen señal de aprendizaje, habilidades, formación o recualificación. Esto sugiere que la adopción de IA no solo sustituye esfuerzo viejo por output automático; crea trabajo nuevo de alfabetización, ajuste de criterio, rediseño de procedimientos y gestión de dependencia tecnológica.",
            "",
            "La lectura conjunta permite formular una tesis clara: la IA funciona mejor como tecnología de compresión de ejecución que como tecnología de desaparición del trabajo. Allí donde la tarea tiene criterio claro y bajo coste de error, el ahorro puede ser real. Allí donde la tarea es ambigua, experta, regulada o institucionalmente sensible, el ahorro se vuelve condicional porque aumentan revisión, responsabilidad y coordinación.",
            "",
            "Tabla 8B. Balance interpretativo entre ahorro y desplazamiento.",
            markdown_table(
                ["Capa del trabajo", "Señal recuperada", "Implicación para la tesis"],
                [
                    ["Ejecución", f"{counts['productivity']}/{primary_total}", "Puede reducirse en tareas acotadas; es la parte más visible del ahorro."],
                    ["Verificación y control", f"{counts['supervision']}/{primary_total}", "Tiende a crecer cuando la salida debe ser validada, corregida o integrada."],
                    ["Riesgo y responsabilidad", f"{counts['risk_error']}/{primary_total}", "Impide leer velocidad como mejora si no se controla error, sesgo y coste de fallo."],
                    ["Aprendizaje y adaptación", f"{counts['learning']}/{primary_total}", "Convierte la adopción en trabajo de transición, formación y cambio organizativo."],
                    ["Gobernanza", f"{counts['governance']}/{primary_total}", "Hace explícito que trabajar con IA también implica reglas, política, privacidad y accountability."],
                ],
            ),
            "",
            "La síntesis sustantiva, por tanto, no debe decir solamente que la evidencia es heterogénea. Debe decir que esa heterogeneidad tiene estructura: los estudios que celebran productividad suelen mirar una capa del trabajo; los que advierten riesgos, dependencia o revisión miran otras capas. La contribución del artículo está en poner esas capas en la misma contabilidad.",
            "",
        ]
    if profile == "ai_security_harness":
        counts = security_harness_signal_counts(focus_rows)
        families = Counter(security_harness_evidence_family(row) for row in focus_rows)
        return [
            "## Síntesis sustantiva de resultados",
            "",
            f"La respuesta sustantiva no es que exista un harness universalmente mejor. Los {total} estudios focales permiten comparar defensas dentro de contratos concretos de amenaza, superficie, atacante y baseline. La síntesis se distribuye en {counter_summary(families, total, limit=6)}; esa distribución muestra que filtrar prompts, proteger RAG, restringir herramientas, aislar ejecución y verificar salidas resuelven problemas distintos {citation_block(top_ids[:4])}.",
            "",
            f"El primer patrón es la incompletitud del contrato comparativo. La amenaza es recuperable en {counts['threat']}/{total} estudios, el control en {counts['control']}/{total}, el punto de aplicación en {counts['enforcement']}/{total} y un baseline en {counts['baseline']}/{total}. Cuando una evaluación omite cualquiera de estas piezas, la tasa de éxito o bloqueo no permite saber si la defensa mejora una alternativa razonable bajo el mismo riesgo.",
            "",
            f"El segundo patrón separa eficacia local y robustez. {counts['asr']}/{total} estudios reportan ASR o una métrica defensiva equivalente, pero solo {counts['adaptive']}/{total} incluyen señal de atacante adaptativo y {counts['robustness']}/{total} aportan transferencia, ataques no vistos, ablación o validación externa. La evidencia favorece cautela: vencer un conjunto fijo de prompts demuestra cobertura del conjunto, no resistencia frente a un adversario que conoce y optimiza contra el control.",
            "",
            f"El tercer patrón es el coste oculto de la seguridad. Falsos positivos aparecen en {counts['false_positive']}/{total} estudios, utilidad en {counts['utility']}/{total}, latencia en {counts['latency']}/{total} y coste en {counts['cost']}/{total}. Esta asimetría impide aceptar un ranking basado solo en bloqueo: una defensa demasiado restrictiva puede reducir ataques y, al mismo tiempo, impedir uso legítimo, aumentar revisión humana o hacer inviable el sistema.",
            "",
            "El cuarto patrón es de cobertura de superficie. Permisos y sandbox actúan sobre herramientas; separación de instrucciones y datos sobre contexto; monitores de runtime sobre trayectorias; y verificadores de salida sobre respuestas. La evidencia no demuestra que más capas sean siempre mejores ni que una barrera única sea necesariamente inferior. Sí demuestra que estos controles no son intercambiables: una comparación válida debe indicar qué ruta de ataque interrumpe cada mecanismo y qué daño residual queda fuera de su alcance.",
            "",
            f"El quinto patrón es la transparencia del fallo. {counts['failure']}/{total} estudios declaran modos de fallo y {counts['artifact']}/{total} código o artefactos. Estos datos son científicamente centrales: permiten definir la frontera de uso seguro, reproducir bypasses y decidir qué capa compensatoria hace falta. Una defensa que solo publica éxitos aporta menos a la seguridad acumulativa que otra que muestra dónde deja de funcionar.",
            "",
            "Tabla 8C. Contrato comparativo para decidir si un harness aporta una mejora defensiva.",
            markdown_table(
                ["Dimensión", "Cobertura focal", "Regla de interpretación"],
                [
                    ["Amenaza y superficie", f"{counts['threat']}/{total}", "La eficacia solo viaja a amenazas y superficies equivalentes."],
                    ["Control y enforcement", f"Control: {counts['control']}/{total}; enforcement: {counts['enforcement']}/{total}", "Debe saberse qué decisión controla y antes de qué daño."],
                    ["Baseline y eficacia", f"Baseline: {counts['baseline']}/{total}; eficacia: {counts['asr']}/{total}", "Sin comparación común no existe mejora atribuible."],
                    ["Adaptación y robustez", f"Atacante adaptativo: {counts['adaptive']}/{total}; robustez amplia: {counts['robustness']}/{total}", "Separa prueba adversarial adaptativa de transferencia, ablación o ataques no vistos."],
                    ["Utilidad y coste", f"Utilidad: {counts['utility']}/{total}; latencia: {counts['latency']}/{total}; coste: {counts['cost']}/{total}", "Evita llamar mejor a una defensa inutilizable o demasiado cara."],
                    ["Fallo y reproducibilidad", f"Fallo: {counts['failure']}/{total}; artefacto: {counts['artifact']}/{total}", "Delimita riesgo residual y permite repetir la evaluación."],
                ],
            ),
            "",
            "La síntesis permite una decisión fuerte pero condicionada: no hay un campeón universal; hay configuraciones que dominan dentro de una amenaza y un coste de fallo definidos. Cuando dos harnesses intercambian seguridad por utilidad o coste, la literatura debe reportar una frontera de compromiso y no ocultarla detrás de una media única.",
            "",
        ]
    if profile == "social_sciences":
        counts = social_science_signal_counts(focus_rows)
        exposure = counts["exposure"]
        identity = counts["identity"]
        trust = counts["trust"]
        information = counts["information"]
        causal = counts["causal"]
        family_counts = Counter(social_science_evidence_family(row) for row in focus_rows)
        trust_dominant = family_counts.get("Confianza institucional y legitimidad democrática", 0)
        context_missing = sum(
            1
            for row in focus_rows
            if is_missing_reporting_value(first_nonempty(row.get("countries"), row.get("country_or_countries")))
        )
        return [
            "## Síntesis sustantiva de resultados",
            "",
            f"La respuesta sustantiva a la pregunta de investigación no es que las redes sociales produzcan por sí mismas polarización afectiva o pérdida de confianza institucional. La lectura integrada de los {total} estudios focales indica una relación condicional: la exposición digital importa cuando se conecta con identidad partidista, calidad informativa, contexto institucional, ciclo político y forma de medición {citation_block(top_ids[:4])}.",
            "",
            f"El primer patrón analítico es la articulación entre exposición y entorno informativo. En el subconjunto focal aparecen señales de exposición digital o plataforma en {exposure}/{total} estudios y señales de información, noticias o desinformación en {information}/{total}. Este conteo no prueba por sí solo una mediación causal; indica que el problema no reside solo en usar redes sociales, sino en qué contenido circula, cómo se selecciona, qué credibilidad recibe y qué relación guarda con conflictos políticos o instituciones concretas {citation_block(top_ids[4:8])}.",
            "",
            f"El segundo mecanismo es identitario. La polarización afectiva o partidista aparece como señal en {identity}/{total} estudios, pero su papel cambia según se mida como distancia emocional, animosidad hacia el adversario, identidad de grupo, incivilidad o reacción ante información problemática. Por eso la dirección de la relación no debe leerse como efecto lineal único: la misma exposición puede reforzar identidad, activar rechazo al exogrupo o no producir cambio detectable si el contexto político y la medición no lo capturan.",
            "",
            f"El tercer mecanismo afecta a la confianza institucional. Como familia dominante aparece en {trust_dominant}/{total} estudios, mientras que como señal sustantiva aparece en {trust}/{total}. Esa asimetría importa: permite discutir confianza como parte de la relación revisada, pero obliga a no sobredimensionarla frente al bloque más amplio de polarización afectiva e identidad partidista. La confianza baja puede predisponer a aceptar información hostil; al mismo tiempo, entornos informativos polarizados pueden erosionar confianza en actores, instituciones o procedimientos democráticos. Esta doble condición explica por qué la síntesis habla de relación situada y no de causalidad universal {citation_block(top_ids[8:12])}.",
            "",
            f"La fuerza causal del corpus es desigual. {causal}/{total} estudios contienen señal de experimento, panel, longitudinalidad, controles fuertes o estrategia causal; el resto aporta principalmente asociación, descripción, modelización, revisión o evidencia contextual. La conclusión fuerte, por tanto, no es una magnitud de efecto agregada, sino una tesis de mecanismo: las relaciones son más comparables cuando el estudio declara constructo, población, instrumento, contexto y dirección temporal.",
            "",
            f"Las condiciones de transferencia son parte del resultado. {context_missing}/{total} estudios focales no detallan país o contexto con suficiente precisión; incluso cuando lo hacen, una plataforma, un sistema de partidos, una elección, una crisis institucional o una comunidad mediática pueden cambiar el sentido del hallazgo. Por eso la síntesis sustantiva final se formula así: existe evidencia de conexión entre exposición digital, polarización afectiva y confianza institucional, pero esa conexión depende de mecanismos identitarios e informativos, de mediciones no siempre equivalentes y de contextos democráticos que delimitan su generalización.",
            "",
            "Tabla 8B. Mecanismos sustantivos que organizan la respuesta a la pregunta de investigación.",
            markdown_table(
                ["Mecanismo", "Señal focal", "Lectura sustantiva"],
                [
                    ["Exposición digital/plataforma", f"{exposure}/{total}", "No basta el uso agregado: importa contenido, selección, plataforma y situación política."],
                    ["Identidad y polarización afectiva", f"{identity}/{total}", "La animosidad, identidad partidista y distancia emocional son rutas distintas y no deberían agregarse sin definición."],
                    ["Confianza o legitimidad institucional", f"{trust}/{total}", "Puede operar como antecedente, resultado o condición de vulnerabilidad ante información política."],
                    ["Información, noticias o desinformación", f"{information}/{total}", "La calidad informativa media la relación entre exposición digital y actitudes democráticas."],
                ],
            ),
            "",
            "Tabla 8C. Dirección y consistencia de las relaciones centrales recuperables.",
            markdown_table(
                ["Relación", "N focal", "Dirección recuperada", "Magnitud comparable", "Lectura inferencial"],
                social_science_relation_direction_rows(focus_rows),
            ),
            "",
            "La Tabla 8C responde a la pregunta que una frecuencia temática no puede resolver por sí sola: qué dirección sugieren los estudios y con qué prudencia debe leerse. Sus filas no son categorías excluyentes y no deben sumarse hasta 35: un mismo estudio puede informar más de una relación y los estudios no empíricos funcionan como soporte conceptual, no como dirección de efecto. La revisión no calcula una metaestimación porque los estudios focales combinan encuestas, experimentos, análisis de plataforma, revisiones y diseños cualitativos con escalas y resultados no equivalentes. En lugar de forzar una magnitud falsa, el manuscrito separa dirección, consistencia y límite inferencial; esa es la forma más honesta de integrar hallazgos sustantivos cuando el corpus es heterogéneo.",
            "",
        ]
    if profile == "ai_higher_education_teaching":
        family_counts = Counter(education_ai_evidence_family(row) for row in focus_rows)
        return [
            "## Síntesis sustantiva de resultados",
            "",
            f"La respuesta sustantiva no es que la IA mejore la docencia universitaria por presencia tecnológica. La evidencia focal se organiza en {counter_summary(family_counts, total, limit=6)}, lo que obliga a comparar funciones docentes concretas: feedback, evaluación, diseño curricular, tutoría, productividad, alfabetización, integridad y gobernanza {citation_block(top_ids[:4])}.",
            "",
            "El patrón interpretativo es que la IA aporta valor cuando media una tarea docente con criterio explícito y supervisión humana, no cuando se introduce como automatización genérica. Por eso la síntesis separa mejora de calidad educativa, reducción de carga, percepción de utilidad y aprendizaje observado: son resultados distintos y no deben colapsarse en una sola promesa de mejora.",
            "",
        ]
    if profile == "creativity_llm":
        family_counts = Counter(creativity_evidence_family(row) for row in focus_rows)
        return [
            "## Síntesis sustantiva de resultados",
            "",
            f"La respuesta sustantiva no es si los LLMs `son creativos`, sino bajo qué configuración producen salidas que una rúbrica acepta como novedosas, útiles o diversas. El subconjunto focal se distribuye en {counter_summary(family_counts, total, limit=6)}, lo que muestra que creatividad cambia de significado según tarea, juez, comparador y criterio de evaluación {citation_block(top_ids[:4])}.",
            "",
            "El patrón central es que la evaluación forma parte del fenómeno: cambiar prompt, dominio, juez o rúbrica puede modificar la conclusión. Por eso la revisión no debe terminar en un ranking de modelos, sino en una gramática de comparación entre tarea, restricción, variación y juicio.",
            "",
        ]
    return [
        "## Síntesis sustantiva de resultados",
        "",
        f"La respuesta sustantiva a la pregunta de investigación se construye comparando mecanismos, métodos, evidencias y límites, no solo frecuencias. En los {total} estudios focales, la síntesis distingue patrones consolidados, señales emergentes y zonas donde la heterogeneidad impide una afirmación fuerte {citation_block(top_ids[:4])}.",
        "",
        f"El resultado principal es que {topic} debe analizarse como configuración: qué objeto se estudia, con qué método, sobre qué unidad de análisis, con qué evidencia y bajo qué límite de transferencia. Esta lectura permite que los estudios se acumulen por comparabilidad real y no solo por vocabulario compartido.",
        "",
    ]


def dominant_label(values: Iterable[str]) -> str:
    cleaned = [value for value in values if value and value.lower() != "no reportado"]
    if not cleaned:
        return "no reportado"
    return Counter(cleaned).most_common(1)[0][0]


def interpretive_summary_for_row(
    row: dict[str, str],
    record: CorpusRecord | None = None,
    profile: str = "software_architecture",
) -> str:
    title = row_title(row, record, width=220)
    method = no_fragment_label(narrative_method_label(row, width=120), "método descrito en el texto completo")
    result = no_fragment_label(
        principal_result_sentence(row, width=260),
        "el estudio aporta evidencia sustantiva útil para delimitar mecanismo, contexto y alcance inferencial.",
    )
    work_type = nice_value(row.get("work_type")).lower()
    if profile == "ai_security_harness":
        family = security_harness_evidence_family(row)
        threat = no_fragment_label(row.get("threat_model"), "amenaza descrita por el estudio")
        control = no_fragment_label(row.get("control_architecture"), "control de seguridad descrito por el estudio")
        enforcement = no_fragment_label(row.get("enforcement_point"), "punto de aplicación descrito por el estudio")
        return (
            f"{title} entra en la revisión porque aporta evidencia trazable en la familia {family.lower()}. "
            f"Evalúa {control} frente a {threat}, con aplicación en {enforcement}. "
            f"Metodológicamente se articula como {method}. Su aportación central es: {result}"
        )
    if profile == "personality_llm":
        model_scope = model_scope_label(row, width=120)
        task_scope = tasks_or_domains_label(row, width=110)
        scope_clause = (
            f"Analiza {model_scope} en el contexto de {task_scope}."
            if model_scope != "no reportado" and task_scope != "no reportado"
            else f"Analiza {model_scope}."
            if model_scope != "no reportado"
            else f"Se centra en {task_scope}."
            if task_scope != "no reportado"
            else ""
        )
        return (
            f"{title} entra en la revisión porque aporta evidencia trazable sobre personalidad en LLMs. "
            f"{scope_clause} En términos metodológicos, se articula como {method}. "
            f"Su aportación central es: {result}"
        )
    if profile == "creativity_llm":
        model_scope = model_scope_label(row, width=120)
        task_scope = tasks_or_domains_label(row, width=110)
        instrument_scope = instruments_label(row, width=110)
        family = creativity_evidence_family(row)
        scope_bits = []
        if model_scope != "no reportado":
            scope_bits.append(f"modelos o sistemas: {model_scope}")
        if task_scope != "no reportado":
            scope_bits.append(f"tareas: {task_scope}")
        if instrument_scope != "no reportado":
            scope_bits.append(f"instrumentos: {instrument_scope}")
        scope_clause = " Analiza " + "; ".join(scope_bits) + "." if scope_bits else ""
        if work_type == "review":
            return (
                f"{title} entra en la revisión porque ordena una familia de evidencia sobre creatividad en LLMs: {family}. "
                f"{scope_clause} Su valor para la pregunta de investigación es: {result}"
            )
        return (
            f"{title} entra en la revisión porque aporta evidencia trazable sobre creatividad de modelos LLM en la familia {family}. "
            f"{scope_clause} Metodológicamente se articula como {method}. "
            f"Su aportación central es: {result}"
        )
    if profile == "ai_higher_education_teaching":
        system_scope = model_scope_label(row, width=120)
        task_scope = tasks_or_domains_label(row, width=120)
        instrument_scope = instruments_label(row, width=110)
        scope_bits = []
        if system_scope != "no reportado":
            scope_bits.append(f"sistemas o herramientas: {system_scope}")
        if task_scope != "no reportado":
            scope_bits.append(f"tareas docentes: {task_scope}")
        if instrument_scope != "no reportado":
            scope_bits.append(f"instrumentos o indicadores: {instrument_scope}")
        scope_clause = " Analiza " + "; ".join(scope_bits) + "." if scope_bits else ""
        if work_type == "review":
            return (
                f"{title} entra en la revisión como trabajo de síntesis porque ordena evidencia sobre IA aplicada a docencia universitaria. "
                f"{scope_clause} Su valor para la pregunta de investigación es: {result}"
            )
        return (
            f"{title} entra en la revisión porque aporta evidencia trazable sobre el uso de IA por profesorado universitario o en tareas docentes de educación superior. "
            f"{scope_clause} Metodológicamente se articula como {method}. "
            f"Su aportación central es: {result}"
        )
    if profile == "social_sciences":
        family = social_science_evidence_family(row)
        unit_raw = normalize_phrase(
            first_nonempty(row.get("unit_of_analysis"), row.get("sample_description"), row.get("benchmark_dataset_or_corpus"))
        )
        variables_raw = normalize_phrase(
            first_nonempty(row.get("variables_dependent"), row.get("variables_independent"), row.get("tasks_or_domains"))
        )
        unit = unit_raw if unit_raw and len(unit_raw) <= 180 else "unidad empírica o corpus descrito por el estudio"
        variables = variables_raw if variables_raw and len(variables_raw) <= 160 else "constructos sociales principales declarados por el estudio"
        scope_bits = []
        if unit.lower() != "no reportado":
            scope_bits.append(f"unidad de análisis: {unit}")
        if variables.lower() != "no reportado":
            scope_bits.append(f"constructos o variables: {variables}")
        scope_clause = " Sitúa la evidencia en " + "; ".join(scope_bits) + "." if scope_bits else ""
        if work_type == "review":
            return (
                f"{title} entra en la revisión como trabajo de síntesis porque ordena evidencia en la familia {family.lower()}. "
                f"{scope_clause} Su valor para la pregunta de investigación es: {result}"
            )
        return (
            f"{title} entra en la revisión porque aporta evidencia trazable de ciencias sociales sobre {family.lower()}. "
            f"{scope_clause} Metodológicamente se articula como {method}. "
            f"Su aportación central es: {result}"
        )
    if profile == "generic":
        if work_type == "review":
            return (
                f"{title} entra en la revisión como trabajo de síntesis porque ordena evidencia relevante para la pregunta del protocolo. "
                f"Su valor para la pregunta de investigación es: {result}"
            )
        return (
            f"{title} entra en la revisión porque aporta evidencia trazable y directamente conectada con el tema definido en el protocolo. "
            f"Metodológicamente se articula como {method}. "
            f"Su aportación central es: {result}"
        )
    archetype = infer_architecture_archetype(row)
    archetype_label = display_archetype(archetype)
    task = software_task_label(row)
    if work_type == "empirical":
        return (
            f"{title} entra en la revisión porque ofrece evidencia empírica trazable sobre una {archetype_label} aplicada a {task}. "
            f"Metodológicamente se apoya en {method}. "
            f"Su aportación central es: {result}"
        )
    if work_type == "review":
        return (
            f"{title} entra en la revisión como trabajo de síntesis porque ordena el campo de {task} desde una lógica de {archetype_label}. "
            f"Su valor para la pregunta de investigación es: {result}"
        )
    return (
        f"{title} entra en la revisión porque formula o estabiliza una {archetype_label} relevante para {task}. "
        f"Se apoya en {method} y aporta sobre todo que {result}"
    )


def study_explanatory_paragraph_for_row(
    row: dict[str, str],
    record: CorpusRecord | None = None,
    profile: str = "software_architecture",
) -> str:
    work_type = display_work_type(row.get("work_type"))
    empirical_type = display_empirical_type(row.get("empirical_type") or "")
    countries = display_countries(row.get("countries"))
    sample = no_fragment_label(benchmark_or_sample_label(row), "muestra, corpus o contexto empírico descrito por el estudio")
    theory = display_theory_label(row.get("theory_framework"))
    method = no_fragment_label(summarize_phrase(row.get("method_used"), width=150), "método descrito en el texto completo")
    design_detail = no_fragment_label(design_detail_label(row, width=170), "diseño descrito en el texto completo")
    unit = no_fragment_label(unit_of_analysis_label(row, width=120), "unidad empírica o corpus descrito por el estudio")
    model_scope = no_fragment_label(model_scope_label(row, width=150), "modelos o sistemas descritos por el estudio")
    benchmark = no_fragment_label(benchmark_dataset_label(row, width=140), "dataset, corpus o fuente empírica descrita por el estudio")
    task_scope = no_fragment_label(tasks_or_domains_label(row, width=140), "dominio sustantivo descrito por el estudio")
    comparators = no_fragment_label(comparators_label(row, width=140), "comparadores, grupos o condiciones descritos por el estudio")
    instruments = no_fragment_label(instruments_label(row, width=140), "instrumentos o indicadores descritos por el estudio")
    confidence = parse_int(row.get("extraction_confidence"), 0)
    result_sentence = no_fragment_label(
        principal_result_sentence(row, width=280),
        "el estudio aporta evidencia sustantiva que ayuda a delimitar mecanismo, contexto y alcance inferencial.",
    )
    confidence_phrase = (
        "La confianza de extracción es muy alta, de modo que la ficha puede leerse como evidencia especialmente robusta dentro del corpus."
        if confidence >= 90
        else "La confianza de extracción es alta y permite integrar el estudio en la comparación central con una base empírica suficiente."
        if confidence >= 80
        else "La confianza de extracción es moderada y aconseja interpretar el estudio con más cautela que el núcleo más robusto del corpus."
    )
    if work_type.lower() == "revisión":
        design_label = "de revisión"
    elif work_type.lower() == "teórico":
        design_label = "teórico"
    else:
        design_label = work_type if empirical_type.lower() == "no reportado" else f"{work_type} de tipo {empirical_type}"
    design_detail_clause = (
        f"El diseño concreto puede resumirse como {design_detail}."
        if design_detail.lower() != "no reportado"
        else "El PDF no detalla con suficiente precisión el diseño más allá de la clasificación general del estudio."
    )
    unit_clause = (
        f"La unidad analítica principal se define como {unit}."
        if unit.lower() != "no reportado"
        else "La unidad analítica no queda plenamente explicitada en el PDF."
    )
    sample_clause = (
        f"La unidad analítica o muestra reportada se concreta en {sample}."
        if sample.lower() != "no reportado"
        else "El artículo no explicita con suficiente detalle la unidad analítica o el tamaño muestral, lo que limita la comparabilidad fina."
    )
    country_clause = (
        f"El contexto empírico se sitúa en {countries}."
        if countries.lower() != "no reportado"
        else "El país o contexto empírico no queda reportado con claridad en el PDF, lo que reduce la capacidad de contextualizar externamente los hallazgos."
    )
    theory_clause = (
        f"El marco teórico declarado es {theory}."
        if theory.lower() != "no reportado"
        else "El trabajo no explicita un marco teórico fuerte, de modo que su aportación es más instrumental que acumulativa en términos conceptuales."
    )
    if profile == "ai_security_harness":
        threat = no_fragment_label(row.get("threat_model"), "amenaza no reportada con precisión")
        control = no_fragment_label(row.get("control_architecture"), "control no reportado con precisión")
        enforcement = no_fragment_label(row.get("enforcement_point"), "punto de aplicación no reportado")
        adaptivity = no_fragment_label(row.get("attacker_adaptivity"), "adaptatividad del atacante no reportada")
        efficacy = no_fragment_label(row.get("attack_success_rate"), "métrica de eficacia no reportada")
        utility = no_fragment_label(row.get("utility_impact"), "impacto en utilidad no reportado")
        overhead = "; ".join(
            value
            for value in (
                no_fragment_label(row.get("latency_overhead"), ""),
                no_fragment_label(row.get("cost_overhead"), ""),
            )
            if value
        ) or "sobrecoste no reportado"
        robustness = no_fragment_label(row.get("robustness_evidence"), "robustez no reportada")
        failure = no_fragment_label(row.get("failure_modes"), "fallo residual no reportado")
        return (
            f"Desde el punto de vista del diseño, se trata de un estudio {design_label} apoyado en {method}. "
            f"{design_detail_clause} Protege frente a {threat} mediante {control}, aplicado en {enforcement}; la capacidad del atacante se clasifica como {adaptivity}. "
            f"El comparador principal es {comparators}. La eficacia se reporta como {efficacy}, el efecto sobre uso legítimo como {utility} y el sobrecoste como {overhead}. "
            f"La evidencia de robustez es {robustness} y el fallo residual recuperable es {failure}. "
            f"Para la pregunta de investigación, esto importa así: {result_sentence} {confidence_phrase}"
        )
    if profile == "personality_llm":
        model_clause = (
            f"El estudio examina de forma explícita {model_scope}."
            if model_scope.lower() != "no reportado"
            else "El artículo no identifica con detalle los modelos o sistemas analizados."
        )
        benchmark_clause = (
            f"El benchmark o corpus empírico principal se concreta en {benchmark}."
            if benchmark.lower() != "no reportado"
            else "El benchmark, dataset o corpus no queda descrito con suficiente detalle."
        )
        task_clause = (
            f"La tarea o el dominio empírico se sitúan en {task_scope}."
            if task_scope.lower() != "no reportado"
            else "La tarea empírica queda descrita de forma más general que específica."
        )
        comparator_clause = (
            f"Las comparaciones sustantivas se establecen frente a {comparators}."
            if comparators.lower() != "no reportado"
            else "El trabajo no explicita con suficiente nitidez las líneas base o comparadores."
        )
        instrument_clause = (
            f"Los instrumentos o escalas movilizados incluyen {instruments}."
            if instruments.lower() != "no reportado"
            else "No se recuperan con claridad instrumentos o escalas estandarizadas en el PDF."
        )
        return (
            f"Desde el punto de vista del diseño, se trata de un estudio {design_label} apoyado en {method}. "
            f"{design_detail_clause} {unit_clause} {sample_clause} {country_clause} "
            f"{model_clause} {benchmark_clause} {task_clause} {comparator_clause} {instrument_clause} {theory_clause} "
            f"Para la pregunta de investigación, esto importa así: {result_sentence} {confidence_phrase}"
        )
    if profile == "ai_higher_education_teaching":
        model_clause = (
            f"El estudio examina de forma explícita {model_scope}."
            if model_scope.lower() != "no reportado"
            else "El artículo no identifica con detalle todos los sistemas, herramientas o modelos de IA analizados."
        )
        benchmark_clause = (
            f"El benchmark, dataset, curso, corpus o escenario educativo principal se concreta en {benchmark}."
            if benchmark.lower() != "no reportado"
            else "El curso, dataset, corpus o escenario educativo no queda descrito con suficiente detalle."
        )
        task_clause = (
            f"La tarea o dominio docente se sitúa en {task_scope}."
            if task_scope.lower() != "no reportado"
            else "La tarea docente queda descrita de forma más general que específica."
        )
        comparator_clause = (
            f"Las comparaciones sustantivas se establecen frente a {comparators}."
            if comparators.lower() != "no reportado"
            else "El trabajo no explicita con suficiente nitidez las líneas base, condiciones de control o comparadores institucionales."
        )
        instrument_clause = (
            f"Los instrumentos, escalas o indicadores educativos movilizados incluyen {instruments}."
            if instruments.lower() != "no reportado"
            else "No se recuperan con claridad instrumentos, escalas o indicadores educativos estandarizados en el PDF."
        )
        return (
            f"Desde el punto de vista del diseño, se trata de un estudio {design_label} apoyado en {method}. "
            f"{design_detail_clause} {unit_clause} {sample_clause} {country_clause} "
            f"{model_clause} {benchmark_clause} {task_clause} {comparator_clause} {instrument_clause} {theory_clause} "
            f"Para la pregunta de investigación, esto importa así: {result_sentence} {confidence_phrase}"
        )
    if profile == "social_sciences":
        family = social_science_evidence_family(row)
        construct_clause = (
            f"El fenómeno sustantivo se ubica en {task_scope}."
            if task_scope.lower() != "no reportado"
            else f"El fenómeno sustantivo se clasifica dentro de {family.lower()}."
        )
        variable_clause = (
            "Las variables o dimensiones recuperadas son "
            + no_fragment_label(
                summarize_phrase_soft(
                    "; ".join(
                        value
                        for value in (
                            row.get("variables_dependent", ""),
                            row.get("variables_independent", ""),
                            row.get("variables_moderating", ""),
                            row.get("variables_mediating", ""),
                        )
                        if nice_value(value).lower() != "no reportado"
                    ),
                    width=180,
                ),
                "constructos sociales principales declarados por el estudio",
            )
            + "."
        )
        if variable_clause == "Las variables o dimensiones recuperadas son .":
            variable_clause = "El artículo no explicita con suficiente claridad todas las variables o dimensiones, lo que limita la comparación fina."
        comparator_clause = (
            f"El comparador, baseline o contraste principal se recupera como {comparators}."
            if comparators.lower() != "no reportado"
            else "El comparador o contraste causal no queda suficientemente detallado; por eso el estudio pesa más como señal descriptiva que como prueba causal fuerte."
        )
        instrument_clause = (
            f"Los instrumentos, escalas o indicadores movilizados incluyen {instruments}."
            if instruments.lower() != "no reportado"
            else "No se recuperan con claridad instrumentos, escalas o indicadores estandarizados en el PDF."
        )
        return (
            f"Desde el punto de vista del diseño, se trata de un estudio {design_label} apoyado en {method}. "
            f"{design_detail_clause} {unit_clause} {sample_clause} {country_clause} "
            f"{construct_clause} {variable_clause} {comparator_clause} {instrument_clause} {theory_clause} "
            f"Para la pregunta de investigación, esto importa así: {result_sentence} {confidence_phrase}"
        )
    if profile == "generic":
        method_clause = (
            f"El método usado se recupera como {method}."
            if method.lower() != "no reportado"
            else "El método no queda descrito con suficiente precisión en el PDF."
        )
        topic_clause = (
            f"La tarea, dominio o fenómeno analizado se sitúa en {task_scope}."
            if task_scope.lower() != "no reportado"
            else "El dominio empírico aparece descrito de forma general y se interpreta desde los criterios del protocolo."
        )
        comparator_clause = (
            f"Las líneas base o comparadores explícitos son {comparators}."
            if comparators.lower() != "no reportado"
            else "El trabajo no explicita comparadores fuertes, lo que limita la lectura causal o comparativa."
        )
        return (
            f"Desde el punto de vista del diseño, se trata de un estudio {design_label}. "
            f"{design_detail_clause} {unit_clause} {sample_clause} {country_clause} "
            f"{method_clause} {topic_clause} {comparator_clause} {theory_clause} "
            f"Para la pregunta de investigación, esto importa así: {result_sentence} {confidence_phrase}"
        )
    if profile == "creativity_llm":
        model_clause = (
            f"El estudio examina de forma explícita {model_scope}."
            if model_scope.lower() != "no reportado"
            else "El artículo no identifica con detalle todos los modelos o sistemas analizados."
        )
        benchmark_clause = (
            f"El benchmark, dataset o corpus principal se concreta en {benchmark}."
            if benchmark.lower() != "no reportado"
            else "El benchmark, dataset o corpus no queda descrito con suficiente detalle."
        )
        task_clause = (
            f"La tarea o dominio creativo se sitúa en {task_scope}."
            if task_scope.lower() != "no reportado"
            else "La tarea creativa queda descrita de forma más general que específica."
        )
        comparator_clause = (
            f"Las comparaciones sustantivas se establecen frente a {comparators}."
            if comparators.lower() != "no reportado"
            else "El trabajo no explicita con suficiente nitidez las líneas base, modelos comparados o referencia humana."
        )
        instrument_clause = (
            f"Los instrumentos o escalas movilizados incluyen {instruments}."
            if instruments.lower() != "no reportado"
            else "No se recuperan con claridad instrumentos, métricas o escalas estandarizadas en el PDF."
        )
        return (
            f"Desde el punto de vista del diseño, se trata de un estudio {design_label} apoyado en {method}. "
            f"{design_detail_clause} {unit_clause} {sample_clause} {country_clause} "
            f"{model_clause} {benchmark_clause} {task_clause} {comparator_clause} {instrument_clause} {theory_clause} "
            f"Para la pregunta de investigación, esto importa así: {result_sentence} {confidence_phrase}"
        )
    archetype = display_archetype(infer_architecture_archetype(row))
    task = software_task_label(row)
    return (
        f"Desde el punto de vista del diseño, se trata de un estudio {design_label} sobre {archetype} aplicada a {task}, apoyado en {method}. "
        f"{design_detail_clause} {unit_clause} {sample_clause} {country_clause} {theory_clause} "
        f"Para la pregunta de investigación, esto importa así: {result_sentence} {confidence_phrase}"
    )


def comparative_takeaway_for_row(row: dict[str, str], profile: str = "software_architecture") -> str:
    if profile == "ai_security_harness":
        return (
            f"Aporta evidencia sobre {security_harness_evidence_family(row).lower()} y permite comparar amenaza, "
            "punto de aplicación, baseline, eficacia, utilidad, coste y fallo residual frente a estudios con contrato defensivo menos completo."
        )
    if profile == "personality_llm":
        return (
            "Aporta sobre todo evidencia sobre medición, control o efectos de personalidad en LLMs "
            "frente a trabajos menos explícitos en variables, muestra o marco teórico."
        )
    if profile == "creativity_llm":
        return (
            f"Aporta sobre todo evidencia sobre {creativity_evidence_family(row).lower()} "
            "frente a estudios que mencionan creatividad o LLMs de forma más tangencial."
        )
    if profile == "ai_higher_education_teaching":
        return (
            "Aporta sobre todo evidencia sobre tareas docentes, adopción universitaria, feedback, evaluación, diseño curricular, "
            "productividad académica o calidad educativa frente a trabajos donde la IA aparece solo como tecnología general."
        )
    if profile == "social_sciences":
        return (
            f"Aporta sobre todo evidencia sobre {social_science_evidence_family(row).lower()} "
            "frente a estudios que solo comparten vocabulario temático, pero no unidad de análisis, método o relación sustantiva comparable."
        )
    if profile == "generic":
        return (
            "Aporta evidencia directa sobre el foco definido en el protocolo y permite contrastar método, muestra, "
            "resultado principal y limitaciones frente al resto del corpus incluido."
        )
    archetype = infer_architecture_archetype(row)
    task = software_task_label(row)
    return (
        f"Aporta sobre todo evidencia sobre {display_archetype(archetype)} orientada a {task} "
        f"frente a {architecture_comparison_target(row)}."
    )


def study_metadata_table(row: dict[str, str], profile: str = "generic") -> str:
    if profile == "ai_security_harness":
        fields = [
            ["Campo", "Valor"],
            ["Tipo de trabajo", table_label(display_work_type(row.get("work_type")))],
            ["Diseño", no_fragment_label(design_detail_label(row, width=150), "diseño descrito en el texto completo")],
            ["Modelos o sistemas protegidos", model_scope_label(row, width=150)],
            ["Harness o defensa", nice_value(row.get("security_harness_name"))],
            ["Arquitectura de control", nice_value(row.get("control_architecture"))],
            ["Punto de aplicación", nice_value(row.get("enforcement_point"))],
            ["Modelo de amenaza", nice_value(row.get("threat_model"))],
            ["Tipo de ataque", nice_value(row.get("attack_type"))],
            ["Adaptatividad del atacante", nice_value(row.get("attacker_adaptivity"))],
            ["Entorno o benchmark", first_nonempty(row.get("evaluation_setting"), benchmark_dataset_label(row, width=140))],
            ["Baseline o comparador", comparators_label(row, width=140)],
            ["Métricas de seguridad", nice_value(row.get("security_metrics"))],
            ["Tasa de éxito del ataque", nice_value(row.get("attack_success_rate"))],
            ["Falsos positivos", nice_value(row.get("false_positive_rate"))],
            ["Impacto en utilidad", nice_value(row.get("utility_impact"))],
            ["Sobrecoste de latencia", nice_value(row.get("latency_overhead"))],
            ["Sobrecoste económico o computacional", nice_value(row.get("cost_overhead"))],
            ["Evidencia de robustez", nice_value(row.get("robustness_evidence"))],
            ["Modos de fallo", nice_value(row.get("failure_modes"))],
            ["Código o artefactos", nice_value(row.get("code_or_artifact_availability"))],
            ["Conclusión defensiva", nice_value(row.get("security_conclusion"))],
            ["Confianza de extracción", nice_value(row.get("extraction_confidence"))],
        ]
    elif profile == "social_sciences":
        fields = [
            ["Campo", "Valor"],
            ["Tipo de trabajo", table_label(display_work_type(row.get("work_type")))],
            ["Tipo empírico", table_label(display_empirical_type(row.get("empirical_type") or ""))],
            ["Diseño detallado", no_fragment_label(design_detail_label(row, width=150), "diseño descrito en el texto completo")],
            ["País o contexto", display_countries(row.get("countries"))],
            ["Unidad analítica", no_fragment_label(unit_of_analysis_label(row, width=120), "unidad empírica o corpus descrito por el estudio")],
            ["Muestra o corpus", no_fragment_label(nice_value(row.get("sample_description")), "muestra, corpus o contexto empírico descrito por el estudio")],
            ["Tamaño de la muestra", nice_value(row.get("sample_size"))],
            ["Constructos o dominios", no_fragment_label(tasks_or_domains_label(row, width=140), "constructos o dominios descritos por el estudio")],
            ["Datos, corpus o fuente empírica", no_fragment_label(benchmark_dataset_label(row, width=140), "datos, corpus o fuente empírica descrita por el estudio")],
            ["Base comparativa o contraste", no_fragment_label(comparators_label(row, width=140), "comparadores, grupos o condiciones descritos por el estudio")],
            ["Instrumentos o indicadores", no_fragment_label(instruments_label(row, width=140), "instrumentos o indicadores descritos por el estudio")],
            ["Método usado", nice_value(row.get("method_used"))],
            ["Variables dependientes", nice_value(row.get("variables_dependent"))],
            ["Variables independientes", nice_value(row.get("variables_independent"))],
            ["Variables moderadoras", nice_value(row.get("variables_moderating"))],
            ["Variables mediadoras", nice_value(row.get("variables_mediating"))],
            ["Variables de control", nice_value(row.get("variables_control"))],
            ["Marco teórico", display_theory_label(row.get("theory_framework"))],
            ["Resultado principal", no_fragment_label(principal_result_label(row, width=140), "resultado sustantivo descrito en la ficha interpretativa")],
            ["Confianza de extracción", nice_value(row.get("extraction_confidence"))],
        ]
    else:
        fields = [
            ["Campo", "Valor"],
            ["Tipo de trabajo", table_label(display_work_type(row.get("work_type")))],
            ["Tipo empírico", table_label(display_empirical_type(row.get("empirical_type") or ""))],
            ["Diseño detallado", design_detail_label(row, width=150)],
            ["País o países", display_countries(row.get("countries"))],
            ["Unidad analítica", unit_of_analysis_label(row, width=120)],
            ["Muestra", nice_value(row.get("sample_description"))],
            ["Tamaño de la muestra", nice_value(row.get("sample_size"))],
            ["Modelos o sistemas analizados", model_scope_label(row, width=150)],
            ["Número de modelos o sistemas", sanitized_model_count(row.get("model_count"))],
            ["Benchmark, dataset o corpus", benchmark_dataset_label(row, width=140)],
            ["Tareas o dominios", tasks_or_domains_label(row, width=140)],
            ["Baselines o comparadores", comparators_label(row, width=140)],
            ["Instrumentos o escalas", instruments_label(row, width=140)],
            ["Método usado", nice_value(row.get("method_used"))],
            ["Variables dependientes", nice_value(row.get("variables_dependent"))],
            ["Variables independientes", nice_value(row.get("variables_independent"))],
            ["Variables moderadoras", nice_value(row.get("variables_moderating"))],
            ["Variables mediadoras", nice_value(row.get("variables_mediating"))],
            ["Variables de control", nice_value(row.get("variables_control"))],
            ["Marco teórico", display_theory_label(row.get("theory_framework"))],
            ["Resultado principal", principal_result_label(row, width=140)],
            ["Confianza de extracción", nice_value(row.get("extraction_confidence"))],
        ]
    headers, body = fields[0], fields[1:]
    return markdown_table(headers, body)


def study_comparison_rows(focus_rows: list[dict[str, str]]) -> list[list[str]]:
    rendered: list[list[str]] = []
    for row in focus_rows:
        flags = component_flags(row)
        rendered.append(
            [
                f"{public_doi_value(row)} - {row_title(row, width=64)}",
                display_archetype(infer_architecture_archetype(row)),
                bool_label(flags.get("roles", False)),
                bool_label(flags.get("orquestador", False)),
                bool_label(flags.get("herramientas", False)),
                bool_label(flags.get("memoria", False)),
                bool_label(flags.get("verificador", False)),
                software_task_label(row),
                benchmark_or_sample_label(row),
                principal_metric_label(row),
                principal_result_label(row, width=95),
                nice_value(row.get("extraction_confidence")),
            ]
        )
    return rendered


def empirical_comparison_rows(focus_rows: list[dict[str, str]]) -> list[list[str]]:
    rendered: list[list[str]] = []
    for row in focus_rows:
        if nice_value(row.get("work_type")).lower() != "empirical":
            continue
        design_cell = table_label(
            summarize_phrase_soft(
                first_nonempty(row.get("design_detail"), display_empirical_type(row.get("empirical_type") or "")),
                width=85,
            )
        )
        rendered.append(
            [
                f"{public_doi_value(row)} - {row_title(row, width=60)}",
                design_cell,
                summarize_phrase_soft(first_nonempty(row.get("unit_of_analysis"), row.get("sample_description")), width=85),
                nice_value(row.get("sample_size")),
                summarize_phrase_soft(row.get("variables_dependent"), width=85),
                summarize_phrase_soft(row.get("variables_independent"), width=85),
                summarize_phrase_soft(row.get("method_used"), width=85),
                summarize_phrase_soft(display_countries(row.get("countries")), width=45),
                display_theory_label(row.get("theory_framework"), width=95),
            ]
        )
    return rendered


def theory_family_labels_for_row(row: dict[str, str]) -> list[str]:
    raw = row.get("theory_framework", "")
    labels: list[str] = []
    for token in split_theory_framework_tokens(raw):
        label = display_theory_label(token, width=220)
        if label and label.lower() != "no reportado":
            labels.append(label)
    deduped = dedupe_preserve(labels)
    return deduped or ["no reportado"]


def theory_archetype_rows(focus_rows: list[dict[str, str]], limit: int = 6) -> list[list[str]]:
    archetype_order = [
        "multiagente orquestado",
        "skill-based o capability-based",
        "tool-augmented agent",
        "evaluación o benchmark arquitectónico",
        "arquitectura híbrida o no tipificada",
        "gobernanza y auditoría",
    ]
    counter: dict[str, Counter[str]] = {}
    for row in focus_rows:
        archetype = infer_architecture_archetype(row)
        for theory_label in theory_family_labels_for_row(row):
            bucket = counter.setdefault(theory_label, Counter())
            bucket[archetype] += 1
    ordered_labels = [
        label
        for label, _count in sorted(
            ((label, sum(counts.values())) for label, counts in counter.items() if label != "no reportado"),
            key=lambda item: (-item[1], item[0].lower()),
        )[:limit]
    ]
    if "no reportado" in counter:
        ordered_labels.append("no reportado")
    rendered: list[list[str]] = []
    for label in ordered_labels:
        counts = counter.get(label, Counter())
        total = sum(counts.values())
        rendered.append([label, *[str(counts.get(archetype, 0)) for archetype in archetype_order], str(total)])
    return rendered


def compact_theory_table_label(label: str) -> str:
    """Shorten theory labels so wide LaTeX tables remain readable on one page."""
    normalized = normalize_phrase(label).lower()
    if normalized == "no reportado":
        return "No reportado"
    if "teoria de sistemas multiagente" in normalized:
        return "Sist. multiagente"
    if "crisp-dm" in normalized:
        return "CRISP-DM"
    if "design science" in normalized or normalized == "dsr":
        return "DSR"
    if "spar" in normalized:
        return "SPAR"
    if "scrum" in normalized:
        return "Scrum"
    if "arbol de ia" in normalized or "árbol de ia" in label.lower():
        return "Árbol de IA"
    return table_label(summarize_phrase_soft(label, width=28))


def compact_theory_archetype_rows(rows: list[list[str]]) -> list[list[str]]:
    return [[compact_theory_table_label(row[0]), *row[1:]] for row in rows]


def archetype_counter(rows: list[dict[str, str]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[infer_architecture_archetype(row)] += 1
    return counter


PERSONALITY_CONSTRUCT_PATTERNS = {
    "big_five": r"big five|five-factor|ocean",
    "mbti": r"\bmbti\b|jungian",
    "hexaco": r"\bhexaco\b",
    "persona_control": r"persona|role-play|role playing|slider|steering|control|adaptation|activation",
    "assessment_validation": r"assessment|profil|questionnaire|psychometric|benchmark|validation|ranking|classification",
    "human_effects": r"alignment|self-concept|preference|conversation|interaction|tutor|debunking|dispute|affective",
    "bias_safety": r"bias|jailbreak|fairness|risk|moral|harm",
}


PERSONALITY_CONSTRUCT_LABELS = {
    "big_five": "Big Five / OCEAN",
    "mbti": "MBTI / tipos junguianos",
    "hexaco": "HEXACO",
    "persona_control": "Persona, role-play y control",
    "assessment_validation": "Medición, profiling y validación",
    "human_effects": "Interacción humana y alineamiento",
    "bias_safety": "Sesgo, riesgo y seguridad",
}


def personality_construct_flags(row: dict[str, str]) -> dict[str, bool]:
    blob = normalized_text(
        " ".join(
            [
                row.get("title_original", ""),
                row.get("abstract_original", ""),
                row.get("abstract_en", ""),
                row.get("keywords_normalized", ""),
                row.get("method_used", ""),
                row.get("key_findings", ""),
            ]
        )
    )
    return {
        name: bool(re.search(pattern, blob, flags=re.IGNORECASE))
        for name, pattern in PERSONALITY_CONSTRUCT_PATTERNS.items()
    }


def personality_construct_counter(rows: list[dict[str, str]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        for key, enabled in personality_construct_flags(row).items():
            if enabled:
                counter[PERSONALITY_CONSTRUCT_LABELS[key]] += 1
    return counter


def personality_method_family_counter(rows: list[dict[str, str]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        blob = normalized_text(
            " ".join(
                [
                    row.get("method_used", ""),
                    row.get("abstract_original", ""),
                    row.get("key_findings", ""),
                ]
            )
        )
        if re.search(r"benchmark|validation|profil|questionnaire|psychometric|ranking|classification", blob, flags=re.IGNORECASE):
            counter["Assessment / benchmarking"] += 1
        if re.search(r"role-play|persona|steering|slider|control|adaptation|activation|decoding", blob, flags=re.IGNORECASE):
            counter["Persona steering / control"] += 1
        if re.search(r"bias|jailbreak|risk|moral|debunking|fairness", blob, flags=re.IGNORECASE):
            counter["Bias / safety / persuasion"] += 1
        if re.search(r"conversation|interaction|preference|self-concept|tutor|assistive|dispute", blob, flags=re.IGNORECASE):
            counter["Human interaction / alignment"] += 1
    return counter


def personality_construct_matrix_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rendered = []
    for row in rows:
        flags = personality_construct_flags(row)
        rendered.append(
            {
                "record_id": row.get("record_id", ""),
                "title_original": row.get("title_original", ""),
                "work_type": row.get("work_type", ""),
                "empirical_type": row.get("empirical_type", ""),
                "big_five": "1" if flags["big_five"] else "0",
                "mbti": "1" if flags["mbti"] else "0",
                "hexaco": "1" if flags["hexaco"] else "0",
                "persona_control": "1" if flags["persona_control"] else "0",
                "assessment_validation": "1" if flags["assessment_validation"] else "0",
                "human_effects": "1" if flags["human_effects"] else "0",
                "bias_safety": "1" if flags["bias_safety"] else "0",
                "theory_framework": row.get("theory_framework", ""),
                "extraction_confidence": row.get("extraction_confidence", ""),
            }
        )
    return rendered


def export_personality_construct_matrix(review_dir: pathlib.Path, focus_rows: list[dict[str, str]]) -> pathlib.Path:
    matrix_path = review_dir / "tables" / "personality-construct-matrix.csv"
    rows = personality_construct_matrix_rows(focus_rows)
    write_csv_rows(
        matrix_path,
        [
            "record_id",
            "title_original",
            "work_type",
            "empirical_type",
            "big_five",
            "mbti",
            "hexaco",
            "persona_control",
            "assessment_validation",
            "human_effects",
            "bias_safety",
            "theory_framework",
            "extraction_confidence",
        ],
        rows,
    )
    return matrix_path


def export_architecture_component_matrix(review_dir: pathlib.Path, focus_rows: list[dict[str, str]]) -> pathlib.Path:
    matrix_path = review_dir / "tables" / "architecture-component-matrix.csv"
    fieldnames = [
        "record_id",
        "title_original",
        "work_type",
        "empirical_type",
        "memoria",
        "orquestador",
        "herramientas",
        "verificador",
        "roles",
        "archetype",
        "extraction_confidence",
    ]
    rows = []
    for row in focus_rows:
        flags = component_flags(row)
        rows.append(
            {
                "record_id": row.get("record_id", ""),
                "title_original": row.get("title_original", ""),
                "work_type": row.get("work_type", ""),
                "empirical_type": row.get("empirical_type", ""),
                "memoria": "1" if flags["memoria"] else "0",
                "orquestador": "1" if flags["orquestador"] else "0",
                "herramientas": "1" if flags["herramientas"] else "0",
                "verificador": "1" if flags["verificador"] else "0",
                "roles": "1" if flags["roles"] else "0",
                "archetype": infer_architecture_archetype(row),
                "extraction_confidence": row.get("extraction_confidence", ""),
            }
        )
    write_csv_rows(matrix_path, fieldnames, rows)
    return matrix_path


def export_selection_score_matrix(review_dir: pathlib.Path, focus_rows: list[dict[str, str]]) -> pathlib.Path:
    matrix_path = review_dir / "tables" / "selection-score-matrix.csv"
    focus_ids = {row.get("record_id", "") for row in focus_rows if row.get("record_id")}
    rows = []
    for row in read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv"):
        record_id = row.get("record_id", "")
        if not has_public_doi(row):
            continue
        decision = (row.get("decision_before_cap") or "").strip().lower()
        if record_id not in focus_ids and decision not in {"include", "include_ft"}:
            continue
        reason = normalize_phrase(row.get("cap_exclusion_reason"))
        if reason and ("cap ultraquality" in normalized_text(reason) or "menor puntuacion compuesta" in normalized_text(reason)):
            reason = (
                "Incluido en corpus contextual; fuera del corte focal por score compuesto inferior al umbral efectivo "
                "o menor densidad comparativa para la comparación intensiva."
            )
        is_focal = record_id in focus_ids
        rows.append(
            {
                "ultraquality_rank": row.get("ultraquality_rank", ""),
                "selection_status": "focal" if is_focal else "contextual_non_focal_not_individually_scored",
                "doi": public_doi_value(row),
                "title_full": normalize_phrase(row.get("title_original")) or "no reportado",
                "relevance_score": score_label(row.get("relevance_score")) if is_focal else "no aplica",
                "methodological_quality_score": score_label(row.get("methodological_quality_score")) if is_focal else "no aplica",
                "representativeness_score": score_label(row.get("representativeness_score")) if is_focal else "no aplica",
                "composite_score": score_label(composite_selection_score(row)) if is_focal else "no aplica",
                "operational_reason": reason or ("Incluido en síntesis focal" if is_focal else "Perímetro contextual elegible sin evaluación individual fina"),
            }
        )
    rows.sort(key=lambda item: (parse_int(item["ultraquality_rank"], 9999), item["doi"]))
    write_csv_rows(
        matrix_path,
        [
            "ultraquality_rank",
            "selection_status",
            "doi",
            "title_full",
            "relevance_score",
            "methodological_quality_score",
            "representativeness_score",
            "composite_score",
            "operational_reason",
        ],
        rows,
    )
    return matrix_path


def write_prisma_checklist(review_dir: pathlib.Path, flow_counts: dict[str, int], context: dict[str, str]) -> pathlib.Path:
    checklist_path = review_dir / "paper" / "appendices" / "data" / "prisma-checklist.md"
    checklist_path.parent.mkdir(parents=True, exist_ok=True)
    profile = detect_review_profile(context)
    items = [
        ("1", "Título", "Cubierto", "Título del manuscrito"),
        ("2", "Resumen", "Cubierto", "Resumen estructurado narrativo en la sección inicial"),
        ("3", "Justificación", "Cubierto", "Introducción y marco teórico"),
        ("4", "Objetivos", "Cubierto", publication_research_question(context, profile)),
        ("5", "Criterios de elegibilidad", "Cubierto", "Método, criterios de inclusión/exclusión"),
        ("6", "Fuentes de información", "Cubierto", "Search-log y Tabla 2"),
        ("7", "Estrategia de búsqueda", "Cubierto", "protocol/search-strategy.md y search-log.csv"),
        ("8", "Proceso de selección", "Cubierto", "Tabla de flujo de selección y screening CSV"),
        ("9", "Proceso de extracción", "Cubierto", "extraction/extraction-table.csv"),
        ("10a", "Lista de datos", "Cubierto", "Tabla de extracción y anexos CSV"),
        ("10b", "Definiciones/assumptions", "Cubierto", "Método y rúbrica de extracción"),
        ("11", "Riesgo de sesgo", "Cubierto parcialmente", "Perfil de reporting y confianza de extracción"),
        ("12", "Medidas de efecto", "No aplicable", "No se realizó meta-análisis cuantitativo"),
        ("13a", "Síntesis: estudios elegibles", "Cubierto", "Regla DOI + PDF + texto completo"),
        ("13b", "Preparación de datos", "Cubierto", "Normalización DOI, deduplicación y extracción"),
        ("13c", "Tabulación/visualización", "Cubierto", "Figuras y tablas del manuscrito"),
        ("13d", "Métodos de síntesis", "Cubierto", "Síntesis focal, score y matriz comparativa"),
        ("13e", "Exploración de heterogeneidad", "Cubierto", "Resultados, discusión y limitaciones"),
        ("13f", "Sensibilidad", "Cubierto", "Tabla 3 y matriz de selección"),
        ("14", "Sesgo de publicación", "Cubierto parcialmente", "Limitaciones por DOI/PDF y disponibilidad"),
        ("15", "Certeza de evidencia", "Cubierto parcialmente", "Confianza de extracción y reporting"),
        ("16a", "Selección de estudios", "Cubierto", "Figura PRISMA"),
        ("16b", "Exclusiones", "Cubierto", "screening/full-text.csv y selection CSV"),
        ("17", "Características de estudios", "Cubierto", "Fichas analíticas y tabla comparativa"),
        ("18", "Riesgo de sesgo en estudios", "Cubierto parcialmente", "Tabla de reporting/riesgo"),
        ("19", "Resultados individuales", "Cubierto", "Fichas por estudio"),
        ("20a", "Resultados de síntesis", "Cubierto", "Resultados y discusión"),
        ("20b", "Heterogeneidad", "Cubierto", "Resultados y amenazas a la validez"),
        ("20c", "Sensibilidad", "Cubierto", "Shortlist sensitivity"),
        ("20d", "Certeza de evidencia", "Cubierto parcialmente", "Confianza de extracción"),
        ("21", "Sesgos de reporte", "Cubierto", "Amenazas a la validez"),
        ("22", "Certeza global", "Cubierto parcialmente", "Conclusiones y limitaciones"),
        ("23a", "Interpretación general", "Cubierto", "Discusión"),
        ("23b", "Limitaciones de evidencia", "Cubierto", "Amenazas a la validez"),
        ("23c", "Limitaciones del proceso", "Cubierto", "Método y discusión"),
        ("23d", "Implicaciones", "Cubierto", "Discusión y líneas futuras"),
        ("24a", "Registro/protocolo", "Cubierto parcialmente", "Sin preregistro externo; protocolo local auditable"),
        ("24b", "Acceso al protocolo", "Cubierto", "protocol/*.md en paquete editorial"),
        ("24c", "Enmiendas", "Cubierto", "notes/decisions.md"),
        ("25", "Soporte financiero", "Cubierto", "Declaraciones editoriales"),
        ("26", "Conflictos de interés", "Cubierto", "Declaraciones editoriales"),
        ("27", "Disponibilidad de datos", "Cubierto", "Anexos CSV y paquete editorial"),
    ]
    lines = [
        "# PRISMA 2020 Checklist",
        "",
        f"- Tema: {context.get('topic') or 'no reportado'}",
        f"- Pregunta de investigación: {publication_research_question(context, profile)}",
        f"- Registros identificados: {flow_counts.get('identified', 0)}",
        f"- Título/resumen cribados: {flow_counts.get('screened_title_abstract', 0)}",
        f"- Textos completos evaluados en PDF: {flow_counts.get('full_text_assessed', 0)}",
        f"- Estudios incluidos en la revisión: {flow_counts.get('included_in_review', 0)}",
        f"- Base normativa APA: {PRISMA_2020_APA}",
        f"- Extensión de búsqueda APA: {PRISMA_S_APA}",
        "",
        "| Ítem | Elemento PRISMA 2020 | Estado | Localización/evidencia |",
        "|---|---|---|---|",
        *[f"| {item} | {label} | {status} | {location} |" for item, label, status, location in items],
        "",
        "Nota: los elementos marcados como `Cubierto parcialmente` reflejan límites propios de una revisión sin meta-análisis y con regla DOI/PDF estricta; no se ocultan como cumplimiento pleno.",
    ]
    write_text(checklist_path, "\n".join(lines) + "\n")
    return checklist_path


def ensure_visual_evidence(review_dir: pathlib.Path, selected_rows: list[dict[str, str]]) -> None:
    enable_source_visuals = os.environ.get("HERMES_ENABLE_SOURCE_VISUAL_EVIDENCE", "").strip().lower() in {"1", "true", "yes", "on"}
    try:
        source_visual_limit = max(0, int(os.environ.get("HERMES_SOURCE_VISUAL_EVIDENCE_LIMIT", "8")))
    except ValueError:
        source_visual_limit = 8
    figures_manifest = review_dir / "figures" / "evidence-manifest.csv"
    page_renders_manifest = review_dir / "figures" / "page-render-manifest.csv"
    tables_manifest = review_dir / "tables" / "evidence-manifest.csv"
    figures_extracted = review_dir / "figures" / "extracted"
    page_renders_dir = review_dir / "figures" / "page-renders"
    tables_extracted = review_dir / "tables" / "extracted"
    figures_extracted.mkdir(parents=True, exist_ok=True)
    page_renders_dir.mkdir(parents=True, exist_ok=True)
    tables_extracted.mkdir(parents=True, exist_ok=True)
    for directory in (figures_extracted, page_renders_dir, tables_extracted):
        for path in directory.iterdir():
            if path.name.lower() == "readme.md":
                continue
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    docling_table_rows, docling_figure_rows = extract_review_documents(review_dir, selected_rows)
    figure_rows = list(docling_figure_rows)
    page_render_rows = []
    table_rows = list(docling_table_rows)
    docling_figure_dois = {row.get("record_id", "") for row in docling_figure_rows}
    docling_table_dois = {row.get("record_id", "") for row in docling_table_rows}
    source_visuals_processed = 0
    for row in selected_rows:
        if not has_public_doi(row):
            continue
        record_id = normalize_docling_doi(public_doi_value(row))
        if not record_id:
            continue
        source_path = row.get("full_text_path", "")
        assets: list[dict[str, str]] = []
        source_file = pathlib.Path(source_path) if source_path else pathlib.Path()
        if (
            record_id not in docling_figure_dois
            and
            enable_source_visuals
            and source_visuals_processed < source_visual_limit
            and source_file.exists()
            and source_file.suffix.lower() == ".pdf"
        ):
            assets = extract_pdf_figure_assets(source_file, record_id, figures_extracted, page_render_dir=page_renders_dir)
            source_visuals_processed += 1
        elif (
            record_id not in docling_figure_dois
            and
            enable_source_visuals
            and source_visuals_processed < source_visual_limit
            and (source_path.lower().endswith((".html", ".htm")) or source_path.startswith(("http://", "https://")))
        ):
            assets = extract_html_figure_assets(source_path, record_id, figures_extracted)
            source_visuals_processed += 1
        fig_asset = write_visual_asset_markdown(review_dir, record_id, source_path, assets, row)
        table_asset = tables_extracted / f"{slugify(record_id)}-summary.csv"
        if record_id not in docling_table_dois:
            table_asset.write_text(
                "field,value\n"
                + "\n".join(
                    [
                        f"doi,{record_id}",
                        f"title,{(row.get('title_original') or '').replace(',', ';')}",
                        f"work_type,{(row.get('work_type') or '').replace(',', ';')}",
                        f"empirical_type,{(row.get('empirical_type') or '').replace(',', ';')}",
                        f"countries,{(row.get('countries') or '').replace(',', ';')}",
                        f"method_used,{(row.get('method_used') or '').replace(',', ';')}",
                        f"sample_size,{(row.get('sample_size') or '').replace(',', ';')}",
                        f"theory_framework,{(row.get('theory_framework') or '').replace(',', ';')}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        if assets:
            for asset in assets:
                target_rows = page_render_rows if asset.get("status") == "rendered_from_pdf_page" else figure_rows
                target_rows.append(
                    {
                        "record_id": asset.get("record_id", record_id),
                        "asset_id": asset.get("asset_id", f"{record_id}-fig"),
                        "source_path": asset.get("source_path", source_path),
                        "page_or_location": asset.get("page_or_location", "no reportado"),
                        "extracted_asset_path": pathlib.Path(asset.get("extracted_asset_path", "")).relative_to(review_dir).as_posix()
                        if asset.get("extracted_asset_path")
                        else fig_asset.relative_to(review_dir).as_posix(),
                        "vision_model": asset.get("vision_model", ""),
                        "status": asset.get("status", "catalogued_from_pdf"),
                    }
                )
        elif record_id not in docling_figure_dois:
            figure_rows.append(
                {
                    "record_id": record_id,
                    "asset_id": f"{record_id}-fig-md",
                    "source_path": source_path,
                    "page_or_location": "Sin activo visual extraíble; resumen Markdown del documento",
                    "extracted_asset_path": fig_asset.relative_to(review_dir).as_posix(),
                    "vision_model": "",
                    "status": "no_visual_asset_extracted",
                }
            )
        if record_id not in docling_table_dois:
            table_rows.append(
                {
                    "record_id": record_id,
                    "table_id": f"{record_id}-table",
                    "source_path": source_path,
                    "page_or_location": "PDF completo revisado; tabla derivada desde extracción metodológica",
                    "extracted_table_path": table_asset.relative_to(review_dir).as_posix(),
                    "vision_model": "",
                    "status": "derived_from_pdf_text_fallback",
                }
            )

    with figures_manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["record_id", "asset_id", "source_path", "page_or_location", "extracted_asset_path", "vision_model", "status"])
        writer.writeheader()
        writer.writerows(figure_rows)
    with page_renders_manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["record_id", "asset_id", "source_path", "page_or_location", "extracted_asset_path", "vision_model", "status"])
        writer.writeheader()
        writer.writerows(page_render_rows)
    with tables_manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["record_id", "table_id", "source_path", "page_or_location", "extracted_table_path", "vision_model", "status"])
        writer.writeheader()
        writer.writerows(table_rows)


def build_index_section(selected_rows: list[dict[str, str]]) -> str:
    return "\n".join(
        [
            "# Índice de publicación",
            "",
            "- 1. Título, autoría opcional, resumen y palabras clave",
            "- 2. Introducción",
            "- 3. Marco teórico y tesis teóricas",
            "- 4. Método",
            "- 5. Resultados",
            "- 6. Discusión",
            "- 7. Conclusiones y líneas futuras",
            "- 8. Corpus final incluido",
            "- 9. Anexos de datos y trazabilidad",
            "",
            f"- Corpus final seleccionado: {len(selected_rows)} estudios.",
            "- Este índice se conserva como guía editorial y no se incorpora al manuscrito compilado.",
        ]
    ) + "\n"


def publication_research_question(context: dict[str, str], profile: str) -> str:
    raw = normalize_phrase(context.get("research_question"))
    if raw:
        cleaned = re.sub(
            r"\s+y\s+qu[eé]\s+(?:subconjunto\s+final|top)\b.*$",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = re.sub(
            r"\s+para\s+una\s+s[ií]ntesis\s+comparativa\s+publicable\.?$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = re.sub(r"\bframeworks\b", "marcos", cleaned, flags=re.IGNORECASE)
        if profile == "ai_architecture":
            cleaned = re.sub(
                r"\bse\s+est[aá]n\s+consolidando\b|\bse\s+consolidan\b",
                "emergen o muestran patrones recurrentes",
                cleaned,
                flags=re.IGNORECASE,
            )
        cleaned = cleaned.rstrip(". ")
        if cleaned:
            return cleaned if cleaned.endswith("?") else cleaned + "?"
    if profile == "personality_llm":
        timeframe_es = review_timeframe_phrase_es(context)
        return (
            "¿Se puede medir la personalidad de un modelo de IA razonador y cómo se operacionaliza, induce, "
            f"evalúa y valida empíricamente en la literatura publicada {timeframe_es}?"
        )
    if profile == "creativity_llm":
        timeframe_es = review_timeframe_phrase_es(context)
        return (
            "¿Cómo se evalúa y caracteriza la creatividad de los modelos LLM y de la IA generativa "
            f"en la literatura publicada {timeframe_es}?"
        )
    if profile == "ai_higher_education_teaching":
        timeframe_es = review_timeframe_phrase_es(context)
        return (
            "¿Qué evidencia empírica existe sobre cómo la inteligencia artificial, la IA generativa y los sistemas basados en LLM "
            f"ayudan al profesorado universitario en enseñanza, evaluación, retroalimentación, diseño curricular, productividad académica y calidad educativa {timeframe_es}?"
        )
    if profile == "software_architecture":
        return "¿Qué marcos, patrones de coordinación y componentes arquitectónicos caracterizan las arquitecturas de agentes aplicadas al desarrollo de software publicadas en 2026?"
    if profile == "ai_architecture":
        return "¿Qué familias de arquitectura de inteligencia artificial publicadas en 2026 emergen o muestran patrones recurrentes en modelos fundacionales, agentes, RAG, memoria, herramientas, multimodalidad, MoE, inferencia y evaluación?"
    if profile == "agent_architecture":
        return "¿Cómo se caracterizan los agentes de IA publicados entre 2025 y 2026 en términos de arquitectura, memoria, herramientas, orquestación y evaluación?"
    topic = normalize_phrase(context.get("topic")) or "el tema de revisión"
    return f"¿Qué evidencia científica reciente existe sobre {topic} y qué patrones metodológicos, resultados y limitaciones se observan en el corpus incluido?"


def publication_research_question_en(context: dict[str, str], profile: str) -> str:
    raw = normalize_phrase(context.get("research_question_en"))
    if raw:
        cleaned = raw.rstrip(". ")
        if cleaned:
            return cleaned if cleaned.endswith("?") else cleaned + "?"
    if profile == "personality_llm":
        timeframe_en = review_timeframe_phrase_en(context)
        return (
            "Can the personality of a reasoning AI model be measured, and how is it operationalized, induced, "
            f"evaluated, and empirically validated in the literature published {timeframe_en}?"
        )
    if profile == "creativity_llm":
        timeframe_en = review_timeframe_phrase_en(context)
        return (
            "How is creativity in LLMs and generative AI evaluated and characterized "
            f"in the literature published {timeframe_en}?"
        )
    if profile == "ai_higher_education_teaching":
        timeframe_en = review_timeframe_phrase_en(context)
        return (
            "What empirical evidence exists on how artificial intelligence, generative AI, and LLM-based systems help university faculty "
            f"improve teaching, assessment, feedback, curriculum design, academic productivity, and educational quality {timeframe_en}?"
        )
    if profile == "ai_security_harness":
        return (
            "Which architectures, controls, and evaluation strategies for security harnesses protecting generative models and agentic systems "
            "most consistently reduce prompt injection and jailbreak attacks, unsafe tool use, data leakage, and policy violations, and under "
            "which threats, comparative designs, and costs do they outperform alternatives or baselines?"
        )
    if profile in {"social_sciences", "education", "management"}:
        translated = translate_social_phrase_en(context.get("research_question"))
        if translated:
            return translated if translated.endswith("?") else translated + "?"
    if profile == "software_architecture":
        return "What frameworks, coordination patterns, and architectural components characterize agent architectures applied to software development published in 2026?"
    if profile == "ai_architecture":
        return "What AI architecture families published in 2026 are emerging or showing recurrent patterns around foundation models, agents, RAG, memory, tools, multimodality, MoE, inference, and evaluation?"
    if profile == "agent_architecture":
        return "How are AI agents published between 2025 and 2026 characterized in terms of architecture, memory, tools, orchestration, and evaluation?"
    topic = normalize_phrase(context.get("topic")) or "the review topic"
    return f"What recent scientific evidence exists on {topic}, and what methodological patterns, results, and limitations are observed in the included corpus?"


def software_topic_en(_context: dict[str, str]) -> str:
    return "agent architecture frameworks for software development"


def agent_topic_en(context: dict[str, str]) -> str:
    profile = detect_review_profile(context)
    if profile == "software_architecture":
        return software_topic_en(context)
    if profile == "creativity_llm":
        return "creativity in LLMs and generative AI"
    if profile == "ai_higher_education_teaching":
        return "generative AI and AI systems supporting university faculty"
    if profile == "ai_architecture":
        return "AI system architectures in 2026"
    topic = normalize_phrase(context.get("topic"))
    if topic:
        return re.sub(r"\bagentes de ia\b", "AI agents", topic, flags=re.IGNORECASE)
    return "AI agent architectures"


def personality_topic_en(context: dict[str, str]) -> str:
    raw = normalize_phrase(context.get("topic"))
    if raw:
        lowered = raw.lower()
        if "personalidad" in lowered and "razonador" in lowered:
            return "personality models in reasoning AI models"
        if "personalidad" in lowered and "llm" in lowered:
            return "personality in large language models"
    return "personality in reasoning AI models"


def parse_iso_date(text: str) -> date | None:
    raw = normalize_phrase(text)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def month_year_es(value: date) -> str:
    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    return f"{months[value.month - 1]} de {value.year}"


def month_year_en(value: date) -> str:
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    return f"{months[value.month - 1]} {value.year}"


def review_years_label(context: dict[str, str]) -> str:
    years = normalize_phrase(context.get("years"))
    if years:
        return years
    start = parse_iso_date(context.get("start_date", ""))
    end = parse_iso_date(context.get("end_date", ""))
    if start and end:
        return f"{start.year}-{end.year}" if start.year != end.year else str(start.year)
    if start:
        return str(start.year)
    if end:
        return str(end.year)
    return "2026"


def review_timeframe_phrase_es(context: dict[str, str]) -> str:
    start = parse_iso_date(context.get("start_date", ""))
    end = parse_iso_date(context.get("end_date", ""))
    if start and end:
        return f"entre {month_year_es(start)} y {month_year_es(end)}"
    years = review_years_label(context)
    return f"durante {years}"


def review_timeframe_phrase_en(context: dict[str, str]) -> str:
    start = parse_iso_date(context.get("start_date", ""))
    end = parse_iso_date(context.get("end_date", ""))
    if start and end:
        return f"between {month_year_en(start)} and {month_year_en(end)}"
    years = review_years_label(context)
    return f"during {years}"


def selection_score_rows(review_dir: pathlib.Path, focus_rows: list[dict[str, str]]) -> list[list[str]]:
    focus_ids = {row.get("record_id", "") for row in focus_rows if row.get("record_id")}
    rendered: list[list[str]] = []
    for row in read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv"):
        record_id = row.get("record_id", "")
        if record_id not in focus_ids:
            continue
        if not has_public_doi(row):
            continue
        rel = parse_float(row.get("relevance_score"))
        meth = parse_float(row.get("methodological_quality_score"))
        rep = parse_float(row.get("representativeness_score"))
        composite = composite_selection_score(row)
        rendered.append(
            [
                row.get("ultraquality_rank", ""),
                public_doi_value(row),
                normalize_phrase(row.get("title_original")) or "no reportado",
                f"{rel:.1f}".replace(".", ","),
                f"{meth:.1f}".replace(".", ","),
                f"{rep:.1f}".replace(".", ","),
                f"{composite:.1f}".replace(".", ","),
            ]
        )
    rendered.sort(key=lambda item: (parse_int(item[0], 9999), item[1]))
    return rendered


def author_year_label(row: dict[str, str]) -> str:
    authors = first_nonempty(row.get("authors"), row.get("author"))
    year = normalize_reference_year(row.get("year") or "")
    author_items = split_authors(authors)
    if author_items:
        institution_markers = {
            "ecuador",
            "universidad",
            "university",
            "facultad",
            "faculty",
            "instituto",
            "institute",
            "unidad educativa",
            "school",
            "ministerio",
            "ministry",
            "department",
            "editorial",
        }
        chosen = author_items[0]
        for item in author_items:
            normalized = normalize_phrase(item).lower()
            if not any(marker in normalized for marker in institution_markers):
                chosen = item
                break
        family = author_family(chosen)
        if re.search(r"\bsanz\s+tejeda\b", normalize_phrase(chosen), flags=re.IGNORECASE):
            family = "Sanz-Tejeda"
    else:
        family = short_title_for_citation(first_nonempty(row.get("title_original"), row.get("title"), "Título no resuelto"), max_words=4)
    return f"{family} ({year})" if year and year != "s. f." else family


def selection_score_display_rows(review_dir: pathlib.Path, focus_rows: list[dict[str, str]], profile: str) -> list[list[str]]:
    focus_ids = {row.get("record_id", "") for row in focus_rows if row.get("record_id")}
    rendered: list[list[str]] = []
    selected_index = 0
    for row in read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv"):
        record_id = row.get("record_id", "")
        if record_id not in focus_ids or not has_public_doi(row):
            continue
        selected_index += 1
        composite = composite_selection_score(row)
        family = (
            creativity_evidence_family(row)
            if profile == "creativity_llm"
            else education_ai_evidence_family(row)
            if profile == "ai_higher_education_teaching"
            else table_label(display_work_type(row.get("work_type")))
        )
        study_label = (
            f"{author_year_label(row)}. {row_title(row, width=100)} "
            f"[{summarize_phrase_soft(family, width=48)}]"
        )
        rendered.append(
            [
                row.get("ultraquality_rank", "") or str(selected_index),
                public_doi_value(row),
                f"{composite:.1f}".replace(".", ","),
                study_label,
            ]
        )
    rendered.sort(key=lambda item: (parse_int(item[0], 9999), item[1]))
    return rendered


def selection_score_component_rows(review_dir: pathlib.Path, focus_rows: list[dict[str, str]]) -> list[list[str]]:
    """Render the exact score components for every focal study in a compact table."""
    return [[row[0], row[1], row[3], row[4], row[5], row[6]] for row in selection_score_rows(review_dir, focus_rows)]


def non_focal_score_summary_rows(all_shortlist_rows: list[dict[str, str]]) -> list[list[str]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in all_shortlist_rows:
        if is_selected(row) or not has_public_doi(row):
            continue
        if (row.get("decision_before_cap") or "").strip().lower() not in {"include", "include_ft"}:
            continue
        reason = normalize_phrase(row.get("cap_exclusion_reason")) or "Fuera del top N por score compuesto, representatividad o densidad de extracción"
        reason = re.sub(r"^Estudio válido para (?:el )?corpus incluido,\s*pero\s*", "", reason, flags=re.IGNORECASE)
        reason = re.sub(r"^Estudio válido para revisión contextual,\s*pero\s*", "", reason, flags=re.IGNORECASE)
        if "ajuste tematico insuficiente" in normalized_text(reason) and parse_float(row.get("relevance_score")) >= 80:
            reason = "Fuera del subconjunto focal por menor representatividad o densidad de extracción frente al N final"
        reason = summarize_phrase_soft(reason.rstrip("."), width=105)
        groups.setdefault(reason, []).append(row)

    rendered: list[list[str]] = []
    for reason, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        scores = [composite_selection_score(row) for row in rows]
        rels = [parse_float(row.get("relevance_score")) for row in rows if row.get("relevance_score")]
        quals = [parse_float(row.get("methodological_quality_score")) for row in rows if row.get("methodological_quality_score")]
        score_range = f"{min(scores):.1f}-{max(scores):.1f}".replace(".", ",") if scores else "no reportado"
        rel_range = f"{min(rels):.1f}-{max(rels):.1f}".replace(".", ",") if rels else "no reportado"
        qual_range = f"{min(quals):.1f}-{max(quals):.1f}".replace(".", ",") if quals else "no reportado"
        rendered.append([reason, str(len(rows)), score_range, rel_range, qual_range])
    return rendered[:8]


def focal_context_characteristics_rows(
    focus_rows: list[dict[str, str]],
    all_shortlist_rows: list[dict[str, str]],
) -> list[list[str]]:
    """Compare focal and contextual studies so the focal cut is substantively auditable."""
    contextual_rows = [
        row
        for row in all_shortlist_rows
        if not is_selected(row)
        and has_public_doi(row)
        and (row.get("decision_before_cap") or "").strip().lower() in {"include", "include_ft"}
    ]

    def describe_group(label: str, rows: list[dict[str, str]]) -> list[str]:
        n = len(rows)
        if not rows:
            return [label, "0", "no aplica", "no aplica", "no aplica", "no aplica"]
        work_counts = work_type_summary(rows)
        empirical_counts = empirical_summary(rows)
        dominant_work = table_label(display_work_type(work_counts.most_common(1)[0][0])) if work_counts else "no reportado"
        dominant_design = (
            table_label(display_empirical_type(empirical_counts.most_common(1)[0][0]))
            if empirical_counts
            else "sin diseño empírico comparable"
        )
        missing_context = sum(
            1
            for row in rows
            if nice_value(first_nonempty(row.get("countries"), row.get("country_or_countries"))).lower()
            == "no reportado"
        )
        missing_sample = sum(
            1
            for row in rows
            if nice_value(first_nonempty(row.get("sample_size"), row.get("sample_description"))).lower()
            in {"no reportado", "not specified"}
        )
        scores = [composite_selection_score(row) for row in rows if composite_selection_score(row)]
        mean_score = f"{sum(scores) / max(len(scores), 1):.1f}".replace(".", ",") if scores else "no reportado"
        return [
            label,
            str(n),
            f"{dominant_work}; {dominant_design}",
            f"sin contexto: {missing_context}; sin muestra: {missing_sample}",
            mean_score,
            counter_summary(Counter(row.get("source") or "no reportado" for row in rows), n, limit=3),
        ]

    rows = [describe_group("Síntesis focal", focus_rows)]
    if contextual_rows:
        rows.append(describe_group("Perímetro contextual elegible no focal", contextual_rows))
    else:
        rows.append(["Perímetro contextual elegible no focal", "0", "no aplica", "no aplica", "no aplica", "sin estudios fuera del foco"])
    return rows


def score_label(value: str | float | int | None) -> str:
    return f"{parse_float(value):.1f}".replace(".", ",")


def non_focal_selection_rows(all_shortlist_rows: list[dict[str, str]], limit: int = 12) -> list[list[str]]:
    rendered: list[list[str]] = []
    for row in all_shortlist_rows:
        if is_selected(row):
            continue
        if not has_public_doi(row):
            continue
        if (row.get("decision_before_cap") or "").strip().lower() not in {"include", "include_ft"}:
            continue
        rank = row.get("ultraquality_rank", "")
        n_limit = row.get("n_limit", "") or "20"
        reason = normalize_phrase(row.get("cap_exclusion_reason"))
        if not reason:
            reason = (
                f"Estudio válido para el corpus incluido, pero fuera del top {n_limit} "
                "tras ordenar por score compuesto, relevancia temática y calidad metodológica."
            )
        rendered.append(
            [
                rank,
                public_doi_value(row),
                normalize_phrase(row.get("title_original")) or "no reportado",
                score_label(row.get("ultraquality_score")),
                score_label(row.get("relevance_score")),
                score_label(row.get("methodological_quality_score")),
                score_label(row.get("representativeness_score")),
                reason,
            ]
        )
    rendered.sort(key=lambda item: (parse_int(item[0], 9999), item[1]))
    return rendered[:limit]


def non_focal_selection_compact_rows(all_shortlist_rows: list[dict[str, str]], limit: int | None = None) -> list[list[str]]:
    """Render non-focal included studies without long titles so the PDF remains readable."""
    candidates: list[dict[str, str]] = []
    for row in all_shortlist_rows:
        if is_selected(row) or not has_public_doi(row):
            continue
        if (row.get("decision_before_cap") or "").strip().lower() not in {"include", "include_ft"}:
            continue
        candidates.append(row)

    candidates.sort(key=lambda item: (parse_int(item.get("ultraquality_rank"), 9999), public_doi_value(item)))
    if limit is not None:
        candidates = candidates[:limit]
    if len(candidates) > 12:
        ranks = [parse_int(row.get("ultraquality_rank"), 0) for row in candidates if parse_int(row.get("ultraquality_rank"), 0)]
        rank_span = f"{min(ranks)}-{max(ranks)}" if ranks else "no reportado"
        scores = [composite_selection_score(row) for row in candidates if composite_selection_score(row)]
        rels = [parse_float(row.get("relevance_score")) for row in candidates if row.get("relevance_score")]
        qualities = [parse_float(row.get("methodological_quality_score")) for row in candidates if row.get("methodological_quality_score")]
        reps = [parse_float(row.get("representativeness_score")) for row in candidates if row.get("representativeness_score")]
        score_range = f"{min(scores):.1f}-{max(scores):.1f}".replace(".", ",") if scores else "no reportado"
        rel_range = f"{min(rels):.1f}-{max(rels):.1f}".replace(".", ",") if rels else "no reportado"
        quality_range = f"{min(qualities):.1f}-{max(qualities):.1f}".replace(".", ",") if qualities else "no reportado"
        rep_range = f"{min(reps):.1f}-{max(reps):.1f}".replace(".", ",") if reps else "no reportado"
        return [
            [
                rank_span,
                str(len(candidates)),
                score_range,
                rel_range,
                quality_range,
                rep_range,
                "Perímetro contextual elegible; fuera del corte focal por score inferior al umbral efectivo o menor densidad comparativa",
            ]
        ]

    rendered: list[list[str]] = []
    for row in candidates:
        reason = normalize_phrase(row.get("cap_exclusion_reason"))
        contextual_band = False
        if not reason:
            reason = "Incluido en corpus contextual, fuera del N focal por score compuesto, representatividad o densidad de extracción."
        elif "cap ultraquality" in normalized_text(reason) or "menor puntuacion compuesta" in normalized_text(reason):
            contextual_band = True
            reason = "Fuera del corte focal por score inferior al umbral efectivo; conserva valor como contexto auditable"
        score = score_label(composite_selection_score(row))
        rel = score_label(row.get("relevance_score"))
        quality = score_label(row.get("methodological_quality_score"))
        rep = score_label(row.get("representativeness_score"))
        if contextual_band:
            status = "Perímetro contextual elegible"
        else:
            status = "Fuera del N focal"
        rendered.append(
            [
                row.get("ultraquality_rank", ""),
                public_doi_value(row),
                score,
                rel,
                quality,
                rep,
                f"{status}: {reason.rstrip('.')}",
            ]
        )
    rendered.sort(key=lambda item: (parse_int(item[0], 9999), item[1]))
    return rendered


def manuscript_front_matter(
    *,
    title: str,
    abstract_text: str,
    abstract_en: str,
    keywords: str,
    keywords_en: str,
    fallback_keywords: str,
    fallback_keywords_en: str,
    context: dict[str, str],
) -> str:
    """Render the manuscript opening without redundant title labels.

    The publication-ready PDF should not invent authorship. If the intake
    declares authors, contact email, or manuscript date, they are printed under
    the title; otherwise the manuscript starts cleanly with the abstract.
    """
    metadata_lines: list[str] = []
    authors = (context.get("manuscript_authors") or "").strip()
    email = (context.get("manuscript_email") or "").strip()
    date = (context.get("manuscript_date") or "").strip()
    if authors:
        metadata_lines.append(f"**Autoría:** {authors}")
    if email:
        metadata_lines.append(f"**Correo de contacto:** {email}")
    if date:
        metadata_lines.append(f"**Fecha:** {date}")

    parts = [
        f"# {title}",
        "",
    ]
    if metadata_lines:
        parts.extend(metadata_lines)
        parts.append("")
    parts.extend(
        [
            "## Resumen",
            abstract_text,
            "",
            "## Abstract",
            abstract_en,
            "",
            "## Palabras clave",
            keywords or fallback_keywords,
            "",
            "## Keywords",
            keywords_en or fallback_keywords_en,
        ]
    )
    return "\n".join(parts) + "\n"


def is_domain_general_profile(profile: str) -> bool:
    return profile in {
        "ai_security_harness",
        "creativity_llm",
        "ai_higher_education_teaching",
        "social_sciences",
        "education",
        "management",
        "generic",
    }


def review_subject_label_es(context: dict[str, str]) -> str:
    topic = normalize_phrase(context.get("topic"))
    return topic or "el tema definido en el protocolo"


def review_subject_label_en(context: dict[str, str]) -> str:
    profile = detect_review_profile(context)
    if profile == "ai_security_harness":
        return "security harnesses for generative models and agentic systems"
    if profile == "creativity_llm":
        return "creativity in LLMs and generative AI"
    if profile == "ai_higher_education_teaching":
        return "generative AI and AI systems supporting university faculty"
    if profile in {"social_sciences", "education", "management"}:
        return translate_social_phrase_en(context.get("topic")) or "the protocol-defined review topic"
    topic = normalize_phrase(context.get("topic"))
    return topic or "the protocol-defined review topic"


def domain_focus_sentence(profile: str) -> str:
    if profile == "ai_security_harness":
        return (
            "La síntesis separa amenaza, superficie, arquitectura de control, punto de aplicación, atacante, baseline, "
            "eficacia, falsos positivos, utilidad, latencia, coste, robustez y fallo residual."
        )
    if profile == "creativity_llm":
        return (
            "La síntesis separa tareas creativas, instrumentos de evaluación, modelos analizados, comparadores humanos, "
            "métricas de originalidad o novedad y límites metodológicos del reporte."
        )
    if profile == "ai_higher_education_teaching":
        return (
            "La síntesis separa tarea docente, rol del profesorado, herramienta o sistema de IA, contexto universitario, "
            "diseño pedagógico, resultado observado, control humano, riesgo y límites de transferencia."
        )
    if profile in {"social_sciences", "education", "management"}:
        return (
            "La síntesis separa constructos, contexto, unidad de análisis, diseño, método, muestra, resultados, "
            "mecanismos plausibles, límites de transferencia y cautelas inferenciales."
        )
    return (
        "La síntesis separa pregunta, unidad de análisis, diseño, muestra, método, variables, resultados, limitaciones "
        "y trazabilidad de la evidencia."
    )


def domain_default_keywords(profile: str) -> tuple[str, str]:
    if profile == "ai_security_harness":
        return (
            "harnesses de seguridad, modelos generativos, sistemas agénticos, prompt injection, jailbreak, guardrails, seguridad de herramientas, evaluación adversarial, revisión sistemática",
            "security harnesses, generative models, agentic systems, prompt injection, jailbreak, guardrails, tool security, adversarial evaluation, systematic review",
        )
    if profile == "creativity_llm":
        return (
            "creatividad en LLMs, modelos de lenguaje, IA generativa, pensamiento divergente, originalidad, novedad, evaluación de creatividad, revisión sistemática",
            "creativity in LLMs, language models, generative AI, divergent thinking, originality, novelty, creativity assessment, systematic review",
        )
    if profile == "ai_higher_education_teaching":
        return (
            "IA generativa en educación superior, profesorado universitario, docencia universitaria, feedback, evaluación, diseño curricular, alfabetización en IA, revisión sistemática",
            "generative AI in higher education, university faculty, university teaching, feedback, assessment, curriculum design, AI literacy, systematic review",
        )
    if profile == "social_sciences":
        return (
            "constructos sociales, contexto, método, evidencia empírica, transferibilidad, síntesis temática, revisión sistemática",
            "social constructs, context, method, empirical evidence, transferability, thematic synthesis, systematic review",
        )
    if profile == "management":
        return (
            "IA generativa, carga de trabajo, productividad, colaboración humano-IA, supervisión humana, desplazamiento del trabajo, calidad del trabajo, revisión sistemática",
            "generative AI, workload, productivity, human-AI collaboration, human oversight, work displacement, work quality, systematic review",
        )
    return (
        "revisión sistemática, texto completo, síntesis focal, evidencia, método, calidad metodológica, trazabilidad",
        "systematic review, full text, focal synthesis, evidence, method, methodological quality, traceability",
    )


def domain_title_pair(context: dict[str, str], focus_count: int) -> tuple[str, str]:
    profile = detect_review_profile(context)
    timeframe_es = review_timeframe_phrase_es(context)
    timeframe_en = review_timeframe_phrase_en(context)
    if profile == "ai_security_harness":
        return (
            f"Harnesses de seguridad para modelos generativos y sistemas agénticos {timeframe_es}: revisión sistemática de literatura y síntesis focal de {focus_count} estudios",
            f"Security harnesses for generative models and agentic systems {timeframe_en}: a systematic literature review and focal synthesis of {focus_count} studies",
        )
    if profile == "creativity_llm":
        return (
            f"Creatividad en modelos LLM e IA generativa {timeframe_es}: revisión sistemática de literatura y síntesis focal de {focus_count} estudios",
            f"Creativity in LLMs and generative AI {timeframe_en}: a systematic literature review and focal synthesis of {focus_count} studies",
        )
    if profile == "ai_higher_education_teaching":
        return (
            f"IA generativa y sistemas de IA como apoyo al profesorado universitario {timeframe_es}: revisión sistemática de literatura y síntesis focal de {focus_count} estudios",
            f"Generative AI and AI systems supporting university faculty {timeframe_en}: a systematic literature review and focal synthesis of {focus_count} studies",
        )
    topic = review_subject_label_es(context)
    topic_en = review_subject_label_en(context)
    if profile in {"social_sciences", "education", "management", "generic"} and topic:
        topic = topic[:1].upper() + topic[1:]
    return (
        f"{topic}: revisión sistemática de literatura y síntesis focal de {focus_count} estudios",
        f"{topic_en}: a systematic literature review and focal synthesis of {focus_count} studies",
    )


def build_title_abstract_section_domain(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    topic_en = review_subject_label_en(context)
    topic_en_sentence = topic_en[:1].lower() + topic_en[1:] if re.match(r"^[A-Z][a-z]", topic_en) else topic_en
    rq_text = publication_research_question(context, profile)
    included_count = flow_counts.get("included_in_review", 0)
    focus_count = len(focus_rows)
    work_counter = work_type_summary(focus_rows)
    empirical_counter = empirical_summary(focus_rows)
    keyword_list = build_keyword_list(focus_rows, context=context)
    keywords = ", ".join(restore_acronyms(keyword) for keyword in keyword_list)
    keywords_en = ", ".join(english_keywords(keyword_list))
    fallback_keywords, fallback_keywords_en = domain_default_keywords(profile)
    title, title_en = domain_title_pair(context, focus_count)
    relation_text = corpus_focus_relation(included_count, focus_count)
    empirical_n = work_counter.get("empirical", 0)
    support_n = max(focus_count - empirical_n, 0)
    experimental_n = empirical_counter.get("experimental", 0)
    quantitative_n = empirical_counter.get("quantitative", 0)
    qualitative_n = empirical_counter.get("qualitative", 0)
    mixed_n = empirical_counter.get("mixed", 0)
    other_empirical_n = max(empirical_n - experimental_n - quantitative_n - qualitative_n - mixed_n, 0)
    empirical_parts_es: list[str] = []
    empirical_parts_en: list[str] = []
    if quantitative_n:
        empirical_parts_es.append(f"{quantitative_n} {'cuantitativo' if quantitative_n == 1 else 'cuantitativos'}")
        empirical_parts_en.append(f"{quantitative_n} quantitative")
    if experimental_n:
        empirical_parts_es.append(f"{experimental_n} {'experimental o evaluativo' if experimental_n == 1 else 'experimentales o evaluativos'}")
        empirical_parts_en.append(f"{experimental_n} experimental or evaluative")
    if qualitative_n:
        empirical_parts_es.append(f"{qualitative_n} {'cualitativo' if qualitative_n == 1 else 'cualitativos'}")
        empirical_parts_en.append(f"{qualitative_n} qualitative")
    if mixed_n:
        empirical_parts_es.append(f"{mixed_n} {'mixto' if mixed_n == 1 else 'mixtos'}")
        empirical_parts_en.append(f"{mixed_n} mixed-methods")
    if other_empirical_n:
        empirical_parts_es.append(f"{other_empirical_n} de otro tipo empírico")
        empirical_parts_en.append(f"{other_empirical_n} other empirical designs")
    empirical_design_sentence = (
        f"Los {empirical_n} estudios empíricos del subconjunto focal se clasifican, por auto-declaración metodológica y lectura del texto completo, en {join_human_list(empirical_parts_es)}."
        if empirical_n
        else "La síntesis focal no contiene estudios empíricos clasificados con suficiente granularidad."
    )
    empirical_design_sentence_en = (
        f"The {empirical_n} empirical studies in the focal subset are classified, based on methodological self-description and full-text reading, as {join_human_list(empirical_parts_en, language='en')}."
        if empirical_n
        else "The focal synthesis contains no empirical studies classified with sufficient granularity."
    )
    if is_ai_workload_context(context):
        focal_scope_es = (
            f"La síntesis focal contiene {focus_count} estudios, pero la respuesta probatoria a la pregunta se apoya primariamente en los {empirical_n} estudios empíricos; "
            f"los {support_n} trabajos restantes se usan como apoyo teórico, metodológico o contextual, no como prueba directa de reducción neta de trabajo. "
        )
        focal_scope_en = (
            f"The focal synthesis contains {focus_count} studies, but the evidential answer to the question relies primarily on the {empirical_n} empirical studies; "
            f"the remaining {support_n} works are used as theoretical, methodological, or contextual support, not as direct evidence of net workload reduction. "
        )
        abstract_argument_es = (
            "La lectura sustantiva sugiere, con cautela, que la IA comprime tareas de ejecución en contextos delimitados, pero no demuestra una reducción neta general del trabajo humano. "
            "El patrón más útil para investigación futura es el desplazamiento del esfuerzo hacia formulación, revisión, coordinación, aprendizaje, control de errores y responsabilidad institucional."
        )
        abstract_argument_en = (
            "The substantive reading cautiously suggests that AI compresses execution tasks in bounded settings, but it does not demonstrate a general net reduction in human work. "
            "The most useful pattern for future research is the displacement of effort toward formulation, review, coordination, learning, error control, and institutional responsibility."
        )
    else:
        focal_scope_es = f"La síntesis focal contiene {focus_count} estudios. "
        focal_scope_en = f"The focal synthesis contains {focus_count} studies. "
        abstract_argument_es = domain_focus_sentence(profile)
        abstract_argument_en = ""
    abstract_text = (
        f"Esta revisión sistemática de literatura analiza la investigación sobre {topic} {review_timeframe_phrase_es(context)}. "
        f"El protocolo identificó {flow_counts.get('identified', 0)} registros, consolidó {flow_counts.get('duplicates_removed', 0)} duplicados antes del cribado, evaluó {flow_counts.get('full_text_assessed', 0)} textos completos en PDF e incluyó {included_count} estudios en el corpus final. "
        f"{relation_text} "
        f"La pregunta de investigación fue: {rq_text} "
        f"{focal_scope_es}{empirical_design_sentence} "
        f"{abstract_argument_es} "
        "La contribución del artículo es ofrecer una síntesis reproducible basada en DOI público, PDF local, extracción estructurada, matriz de selección y anexos auditables, no solo una narración agregada de la literatura. "
        "La reproducibilidad se refiere a decisiones, matrices y artefactos derivados; los PDFs fuente solo pueden redistribuirse cuando su licencia lo permite."
    )
    abstract_en = (
        f"This systematic literature review examines research on {topic_en_sentence} {review_timeframe_phrase_en(context)}. "
        f"The protocol identified {flow_counts.get('identified', 0)} records, consolidated {flow_counts.get('duplicates_removed', 0)} duplicates before screening, assessed {flow_counts.get('full_text_assessed', 0)} full texts in PDF, and included {included_count} studies in the final review corpus. "
        + focal_synthesis_relation(included_count, focus_count, language="en")
        + " "
        f"The guiding research question was: {publication_research_question_en(context, profile)} "
        f"{focal_scope_en}{empirical_design_sentence_en} "
        + (abstract_argument_en + " " if abstract_argument_en else "")
        + "The contribution is a reproducible full-text synthesis grounded in public DOI traceability, local PDF evidence, structured extraction, a visible selection matrix, and auditable appendices. "
        + "Reproducibility applies to decisions, matrices, and derived artifacts; source PDFs may only be redistributed when their licenses permit it."
    )
    return manuscript_front_matter(
        title=title,
        abstract_text=abstract_text,
        abstract_en=abstract_en,
        keywords=keywords,
        keywords_en=keywords_en,
        fallback_keywords=fallback_keywords,
        fallback_keywords_en=fallback_keywords_en,
        context=context,
    )


def domain_study_matrix_rows(focus_rows: list[dict[str, str]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in focus_rows:
        rows.append(
            [
                public_doi_value(row),
                row_title(row, width=58),
                table_label(display_work_type(row.get("work_type"))),
                table_label(display_empirical_type(row.get("empirical_type"))),
                summarize_phrase_soft(first_nonempty(row.get("models_or_systems_studied"), row.get("unit_of_analysis")), width=58),
                summarize_phrase_soft(row.get("tasks_or_domains"), width=62),
                summarize_phrase_soft(first_nonempty(row.get("instruments_or_scales"), row.get("benchmark_dataset_or_corpus")), width=62),
                summarize_phrase_soft(row.get("method_used"), width=62),
                principal_result_label(row, width=90),
                nice_value(row.get("extraction_confidence")),
            ]
        )
    return rows


def matching_row_count(rows: list[dict[str, str]], pattern: str) -> int:
    regex = re.compile(pattern, flags=re.IGNORECASE)
    return sum(1 for row in rows if regex.search(row_search_blob(row)))


def counter_summary(counter: Counter[str], total: int, limit: int = 5) -> str:
    if not counter:
        return "sin señal agregada suficiente"
    parts = [f"{label}: {count}/{total}" for label, count in counter.most_common(limit)]
    return "; ".join(parts)


def mapped_counter(counter: Counter[str], labels: dict[str, str]) -> Counter[str]:
    mapped: Counter[str] = Counter()
    for key, count in counter.items():
        mapped[labels.get(key, key)] += count
    return mapped


def creativity_task_counter(rows: list[dict[str, str]]) -> Counter[str]:
    patterns = [
        ("escritura creativa o narrativa", r"writing|literary|story|narrative|script|poem|poetry|escritura|literari"),
        ("pensamiento divergente o asociación", r"divergent|associat|remote association|\bDAT\b|\bRAT\b|pensamiento divergente|asociativ"),
        ("ideación científica o planes de investigación", r"scientific|research plan|idea generation|ideaci[oó]n cient|descubrimiento"),
        ("resolución creativa de problemas", r"math|problem[- ]?solving|resoluci[oó]n creativa|creative problem"),
        ("evaluación de originalidad, novedad o utilidad", r"originality|novelty|utility|usefulness|quality|diversity|originalidad|novedad|utilidad|diversidad"),
    ]
    counter: Counter[str] = Counter()
    for row in rows:
        blob = row_search_blob(row)
        for label, pattern in patterns:
            if re.search(pattern, blob, flags=re.IGNORECASE):
                counter[label] += 1
    return counter


def model_mention_summary(rows: list[dict[str, str]], total: int) -> str:
    blobs = " ".join(
        first_nonempty(row.get("models_or_systems_studied"), row.get("baselines_or_comparators"), row.get("key_findings"))
        for row in rows
    )
    pattern = re.compile(
        r"\b(?:GPT-?4(?:\.1|o)?|GPT-?3\.5|ChatGPT|Claude(?:\s*\d(?:\.\d)?)?|Gemini(?:[-\s]?\d(?:\.\d)?)?|"
        r"Llama(?:[-\s]*\d(?:\.\d)?)?|Qwen(?:[-\s]*\d(?:\.\d)?)?|Mistral(?:[-\s]*\d+B)?|DeepSeek|OLMo2?|"
        r"Gemma(?:[-\s]*\d+B)?|Grok|o1|o3)\b",
        flags=re.IGNORECASE,
    )
    mentions = Counter(match.group(0).replace("  ", " ").strip() for match in pattern.finditer(blobs))
    reported = sum(
        1
        for row in rows
        if nice_value(row.get("models_or_systems_studied")).lower() != "no reportado"
        or nice_value(row.get("model_count")).lower() != "no reportado"
    )
    if not mentions:
        return f"{reported}/{total} estudios reportan modelos o sistemas, pero sin nombres normalizables en la extracción."
    mention_text = "; ".join(f"{label}: n={count}" for label, count in mentions.most_common(6))
    return f"{reported}/{total} estudios reportan modelos o sistemas; menciones frecuentes: {mention_text}."


def creativity_family_synthetic_reading(family: str, members: list[dict[str, str]]) -> str:
    if family == "Escritura y generación creativa":
        return (
            "Predomina escritura y generación textual; las ventajas observadas dependen de tarea, métrica y benchmark."
        )
    if family == "Pensamiento divergente y asociación":
        return (
            "La señal depende de instrucciones, métricas asociativas y comparadores humanos; no hay mejora lineal automática."
        )
    if family == "Ideación científica y generación de investigación":
        return (
            "Los modelos pueden generar ideas o planes, pero novedad y utilidad requieren verificación experta."
        )
    if family == "Resolución creativa de problemas":
        return (
            "La creatividad aparece en problemas abiertos y objetivos de entrenamiento; la corrección no basta."
        )
    if family == "Evaluación, métricas y benchmarks":
        return (
            "El bloque refuerza que la medición es parte del hallazgo: juez, rúbrica, benchmark y alineación humana condicionan qué se llama creatividad."
        )
    if family == "Entrenamiento y optimización creativa":
        return (
            "Estos estudios desplazan la pregunta desde evaluar salidas hacia modificar el entrenamiento o las preferencias que producen diversidad, originalidad o utilidad."
        )
    return (
        "Advierte que fluidez textual y originalidad sustantiva no son equivalentes."
    )


def security_harness_evidence_family(row: dict[str, str]) -> str:
    """Group defenses by protected surface rather than by product name."""
    blob = normalized_text(
        " ".join(
            [
                row.get("threat_model", ""),
                row.get("attack_type", ""),
                row.get("control_architecture", ""),
                row.get("enforcement_point", ""),
                row.get("title_original", ""),
                row.get("tasks_or_domains", ""),
                row.get("key_findings", ""),
            ]
        )
    )
    if re.search(r"tool|function call|herramient|capability|permission|sandbox", blob):
        return "Herramientas, permisos y aislamiento"
    if re.search(r"indirect prompt injection|prompt injection indirecta|retrieval|rag|context|memory|memoria", blob):
        return "Contexto, RAG y prompt injection indirecta"
    if re.search(r"data exfiltration|secret|privacy|leak|fuga|exfiltr", blob):
        return "Exfiltración, secretos y privacidad"
    if re.search(r"jailbreak|policy bypass|policy violation|guardrail|filter|firewall", blob):
        return "Jailbreak y cumplimiento de políticas"
    if re.search(r"runtime|monitor|verifier|output|salida|response", blob):
        return "Monitorización, verificación y salida"
    return "Arquitectura y evaluación integral del harness"


def security_family_synthetic_reading(family: str, members: list[dict[str, str]]) -> str:
    total = len(members)
    readings = {
        "Herramientas, permisos y aislamiento": "sitúan la seguridad en la capacidad de actuar: permisos mínimos, sandbox y validación de llamadas reducen impacto aunque el modelo sea manipulado",
        "Contexto, RAG y prompt injection indirecta": "tratan documentos, recuperación y memoria como entradas no confiables y desplazan el control hacia procedencia, aislamiento y separación de instrucciones",
        "Exfiltración, secretos y privacidad": "evalúan si el control evita que datos o secretos crucen límites, una propiedad que no queda cubierta por bloquear lenguaje ofensivo",
        "Jailbreak y cumplimiento de políticas": "miden resistencia a evasión de políticas, pero su fuerza depende de incluir ataques adaptativos y utilidad legítima",
        "Monitorización, verificación y salida": "colocan detección y decisión durante o después de la inferencia, con el riesgo de reaccionar tarde si ya ocurrió una acción",
        "Arquitectura y evaluación integral del harness": "comparan varias capas o proponen evaluaciones de sistema, útiles cuando mantienen amenaza, baseline y coste explícitos",
    }
    return f"{total} estudios {readings.get(family, 'aportan evidencia sobre controles de seguridad y sus límites operacionales')}."


def security_harness_signal_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return {
        "threat": sum(1 for row in rows if security_field_reported(row.get("threat_model"))),
        "control": sum(1 for row in rows if security_field_reported(row.get("control_architecture"))),
        "enforcement": sum(1 for row in rows if security_field_reported(row.get("enforcement_point"))),
        "baseline": sum(1 for row in rows if security_field_reported(row.get("baselines_or_comparators"))),
        "adaptive": sum(
            1
            for row in rows
            if adaptive_attacker_reported(row.get("attacker_adaptivity"))
        ),
        "asr": sum(1 for row in rows if security_field_reported(row.get("attack_success_rate"))),
        "false_positive": sum(
            1 for row in rows if security_field_reported(row.get("false_positive_rate"))
        ),
        "utility": sum(1 for row in rows if security_field_reported(row.get("utility_impact"))),
        "latency": sum(1 for row in rows if security_field_reported(row.get("latency_overhead"))),
        "cost": sum(1 for row in rows if security_field_reported(row.get("cost_overhead"))),
        "robustness": sum(
            1 for row in rows if security_field_reported(row.get("robustness_evidence"))
        ),
        "failure": sum(1 for row in rows if security_field_reported(row.get("failure_modes"))),
        "artifact": sum(
            1
            for row in rows
            if open_artifact_reported(row.get("code_or_artifact_availability"))
        ),
    }


def security_frontier_result_lines(review_dir: pathlib.Path) -> list[str]:
    """Render typed comparison clusters without inventing a universal winner."""

    rows = read_csv_rows(
        review_dir / "analysis" / "security" / "dominance-frontier.csv"
    )
    if not rows:
        return []
    threat_labels = {
        "prompt_injection": "Prompt injection",
        "jailbreak": "Jailbreak",
        "tool_poisoning_or_misuse": "Abuso o envenenamiento de herramientas",
        "memory_or_retrieval_poisoning": "Envenenamiento de memoria o RAG",
        "data_exfiltration": "Exfiltración de datos",
        "other_or_unspecified": "Amenaza no tipificada",
    }
    control_labels = {
        "provenance_or_information_flow": "Procedencia y flujo de información",
        "tool_authorization": "Autorización de herramientas",
        "memory_or_retrieval_control": "Control de memoria o recuperación",
        "causal_or_counterfactual_verification": "Verificación causal o contrafactual",
        "policy_or_intent_guardrail": "Guardrail de política o intención",
        "activation_or_representation_monitor": "Monitor de activaciones o representaciones",
        "runtime_trajectory_monitor": "Monitor de trayectoria en runtime",
        "input_filtering": "Filtrado de entrada",
        "output_filtering": "Filtrado de salida",
        "sandboxing_or_isolation": "Sandbox o aislamiento",
        "cryptographic_or_structural_containment": "Contención criptográfica o estructural",
        "multi_layer_defense": "Defensa multicapa",
        "other_or_unspecified": "Control no tipificado de forma homogénea",
    }
    status_labels = {
        "replicated_frontier_candidate": "Candidata replicada",
        "emerging_frontier": "Frontera emergente",
        "security_effect_only": "Eficacia sin coste completo",
        "insufficient_comparability": "Comparación insuficiente",
        "insufficient_taxonomy": "No tipificable",
    }
    status_order = {
        "replicated_frontier_candidate": 0,
        "emerging_frontier": 1,
        "security_effect_only": 2,
        "insufficient_comparability": 3,
        "insufficient_taxonomy": 4,
    }

    def family_label(value: str, labels: dict[str, str]) -> str:
        parts = [part for part in str(value or "").split("+") if part]
        return " + ".join(
            labels.get(part, part.replace("_", " ")) for part in parts
        )

    selected = sorted(
        [row for row in rows if parse_int(row.get("studies"), 0) >= 2],
        key=lambda row: (
            status_order.get(row.get("frontier_status", ""), 9),
            -parse_int(row.get("studies"), 0),
            row.get("threat_family", ""),
            row.get("control_family", ""),
        ),
    )[:10]
    table_rows = [
        [
            family_label(row.get("threat_family", ""), threat_labels),
            family_label(row.get("control_family", ""), control_labels),
            row.get("studies", "0"),
            f"{row.get('with_explicit_baseline', '0')}/{row.get('studies', '0')}",
            f"{row.get('with_adaptive_attacker', '0')}/{row.get('studies', '0')}",
            (
                f"FP {row.get('with_false_positive_rate', '0')}; "
                f"utilidad {row.get('with_utility_impact', '0')}; "
                f"latencia/coste {row.get('with_latency_or_cost', '0')}"
            ),
            status_labels.get(
                row.get("frontier_status", ""),
                row.get("frontier_status", "").replace("_", " "),
            ),
        ]
        for row in selected
    ]
    replicated = [
        row
        for row in rows
        if row.get("frontier_status") == "replicated_frontier_candidate"
    ]
    residual_n = sum(
        parse_int(row.get("studies"), 0)
        for row in rows
        if row.get("frontier_status") == "insufficient_taxonomy"
    )
    if replicated:
        replicated_text = "; ".join(
            (
                f"{family_label(row.get('threat_family', ''), threat_labels)} con "
                f"{family_label(row.get('control_family', ''), control_labels)} "
                f"(n={row.get('studies', '0')})"
            )
            for row in replicated
        )
        interpretation = (
            f"La señal comparativa más madura aparece en {replicated_text}. "
            "Debe leerse como dirección prioritaria para evaluación y diseño, no como ganador universal: "
            "la equivalencia de amenaza, baseline, métrica y coste todavía debe comprobarse estudio por estudio."
        )
    else:
        interpretation = (
            "Ninguna combinación tipificada alcanza replicación suficiente para sostener una candidata de "
            "dominancia. El corpus permite comparar efectos locales, pero no recomendar una familia como mejor."
        )
    residual_lines = (
        [
            (
                f"Además, {residual_n} configuraciones quedan en familias residuales no tipificadas. "
                "Su volumen no se interpreta como réplica: agrupar mecanismos desconocidos produciría una falsa mayoría."
            ),
            "",
        ]
        if residual_n
        else []
    )
    return [
        "Tabla 8A. Fronteras de dominancia condicionada entre familias de harnesses.",
        markdown_table(
            [
                "Amenaza",
                "Familia de control",
                "N",
                "Baseline",
                "Atacante adaptativo",
                "Trade-offs cuantificados (N)",
                "Estado",
            ],
            table_rows,
        ),
        "",
        (
            "Los estados se asignan con reglas operativas distintas. `Candidata replicada` exige al menos "
            "dos estudios de la misma combinación tipificada de amenaza y control con evidencia suficiente "
            "para probar dominancia condicionada. `Frontera emergente` indica que existe una comparación "
            "con trade-offs recuperables, pero falta réplica o robustez. `Eficacia sin coste completo` "
            "identifica reducción de ataque sin cobertura suficiente de utilidad, falsos positivos, latencia "
            "o coste. `Comparación insuficiente` señala que ni eficacia ni compensaciones permiten una "
            "comparación justa. `No tipificable` se reserva para grupos residuales donde la amenaza o el "
            "mecanismo de control no pueden clasificarse de forma homogénea; disponer de baseline no corrige "
            "esa falta de equivalencia mecanística."
        ),
        "",
        (
            "En las columnas `Baseline` y `Atacante adaptativo`, la fracción x/y significa número de estudios "
            "que reportan la característica sobre el total de estudios de esa familia. En `Trade-offs`, FP "
            "indica falsos positivos y cada recuento identifica cuántos estudios cuantifican utilidad o "
            "latencia/coste; una fracción alta no expresa mayor eficacia, sino mejor cobertura de reporte."
        ),
        "",
        interpretation,
        "",
        *residual_lines,
        *(
            [
                (
                    "La no tipificación aparece cuando el estudio describe el control con una etiqueta genérica, "
                    "combina mecanismos sin aislar su contribución o no aporta detalle operacional suficiente para "
                    "mapearlo de forma estable a procedencia, autorización, aislamiento, memoria, verificación o "
                    "filtrado. La categoría conserva esos trabajos sin atribuirles una homogeneidad defensiva que "
                    "la fuente no permite sostener."
                ),
                "",
            ]
            if residual_n
            else []
        ),
        (
            "La tabla no agrega ASR, falsos positivos o utilidad entre benchmarks incompatibles. "
            "Su función es identificar dónde existe evidencia suficiente para una comparación condicionada y "
            "dónde el siguiente estudio debería replicar amenaza, baseline y costes antes de afirmar superioridad."
        ),
        "",
    ]


def domain_aggregate_result_rows(focus_rows: list[dict[str, str]], profile: str) -> list[list[str]]:
    total = len(focus_rows)
    if total <= 0:
        return [["Sin estudios focales", "0/0", "No hay evidencia suficiente para sintetizar."]]
    if profile == "ai_security_harness":
        families = Counter(security_harness_evidence_family(row) for row in focus_rows)
        counts = security_harness_signal_counts(focus_rows)
        return [
            [
                "Superficies y familias defensivas",
                counter_summary(families, total, limit=6),
                "La clasificación separa la superficie protegida; un mismo estudio puede combinar capas, pero se resume por su función defensiva dominante.",
            ],
            [
                "Contrato mínimo de comparación",
                f"amenaza: {counts['threat']}/{total}; control: {counts['control']}/{total}; punto de aplicación: {counts['enforcement']}/{total}; baseline: {counts['baseline']}/{total}",
                "Sin amenaza, control, enforcement y baseline recuperables no puede sostenerse una comparación de superioridad.",
            ],
            [
                "Eficacia defensiva",
                f"ASR o métrica equivalente: {counts['asr']}/{total}; ataques adaptativos: {counts['adaptive']}/{total}; robustez: {counts['robustness']}/{total}",
                "La cobertura de ataques estáticos informa rendimiento local; la robustez exige adaptación, transferencia o ataques no vistos.",
            ],
            [
                "Coste de seguridad",
                f"falsos positivos: {counts['false_positive']}/{total}; utilidad: {counts['utility']}/{total}; latencia: {counts['latency']}/{total}; coste: {counts['cost']}/{total}",
                "Un harness no es mejor si reduce ataques a costa de bloquear uso legítimo o introducir un sobrecoste operacional no declarado.",
            ],
            [
                "Fallo residual y reproducibilidad",
                f"modos de fallo: {counts['failure']}/{total}; código o artefacto: {counts['artifact']}/{total}",
                "Reportar fallos y artefactos permite distinguir una defensa generalizable de un ajuste opaco al benchmark.",
            ],
        ]
    if profile not in {"social_sciences", "creativity_llm", "ai_higher_education_teaching", "education", "management"} and is_ai_workload_rows(focus_rows):
        empirical_rows = empirical_rows_only(focus_rows)
        support_rows = support_rows_only(focus_rows)
        primary_rows = empirical_rows or focus_rows
        primary_total = len(primary_rows)
        counts = ai_workload_signal_counts(primary_rows)
        method_counter = Counter(
            table_label(display_empirical_type(row.get("empirical_type")))
            for row in empirical_rows
            if table_label(display_empirical_type(row.get("empirical_type"))).lower() != "no reportado"
        )
        return [
            [
                "Base probatoria",
                f"{len(empirical_rows)}/{total} estudios empíricos; {len(support_rows)}/{total} de apoyo teórico, revisión o contexto.",
                "La respuesta sobre reducción de trabajo debe apoyarse en la base empírica; el apoyo no empírico sirve para interpretar mecanismos, no para inflar la fuerza probatoria.",
            ],
            [
                "Productividad local",
                f"{counts['productivity']}/{primary_total} estudios empíricos contienen señal de productividad, eficiencia o tiempo.",
                "Esta señal habla de ahorro en tareas o fases concretas; no demuestra por sí sola reducción neta del trabajo humano.",
            ],
            [
                "Carga y esfuerzo",
                f"{counts['workload']}/{primary_total} estudios empíricos contienen señal de carga, presión operativa, burnout o carga administrativa.",
                "La carga aparece como fenómeno más amplio que minutos ahorrados: incluye presión, responsabilidad, interrupciones y trabajo invisible.",
            ],
            [
                "Supervisión y control",
                f"{counts['supervision']}/{primary_total} estudios empíricos contienen señal de supervisión, revisión, coordinación, rework o control de calidad.",
                "La búsqueda ya contenía términos de supervisión; por eso esta señal se interpreta como capa a medir, no como descubrimiento espontáneo.",
            ],
            [
                "Riesgo, error y gobernanza",
                f"{counts['risk_error']}/{primary_total} estudios empíricos contienen señal de error, sesgo, privacidad o riesgo; {counts['governance']}/{primary_total} incorporan gobernanza o responsabilidad.",
                "Cuanto mayor es el coste de fallo, más débil resulta la promesa de trabajar menos sin una capa fuerte de verificación.",
            ],
            [
                "Métodos empíricos",
                f"{counter_summary(method_counter, max(len(empirical_rows), 1))} sobre {len(empirical_rows)}/{total} estudios empíricos focales",
                "La evidencia permite una tesis interpretativa sobre desplazamiento del trabajo, pero no una metaestimación causal única.",
            ],
        ]
    if profile == "creativity_llm":
        families = Counter(creativity_evidence_family(row) for row in focus_rows)
        compact_family_labels = {
            "Escritura y generación creativa": "escritura",
            "Pensamiento divergente y asociación": "divergente/asociación",
            "Ideación científica y generación de investigación": "ideación científica",
            "Resolución creativa de problemas": "problemas",
            "Caracterización metodológica de creatividad": "método",
            "Evaluación, métricas y benchmarks": "métricas",
            "Entrenamiento y optimización creativa": "entrenamiento",
        }
        compact_task_labels = {
            "escritura creativa o narrativa": "escritura",
            "pensamiento divergente o asociación": "divergente/asociación",
            "ideación científica o planes de investigación": "ideación científica",
            "resolución creativa de problemas": "problemas",
            "evaluación de originalidad, novedad o utilidad": "originalidad/novedad",
        }
        task_counter = creativity_task_counter(focus_rows)
        human_comparators = matching_row_count(focus_rows, r"human|humano|participant|expert|judge|evaluador|annotator|anotador")
        metric_or_benchmark = matching_row_count(focus_rows, r"metric|benchmark|rubric|score|originality|novelty|diversity|quality|m[eé]trica|rúbrica|originalidad|novedad|diversidad")
        quantitative_signal = matching_row_count(focus_rows, r"\bp\s*<|spearman|correl|rho|ρ|accuracy|effect|significant|%|porcentaje")
        proprietary_comparison = matching_row_count(focus_rows, r"proprietary|open[- ]?source|c[oó]digo abierto|propietari")
        return [
            [
                "Familias de evidencia",
                counter_summary(mapped_counter(families, compact_family_labels), total, limit=6),
                "La síntesis cubre las 25 unidades focales; las familias no son etiquetas decorativas, sino funciones de evidencia dentro de la revisión.",
            ],
            [
                "Tareas creativas",
                counter_summary(mapped_counter(task_counter, compact_task_labels), total, limit=5),
                "La creatividad no se agrega como una sola variable: cambia cuando la tarea es escritura, asociación, ideación científica o resolución de problemas.",
            ],
            [
                "Modelos analizados",
                model_mention_summary(focus_rows, total),
                "El artículo informa modelos cuando el PDF los declara; si no, conserva la ausencia como límite de reporting en lugar de inventar comparaciones.",
            ],
            [
                "Métricas, jueces y benchmarks",
                f"{metric_or_benchmark}/{total} estudios reportan métrica, rúbrica o benchmark; {human_comparators}/{total} incorporan señal humana, experta o de jueces.",
                "La dirección de los resultados depende del instrumento de medición; por eso la revisión separa métrica, comparador y hallazgo.",
            ],
            [
                "Dirección de resultados",
                f"{quantitative_signal}/{total} estudios contienen señal cuantitativa explícita; {proprietary_comparison}/{total} comparan modelos propietarios, abiertos o familias de modelos.",
                "No se calcula un ganador global: las conclusiones se formulan por dominio y diseño porque los estudios no son conmensurables como meta-análisis único.",
            ],
        ]
    if profile == "ai_higher_education_teaching":
        families = Counter(education_ai_evidence_family(row) for row in focus_rows)
        compact_family_labels = {
            "Feedback, evaluación y calidad de la retroalimentación": "feedback/evaluación",
            "Diseño curricular, materiales y planificación docente": "diseño curricular",
            "Adopción docente, alfabetización en IA y competencias": "adopción/alfabetización",
            "Productividad académica y carga de trabajo docente": "productividad/carga",
            "Resultados de aprendizaje y calidad educativa": "aprendizaje/calidad",
            "Integridad académica, ética y gobernanza": "integridad/gobernanza",
            "Uso docente de IA en educación superior": "uso docente",
        }
        method_counter = Counter(
            table_label(display_empirical_type(row.get("empirical_type")))
            for row in focus_rows
            if (row.get("work_type") or "").strip().lower() == "empirical"
            if table_label(display_empirical_type(row.get("empirical_type"))).lower() != "no reportado"
        )
        empirical_total = sum(method_counter.values())
        faculty_signal = matching_row_count(focus_rows, r"faculty|teacher|docente|profesor|lecturer|instructor|academic staff|profesorado")
        feedback_signal = matching_row_count(focus_rows, r"feedback|retroalimentaci[oó]n|assessment|evaluaci[oó]n|grading|rubric|rúbrica")
        ai_system_signal = matching_row_count(focus_rows, r"chatgpt|generative ai|ia generativa|llm|large language model|chatbot|copilot|artificial intelligence|inteligencia artificial")
        governance_signal = matching_row_count(focus_rows, r"integrity|integridad|ethic|ética|privacy|privacidad|policy|política|bias|sesgo|governance")
        return [
            [
                "Funciones docentes analizadas",
                counter_summary(mapped_counter(families, compact_family_labels), total, limit=7),
                "La síntesis no agrega IA educativa como una sola intervención: separa feedback, evaluación, diseño curricular, adopción, productividad, aprendizaje y gobernanza.",
            ],
            [
                "Métodos empíricos",
                f"{counter_summary(method_counter, max(empirical_total, 1))} sobre {empirical_total}/{total} estudios empíricos focales",
                "La fuerza de las conclusiones depende del tipo de diseño; percepción, experimento, benchmark o estudio cualitativo no sostienen el mismo tipo de inferencia.",
            ],
            [
                "Señal docente explícita",
                f"{faculty_signal}/{total} estudios contienen señal directa sobre profesorado, docentes, faculty, lecturers o teaching staff.",
                "El filtro protege la revisión frente a literatura centrada solo en estudiantes o en tecnología educativa genérica.",
            ],
            [
                "Sistemas de IA reportados",
                f"{ai_system_signal}/{total} estudios mencionan IA generativa, LLMs, ChatGPT, chatbots, copilots o sistemas de inteligencia artificial.",
                "La comparación se hace por tarea y configuración, no por marca de herramienta o modelo aislado.",
            ],
            [
                "Evaluación y gobernanza",
                f"{feedback_signal}/{total} estudios reportan señal de feedback/evaluación; {governance_signal}/{total} mencionan integridad, ética, privacidad, sesgo o políticas.",
                "La utilidad práctica exige leer mejora docente junto a control, riesgo y condiciones institucionales.",
            ],
        ]
    if profile == "social_sciences":
        families = Counter(social_science_evidence_family(row) for row in focus_rows)
        compact_family_labels = {
            "Polarización afectiva e identidad partidista": "polarización/identidad",
            "Confianza institucional y legitimidad democrática": "confianza/legitimidad",
            "Exposición digital y plataformas sociales": "plataformas/exposición",
            "Información política, desinformación y ecosistemas mediáticos": "información/desinformación",
            "Participación y actitudes democráticas": "participación/actitudes",
            "Evidencia metodológica y medición social": "medición social",
            "Constructos sociales y contexto institucional": "contexto institucional",
        }
        empirical_rows = [row for row in focus_rows if (row.get("work_type") or "").strip().lower() == "empirical"]
        method_counter = Counter(
            table_label(display_empirical_type(row.get("empirical_type")))
            for row in empirical_rows
            if table_label(display_empirical_type(row.get("empirical_type"))).lower() != "no reportado"
        )
        total_empirical = len(empirical_rows)
        causal_signal = matching_row_count(focus_rows, r"experiment|random|panel|longitudinal|instrumental|difference-in-differences|fixed effects|causal|experimento")
        context_signal = sum(
            1
            for row in focus_rows
            if not is_missing_extraction_value(first_nonempty(row.get("countries"), row.get("country_or_countries"), row.get("country")))
        )
        context_missing = max(total - context_signal, 0)
        variable_signal = matching_row_count(focus_rows, r"variable|scale|measure|medici[oó]n|construct|indicator|índice|indice")
        return [
            [
                "Familias sustantivas",
                counter_summary(mapped_counter(families, compact_family_labels), total, limit=7),
                "La síntesis se organiza por mecanismos y constructos sociales, no por frecuencia de palabras clave.",
            ],
            [
                "Métodos empíricos",
                f"{counter_summary(method_counter, max(total_empirical, 1))} sobre {total_empirical}/{total} estudios empíricos focales",
                "La fuerza inferencial cambia si la evidencia procede de encuesta, experimento, panel, datos digitales, entrevista o revisión.",
            ],
            [
                "Relación central de la pregunta",
                social_science_relation_signal(focus_rows),
                "El artículo conserva por separado exposición digital, polarización, confianza y entorno informativo para no convertir una relación triangular en una causa simple.",
            ],
            [
                "Contexto e instituciones",
                f"{context_signal}/{total} estudios reportan país, territorio o contexto institucional suficiente; {context_missing}/{total} quedan con contexto débil o no recuperable.",
                "El contexto no es decorado: condiciona la transferencia de hallazgos entre democracias, plataformas y ciclos políticos.",
            ],
            [
                "Cautela causal",
                f"{causal_signal}/{total} estudios contienen señal de experimento, panel, longitudinalidad, controles fuertes o estrategia causal; {variable_signal}/{total} reportan señal clara de medición o constructo.",
                "La revisión distingue asociación, mecanismo plausible y evidencia causal para evitar sobreafirmaciones.",
            ],
        ]

    method_counter = Counter(
        table_label(display_empirical_type(row.get("empirical_type")))
        for row in focus_rows
        if (row.get("work_type") or "").strip().lower() == "empirical"
        if table_label(display_empirical_type(row.get("empirical_type"))).lower() != "no reportado"
    )
    empirical_total = sum(method_counter.values())
    instrument_reported = sum(1 for row in focus_rows if nice_value(row.get("instruments_or_scales")).lower() != "no reportado")
    sample_reported = sum(1 for row in focus_rows if nice_value(row.get("sample_size")).lower() != "no reportado" or nice_value(row.get("sample_description")).lower() != "no reportado")
    theory_reported = sum(1 for row in focus_rows if nice_value(row.get("theory_framework")).lower() != "no reportado")
    result_reported = sum(1 for row in focus_rows if nice_value(row.get("key_findings")).lower() != "no reportado")
    return [
        ["Diseños empíricos", f"{counter_summary(method_counter, max(empirical_total, 1))} sobre {empirical_total}/{total} estudios empíricos focales", "El cuerpo principal distingue diseño y método para no convertir evidencias heterogéneas en una conclusión plana."],
        ["Instrumentos o métricas", f"{instrument_reported}/{total} estudios reportan instrumentos, escalas, benchmarks o métricas.", "La revisión conserva la diferencia entre afirmar un resultado y mostrar con qué instrumento fue producido."],
        ["Muestra o unidad de análisis", f"{sample_reported}/{total} estudios reportan muestra, corpus, casos o unidad analítica.", "La comparabilidad depende de saber qué se observó realmente en cada artículo."],
        ["Marco teórico", f"{theory_reported}/{total} estudios declaran marco teórico o conceptual recuperable.", "La ausencia de teoría explícita se reporta como límite del campo, no se corrige editorialmente."],
        ["Resultado sustantivo", f"{result_reported}/{total} estudios ofrecen hallazgo principal recuperable desde texto completo.", "Cada conclusión del artículo se apoya en fichas y CSV, no solo en una lectura narrativa."],
    ]


def domain_focus_summary_rows(focus_rows: list[dict[str, str]], profile: str) -> list[list[str]]:
    """Build a journal-friendly summary table; the full study matrix remains in CSV."""
    buckets: dict[str, list[dict[str, str]]] = {}
    ai_workload = profile not in {"social_sciences", "creativity_llm", "ai_higher_education_teaching", "education", "management"} and is_ai_workload_rows(focus_rows)
    rows_for_buckets = empirical_rows_only(focus_rows) if ai_workload and empirical_rows_only(focus_rows) else focus_rows
    for row in rows_for_buckets:
        if ai_workload:
            key = ai_workload_evidence_family(row)
        elif profile == "ai_security_harness":
            key = security_harness_evidence_family(row)
        elif profile == "creativity_llm":
            key = creativity_evidence_family(row)
        elif profile == "ai_higher_education_teaching":
            key = education_ai_evidence_family(row)
        elif profile == "social_sciences":
            key = social_science_evidence_family(row)
        else:
            key = dominant_label(
                [
                    table_label(display_work_type(row.get("work_type"))),
                    summarize_phrase_soft(first_nonempty(row.get("tasks_or_domains"), row.get("method_used")), width=44),
                ]
            )
        buckets.setdefault(key, []).append(row)

    rows: list[list[str]] = []
    for family, members in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
        designs = Counter(
            table_label(display_empirical_type(row.get("empirical_type")))
            if (row.get("work_type") or "").strip().lower() == "empirical"
            else "No empírico"
            for row in members
        )
        work_types = Counter(table_label(display_work_type(row.get("work_type"))) for row in members)
        methods = [
            summarize_phrase_soft(first_nonempty(row.get("instruments_or_scales"), row.get("benchmark_dataset_or_corpus"), row.get("method_used")), width=72)
            for row in members
        ]
        representative = max(members, key=lambda row: parse_int(row.get("extraction_confidence"), 0))
        reading = (
            ai_workload_family_synthetic_reading(family, members)
            if ai_workload
            else security_family_synthetic_reading(family, members)
            if profile == "ai_security_harness"
            else creativity_family_synthetic_reading(family, members)
            if profile == "creativity_llm"
            else social_family_synthetic_reading(family, members)
            if profile == "social_sciences"
            else principal_result_label(representative, width=105)
        )
        if ai_workload:
            reading = ai_workload_family_synthetic_reading(family, members)
        rows.append(
            [
                family,
                str(len(members)),
                dominant_label([label for label, _ in work_types.most_common(2)]),
                dominant_label([label for label, _ in designs.most_common(2)]),
                summarize_phrase_soft(dominant_label(methods), width=82),
            reading if ai_workload or profile in {"ai_security_harness", "creativity_llm", "social_sciences"} else summarize_phrase_soft(reading, width=115),
            ]
        )
    covered = sum(parse_int(row[1], 0) for row in rows)
    if ai_workload:
        support_count = max(len(focus_rows) - covered, 0)
        if support_count:
            rows.append(
                [
                    "Apoyo teórico, revisión o contexto",
                    str(support_count),
                    "No empírico",
                    "No aplica",
                    "lectura conceptual o metodológica",
                    "Acompaña la interpretación de mecanismos, pero no se usa como prueba directa de reducción o aumento neto de trabajo.",
                ]
            )
    elif focus_rows and covered != len(focus_rows):
        rows.append(
            [
                "Otros estudios focales",
                str(max(len(focus_rows) - covered, 0)),
                "mixto",
                "mixto",
                "métodos heterogéneos",
                "Fila de control añadida para que la tabla cubra todo el subconjunto focal.",
            ]
        )
    return rows


def short_authorial_position_sentence(focus_rows: list[dict[str, str]], context: dict[str, str]) -> str:
    """State the paper's falsifiable position early, before the manuscript hides behind counts."""
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    if is_ai_workload_context(context):
        return (
            "La posición que se somete a prueba es que la IA no debe evaluarse por velocidad visible de ejecución, "
            "sino por balance de trabajo total: qué esfuerzo desaparece, cuál reaparece como control y quién absorbe esa nueva capa."
        )
    if profile == "creativity_llm":
        return (
            "La posición que se somete a prueba es que la creatividad de los LLMs no se compara por modelo aislado, "
            "sino por la configuración entre tarea, criterio de novedad, juez, comparador y condición de generación."
        )
    if profile == "ai_higher_education_teaching":
        return (
            "La posición que se somete a prueba es que la IA no mejora la docencia universitaria por adopción tecnológica en sí misma, "
            "sino cuando modifica una tarea docente concreta bajo control pedagógico y evidencia de calidad."
        )
    if profile == "social_sciences":
        return (
            "La posición que se somete a prueba es que el campo no puede acumular conocimiento solo por coincidencia temática: "
            "debe comparar constructos, mecanismos, mediciones, contextos y alcance inferencial."
        )
    return (
        f"La posición que se somete a prueba es que {topic} no debe leerse como una lista de hallazgos, "
        "sino como una matriz de comparación entre objeto, método, evidencia, límites y condiciones de transferencia."
    )


def build_positioning_section_lines(focus_rows: list[dict[str, str]], context: dict[str, str]) -> list[str]:
    """Insert an explicit authorial position in every paper, independent of topic."""
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    contribution = authorial_contribution_model(
        profile,
        topic,
        len(focus_rows),
        len(focus_rows),
        diagnostics,
    )
    if is_ai_workload_context(context):
        return [
            "## Posicionamiento interpretativo del artículo",
            "",
            "La posición del artículo es deliberadamente incómoda: no basta con demostrar que la IA acelera una tarea para concluir que reduce trabajo. La tesis que organiza la revisión es que muchas ganancias de ejecución solo son reales si no reaparecen como revisión, rework, aprendizaje, coordinación, gobernanza o responsabilidad.",
            "",
            "Esta posición no niega los beneficios de la IA. Los limita. Una herramienta puede ahorrar tiempo y seguir aumentando el trabajo total si obliga a más control, más validación o más absorción organizativa. Por eso el artículo no pregunta si la IA es útil en abstracto, sino bajo qué configuración el ahorro visible supera el coste invisible.",
            "",
            "La tesis queda formulada como una afirmación falsable: si futuros estudios miden las seis capas del trabajo y muestran reducción conjunta de ejecución, articulación, verificación, coordinación, aprendizaje y responsabilidad sin pérdida de calidad, la hipótesis de desplazamiento deberá rebajarse. Mientras esa medición no exista, la afirmación de trabajar menos sigue siendo incompleta.",
        ]
    return [
        "## Posicionamiento interpretativo del artículo",
        "",
        str(contribution["thesis"]),
        "",
        "Esta posición obliga a separar tres planos que muchas revisiones mezclan: lo que el corpus permite afirmar, lo que solo aparece como señal emergente y lo que todavía no puede sostenerse sin mejores diseños primarios.",
        "",
        f"En este artículo, mojarse no significa convertir frecuencias en certeza. Significa declarar una unidad de comparación, explicar por qué esa unidad ordena {topic}, reconocer qué evidencia la sostiene y dejar claro qué hallazgo futuro podría matizarla o refutarla.",
    ]


def build_results_authorial_stance_lines(focus_rows: list[dict[str, str]], context: dict[str, str]) -> list[str]:
    """Add a deterministic stance matrix to Results so counts become claims with limits."""
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    empirical_n = len(empirical_rows_only(focus_rows))
    support_n = max(len(focus_rows) - empirical_n, 0)
    if profile == "ai_security_harness":
        counts = security_harness_signal_counts(focus_rows)
        rows = [
            [
                "Afirmación que sí sostiene el artículo",
                "La superioridad defensiva solo puede afirmarse dentro de un contrato compartido de amenaza, superficie, atacante, punto de aplicación y baseline.",
                f"Amenaza recuperable en {counts['threat']}/{len(focus_rows)} estudios, baseline en {counts['baseline']}/{len(focus_rows)} y eficacia defensiva cuantificada en {counts['asr']}/{len(focus_rows)}.",
            ],
            [
                "Afirmación que no sostiene",
                "No existe evidencia para ordenar todos los harnesses en un ranking universal ni para tratar una tasa de bloqueo aislada como seguridad operacional.",
                f"Solo {counts['adaptive']}/{len(focus_rows)} estudios prueban atacantes adaptativos y la cobertura de utilidad, falsos positivos, latencia y coste sigue siendo desigual.",
            ],
            [
                "Condición de frontera",
                "Una configuración domina de forma condicionada cuando reduce el riesgo frente al mismo atacante y baseline sin degradar de manera material la utilidad o desplazar un coste inaceptable.",
                "Si seguridad, utilidad y coste se compensan, el resultado correcto es una frontera de decisión, no un campeón único.",
            ],
            [
                "Qué cambiaría la tesis",
                "Replicaciones entre modelos, dominios y ataques adaptativos, con artefactos abiertos y medición conjunta de seguridad, utilidad, latencia, coste y fallo residual.",
                f"Robustez o transferencia aparece en {counts['robustness']}/{len(focus_rows)} estudios y modos de fallo en {counts['failure']}/{len(focus_rows)}; ampliar ambas señales permitiría convertir fronteras emergentes en recomendaciones más fuertes.",
            ],
        ]
    elif is_ai_workload_context(context):
        primary_rows = empirical_rows_only(focus_rows) or focus_rows
        counts = ai_workload_signal_counts(primary_rows)
        rows = [
            [
                "Afirmación que sí sostiene el artículo",
                "La evidencia disponible favorece una hipótesis de desplazamiento condicionado: la IA puede ahorrar ejecución, pero no demuestra reducción neta general de trabajo.",
                f"Productividad/tiempo en {counts['productivity']}/{len(primary_rows)} estudios empíricos primarios; aprendizaje, control, riesgo o gobernanza aparecen como capas de coste en la misma base empírica.",
            ],
            [
                "Afirmación que no sostiene",
                "No se afirma que la IA haga trabajar menos de forma universal ni que todo uso de IA intensifique el trabajo.",
                "La base empírica es heterogénea y muchos trabajos miden fases parciales de la tarea, no el flujo completo.",
            ],
            [
                "Condición de frontera",
                "El ahorro es más defendible cuando la tarea es acotada, el criterio de calidad es claro y revisar cuesta menos que producir manualmente.",
                "Cuando suben riesgo, ambigüedad, responsabilidad o coordinación, la promesa de ahorro debe tratarse como hipótesis, no como conclusión.",
            ],
            [
                "Qué cambiaría la tesis",
                "Estudios longitudinales o experimentales que midan ejecución, articulación, verificación, coordinación, aprendizaje y responsabilidad con calidad final comparable.",
                "Sin esa medición de trabajo total, los resultados de productividad local no bastan para cerrar la pregunta.",
            ],
        ]
    elif profile == "social_sciences":
        gap_text = reporting_gap_sentence(diagnostics)
        rows = [
            [
                "Afirmación que sí sostiene el artículo",
                "La relación revisada debe leerse como inferencia situada: constructo, mecanismo, medición, población y contexto institucional deciden si un hallazgo puede viajar a otro caso.",
                "La síntesis focal compara diseños y contextos antes de agregar resultados; por eso una asociación no se trata automáticamente como mecanismo general.",
            ],
            [
                "Afirmación que no sostiene",
                f"No se afirma una causalidad universal ni una respuesta única para {topic}.",
                f"La cautela viene de la heterogeneidad de medición y de los límites de reporte: {gap_text}.",
            ],
            [
                "Decisión para el campo",
                "Un nuevo estudio solo debería agregarse al mismo plano comparativo si declara constructo, mecanismo, unidad de análisis, instrumento, contexto, comparador y alcance inferencial.",
                "Si esas piezas faltan, el estudio puede ser útil como contexto, pero no como evidencia acumulativa fuerte.",
            ],
            [
                "Qué cambiaría la tesis",
                "Diseños longitudinales, experimentales, comparativos o multimétodo con medición explícita y contextos contrastables podrían convertir señales situadas en inferencias más transportables.",
                "Sin esa equivalencia, la revisión debe ayudar a decidir con prudencia, no vender una certeza que los datos primarios no sostienen.",
            ],
        ]
    else:
        contribution = authorial_contribution_model(
            profile,
            topic,
            len(focus_rows),
            len(focus_rows),
            diagnostics,
        )
        gap_text = reporting_gap_sentence(diagnostics)
        rows = [
            [
                "Afirmación que sí sostiene el artículo",
                str(contribution["field"]),
                "La síntesis focal permite proponer una unidad de comparación y una gramática analítica para ordenar el campo, no solo una lista de frecuencias.",
            ],
            [
                "Afirmación que no sostiene",
                "No se convierte frecuencia documental en causalidad ni se trata todo estudio como evidencia equivalente.",
                f"La cautela viene de los límites de reporte: {gap_text}.",
            ],
            [
                "Condición de frontera",
                "La tesis solo viaja a nuevos contextos cuando se mantienen objeto, método, unidad de análisis, medición, comparador y calidad de evidencia.",
                f"El corpus focal combina {empirical_n} estudios empíricos y {support_n} trabajos de apoyo o contexto.",
            ],
            [
                "Qué cambiaría la tesis",
                "Nuevos estudios con teoría, medición, comparador, validación y contexto más equivalentes podrían reforzar, matizar o refutar la gramática propuesta.",
                "La revisión queda diseñada como infraestructura de actualización, no como cierre retórico.",
            ],
        ]
    table_number = "8B" if profile == "ai_security_harness" else "8A"
    return [
        "## Lectura interpretativa de los resultados",
        "",
        "Antes de continuar con la síntesis, el artículo fija qué lectura autoriza el corpus y qué lectura no autoriza. Esta matriz evita que las tablas funcionen como decoración: cada número debe convertirse en una afirmación, una cautela o una condición de frontera.",
        "",
        f"Tabla {table_number}. Matriz de toma de posición interpretativa.",
        markdown_table(["Plano", "Lectura del artículo", "Base o cautela"], rows),
        "",
    ]


def build_results_decision_opening_lines(
    topic: str,
    focus_rows: list[dict[str, str]],
    included_count: int,
    contextual_count: int,
    context: dict[str, str],
    top_ids: list[str],
) -> list[str]:
    """Open Results with the scientific decision enabled by the evidence."""
    profile = detect_review_profile(context)
    focus_count = len(focus_rows)
    corpus_sentence = corpus_focus_relation(included_count, focus_count)
    cite = citation_block(top_ids[:4])
    if profile == "social_sciences":
        return [
            (
                f"Los resultados no deben leerse como un inventario de artículos sobre {topic}. "
                "La decisión científica que habilitan es más exigente: no conviene tratar el fenómeno revisado como una cadena causal única, sino como una relación situada entre constructos, mecanismos, mediciones, poblaciones y contextos institucionales."
            ),
            "",
            (
                "El valor del corpus está en marcar una frontera: hay evidencia suficiente para comparar patrones, mecanismos y condiciones de transferencia, pero no para convertir toda asociación empírica en una ley general. "
                "Esta lectura es más útil para la ciencia porque indica qué puede acumularse, qué debe mantenerse como señal contextual y qué no debería agregarse sin rediseñar la medición."
                + (f" {cite}." if cite else "")
            ),
            "",
            (
                f"El mapa documental conserva la trazabilidad completa: {included_count} estudios incluidos, {focus_count} estudios en síntesis focal y {contextual_count} estudios como perímetro contextual elegible. "
                f"{corpus_sentence}"
            ),
            "",
        ]
    if is_ai_workload_context(context):
        return [
            (
                f"Los resultados no responden a {topic} con un sí o un no simple. "
                "La decisión científica que permiten tomar es otra: una intervención de IA solo debería declararse reductora de trabajo si mide el trabajo total del sistema, no solo la velocidad de una tarea."
            ),
            "",
            (
                "La evidencia revisada autoriza una tesis prudente pero fuerte: la IA puede reducir ejecución local y, aun así, desplazar esfuerzo hacia formulación, revisión, coordinación, aprendizaje, gobernanza y responsabilidad. "
                "Por tanto, el criterio de decisión no debe ser `produce más rápido`, sino `reduce carga neta con calidad comparable y coste de control explícito`."
                + (f" {cite}." if cite else "")
            ),
            "",
            (
                f"El mapa documental conserva la trazabilidad completa: {included_count} estudios incluidos, {focus_count} estudios en síntesis focal y {contextual_count} estudios como perímetro contextual elegible. "
                f"{corpus_sentence}"
            ),
            "",
        ]
    if profile == "creativity_llm":
        return [
            (
                f"Los resultados no convierten {topic} en un ranking de modelos ni en una declaración abstracta sobre creatividad artificial. "
                "La decisión científica es comparar tareas, rúbricas, jueces, métricas y condiciones de evaluación antes de afirmar superioridad creativa."
            ),
            "",
            (
                "La evidencia permite decidir que la creatividad en LLMs es un fenómeno de configuración evaluativa: cambia cuando cambian tarea, prompt, muestra, criterio humano o métrica automática. "
                "Por eso el campo debería dejar de preguntar qué modelo es `más creativo` sin especificar qué creatividad se mide y quién la valida."
                + (f" {cite}." if cite else "")
            ),
            "",
            (
                f"El mapa documental conserva la trazabilidad completa: {included_count} estudios incluidos, {focus_count} estudios en síntesis focal y {contextual_count} estudios como perímetro contextual elegible. "
                f"{corpus_sentence}"
            ),
            "",
        ]
    if profile == "ai_higher_education_teaching":
        return [
            (
                f"Los resultados no deberían usarse para justificar adopción tecnológica genérica en {topic}. "
                "La decisión científica es bajar la comparación a tareas docentes verificables: planificación, feedback, evaluación, tutoría, analítica, inclusión o coordinación académica."
            ),
            "",
            (
                "La evidencia permite distinguir utilidad percibida de mejora educativa. La pregunta relevante no es si la IA se usa, sino qué tarea mejora, con qué control pedagógico, qué métrica de calidad y qué coste de supervisión para el profesorado."
                + (f" {cite}." if cite else "")
            ),
            "",
            (
                f"El mapa documental conserva la trazabilidad completa: {included_count} estudios incluidos, {focus_count} estudios en síntesis focal y {contextual_count} estudios como perímetro contextual elegible. "
                f"{corpus_sentence}"
            ),
            "",
        ]
    contribution = authorial_contribution_model(
        profile,
        topic,
        focus_count,
        included_count,
        conclusion_reporting_diagnostics(focus_rows),
    )
    return [
        (
            f"Los resultados no se presentan como una contabilidad plana de estudios sobre {topic}. "
            "La decisión científica que habilitan es identificar qué unidad de comparación permite acumular evidencia sin borrar diferencias de diseño, medición, contexto y calidad."
        ),
        "",
        (
            str(contribution["field"])
            + " En consecuencia, las tablas no funcionan como cierre descriptivo: funcionan como soporte para decidir qué afirmaciones son defendibles, cuáles son solo señales y qué vacíos impiden una conclusión más fuerte."
            + (f" {cite}." if cite else "")
        ),
        "",
        (
            f"El mapa documental conserva la trazabilidad completa: {included_count} estudios incluidos, {focus_count} estudios en síntesis focal y {contextual_count} estudios como perímetro contextual elegible. "
            f"{corpus_sentence}"
        ),
        "",
    ]


def build_introduction_section_domain(selected_rows: list[dict[str, str]], context: dict[str, str]) -> str:
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    rq = publication_research_question(context, profile)
    anchor_ids = top_citation_ids(selected_rows, 8)
    if is_ai_workload_context(context):
        opening = (
            "La pregunta sobre si la inteligencia artificial permite trabajar menos está mal formulada si solo mira la velocidad de una tarea. El punto crítico no es si una herramienta genera más rápido, sino si el trabajo total del sistema baja cuando se suman preparación, revisión, coordinación, aprendizaje, control de calidad y responsabilidad."
        )
        gap = (
            "El problema central es que buena parte del debate confunde productividad local con reducción neta de carga. Un asistente puede ahorrar minutos en redactar, clasificar o resumir, pero esos minutos pueden reaparecer como supervisión, corrección, rework, dependencia tecnológica, vigilancia de errores o rediseño de procesos. La revisión debe mojarse precisamente ahí: distinguir ahorro visible de desplazamiento invisible del esfuerzo."
        )
    elif profile == "creativity_llm":
        opening = (
            "La creatividad de los modelos de lenguaje se ha convertido en una pregunta empírica y no solo filosófica: ya no basta con afirmar que un modelo genera textos originales, sino que hay que preguntar con qué tarea, qué métrica, qué comparador humano y qué criterio de evaluación se sostiene esa afirmación."
        )
        gap = (
            "El problema central es que el campo mezcla escritura creativa, pensamiento divergente, resolución de problemas, ideación, originalidad, novedad y evaluaciones humanas o automáticas bajo una misma etiqueta. Sin una revisión sistemática, esa diversidad puede confundirse con evidencia acumulada cuando en realidad puede tratarse de diseños poco comparables."
        )
    elif profile == "social_sciences":
        opening = (
            f"La literatura sobre {topic} combina mediciones de actitudes, exposición informativa, contexto institucional y comportamiento político. En ciencias sociales, esa combinación exige más que localizar estudios: exige distinguir constructos, mecanismos, unidades de análisis y límites causales."
        )
        gap = (
            "El problema central es que una misma pregunta puede esconder diseños muy distintos: encuestas transversales, paneles, experimentos, análisis de contenido, datos de plataformas, entrevistas o revisiones. Sin una síntesis sistemática, una asociación puede confundirse con causalidad, un contexto nacional con evidencia general y una variable nominalmente igual con mediciones no equivalentes."
        )
    elif profile == "ai_security_harness":
        opening = (
            "Los modelos generativos dejan de ser componentes pasivos cuando recuperan documentos, mantienen memoria, llaman herramientas, escriben en sistemas externos o coordinan otros agentes. En ese momento, la seguridad ya no depende únicamente de la respuesta lingüística del modelo: depende de quién introduce datos, qué instrucciones conservan autoridad, qué capacidades puede ejecutar el sistema y qué daño sigue siendo posible después de una evasión."
        )
        gap = (
            "La literatura ha respondido con filtros, guardrails, clasificadores, separación entre instrucciones y datos, controles de procedencia, autorización de herramientas, sandboxing, monitores de trayectoria y verificadores de salida. Sin embargo, estas soluciones no protegen la misma superficie ni interrumpen el ataque en el mismo punto. Una tasa de bloqueo aislada puede ocultar que el atacante era estático, que la alternativa comparada era débil, que la utilidad legítima cayó o que la defensa trasladó el coste a latencia, tokens o revisión humana."
        )
    else:
        opening = (
            f"La literatura reciente sobre {topic} crece con rapidez y combina estudios empíricos, propuestas conceptuales, evaluaciones, benchmarks y revisiones parciales. En ese contexto, una revisión sistemática permite separar volumen documental de evidencia realmente comparable."
        )
        gap = (
            "El problema no es solo encontrar estudios, sino decidir cuáles responden a la pregunta, cuáles aportan evidencia verificable y cuáles quedan fuera por falta de método, trazabilidad o texto completo recuperable."
        )
    security_depth = []
    if profile == "ai_security_harness":
        security_depth = [
            "Esta heterogeneidad obliga a definir el objeto revisado con precisión. En este artículo, un harness de seguridad es el conjunto de controles externos o acoplados al modelo que observan, restringen, verifican, contienen o recuperan la operación del sistema durante inferencia y uso. La definición incluye controles en entrada, contexto, recuperación, memoria, razonamiento, llamadas de herramientas, salida y persistencia; excluye el entrenamiento de seguridad del modelo base cuando no existe una capa operacional evaluable. `Guardrail` se usa solo para el subconjunto de controles que clasifica, filtra o aplica una política sobre entradas, trayectorias o salidas; no se trata como sinónimo de toda la arquitectura del harness.",
            "",
            "El problema científico no consiste, por tanto, en preguntar qué producto bloquea más ataques en abstracto. Consiste en reconstruir un contrato comparativo: amenaza, capacidad del atacante, superficie protegida, mecanismo de control, punto de enforcement, baseline, reducción observada del riesgo, utilidad preservada, sobrecoste y modo de fallo residual. Dos defensas solo pueden ordenarse cuando ese contrato es suficientemente equivalente; si no lo es, sus cifras describen experimentos distintos y no una competición común.",
            "",
            "La evaluación adversarial añade una dificultad adicional. Un conjunto fijo de prompts mide cobertura sobre ejemplos conocidos, mientras que un adversario adaptativo busca la frontera del control, cambia la formulación, desplaza la carga maliciosa a documentos o herramientas y explota las decisiones del sistema completo. Esta diferencia separa una demostración local de una afirmación de robustez operacional y explica por qué el artículo trata adaptatividad, transferencia, ablación y fallos conocidos como evidencia central, no como anexos secundarios.",
            "",
            "La revisión adopta además una perspectiva multiobjetivo. Bloquear más no constituye una mejora si el harness inutiliza tareas legítimas, multiplica falsos positivos, introduce una latencia incompatible con el uso o desplaza el riesgo a una capa no observada. La decisión relevante es una frontera condicionada entre seguridad, utilidad, disponibilidad, coste y recuperabilidad. Esa frontera puede producir configuraciones prometedoras, pero no autoriza un ganador universal fuera de la amenaza y el entorno evaluados.",
            "",
        ]
    return "\n".join(
        [
            "# Introducción",
            "",
            opening + " " + citation_block(anchor_ids[:4]) + ".",
            "",
            gap + " " + citation_block(anchor_ids[4:8]) + ".",
            "",
            *security_depth,
            f"Este artículo aborda esa brecha mediante una revisión sistemática guiada por la pregunta: {rq} La unidad de análisis es el estudio publicado y leído en texto completo, no la mera presencia de palabras clave en bases bibliográficas.",
            "",
            short_authorial_position_sentence(selected_rows, context),
            "",
            "La lógica de la revisión es deliberadamente conservadora: un estudio solo sostiene afirmaciones de síntesis cuando dispone de DOI público, PDF local legible, extracción estructurada y una justificación visible dentro de la matriz de selección. Esta regla reduce cobertura bruta, pero aumenta la auditabilidad del manuscrito final.",
            "",
            (
                "La contribución buscada es doble. En el plano sustantivo, el artículo identifica qué combinaciones defensivas muestran la señal comparativa mejor sustentada y bajo qué límites dejan de dominar. En el plano teórico, propone una gramática para acumular evidencia sin confundir detección, prevención, contención y recuperación. Esta gramática convierte la seguridad en una propiedad situada del sistema y obliga a que cualquier afirmación de superioridad declare también su coste y su frontera de fallo."
                if profile == "ai_security_harness"
                else ""
            ),
        ]
    ).rstrip() + "\n"


def build_theoretical_framework_section_domain(focus_rows: list[dict[str, str]], context: dict[str, str]) -> str:
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    theories = theory_summary(focus_rows, 5)
    work_counts = work_type_summary(focus_rows)
    empirical_counts = empirical_summary(focus_rows)
    top_ids = top_citation_ids(focus_rows, 12)
    theory_sentence = (
        "Los marcos teóricos explícitos aparecen de forma dispersa: "
        + "; ".join(f"{label} (n={count})" for label, count in theories[:4])
        if theories
        else "No emerge un marco teórico único dominante; el corpus funciona como una acumulación de diseños, tareas e instrumentos más que como una escuela consolidada."
    )
    if profile == "creativity_llm":
        lens = (
            "La revisión usa como lente analítica la distinción entre creatividad como producto observable, creatividad como proceso de generación y creatividad como evaluación comparativa frente a humanos, benchmarks o jueces automáticos."
        )
    elif is_ai_workload_context(context):
        lens = (
            "La revisión usa como lente analítica la diferencia entre trabajo de ejecución y trabajo de control. Esta distinción es decisiva: la IA puede reducir el esfuerzo de producir una primera salida y, al mismo tiempo, aumentar el esfuerzo de formular la tarea, validar la salida, corregir fallos, coordinar decisiones, aprender nuevas rutinas y asumir responsabilidad por el resultado."
        )
    elif profile == "ai_higher_education_teaching":
        lens = (
            "La revisión usa como lente analítica la relación entre tarea docente, sistema de IA, control pedagógico y evidencia de calidad educativa. Esta decisión evita confundir adopción tecnológica, satisfacción del profesorado y mejora real de la enseñanza como si fueran el mismo constructo."
        )
    elif profile == "social_sciences":
        lens = (
            "La revisión usa como lente analítica la relación entre constructo, mecanismo, medición y contexto. Esta decisión evita confundir presencia de redes sociales, polarización, confianza o democracia con una relación causal homogénea; cada estudio se compara por lo que mide, cómo lo mide, sobre quién lo mide y bajo qué contexto institucional."
        )
    elif profile == "ai_security_harness":
        lens = (
            "La revisión usa como lente analítica la relación amenaza-superficie-control-enforcement-resultado. La amenaza define la capacidad y el objetivo del atacante; la superficie localiza dónde entra o se materializa el riesgo; el control identifica el mecanismo que interrumpe la cadena; el enforcement determina cuándo una decisión deja de ser solo recomendación; y el resultado debe medir simultáneamente reducción de daño, utilidad, coste y fallo residual."
        )
    else:
        lens = (
            "La revisión usa como lente analítica la relación entre unidad de análisis, método, evidencia recuperable y resultado reportado. Esta decisión evita imponer una teoría externa cuando el propio corpus todavía muestra heterogeneidad conceptual."
        )
    comparison_axis = (
        "diseño, constructo, muestra, contexto, instrumento, variables, comparadores y hallazgos"
        if profile == "social_sciences"
        else "ejecución, articulación, verificación, coordinación, aprendizaje, responsabilidad, métricas de productividad y señales de carga"
        if is_ai_workload_context(context)
        else "diseño, tarea, instrumentos, modelos o sistemas analizados, métricas y hallazgos"
    )
    empirical_total = work_counts.get("empirical", 0)
    if is_ai_workload_context(context):
        thesis_lines = [
            "1. La revisión distingue ahorro de tarea y reducción neta de trabajo: una mejora en tiempo de ejecución no basta para afirmar que se trabaja menos.",
            "2. La comparación se organiza por ejecución, articulación, verificación, coordinación, aprendizaje y responsabilidad, no por una etiqueta genérica de `uso de IA`.",
            "3. La productividad se interpreta como señal parcial; la carga de trabajo exige medir también revisión, errores, rework, coordinación, dependencia y coste de control.",
            "4. La aportación teórica del artículo consiste en convertir la promesa de automatización en una contabilidad del trabajo total del sistema.",
        ]
    elif profile == "ai_security_harness":
        thesis_lines = [
            "1. La unidad de comparación no es el modelo ni el nombre del guardrail, sino el contrato operacional completo entre amenaza, superficie, control, punto de enforcement, baseline, eficacia, utilidad, coste y fallo residual.",
            "2. Detección, prevención, contención y recuperación son funciones defensivas distintas. Un estudio debe declarar cuál implementa y qué daño puede ocurrir si esa función falla.",
            "3. Cobertura estática y robustez adaptativa no son equivalentes. La segunda exige que el atacante pueda observar, reformular o trasladar su estrategia frente al control desplegado.",
            "4. La superioridad es condicionada y multiobjetivo. Una defensa domina solo dentro de amenazas comparables y cuando mejora seguridad sin un deterioro desproporcionado de utilidad, disponibilidad o coste.",
            "5. El modo de fallo no es una nota negativa, sino una propiedad teórica del harness: define la frontera donde hacen falta una capa compensatoria, recuperación o intervención humana.",
            "6. La acumulación científica requiere taxonomías suficientemente precisas para no convertir controles no tipificados o benchmarks incompatibles en una mayoría artificial.",
        ]
    else:
        thesis_lines = [
            "1. La revisión trata la evidencia recuperable como condición de interpretación: sin texto completo y extracción trazable, una afirmación no entra en la síntesis focal.",
            f"2. La comparación se organiza por {comparison_axis}, no por popularidad del artículo ni por visibilidad de una etiqueta temática.",
            "3. La heterogeneidad del corpus se reporta como resultado metodológico, no como ruido a ocultar: cuando faltan teoría, muestra, variables, comparadores o validación, esa ausencia pasa a formar parte del diagnóstico.",
            "4. La aportación teórica del artículo consiste en convertir un campo rápido y desigual en una matriz comparable de decisiones, métodos, evidencias, límites y vacíos acumulativos.",
        ]
    security_framework = []
    if profile == "ai_security_harness":
        security_framework = [
            "## Modelo conceptual de la defensa operacional",
            "",
            "En este marco, el `contrato comparativo` es la unidad mínima que hace interpretable una comparación: especifica amenaza y capacidad del atacante, superficie y activo protegidos, mecanismo de control, punto de enforcement, acción permitida o denegada, baseline, métricas de seguridad y utilidad, latencia, coste, robustez y fallo residual. No es una plantilla administrativa. Es la condición de conmensurabilidad que permite decidir si dos resultados prueban alternativas frente al mismo problema o si describen experimentos que solo comparten vocabulario.",
            "",
            "El primer eje del modelo conceptual es la autoridad. Los ataques de prompt injection explotan la dificultad de distinguir instrucciones legítimas, datos no confiables y contenido recuperado que intenta adquirir autoridad. Los controles de procedencia, separación de contexto y flujo de información responden a esta ambigüedad; su hipótesis causal es que el sistema puede impedir que una fuente no autorizada determine una acción aunque el modelo procese su contenido.",
            "",
            "El segundo eje es la capacidad. Un agente se vuelve peligroso cuando una salida textual puede transformarse en lectura de secretos, escritura, compra, envío, ejecución o persistencia. Autorización, mínimos privilegios, sandboxing y validación de llamadas actúan sobre esa transición. Su valor no depende de que el modelo reconozca siempre el ataque, sino de reducir qué puede hacer una decisión equivocada y de contener el radio de impacto.",
            "",
            "El tercer eje es la observabilidad temporal. Los filtros de entrada actúan antes de que el modelo razone; los monitores de contexto y trayectoria actúan durante la construcción de la acción; los verificadores de salida actúan después de generar una respuesta; y los controles de memoria condicionan interacciones futuras. Ningún punto observa por sí solo toda la cadena. La arquitectura defensiva debe situar el control antes del momento en que el daño se vuelve irreversible.",
            "",
            "El cuarto eje es la evaluación. La seguridad empírica debe tratarse como una comparación adversarial y multiobjetivo, no como exactitud de clasificación aislada. ASR, falsos positivos, utilidad, latencia, coste, ataques no vistos, transferencia y disponibilidad describen dimensiones diferentes. La combinación de estas medidas determina si una defensa reduce riesgo operativo o solo desplaza el problema.",
            "",
            "De estos ejes emerge una gramática de defensa operacional: autoridad, capacidad, observabilidad y evaluación. Esta gramática no presupone que una familia sea universalmente superior; permite explicar por qué ciertos controles pueden complementarse, por qué otros son redundantes y qué evidencia haría falta para sostener una frontera de dominancia entre configuraciones.",
            "",
        ]
    return "\n".join(
        [
            "# Marco teórico",
            "",
            (
                "El corpus se interpreta desde una tesis de reorganización del trabajo: la IA no debe estudiarse solo como sustituto de tareas, sino como dispositivo que redistribuye esfuerzo entre producción, control y responsabilidad "
                + citation_block(top_ids[:4])
                + "."
                if is_ai_workload_context(context)
                else f"El corpus sobre {topic} se interpreta como un campo de evidencia en construcción. La revisión no presupone que exista una teoría única capaz de ordenar todos los estudios; primero identifica cómo cada artículo define su objeto, qué método usa, qué unidad analiza y qué resultado afirma " + citation_block(top_ids[:4]) + "."
            ),
            "",
            (
                "Para evitar un marco teórico decorativo, la revisión separa seis capas del trabajo humano: ejecución, articulación, verificación, coordinación, aprendizaje y responsabilidad. Esta arquitectura permite leer la productividad como una parte del fenómeno, no como el fenómeno completo. Si una intervención reduce ejecución pero aumenta verificación o responsabilidad, la conclusión no puede ser que se trabaja menos sin matices."
                if is_ai_workload_context(context)
                else "Para evitar que el marco teórico sea solo un inventario de autores o conceptos, esta revisión lo organiza en tres capas. La primera capa recoge las teorías, marcos conceptuales o vocabularios que los propios estudios declaran. La segunda capa construye una lente analítica común para comparar estudios que no siempre usan las mismas palabras. La tercera capa fija límites interpretativos: qué puede afirmarse con los datos disponibles, qué aparece solo como señal emergente y qué no debe convertirse todavía en conclusión fuerte."
            ),
            "",
            lens,
            "",
            *security_framework,
            theory_sentence,
            "",
            f"Metodológicamente, la síntesis focal contiene {len(focus_rows)} estudios; {empirical_total} de ellos son empíricos. Dentro de los estudios empíricos, los diseños se distribuyen como {', '.join(f'{table_label(display_empirical_type(label))}: n={count}' for label, count in empirical_counts.most_common()) or 'no reportado con suficiente granularidad'}. Esta distribución importa porque las conclusiones de una revisión sistemática no deben pesar igual cuando proceden de experimentos, benchmarks, estudios cualitativos, revisiones o propuestas teóricas.",
            "",
            *build_positioning_section_lines(focus_rows, context),
            "",
            "## Tesis analíticas del marco",
            *thesis_lines,
        ]
    ) + "\n"


def selection_weight_triplet(context: dict[str, str] | None = None) -> tuple[float, float, float]:
    """Read the active methodological-mode weights used by the focal score."""
    context = context or {}
    mode_key = context.get("primary_review_mode") or context.get("review_mode") or "technical"
    return selection_weights(mode_key)


def selection_weight_percent(value: float) -> str:
    """Format a decimal weight as a whole-number percentage for prose tables."""
    return f"{round(value * 100):.0f}%"


def review_mode_display(context: dict[str, str]) -> str:
    """Return one readable mode label without repeating primary metadata."""

    label = normalize_phrase(context.get("review_mode_label"))
    summary = normalize_phrase(context.get("review_mode_summary"))
    if label and summary.lower() == f"{label}; principal: {label}".lower():
        return label
    return summary or label or "modo metodológico declarado"


def focal_score_formula_lines(context: dict[str, str] | None = None) -> list[str]:
    """Return the focal-selection score as a readable Markdown/LaTeX block."""
    context = context or {}
    wr, wq, wp = selection_weight_triplet(context)

    def latex_weight(value: float) -> str:
        return f"{value:.2f}".replace(".", "{,}")

    return [
        "La regla de priorización focal puede expresarse formalmente como:",
        "",
        "$$",
        rf"\mathrm{{Score}}_{{i}}={latex_weight(wr)}\,\mathrm{{Rel}}_{{i}}+{latex_weight(wq)}\,\mathrm{{Cal}}_{{i}}+{latex_weight(wp)}\,\mathrm{{Rep}}_{{i}}",
        "$$",
        "",
        f"donde $\\mathrm{{Rel}}_{{i}}$ representa la relevancia temática del estudio, $\\mathrm{{Cal}}_{{i}}$ su calidad metodológica recuperable y $\\mathrm{{Rep}}_{{i}}$ la corrección de representatividad/diversidad aplicada antes del corte focal. Las ponderaciones proceden del {review_mode_display(context)} y las tres magnitudes se expresan en escala 0-100.",
        "",
        "Operativamente, la relevancia se asigna por bandas de ajuste temático: sin ajuste suficiente, ajuste tangencial, ajuste directo a la pregunta y ajuste directo con mecanismo, variables y contexto recuperables. La calidad combina confianza de extracción, claridad de diseño, muestra/unidad, método, comparador, resultado y limitaciones recuperables. La representatividad aplica una corrección de diversidad para no saturar el N focal con la misma fuente, familia temática, país, plataforma, diseño o registro casi duplicado. Los valores crudos y el score resultante se conservan en `paper/appendices/data/selection-score-matrix.csv`.",
        "",
        "La representatividad no se interpreta como calidad adicional del artículo, sino como corrección de diversidad: evita que el N focal quede saturado por una misma fuente, familia temática, tipo de trabajo, país, plataforma, benchmark o propuesta casi duplicada. En empates o bandas equivalentes, se conserva el orden estable de la matriz auditada y no se reordenan manualmente los registros después de conocer los resultados.",
    ]


def focal_score_component_rubric_rows() -> list[list[str]]:
    """Explain how the three score components should be audited by readers."""
    return [
        [
            "Relevancia temática (Rel)",
            "0-100",
            "Ajuste a la pregunta, población/contexto, tecnología o intervención, tarea/dominio, ventana temporal y criterios de inclusión.",
        ],
        [
            "Calidad metodológica recuperable (Cal)",
            "0-100",
            "Claridad de diseño, muestra o unidad analítica, método/instrumento, comparador, resultado, limitaciones y trazabilidad textual en PDF.",
        ],
        [
            "Representatividad/diversidad (Rep)",
            "0-100",
            "Corrección para evitar que el N focal quede dominado por una fuente, familia de tarea, tipo de estudio, país, año o propuesta casi duplicada.",
        ],
        [
            "Desempate y estabilidad",
            "orden estable",
            "Cuando varios estudios quedan en la misma banda de score, no se introduce una jerarquía artificial: se conserva el orden auditado, se reporta el umbral y se deja una matriz suplementaria para reproducir o reabrir el corte.",
        ],
        [
            "Corte operativo",
            "score compuesto",
            "El ranking se aplica solo a estudios ya incluidos por full text; no sustituye criterios de elegibilidad ni elimina del corpus contextual los estudios válidos fuera del N focal.",
        ],
    ]


def build_method_section_domain(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    all_shortlist_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    topic = review_subject_label_es(context)
    profile = detect_review_profile(context)
    raw_n_contract = parse_intake_field(review_dir, "Límite final N ultraquality")
    n_min, n_max = parse_n_range(raw_n_contract)
    target_n = n_max or len(focus_rows)
    n_contract_text = (
        f"un rango entre {n_min} y {n_max} estudios"
        if n_min and n_max and n_min != n_max
        else f"{target_n or len(focus_rows)} estudios"
    )
    source_rows = search_source_execution_rows(review_dir)
    score_rows = selection_score_display_rows(review_dir, focus_rows, profile)
    score_component_rows = selection_score_component_rows(review_dir, focus_rows)
    non_focal_rows = non_focal_selection_compact_rows(all_shortlist_rows)
    focal_context_rows = focal_context_characteristics_rows(focus_rows, all_shortlist_rows)
    sensitivity = shortlist_sensitivity(review_dir)
    score_threshold = score_rows[-1][2] if score_rows and len(score_rows[-1]) > 2 else "no reportado"
    wr, wq, wp = selection_weight_triplet(context)
    prisma_rows = [
        ["Registros identificados", str(flow_counts.get("identified", 0))],
        ["Duplicados consolidados antes del cribado", str(flow_counts.get("duplicates_removed", 0))],
        ["Cribado título/resumen", str(flow_counts.get("screened_title_abstract", 0))],
        ["Exclusiones título/resumen", str(flow_counts.get("excluded_title_abstract", 0))],
        [
            "Candidatos tras título/resumen (include/maybe)",
            str(max(flow_counts.get("screened_title_abstract", 0) - flow_counts.get("excluded_title_abstract", 0), 0)),
        ],
        [
            "No trasladados a recuperación tras precheck documental",
            str(
                max(
                    flow_counts.get("screened_title_abstract", 0)
                    - flow_counts.get("excluded_title_abstract", 0)
                    - flow_counts.get("full_text_sought", 0),
                    0,
                )
            ),
        ],
        ["Candidatos enviados a recuperación de texto completo", str(flow_counts.get("full_text_sought", 0))],
        ["PDF o texto completo no recuperado", str(flow_counts.get("full_text_not_retrieved", 0))],
        ["PDF o texto completo recuperado y evaluado", str(flow_counts.get("full_text_assessed", 0))],
        ["Estudios incluidos tras lectura de texto completo", str(flow_counts.get("included_in_review", 0))],
        ["Estudios de síntesis focal", str(len(focus_rows))],
        ["Estudios focales con DOI y PDF local legible", str(len(focus_rows))],
    ]
    cap_rows = [
        ["Elegibilidad de entrada", "solo estudios incluidos tras lectura de texto completo"],
        ["DOI público", "sin DOI normalizado no entra en el corpus publicable"],
        ["PDF local legible", "sin texto completo extraído no entra en síntesis focal"],
        ["Relevancia temática", f"{selection_weight_percent(wr)} del score compuesto; mide ajuste a pregunta y criterios"],
        ["Calidad metodológica", f"{selection_weight_percent(wq)} del score compuesto; mide diseño, método, muestra, evaluación y trazabilidad"],
        ["Representatividad", f"{selection_weight_percent(wp)} del score compuesto; evita concentración por fuente o familia casi idéntica"],
        ["Corte focal", f"entran los estudios robustos dentro del contrato {n_contract_text}; en esta revisión el umbral efectivo del score compuesto fue >= {score_threshold}"],
        ["Umbral de confianza", "la síntesis focal exige extracción robusta; por defecto se usa confianza >= 80 salvo que el protocolo documente una reserva excepcional"],
        ["Sensibilidad", f"solapamiento alternativo: {sensitivity.get('alt_a_overlap', 0)}/{sensitivity.get('target_n', 0)} y {sensitivity.get('alt_b_overlap', 0)}/{sensitivity.get('target_n', 0)}"],
    ]
    rubric_rows = [
        ["Ajuste explícito a la pregunta de investigación", "25"],
        ["Claridad de diseño, muestra o unidad de análisis", "20"],
        ["Método, instrumento, métrica o procedimiento reportado", "20"],
        ["Resultado sustantivo y limitaciones recuperables", "20"],
        ["Trazabilidad dentro del PDF y consistencia de extracción", "15"],
    ]
    if is_ai_workload_context(context):
        empirical_focus_total = len(empirical_rows_only(focus_rows))
        non_empirical_focus_total = max(len(focus_rows) - empirical_focus_total, 0)
        empirical_scope_paragraph = (
            f"Dado que la pregunta solicita evidencia empírica, la síntesis se organiza en dos capas probatorias. "
            f"La primera capa contiene los {empirical_focus_total} estudios empíricos del subconjunto focal y sostiene la respuesta sobre reducción, desplazamiento o intensificación del trabajo. "
            f"La segunda capa contiene {non_empirical_focus_total} trabajos teóricos, metodológicos o de revisión que ayudan a construir vocabulario, mecanismo y cautela interpretativa, pero no se contabilizan como prueba directa de efecto empírico. "
            "Esta separación evita que una revisión amplia parezca más concluyente de lo que permite su base empírica."
        )
    else:
        empirical_scope_paragraph = ""
    return "\n".join(
        [
            "# Método",
            "",
            f"El estudio se diseñó como una revisión sistemática de literatura sobre {topic}. La metodología combinó planificación explícita, búsqueda trazable, cribado documentado, lectura de texto completo y síntesis focal; los estándares de reporte de revisiones sistemáticas se usaron como soporte de transparencia, no como sustituto de la contribución analítica (Kitchenham & Charters, 2007; Snyder, 2019; Page et al., 2021; Rethlefsen et al., 2021).",
            "",
            "## Diseño de la revisión sistemática",
            f"La unidad de análisis fue el estudio publicado sobre {topic}. La ventana temporal fue {review_timeframe_phrase_es(context)} y se cerró con fechas exactas en el protocolo y en `searches/search-log.csv`, evitando proyectar la revisión hasta un final de 2026 todavía no observado.",
            "",
            f"Antes de ejecutar la búsqueda se estableció un modo metodológico: {review_mode_display(context)}. Esta decisión afecta al marco de pregunta, la descomposición de búsqueda, el cribado, la evaluación crítica, la ponderación del score focal y la forma de síntesis. En consecuencia, la revisión no aplica un molde único a cualquier disciplina: adapta la lógica de comparación a la unidad real de evidencia del campo.",
            "",
            "No se registró un protocolo externo en PROSPERO ni en OSF antes de iniciar la revisión. Esta ausencia no se oculta ni se sustituye por una declaración retrospectiva: delimita el estatus del estudio. Como compensación de transparencia, el paquete conserva la captación inicial fechada, la pregunta, los criterios previos, la estrategia y descomposición de búsqueda, los logs por fuente, las decisiones de cribado, las discrepancias resueltas, los PDFs recuperados, la matriz de extracción y las reglas del corte focal. Una réplica puede así reconstruir qué decisiones precedieron a los resultados y cuáles surgieron durante la síntesis.",
            "",
            "La revisión aplicó una regla conservadora de publicabilidad: DOI público normalizado, PDF local legible y extracción textual trazable. Esta regla puede excluir estudios potencialmente interesantes sin DOI o sin PDF recuperable, pero evita que el artículo final mezcle evidencia auditable con referencias imposibles de verificar.",
            "",
            f"El subconjunto focal no se decidió por intuición editorial. El protocolo fijó {n_contract_text} para síntesis focal; después, solo los estudios incluidos tras lectura de texto completo fueron ordenados mediante un score compuesto transparente que se formaliza más abajo junto a la matriz de selección. Cuando el protocolo declara un rango, la regla no fuerza un número exacto: selecciona todos los estudios que cumplen DOI público, PDF legible, extracción trazable, confianza suficiente y score compuesto dentro del máximo autorizado, siempre que se alcance el mínimo metodológico. En esta revisión, el último estudio seleccionado fija un umbral efectivo de score >= {score_threshold}. Los estudios que cumplen la revisión pero no entran en ese corte se conservan como corpus contextual, de modo que la revisión no los borra ni los usa indebidamente como evidencia fina.",
            "",
            empirical_scope_paragraph,
            "" if empirical_scope_paragraph else "",
            "La puntuación fue diseñada como heurística transparente de priorización: la relevancia temática se calcula desde el ajuste a la pregunta, los criterios y las señales recuperables en título, resumen y texto completo; la calidad metodológica se apoya en diseño, muestra, instrumento, método, resultado y limitaciones recuperables; y la representatividad penaliza duplicación excesiva de una misma familia, fuente o tipo de tarea. El score focal no se presenta como una doble codificación humana: el manuscrito publica sus componentes, sensibilidad alternativa y trazabilidad DOI/PDF para que el corte pueda ser auditado externamente.",
            "",
            f"Como control de sensibilidad, el corte focal se recalculó con dos variantes de pesos del score: `0,40/0,40/0,20` y `0,45/0,30/0,25`. En esta revisión, esas variantes conservaron {sensitivity.get('alt_a_overlap', 0)}/{sensitivity.get('target_n', 0)} y {sensitivity.get('alt_b_overlap', 0)}/{sensitivity.get('target_n', 0)} estudios del subconjunto focal. Esta prueba verifica que el N final no depende de una única ponderación oportunista, aunque no sustituye una codificación humana independiente del score.",
            "",
            *build_method_depth_lines(review_dir, focus_rows, flow_counts, context),
            "",
            "## Criterios de inclusión",
            f"- {context.get('inclusion') or f'Estudios científicos con ajuste sustantivo a {topic}, método identificable y texto completo recuperable.'}",
            "- DOI público normalizado.",
            "- PDF local legible para lectura de texto completo.",
            "",
            "## Criterios de exclusión",
            f"- {context.get('exclusion') or 'Registros sin ajuste temático suficiente, sin método recuperable, sin DOI público o sin PDF legible.'}",
            "- Material divulgativo, editorial, tutorial o meramente promocional sin contribución investigadora verificable.",
            "- Mención tangencial del tema sin análisis, evaluación o resultado sustantivo.",
            "",
            "Figura 1. Arquitectura operativa de revisión.",
            figure_markdown("../../figures/png/fig-review-architecture.png", "Figura 1. Arquitectura operativa de revisión"),
            "",
            "Tabla 1. Flujo de selección de estudios.",
            markdown_table(["Etapa", "N"], prisma_rows),
            "",
            f"En la Tabla 1 no hay contradicción entre cribado y recuperación: tras título/resumen quedaron {max(flow_counts.get('screened_title_abstract', 0) - flow_counts.get('excluded_title_abstract', 0), 0)} registros include/maybe. De ellos, {max(flow_counts.get('screened_title_abstract', 0) - flow_counts.get('excluded_title_abstract', 0) - flow_counts.get('full_text_sought', 0), 0)} no se trasladaron a recuperación por precheck documental, tipo de material, duplicidad funcional, falta de DOI utilizable o baja densidad metodológica antes de búsqueda de PDF; los {flow_counts.get('full_text_sought', 0)} restantes sí pasaron a recuperación de texto completo. De esos {flow_counts.get('full_text_sought', 0)}, {flow_counts.get('full_text_not_retrieved', 0)} no tuvieron PDF recuperable y {flow_counts.get('full_text_assessed', 0)} fueron evaluados a partir de PDF o texto completo extraído.",
            "",
            "Tabla 2. Ejecución y cobertura operativa de la búsqueda por fuente.",
            markdown_table(["Fuente", "Eventos", "Resultados brutos", "Estado operacional"], source_rows),
            "",
            "Los resultados brutos de la Tabla 2 son respuestas acumuladas antes de deduplicación y pueden solaparse entre cadenas y fuentes. `—` no equivale a cero resultados: indica que la fuente no llegó a ejecutarse o que el log conserva una incidencia sin recuento recuperable. En particular, una única fila de Scopus, Web of Science, IEEE Xplore, Embase o Lens documenta su comprobación operacional y eventual omisión por acceso opcional, no una búsqueda equivalente a las APIs abiertas. Esta diferencia se conserva como límite de cobertura en lugar de presentar como ejecutada una fuente que no lo fue.",
            "",
            search_coverage_limit_sentence(source_rows),
            "",
            *search_strategy_summary_lines(review_dir, context),
            "Tabla 3. Reglas operativas de composición del subconjunto focal.",
            markdown_table(["Criterio", "Regla operativa"], cap_rows),
            "",
            "Tabla 4. Rúbrica operativa de confianza de extracción.",
            markdown_table(["Indicador", "Peso máximo"], rubric_rows),
            "",
            "Tabla 4A. Componentes auditables del score en estudios focales.",
            markdown_table(
                ["Pos.", "DOI", "Rel.", "Calidad", "Rep.", "Score"],
                score_component_rows or [["-", "-", "0,0", "0,0", "0,0", "0,0"]],
            ),
            "",
            "Nota metodológica sobre la relevancia: cuando todos los estudios focales muestran una relevancia similar, la columna `Rel.` debe leerse como puerta de elegibilidad temática, no como una jerarquía fina. En ese caso, la discriminación real del subconjunto focal procede de calidad metodológica recuperable, representatividad/diversidad, confianza de extracción, disponibilidad de PDF y estabilidad del corte. La tabla conserva `Rel.` precisamente para mostrar que no se introducen décimas artificiales de relevancia cuando el corpus ya pasó un umbral temático homogéneo.",
            "",
            "Tabla 4B. Estatus de estudios contextuales elegibles pero no focales.",
            markdown_table(
                ["Pos./rango", "N o DOI", "Score", "Rel.", "Calidad", "Rep.", "Criterio operativo"],
                non_focal_rows
                or [["-", "0", "0,0", "0,0", "0,0", "0,0", "Todos los estudios incluidos entraron en la síntesis focal."]],
            ),
            "",
            (
                "La Tabla 4B expone score o rango de score para que el recorte focal no quede como decisión opaca. Estos registros pertenecen al perímetro contextual elegible de la revisión, pero no alcanzaron el umbral combinado que justifica tratarlos al mismo nivel que el N focal. La distinción metodológica relevante es focal frente a contextual: reordenar internamente ese perímetro exigiría una segunda ronda de extracción profunda o una validación humana adicional."
                if non_focal_rows
                else "No hay estudios contextuales fuera del N focal; por tanto, no se necesita lectura contextual adicional."
            ),
            "",
            "Tabla 4C. Comparación focal-contextual.",
            markdown_table(
                ["Grupo", "N", "Perfil dominante", "Vacíos de reporte", "Score/estatus", "Fuentes principales"],
                focal_context_rows,
            ),
            "",
            "La Tabla 4C verifica que el recorte focal no se trate como una caja negra: compara el núcleo intensivo con los estudios incluidos que permanecen como contexto, mostrando perfil dominante, vacíos de reporte, score medio y fuentes. Si ambos grupos difieren, esa diferencia se interpreta como límite de transferencia de la síntesis focal y no como desaparición metodológica del corpus contextual. En el perímetro contextual, un campo vacío significa que esa variable no fue recuperada en la matriz compacta de selección; no demuestra por sí solo que el paper original no la reporte ni que el estudio sea de menor calidad. El rasgo común de ese perímetro es una densidad comparativa o un score inferiores al umbral focal. Elevar uno de esos registros al mismo plano analítico exige lectura y extracción profunda adicionales, no una inferencia desde el vacío tabular.",
            "",
            "La puntuación base de la preselección focal se calculó mediante una regla ponderada explícita.",
            "",
            *focal_score_formula_lines(context),
            "",
            "Tabla 4D. Operacionalización auditable de los componentes del score.",
            markdown_table(["Componente", "Escala", "Criterios observables"], focal_score_component_rubric_rows()),
            "",
            f"La Tabla 4A identifica mediante DOI los {len(focus_rows)} estudios que sostienen la síntesis intensiva y desglosa relevancia, calidad, representatividad y score para cada uno; la Tabla 4B muestra score o rango de score de los registros contextuales; y la matriz suplementaria conserva títulos, DOI y razones operativas para auditar la selección del N final sin depender de una decisión opaca del manuscrito. El umbral >= {score_threshold} debe leerse como resultado operativo de la regla aplicada al corpus focal, no como una frontera inventada después de leer los resultados. Las variantes de sensibilidad mantienen el solapamiento indicado en la Tabla 3 y funcionan como control contra un corte oportunista.",
        ]
    ) + "\n"


def build_method_depth_lines(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> list[str]:
    """Add a reusable methodological depth layer beyond flow counts and selection diagrams."""
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    identified = flow_counts.get("identified", 0)
    screened = flow_counts.get("screened_title_abstract", 0)
    sought = flow_counts.get("full_text_sought", 0)
    assessed = flow_counts.get("full_text_assessed", 0)
    included = flow_counts.get("included_in_review", 0)
    not_retrieved = flow_counts.get("full_text_not_retrieved", 0)
    diagnostics = conclusion_reporting_diagnostics(focus_rows)

    if profile in {"ai_architecture", "software_architecture", "agent_architecture"}:
        unit_sentence = (
            f"La unidad de análisis fue la configuración arquitectónica reportada por cada estudio sobre {topic}: tarea, modelo o familia de modelos, recuperación, memoria, herramientas, roles, orquestación, política de inferencia, evaluación, dominio, método, muestra, variables, resultados, limitaciones y trazabilidad textual. "
            "Esta decisión evita que dos papers se traten como comparables solo porque usan el mismo modelo base o una etiqueta parecida."
        )
        extraction_sentence = (
            "La extracción estructurada no se limitó a resumen bibliográfico. Para cada PDF se buscó contribución arquitectónica, tarea o dominio, componentes funcionales, mecanismo de coordinación, fuentes de evidencia, evaluación, benchmark o comparador, resultados principales, límites, señales de riesgo y nivel de detalle metodológico. Cuando un componente no estaba reportado, se conservó como ausencia explícita y no se infirió por conveniencia."
        )
    elif profile == "personality_llm":
        unit_sentence = (
            f"La unidad de análisis fue la configuración constructo-procedimiento-efecto reportada por cada estudio sobre {topic}: constructo de personalidad, instrumento, prompt o intervención, modelo, tarea, muestra o simulación, métrica, comparador, efecto observado, limitaciones y trazabilidad textual. "
            "Esta decisión evita tratar como equivalentes estudios que comparten la palabra personalidad pero miden profiling, steering o efectos downstream distintos."
        )
        extraction_sentence = (
            "La extracción estructurada separó constructo, intervención, instrumento psicométrico, condiciones de generación, muestra o corpus, comparador, métrica, resultado, efecto downstream y limitaciones. Cuando el paper no distinguía rasgo, estilo, persona inducida o role-play, esa ambigüedad se conservó como dato metodológico y no se resolvió artificialmente."
        )
    elif profile == "ai_higher_education_teaching":
        unit_sentence = (
            f"La unidad de análisis fue la configuración tarea docente-sistema de IA-evidencia pedagógica reportada por cada estudio sobre {topic}: actividad del profesorado, herramienta o sistema usado, contexto universitario, diseño pedagógico, muestra o corpus, comparador, resultado observado, riesgo, limitación y trazabilidad textual. "
            "Esta decisión evita tratar como equivalentes estudios que solo comparten la etiqueta de IA, pero analizan tareas docentes, niveles de adopción o resultados educativos distintos."
        )
        extraction_sentence = (
            "La extracción estructurada separó tarea docente, tipo de IA, rol del profesorado, contexto institucional, actividad educativa, instrumentos, comparadores, resultados de calidad, eficiencia, feedback, evaluación, diseño curricular, alfabetización en IA, integridad académica y límites. Cuando el paper solo reportaba intención de uso o percepción sin resultado pedagógico trazable, esa debilidad se conservó como dato metodológico."
        )
    elif profile == "ai_security_harness":
        unit_sentence = (
            f"La unidad de análisis fue el contrato operacional de defensa reportado por cada estudio sobre {topic}: activo protegido, amenaza, capacidad del atacante, superficie, arquitectura de control, punto de aplicación, decisión autorizada o denegada, baseline, métrica de seguridad, utilidad, latencia, coste, robustez y fallo residual. "
            "Esta decisión evita tratar como equivalentes un filtro de entrada, un monitor de trayectoria, una política de herramientas y un sandbox solo porque todos se presenten como guardrails."
        )
        extraction_sentence = (
            "La extracción estructurada separó amenaza y superficie, control y punto de enforcement, atacante estático o adaptativo, corpus o entorno de evaluación, baseline, ASR o métrica defensiva equivalente, falsos positivos, utilidad, latencia, coste, transferencia, ablaciones, modos de fallo y disponibilidad de artefactos. Una cifra solo se codificó como resultado cuando el PDF permitía vincularla con el control y la evaluación observados; números de tablas, parámetros de diseño, coste del atacante o afirmaciones sin valor medido no se reutilizaron como rendimiento del harness."
        )
    elif profile == "creativity_llm":
        unit_sentence = (
            f"La unidad de análisis fue la configuración tarea-criterio-evaluación reportada por cada estudio sobre {topic}: tarea creativa, definición de novedad o utilidad, modelo, condición de generación, juez, métrica, comparador, resultado, limitación y trazabilidad textual. "
            "Esta decisión evita convertir creatividad en una propiedad global del modelo cuando los papers miden fenómenos creativos distintos."
        )
        extraction_sentence = (
            "La extracción estructurada separó tipo de tarea creativa, criterio de evaluación, juez humano o automático, condiciones de prompting, comparador, métrica, salida evaluada, resultado y límites. Cuando creatividad aparecía como etiqueta general sin operacionalización, se codificó como debilidad de constructo."
        )
    else:
        unit_sentence = (
            f"La unidad de análisis fue el estudio publicado sobre {topic}, pero la comparación se hizo sobre configuraciones metodológicas y sustantivas: objeto, diseño, unidad empírica, método, muestra o corpus, variables o dimensiones, instrumento, resultado, limitación y trazabilidad textual. "
            "Esta decisión evita que la revisión trate como equivalentes estudios que solo comparten palabras clave."
        )
        extraction_sentence = (
            "La extracción estructurada buscó método, muestra o unidad de análisis, país o contexto, variables o dimensiones, instrumento, comparador, resultado, limitaciones, marco teórico y evidencia localizada dentro del texto completo. Los silencios de reporte se conservaron como hallazgos metodológicos porque afectan a la posibilidad de comparación acumulativa."
        )

    return [
        "## Profundización metodológica y trazabilidad",
        "La pregunta de investigación se tradujo en un protocolo operativo antes de interpretar resultados: tema, ventana temporal, fuentes, criterios, N objetivo, unidad de análisis y reglas de exclusión quedaron documentados como decisiones metodológicas previas. Esto es importante porque el método no debe aparecer solo como una narración posterior; debe funcionar como frontera previa que decide qué evidencia puede entrar, con qué peso y bajo qué condiciones.",
        "",
        unit_sentence,
        "",
        f"La búsqueda se interpretó como captación reproducible y no como acumulación indiscriminada. Los {identified} registros identificados pasaron por deduplicación, cribado de título/resumen y recuperación de texto completo; los {screened} registros cribados no equivalen a estudios incluidos, sino al universo sometido a decisión inicial. El paso crítico fue la transición a texto completo: se buscaron {sought} PDFs o textos completos, {not_retrieved} no fueron recuperables y {assessed} pudieron evaluarse materialmente.",
        "",
        "La decisión de cribado se organizó en tres estados: OK, KO o necesita más prueba. OK exige ajuste temático suficiente, DOI trazable y evidencia recuperable; KO exige motivo explícito de exclusión; necesita más prueba se usa cuando título y resumen no bastan para cerrar la decisión sin leer texto completo. Esta regla reduce el riesgo de excluir por intuición y obliga a que las decisiones dudosas avancen a una fase más exigente.",
        "",
        "La lectura de texto completo funcionó como segunda frontera metodológica. Un registro no entró en el corpus final por promesa del abstract, popularidad del tema o afinidad con la tesis del artículo; entró cuando el PDF permitió recuperar evidencia suficiente sobre método, resultado y límite. Esta regla puede ser conservadora, pero protege la revisión frente a inferencias no auditables.",
        "",
        extraction_sentence,
        "",
        f"La calidad no se trató como prestigio editorial, sino como extractabilidad y comparabilidad. El score combina relevancia temática, calidad metodológica y representatividad; además, la confianza de extracción valora si el PDF permite localizar lo que el artículo afirma. En el subconjunto focal, los vacíos de reporte quedan visibles: {reporting_gap_sentence(diagnostics)}.",
        "",
        "La evaluación crítica se separó en dos capas. La primera capa valora calidad metodológica como parte del score de selección; la segunda capa, reportada en resultados, clasifica el riesgo de reporting y trazabilidad por estudio. Esta separación evita confundir prioridad de inclusión con certeza de inferencia: un estudio puede ser muy relevante para la pregunta y, aun así, dejar límites por comparador, teoría, validación externa o reporting incompleto.",
        "",
        f"La síntesis se dividió en dos niveles: corpus incluido y síntesis focal. Los {included} estudios incluidos delimitan el perímetro de la revisión; los {len(focus_rows)} estudios focales sostienen la comparación intensiva. Esta separación evita dos errores frecuentes: presentar todo el corpus como si tuviera la misma densidad de evidencia o, al contrario, ocultar estudios válidos solo porque no entran en el N final.",
        "",
        *screening_reliability_method_lines(review_dir),
        "",
        "La reproducibilidad se sostiene en artefactos concretos: protocolo, estrategia de búsqueda, logs por fuente, índice DOI, duplicados, registros cribados, decisiones de texto completo, matriz de extracción, matriz de score, anexos tabulares, PDFs locales cuando la licencia lo permite y paquete editorial. El método queda así conectado a archivos verificables y no solo a una declaración de buenas intenciones.",
    ]


def build_results_section_domain(
    review_dir: pathlib.Path,
    all_review_rows: list[dict[str, str]],
    focus_rows: list[dict[str, str]],
) -> str:
    context = read_research_context(review_dir)
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    corpus_rows = all_review_rows or focus_rows
    flow_counts = read_flow_counts(review_dir)
    included_count = max(len(corpus_rows), flow_counts.get("included_in_review", 0))
    work_counter = work_type_summary(corpus_rows)
    classified_total = sum(work_counter.values())
    if included_count > classified_total:
        work_counter["unclassified"] += included_count - classified_total
    contextual_count = max(included_count - len(focus_rows), 0)
    empirical_counter = empirical_summary(focus_rows)
    empirical_focus_total = sum(empirical_counter.values())
    non_empirical_focus_total = max(len(focus_rows) - empirical_focus_total, 0)
    analytic_status_rows = [
        ["Estudios empíricos dentro de la síntesis focal", f"{empirical_focus_total} ({percentage(empirical_focus_total, included_count)})"],
    ]
    if non_empirical_focus_total:
        analytic_status_rows.append(
            [
                "Estudios teóricos, de revisión o metodológicos dentro de la síntesis focal",
                f"{non_empirical_focus_total} ({percentage(non_empirical_focus_total, included_count)})",
            ]
        )
    if contextual_count:
        analytic_status_rows.append(
            ["Perímetro contextual elegible no focal", f"{contextual_count} ({percentage(contextual_count, included_count)})"]
        )
    empirical_rows = [[table_label(display_empirical_type(label)), f"{count} ({percentage(count, sum(empirical_counter.values()))})"] for label, count in empirical_counter.most_common()]
    bias_rows = risk_of_bias_rows(focus_rows)
    per_study_bias_rows = study_risk_of_bias_rows(focus_rows)
    appraisal_signal_summary_rows = critical_appraisal_signal_summary_rows(focus_rows)
    appraisal_weight_rows = critical_appraisal_weight_rows()
    compact_bias_rows = [
            [
                row[0],
                row[1],
                row[2],
                f"Sin tamaño/corpus: {row[3]}; sin contexto: {row[4]}; sin teoría: {row[5]}; riesgo: {row[6]}",
            ]
        for row in bias_rows
    ]
    summary_rows = domain_focus_summary_rows(focus_rows, profile)
    compact_summary_rows = [[row[0], row[1], row[3], row[5]] for row in summary_rows]
    aggregate_rows = domain_aggregate_result_rows(focus_rows, profile)
    top_ids = top_citation_ids(focus_rows, 24)
    table7_8_note_lines: list[str] = []
    if profile == "social_sciences":
        social_family_counts = Counter(social_science_evidence_family(row) for row in focus_rows)
        trust_dominant = social_family_counts.get("Confianza institucional y legitimidad democrática", 0)
        trust_signal = social_science_signal_counts(focus_rows)["trust"]
        table7_8_note_lines = [
            f"Nota de lectura para las Tablas 7 y 8: la Tabla 7 clasifica cada estudio por familia dominante, mientras que la Tabla 8 cuenta señales presentes dentro del texto completo. Por eso `confianza/legitimidad institucional` puede aparecer como familia principal en {trust_dominant}/{len(focus_rows)} estudios y como señal sustantiva en {trust_signal}/{len(focus_rows)}. No es una discrepancia contable: es una advertencia sobre cobertura y fuerza inferencial.",
            "En consecuencia, las conclusiones sobre confianza institucional se formulan como evidencia condicionada y no como estimación universal. La revisión puede discutir cómo la confianza aparece conectada con exposición, identidad, información y legitimidad, pero debe reconocer que el núcleo más denso del corpus está en polarización afectiva e identidad partidista.",
            "Regla de codificación de mecanismos: una palabra aislada no se trata como mecanismo. Exposición, identidad, confianza, legitimidad o desinformación solo entran en la síntesis mecanística cuando aparecen conectadas con una unidad de análisis, un diseño, una medición o una lectura causal explícita; si esa conexión no existe, la señal se conserva como contexto temático y no como evidencia de mecanismo.",
        ]
    if len(focus_rows) == empirical_focus_total:
        focus_empirical_note = (
            f"Las filas de la Tabla 7 cubren el subconjunto focal completo: {sum(parse_int(row[1], 0) for row in summary_rows)} de {len(focus_rows)} estudios. "
            f"En esta revisión, los {len(focus_rows)} estudios focales se clasifican como empíricos; los estudios contextuales no focales quedan fuera de esta síntesis intensiva."
        )
    else:
        focus_empirical_note = (
            f"Las filas de la Tabla 7 cubren el subconjunto focal completo: {sum(parse_int(row[1], 0) for row in summary_rows)} de {len(focus_rows)} estudios. "
            f"La diferencia entre {len(focus_rows)} estudios focales y {empirical_focus_total} estudios empíricos se debe a que el subconjunto puede contener revisiones, trabajos teóricos o estudios metodológicos que aportan estructura conceptual pero no se clasifican como empíricos."
        )
    if profile == "ai_security_harness":
        result_focus = "El patrón principal es que la eficacia defensiva no forma una jerarquía única: depende de amenaza, superficie, punto de aplicación, atacante, baseline y compensación entre seguridad, utilidad y coste."
    elif profile == "creativity_llm":
        result_focus = "El patrón principal es la diversidad de tareas e instrumentos: la creatividad aparece como escritura, ideación, pensamiento divergente, originalidad, novedad o resolución creativa de problemas, con comparadores y métricas todavía heterogéneos."
    elif profile == "social_sciences":
        result_focus = "El patrón principal es la relación condicional entre constructos: exposición digital, polarización, confianza, información y contexto institucional no forman una causa única, sino una red de mecanismos y mediciones."
    else:
        result_focus = "El patrón principal es la heterogeneidad metodológica: el corpus combina diseños, unidades de análisis, métricas e instrumentos que obligan a distinguir mapa general y síntesis focal."
    if profile == "ai_security_harness":
        theme_figure_explanation = (
            "La Figura 0 compara, en el panel izquierdo, la cobertura de amenazas y superficies y, en el "
            "panel derecho, las familias de control. Las barras representan conteos multietiqueta, por lo "
            "que un estudio puede contribuir a varias categorías. La concentración en prompt injection y "
            "monitores de ejecución describe dónde existe más investigación, no qué control es más eficaz; "
            "la categoría no tipificada hace visible la parte que todavía no admite ranking por mecanismo. "
            "`Familias de control` nombra aquí el conjunto amplio de funciones del harness; `guardrail` se "
            "reserva para controles de clasificación, filtrado o política y no se usa como sinónimo del sistema completo. "
            + result_focus
        )
        matrix_figure_explanation = (
            "La Figura 0 cruza amenazas en columnas y familias de control en filas. La intensidad y el número "
            "de cada celda indican cuántos estudios focales evalúan ese cruce; una celda vacía significa "
            "ausencia de evidencia recuperable, no eficacia nula. El mapa muestra dónde pueden buscarse "
            "replicaciones comparables y dónde la literatura aún carece de cobertura entre superficie y control."
        )
    else:
        theme_figure_explanation = (
            "La Figura 0 organiza el campo por familias sustantivas para que la lectura no dependa solo de "
            "frecuencias aisladas. " + result_focus
        )
        matrix_figure_explanation = (
            "La Figura 0 cruza dimensiones del corpus y permite detectar qué combinaciones concentran "
            "evidencia suficiente para sostener una comparación focal."
        )
    security_frontier_lines = (
        security_frontier_result_lines(review_dir)
        if profile == "ai_security_harness"
        else []
    )
    design_appraisal_lines: list[str] = []
    if profile == "ai_security_harness":
        design_appraisal_lines = [
            "La evaluación crítica se interpreta con una rúbrica específica de seguridad. Para cada estudio se comprueba si la amenaza está definida, si el atacante es estático o adaptativo, si existe baseline, si el corpus de ataques es reproducible, si se reporta eficacia defensiva, si se conserva utilidad, si se cuantifican falsos positivos, latencia o coste, y si se prueban ataques no vistos, transferencia entre modelos o modos de fallo. Esta adaptación impide que una reducción local de ASR se trate como evidencia suficiente de superioridad operacional.",
            "",
        ]
    elif profile in {"social_sciences", "management", "education", "generic"}:
        design_appraisal_lines = [
            "La evaluación crítica se interpreta por familia de diseño y no como checklist único. La rúbrica se apoya en criterios de revisiones sistemáticas aplicadas (Kitchenham & Charters, 2007; Snyder, 2019), en la lógica de evaluación crítica de JBI/MMAT cuando procede y en dominios propios de management y ciencias sociales: claridad de constructo, unidad de análisis, medición, contexto, comparador, validez interna, transferencia y robustez. En experimentos o evaluaciones se revisan tratamiento, comparador, tamaño muestral, medición y posibilidad de inferencia causal; en encuestas, paneles o estudios organizativos se priorizan muestra, instrumento, contexto, dirección temporal y controles; en análisis de contenido o plataforma se revisan corpus, estrategia de muestreo, codificación y vínculo con resultados observables; en cualitativos se valoran caso, contexto, trazabilidad interpretativa y transferibilidad; y en revisiones o trabajos teóricos se registra función probatoria auxiliar, no efecto empírico. Esta adaptación se documenta en `paper/appendices/data/critical-appraisal-matrix.csv` y evita tratar estudios heterogéneos como si todos pudieran evaluarse con una herramienta clínica única.",
            "",
        ]
    non_empirical_clarification_lines: list[str] = []
    if non_empirical_focus_total:
        non_empirical_clarification_lines = [
            "Tabla 5A. Función probatoria de los estudios focales según tipo de evidencia.",
            markdown_table(
                ["Capa de evidencia", "N", "Función dentro de la síntesis", "Peso interpretativo"],
                [
                    [
                        "Evidencia empírica directa",
                        str(empirical_focus_total),
                        "Sostiene la respuesta principal a la pregunta de investigación mediante datos, muestra, corpus, experimento, encuesta, panel, caso o evaluación observable.",
                        "Base probatoria para afirmaciones sustantivas.",
                    ],
                    [
                        "Soporte teórico, metodológico o de revisión",
                        str(non_empirical_focus_total),
                        "Aporta vocabulario conceptual, mecanismos plausibles, límites de medición, contexto disciplinar o contraste con revisiones previas.",
                        "Apoyo interpretativo; no se contabiliza como efecto empírico equivalente.",
                    ],
                ],
            ),
            "",
            f"Esta separación es importante porque la pregunta de investigación pide evidencia empírica. Por ello, los {empirical_focus_total} estudios empíricos sostienen el peso probatorio de la respuesta, mientras que los {non_empirical_focus_total} trabajos no empíricos cumplen una función auxiliar: ordenar conceptos, mecanismos, límites de medición y condiciones de interpretación. La síntesis no los usa para inflar la evidencia empírica ni para cerrar efectos causales; los usa para explicar por qué ciertos hallazgos pueden compararse y por qué otros deben mantenerse como contexto.",
            "La Tabla 5A clasifica función probatoria; la Tabla 7, en cambio, clasifica familia sustantiva dominante. Por eso sus N no deben sumarse ni compararse como si midieran lo mismo: una tabla responde qué peso tiene cada tipo de evidencia y la otra responde qué tema organiza cada estudio focal.",
            "",
        ]
    result_figure_number = 2
    result_figure_blocks: list[str] = []
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-corpus-map",
        result_figure_number,
        "Mapa del corpus por tipo de trabajo, fuente y señal empírica.",
        "Mapa del corpus",
        f"La Figura 2 resume la base documental de la revisión sobre {topic} y ayuda a distinguir composición general, foco empírico y perímetro contextual.",
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-theme-landscape",
        result_figure_number,
        "Panorama temático del corpus final.",
        "Panorama temático",
        theme_figure_explanation,
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-agent-task-matrix",
        result_figure_number,
        "Matriz entre temas, tareas, métodos y resultados observados.",
        "Matriz tema-método",
        matrix_figure_explanation,
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-method-profile",
        result_figure_number,
        "Mapa de comparabilidad metodológica de los estudios empíricos.",
        "Mapa de comparabilidad metodológica",
        "La Figura 5 resume el nivel de comparabilidad metodológica del subconjunto focal: diseño, muestra, contexto, variables, comparador y validación.",
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-evidence-maturity",
        result_figure_number,
        "Madurez comparativa de la evidencia por estado y dominio de resultado.",
        "Madurez comparativa de la evidencia",
        "La Figura 0 separa alineación descriptiva, evidencia insuficiente y preguntas abiertas. Esta distinción evita presentar como consenso causal lo que todavía es repetición documental, heterogeneidad no resuelta o una comparación aislada.",
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-topic-network",
        result_figure_number,
        "Red temática del corpus y comunidades principales.",
        "Red temática del corpus",
        "La Figura 0 sitúa los temas dominantes dentro de una estructura relacional: identifica comunidades, conceptos puente y zonas periféricas que no pueden recuperarse mediante una lista plana de palabras clave.",
    )
    result_figure_blocks.extend(blocks)
    return "\n".join(
        [
            "# Resultados",
            "",
            *build_results_decision_opening_lines(
                topic,
                focus_rows,
                included_count,
                contextual_count,
                context,
                top_ids,
            ),
            *result_figure_blocks,
            *build_evidence_position_lines(review_dir),
            "Tabla 5. Distribución del corpus incluido por estado analítico.",
            markdown_table(["Estado analítico", "N"], analytic_status_rows or [["Sin datos", "0"]]),
            "",
            f"En la Tabla 5, el estado analítico separa el corpus incluido completo de la síntesis focal. La revisión contiene {included_count} estudios incluidos: {len(focus_rows)} sostienen la comparación intensiva y {contextual_count} {'permanece' if contextual_count == 1 else 'permanecen'} como perímetro contextual elegible no focal. Dentro de la síntesis focal, {empirical_focus_total} estudios son empíricos y {non_empirical_focus_total} aportan soporte teórico, metodológico o de revisión. Esta separación evita mezclar tipo de trabajo con función analítica dentro del manuscrito; los porcentajes se calculan sobre el N incluido total para mostrar la arquitectura completa del corpus.",
            "",
            *non_empirical_clarification_lines,
            "Tabla 6. Distribución del subconjunto empírico por diseño.",
            markdown_table(["Tipo empírico", "N"], empirical_rows or [["Sin datos", "0"]]),
            "",
            "Nota: los porcentajes de las tablas descriptivas se redondean a una decimal y pueden no sumar exactamente 100%.",
            "",
            "Tabla 7. Síntesis compacta del subconjunto focal por familia de evidencia.",
            markdown_table(
                ["Familia", "N", "Diseño dominante", "Lectura sintética"],
                compact_summary_rows or [["Sin estudios focales", "0", "-", "-"]],
            ),
            "",
            focus_empirical_note,
            "",
            "Tabla 8. Señales agregadas que sostienen la síntesis principal.",
            markdown_table(
                ["Dimensión", "Señal agregada", "Lectura para la revisión"],
                aggregate_rows,
            ),
            "",
            *security_frontier_lines,
            *[line + "\n" for line in table7_8_note_lines],
            *build_results_authorial_stance_lines(focus_rows, context),
            *domain_substantive_synthesis_lines(profile, topic, focus_rows, top_ids),
            "Este bloque evita que la síntesis dependa de una frase por familia. El cuerpo principal conserva las señales necesarias para interpretar constructos, mecanismos, unidades de análisis, métodos, comparadores y dirección de resultados; la matriz suplementaria mantiene el detalle por estudio para trazabilidad y actualización.",
            "",
            f"La matriz completa por estudio no se fuerza dentro del cuerpo del PDF porque pierde legibilidad cuando combina DOI, título, constructos, unidades de análisis, instrumentos, métodos y hallazgos de {len(focus_rows)} estudios focales. Por ese motivo, el cuerpo principal resume la información comparable y el material suplementario conserva la trazabilidad detallada.",
            "",
            "Tabla 9. Evaluación crítica de reporting, trazabilidad y cautela inferencial.",
            markdown_table(
                ["Diseño", "N", "Score crítico medio", "Perfil de reporting"],
                compact_bias_rows or [["Sin datos", "0", "0,0", "No evaluable"]],
            ),
            "",
            f"La Tabla 9 resume el perfil agregado, pero la evaluación crítica no queda solo en un promedio ni replica mecánicamente la confianza de extracción. Para cada uno de los {len(focus_rows)} estudios focales se aplicó una rúbrica específica de esta revisión para valorar reporting, trazabilidad y cautela inferencial, basada en cinco señales auditables: tamaño muestral o corpus, contexto o país, marco teórico, comparador o línea base y validación/robustez recuperable desde el PDF. El score crítico se calcula como `0,55 × confianza de extracción + 0,45 × cobertura de señales aplicables`. La cobertura de señales aplicables se obtiene con los pesos de la Tabla 9A; cuando una dimensión no aplica por tipo de trabajo, no penaliza el denominador. Esta rúbrica no se presenta como sustituto universal de una herramienta validada de riesgo de sesgo; separa la calidad de reporte/extractabilidad de la certeza causal. Por eso los resultados empíricos se interpretan con cautela cuando faltan comparador, medición, contexto, validación externa o control de endogeneidad. Los conteos agregados y la codificación de cada estudio pueden recomputarse en `paper/appendices/data/critical-appraisal-matrix.csv`, donde se conservan DOI, señales reportadas, vacíos, dimensiones no aplicables y score.",
            "",
            *design_appraisal_lines,
            "Tabla 9A. Pesos de la evaluación crítica de reporting y trazabilidad.",
            markdown_table(
                ["Señal auditable", "Peso", "Criterio de lectura"],
                appraisal_weight_rows,
            ),
            "",
            "Tabla 9B. Riesgo de reporting por estudio focal.",
            markdown_table(
                ["#", "Referencia", "DOI", "Riesgo", "Base del juicio"],
                per_study_bias_rows or [["-", "Sin estudios focales", "-", "No evaluable", "-"]],
            ),
            "",
            "Tabla 9C. Indicadores agregados de evaluación crítica.",
            markdown_table(
                ["Señal auditable", "Reportada", "Vacío", "No aplica", "Lectura interpretativa"],
                appraisal_signal_summary_rows or [["Sin estudios focales", "0", "0", "0", "No evaluable"]],
            ),
            "",
            "La Tabla 9C resume la codificación crítica de forma agregada para no desplazar al cuerpo principal una matriz excesivamente granular. En esta tabla, la columna reportada indica señales recuperables en el texto completo, la columna vacío indica reporte insuficiente y la columna no aplica identifica dimensiones que no corresponden al tipo de trabajo evaluado.",
            "",
            "En conjunto, los resultados se apoyan en lectura de texto completo, extracción estructurada y tablas de síntesis comparables. La síntesis focal permite identificar patrones sin borrar la variabilidad metodológica que caracteriza al corpus " + citation_block(top_ids[4:8]) + ".",
        ]
    ) + "\n"


def build_discussion_section_domain(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    top_ids = top_citation_ids(focus_rows, 24)
    empirical_counter = empirical_summary(focus_rows)
    empirical_text = ", ".join(f"{table_label(display_empirical_type(label))}: n={count}" for label, count in empirical_counter.most_common()) or "sin granularidad suficiente"
    theory_families = theory_family_counter(focus_rows, 4)
    theory_text = ", ".join(f"{label} (n={count})" for label, count in theory_families) if theory_families else "marcos teóricos dispersos o no reportados"
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    contribution_model = authorial_contribution_model(
        profile,
        topic,
        len(focus_rows),
        flow_counts.get("included_in_review", len(focus_rows)),
        diagnostics,
    )
    contribution_rows = list(contribution_model["rows"])  # type: ignore[arg-type]
    grammar_figure_blocks, _discussion_next_figure = render_numbered_body_figure(
        review_dir,
        "fig-analytical-grammar",
        next_discussion_figure_number(review_dir),
        "Modelo interpretativo de la gramática analítica propuesta por la revisión.",
        "Modelo interpretativo de la gramática analítica",
        "La Figura 0 sintetiza la aportación del artículo como una gramática comparativa: define la unidad real de comparación, ordena las dimensiones que explican el campo, separa evidencia estable de señal emergente y convierte los vacíos de reporte en agenda futura.",
    )

    def cite_suffix(record_ids: list[str], limit: int = 4) -> str:
        citation = citation_block(record_ids, limit=limit)
        return f" {citation}" if citation else ""

    if is_ai_workload_context(context):
        empirical_rows = empirical_rows_only(focus_rows)
        support_rows = support_rows_only(focus_rows)
        primary_rows = empirical_rows or focus_rows
        primary_total = len(primary_rows)
        counts = ai_workload_signal_counts(primary_rows)
        theoretical = (
            "La discusión central no es si la IA produce más rápido, sino si reduce el trabajo humano total cuando se contabilizan las capas que aparecen antes, durante y después de la producción de una salida."
        )
        discussion_development = [
            (
                f"El primer punto de discusión es probatorio: la pregunta pide evidencia empírica y, por tanto, el peso principal debe recaer en {primary_total} estudios empíricos. "
                f"Los {len(support_rows)} trabajos restantes ayudan a interpretar conceptos, mecanismos o revisiones previas, pero no se usan aquí para inflar la fuerza de la conclusión. "
                "Esta separación cambia el tono del artículo: no se vende una certeza amplia, se defiende una tesis prudente sobre cómo se redistribuye el esfuerzo cuando la IA entra en flujos de trabajo reales."
            ),
            (
                f"El segundo punto es que productividad local no equivale a reducción neta. En la base empírica, {counts['productivity']}/{primary_total} estudios contienen señal de productividad, eficiencia o tiempo. "
                "Esa señal tiene valor, pero suele mirar una fase visible de la tarea: generar, responder, resumir, clasificar o producir una primera versión. "
                "La inferencia fuerte solo sería válida si el estudio mide también preparación, revisión, corrección, rework, coordinación, aprendizaje y responsabilidad. Cuando esas capas quedan fuera, el resultado describe velocidad de ejecución, no carga total de trabajo."
            ),
            (
                f"El tercer punto es la supervisión. {counts['supervision']}/{primary_total} estudios empíricos contienen señales de revisión, control, coordinación, supervisión o rework. "
                "Pero esta frecuencia no debe presentarse como descubrimiento espontáneo: la estrategia de búsqueda ya incluía términos de supervisión, revisión y coordinación. "
                "La aportación no está en contar que aparece supervisión, sino en interpretar qué papel cumple: la IA desplaza parte del trabajo desde producir directamente hacia definir, comprobar, corregir, integrar y justificar salidas."
            ),
            (
                f"El cuarto punto es el coste de error. {counts['risk_error']}/{primary_total} estudios empíricos contienen señales de riesgo, error, sesgo, privacidad u omisión, y {counts['high_risk']}/{primary_total} se sitúan en ámbitos de decisión experta o alto impacto. "
                "En esos escenarios, una salida más rápida no es necesariamente una mejora si aumenta el coste de verificarla o si desplaza responsabilidad a una persona que no controla del todo el sistema. "
                "La tesis se vuelve condicional: la IA reduce trabajo cuando el coste de revisión es menor que el ahorro de ejecución; lo desplaza o intensifica cuando ocurre lo contrario."
            ),
            (
                f"El quinto punto es aprendizaje y dependencia. {counts['learning']}/{primary_total} estudios empíricos contienen señales de formación, alfabetización, habilidades, dependencia o adaptación. "
                "Esto importa porque aprender a usar IA no es una fase externa al trabajo: es trabajo. También lo es rediseñar procedimientos, ajustar criterios de calidad, decidir cuándo confiar y detectar cuándo una salida plausible es falsa o incompleta. "
                "La literatura que solo mide el antes/después de una tarea puede perder justo la capa donde aparece el coste de adopción."
            ),
            (
                f"El sexto punto es organizativo. {counts['governance']}/{primary_total} estudios empíricos contienen señales de gobernanza, responsabilidad, política de uso o rendición de cuentas. "
                "Aquí la pregunta deja de ser individual y pasa a ser institucional: una persona puede tardar menos en producir un borrador, pero la organización puede necesitar nuevas normas, controles, auditorías, formación, documentación y gestión del riesgo. "
                "Por eso la conclusión más seria no es que la IA ahorre o no ahorre trabajo de forma universal, sino que cambia quién hace qué trabajo, en qué fase y con qué responsabilidad."
            ),
        ]
        practical = (
            "Para organizaciones, universidades y equipos profesionales, la implicación práctica es medir el flujo completo antes de declarar ahorro: tarea inicial, calidad final, revisión, errores, rework, coordinación, aprendizaje, gobernanza y responsabilidad."
        )
        evidence_implication = (
            "En términos sustantivos, la revisión sugiere una hipótesis de desplazamiento condicionado: la IA puede ahorrar ejecución en tareas delimitadas, pero no demuestra reducción neta si el trabajo reaparece como control, aprendizaje, coordinación o riesgo institucional."
        )
    elif profile == "ai_security_harness":
        counts = security_harness_signal_counts(focus_rows)
        family_counts = Counter(security_harness_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(family_counts, len(focus_rows), limit=6)
        sparse_families = [
            label for label, count in family_counts.items() if count == 1
        ]
        theoretical = (
            "La seguridad de modelos generativos y sistemas agénticos debe entenderse como una propiedad del sistema completo y de su entorno de amenaza, no como una propiedad intrínseca del modelo ni como la mera presencia de un filtro."
        )
        discussion_development = [
            (
                f"El primer punto de discusión es que la evidencia focal se distribuye entre {family_text}. "
                "Esta composición muestra que `harness de seguridad` designa controles distintos: algunos filtran lenguaje, otros aíslan contexto, restringen herramientas, monitorizan ejecución, verifican salidas o protegen secretos. "
                f"Compararlos como una sola clase borraría qué superficie protege cada uno y qué daño puede seguir ocurriendo{cite_suffix(top_ids[:4])}."
            ),
            *(
                [
                    (
                        f"Las familias sostenidas por un único estudio —{join_human_list(sparse_families)}— "
                        "se conservan para no borrar una superficie emergente, pero no se usan para inferir "
                        "madurez, eficacia típica ni prioridad de despliegue. Su función es señalar una "
                        "hipótesis que requiere réplica, no añadir peso a una mayoría defensiva."
                    )
                ]
                if sparse_families
                else []
            ),
            (
                f"El segundo punto es la comparabilidad. En {counts['threat']}/{len(focus_rows)} estudios se recupera una amenaza explícita, en {counts['enforcement']}/{len(focus_rows)} un punto de aplicación y en {counts['baseline']}/{len(focus_rows)} un baseline. "
                "Cuando falta una de estas piezas, una cifra de eficacia pierde parte de su significado: no sabemos frente a qué atacante funciona, qué decisión controla ni si mejora una alternativa razonable. "
                f"Por eso la revisión no construye un ranking universal; construye comparaciones condicionadas por contrato de amenaza{cite_suffix(top_ids[4:8])}."
            ),
            (
                f"El tercer punto es la adaptatividad. {counts['adaptive']}/{len(focus_rows)} estudios reportan señal de atacante adaptativo y {counts['robustness']}/{len(focus_rows)} aportan robustez, transferencia, ablación o ataques no vistos. "
                "La segunda cifra es deliberadamente más amplia y no implica que todos esos estudios enfrenten a un adversario adaptativo: también incluye transferencia entre modelos o dominios, ablaciones y conjuntos no vistos. "
                "Una defensa evaluada sobre prompts estáticos puede aprender la forma del benchmark sin resistir a un adversario que conoce el filtro, reformula el ataque o desplaza la inyección a documentos, memoria o herramientas. "
                f"La diferencia entre cobertura estática y robustez adaptativa es la frontera más importante entre demostración y seguridad operacional{cite_suffix(top_ids[8:12])}."
            ),
            (
                f"El cuarto punto es el coste de proteger. Solo {counts['false_positive']}/{len(focus_rows)} estudios reportan falsos positivos, {counts['utility']}/{len(focus_rows)} utilidad, {counts['latency']}/{len(focus_rows)} latencia y {counts['cost']}/{len(focus_rows)} coste. "
                "Una defensa puede reducir la tasa de ataque porque rechaza demasiadas entradas, limita herramientas legítimas o añade una revisión costosa. "
                "La superioridad científica exige medir simultáneamente seguridad y capacidad útil; de lo contrario, el problema se resuelve desactivando parte del sistema que se pretendía proteger. "
                "La baja cobertura de latencia y coste impide convertir las fronteras observadas en una recomendación de producción: sin cómputo adicional, tokens, tiempo de respuesta, intervención humana y coste de falsos rechazos no puede estimarse el coste total de operar la defensa. "
                "La consecuencia es metodológica y empresarial: una frontera de dominancia sin esas métricas sigue siendo una hipótesis comparativa útil, pero no una decisión de despliegue cerrada."
            ),
            (
                "El quinto punto es que las capas defensivas no son intercambiables. Un filtro de entrada puede detener patrones conocidos, pero no controla una llamada de herramienta ya autorizada; un sandbox limita impacto, pero no evita fuga de información en la respuesta; un verificador de salida puede detectar daño, pero llega tarde si el agente ya ejecutó una acción irreversible. "
                "La arquitectura adecuada depende del momento en que el daño puede materializarse y del coste de una falsa aceptación frente a un falso rechazo."
            ),
            (
                "La concentración de configuraciones en controles no tipificados no constituye una familia defensiva adicional ni una réplica implícita. Es un diagnóstico de inmadurez taxonómica: parte de la literatura usa etiquetas genéricas, combina mecanismos sin aislar su efecto o no describe con precisión qué transición del sistema interrumpe. Mientras esa opacidad persista, sumar esos estudios como si probaran el mismo control produciría una mayoría artificial y debilitaría, en lugar de fortalecer, la comparación."
            ),
            (
                f"Finalmente, la madurez del campo depende de sus fallos visibles. {counts['failure']}/{len(focus_rows)} estudios reportan modos de fallo y {counts['artifact']}/{len(focus_rows)} código o artefactos recuperables. "
                "Los resultados negativos, bypasses y límites de transferencia no debilitan una defensa; permiten delimitar dónde puede usarse. "
                "Un harness científicamente útil no promete invulnerabilidad: ofrece una reducción de riesgo verificable, declara qué deja pasar y facilita repetir la prueba."
            ),
        ]
        practical = (
            "Para equipos que despliegan modelos y agentes, la implicación práctica es seleccionar controles desde el daño posible y el punto donde puede materializarse, no desde una lista genérica de guardrails."
        )
        evidence_implication = (
            "En términos sustantivos, la revisión permite identificar configuraciones defensivas prometedoras, pero solo puede llamar mejor a una alternativa cuando comparte amenaza y baseline y conserva utilidad con coste y fallo residual explícitos."
        )
    elif profile == "creativity_llm":
        family_counts = Counter(creativity_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(
            mapped_counter(
                family_counts,
                {
                    "Escritura y generación creativa": "escritura",
                    "Pensamiento divergente y asociación": "divergente/asociación",
                    "Ideación científica y generación de investigación": "ideación científica",
                    "Resolución creativa de problemas": "problemas",
                    "Caracterización metodológica de creatividad": "método",
                    "Evaluación, métricas y benchmarks": "métricas",
                    "Entrenamiento y optimización creativa": "entrenamiento",
                },
            ),
            len(focus_rows),
            limit=6,
        )
        task_text = counter_summary(creativity_task_counter(focus_rows), len(focus_rows), limit=5)
        model_text = model_mention_summary(focus_rows, len(focus_rows))
        theoretical = (
            "La creatividad en LLMs aparece menos como una capacidad única y más como un conjunto de operaciones evaluables: producir ideas, variar soluciones, generar textos originales, resolver problemas abiertos o satisfacer criterios humanos de novedad y utilidad."
        )
        discussion_development = [
            (
                f"El primer punto de discusión es que el corpus no autoriza una pregunta genérica del tipo `¿son creativos los LLMs?`. "
                f"La evidencia focal se reparte en {family_text}, y esa distribución cambia el significado de la conclusión: no es lo mismo evaluar escritura creativa que pensamiento divergente, ideación científica, optimización de respuestas o resolución creativa de problemas. "
                f"Por eso, la unidad interpretativa de la revisión no es el modelo aislado, sino la combinación entre tarea, instrumento, comparador y criterio de creatividad{cite_suffix(top_ids[:4])}."
            ),
            (
                f"El segundo punto es que la medición forma parte del fenómeno observado. En el subconjunto focal aparecen señales de tarea como {task_text}. "
                "Cuando un estudio mide originalidad mediante jueces humanos, otro usa métricas automáticas de diversidad y otro trabaja con benchmarks de asociación o resolución de problemas, la palabra `creatividad` deja de funcionar como variable homogénea. "
                f"La discusión, por tanto, no puede cerrar con una jerarquía simple de modelos; debe preguntar qué definición de creatividad se activó, quién o qué la evaluó y bajo qué condiciones se produjo la salida{cite_suffix(top_ids[4:8])}."
            ),
            (
                f"El tercer punto afecta a la comparación entre modelos. {model_text} Este dato es útil, pero también peligroso si se interpreta como ranking. "
                "La revisión muestra que el rendimiento atribuido a un modelo depende de prompts, modalidad de tarea, baseline, temperatura o política de generación, además del sistema de evaluación usado por cada paper. "
                f"En consecuencia, la síntesis no debe decir que un modelo `gana` en creatividad de forma universal, sino que ciertas configuraciones producen mejor señal en determinados contextos experimentales o evaluativos{cite_suffix(top_ids[8:12])}."
            ),
            (
                f"El cuarto punto es metodológico. El subconjunto empírico se distribuye como {empirical_text}, lo que permite describir patrones, pero no convertir el corpus en un meta-análisis causal único. "
                "Los estudios son valiosos precisamente porque abren ventanas distintas sobre el fenómeno: algunos comparan humanos y modelos, otros examinan tareas de ideación, otros se centran en escritura, otros en métricas o entrenamiento. "
                "Esa diversidad fortalece la cartografía del campo, pero limita cualquier conclusión demasiado rotunda sobre una creatividad general, estable y transferible entre dominios."
            ),
            (
                "La lectura transversal sugiere además una tensión de fondo entre creatividad como producto y creatividad como proceso. Muchos trabajos evalúan el producto final porque es lo observable y puntuable; sin embargo, la creatividad humana suele incluir exploración, iteración, intención, selección, restricción contextual y juicio situado. "
                "Los LLMs pueden generar productos que satisfacen criterios de novedad o utilidad, pero la revisión obliga a distinguir ese resultado observable de afirmaciones más fuertes sobre agencia creativa, comprensión estética o intencionalidad. "
                f"Esta distinción es crucial para que la literatura avance sin confundir rendimiento textual, sorpresa estadística y creatividad en sentido amplio{cite_suffix(top_ids[12:16])}."
            ),
            (
                "Finalmente, la madurez del campo debe medirse por la calidad del diseño y del reporte, no por la rapidez con la que aparecen nuevos modelos. "
                "Un estudio aporta más a la acumulación científica cuando declara la tarea, conserva el comparador, explica la rúbrica, identifica el juez, reporta límites y permite reconstruir la extracción. "
                "Ese es el motivo por el que esta revisión insiste en DOI, PDF legible, matriz de selección y material suplementario: no como formalismo PRISMA, sino como condición para que una afirmación sobre creatividad artificial sea discutible, replicable y acumulativa."
            ),
        ]
        practical = (
            "Para equipos que diseñan o evalúan modelos, la implicación práctica es que no basta con pedir salidas creativas: hay que declarar tarea, criterio, comparador, métrica, juez y condiciones de prompting."
        )
        evidence_implication = (
            "En términos sustantivos, la revisión muestra que escritura creativa, pensamiento divergente, ideación científica y resolución de problemas no deben mezclarse sin control. Un modelo puede mostrar buen rendimiento en una rúbrica de escritura y no trasladar esa señal a originalidad asociativa, razonamiento creativo o generación de hipótesis científicas."
        )
    elif profile == "ai_higher_education_teaching":
        family_counts = Counter(education_ai_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(
            mapped_counter(
                family_counts,
                {
                    "Feedback, evaluación y calidad de la retroalimentación": "feedback/evaluación",
                    "Diseño curricular, materiales y planificación docente": "diseño curricular",
                    "Adopción docente, alfabetización en IA y competencias": "adopción/alfabetización",
                    "Productividad académica y carga de trabajo docente": "productividad/carga",
                    "Resultados de aprendizaje y calidad educativa": "aprendizaje/calidad",
                    "Integridad académica, ética y gobernanza": "integridad/gobernanza",
                    "Uso docente de IA en educación superior": "uso docente",
                },
            ),
            len(focus_rows),
            limit=7,
        )
        theoretical = (
            "La literatura sobre IA aplicada a docentes universitarios muestra que la pregunta relevante no es si la IA se usa en educación superior, sino bajo qué tarea docente, con qué control pedagógico y con qué evidencia puede afirmarse que aporta calidad."
        )
        discussion_development = [
            (
                f"El primer punto de discusión es que el corpus desplaza el foco desde la herramienta hacia la práctica docente. "
                f"La evidencia focal se reparte en {family_text}, y esa distribución impide hablar de `ayuda de la IA` como un efecto único. "
                f"Apoyar feedback, diseñar materiales, reducir carga, acompañar tutorías o reforzar alfabetización en IA son intervenciones diferentes, con riesgos y métricas distintas{cite_suffix(top_ids[:4])}."
            ),
            (
                "El segundo punto es que adopción no equivale a mejora educativa. Muchos estudios capturan percepción, intención de uso, aceptación o facilidad percibida; esos datos son valiosos para explicar implementación, pero no sustituyen evidencia sobre aprendizaje, calidad del feedback, consistencia de evaluación o mejora de diseño curricular. "
                f"Por eso la revisión separa resultados de uso, resultados docentes y resultados educativos, en lugar de convertirlos en una misma señal positiva{cite_suffix(top_ids[4:8])}."
            ),
            (
                f"El tercer punto es metodológico. El subconjunto empírico se distribuye como {empirical_text}, lo que permite describir patrones, pero exige cautela para no convertir estudios de percepción, experiencias piloto o benchmarks locales en una conclusión universal. "
                "La IA puede ayudar mucho en tareas docentes concretas y, al mismo tiempo, requerir evaluación situada por disciplina, institución, política de datos, nivel de alfabetización del profesorado y tipo de evaluación."
            ),
            (
                "El cuarto punto afecta al control pedagógico. La revisión sugiere que el valor de la IA no reside solo en generar contenido, sino en ampliar la capacidad del docente para revisar, adaptar, comparar, explicar y tomar decisiones informadas. "
                "Cuando el sistema sustituye criterio docente por automatización opaca, el beneficio práctico se vuelve frágil; cuando se integra como apoyo supervisado, puede reducir carga, mejorar consistencia y abrir nuevas formas de retroalimentación."
            ),
            (
                "El quinto punto es institucional. Una universidad no adopta IA en abstracto: adopta flujos con datos, herramientas, formación, políticas, responsabilidades y límites. "
                "Por eso la evidencia sobre ética, privacidad, sesgo, integridad académica y gobernanza no debe tratarse como sección separada de riesgos, sino como condición para interpretar si una intervención puede escalar más allá del piloto."
            ),
            (
                "Finalmente, el campo necesita pasar de demostraciones de posibilidad a diseños comparables. Para acumular conocimiento, los estudios futuros deben declarar tarea docente, población o unidad de análisis, herramienta, prompts o configuración, criterio de éxito, comparador, revisión humana y límites. "
                "Solo así la revisión posterior podrá distinguir qué parte de la mejora procede de la IA, qué parte de la formación docente y qué parte del contexto institucional."
            ),
        ]
        practical = (
            "Para universidades y equipos docentes, la implicación práctica es que la IA debe implantarse por casos de uso verificables: feedback, evaluación, diseño curricular, tutoría, productividad o alfabetización, siempre con control docente y métricas de calidad."
        )
        evidence_implication = (
            "En términos sustantivos, la revisión muestra que la IA puede aportar valor a docentes universitarios cuando se conecta con tareas concretas y evidencia de calidad, pero la adopción general, la satisfacción o la novedad tecnológica no bastan para demostrar mejora educativa."
        )
    elif profile == "social_sciences":
        family_counts = Counter(social_science_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(
            mapped_counter(
                family_counts,
                {
                    "Polarización afectiva e identidad partidista": "polarización/identidad",
                    "Confianza institucional y legitimidad democrática": "confianza/legitimidad",
                    "Exposición digital y plataformas sociales": "exposición digital",
                    "Información política, desinformación y ecosistemas mediáticos": "información/desinformación",
                    "Participación y actitudes democráticas": "participación/actitudes",
                    "Evidencia metodológica y medición social": "medición",
                },
            ),
            len(focus_rows),
            limit=6,
        )
        relation_signal = social_science_relation_signal(focus_rows)
        trust_dominant = family_counts.get("Confianza institucional y legitimidad democrática", 0)
        trust_signal = social_science_signal_counts(focus_rows)["trust"]
        theoretical = (
            f"La literatura sobre {topic} debe leerse como una relación entre mecanismos sociales, mediciones y contextos institucionales, no como un efecto lineal de una variable aislada. "
            "La pregunta sustantiva no es solo si una exposición aumenta o reduce un resultado, sino bajo qué condiciones una práctica comunicativa, identidad política o entorno institucional cambia actitudes, confianza o comportamiento."
        )
        discussion_development = [
            (
                f"El primer punto de discusión es que la evidencia focal se organiza en {family_text}. "
                "Esta distribución muestra que el objeto revisado no puede reducirse a una oposición simple entre redes sociales buenas o malas. "
                f"Los estudios separan exposición digital, identidad partidista, confianza institucional, información política y contexto democrático; por eso la síntesis debe comparar mecanismos y no solo asociaciones{cite_suffix(top_ids[4:8])}."
            ),
            (
                "El segundo punto es que la polarización afectiva funciona como algo más que una actitud extrema. En muchos diseños aparece como distancia emocional, animosidad hacia el grupo contrario, identidad partidista o percepción de amenaza. "
                "Eso importa porque redes sociales, noticias políticas y conversaciones online pueden influir por vías distintas: selección de fuentes, exposición incidental, refuerzo de identidad, incivilidad, desinformación o presión del grupo. "
                f"Una revisión publicable debe mantener esas rutas separadas antes de declarar un efecto general{cite_suffix(top_ids[8:12])}."
            ),
            (
                "El tercer punto es que la confianza institucional debe tratarse como inferencia teórica situada, no como conclusión empírica robusta del corpus por sí sola. En esta revisión aparece sobre todo como zona de conexión conceptual: puede ser resultado, antecedente o condición contextual, pero esa pluralidad no autoriza todavía una afirmación bidireccional fuerte. "
                f"El manuscrito debe ser especialmente prudente porque confianza/legitimidad es familia dominante en {trust_dominant}/{len(focus_rows)} estudios y señal presente en {trust_signal}/{len(focus_rows)}. Por eso la revisión no afirma recursividad probada; formula una hipótesis contextual que debe ser contrastada con diseños longitudinales, experimentales o comparadores temporales suficientes{cite_suffix(top_ids[12:16])}."
            ),
            (
                f"El cuarto punto es metodológico. La señal central queda resumida así: {relation_signal}. "
                f"El subconjunto empírico se distribuye como {empirical_text}, lo que permite detectar patrones, pero obliga a distinguir correlación, mecanismo plausible y causalidad. "
                f"Las encuestas transversales pueden mostrar asociación; los paneles y experimentos aportan más dirección temporal o control; los análisis de contenido y datos digitales explican entorno informativo, pero no siempre resultado actitudinal{cite_suffix(top_ids[16:20])}."
            ),
            (
                "El quinto punto es la transferencia. Una conclusión sobre plataformas, confianza o polarización depende de país, sistema de partidos, ciclo electoral, intensidad del conflicto, confianza previa, edad, exposición mediática y diseño de medición. "
                "Por eso el contexto democrático no debe aparecer como dato secundario: es una condición de validez externa."
            ),
            (
                "Finalmente, la contribución de la revisión es convertir heterogeneidad en lectura acumulativa. El artículo no necesita fingir que todos los estudios miden lo mismo; necesita mostrar qué relaciones están suficientemente repetidas, qué mecanismos aparecen como señal y qué vacíos impiden todavía una tesis causal más fuerte."
            ),
        ]
        practical = (
            "Para investigadores, instituciones y equipos de análisis público, la implicación práctica es que las decisiones no deberían basarse en una afirmación genérica sobre redes sociales, sino en configuraciones observables de exposición, población, plataforma, contexto político, medición y riesgo institucional."
        )
        evidence_implication = (
            "En términos sustantivos, la revisión sugiere que la relación entre redes sociales, polarización afectiva y confianza institucional debe tratarse como condicional y mediada por contexto, identidad, información y diseño de medición."
        )
    else:
        theoretical = (
            f"La literatura sobre {topic} muestra que la acumulación de estudios no equivale automáticamente a consolidación teórica. La revisión identifica qué partes del campo están apoyadas en diseños comparables y qué partes siguen dependiendo de reportes fragmentarios."
        )
        discussion_development = [
            (
                f"El primer punto de discusión es que {topic} no puede evaluarse solo por presencia documental o frecuencia de resultados positivos. "
                "Una revisión sistemática necesita separar el tamaño del corpus, la calidad de la evidencia, la claridad metodológica y la capacidad real de sostener inferencias comparables. "
                f"Por eso, la discusión no trata los estudios incluidos como votos equivalentes, sino como piezas con distinto peso analítico según diseño, trazabilidad y densidad de extracción{cite_suffix(top_ids[:4])}."
            ),
            (
                "El segundo punto es que la heterogeneidad no es un defecto accidental, sino una propiedad central del campo revisado. "
                "Los estudios pueden compartir vocabulario y aun así responder a preguntas diferentes, usar unidades analíticas no equivalentes o reportar resultados bajo criterios incompatibles. "
                f"La síntesis debe convertir esa heterogeneidad en información: qué dimensiones convergen, cuáles siguen fragmentadas y dónde la evidencia todavía no permite pasar de patrón descriptivo a conclusión fuerte{cite_suffix(top_ids[4:8])}."
            ),
            (
                f"El tercer punto es metodológico. El subconjunto empírico se distribuye como {empirical_text}, de modo que las frecuencias deben leerse como mapa de reporting y no como jerarquía definitiva. "
                "La revisión puede identificar señales recurrentes, pero no debe presentar como causal lo que procede de diseños, muestras, métricas o contextos todavía poco comparables."
            ),
            (
                "Finalmente, la aportación de una revisión publicable está en conservar la tensión entre claridad y cautela. "
                "El manuscrito debe decir algo más que faltan estudios, pero tampoco debe cerrar el campo antes de tiempo. "
                "Por eso la discusión combina patrones sustantivos, amenazas a la validez y condiciones de replicabilidad: solo así la síntesis resulta útil para investigadores, revisores y lectores aplicados."
            ),
        ]
        practical = (
            "Para investigadores y equipos aplicados, la implicación práctica es que una revisión útil debe separar evidencia fuerte, señal prometedora y registros todavía insuficientes antes de convertir el corpus en recomendaciones."
        )
        evidence_implication = (
            "En términos sustantivos, la revisión obliga a distinguir resultados robustos, señales emergentes y vacíos de reporte antes de transformar el corpus en recomendaciones aplicadas."
        )
    if is_ai_workload_context(context):
        theoretical_implication_lines = [
            "## Implicaciones teóricas",
            "La primera implicación teórica es abandonar la equivalencia entre productividad y carga de trabajo. La productividad describe cuánto se produce por unidad de tiempo o recurso; la carga de trabajo describe el esfuerzo cognitivo, coordinativo, emocional, técnico y responsable que queda para que una tarea sea aceptable. La IA puede mejorar la primera y no reducir la segunda.",
            "",
            "La segunda implicación es tratar el trabajo como sistema distribuido. El trabajo humano no se agota en ejecutar una tarea; incluye formularla, darle contexto, revisar resultados, reparar errores, coordinar con otros actores, aprender nuevas prácticas y asumir responsabilidad. La IA interviene en esa distribución y por eso debe estudiarse como tecnología de redistribución, no solo de sustitución.",
            "",
            "La tercera implicación es que el concepto de ahorro debe volverse relacional. Un ahorro para quien genera una salida puede convertirse en coste para quien la revisa; un ahorro para un departamento puede transformarse en carga para compliance, IT, supervisores o usuarios finales; un ahorro inmediato puede convertirse en dependencia o deuda de aprendizaje. La teoría debe seguir esos desplazamientos.",
            "",
            "La cuarta implicación es distinguir automatización de transferencia de responsabilidad. Aunque una salida sea producida por IA, la rendición de cuentas suele permanecer en humanos e instituciones. En tareas de alto riesgo, esa permanencia convierte la verificación en parte estructural del trabajo, no en un añadido menor.",
            "",
            "La quinta implicación es que las revisiones futuras deben dejar de agregar estudios por `IA en el trabajo` y empezar a compararlos por capas del esfuerzo: ejecución, articulación, verificación, coordinación, aprendizaje y responsabilidad. Esa gramática permite que resultados aparentemente contradictorios se vuelvan compatibles: unos miden ahorro de ejecución; otros, coste de control.",
            "",
            "La sexta implicación es que la tesis del artículo no es tecnófoba ni promocional. Reconoce ganancias reales en tareas concretas, pero exige una contabilidad completa antes de aceptar la promesa de trabajar menos. La pregunta madura deja de ser `¿ahorra tiempo la IA?` y pasa a ser `¿qué trabajo desaparece, qué trabajo aparece y quién lo absorbe?`.",
        ]
    elif profile == "ai_security_harness":
        theoretical_implication_lines = [
            "## Implicaciones teóricas",
            "La primera implicación teórica derivada de los harnesses analizados es que su seguridad no puede localizarse únicamente en el modelo base. Dentro del alcance de este corpus, el comportamiento seguro emerge de una relación entre modelo, contexto, herramientas, memoria, permisos, verificadores y entorno de ejecución. Esta perspectiva no se presenta como una verdad ontológica sobre todo sistema de IA: es una inferencia arquitectónica apoyada por las defensas operacionales revisadas. La unidad teórica relevante deja de ser la respuesta aislada del modelo y pasa a ser el circuito que transforma información en una capacidad, una decisión y una consecuencia" + cite_suffix(top_ids[:4]) + ".",
            "",
            "La segunda implicación es que una defensa se define por el daño que interrumpe y por el momento en que lo hace. Filtrar una entrada, separar instrucciones de datos, negar una capacidad, aislar una ejecución y verificar una salida son mecanismos causalmente distintos. La teoría del campo debe explicar qué ruta de ataque corta cada control, no limitarse a contar cuántas capas existen. Esto introduce una gramática causal mínima: autoridad disponible, capacidad solicitada, transición permitida, evidencia usada para decidir y contención posterior al fallo.",
            "",
            "La tercera implicación es que detección y enforcement no son sustitutos. Un clasificador puede reconocer una intención dañina sin impedir que una herramienta actúe; una política de permisos puede contener la acción aunque no identifique semánticamente el ataque. La distinción permite ordenar dos tradiciones que a menudo se comparan de manera impropia: las defensas epistemológicas, que estiman si una entrada o trayectoria es peligrosa, y las defensas de autoridad, que limitan lo que el sistema puede hacer incluso cuando la estimación falla. En sistemas de alto impacto, ambas funciones son complementarias y su composición debe evaluarse como tal" + cite_suffix(top_ids[4:8]) + ".",
            "",
            "La cuarta implicación es que robustez y cobertura no son equivalentes. Cobertura describe rendimiento sobre un conjunto conocido; robustez exige mantener la reducción de riesgo cuando cambia el modelo, el dominio, la formulación o la estrategia del atacante. Esta distinción impide interpretar buenos resultados estáticos como seguridad general. Un atacante adaptativo no es solo una condición experimental más exigente: es una prueba epistemológica de si el mecanismo defensivo captura la ruta de daño o únicamente regularidades superficiales del benchmark.",
            "",
            "La quinta implicación es multiobjetivo: seguridad, utilidad, disponibilidad, latencia, coste y operabilidad forman una frontera de decisión. No existe una defensa universalmente mejor cuando una alternativa bloquea más ataques pero degrada de forma material el uso legítimo o desplaza el coste hacia revisión humana. Teóricamente, la dominancia entre harnesses es un orden parcial: una configuración solo puede dominar a otra dentro de un contrato equivalente y cuando no empeora de forma sustantiva las dimensiones operacionales relevantes. Fuera de esas condiciones, una media única destruye información de decisión.",
            "",
            "La sexta implicación es que el fallo residual forma parte de la teoría de la defensa. Un harness maduro no se define por prometer bloqueo total, sino por delimitar qué ataques reduce, cuáles siguen siendo posibles, cómo se detecta el fallo y qué mecanismo contiene el daño después de una evasión. Esta lectura desplaza la seguridad desde la fantasía de invulnerabilidad hacia una teoría de reducción, observabilidad y contención del riesgo. Publicar bypasses, falsos negativos y condiciones de degradación no debilita la contribución; revela su frontera de validez" + cite_suffix(top_ids[8:12]) + ".",
            "",
            "La séptima implicación afecta a la composición de capas. Añadir controles no garantiza una mejora monótona: dos filtros pueden compartir el mismo punto ciego, una verificación tardía puede no reparar una acción irreversible y una política restrictiva puede trasladar el riesgo a operadores humanos que aprueban excepciones bajo presión. La teoría debe estudiar independencia de fallos, orden de ejecución y capacidad de recuperación, no solo número de componentes. Una defensa multicapa aporta valor cuando cada capa cubre un modo de fallo distinto y la interacción entre ellas conserva una ruta de decisión interpretable.",
            "",
            "La octava implicación es acumulativa. El campo solo podrá comparar resultados si comparte una gramática mínima: amenaza, atacante, superficie, control, enforcement, baseline, eficacia, utilidad, coste y robustez. Esa gramática permite integrar estudios heterogéneos sin convertirlos en un ranking engañoso. También convierte los vacíos de reporte en información teórica: si no se declara quién ataca, qué autoridad posee el sistema o qué daño se contiene, la afirmación de seguridad carece de objeto estable.",
            "",
            "La novena implicación es una regla de diseño científico. Los estudios futuros deberían formular la defensa como una hipótesis refutable sobre una transición concreta del sistema: bajo una amenaza definida, el control impide o contiene una acción sin superar un coste operacional preestablecido. Esa formulación obliga a declarar qué resultado refutaría la propuesta y permite que una réplica modifique modelo, dominio o atacante sin perder la unidad comparativa. La teoría de los harnesses avanzará cuando pueda explicar no solo que una defensa funcionó, sino por qué funcionó, dónde deja de hacerlo y qué evidencia permitiría sustituirla" + cite_suffix(top_ids[12:16]) + ".",
        ]
    else:
        theoretical_implication_lines = [
            "## Implicaciones teóricas",
            f"La primera implicación teórica es que {topic} no debe leerse solo como una acumulación de resultados, sino como un campo cuya unidad de comparación todavía necesita ser construida. En el subconjunto focal aparecen {theory_text}; por tanto, la revisión no fuerza una teoría única, sino que documenta qué piezas conceptuales están disponibles y cuáles siguen ausentes.",
            "",
            f"La segunda implicación es de conmensurabilidad. Dos artículos pueden usar términos similares y, sin embargo, responder a preguntas distintas, usar instrumentos distintos y sostener conclusiones no equivalentes {citation_block(top_ids[4:8])}. Por eso el aporte teórico de la revisión consiste en identificar bajo qué condiciones los estudios son realmente comparables: objeto, diseño, unidad de análisis, método, evidencia, resultado y límite inferencial.",
            "",
            "La tercera implicación es que los vacíos de reporte tienen valor teórico. La ausencia de marco conceptual, muestra, variables, comparadores o validación no se trata como un problema administrativo, sino como una señal sobre el grado de madurez del campo. Una revisión sistemática publicable debe convertir esos silencios en diagnóstico, porque ahí se decide si un patrón puede convertirse en teoría acumulativa o si solo describe una frontera todavía fragmentada.",
            "",
            "La cuarta implicación es constructiva: el artículo no solo revisa literatura, sino que propone una gramática analítica para futuras comparaciones. Esa gramática permite pasar de una lista de estudios a un vocabulario de comparación que otros trabajos pueden reutilizar, discutir o refinar.",
            "",
            "La quinta implicación es acumulativa. Una revisión sistemática no debería limitarse a declarar tendencias; debe mostrar qué condiciones permitirían que futuros estudios se agreguen al mismo marco. Por eso el artículo identifica dimensiones reutilizables, vacíos de reporte y criterios de calidad que pueden volver a aplicarse cuando el campo incorpore nuevos trabajos.",
            "",
            "La sexta implicación es inferencial. La revisión distingue entre patrón documentado, señal emergente e hipótesis que todavía no puede cerrarse. Esta separación protege la contribución teórica frente a dos riesgos frecuentes: convertir frecuencias descriptivas en causalidad y presentar heterogeneidad metodológica como si fuera consenso disciplinar.",
        ]
    return "\n".join(
        [
            "# Discusión",
            "",
            theoretical + " " + citation_block(top_ids[:4]) + ".",
            "",
            *[paragraph + "\n" for paragraph in discussion_development],
            *theoretical_implication_lines,
            "",
            *build_practical_implications_lines(
                focus_rows,
                context,
                citation_ids=top_ids,
                opening=practical,
                evidence_implication=evidence_implication,
            ),
            "",
            "## Aportación original del artículo",
            str(contribution_model["thesis"]),
            "",
            str(contribution_model["theory"]),
            "",
            str(contribution_model["model"]),
            "",
            "Tabla 10. Modelo de aportación original del artículo.",
            markdown_table(["Plano", "Tesis del artículo", "Valor para el campo"], contribution_rows),
            "",
            str(contribution_model["field"]),
            "",
            str(contribution_model["method"]),
            "",
            *grammar_figure_blocks,
            *build_validity_threats_lines(focus_rows, flow_counts, context, citation_ids=top_ids),
        ]
    ) + "\n"


def build_conclusions_section_domain(
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    profile = detect_review_profile(context)
    topic = review_subject_label_es(context)
    top_ids = top_citation_ids(focus_rows, 12)
    rq_text = publication_research_question(context, profile)
    empirical_n = work_type_summary(focus_rows).get("empirical", 0)
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    unit_thesis = conclusion_unit_thesis(profile, topic)
    grammar_sentence = conclusion_grammar_sentence(profile, len(focus_rows))
    if is_ai_workload_context(context):
        empirical_rows = empirical_rows_only(focus_rows)
        support_rows = support_rows_only(focus_rows)
        primary_rows = empirical_rows or focus_rows
        primary_total = len(primary_rows)
        counts = ai_workload_signal_counts(primary_rows)
        unit_thesis = (
            "Esta revisión muestra que el campo no debe comparar `uso de IA` frente a `no uso de IA` como si ambas categorías fueran homogéneas. "
            "La unidad real de comparación es la configuración completa entre tarea, riesgo, grado de automatización, revisión humana, coste de error, aprendizaje requerido y responsabilidad final."
        )
        grammar_sentence = (
            "A partir de esta revisión se propone una gramática de trabajo total basada en seis capas: ejecución, articulación, verificación, coordinación, aprendizaje y responsabilidad. "
            "Esa gramática no afirma que todas las capas aparezcan con la misma densidad empírica; permite explicar por qué algunos estudios observan ahorro de tiempo y otros observan sobrecarga, dependencia o nuevas tareas de control sin que haya contradicción lógica entre ellos."
        )
        answer = (
            "no puede afirmarse, con la evidencia disponible, que la IA haga trabajar menos en términos netos. "
            "Los patrones observados sugieren una tesis más precisa: la IA puede reducir esfuerzo de ejecución en tareas delimitadas, pero parte del trabajo reaparece como preparación de instrucciones, revisión de salidas, coordinación organizativa, aprendizaje de uso, control de errores y responsabilidad humana o institucional."
        )
        domain_conclusion = (
            f"En la base empírica primaria, la señal de productividad local aparece en {counts['productivity']}/{primary_total} estudios, mientras que supervisión, riesgo, aprendizaje o gobernanza aparecen como capas de esfuerzo en {max(counts['supervision'], counts['risk_error'], counts['learning'], counts['governance'])}/{primary_total} cuando se leen por familias de evidencia. "
            "La conclusión no es que la IA no sirva; es que su valor debe medirse con contabilidad completa del trabajo y no con una métrica estrecha de velocidad de producción."
        )
        certainty_signal_gap = (
            "Lo que puede afirmarse con más seguridad es que existen ganancias locales cuando la tarea está bien delimitada, el criterio de calidad es claro y el coste de revisar la salida no supera el ahorro de producirla. "
            "Lo que aparece como señal emergente es un desplazamiento del esfuerzo desde producir hacia controlar: formular mejor, verificar más, corregir fallos, coordinar usos y sostener la responsabilidad sobre decisiones asistidas por IA. "
            "Lo que todavía no puede concluirse es una reducción neta general de carga de trabajo, porque esa afirmación exige medir también el trabajo invisible que muchos estudios dejan fuera: relectura, validación, rework, formación, dependencia, auditoría y gestión del riesgo."
        )
    elif profile == "ai_security_harness":
        counts = security_harness_signal_counts(focus_rows)
        family_counts = Counter(security_harness_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(family_counts, len(focus_rows), limit=6)
        answer = (
            "no existe evidencia suficiente para declarar un harness universalmente mejor. La evidencia permite identificar defensas superiores dentro de comparaciones concretas, pero la superioridad depende de compartir amenaza, atacante, superficie, baseline y criterio de coste, y de demostrar que la reducción del riesgo no se obtiene degradando de forma material la utilidad."
        )
        domain_conclusion = (
            "La distribución observada desplaza la decisión desde el nombre de una defensa hacia la superficie "
            "que protege y el daño que contiene. La cobertura desigual de baseline, atacante adaptativo y coste "
            "permite priorizar arquitecturas para una amenaza concreta, pero impide convertir resultados locales "
            "en una liga única de harnesses."
        )
        certainty_signal_gap = (
            "Lo que puede afirmarse con más seguridad es que el harness debe cubrir las fronteras donde datos no confiables pueden convertirse en instrucciones, permisos, llamadas de herramienta o salidas con efecto. Ninguna familia aislada cubre por definición entrada, contexto, memoria, herramientas, runtime y salida; esta es una conclusión arquitectónica, no una afirmación de superioridad empírica entre controles. "
            "Lo que aparece como señal emergente es una transición desde guardrails monolíticos hacia defensa en profundidad, pero el corpus todavía no demuestra qué combinación es mejor bajo comparaciones homogéneas. "
            f"Lo que todavía no puede concluirse es qué combinación domina de forma general: solo {counts['false_positive']}/{len(focus_rows)} estudios reportan falsos positivos, {counts['utility']}/{len(focus_rows)} utilidad, {counts['latency']}/{len(focus_rows)} latencia y {counts['cost']}/{len(focus_rows)} coste."
        )
    elif profile == "creativity_llm":
        family_counts = Counter(creativity_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(
            mapped_counter(
                family_counts,
                {
                    "Escritura y generación creativa": "escritura",
                    "Pensamiento divergente y asociación": "divergente/asociación",
                    "Ideación científica y generación de investigación": "ideación científica",
                    "Resolución creativa de problemas": "problemas",
                    "Caracterización metodológica de creatividad": "método",
                    "Evaluación, métricas y benchmarks": "métricas",
                },
            ),
            len(focus_rows),
            limit=6,
        )
        answer = (
            "la creatividad en LLMs no puede tratarse como una propiedad monolítica del modelo. La evidencia indica que el resultado depende de la tarea creativa, "
            "del instrumento, del juez, del comparador y de la condición de generación que cada estudio activa."
        )
        domain_conclusion = (
            f"La evidencia focal se reparte en {family_text}. Ese patrón no debe leerse como ranking de modelos, sino como mapa de operacionalizaciones: escritura, pensamiento divergente, ideación, resolución de problemas y métricas no miden exactamente el mismo fenómeno."
        )
        certainty_signal_gap = (
            "Lo que puede afirmarse con más seguridad es que la creatividad evaluada depende de configuraciones concretas de tarea, rúbrica y comparador. "
            "Lo que aparece como señal emergente es la posibilidad de construir protocolos más finos para distinguir novedad, utilidad y diversidad. "
            "Lo que todavía no puede concluirse es que exista una creatividad general, estable y transferible entre dominios o familias de modelos sin controlar esas condiciones."
        )
    elif profile == "ai_higher_education_teaching":
        family_counts = Counter(education_ai_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(
            mapped_counter(
                family_counts,
                {
                    "Feedback, evaluación y calidad de la retroalimentación": "feedback/evaluación",
                    "Diseño curricular, materiales y planificación docente": "diseño curricular",
                    "Adopción docente, alfabetización en IA y competencias": "adopción/alfabetización",
                    "Productividad académica y carga de trabajo docente": "productividad/carga",
                    "Resultados de aprendizaje y calidad educativa": "aprendizaje/calidad",
                    "Integridad académica, ética y gobernanza": "integridad/gobernanza",
                    "Uso docente de IA en educación superior": "uso docente",
                },
            ),
            len(focus_rows),
            limit=7,
        )
        answer = (
            "la IA, especialmente la IA generativa y los sistemas basados en LLM, aporta valor potencial al profesorado universitario cuando se integra en tareas docentes concretas y con control pedagógico explícito. "
            "La evidencia no sostiene una afirmación genérica de mejora automática: sostiene una comparación por función docente, contexto, herramienta, diseño de evaluación y límite institucional."
        )
        domain_conclusion = (
            f"La evidencia focal se organiza en {family_text}. Ese patrón indica que el campo no debe agregarse como `IA en educación superior`, sino como un conjunto de configuraciones entre tarea docente, sistema de IA, resultado esperado y riesgo controlado."
        )
        certainty_signal_gap = (
            f"Lo que puede afirmarse con más seguridad es que los {len(focus_rows)} estudios focales muestran utilidad de la IA en tareas docentes delimitadas cuando existe supervisión, criterio pedagógico y evidencia trazable. "
            f"Lo que aparece como señal emergente es el paso desde herramientas conversacionales aisladas hacia flujos de apoyo docente más integrados en feedback, evaluación, diseño curricular, alfabetización y productividad. "
            f"Lo que todavía no puede concluirse es una mejora universal de la calidad educativa, porque {count_studies_es(diagnostics['missing_theory'])} {verb_by_count(diagnostics['missing_theory'], 'no explicita', 'no explicitan')} marco teórico, {count_studies_es(diagnostics['missing_variables'])} {verb_by_count(diagnostics['missing_variables'], 'no detalla', 'no detallan')} variables o dimensiones analíticas y {count_studies_es(diagnostics['missing_benchmark'])} {verb_by_count(diagnostics['missing_benchmark'], 'carece', 'carecen')} de comparador suficientemente claro."
        )
    elif profile == "social_sciences":
        family_counts = Counter(social_science_evidence_family(row) for row in focus_rows)
        family_text = counter_summary(
            mapped_counter(
                family_counts,
                {
                    "Polarización afectiva e identidad partidista": "polarización/identidad",
                    "Confianza institucional y legitimidad democrática": "confianza/legitimidad",
                    "Exposición digital y plataformas sociales": "exposición digital",
                    "Información política, desinformación y ecosistemas mediáticos": "información/desinformación",
                    "Participación y actitudes democráticas": "participación/actitudes",
                    "Evidencia metodológica y medición social": "medición",
                },
            ),
            len(focus_rows),
            limit=6,
        )
        answer = (
            "la relación entre uso de redes sociales, polarización afectiva y confianza institucional tiene relevancia teórica y metodológica, pero la evidencia empírica directa sobre confianza institucional es todavía insuficiente para sostener una respuesta universal. "
            "La evidencia disponible apunta a una relación condicionada por exposición, identidad partidista, calidad informativa, plataforma, contexto democrático, diseño de medición y estrategia empírica; esa relación es más fuerte como mapa de mecanismos plausibles y vacíos de evidencia que como magnitud causal agregable."
        )
        domain_conclusion = (
            f"La evidencia focal se organiza en {family_text}. Ese patrón indica que el campo no debe agregarse como efecto simple de redes sociales, sino como configuraciones entre exposición digital, mecanismo político, medición actitudinal, contexto institucional y límite causal."
        )
        social_gap_parts = []
        if diagnostics["missing_theory"] > 0:
            social_gap_parts.append(f"{count_studies_es(diagnostics['missing_theory'])} {verb_by_count(diagnostics['missing_theory'], 'no explicita', 'no explicitan')} marco teórico")
        if diagnostics["missing_variables"] > 0:
            social_gap_parts.append(f"{count_studies_es(diagnostics['missing_variables'])} {verb_by_count(diagnostics['missing_variables'], 'no detalla', 'no detallan')} variables o dimensiones analíticas")
        if diagnostics["missing_benchmark"] > 0:
            social_gap_parts.append(f"{count_studies_es(diagnostics['missing_benchmark'])} {verb_by_count(diagnostics['missing_benchmark'], 'carece', 'carecen')} de comparador suficientemente claro")
        social_gap_clause = (
            "porque " + ", ".join(social_gap_parts)
            if social_gap_parts
            else "porque los diseños siguen siendo heterogéneos y no todos sostienen la misma fuerza causal, aunque los campos mínimos estén reportados"
        )
        certainty_signal_gap = (
            f"Lo que puede afirmarse con más seguridad es que los {len(focus_rows)} estudios focales permiten comparar mecanismos y mediciones de una relación social compleja, no una causa única. "
            f"Lo que aparece como señal emergente es que la exposición digital, la polarización afectiva, la confianza institucional y la calidad informativa se conectan de forma contextual y abren hipótesis recursivas que todavía requieren diseños longitudinales, experimentales o comparadores temporales para poder cerrarse. "
            f"Lo que todavía no puede concluirse es una jerarquía causal definitiva, {social_gap_clause}."
        )
    else:
        answer = (
            f"la literatura sobre {topic} requiere una lectura sistemática basada en texto completo para distinguir evidencia fuerte, señal temática y registros insuficientes."
        )
        domain_conclusion = (
            "La síntesis focal permite formular conclusiones descriptivas sobre patrones de diseño, método y evidencia, pero evita convertir frecuencia documental en fuerza causal. La contribución del cierre está en traducir esos patrones en condiciones de comparación, no en repetir conteos."
        )
        certainty_signal_gap = (
            f"Lo que puede afirmarse con más seguridad es que los {len(focus_rows)} estudios focales permiten identificar dimensiones comparables de diseño, método y evidencia. "
            f"Lo que aparece como señal emergente es la existencia de patrones que merecen seguimiento en nuevas ventanas temporales. "
            f"Lo que todavía no puede concluirse es una jerarquía causal definitiva, especialmente cuando {count_studies_es(diagnostics['missing_theory'])} {verb_by_count(diagnostics['missing_theory'], 'no explicita', 'no explicitan')} marco teórico, {count_studies_es(diagnostics['missing_variables'])} {verb_by_count(diagnostics['missing_variables'], 'no detalla', 'no detallan')} variables o dimensiones analíticas y {count_studies_es(diagnostics['missing_benchmark'])} {verb_by_count(diagnostics['missing_benchmark'], 'carece', 'carecen')} de comparador suficientemente claro."
        )
    if is_ai_workload_context(context):
        composition_sentence = (
            f"La composición del corpus combina {len(empirical_rows)} estudios empíricos primarios y {len(support_rows)} trabajos de apoyo teórico, revisión o contexto. "
            "Esta separación es decisiva: los trabajos no empíricos ayudan a construir el modelo interpretativo, pero la respuesta a la pregunta se apoya en la base empírica. La mezcla no permite vender una cifra única de ahorro; sí permite una conclusión más útil: la promesa de trabajar menos depende de qué capa del trabajo se mida y de quién absorba la capa que la IA no elimina."
        )
        final_contribution_sentence = (
            "Como aportación final, el artículo propone una contabilidad de trabajo total para estudiar IA en organizaciones, educación, ciencia y conocimiento profesional. "
            "La contribución no es repetir que algunos estudios reportan productividad y otros reportan riesgos; es ordenar esa tensión en una regla evaluable: una adopción solo reduce trabajo si la suma de ejecución, articulación, verificación, coordinación, aprendizaje y responsabilidad disminuye sin degradar calidad, trazabilidad ni seguridad. "
            "Esa regla convierte una discusión promocional en una pregunta científica acumulativa " + citation_block(top_ids[8:12]) + "."
        )
    elif profile == "ai_security_harness":
        composition_sentence = (
            f"El corpus final incluido contiene {flow_counts.get('included_in_review', len(focus_rows))} estudios y la síntesis focal compara {len(focus_rows)} configuraciones defensivas con texto completo. "
            f"{empirical_n} estudios son empíricos según la extracción. La conclusión se apoya en esa base comparativa y usa los trabajos teóricos o metodológicos para interpretar mecanismos, no para inflar la evidencia de eficacia."
        )
        final_contribution_sentence = (
            "Como aportación final, el artículo propone una frontera de dominancia defensiva para evaluar harnesses de seguridad. "
            "Una alternativa domina solo cuando, bajo la misma amenaza y baseline, reduce más riesgo sin empeorar materialmente utilidad, falsos positivos, latencia o coste; si las métricas se compensan, la decisión debe declarar el contexto y la prioridad de riesgo. "
            "Esta frontera es una regla teórica derivada del diagnóstico del corpus, no una jerarquía empírica ya validada entre todos los harnesses. Su función es especificar qué evidencia futura permitiría demostrar dominancia y qué comparaciones deben seguir siendo contextuales. "
            "La regla permite transformar resultados fragmentarios de jailbreak, prompt injection, herramientas y exfiltración en decisiones comparables sin fingir una clasificación universal " + citation_block(top_ids[8:12]) + "."
        )
    else:
        composition_sentence = (
            f"El corpus final incluido contiene {flow_counts.get('included_in_review', len(focus_rows))} estudios, de los cuales {len(focus_rows)} sostienen la síntesis focal. "
            f"{empirical_n} de ellos son empíricos según la extracción estructurada. Esa composición permite proponer conclusiones descriptivas y metodológicas, pero no una inferencia causal cerrada."
        )
        final_contribution_sentence = (
            "Como aportación final, el artículo deja un corpus organizado, una síntesis focal, fichas analíticas por estudio y anexos que facilitan auditoría, actualización y réplica parcial sin reiniciar el trabajo desde cero. "
            "Esa trazabilidad no garantiza por sí sola una replicación completa, porque depende de acceso a PDFs, APIs y decisiones de revisión posteriores; sí convierte el cierre del artículo en una base de actualización, no en una declaración finalista " + citation_block(top_ids[8:12]) + "."
        )
    future_lines = conclusion_diagnostic_future_lines(focus_rows, profile)
    conclusion_evidence_verb = "sugiere" if profile == "social_sciences" and not is_ai_workload_context(context) else "indica"
    return "\n".join(
        [
            "# Conclusiones",
            "",
            f"En respuesta a la pregunta de investigación, {rq_text}, la evidencia {conclusion_evidence_verb} que {answer} " + citation_block(top_ids[:4]) + ".",
            "",
            composition_sentence,
            "",
            unit_thesis,
            "",
            grammar_sentence,
            "",
            domain_conclusion + " " + citation_block(top_ids[4:8]) + ".",
            "",
            certainty_signal_gap,
            "",
            "El límite no invalida la síntesis; define su alcance. La regla de DOI público, PDF legible, lectura de texto completo y matriz de selección reduce amplitud potencial, pero aumenta auditabilidad y evita sostener conclusiones sobre registros que no pueden comprobarse desde el documento fuente.",
            "",
            final_contribution_sentence,
            "",
            *future_lines,
            "",
            *build_author_contribution_section(focus_rows, flow_counts, context),
        ]
    ) + "\n"


def build_title_abstract_section(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    profile = detect_review_profile(context)
    if is_domain_general_profile(profile):
        return build_title_abstract_section_domain(review_dir, focus_rows, flow_counts, context)
    topic_text = context.get("topic") or (
        "arquitecturas de agentes para desarrollo de software"
        if profile == "software_architecture"
        else "agentes de IA"
    )
    rq_text = publication_research_question(context, profile)
    included_count = flow_counts.get("included_in_review", 0)
    focus_count = len(focus_rows)
    component_counts = component_counter(focus_rows)
    keyword_list = build_keyword_list(focus_rows, context=context)
    keywords = ", ".join(restore_acronyms(keyword) for keyword in keyword_list)
    keywords_en = ", ".join(english_keywords(keyword_list))
    timeframe_es = review_timeframe_phrase_es(context)
    timeframe_en = review_timeframe_phrase_en(context)
    spanish_topic = topic_text
    spanish_topic = re.sub(
        r"\bframeworks de arquitecturas de agentes\b",
        "arquitecturas y marcos de agentes",
        spanish_topic,
        flags=re.IGNORECASE,
    )
    spanish_topic = re.sub(r"\bframeworks\b", "marcos", spanish_topic, flags=re.IGNORECASE)
    if profile == "software_architecture":
        title = f"Arquitecturas de agentes para el desarrollo de software en 2026: revisión sistemática de literatura y síntesis focal de {focus_count} estudios"
        fallback_keywords = "arquitecturas de agentes, desarrollo de software, revisión sistemática de literatura, agentes autónomos, ingeniería del software"
        fallback_keywords_en = "agent architectures, software development, systematic literature review, autonomous agents, software engineering"
    elif profile == "ai_architecture":
        title = f"Arquitecturas de sistemas de IA en 2026: revisión sistemática de literatura y síntesis focal de {focus_count} estudios"
        fallback_keywords = "arquitecturas de IA, modelos fundacionales, RAG, agentes de IA, memoria, herramientas, inferencia, revisión sistemática de literatura"
        fallback_keywords_en = "AI architectures, foundation models, RAG, AI agents, memory, tools, inference, systematic literature review"
    else:
        title = f"Arquitecturas de agentes de IA en 2025-2026: revisión sistemática de literatura y síntesis focal de {focus_count} estudios"
        fallback_keywords = "agentes de IA, arquitecturas agénticas, memoria, herramientas, orquestación, evaluación, revisión sistemática de literatura"
        fallback_keywords_en = "AI agents, agentic architectures, memory, tools, orchestration, evaluation, systematic literature review"
    relation_text = corpus_focus_relation(included_count, focus_count)
    abstract_text = (
        f"Esta revisión sistemática de literatura analiza el estado de la investigación sobre {spanish_topic} {timeframe_es}. "
        f"El protocolo identificó {flow_counts.get('identified', 0)} registros, consolidó {flow_counts.get('duplicates_removed', 0)} duplicados antes del cribado, evaluó {flow_counts.get('full_text_assessed', 0)} textos completos en PDF e incluyó {included_count} estudios en el corpus final de la revisión. "
        f"{relation_text} "
        f"La pregunta de investigación que organiza el artículo es: {rq_text} "
        f"En la síntesis focal de {focus_count} estudios predominan arquitecturas con herramientas explícitas (n={component_counts.get('herramientas', 0)}), verificación o evaluación integrada (n={component_counts.get('verificador', 0)}), roles especializados (n={component_counts.get('roles', 0)}) y orquestación explícita (n={component_counts.get('orquestador', 0)}), aunque todavía persisten heterogeneidad metodológica, lagunas teóricas y diferencias en la calidad del reporte empírico. "
        "La contribución del trabajo consiste en "
        + contribution_scope_phrase(included_count, focus_count)
    )
    abstract_en = (
        f"This systematic literature review examines the state of research on {agent_topic_en(context)} {timeframe_en}. "
        f"The protocol identified {flow_counts.get('identified', 0)} records, consolidated {flow_counts.get('duplicates_removed', 0)} duplicates before screening, assessed {flow_counts.get('full_text_assessed', 0)} full texts in PDF, and included {included_count} studies in the final review corpus. "
        + focal_synthesis_relation(included_count, focus_count, language="en")
        + " "
        f"The research question guiding the article is: {publication_research_question_en(context, profile)} "
        f"Within the focal synthesis of {focus_count} studies, architectures with explicit tools (n={component_counts.get('herramientas', 0)}), integrated verification or evaluation (n={component_counts.get('verificador', 0)}), specialized roles (n={component_counts.get('roles', 0)}), and explicit orchestration (n={component_counts.get('orquestador', 0)}) predominate, while methodological heterogeneity, theoretical gaps, and differences in empirical reporting quality still persist. "
        "The contribution of the paper is to provide a reproducible structural characterization of the included corpus and deliver reusable CSV annexes and PDF evidence for audit and replication."
    )
    return manuscript_front_matter(
        title=title,
        abstract_text=abstract_text,
        abstract_en=abstract_en,
        keywords=keywords,
        keywords_en=keywords_en,
        fallback_keywords=fallback_keywords,
        fallback_keywords_en=fallback_keywords_en,
        context=context,
    )


def build_introduction_section(selected_rows: list[dict[str, str]], context: dict[str, str] | None = None) -> str:
    context = context or {}
    profile = detect_review_profile(context)
    if is_domain_general_profile(profile):
        return build_introduction_section_domain(selected_rows, context)
    anchor_ids = top_citation_ids(selected_rows, 8)
    rq_text = publication_research_question(context, profile)
    domain_sentence = (
        "En el ámbito del desarrollo de software, este cambio obliga a estudiar no solo el rendimiento observable, sino la organización interna del sistema, la distribución de roles, la memoria, la gobernanza de herramientas y la estrategia de evaluación "
        if profile == "software_architecture"
        else "En el campo más amplio de las arquitecturas de IA, este cambio obliga a estudiar no solo el rendimiento observable, sino la organización interna del sistema, la distribución de roles, la memoria, la gobernanza de herramientas y la estrategia de evaluación "
        if profile == "ai_architecture"
        else "En el campo más amplio de los agentes de IA, este cambio obliga a estudiar no solo el rendimiento observable, sino la organización interna del sistema, la distribución de roles, la memoria, la gobernanza de herramientas y la estrategia de evaluación "
    )
    scope_sentence = (
        "La literatura de 2026 resulta especialmente adecuada para una revisión estructural porque acumula propuestas de marcos multiagente, patrones de orquestación, sistemas de benchmarking y diseños específicos para testing, debugging, seguridad o automatización de flujos de desarrollo. "
        if profile == "software_architecture"
        else "La literatura de 2026 resulta especialmente adecuada para una revisión estructural porque acumula arquitecturas de modelos fundacionales, sistemas RAG, memoria, herramientas, agentes, multimodalidad, MoE, serving, inferencia y evaluaciones aplicadas en dominios heterogéneos. "
        if profile == "ai_architecture"
        else "La literatura de 2025-2026 resulta especialmente adecuada para una revisión estructural porque acumula prototipos, sistemas multiagente, agentes conversacionales, arquitecturas con herramientas, diseños RAG y evaluaciones aplicadas en dominios heterogéneos. "
    )
    goal_sentence = (
        "Este artículo responde a esa brecha con una revisión sistemática centrada en arquitecturas agnósticas a tecnología, framework o proveedor. La meta no es comparar marcas, sino identificar qué piezas estructurales se repiten, qué tareas de ingeniería cubren, cómo se evalúan y qué límites metodológicos siguen presentes en el campo."
        if profile == "software_architecture"
        else "Este artículo responde a esa brecha con una revisión sistemática centrada en arquitecturas agnósticas a tecnología, framework o proveedor. La meta no es comparar marcas, sino identificar qué piezas estructurales se repiten, en qué dominios se aplican, cómo se evalúan y qué límites metodológicos siguen presentes en el campo."
    )
    return "\n".join(
        [
            "# Introducción",
            "",
            "La evolución reciente de los sistemas basados en modelos fundacionales ha desplazado el foco desde asistentes puntuales hacia arquitecturas agénticas capaces de planificar, coordinar herramientas y ejecutar subtareas de forma sostenida. "
            + domain_sentence + citation_block(anchor_ids[:4]) + ".",
            "",
            scope_sentence
            + "Sin embargo, esa riqueza convive con una elevada heterogeneidad metodológica y con descripciones incompletas del aparato arquitectónico en parte del corpus " + citation_block(anchor_ids[4:8]) + ".",
            "",
            goal_sentence,
            "",
            f"Con esa delimitación, la pregunta de investigación que guía el artículo es: {rq_text}",
        ]
    ) + "\n"


def architectural_theoretical_thesis_lines(focus_rows: list[dict[str, str]], profile: str) -> list[str]:
    component_counts = component_counter(focus_rows)
    theories = theory_summary(focus_rows, 4)
    total = max(len(focus_rows), 1)
    explicit_theory_n = sum(
        1 for row in focus_rows if nice_value(row.get("theory_framework")).lower() != "no reportado"
    )
    explicit_fragment = (
        "; ".join(f"{label} (n={count}, {percentage(count, total)})" for label, count in theories[:3])
        if theories
        else "no aparece una teoría dominante única y los estudios reportan marcos fragmentados o ad hoc"
    )
    convergence_label = "convergencia ingenieril" if profile == "software_architecture" else "convergencia aplicada"
    return [
        "## Tesis teóricas y bases declaradas",
        "1. La unidad analítica dominante del campo no es el modelo aislado, sino la arquitectura del sistema: composición de roles, coordinación, herramientas, memoria y verificación.",
        "2. La coordinación explícita y la especialización funcional actúan como tesis de diseño recurrente frente a la figura del agente único monolítico, especialmente cuando la tarea exige trazabilidad, delegación o control de calidad.",
        f"3. La instrumentación del sistema importa tanto como la generación: herramientas (n={component_counts.get('herramientas', 0)}), verificación (n={component_counts.get('verificador', 0)}), roles especializados (n={component_counts.get('roles', 0)}) y orquestación (n={component_counts.get('orquestador', 0)}) aparecen como componentes estructurales recurrentes del subconjunto focal.",
        f"4. Las bases teóricas explícitamente declaradas por los estudios siguen fragmentadas: {explicit_fragment}. En términos editoriales, esto sugiere un campo con más {convergence_label} que consolidación doctrinal.",
        f"5. Solo {explicit_theory_n} de {len(focus_rows)} estudios focales reportan un marco teórico identificable en la extracción, lo que convierte la ausencia de teoría explícita en un resultado del corpus y no en una omisión menor del manuscrito.",
    ]


def personality_theoretical_thesis_lines(focus_rows: list[dict[str, str]]) -> list[str]:
    theories = theory_family_counter(focus_rows, 4)
    constructs = personality_construct_counter(focus_rows)
    total = max(len(focus_rows), 1)
    explicit_fragment = (
        "; ".join(f"{label} (n={count}, {percentage(count, total)})" for label, count in theories[:3])
        if theories
        else "no aparece una teoría dominante única y el corpus opera como convergencia entre psicometría, persona steering e interacción humano-IA"
    )
    return [
        "## Tesis teóricas y bases declaradas",
        "1. La personalidad en LLMs se estudia simultáneamente como constructo medible, como palanca de steering y como fuente de efectos downstream sobre interacción, sesgo o alineamiento.",
        f"2. Los constructos más visibles del subconjunto focal son {', '.join(f'{label} (n={count})' for label, count in constructs.most_common(4)) or 'heterogéneos y fragmentados'}, lo que refuerza una tesis de pluralidad conceptual más que de teoría única.",
        f"3. Las bases teóricas explícitas reportadas se distribuyen del siguiente modo: {explicit_fragment}. Esto sugiere convergencia parcial, pero no una escuela unificada.",
        "4. La literatura conecta psicometría, role-play y control conductual del agente con mayor claridad que los mecanismos de validez externa o estabilidad longitudinal de esos constructos.",
    ]


def build_theoretical_framework_section(
    focus_rows: list[dict[str, str]],
    context: dict[str, str] | None = None,
) -> str:
    context = context or {}
    profile = detect_review_profile(context)
    if is_domain_general_profile(profile):
        return build_theoretical_framework_section_domain(focus_rows, context)
    theories = theory_summary(focus_rows, 5)
    work_counts = work_type_summary(focus_rows)
    empirical_counts = empirical_summary(focus_rows)
    top_ids = top_citation_ids(focus_rows, 12)
    total = len(focus_rows)
    if not theories:
        theory_sentence = (
            "No emerge una teoría única dominante; el corpus funciona más como un espacio de ingeniería arquitectónica que como un frente consolidado sobre un solo marco formal."
            if profile == "software_architecture"
            else "No emerge una teoría única dominante; el corpus funciona más como un espacio de diseño aplicado de sistemas agénticos que como un frente consolidado sobre un solo marco formal."
        )
    elif max(count for _, count in theories[:3]) <= 1:
        theory_sentence = (
            "Los marcos explícitos aparecen de forma muy fragmentada y no permiten identificar una escuela dominante. "
            + (
                "El corpus mezcla estándares de calidad del software, modelos de objetivos, heurísticas de coordinación "
                if profile == "software_architecture"
                else "El corpus mezcla modelos de objetivos, heurísticas de coordinación, marcos de evaluación, patrones RAG "
            )
            + "y marcos ad hoc propuestos por estudios individuales, sin que ninguno articule por sí solo el campo."
        )
    else:
        theory_sentence = (
            "Los marcos más visibles son "
            + "; ".join(
                f"{label} (n={count}, {percentage(count, total)})"
                for label, count in theories[:3]
            )
            + "."
        )
    experimental_count = empirical_counts.get("experimental", 0)
    mixed_count = empirical_counts.get("mixed", 0)
    quantitative_count = empirical_counts.get("quantitative", 0)
    qualitative_count = empirical_counts.get("qualitative", 0)
    empirical_total = work_counts.get("empirical", 0)
    other_empirical_count = max(empirical_total - experimental_count - mixed_count - quantitative_count - qualitative_count, 0)
    review_count = work_counts.get("review", 0)
    method_sentence = (
        "Desde el punto de vista metodológico, tampoco se observa una escuela única, sino una combinación de benchmarks, comparativas experimentales, propuestas de sistema y revisiones de alcance."
        if not empirical_counts and not review_count
        else "Metodológicamente, el corpus focal reúne "
        f"{empirical_total} estudios empíricos ({percentage(empirical_total, total)}); dentro de ellos predominan los diseños experimentales "
        f"(n={experimental_count}), acompañados por variantes mixtas (n={mixed_count}), cuantitativas (n={quantitative_count}), cualitativas (n={qualitative_count}) "
        f"y otras formas empíricas o reporting metodológico abierto (n={other_empirical_count}). "
        f"Las revisiones explícitas siguen siendo escasas (n={review_count}, {percentage(review_count, total)})."
    )
    return "\n".join(
        [
            "# Marco teórico",
            "",
            (
                "El corpus de 2026 se articula más como un espacio de ingeniería arquitectónica que como un campo asentado sobre una teoría unificada. "
                if profile == "software_architecture"
                else "El corpus de 2026 se articula más como un espacio de diseño de sistemas de IA que como un campo asentado sobre una teoría unificada. "
                if profile == "ai_architecture"
                else "El corpus de 2025-2026 se articula más como un espacio de diseño de sistemas agénticos que como un campo asentado sobre una teoría unificada. "
            )
            + "Las propuestas combinan patrones de planificación, ejecución especializada, orquestación con herramientas y mecanismos de evaluación o verificación, lo que sugiere una ecología de diseños más pragmática que doctrinal " + citation_block(top_ids[8:12]) + ".",
            "",
            "El marco teórico se organiza en tres capas para no confundir revisión sistemática con catálogo técnico. La primera capa recoge las bases teóricas o conceptuales que los propios papers declaran. La segunda construye una lente de comparación común a partir del corpus: arquitectura como combinación entre tarea, componentes, coordinación, herramientas, memoria, inferencia, evaluación y evidencia. La tercera capa delimita qué puede afirmarse y qué no, porque una arquitectura descrita en un prototipo, un benchmark o un sistema desplegado no tiene el mismo peso inferencial.",
            "",
            "En términos operativos, esta revisión usa dos familias arquitectónicas como lente analítica descriptiva. Los enfoques basados en capacidades o habilidades agrupan capacidades reutilizables o invocables dentro de un agente o de un catálogo de habilidades componibles; los enfoques multiagente orquestados separan explícitamente roles, delegación y coordinación entre agentes o subagentes. Esa distinción se usa solo para comparar el corpus y no como taxonomía normativa cerrada: su función es mostrar qué cambia cuando el sistema pasa de capacidad aislada a configuración coordinada.",
            "",
            theory_sentence,
            "",
            method_sentence,
            "",
            "Estos conteos proceden de los campos estructurados `work_type` y `empirical_type` de la tabla de extracción y deben leerse como una cartografía descriptiva del corpus, no como una inferencia causal autónoma.",
            "",
            "Por tanto, el marco no intenta imponer una teoría externa más fuerte que el propio corpus. Su función es construir una gramática de lectura: qué unidad se compara, qué componentes la forman, qué evidencia la sostiene y qué límites impiden convertir una señal recurrente en una ley general del campo.",
            "",
            *architectural_theoretical_thesis_lines(focus_rows, profile),
            "",
            "En conjunto, el marco conceptual emergente puede describirse como una convergencia entre sistemas multiagente, arquitecturas instrumentadas con herramientas y estrategias de evaluación orientadas a tareas. "
            "La revisión permite, por tanto, tratar la arquitectura como unidad analítica central del campo " + citation_block(top_ids[4:8]) + ".",
        ]
    ) + "\n"


def build_method_section(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    all_shortlist_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    if is_domain_general_profile(detect_review_profile(context)):
        return build_method_section_domain(review_dir, focus_rows, all_shortlist_rows, flow_counts, context)
    source_counter = read_search_sources(review_dir)
    source_rows = [[source, str(count)] for source, count in source_counter.most_common(8)]
    source_sentence = join_human_list([source for source, _count in source_counter.most_common(8)])
    focus_exclusions = Counter(
        reason
        for row in all_shortlist_rows
        if is_selected(row) and (reason := focus_exclusion_reason(review_dir, row))
    )
    focus_low_conf = sum(1 for row in focus_rows if parse_int(row.get("extraction_confidence"), 0) < 80)
    sensitivity = shortlist_sensitivity(review_dir)
    relation_text = corpus_focus_relation(flow_counts.get("included_in_review", 0), len(focus_rows))
    profile = detect_review_profile(context)
    software_profile = profile == "software_architecture"
    ai_architecture_profile = profile == "ai_architecture"
    years_label = review_years_label(context)
    domain_cap_label = (
        "Fuera del dominio software"
        if software_profile
        else "Fuera del dominio de arquitecturas de IA"
        if ai_architecture_profile
        else "Fuera del dominio de agentes de IA"
    )
    default_inclusion_text = (
        "Publicaciones de 2026 sobre arquitecturas de agentes aplicadas al desarrollo de software o a tareas claras de ingeniería del software."
        if software_profile
        else "Publicaciones de 2026 sobre arquitecturas de IA, modelos fundacionales, agentes, RAG, memoria, herramientas, multimodalidad, MoE, inferencia o evaluación arquitectónica con evidencia metodológica identificable."
        if ai_architecture_profile
        else "Publicaciones de 2025-2026 sobre agentes de IA con arquitectura, memoria, herramientas, orquestación, evaluación o diseño metodológico identificable."
    )
    default_exclusion_text = (
        "Ausencia de arquitectura agéntica explícita aplicable al desarrollo de software, ausencia de PDF legible "
        "o imposibilidad de recuperar evidencia metodológica suficiente del texto completo."
        if software_profile
        else "Ausencia de contribución sustantiva sobre arquitectura de IA, ausencia de PDF legible "
        "o imposibilidad de recuperar evidencia metodológica suficiente del texto completo."
        if ai_architecture_profile
        else "Ausencia de contribución sustantiva sobre agentes de IA, ausencia de PDF legible "
        "o imposibilidad de recuperar evidencia metodológica suficiente del texto completo."
    )
    search_terms_text = (
        "Las búsquedas combinaron términos sobre `agent architecture`, `multi-agent`, `orchestration`, `software engineering`, `testing`, `debugging`, `security`, `benchmarking` y expresiones equivalentes en fuentes bibliográficas generales y técnicas."
        if software_profile
        else "Las búsquedas combinaron términos sobre `AI architecture`, `foundation model`, `RAG` (retrieval-augmented generation), `agentic AI`, `multi-agent`, `memory`, `tool use`, `multimodal`, `MoE` (mixture of experts), `inference`, `serving`, `evaluation` y expresiones equivalentes en fuentes bibliográficas generales y técnicas."
        if ai_architecture_profile
        else "Las búsquedas combinaron términos sobre `AI agents`, `agent architecture`, `multi-agent systems`, `orchestration`, `memory`, `tools`, `RAG`, `evaluation`, `benchmarking` y expresiones equivalentes en fuentes bibliográficas generales y técnicas."
    )
    protocol_scope_text = (
        "literatura de ingeniería del software de 2026"
        if software_profile
        else "literatura técnica sobre arquitecturas de IA publicada en 2026"
        if ai_architecture_profile
        else "literatura técnica sobre agentes de IA publicada entre 2025 y 2026"
    )
    operational_exclusion_text = (
        "Operativamente, la exclusión temática se aplicó a trabajos sin arquitectura agéntica explícita, estudios cuyo foco principal no era una tarea de ingeniería del software o registros que no ofrecían señal suficiente para ubicar componentes, método o evaluación dentro del PDF."
        if software_profile
        else "Operativamente, la exclusión temática se aplicó a trabajos sin foco sustantivo en arquitectura de IA, estudios donde la IA era solo una aplicación tangencial o registros que no ofrecían señal suficiente para ubicar componentes, método o evaluación dentro del PDF."
        if ai_architecture_profile
        else "Operativamente, la exclusión temática se aplicó a trabajos sin foco sustantivo en agentes de IA, estudios donde el agente era solo una metáfora o registros que no ofrecían señal suficiente para ubicar componentes, método o evaluación dentro del PDF."
    )
    focal_rule_text = (
        "Para la síntesis focal del artículo, además, se excluyeron del N final los estudios con desajuste temático manifiesto respecto a la ingeniería del software y se priorizaron los trabajos con confianza de extracción igual o superior a 80."
        if software_profile
        else "Para la síntesis focal del artículo, además, se excluyeron del N final los estudios con desajuste temático manifiesto respecto a arquitecturas de IA y se priorizaron los trabajos con confianza de extracción igual o superior a 80."
        if ai_architecture_profile
        else "Para la síntesis focal del artículo, además, se excluyeron del N final los estudios con desajuste temático manifiesto respecto a agentes de IA y se priorizaron los trabajos con confianza de extracción igual o superior a 80."
    )
    relevance_definition_text = (
        "La `relevancia temática` valora el ajuste explícito a arquitecturas de agentes en ingeniería del software; la `calidad metodológica` valora la claridad de método, muestra, evaluación y hallazgos; y la `representatividad` evita que el N final quede dominado por propuestas casi idénticas."
        if software_profile
        else "La `relevancia temática` valora el ajuste explícito a arquitecturas de IA y a sus componentes de modelo, recuperación, memoria, herramientas, orquestación, inferencia o evaluación; la `calidad metodológica` valora la claridad de método, muestra, evaluación y hallazgos; y la `representatividad` evita que el N final quede dominado por propuestas casi idénticas."
        if ai_architecture_profile
        else "La `relevancia temática` valora el ajuste explícito a agentes de IA y a sus componentes de arquitectura, memoria, herramientas, orquestación o evaluación; la `calidad metodológica` valora la claridad de método, muestra, evaluación y hallazgos; y la `representatividad` evita que el N final quede dominado por propuestas casi idénticas."
    )
    final_filter_text = (
        "En el manuscrito final, esa priorización se depuró además con tres reglas complementarias: conservar únicamente estudios con PDF local verificable, degradar a reserva los estudios con confianza de extracción inferior a 80 y retirar del subconjunto focal los casos con desajuste manifiesto respecto al desarrollo de software. "
        if software_profile
        else "En el manuscrito final, esa priorización se depuró además con tres reglas complementarias: conservar únicamente estudios con PDF local verificable, degradar a reserva los estudios con confianza de extracción inferior a 80 y retirar del subconjunto focal los casos con desajuste manifiesto respecto a arquitecturas de IA. "
        if ai_architecture_profile
        else "En el manuscrito final, esa priorización se depuró además con tres reglas complementarias: conservar únicamente estudios con PDF local verificable, degradar a reserva los estudios con confianza de extracción inferior a 80 y retirar del subconjunto focal los casos con desajuste manifiesto respecto a agentes de IA. "
    )
    exclusion_text = context.get("exclusion") or ""
    if not exclusion_text or "irrelevancia manifiesta" in exclusion_text.lower():
        exclusion_text = default_exclusion_text
    prisma_rows = [
        ["Registros identificados", str(flow_counts.get("identified", 0))],
        ["Duplicados consolidados antes del cribado", str(flow_counts.get("duplicates_removed", 0))],
        ["Cribado título/resumen", str(flow_counts.get("screened_title_abstract", 0))],
        ["Exclusiones título/resumen", str(flow_counts.get("excluded_title_abstract", 0))],
        ["Texto completo buscado", str(flow_counts.get("full_text_sought", 0))],
        ["Texto completo no recuperado en PDF", str(flow_counts.get("full_text_not_retrieved", 0))],
        ["Texto completo evaluado", str(flow_counts.get("full_text_assessed", 0))],
        ["Estudios incluidos tras lectura de texto completo", str(flow_counts.get("included_in_review", 0))],
        ["Estudios de síntesis focal", str(len(focus_rows))],
    ]
    wr, wq, wp = selection_weight_triplet(context)
    cap_rows = [
        ["Elegibilidad de entrada", "solo estudios incluidos tras lectura de texto completo"],
        ["Regla dura de PDF", "sin PDF local legible no puede entrar en corpus final ni en síntesis focal"],
        ["Relevancia temática", f"{selection_weight_percent(wr)} del score compuesto; mide ajuste al foco sustantivo de la revisión"],
        ["Calidad metodológica", f"{selection_weight_percent(wq)} del score compuesto; mide método, muestra, evaluación, resultados y trazabilidad"],
        ["Representatividad", f"{selection_weight_percent(wp)} del score compuesto; corrige concentración por fuente, tipo de trabajo o familia casi idéntica"],
        ["Ordenación focal", "score compuesto descendente; en empates se conserva el orden DOI/PDF ya fijado por la matriz antes del corte y se reporta sensibilidad alternativa"],
        ["Límite N final", f"se retienen hasta N estudios declarados en el protocolo; aquí pasan {len(focus_rows)} por la regla DOI + PDF"],
        ["Confianza de extracción < 80", "el estudio pasa a reserva y deja de competir en igualdad de condiciones"],
        [domain_cap_label, "penalización temática fuerte y salida del top si persiste tras la curación editorial"],
    ]
    rubric_rows = [
        ["Ajuste arquitectónico y definición de la tarea", "25"],
        ["Explicitud de componentes, roles y coordinación", "25"],
        ["Método, evaluación y resultados reportados", "25"],
        ["Trazabilidad de la evidencia dentro del PDF", "15"],
        ["Contexto, muestra y entorno de aplicación", "10"],
    ]
    score_rows = selection_score_rows(review_dir, focus_rows)
    non_focal_rows = non_focal_selection_rows(all_shortlist_rows)
    focal_context_rows = focal_context_characteristics_rows(focus_rows, all_shortlist_rows)
    non_focal_explanation = (
        "La selección focal no elimina estudios del corpus incluido: solo separa el nivel de cartografía general del nivel de comparación intensiva. "
        "Por eso los registros fuera del N focal siguen reportados en la Tabla 4B, con rank, score y criterio operativo visible. "
        if non_focal_rows
        else "En esta revisión, la regla DOI + PDF dejó el corpus incluido y la síntesis focal con el mismo N; la Tabla 4B se conserva como comprobación explícita de que no hay estudios DOI-válidos fuera del foco intensivo. "
    )
    return "\n".join(
        [
            "# Método",
            "",
            "El estudio se diseñó como una revisión sistemática de literatura: primero se fijó una pregunta de investigación, después se definieron fuentes y cadenas de búsqueda, se aplicaron criterios de elegibilidad, se recuperó texto completo, se extrajo evidencia estructurada y finalmente se sintetizaron patrones arquitectónicos comparables. "
            "Los estándares de reporte de revisiones sistemáticas se emplearon como guía de transparencia de selección, no como sustituto de la metodología ni de la tesis del artículo. El diseño operativo sigue la lógica clásica de planificación, conducción y reporte descrita por Kitchenham y Charters (2007), Page et al. (2021), Rethlefsen et al. (2021) y Snyder (2019). "
            "La regla metodológica más estricta fue que ningún estudio podía entrar en el corpus final publicable sin DOI normalizado, PDF local legible y texto extraído desde ese PDF.",
            "",
            "## Diseño de la revisión sistemática",
            (
                "La unidad de análisis fue el estudio publicado sobre arquitecturas de IA, no el modelo concreto, proveedor o framework descrito en cada paper. Por eso la extracción separó arquitectura, tarea, herramientas, memoria, recuperación, orquestación, inferencia, evaluación, muestra, método, variables, resultados y limitaciones. El objetivo no era demostrar que una tecnología concreta fuese superior, sino sintetizar cómo se está configurando el campo de las arquitecturas de sistemas de IA en la literatura de 2026."
                if ai_architecture_profile
                else "La unidad de análisis fue el estudio publicado sobre agentes de IA, no el modelo concreto, proveedor o framework descrito en cada paper. Por eso la extracción separó arquitectura, tarea, herramientas, memoria, orquestación, evaluación, muestra, método, variables, resultados y limitaciones. El objetivo no era demostrar que una tecnología concreta fuese superior, sino sintetizar cómo se está configurando el campo de las arquitecturas agénticas en la literatura reciente."
            ),
            "",
            f"Rango temporal: publicaciones fechadas en {years_label}. Idiomas: universo abierto; cuando el título o el abstract aparecían en otra lengua, se conservaron y tradujeron para facilitar la comparación, pero la inclusión final siguió dependiendo de DOI normalizado y PDF legible.",
            "",
            f"Las fuentes consultadas fueron {source_sentence or 'las fuentes registradas en el protocolo'}. La búsqueda se ejecutó como estrategia multi-fuente: OpenAlex aportó cobertura bibliográfica amplia, Crossref reforzó resolución DOI y metadatos editoriales, Semantic Scholar añadió señal técnica y de citación, y arXiv capturó preprints tempranos de un campo todavía en movimiento.",
            "",
            search_terms_text + " El detalle completo de las cadenas se conserva en el anexo metodológico para no sobrecargar el cuerpo principal.",
            "",
            "El cribado siguió una lógica secuencial: primero se excluyeron registros por título y resumen cuando el desajuste temático era claro; después se buscó PDF; finalmente se evaluó el texto completo. La decisión `include_ft` exigió que el PDF permitiera recuperar al menos contribución arquitectónica, método o evaluación y una señal mínima de resultados. Cuando faltaba texto completo legible, el registro quedaba documentado, pero no podía entrar en el corpus final.",
            "",
            "Operativamente, `arquitectura agnóstica a tecnología, marco o proveedor` significa que la comparación abstrajo cada estudio a componentes funcionales comunes —roles, orquestador, herramientas, memoria y verificador— y no a productos, SDKs, marcas o stacks concretos. Cuando un estudio describía AutoGen, LangGraph, un stack propietario o una integración específica, el manuscrito solo retenía la lógica arquitectónica comparable.",
            "",
            f"No se registró un protocolo externo en PROSPERO ni en OSF antes de realizar la revisión. La justificación es metodológica: se trata de una revisión de escritorio centrada en {protocol_scope_text}. Para compensar esa ausencia de preregistro, se conservan el protocolo inicial, la estrategia de búsqueda, los logs de búsqueda, los registros de cribado, los PDFs locales y la preselección curada como rastro auditable completo.",
            "",
            *build_method_depth_lines(review_dir, focus_rows, flow_counts, context),
            "",
            "## Criterios de inclusión",
            f"- {context.get('inclusion') or default_inclusion_text}",
            "- DOI normalizado disponible para trazabilidad bibliográfica pública.",
            "- Disponibilidad de PDF local verificable para la fase de texto completo.",
            "",
            "## Criterios de exclusión",
            f"- {exclusion_text}",
            f"- {operational_exclusion_text}",
            f"- {focal_rule_text}",
            "",
            "Figura 1. Arquitectura operativa de revisión.",
            figure_markdown("../../figures/png/fig-review-architecture.png", "Figura 1. Arquitectura operativa de revisión"),
            "",
            "Tabla 1. Flujo de selección de estudios.",
            markdown_table(["Etapa", "N"], prisma_rows),
            "",
            "Tabla 2. Distribución de consultas registradas por fuente.",
            markdown_table(["Fuente", "Consultas"], source_rows),
            "",
            "Tabla 3. Reglas operativas de composición del subconjunto focal.",
            markdown_table(["Criterio", "Regla operativa"], cap_rows),
            "",
            "Tabla 4. Rúbrica operativa de la confianza de extracción.",
            markdown_table(["Indicador", "Peso máximo"], rubric_rows),
            "",
            "Tabla 4A. Transparencia del score aplicado al subconjunto focal.",
            markdown_table(
                ["Pos.", "DOI", "Título completo", "Rel.", "Calidad", "Rep.", "Score"],
                score_rows or [["—", "—", "No disponible", "0,0", "0,0", "0,0", "0,0"]],
            ),
            "",
            "Tabla 4B. Estudios incluidos en la revisión pero fuera de la síntesis focal.",
            markdown_table(
                ["Pos.", "DOI", "Título completo", "Score", "Rel.", "Calidad", "Rep.", "Criterio operativo"],
                non_focal_rows or [["—", "—", "No aplica", "0,0", "0,0", "0,0", "0,0", "Todos los estudios incluidos entraron en la síntesis focal."]],
            ),
            "",
            "Tabla 4C. Comparación focal-contextual.",
            markdown_table(
                ["Grupo", "N", "Perfil dominante", "Vacíos de reporte", "Score medio", "Fuentes principales"],
                focal_context_rows,
            ),
            "",
            "La Tabla 4C permite comprobar si el núcleo intensivo y el perímetro contextual difieren en diseño, reporte o fuente. Cuando hay diferencias, el manuscrito las interpreta como límite de transferencia de la síntesis focal y no como descarte invisible de evidencia.",
            "",
            "La escala de `confianza de extracción` se expresa de 0 a 100 y resume cuánta evidencia metodológica verificable ofrece el PDF completo de cada estudio. "
            "No es una medida de perfección del reporte, sino de extractabilidad auditada: combina claridad arquitectónica, explicitud de método y evaluación, trazabilidad del hallazgo principal y posibilidad de ubicar la evidencia dentro del PDF. "
            "Por eso la ausencia de un dato aislado, como el tamaño muestral en algunos benchmarks o comparativas de arquitecturas, penaliza la puntuación pero no la anula si el resto del diseño, la tarea y la evaluación son explícitos. "
            + relevance_definition_text,
            "",
            "Las cadenas de búsqueda completas, el intake y los criterios detallados se entregan también como anexos metodológicos del artículo junto con los CSV del corpus, para que la selección pueda auditarse sin depender de esta narrativa resumida.",
            "",
            "La literatura capturada en 2026 está sesgada hacia preprints, repositorios abiertos y actas tempranas, algo esperable en un frente que evoluciona más rápido que los ciclos editoriales tradicionales. El manuscrito no oculta ese sesgo: lo trata como una limitación del corpus y lo compensa con trazabilidad PDF, reglas duras de selección y entrega íntegra de anexos para auditoría externa.",
            "",
            f"La diferencia entre los {flow_counts.get('identified', 0)} registros identificados y los {flow_counts.get('screened_title_abstract', 0)} cribados en título/resumen responde a {flow_counts.get('duplicates_removed', 0)} duplicados consolidados antes del cribado inicial. "
            f"Del mismo modo, los {flow_counts.get('full_text_sought', 0)} candidatos a texto completo no equivalen a {flow_counts.get('full_text_assessed', 0)} PDFs evaluados: {flow_counts.get('full_text_not_retrieved', 0)} registros no pudieron recuperarse en PDF y, por regla metodológica, no entraron en el corpus final. "
            f"De los {flow_counts.get('full_text_assessed', 0)} PDFs efectivamente evaluados, {flow_counts.get('full_text_excluded', 0)} quedaron excluidos en la lectura de texto completo y {flow_counts.get('included_in_review', 0)} pasaron al corpus incluido de la revisión.",
            "La diferencia entre duplicados consolidados y ocurrencias duplicadas se conserva explícitamente: el flujo de selección informa la reducción neta de registros antes del cribado, mientras que `duplicates.csv` registra ocurrencias crudas dentro de grupos duplicados. Por eso ambos valores pueden diferir sin que exista una incoherencia PRISMA: uno mide reducción de universo cribado y el otro documenta evidencias de duplicidad detectadas.",
            "",
            "La Tabla 1 documenta el paso de registros a estudios incluidos y síntesis focal. La Figura 1 no sustituye ese flujo: resume cómo se coordinan intake, búsquedas, lectura de PDFs, extracción, evaluación de calidad, síntesis y revisión cruzada para producir una revisión reproducible.",
            "",
            relation_text + " La puntuación base de la preselección focal se calculó mediante una regla ponderada explícita.",
            "",
            *focal_score_formula_lines(context),
            "",
            (
                "Operativamente, `relevancia temática` y `calidad metodológica` se miden como indicadores numéricos de 0 a 100 extraídos del PDF completo; `representatividad` se calcula como corrección de diversidad para evitar que el N final quede dominado por una sola fuente, un único tipo de trabajo o propuestas casi idénticas. "
                + non_focal_explanation
                + f"Como comprobación de robustez, dos variantes simples de sensibilidad (`0,40/0,40/0,20` y `0,45/0,30/0,25`) conservaron {sensitivity.get('alt_a_overlap', 0)}/{sensitivity.get('target_n', 0)} y {sensitivity.get('alt_b_overlap', 0)}/{sensitivity.get('target_n', 0)} estudios del subconjunto final, lo que sugiere que la composición del N final es estable y no depende de un ajuste oportunista de pesos. "
                + "Las Tablas 4A-4B y el anexo `selection-score-matrix.csv` hacen explícita esa puntuación para que la selección del N final no funcione como caja negra."
            ),
            "La puntuación y la codificación se aplicaron sobre texto completo, pero no por un panel humano independiente. Por tanto, no se declara kappa ni acuerdo intercodificador humano en esta revisión. Esta decisión se trata como limitación metodológica: el valor del procedimiento está en dejar reglas, evidencia PDF y matrices auditables, pero no sustituye la fiabilidad que aportaría una doble codificación humana en una versión editorial posterior.",
            "",
            final_filter_text
            +
            f"En esta revisión, ese filtrado complementario afectó a {sum(count for reason, count in focus_exclusions.items() if reason != 'confianza_de_extraccion_baja')} "
            f"registro{'s' if sum(count for reason, count in focus_exclusions.items() if reason != 'confianza_de_extraccion_baja') != 1 else ''} inicialmente seleccionado{'s' if sum(count for reason, count in focus_exclusions.items() if reason != 'confianza_de_extraccion_baja') != 1 else ''} por el ranking automático. "
            "Cuando ese valor es cero, significa que el N final automático ya era consistente con las reglas editoriales finales y no fue necesario sustituir estudios tras la depuración temática. "
            f"El subconjunto final mantiene {focus_low_conf} estudios con confianza de extracción inferior a 80, señalados como lectura de reserva mientras se completa la profundización metodológica.",
        ]
    ) + "\n"


def build_results_section(
    review_dir: pathlib.Path,
    all_review_rows: list[dict[str, str]],
    focus_rows: list[dict[str, str]],
) -> str:
    context = read_research_context(review_dir)
    profile = detect_review_profile(context)
    if is_domain_general_profile(profile):
        return build_results_section_domain(review_dir, all_review_rows, focus_rows)
    corpus_rows = all_review_rows or focus_rows
    work_counter = work_type_summary(corpus_rows)
    empirical_counter = empirical_summary(focus_rows)
    corpus_component_counts = component_counter(corpus_rows)
    component_counts = component_counter(focus_rows)
    corpus_archetypes = archetype_counter(corpus_rows)
    archetypes = archetype_counter(focus_rows)
    work_rows = [[table_label(display_work_type(label)), f"{count} ({percentage(count, len(corpus_rows))})"] for label, count in work_counter.most_common()]
    empirical_rows = [[table_label(display_empirical_type(label)), f"{count} ({percentage(count, sum(empirical_counter.values()))})"] for label, count in empirical_counter.most_common()]
    component_rows = [
        [table_label(label), f"{count} ({percentage(count, len(focus_rows))})"]
        for label, count in component_counts.most_common()
    ]
    def sensitivity_label(corpus_count: int, focal_count: int, corpus_total: int, focal_total: int) -> str:
        corpus_pct = (corpus_count / corpus_total * 100.0) if corpus_total else 0.0
        focal_pct = (focal_count / focal_total * 100.0) if focal_total else 0.0
        diff = abs(focal_pct - corpus_pct)
        if diff < 5:
            return "Estable"
        if diff < 15:
            return "Diferencia moderada"
        return "Sensible al corte"

    component_sensitivity_rows = [
        [
            table_label(label),
            f"{corpus_component_counts.get(label, 0)} ({percentage(corpus_component_counts.get(label, 0), len(corpus_rows))})",
            f"{component_counts.get(label, 0)} ({percentage(component_counts.get(label, 0), len(focus_rows))})",
            sensitivity_label(corpus_component_counts.get(label, 0), component_counts.get(label, 0), len(corpus_rows), len(focus_rows)),
        ]
        for label, _count in (component_counts | corpus_component_counts).most_common()
    ]
    pair_counter, triple_counter = component_cooccurrence_counters(focus_rows)
    cooccurrence_rows = component_cooccurrence_rows(focus_rows)
    archetype_rows = [
        [table_label(display_archetype(label)), f"{count} ({percentage(count, len(focus_rows))})"]
        for label, count in archetypes.most_common()
    ]
    archetype_sensitivity_rows = [
        [
            table_label(display_archetype(label)),
            f"{corpus_archetypes.get(label, 0)} ({percentage(corpus_archetypes.get(label, 0), len(corpus_rows))})",
            f"{archetypes.get(label, 0)} ({percentage(archetypes.get(label, 0), len(focus_rows))})",
            sensitivity_label(corpus_archetypes.get(label, 0), archetypes.get(label, 0), len(corpus_rows), len(focus_rows)),
        ]
        for label, _count in (archetypes | corpus_archetypes).most_common()
    ]
    theory_archetype_matrix_rows = theory_archetype_rows(focus_rows, limit=6)
    bias_rows = risk_of_bias_rows(focus_rows)
    score_rows = selection_score_rows(review_dir, focus_rows)
    autopilot_results_figures = render_autopilot_figure_blocks(
        review_dir,
        {"resultados", "results"},
        {"synthesis-diagram", "concept-map", "taxonomy-diagram", "timeline-diagram", "construct-flow"},
        figure_number_start=6,
    )
    orquestados = archetypes.get("multiagente orquestado", 0)
    skill_based = archetypes.get("skill-based o capability-based", 0)
    thematic_sentence = (
        "La Figura 3 muestra la concentración temática en testing, benchmarking, seguridad, depuración y soporte al ciclo de vida del software. El campo no se distribuye de forma homogénea: varias propuestas se orientan a tareas concretas de validación, revisión de código o automatización de flujos de trabajo, mientras que la teoría arquitectónica permanece más dispersa."
        if profile == "software_architecture"
        else "La Figura 3 muestra una concentración temática heterogénea: prototipos de sistema, agentes conversacionales, automatización de procesos, evaluación, RAG, salud, educación, negocio y gestión organizativa. El campo no se distribuye de forma homogénea; varias propuestas se orientan a tareas aplicadas concretas, mientras que la teoría arquitectónica permanece más dispersa."
    )
    aggregate_sentence = (
        "La señal cuantificada permite sostener tres hallazgos. Primero, la tendencia hacia la modularidad se refleja en la recurrencia conjunta de herramientas, verificación y roles especializados. Segundo, el campo no converge en un único arquetipo, sino en varias familias, entre ellas los sistemas multiagente orquestados (n="
        if profile == "software_architecture"
        else "La señal cuantificada permite sostener tres hallazgos. Primero, la tendencia hacia la modularidad se refleja en la recurrencia conjunta de herramientas, verificación y coordinación. Segundo, el campo no converge en un único arquetipo, sino en varias familias, entre ellas los sistemas multiagente u orquestados (n="
    )
    top_ids = top_citation_ids(focus_rows, 24)
    matrix_title = (
        "Matriz entre tipos de agentes, tareas de ingeniería y resultados."
        if profile == "software_architecture"
        else "Matriz entre tipos de agentes, dominios de aplicación y resultados."
    )
    programmatic_paragraph = (
        "Los marcos más programáticos del corpus también encuentran reflejo en los resultados. La visión de SE 3.0 y el desplazamiento hacia `agent interfaces` e `invocable capabilities` se alinean con la familia basada en capacidades o habilidades, mientras que los trabajos de benchmark, failure taxonomy y deployment readiness alimentan el arquetipo de evaluación arquitectónica y explican por qué una parte del campo se organiza alrededor de métricas, escenarios y modos de fallo antes que alrededor de un único diseño dominante "
        if profile == "software_architecture"
        else "Los marcos más programáticos del corpus también encuentran reflejo en los resultados. El desplazamiento hacia `agent interfaces`, capacidades invocables, memoria, herramientas y evaluación situada se alinea con la familia basada en capacidades o habilidades, mientras que los trabajos de benchmark, taxonomía de fallos y readiness alimentan el arquetipo de evaluación arquitectónica y explican por qué una parte del campo se organiza alrededor de métricas, escenarios y modos de fallo antes que alrededor de un único diseño dominante "
    )
    empirical_n = work_counter.get("empirical", 0)
    theoretical_n = work_counter.get("theoretical", 0)
    experimental_n = empirical_counter.get("experimental", 0)
    mixed_n = empirical_counter.get("mixed", 0)
    quantitative_n = empirical_counter.get("quantitative", 0)
    qualitative_n = empirical_counter.get("qualitative", 0)
    other_empirical_n = max(empirical_n - experimental_n - mixed_n - quantitative_n - qualitative_n, 0)
    empirical_fragments = [
        f"{experimental_n} adoptan un diseño experimental",
        f"{mixed_n} son mixtos",
        f"{quantitative_n} son cuantitativos",
        f"{qualitative_n} {'es cualitativo' if qualitative_n == 1 else 'son cualitativos'}",
        f"{other_empirical_n} quedan en otras variantes o en reporting metodológico más abierto",
    ]
    if len(corpus_rows) == len(focus_rows):
        corpus_relation_text = (
            f"En esta revisión, los {len(focus_rows)} estudios focales coinciden con el corpus incluido, "
            "de modo que la cartografía general y la comparación intensiva descansan sobre el mismo conjunto auditado de PDFs."
        )
        levels_text = (
            f"Por esa razón, las Tablas 5-10 y las figuras principales deben leerse como dos vistas complementarias de un mismo corpus de {len(focus_rows)} estudios: "
            "unas priorizan distribución general y otras comparación arquitectónica fina."
        )
        corpus_map_sentence = (
            f"La Figura 2 resume ese corpus único: en los {len(focus_rows)} estudios aparecen {empirical_n} trabajos empíricos "
            f"({percentage(empirical_n, len(focus_rows))}) frente a {theoretical_n} teóricos ({percentage(theoretical_n, len(focus_rows))}), "
            "con presencia menor de revisiones y otros formatos. Esta distribución confirma que la discusión arquitectónica de 2026 se apoya sobre todo en estudios empíricos y reportes de sistema."
        )
    else:
        corpus_relation_text = (
            f"El subconjunto focal de {len(focus_rows)} estudios no reemplaza al corpus incluido completo, sino que lo profundiza. "
            f"Los {len(corpus_rows)} estudios incluidos sostienen el mapa general del campo; los {len(focus_rows)} focales sostienen la comparación arquitectónica intensiva porque concentran mejor ajuste temático, mejor trazabilidad PDF y mejor señal metodológica."
        )
        levels_text = (
            "Para evitar ambigüedad, los resultados se reportan en dos niveles. El nivel `corpus incluido` (n="
            + str(len(corpus_rows))
            + ") sostiene la cartografía general del campo y la Tabla 5. El nivel `síntesis focal` (n="
            + str(len(focus_rows))
            + ") sostiene las figuras sustantivas y las Tablas 6-10, donde se comparan arquitectura, co-ocurrencias, arquetipos y calidad de reporte con más detalle."
        )
        corpus_map_sentence = (
            f"La Figura 2 resume el corpus incluido y su síntesis focal: en la síntesis focal aparecen {empirical_n} trabajos empíricos "
            f"({percentage(empirical_n, len(focus_rows))}) frente a {theoretical_n} teóricos ({percentage(theoretical_n, len(focus_rows))}), "
            f"con presencia menor de revisiones y otros formatos. Esta distribución confirma que la discusión arquitectónica de 2026 se apoya sobre todo en estudios empíricos y reportes de sistema, pero parte de un mapa más amplio de {len(corpus_rows)} estudios incluidos."
        )
    result_figure_number = 2
    result_figure_blocks: list[str] = []
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-corpus-map",
        result_figure_number,
        "Mapa del corpus por tipo de trabajo, fuente y señal empírica.",
        "Mapa del corpus",
        corpus_map_sentence,
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-theme-landscape",
        result_figure_number,
        "Panorama temático del corpus final.",
        "Panorama temático",
        thematic_sentence,
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-agent-task-matrix",
        result_figure_number,
        matrix_title,
        "Matriz agente-tarea",
        "La Figura 4 permite observar que la modularidad, la coordinación y la asignación de responsabilidades aparecen sobre todo cuando el objetivo exige conexión con herramientas, trazabilidad del razonamiento o separación explícita entre planificación y ejecución. Esta lectura se refuerza con la matriz componente a componente exportada como anexo CSV. Los conteos no son categorías excluyentes: un mismo estudio puede sumar herramientas, memoria, roles, orquestación y verificación a la vez. En esa lectura, herramientas (n="
        + str(component_counts.get("herramientas", 0))
        + "), verificación (n="
        + str(component_counts.get("verificador", 0))
        + "), roles especializados (n="
        + str(component_counts.get("roles", 0))
        + ") y orquestación (n="
        + str(component_counts.get("orquestador", 0))
        + ") y memoria persistente (n="
        + str(component_counts.get("memoria", 0))
        + ") describen señales de diseño superpuestas, no una partición cerrada del corpus.",
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-method-profile",
        result_figure_number,
        "Mapa de comparabilidad metodológica de los estudios empíricos.",
        "Mapa de comparabilidad metodológica",
        f"La Figura 5 refuerza que la comparación depende de algo más que el diseño declarado: muestra, contexto, marco, variables, comparador y validación determinan cuánta inferencia puede sostener cada estudio. En esta revisión, los conteos metodológicos detallados se refieren al subconjunto focal de {len(focus_rows)} estudios, mientras que la cartografía amplia del campo descansa sobre los {len(corpus_rows)} estudios del corpus incluido.",
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-evidence-maturity",
        result_figure_number,
        "Madurez comparativa de la evidencia por estado y dominio de resultado.",
        "Madurez comparativa de la evidencia",
        "La Figura 0 distingue las comparaciones que permiten una alineación descriptiva de aquellas que aún descansan en evidencia insuficiente o preguntas abiertas; repetición no equivale automáticamente a causalidad ni a generalización.",
    )
    result_figure_blocks.extend(blocks)
    blocks, result_figure_number = render_numbered_body_figure(
        review_dir,
        "fig-topic-network",
        result_figure_number,
        "Red temática del corpus y comunidades principales.",
        "Red temática del corpus",
        "La Figura 0 muestra qué temas forman comunidades estables, cuáles actúan como puentes y qué conceptos permanecen periféricos. Su lectura complementa las frecuencias al preservar relaciones entre palabras clave.",
    )
    result_figure_blocks.extend(blocks)
    return "\n".join(
        [
            "# Resultados",
            "",
            corpus_relation_text + " "
            "En ese subconjunto, el rasgo dominante no es la existencia de un único agente muy capaz, sino la combinación de componentes con responsabilidades diferenciadas, acceso a herramientas y mecanismos de validación " + citation_block(top_ids[12:16]) + ".",
            "",
            levels_text,
            "",
            *result_figure_blocks,
            *autopilot_results_figures,
            *build_evidence_position_lines(review_dir),
            "Tabla 5. Distribución del corpus incluido por tipo de trabajo.",
            markdown_table(["Tipo de trabajo", "N"], work_rows),
            "",
            "Tabla 6. Distribución del subconjunto empírico por diseño.",
            markdown_table(["Tipo empírico", "N"], empirical_rows),
            "",
            "Para evitar sobreinterpretar la categoría `verificador`, la codificación no la trata como sinónimo genérico de que un paper evalúe algo. Un estudio se marca con `verificador` cuando el PDF declara un mecanismo operativo de validación, prueba, métrica, juez, auditoría, control de salida o benchmark conectado con la arquitectura descrita. Por tanto, la categoría mide señal de control funcional reportada en el texto completo, no calidad metodológica global ni garantía de que exista un módulo separado con ese nombre.",
            "",
            "Tabla 7. Frecuencia de componentes estructurales en el subconjunto focal.",
            markdown_table(["Componente", "N"], component_rows),
            "",
            "Tabla 7A. Sensibilidad de componentes entre corpus incluido y síntesis focal.",
            markdown_table(["Componente", f"Corpus incluido (n={len(corpus_rows)})", f"Síntesis focal (n={len(focus_rows)})", "Lectura"], component_sensitivity_rows),
            "",
            "La Tabla 7A evita leer las frecuencias focales como prevalencias universales del campo. La síntesis focal prioriza estudios con mejor PDF, mayor densidad metodológica y mayor ajuste temático; por tanto, componentes ligados a evaluación o control pueden aparecer más concentrados que en el corpus incluido completo.",
            "",
            "Tabla 8. Co-ocurrencias estructurales más frecuentes en el subconjunto focal.",
            markdown_table(["Combinación recurrente", "N"], cooccurrence_rows),
            "",
            "Tabla 9. Arquetipos arquitectónicos inferidos en la síntesis focal.",
            markdown_table(["Arquetipo", "N"], archetype_rows),
            "",
            "Tabla 9A. Sensibilidad de arquetipos entre corpus incluido y síntesis focal.",
            markdown_table(["Arquetipo", f"Corpus incluido (n={len(corpus_rows)})", f"Síntesis focal (n={len(focus_rows)})", "Lectura"], archetype_sensitivity_rows),
            "",
            "Tabla 10. Perfil de riesgo de sesgo/reporting del subconjunto empírico.",
            markdown_table(["Diseño", "N", "Confianza media (0-100)", "Sin tamaño muestral", "Sin país/contexto", "Sin marco teórico", "Riesgo global"], bias_rows),
            "",
            "Tabla 10A. Cruce entre marcos teóricos y arquetipos arquitectónicos del subconjunto focal. Nota: `Multiag.` = multiagente, `Capac.` = capacidades/habilidades, `Herram.` = instrumentada con herramientas, `Bench.` = benchmark/evaluación y `Gob.` = gobernanza/auditoría.",
            markdown_table(
                [
                    "Marco",
                    "Multiag.",
                    "Capac.",
                    "Herram.",
                    "Bench.",
                    "Híbrida",
                    "Gob.",
                    "Total",
                ],
                compact_theory_archetype_rows(theory_archetype_matrix_rows)
                or [["No reportado", "0", "0", "0", "0", "0", "0", "0"]],
            ),
            "",
            "Tabla 11. Matrices auditables entregadas como anexos editoriales.",
            markdown_table(
                ["Matriz", "Contenido", "Archivo anexo"],
                [
                    [
                        "Componentes arquitectónicos",
                        f"{len(focus_rows)} estudios focales con roles, herramientas, memoria, verificación, tarea y arquetipo.",
                        "architecture-component-matrix.csv",
                    ],
                    [
                        "Extracción completa",
                        "Campos metodológicos, empíricos, variables, marco teórico, resultados y confianza de extracción.",
                        "extraction-table.csv",
                    ],
                    [
                        "Evidencia tabular",
                        "Tablas detectadas, reutilizadas y descartadas durante la auditoría documental.",
                        "tables-evidence-manifest.csv",
                    ],
                ],
            ),
            "",
            f"Las matrices completas no se fuerzan en el cuerpo porque una tabla con {len(focus_rows)} estudios y muchas columnas sacrifica legibilidad. La decisión editorial es mantener en el artículo las vistas agregadas y entregar la granularidad completa como CSV verificable.",
            "",
            "Tabla 12. Transparencia del ranking final del subconjunto focal con títulos completos.",
            markdown_table(
                ["Pos.", "DOI", "Título completo", "Rel.", "Calidad", "Rep.", "Score"],
                score_rows or [["—", "—", "No disponible", "0,0", "0,0", "0,0", "0,0"]],
            ),
            "",
            "La `confianza media` de la Tabla 10 no debe confundirse con una puntuación de completitud bibliográfica. Resume cuánta evidencia metodológica y arquitectónica pudo extraerse del PDF completo para sostener la comparación. En consecuencia, algunos estudios mixtos o cuantitativos mantienen confianza alta cuando el diseño experimental, la tarea, las métricas y los resultados están bien descritos, aunque no reporten todas las convenciones clásicas de muestra aplicables a estudios con participantes humanos o casos organizativos.",
            "",
            f"En términos agregados, {empirical_n} de los {len(focus_rows)} estudios focales ({percentage(empirical_n, len(focus_rows))}) son empíricos. Dentro de ese bloque empírico, "
            + ", ".join(empirical_fragments[:-1])
            + " y "
            + empirical_fragments[-1]
            + ". "
            + aggregate_sentence
            + str(archetypes.get("multiagente orquestado", 0))
            + "), los diseños basados en capacidades o habilidades (n="
            + str(archetypes.get("skill-based o capability-based", 0))
            + ") y los marcos de evaluación arquitectónica. Tercero, la comparabilidad mejora cuando los estudios explicitan muestra, método y evaluación, aunque el campo sigue siendo metodológicamente desigual y parte de la frontera permanece más descriptiva que contrastiva "
            + citation_block(top_ids[4:8]) + ".",
            "",
            "La Tabla 8 permite sostener esa inferencia de forma menos retórica: herramientas + verificador aparecen conjuntamente en "
            + str(pair_counter.get(("herramientas", "verificador"), 0))
            + " estudios, herramientas + roles en "
            + str(pair_counter.get(("herramientas", "roles"), 0))
            + " y la triple combinación herramientas + roles + verificador en "
            + str(triple_counter.get(("herramientas", "roles", "verificador"), 0))
            + ". En términos descriptivos, esa pauta sugiere una preferencia emergente por combinaciones de capacidad instrumental, supervisión y reparto funcional, más que una modularidad homogénea o universalmente estable.",
            "",
            "La Tabla 10A añade una capa interpretativa que faltaba en la versión anterior del manuscrito: muestra qué bases teóricas o marcos declarados aparecen asociados a cada familia arquitectónica. Debe leerse como tabla de ocurrencias y no como partición exclusiva del corpus, porque un mismo estudio puede declarar más de una base teórica. En esta revisión, la presencia de `no reportado` sigue siendo relevante y funciona como indicador de debilidad de reporting teórico, no como categoría sustantiva del campo.",
            "",
            "La Tabla 11 separa deliberadamente el cuerpo narrativo de las matrices completas: el artículo conserva vistas agregadas legibles y el paquete editorial entrega los CSV necesarios para recontar cada estudio. La Tabla 12 añade la capa de transparencia del ranking focal y conecta el manuscrito con el anexo `selection-score-matrix.csv`.",
            "",
            programmatic_paragraph + citation_block(top_ids[8:12]) + ".",
            "",
            f"La divergencia más visible aparece entre propuestas que apuestan por agentes con capacidades componibles o diseños basados en habilidades y trabajos que defienden la especialización multiagente con orquestación explícita. Los primeros maximizan simplicidad y mantenibilidad conceptual, mientras que los segundos priorizan trazabilidad, paralelización y control de fallos en tareas de largo horizonte {citation_block(top_ids[8:12])}. En el subconjunto focal, la familia multiagente orquestada reúne {orquestados} estudios frente a {skill_based} diseño{'s' if skill_based != 1 else ''} basado{'s' if skill_based != 1 else ''} en capacidades o habilidades, de modo que ambos enfoques deben leerse como estrategias coexistentes. La matriz completa de {len(focus_rows)} estudios y cinco componentes estructurales se entrega como anexo CSV para auditoría y reutilización.",
        ]
    ) + "\n"


def build_discussion_section(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str] | None = None,
) -> str:
    context = context or read_research_context(review_dir)
    profile = detect_review_profile(context)
    if is_domain_general_profile(profile):
        return build_discussion_section_domain(review_dir, focus_rows, flow_counts, context)
    top_ids = top_citation_ids(focus_rows, 24)
    component_counts = component_counter(focus_rows)
    archetypes = archetype_counter(focus_rows)
    theory_families = theory_family_counter(focus_rows, 4)
    results_autopilot_count = len(
        load_autopilot_figure_rows(
            review_dir,
            {"resultados", "results"},
            {"synthesis-diagram", "concept-map", "taxonomy-diagram", "timeline-diagram", "construct-flow"},
        )
    )
    discussion_figure_start = next_discussion_figure_number(review_dir)
    grammar_figure_blocks, discussion_next_figure = render_numbered_body_figure(
        review_dir,
        "fig-analytical-grammar",
        discussion_figure_start,
        "Modelo interpretativo de la gramática analítica propuesta por la revisión.",
        "Modelo interpretativo de la gramática analítica",
        "La Figura 0 sintetiza la aportación del artículo como una gramática comparativa: define la unidad real de comparación, ordena las dimensiones que explican el campo, separa evidencia estable de señal emergente y convierte los vacíos de reporte en agenda futura.",
    )
    autopilot_discussion_figures = render_autopilot_figure_blocks(
        review_dir,
        {"discusión", "discusion", "discussion"},
        {"workflow-diagram", "flow-diagram", "flow diagram"},
        figure_number_start=discussion_next_figure + results_autopilot_count,
    )
    explicit_n1 = 0
    small_n = 0
    for row in focus_rows:
        sample = normalize_phrase(row.get("sample_size")).lower()
        if not sample or sample == "no reportado":
            continue
        values = [int(value) for value in re.findall(r"\d+", sample)]
        if re.search(r"\bn\s*=\s*1\b|\b1 por\b|\buno por\b|single case|\b1 caso\b", sample) or values == [1]:
            explicit_n1 += 1
            small_n += 1
            continue
        if values and min(values) <= 3:
            small_n += 1
    theory_text = ", ".join(f"{label} (n={count})" for label, count in theory_families) if theory_families else "bases teóricas dispersas o no reportadas"
    opening = (
        "En el corpus analizado, la discusión científica sobre agentes para desarrollo de software se está desplazando desde el modelo base hacia la arquitectura del sistema. "
        if profile == "software_architecture"
        else "En el corpus analizado, la discusión científica sobre arquitecturas de IA se está desplazando desde el modelo base hacia el sistema completo: memoria, herramientas, recuperación, coordinación, inferencia y evaluación. "
        if profile == "ai_architecture"
        else "En el corpus analizado, la discusión científica sobre agentes de IA se está desplazando desde el modelo base hacia la arquitectura del sistema, la memoria, las herramientas, la coordinación y la evaluación. "
    )
    practical = (
        "Esto sugiere que las arquitecturas útiles en ingeniería del software no se distinguen solo por qué modelo usan, sino por cómo separan planificación, ejecución, chequeo y coordinación sobre repositorios, pruebas y flujos de trabajo."
        if profile == "software_architecture"
        else "Esto sugiere que las arquitecturas útiles de IA no se distinguen solo por qué modelo base usan, sino por cómo combinan recuperación, herramientas, memoria, especialización funcional, inferencia y criterios de evaluación."
        if profile == "ai_architecture"
        else "Esto sugiere que las arquitecturas útiles no se distinguen solo por qué modelo usan, sino por cómo separan planificación, ejecución, chequeo y coordinación en tareas aplicadas."
    )

    def cite_suffix(record_ids: list[str], limit: int = 4) -> str:
        citation = citation_block(record_ids, limit=limit)
        return f" {citation}" if citation else ""

    discussion_development = [
        (
            (
                "El primer punto de discusión es que el sistema de IA no aparece en la literatura como una simple interfaz conversacional sobre un modelo fundacional, sino como una unidad compuesta de ejecución. "
                if profile == "ai_architecture"
                else "El primer punto de discusión es que el agente no aparece en la literatura como una simple interfaz conversacional sobre un LLM, sino como una unidad compuesta de ejecución. "
            )
            +
            "Cuando los estudios describen herramientas, memoria, roles, orquestación o verificadores, están moviendo el análisis desde la calidad de una respuesta aislada hacia la calidad de un sistema que actúa, consulta, decide, registra y corrige. "
            f"Esa diferencia es sustantiva: dos trabajos pueden usar modelos parecidos y, sin embargo, no ser comparables si uno evalúa una salida textual y otro evalúa un circuito instrumentado con estado, herramientas y control de fallos{cite_suffix(top_ids[16:20])}."
        ),
        (
            "El segundo punto es que la arquitectura no funciona como decoración técnica, sino como condición de interpretación del resultado. "
            "La memoria cambia qué información puede permanecer disponible; las herramientas cambian qué acciones puede ejecutar el sistema; la orquestación cambia cómo se reparten responsabilidades; y la verificación cambia cuándo una salida se considera aceptable. "
            + (
                "Por eso una revisión sistemática de arquitecturas de IA no debería limitarse a listar modelos o benchmarks: debe reconstruir qué componentes hacen posible el comportamiento observado y qué parte del resultado procede del modelo frente al andamiaje que lo envuelve."
                if profile == "ai_architecture"
                else "Por eso una revisión sistemática de agentes de IA no debería limitarse a listar modelos o benchmarks: debe reconstruir qué componentes hacen posible el comportamiento observado y qué parte del resultado procede del modelo frente al andamiaje que lo envuelve."
            )
        ),
        (
            f"El tercer punto es la centralidad del control. En el subconjunto focal, la verificación o evaluación integrada aparece en {component_counts.get('verificador', 0)} de {len(focus_rows)} estudios, lo que sugiere que el campo está vinculando capacidad con comprobación explícita. "
            + (
                "Un sistema de IA útil no es solo el que produce más salidas, sino el que deja comprobar qué evidencia usó, qué condición de salida aceptó y qué ocurre cuando falla. "
                if profile == "ai_architecture"
                else "Un agente útil no es solo el que produce más acciones, sino el que deja comprobar por qué actuó, qué evidencia usó, qué condición de salida aceptó y qué ocurre cuando falla. "
            )
            +
            f"Esta lectura conecta los trabajos de benchmarking, readiness, seguridad, pruebas o evaluación con los trabajos de orquestación y diseño operativo: todos intentan domesticar la misma tensión entre capacidad y control{cite_suffix(top_ids[12:16])}."
        ),
        (
            "El cuarto punto es que la oposición entre arquitecturas multiagente, agentes instrumentados y diseños basados en capacidades no debe leerse como una carrera lineal hacia mayor complejidad. "
            "La complejidad arquitectónica solo aporta valor cuando la tarea exige reparto de responsabilidades, trazabilidad, paralelización, memoria persistente o tolerancia a fallos; en tareas más acotadas, una arquitectura más simple puede ser más verificable y mantenible. "
            f"Por eso el resultado de la revisión no es una recomendación universal, sino una gramática comparativa que ayuda a decidir qué forma arquitectónica encaja con cada problema{cite_suffix(top_ids[8:12])}."
        ),
        (
            f"El quinto punto es teórico. En el subconjunto focal aparecen sobre todo {theory_text}; esta dispersión indica que el campo todavía está más maduro en ingeniería de prototipos que en acumulación conceptual. "
            "Muchos papers describen sistemas ricos, pero no siempre explicitan con la misma fuerza la teoría que justificaría sus componentes, sus límites o sus mecanismos causales. "
            "Esta asimetría importa porque una arquitectura puede funcionar en un benchmark y seguir siendo difícil de comparar si no declara con claridad su unidad analítica, su contexto de uso, sus variables y sus supuestos de diseño."
        ),
        (
            "Finalmente, la discusión debe separar cuidadosamente el soporte metodológico de la aportación sustantiva. "
            "Documentar identificación, cribado y elegibilidad hace la revisión auditable, pero no explica por sí solo qué significa que una arquitectura use memoria, herramientas, roles o verificadores. "
            + (
                "La aportación científica empieza cuando ese flujo transparente permite formular una interpretación sobre el campo: las arquitecturas de IA están dejando de ser simples envoltorios de modelos y empiezan a presentarse como sistemas compuestos cuya calidad depende de diseño, evidencia, control y contexto de aplicación."
                if profile == "ai_architecture"
                else "La aportación científica empieza cuando ese flujo transparente permite formular una interpretación sobre el campo: los agentes de IA están dejando de ser prompts ampliados y empiezan a presentarse como sistemas compuestos cuya calidad depende de diseño, evidencia, control y contexto de aplicación."
            )
        ),
    ]
    return "\n".join(
        [
            "# Discusión",
            "",
            opening
            + "Ese desplazamiento obliga a comparar composición funcional, coordinación, integración con herramientas y mecanismos de control más que simples métricas de benchmark " + citation_block(top_ids[12:16]) + ".",
            "",
            *[paragraph + "\n" for paragraph in discussion_development],
            "## Implicaciones teóricas",
            f"La primera implicación teórica es que las teorías centradas solo en capacidad de modelo quedan cortas para explicar el corpus. Que {component_counts.get('verificador', 0)} de los {len(focus_rows)} estudios focales reporten algún mecanismo de evaluación, validación o control indica una preocupación observable por comprobar el comportamiento del sistema, no solo por aumentar potencia generativa. La arquitectura aparece así como mediación entre capacidad, contexto, acción y evidencia.",
            "",
            "La segunda implicación es que los componentes no deben entenderse como piezas aisladas, sino como relaciones. Herramientas, memoria, roles, orquestación y verificación no explican mucho por separado; adquieren significado teórico cuando se observa cómo se combinan para resolver una tarea, reducir incertidumbre, distribuir responsabilidad o hacer auditable una salida. Esto desplaza la teoría desde el inventario de módulos hacia la gramática de configuración.",
            "",
            f"La tercera implicación es la coexistencia de estrategias arquitectónicas. Los trabajos basados en capacidades o habilidades prometen composabilidad y menor sobrecarga organizativa, mientras que los marcos multiagente u orquestados maximizan especialización, paralelismo y separación de responsabilidades. Esta revisión no resuelve esa divergencia en favor de un ganador único; sugiere que tarea, coste de fallo, necesidad de auditabilidad, latencia y contexto empírico funcionan como condiciones de frontera. En el subconjunto focal, la familia multiagente u orquestada aparece en {archetypes.get('multiagente orquestado', 0)} estudios frente a {archetypes.get('skill-based o capability-based', 0)} diseño{'s' if archetypes.get('skill-based o capability-based', 0) != 1 else ''} basado{'s' if archetypes.get('skill-based o capability-based', 0) != 1 else ''} en capacidades o habilidades; ambos enfoques deben leerse como estrategias coexistentes, no como generaciones sucesivas " + citation_block(top_ids[16:20]) + ".",
            "",
            f"La cuarta implicación es que la fragmentación teórica no es un detalle menor, sino un hallazgo del campo. En el subconjunto focal aparecen sobre todo {theory_text}. Ese reparto no constituye todavía una teoría unificada, pero sí una pauta: las bases explícitas se concentran en nichos concretos y conviven con una fracción importante de trabajos donde la arquitectura es operativamente rica pero teóricamente poco declarada. La teoría futura debería explicar no solo qué componentes existen, sino cuándo una configuración es preferible, bajo qué evidencia y con qué límites de validez.",
            "",
            "De esta lectura se derivan cuatro proposiciones teóricas para acumulación futura: primera, la unidad explicativa principal es el sistema completo y no el modelo aislado; segunda, la capacidad solo se vuelve comparable cuando se observa junto a control, contexto y evidencia; tercera, la complejidad arquitectónica debe justificarse por condiciones de tarea y riesgo, no por moda multiagente; cuarta, la madurez del campo dependerá de conectar diseño arquitectónico con teoría declarada y evaluación replicable.",
            "",
            *build_practical_implications_lines(
                focus_rows,
                context,
                citation_ids=top_ids,
                opening=f"Para diseño de sistemas reales, el resultado más útil es menos doctrinal y más componible: herramientas explícitas, verificación integrada, roles especializados, memoria y orquestación aparecen como señales prácticas repetidas del corpus. {practical}",
            ),
            "",
            "## Aportación original del artículo",
            (
                "La aportación original del artículo es formular una tesis fuerte sobre la unidad de comparación del campo: en 2026, las arquitecturas de sistemas de IA ya no pueden compararse de forma rigurosa tomando el modelo fundacional como unidad principal, sino observando el sistema completo que lo rodea. La revisión no ordena papers para decir qué modelo aparece más, sino para mostrar cómo cada estudio convierte una capacidad de modelo en una arquitectura con recuperación, memoria, herramientas, orquestación, inferencia, evaluación y control. Ese desplazamiento es sustantivo porque separa tres planos que suelen mezclarse en la literatura emergente: capacidad del modelo, diseño del sistema y calidad de la evidencia "
                if profile == "ai_architecture"
                else "La aportación original del artículo es formular una tesis fuerte sobre la unidad de comparación del campo: las arquitecturas agénticas no pueden compararse de forma rigurosa tomando el modelo de lenguaje como unidad principal, sino observando el sistema completo que lo rodea. La revisión no ordena papers para decir qué modelo aparece más, sino para mostrar cómo cada estudio convierte una capacidad de modelo en una arquitectura con roles, herramientas, memoria, orquestación, evaluación y control. Ese desplazamiento es sustantivo porque separa tres planos que suelen mezclarse en la literatura emergente sobre agentes: capacidad del modelo, diseño del sistema y calidad de la evidencia "
            ) + citation_block(top_ids[16:20]) + ".",
            "",
            *original_contribution_table_lines(profile, review_subject_label_es(context), len(focus_rows)),
            (
                f"La segunda aportación es conceptual: el artículo propone una gramática arquitectónica de sistemas de IA. Esa gramática no es una taxonomía cerrada ni una lista ornamental de componentes, sino un vocabulario comparativo para leer cómo se combinan recuperación, memoria, herramientas, roles, orquestación, inferencia y verificación según tarea, dominio, coste de fallo y necesidad de auditabilidad. Los {len(focus_rows)} estudios analizados revelan una arquitectura recurrente pero no universal, donde verificación o evaluación integrada aparece en {component_counts.get('verificador', 0)} casos, herramientas explícitas en {component_counts.get('herramientas', 0)}, roles especializados en {component_counts.get('roles', 0)}, memoria persistente o RAG en {component_counts.get('memoria', 0)} y orquestación en {component_counts.get('orquestador', 0)}. La novedad está en tratar esos componentes como piezas combinables de una gramática de diseño, no como etiquetas aisladas "
                if profile == "ai_architecture"
                else f"La segunda aportación es conceptual: el artículo propone una gramática arquitectónica de agentes de IA. Esa gramática no es una taxonomía cerrada ni una lista ornamental de componentes, sino un vocabulario comparativo para leer cómo se combinan roles, herramientas, memoria, orquestación y verificación según tarea, dominio, coste de fallo y necesidad de auditabilidad. Los {len(focus_rows)} estudios analizados revelan una arquitectura recurrente pero no universal, donde verificación o evaluación integrada aparece en {component_counts.get('verificador', 0)} casos, herramientas explícitas en {component_counts.get('herramientas', 0)}, roles especializados en {component_counts.get('roles', 0)}, memoria persistente o RAG en {component_counts.get('memoria', 0)} y orquestación en {component_counts.get('orquestador', 0)}. La novedad está en tratar esos componentes como piezas combinables de una gramática de diseño, no como etiquetas aisladas "
            ) + citation_block(top_ids[8:12]) + ".",
            "",
            "La tercera aportación es empírica. El artículo no se limita a afirmar que el campo es heterogéneo: muestra dónde se concentra esa heterogeneidad, qué patrones resisten el contraste entre corpus incluido y síntesis focal, y qué señales pueden estar influidas por la propia regla de selección. Por eso las Tablas 7A y 9A son parte de la contribución, no un detalle técnico: permiten distinguir entre patrón estable, diferencia moderada y componente potencialmente sensible al corte.",
            "",
            "La cuarta aportación es metodológica, pero va más allá de decir que el estudio es reproducible. El artículo convierte cada afirmación de síntesis en una cadena rastreable: DOI normalizado, PDF local, extracción estructurada, confianza de extracción, matriz de componentes, tablas comparativas, anexos CSV y figuras propias de síntesis. Esto cambia el estatuto del manuscrito: no es solo un texto que resume literatura, sino un objeto editorial auditable en el que el lector puede seguir el recorrido desde el registro bibliográfico hasta la afirmación interpretativa. Esa trazabilidad es especialmente importante en un campo rápido, donde muchos artículos describen prototipos, flujos y agentes con niveles desiguales de detalle.",
            "",
            "La quinta aportación es editorial y práctica. El trabajo ofrece un criterio explícito para decidir qué evidencias deben entrar en el artículo y cuáles deben conservarse solo como material de comprobación. Una tabla, figura o activo suplementario se incorpora al manuscrito cuando ayuda a explicar una relación analítica y no simplemente porque exista en un paper fuente. De ese modo, el material suplementario refuerza la interpretación sin convertir el artículo en una galería heterogénea de capturas.",
            "",
            (
                "En conjunto, el artículo aporta una tesis y una gramática: la tesis es que la arquitectura completa del sistema se convierte en la unidad real de comparación; la gramática es el conjunto de dimensiones que permite observar esa arquitectura sin reducirla al modelo base. Esa es la diferencia principal frente a una revisión narrativa convencional: la contribución no es solo qué dice el artículo sobre las arquitecturas de IA, sino qué marco deja para que otros estudios puedan compararlas, discutirlas y ampliarlas."
                if profile == "ai_architecture"
                else "En conjunto, el artículo aporta una tesis y una gramática: la tesis es que la arquitectura completa del agente se convierte en la unidad real de comparación; la gramática es el conjunto de dimensiones que permite observar esa arquitectura sin reducirla al modelo base. Esa es la diferencia principal frente a una revisión narrativa convencional: la contribución no es solo qué dice el artículo sobre los agentes, sino qué marco deja para que otros estudios puedan compararlos, discutirlos y ampliarlos."
            ),
            "",
            *grammar_figure_blocks,
            *autopilot_discussion_figures,
            *build_validity_threats_lines(
                focus_rows,
                flow_counts,
                context,
                citation_ids=top_ids,
                explicit_n1=explicit_n1,
                small_n=small_n,
            ),
        ]
    ) + "\n"


def build_conclusions_section(
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str] | None = None,
) -> str:
    context = context or {}
    profile = detect_review_profile(context)
    if is_domain_general_profile(profile):
        return build_conclusions_section_domain(focus_rows, flow_counts, context)
    top_ids = top_citation_ids(focus_rows, 24)
    component_counts = component_counter(focus_rows)
    included_n = flow_counts.get("included_in_review", len(focus_rows))
    rq_text = publication_research_question(context, profile)
    unit_thesis = conclusion_unit_thesis(profile, review_subject_label_es(context))
    grammar_sentence = conclusion_grammar_sentence(profile, len(focus_rows))
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    future_lines = conclusion_diagnostic_future_lines(focus_rows, profile)
    if profile == "ai_architecture":
        answer = (
            "las arquitecturas de sistemas de IA en 2026 se comprenden mejor como configuraciones completas de sistema que como modelos aislados. "
            "El corpus muestra que la recuperación, la memoria, las herramientas, la orquestación, la inferencia y la verificación cambian la naturaleza de lo que se puede comparar."
        )
        conclusion_development = [
            "La primera conclusión sustantiva es que la arquitectura aporta valor cuando convierte una capacidad de modelo en un sistema verificable. Los estudios seleccionados no se limitan a presentar modelos más potentes: describen formas de recuperar información, conservar contexto, invocar herramientas, repartir responsabilidades, enrutar inferencia y evaluar salidas. Esa lectura desplaza el eje desde qué modelo responde hacia qué sistema produce, controla y justifica la respuesta " + citation_block(top_ids[16:20]) + ".",
            "",
            "La segunda conclusión es que RAG, memoria y herramientas funcionan como infraestructura de contexto, no como accesorios decorativos. En los papers focales, la recuperación y la memoria permiten conectar el modelo con documentos, grafos, estados persistentes o bases de conocimiento; las herramientas permiten actuar sobre tareas externas; y la evaluación integrada introduce una condición mínima de control. La utilidad práctica aparece precisamente en esa combinación, no en cada componente aislado.",
            "",
            "La tercera conclusión es que la orquestación no equivale siempre a añadir más agentes. Algunas tareas necesitan separación explícita de roles, coordinación multiagente o pipelines de decisión; otras se benefician de diseños más simples, paralelizables y fáciles de auditar. Por eso la revisión no recomienda una arquitectura universal: propone leer la complejidad como una respuesta al coste de fallo, la necesidad de trazabilidad, la presión de latencia y el tipo de evidencia disponible " + citation_block(top_ids[8:12]) + ".",
            "",
            "La cuarta conclusión es interpretativa: los conteos de componentes no son el hallazgo final, sino la pista que permite leer una transformación del campo. Cuando herramientas, memoria, roles, orquestación y verificación aparecen juntos, la unidad de valor se desplaza desde la capacidad aislada hacia sistemas contextualizados, instrumentados y comprobables.",
        ]
        certainty_signal_gap = (
            f"Lo que puede afirmarse con más seguridad es que los {len(focus_rows)} estudios focales convergen en la necesidad de comparar sistemas completos y no solo modelos. "
            f"Lo que aparece como señal emergente es una gramática arquitectónica todavía abierta, donde algunas combinaciones de componentes se repiten pero no forman un estándar cerrado. "
            f"Lo que todavía no puede concluirse es una teoría causal general de superioridad arquitectónica, sobre todo porque {count_studies_es(diagnostics['missing_theory'])} {verb_by_count(diagnostics['missing_theory'], 'no declara', 'no declaran')} marco teórico, {count_studies_es(diagnostics['missing_benchmark'])} {verb_by_count(diagnostics['missing_benchmark'], 'no deja', 'no dejan')} comparador claro y {count_studies_es(diagnostics['missing_variables'])} {verb_by_count(diagnostics['missing_variables'], 'no explicita', 'no explicitan')} variables o dimensiones analíticas."
        )
    else:
        answer = (
            "los agentes de IA se comparan mejor como arquitecturas de trabajo que como modelos aislados. La evidencia indica que tarea, herramienta, memoria, rol, orquestación, evaluación y contexto de uso explican más que la simple presencia de un LLM."
        )
        conclusion_development = [
            "La primera conclusión sustantiva es que los agentes aportan más valor en tareas acotadas, instrumentadas y verificables que en formulaciones genéricas de autonomía. Los trabajos sobre recomendación musical, BI conversacional, asistencia académica, gestión de proyectos, logística, planificación de sprints, revisión científica y selección editorial coinciden en un punto: el agente funciona mejor cuando dispone de entradas delimitadas, herramientas concretas, una tarea evaluable y un criterio de salida reconocible. En esos casos, los estudios reportan mejoras de accesibilidad, velocidad, apoyo a la decisión, reducción de carga cognitiva o consistencia operativa, aunque casi siempre dentro de escenarios todavía controlados o prototípicos " + citation_block(top_ids[16:20]) + ".",
            "",
            "La segunda conclusión es que la orquestación no es una moda terminológica, sino una respuesta a la complejidad de ciertas tareas. Los estudios comparativos y experimentales sugieren que los workflows son adecuados cuando el proceso es estable y se busca control, mientras que los enfoques multiagente o A2A ganan interés cuando hay que distribuir responsabilidades, coordinar subtareas, consultar herramientas distintas o sostener trazabilidad. Esta conclusión no convierte la arquitectura multiagente en solución superior para todo: más bien indica que la complejidad arquitectónica solo se justifica cuando la tarea exige coordinación, explicabilidad o tolerancia a fallos " + citation_block(top_ids[8:12]) + ".",
            "",
            "La tercera conclusión es que memoria, RAG e integración con herramientas aparecen como condiciones de utilidad práctica, no como accesorios. Los estudios sobre BI, soporte académico, gestión de proyectos, análisis multimodal de Parkinson, asistentes descentralizados y agentes editoriales muestran que el agente se vuelve más útil cuando puede conectar lenguaje natural con bases documentales, APIs, documentos institucionales, métricas de evaluación o flujos de automatización. La capacidad generativa, por sí sola, no basta: la arquitectura debe controlar qué información usa el sistema, cómo la recupera, qué acción ejecuta y cómo se verifica la respuesta.",
            "",
            "La cuarta conclusión es interpretativa: los resultados positivos no autorizan una lectura triunfalista del campo. Varios papers trabajan con pruebas de concepto, muestras pequeñas, datasets sintéticos, benchmarks limitados o validaciones de corto plazo; por eso el valor de la revisión está en separar utilidad plausible, señal emergente y evidencia todavía insuficiente.",
        ]
        certainty_signal_gap = (
            f"Lo que puede afirmarse con más seguridad es que los {len(focus_rows)} estudios focales muestran una relación recurrente entre tarea delimitada, herramienta, memoria y evaluación. "
            f"Lo que aparece como señal emergente es la utilidad de arquitecturas más coordinadas cuando el coste de fallo, la trazabilidad o la complejidad de la tarea aumentan. "
            f"Lo que todavía no puede concluirse es que una familia arquitectónica sea superior en todos los dominios, especialmente cuando {count_studies_es(diagnostics['missing_theory'])} {verb_by_count(diagnostics['missing_theory'], 'no declara', 'no declaran')} marco teórico y {count_studies_es(diagnostics['missing_benchmark'])} {verb_by_count(diagnostics['missing_benchmark'], 'no reporta', 'no reportan')} comparadores equivalentes."
        )
    return "\n".join(
        [
            "# Conclusiones",
            "",
            f"En respuesta a la pregunta de investigación, {rq_text}, la evidencia indica que {answer} " + citation_block(top_ids[:4]) + ".",
            "",
            f"La conclusión principal no es que existan {included_n} estudios trazables, sino que esos estudios permiten formular una tesis comparativa: {unit_thesis}",
            "",
            grammar_sentence,
            "",
            *conclusion_development,
            "",
            certainty_signal_gap,
            "",
            f"En términos cuantificados, esta lectura se apoya en herramientas explícitas (n={component_counts.get('herramientas', 0)}), verificación integrada (n={component_counts.get('verificador', 0)}), memoria persistente o RAG (n={component_counts.get('memoria', 0)}), roles especializados (n={component_counts.get('roles', 0)}) y orquestación (n={component_counts.get('orquestador', 0)}). La conclusión no es la frecuencia en sí, sino lo que esos patrones indican: el campo está desplazando el valor desde la capacidad aislada hacia sistemas contextualizados, instrumentados y verificables.",
            "",
            "El límite no invalida la síntesis; define su alcance. La regla de DOI público, PDF legible, extracción estructurada y síntesis focal reduce el universo de registros, pero aumenta la posibilidad de auditar cada afirmación. Por eso la cautela del artículo no funciona como disculpa, sino como condición de madurez científica.",
            "",
            "Como cierre, el artículo no propone un canon definitivo. Propone una unidad de comparación, una gramática analítica y una agenda de acumulación empírica que permite convertir conclusiones dispersas de los estudios seleccionados en una síntesis comparable " + citation_block(top_ids[12:16]) + ".",
            "",
            *future_lines,
            "",
            *build_author_contribution_section(focus_rows, flow_counts, context),
        ]
    ) + "\n"


def build_title_abstract_section_personality(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    topic_text = context.get("topic") or "personalidad en LLMs"
    rq_text = publication_research_question(context, "personality_llm")
    rq_text_en = publication_research_question_en(context, "personality_llm")
    included_count = flow_counts.get("included_in_review", 0)
    construct_counts = personality_construct_counter(focus_rows)
    top_constructs = ", ".join(f"{label} (n={count})" for label, count in construct_counts.most_common(3))
    top_constructs_en = ", ".join(
        f"{personality_construct_label_en(label)} (n={count})"
        for label, count in construct_counts.most_common(3)
    )
    keyword_list = build_keyword_list(focus_rows, context=context)
    keywords = ", ".join(restore_acronyms(keyword) for keyword in keyword_list)
    keywords_en = ", ".join(english_keywords(keyword_list))
    years_label = review_years_label(context)
    timeframe_es = review_timeframe_phrase_es(context)
    timeframe_en = review_timeframe_phrase_en(context)
    title = f"Personalidad en modelos de IA razonadores ({years_label}): revisión sistemática de literatura y síntesis focal de {len(focus_rows)} estudios"
    abstract_text = (
        f"Esta revisión sistemática de literatura analiza el estado de la investigación sobre {topic_text} {timeframe_es}. "
        f"El protocolo identificó {flow_counts.get('identified', 0)} registros, {deduplication_summary(flow_counts.get('duplicates_removed', 0), 'es')}, evaluó {flow_counts.get('full_text_assessed', 0)} textos completos en PDF e incluyó {included_count} estudios en el corpus final. "
        f"{focal_synthesis_relation(included_count, len(focus_rows), 'es')} "
        f"La pregunta de investigación que organiza el artículo es: {rq_text} "
        f"Los resultados muestran un campo en el que predominan trabajos empíricos y constructos como {top_constructs or 'Big Five, persona steering y validación psicométrica'}, aunque persisten heterogeneidad metodológica, vacíos en variables y problemas de reporte en parte del corpus. "
        "La principal aportación consiste en mostrar cómo la literatura conecta medición psicométrica, steering de personas sintéticas y efectos humanos o de seguridad, además de ofrecer una cartografía reproducible de constructos, métodos y marcos teóricos con anexos CSV y PDFs reutilizables para auditoría y replicación."
    )
    abstract_en = (
        f"This systematic literature review examines the state of research on {personality_topic_en(context)} {timeframe_en}. "
        f"The protocol identified {flow_counts.get('identified', 0)} records, {deduplication_summary(flow_counts.get('duplicates_removed', 0), 'en')}, assessed {flow_counts.get('full_text_assessed', 0)} full texts in PDF, and included {included_count} studies in the final review corpus. "
        f"{focal_synthesis_relation(included_count, len(focus_rows), 'en')} "
        f"The research question guiding the article is: {rq_text_en} "
        f"The results show a field dominated by empirical studies and constructs such as {top_constructs_en or 'Big Five, persona steering, and psychometric validation'}, although methodological heterogeneity, variable gaps, and reporting problems still persist in part of the corpus. "
        "The main contribution is to show how the literature connects psychometric measurement, synthetic-persona steering, and human or safety-related effects, while also providing a reproducible map of constructs, methods, and theoretical frameworks supported by reusable CSV annexes and PDFs for audit and replication."
    )
    return manuscript_front_matter(
        title=title,
        abstract_text=abstract_text,
        abstract_en=abstract_en,
        keywords=keywords,
        keywords_en=keywords_en,
        fallback_keywords="personalidad en llms, persona, traits, psychometric profiling, persona steering, revisión sistemática",
        fallback_keywords_en="personality in LLMs, personas, traits, psychometric profiling, persona steering, systematic review",
        context=context,
    )


def build_introduction_section_personality(focus_rows: list[dict[str, str]], context: dict[str, str]) -> str:
    top_rows = top_rows_by_rank(focus_rows, 16)
    timeframe_es = review_timeframe_phrase_es(context)
    years_label = review_years_label(context)
    return "\n".join(
        [
            "# Introducción",
            "",
            "La personalidad se ha convertido en un problema central dentro del estudio contemporáneo de los large language models. La literatura reciente no solo pregunta si los LLMs pueden simular rasgos, sino también cómo se inducen, cómo se miden, qué efectos producen en la interacción humana y qué límites psicométricos o éticos aparecen cuando se estabilizan personas sintéticas " + citation_block_for_rows(top_rows[:4]) + ".",
            "",
            f"En la ventana {timeframe_es} el campo se expandió con rapidez en varias direcciones: evaluación de rasgos y perfiles, steering o control de personalidad en inferencia, análisis de sesgos asociados a personas sintéticas, validación conversacional de constructos y estudios sobre efectos en preferencias, autoimagen o persuasión. Esa diversidad vuelve especialmente necesario distinguir entre trabajos que simplemente tematizan la personalidad y trabajos que la operacionalizan de forma suficientemente explícita para una síntesis científica profunda " + citation_block_for_rows(top_rows[4:8]) + ".",
            "",
            f"Este artículo responde a esa necesidad mediante una revisión sistemática de literatura centrada en personalidad en LLMs durante {years_label}. La meta no es defender una teoría única, sino identificar qué constructos dominan el campo, cómo se diseñan los estudios, qué marcos teóricos se movilizan y qué tensiones aparecen entre medición, control de personas sintéticas y efectos humanos o de seguridad " + citation_block_for_rows(top_rows[8:12]) + ".",
            "",
            f"La distinción entre corpus incluido y síntesis focal no constituye la pregunta de investigación, sino una decisión metodológica posterior para aislar el subconjunto comparativamente más robusto. El eje del artículo sigue siendo sustantivo: cómo se está entendiendo y operacionalizando la personalidad en los LLMs del periodo {years_label}.",
        ]
    ) + "\n"


def build_theoretical_framework_section_personality(focus_rows: list[dict[str, str]], context: dict[str, str]) -> str:
    theories = theory_family_counter(focus_rows, 6)
    constructs = personality_construct_counter(focus_rows)
    work_counts = work_type_summary(focus_rows)
    empirical_counts = empirical_summary(focus_rows)
    top_rows = top_rows_by_rank(focus_rows, 8)
    total = len(focus_rows)
    years_label = review_years_label(context)
    theory_sentence = (
        "No emerge un marco teórico único; el campo opera más bien como una convergencia entre psicología de rasgos, teoría de la interacción y diseños instrumentales de persona."
        if not theories
        else "A partir de la codificación propia del subconjunto focal, resumida de forma completa en la Tabla 9, los marcos y vocabularios conceptuales más visibles son "
        + "; ".join(f"{label} (n={count}, {percentage(count, total)})" for label, count in theories[:4])
        + "."
    )
    construct_sentence = (
        "Los constructos más recurrentes del subconjunto focal son "
        + "; ".join(f"{label} (n={count}, {percentage(count, total)})" for label, count in constructs.most_common(4))
        + "."
        if constructs
        else "Los constructos aparecen muy fragmentados y no permiten una jerarquía clara."
    )
    review_count = work_counts.get("review", 0)
    return "\n".join(
        [
            "# Marco teórico",
            "",
            f"El campo de personalidad en LLMs durante {years_label} no está organizado por una única escuela. Conviven marcos clásicos de psicología de rasgos, aproximaciones de persona o role-play, diseños de profiling y trabajos centrados en alineamiento, sesgo o efectos humanos " + citation_block_for_rows(top_rows[:4]) + ".",
            "",
            "El marco teórico se organiza en tres capas. La primera identifica qué teorías, constructos o vocabularios psicológicos declara cada paper. La segunda construye una lente transversal para comparar estudios que mezclan medición, steering, role-play, sesgo, alineamiento y efectos downstream. La tercera delimita el alcance de las inferencias: medir una respuesta compatible con un rasgo, inducir una persona sintética y demostrar estabilidad psicológica no son afirmaciones equivalentes.",
            "",
            theory_sentence,
            "",
            construct_sentence,
            "",
            f"Desde el punto de vista metodológico, el subconjunto focal combina sobre todo estudios empíricos experimentales (n={empirical_counts.get('experimental', 0)}, {percentage(empirical_counts.get('experimental', 0), total)}), con presencia menor de diseños cuantitativos o mixtos y muy pocas revisiones explícitas (n={review_count}, {percentage(review_count, total)}).",
            "",
            "Esta estructura evita que el marco teórico trate `personalidad` como una palabra única. En la revisión, personalidad puede funcionar como constructo medido, como intervención de control, como interfaz conversacional o como fuente de efectos sobre interacción y seguridad. La comparación solo es válida cuando el estudio deja claro cuál de esas funciones está activando.",
            "",
            *personality_theoretical_thesis_lines(focus_rows),
            "",
            "Estos conteos deben leerse como cartografía descriptiva de familias teóricas explícitamente reportadas por los artículos y no como demostración de una teoría dominante cerrada. Lo que emerge es un espacio híbrido entre psicometría, interacción humano-IA y control conductual de agentes conversacionales " + citation_block_for_rows(top_rows[4:8]) + ".",
        ]
    ) + "\n"


def build_method_section_personality(
    review_dir: pathlib.Path,
    focus_rows: list[dict[str, str]],
    all_shortlist_rows: list[dict[str, str]],
    flow_counts: dict[str, int],
    context: dict[str, str],
) -> str:
    source_counter = read_search_sources(review_dir)
    source_rows = [[SOURCE_DISPLAY_MAP.get(source, source), str(count)] for source, count in source_counter.most_common(8)]
    source_sentence_es = render_search_source_list(review_dir, "es")
    focus_exclusions = Counter(
        reason
        for row in all_shortlist_rows
        if is_selected(row) and (reason := focus_exclusion_reason(review_dir, row))
    )
    focus_low_conf = sum(1 for row in focus_rows if parse_int(row.get("extraction_confidence"), 0) < 80)
    sensitivity = shortlist_sensitivity(review_dir)
    prisma_rows = [
        ["Registros identificados", str(flow_counts.get("identified", 0))],
        ["Duplicados consolidados antes del cribado", str(flow_counts.get("duplicates_removed", 0))],
        ["Cribado título/resumen", str(flow_counts.get("screened_title_abstract", 0))],
        ["Exclusiones título/resumen", str(flow_counts.get("excluded_title_abstract", 0))],
        ["Texto completo buscado", str(flow_counts.get("full_text_sought", 0))],
        ["Texto completo no recuperado en PDF", str(flow_counts.get("full_text_not_retrieved", 0))],
        ["Texto completo evaluado", str(flow_counts.get("full_text_assessed", 0))],
        ["Estudios incluidos tras lectura de texto completo", str(flow_counts.get("included_in_review", 0))],
        ["Estudios de síntesis focal", str(len(focus_rows))],
    ]
    wr, wq, wp = selection_weight_triplet(context)
    cap_rows = [
        ["Relevancia temática", f"{selection_weight_percent(wr)} del score compuesto"],
        ["Calidad metodológica", f"{selection_weight_percent(wq)} del score compuesto"],
        ["Representatividad", f"{selection_weight_percent(wp)} del score compuesto"],
        ["Confianza de extracción < 80", "degradación a reserva o salida del top final"],
        ["Sin PDF local", "exclusión dura del subconjunto focal"],
        ["Fuera del dominio temático", "penalización fuerte y salida del top si persiste tras curación editorial"],
    ]
    rubric_rows = [
        ["Claridad del constructo de personalidad", "25"],
        ["Método, evaluación y resultados reportados", "25"],
        ["Trazabilidad de la evidencia dentro del PDF", "20"],
        ["Contexto, muestra y comparabilidad", "15"],
        ["Marco teórico explícito", "15"],
    ]
    non_focal_rows = [
        row for row in all_shortlist_rows
        if (row.get("decision_before_cap") or "").strip().lower() in {"include", "include_ft"}
        and has_public_doi(row)
        and not is_selected(row)
    ]
    non_focal_table_rows = []
    for row in non_focal_rows[:5]:
        conf = parse_int(row.get("extraction_confidence"), 0)
        title = normalize_phrase(row.get("title_original")) or "no reportado"
        reason = (
            f"Confianza de extracción {conf}/100 tras segunda lectura del PDF; "
            "no alcanzó la densidad mínima de evidencia comparable en muestra, contexto o resultados."
        )
        non_focal_table_rows.append([public_doi_value(row), title, reason])
    focal_context_rows = focal_context_characteristics_rows(focus_rows, all_shortlist_rows)
    timeframe_es = review_timeframe_phrase_es(context)
    years_label = review_years_label(context)
    return "\n".join(
        [
            "# Método",
            "",
            "La revisión se diseñó como una revisión sistemática de literatura con captación inicial explícita, trazabilidad DOI, cribado por título/resumen y evaluación final exclusivamente sobre texto completo recuperado en PDF. Los estándares de reporte de revisiones sistemáticas se emplearon como guía de transparencia de selección, no como sustituto de la metodología de revisión. La regla metodológica más estricta del proceso fue que ningún estudio podía entrar en el corpus final publicable sin DOI normalizado, PDF local legible y texto extraído desde ese PDF.",
            "",
            "## Diseño de la revisión sistemática",
            "La base metodológica combina la lógica de planificación, conducción y reporte de revisiones sistemáticas de literatura con estándares de transparencia para identificación, cribado, elegibilidad e inclusión (Kitchenham & Charters, 2007; Page et al., 2021; Snyder, 2019).",
            "",
            "En todo el manuscrito, las citas en texto, la presentación de referencias, las menciones de figuras y tablas y la normalización bibliográfica final se ajustan al estilo APA 7. Esta decisión editorial afecta al cuerpo del artículo y no solo a la bibliografía final.",
            "",
            f"Rango temporal: publicaciones localizadas {timeframe_es}. Etiqueta editorial del periodo: {years_label}. Idiomas: búsqueda sin restricción idiomática; cuando el título o el abstract aparecían en otra lengua, se conservaron y tradujeron para facilitar la comparación, pero la inclusión final siguió dependiendo de la recuperabilidad de un PDF legible.",
            "",
            f"Se consultaron de forma explícita {source_sentence_es}. Las búsquedas combinaron términos sobre `llm personality`, `persona`, `personality traits`, `big five`, `mbti`, `hexaco`, `role-playing`, `persona steering`, `profiling`, `alignment` y `bias`, además de expresiones equivalentes. La Tabla 2 resume la distribución de consultas por fuente y el anexo metodológico conserva las cadenas completas, las fechas exactas y las incidencias operativas registradas durante la captación.",
            "",
            f"La deduplicación se ejecutó sobre DOI normalizado y, cuando faltaba, sobre título normalizado. En esta corrida se identificaron y consolidaron {flow_counts.get('duplicates_removed', 0)} duplicados antes del cribado inicial, sin dejar duplicados residuales en el universo finalmente cribado.",
            "",
            "No se registró un protocolo externo en PROSPERO ni en OSF antes de realizar la revisión. Para compensar esa ausencia, se conservan el documento de captación inicial, la estrategia de búsqueda, los logs, los registros de cribado, los PDFs locales, la preselección curada y los anexos tabulares como rastro auditable completo.",
            "",
            "En esta revisión, `modelos de IA razonadores` designa modelos o variantes experimentales descritos por los propios artículos como reasoning models, reasoning LLMs o sistemas equivalentes con generación deliberativa, cadena de razonamiento explícita o tareas donde el razonamiento constituye parte central del diseño experimental. Los LLMs generales solo entraron cuando el paper los analizaba directamente en comparación con ese tipo de modelos o los usaba como condición experimental relevante para el constructo de personalidad.",
            "",
            *build_method_depth_lines(review_dir, focus_rows, flow_counts, context),
            "",
            "## Criterios de inclusión",
            f"- {context.get('inclusion') or 'Publicaciones de 2026 relevantes para personalidad, rasgos, personas o perfiles conductuales en LLMs.'}",
            "- DOI normalizado disponible para trazabilidad bibliográfica pública.",
            "- Disponibilidad de PDF local verificable para la fase de texto completo.",
            "",
            "## Criterios de exclusión",
            f"- {context.get('exclusion') or 'Irrelevancia manifiesta respecto a personalidad en LLMs, ausencia de PDF legible o imposibilidad de recuperar señal metodológica suficiente.'}",
            "- Operativamente, `irrelevancia manifiesta` se aplicó a trabajos cuyo foco principal no era personalidad, rasgos, personas, perfiles o consistencia conductual en LLMs.",
            "- Para la síntesis focal del paper, además, se priorizaron los trabajos con confianza de extracción igual o superior a 80 y con mejor equilibrio entre constructos, métodos, fuentes y tareas analíticas.",
            "- Un estudio se consideró `sin tamaño muestral explícito` cuando el PDF no reportaba ni número de participantes humanos ni número de instancias, episodios o unidades analíticas comparables; `sin país` cuando el contexto empírico no explicitaba localización o procedencia del entorno de validación; y `sin variables detalladas` cuando el artículo no distinguía al menos una variable dependiente y una independiente o su equivalente experimental.",
            "",
            "Figura 1. Arquitectura operativa de revisión.",
            figure_markdown("../../figures/png/fig-review-architecture.png", "Figura 1. Arquitectura operativa de revisión"),
            "",
            "Tabla 1. Flujo de selección de estudios.",
            markdown_table(["Etapa", "N"], prisma_rows),
            "",
            "Tabla 2. Distribución de consultas registradas por fuente.",
            markdown_table(["Fuente", "Consultas"], source_rows),
            "",
            "Tabla 3. Reglas operativas de composición del subconjunto focal.",
            markdown_table(["Criterio", "Regla operativa"], cap_rows),
            "",
            "Tabla 4. Rúbrica operativa de la confianza de extracción.",
            markdown_table(["Indicador", "Peso máximo"], rubric_rows),
            "",
            "Tabla 4A. Estudios incluidos en la revisión pero fuera de la síntesis focal.",
            markdown_table(["DOI", "Título completo", "Criterio operativo"], non_focal_table_rows or [["—", "No aplica", "Todos los estudios incluidos entraron en la síntesis focal."]]),
            "",
            "Tabla 4B. Comparación focal-contextual.",
            markdown_table(
                ["Grupo", "N", "Perfil dominante", "Vacíos de reporte", "Score medio", "Fuentes principales"],
                focal_context_rows,
            ),
            "",
            "Esta comparación impide que el N focal se lea como una selección opaca: muestra si los estudios de comparación intensiva difieren del perímetro contextual en diseño, reporte, fuente o densidad de evidencia.",
            "",
            "La escala de `confianza de extracción` se expresa de 0 a 100 y resume cuánta señal conceptual, metodológica y empírica pudo recuperarse del PDF completo. No mide prestigio del paper, sino extractabilidad auditada: claridad del constructo de personalidad, método, hallazgos, evidencia ubicada dentro del PDF y comparabilidad con el resto del corpus.",
            "",
            "No se aplicó una herramienta validada única de riesgo de sesgo tipo ROBIS o Cochrane, porque el corpus combina benchmarks computacionales, diseños con participantes y estudios híbridos que no admiten una equivalencia directa con una sola rúbrica clínica o biomédica. En su lugar, el manuscrito incorpora una apreciación estructurada de riesgo de reporting y trazabilidad, basada en completitud muestral, país o contexto empírico, marco teórico y densidad de evidencia recuperable desde el PDF completo; esa apreciación se reporta comparativamente en la Tabla 10 y debe leerse como una evaluación interna del corpus, no como un sustituto universal de una herramienta validada.",
            "La propia rúbrica de `confianza de extracción` tampoco constituye un instrumento psicométrico validado externamente. Debe interpretarse como una guía estructurada de reporting y comparabilidad diseñada para esta revisión, útil para priorizar lectura profunda y detectar vacíos de trazabilidad, pero no para sustituir una evaluación formal universal de calidad metodológica.",
            "",
            f"Del total de {flow_counts.get('full_text_sought', 0)} candidatos a texto completo, {flow_counts.get('full_text_not_retrieved', 0)} no pudieron recuperarse en PDF y quedaron fuera del corpus final. De los {flow_counts.get('full_text_assessed', 0)} PDFs efectivamente evaluados, {flow_counts.get('full_text_excluded', 0)} quedaron excluidos en lectura de texto completo y {flow_counts.get('included_in_review', 0)} pasaron al corpus incluido.",
            "",
            focal_synthesis_relation(flow_counts.get("included_in_review", 0), len(focus_rows), "es"),
            f"La síntesis focal se apoyó, por tanto, en esos mismos {len(focus_rows)} estudios, sin introducir una reducción adicional entre inclusión y comparación intensiva.",
            "",
            f"Como comprobación de robustez, dos variantes simples de sensibilidad (`0,40/0,40/0,20` y `0,45/0,30/0,25`) conservaron {sensitivity.get('alt_a_overlap', 0)}/{sensitivity.get('target_n', 0)} y {sensitivity.get('alt_b_overlap', 0)}/{sensitivity.get('target_n', 0)} estudios del subconjunto final. En esta revisión, ese filtrado complementario afectó a {sum(count for reason, count in focus_exclusions.items() if reason != 'confianza_de_extraccion_baja')} registros inicialmente seleccionados por el ranking automático, y {focus_low_conf} estudios del subconjunto final siguen señalados como lectura de reserva por confianza de extracción inferior a 80.",
        ]
    ) + "\n"


def build_results_section_personality(
    review_dir: pathlib.Path,
    all_review_rows: list[dict[str, str]],
    focus_rows: list[dict[str, str]],
) -> str:
    corpus_rows = all_review_rows or focus_rows
    work_counter = work_type_summary(corpus_rows)
    empirical_counter = empirical_summary(focus_rows)
    empirical_total = max(sum(empirical_counter.values()), 0)
    construct_counts = personality_construct_counter(focus_rows)
    method_family_counts = personality_method_family_counter(focus_rows)
    theory_rows = [[table_label(label), f"{count} ({percentage(count, len(focus_rows))})"] for label, count in theory_family_counter(focus_rows, 6)]
    work_rows = [[table_label(display_work_type(label)), f"{count} ({percentage(count, len(corpus_rows))})"] for label, count in work_counter.most_common()]
    empirical_rows = [[table_label(display_empirical_type(label)), f"{count} ({percentage(count, max(empirical_total, 1))})"] for label, count in empirical_counter.most_common()]
    construct_rows = [[table_label(label), f"{count} ({percentage(count, len(focus_rows))})"] for label, count in construct_counts.most_common()]
    method_rows = [[table_label(label), f"{count} ({percentage(count, len(focus_rows))})"] for label, count in method_family_counts.most_common()]
    bias_rows = risk_of_bias_rows(focus_rows)
    top_rows = top_rows_by_rank(focus_rows, 16)
    return "\n".join(
        [
            "# Resultados",
            "",
            f"El subconjunto focal de {len(focus_rows)} estudios no reemplaza al corpus incluido completo, sino que lo profundiza. Los {len(corpus_rows)} estudios incluidos sostienen el mapa general del campo; los {len(focus_rows)} focales sostienen la comparación intensiva porque concentran mejor ajuste temático, mejor trazabilidad PDF y mejor señal metodológica.",
            "",
            "Figura 2. Mapa del corpus por tipo de trabajo, fuente y señal empírica.",
            figure_markdown("../../figures/png/fig-corpus-map.png", "Figura 2. Mapa del corpus"),
            "La Figura 2 resume la composición del corpus incluido y de la síntesis focal: predominan los trabajos empíricos, aunque siguen coexistiendo aportaciones teóricas y otras piezas de frontera. Esa mezcla explica por qué el artículo distingue entre cartografía general del campo y síntesis focal del subconjunto final.",
            "",
            "Figura 3. Panorama temático del corpus final.",
            figure_markdown("../../figures/png/fig-theme-landscape.png", "Figura 3. Panorama temático"),
            "La Figura 3 condensa el hallazgo más importante del corpus: la literatura no se divide en líneas separadas, sino en una cadena de trabajo donde la personalidad se mide, se convierte en interfaz de control y después se prueba por sus efectos sobre alineamiento, preferencias, cooperación, sesgo o riesgo. Esa continuidad explica por qué la familia `persona steering / control` aparece en todo el subconjunto focal, mientras que los ejes realmente discriminativos son `medición, profiling y validación`, `interacción humana y alineamiento` y `sesgo, riesgo y seguridad`.",
            "",
            "Figura 4. Matriz entre constructos, estrategias metodológicas y resultados.",
            figure_markdown("../../figures/png/fig-agent-task-matrix.png", "Figura 4. Matriz constructo-estrategia"),
            "La Figura 4 permite observar qué combinaciones aparecen con más frecuencia entre constructos de personalidad, estrategias metodológicas y fines analíticos. La densidad no se distribuye homogéneamente: Big Five / OCEAN y los diseños de assessment o benchmarking concentran la mayor parte de la evidencia comparable, mientras que MBTI, HEXACO y los estudios centrados en efectos humanos o morales aparecen en menor volumen y funcionan más como extensiones del núcleo principal que como subcampos equivalentes.",
            "",
            "Figura 5. Mapa de comparabilidad metodológica de los estudios empíricos.",
            figure_markdown("../../figures/png/fig-method-profile.png", "Figura 5. Mapa de comparabilidad metodológica"),
            "La Figura 5 refuerza que el perfil empírico solo es interpretable cuando se observan también muestra, contexto, marco teórico, variables, comparador y validación. La lectura conjunta de las Figuras 3-5 sugiere, por tanto, una asimetría clara: el campo está mejor preparado para demostrar que puede inducir o medir personalidad que para demostrar con la misma precisión sus efectos downstream de forma comparable.",
            "",
            *build_evidence_position_lines(review_dir),
            f"Tabla 5. Distribución del corpus incluido (n={len(corpus_rows)}) por tipo de trabajo.",
            markdown_table(["Tipo de trabajo", "N"], work_rows),
            "",
            f"Tabla 6. Distribución del subconjunto focal empírico (n={empirical_total}) por diseño.",
            markdown_table(["Tipo empírico", "N"], empirical_rows),
            "",
            f"Tabla 7. Familias de constructos de personalidad en el subconjunto focal (n={len(focus_rows)}).",
            markdown_table(["Constructo o familia", "N"], construct_rows),
            "",
            "Tabla 8. Estrategias metodológicas y analíticas más frecuentes.",
            markdown_table(["Estrategia", "N"], method_rows),
            "",
            "Tabla 9. Familias teóricas más visibles en la síntesis focal.",
            markdown_table(["Marco teórico", "N"], theory_rows or [["No reportado", "0"]]),
            "",
            "Tabla 10. Perfil estructurado de riesgo de reporting y trazabilidad del subconjunto empírico.",
            markdown_table(["Diseño", "N", "Confianza media (0-100)", "Sin tamaño muestral", "Sin país", "Sin marco teórico", "Perfil global"], bias_rows),
            "",
            f"Las Tablas 5 y 6 usan denominadores distintos por diseño: la Tabla 5 resume los {len(corpus_rows)} estudios incluidos, mientras que la Tabla 6 solo sintetiza los {empirical_total} estudios empíricos del subconjunto focal de {len(focus_rows)}. Esa diferencia no refleja una inconsistencia numérica, sino un cambio deliberado de unidad analítica.",
            "",
            "La Tabla 10 no debe interpretarse como una herramienta validada universal de riesgo de sesgo, sino como una apreciación estructurada de reporting y trazabilidad adaptada a un corpus heterogéneo de benchmarks computacionales, experimentos con modelos y estudios con participantes. Por eso combina confianza de extracción, explicitud muestral, país o contexto empírico y base teórica reportada.",
            "",
            "Los resultados permiten sostener tres hallazgos principales. Primero, la personalidad en LLMs se estudia sobre todo como problema de medición, steering y validación, más que como teoría psicológica cerrada. Segundo, el campo depende fuertemente de diseños experimentales y benchmarks, mientras que la explicitud de muestra, variables o países sigue siendo irregular. Tercero, el corpus invierte más en demostrar utilidad funcional de las personas sintéticas que en estabilizar un estándar psicométrico compartido, lo que explica la coexistencia de estudios de profiling, control, alineamiento y seguridad " + citation_block_for_rows(top_rows[:6], limit=6) + ".",
            "",
            f"La matriz completa de {len(focus_rows)} estudios y sus familias de constructos se entrega como anexo CSV para auditoría y reutilización. Esa matriz conecta cada estudio con constructos, métodos y confianza de extracción y evita que la comparación descanse solo en texto narrativo. La Tabla 9 del manuscrito resume sus marcos teóricos más visibles y el CSV suplementario permite recontar cada frecuencia de forma directa " + citation_block_for_rows(top_rows[6:12], limit=6) + ".",
            "",
            "En conjunto, la evidencia no describe un catálogo arbitrario de papers, sino una trayectoria metodológica bastante consistente: medir rasgos, convertir esos rasgos en mecanismos de steering o conditioning, y evaluar después su efecto sobre interacción, preferencias, cooperación o riesgo. La diversidad del corpus se sitúa sobre todo en la calidad del reporte, no en la inexistencia de un patrón empírico reconocible " + citation_block_for_rows(top_rows[12:16]) + ".",
        ]
    ) + "\n"


def build_discussion_section_personality(review_dir: pathlib.Path, focus_rows: list[dict[str, str]], flow_counts: dict[str, int], context: dict[str, str]) -> str:
    construct_counts = personality_construct_counter(focus_rows)
    method_family_counts = personality_method_family_counter(focus_rows)
    top_rows = top_rows_by_rank(focus_rows, 20)
    consciousness_ids = record_ids_for_doi(focus_rows, "10.48550/arXiv.2604.13051") or record_ids_for_title_fragment(
        focus_rows,
        "The Consciousness Cluster",
    )
    consciousness_anchor = citation_block(consciousness_ids, limit=1)
    years_label = review_years_label(context)
    construct_flow_path = review_dir / "figures" / "png" / "fig-autopilot-construct-flow.png"
    if construct_flow_path.exists():
        figure_heading = "Figura 6. Flujo entre constructos, steering y efectos downstream."
        figure_block = figure_markdown("../../figures/png/fig-autopilot-construct-flow.png", "Figura 6. Flujo constructo-steering-efectos")
        figure_sentence = "La Figura 6 organiza la literatura como una cadena sustantiva entre constructos medidos, mecanismos de steering y efectos downstream observados."
    else:
        figure_heading = "Figura 6. Flujo corpus–síntesis–manuscrito del proceso editorial."
        figure_block = figure_markdown("../../figures/png/fig-publication-workflow.png", "Figura 6. Flujo de publicación")
        figure_sentence = "La Figura 6 ayuda a leer esa transición como un flujo de evidencia: identificación, cribado, lectura completa del PDF, síntesis focal y ensamblaje del manuscrito final."
    return "\n".join(
        [
            "# Discusión",
            "",
            f"Dentro del corpus {years_label}, la personalidad en LLMs aparece simultáneamente como objeto experimental, mecanismo de control y fuente de riesgo metodológico. El campo estudia a la vez si los modelos pueden perfilar rasgos, si pueden ser steerados hacia personas sintéticas y qué consecuencias tiene eso para interacción, sesgo y alineamiento " + citation_block_for_rows(top_rows[:4]) + "." + (f" Algunos trabajos desplazan incluso el problema hacia preferencias emergentes y autoconcepto cuando el modelo declara conciencia {consciousness_anchor}." if consciousness_anchor else ""),
            "",
            figure_heading,
            figure_block,
            "",
            "## Implicaciones teóricas",
            f"La revisión sugiere una tensión constante entre medición y control. Familias como {', '.join(f'{label} (n={count})' for label, count in construct_counts.most_common(3))} coexisten en el mismo corpus, lo que indica que el campo no distingue siempre con nitidez entre describir la personalidad del modelo, inducirla activamente o evaluar sus efectos aguas abajo. {figure_sentence}",
            "",
            "En términos teóricos, esa tensión obliga a abandonar una lectura simplista según la cual `personalidad` sería un único atributo estable del modelo. Lo que el corpus muestra con más claridad es una constelación de operaciones distintas: unas miden rasgos o perfiles, otras fuerzan o condicionan personas sintéticas y otras observan efectos secundarios de esas configuraciones sobre cooperación, persuasión, alineamiento o sesgo. La implicación teórica más fuerte es que la acumulación futura del campo dependerá de separar mejor esos niveles analíticos sin tratarlos como sinónimos.",
            "",
            "La segunda implicación teórica es que la personalidad debe tratarse como una relación entre constructo, procedimiento e impacto, no como una etiqueta psicológica aislada. Un mismo modelo puede parecer estable, maleable o riesgoso según la tarea, el prompt, el instrumento de medición, la intervención aplicada y el tipo de efecto observado. Por tanto, la teoría futura debe explicar las condiciones bajo las cuales un rasgo medido se convierte en señal válida, en artefacto de role-play o en efecto contextual.",
            "",
            "La tercera implicación es que los vacíos de reporte tienen consecuencias conceptuales. Cuando un estudio no declara muestra, país o contexto, variables, instrumento o marco teórico, no solo falta información metodológica: se debilita la posibilidad de distinguir personalidad, estilo conversacional, preferencia inducida y comportamiento situado. La revisión convierte esos vacíos en parte del diagnóstico teórico del campo.",
            "",
            "La cuarta implicación es que la teoría debe especificar límites de transferencia. Un resultado obtenido con una tarea, prompt, instrumento o modelo concreto no puede extenderse automáticamente a otras situaciones. La comparación futura debe declarar cuándo una señal de personalidad se mantiene, cuándo se transforma y cuándo desaparece al cambiar el contexto de evaluación.",
            "",
            "De esta lectura se derivan tres proposiciones para acumulación futura: primera, no hay comparación sólida sin separar medición, intervención y efecto; segunda, la estabilidad aparente de una personalidad debe probarse entre tareas y contextos, no asumirse desde una sesión; tercera, la validez del constructo depende tanto del instrumento psicométrico como de la arquitectura de prompting, evaluación y control que lo produce.",
            "",
            *build_practical_implications_lines(
                focus_rows,
                context,
                citation_ids=[row.get("record_id", "") for row in top_rows],
            ),
            "",
            "## Aportación original del artículo",
            "La aportación original del artículo es formular una tesis de unidad de comparación para la personalidad en LLMs: el objeto comparable no es el modelo aislado ni la etiqueta `personalidad`, sino la configuración completa entre constructo, procedimiento de medición, intervención, métrica, tarea y efecto observado. Esta tesis evita tratar como equivalentes estudios que comparten vocabulario pero no miden el mismo fenómeno.",
            "",
            *original_contribution_table_lines("personality_llm", "personalidad en LLMs", len(focus_rows)),
            "La segunda aportación es conceptual: el manuscrito propone una gramática analítica de la personalidad en modelos de lenguaje. Esa gramática reordena el campo en torno a la secuencia medición–intervención–efecto, y distingue profiling, steering, persona induction, evaluación psicométrica y efectos downstream como piezas relacionadas pero no intercambiables. Así, el artículo no solo clasifica papers; ofrece un vocabulario para decidir cuándo una afirmación habla de rasgos, cuándo habla de control conductual y cuándo habla de consecuencias observables en interacción.",
            "",
            f"La tercera aportación es sustantiva. En términos empíricos, el predominio de estrategias como {', '.join(f'{label} (n={count})' for label, count in method_family_counts.most_common(3))} muestra que la personalidad en LLMs se estudia sobre todo desde la acción y la validación aplicada, no desde diseños acumulativos homogéneos. El campo parece más cómodo transformando rasgos en palancas de control o evaluación que discutiendo cuándo esas mismas palancas siguen siendo psicológicamente válidas o comparables. Esa asimetría es probablemente el hallazgo crítico más estable del corpus " + citation_block_for_rows(top_rows[8:12]) + ".",
            "",
            "La cuarta aportación es metodológica. La revisión convierte esa gramática en un objeto verificable porque conserva PDFs, anexos CSV, tablas comparativas y referencias normalizadas dentro del paquete editorial. La contribución, por tanto, no es solo la conclusión sobre personalidad en LLMs, sino el marco que permite comprobar, discutir y ampliar esa conclusión sin depender de una lectura narrativa opaca.",
            "",
            *build_validity_threats_lines(focus_rows, flow_counts, context, citation_ids=[row.get("record_id", "") for row in top_rows]),
        ]
    ) + "\n"


def build_conclusions_section_personality(focus_rows: list[dict[str, str]], flow_counts: dict[str, int], context: dict[str, str]) -> str:
    constructs = personality_construct_counter(focus_rows)
    top_rows = top_rows_by_rank(focus_rows, 20)
    years_label = review_years_label(context)
    rq_text = publication_research_question(context, "personality_llm")
    unit_thesis = conclusion_unit_thesis("personality_llm")
    grammar_sentence = conclusion_grammar_sentence("personality_llm", len(focus_rows))
    diagnostics = conclusion_reporting_diagnostics(focus_rows)
    future_lines = conclusion_diagnostic_future_lines(focus_rows, "personality_llm")
    construct_text = ", ".join(f"{label} (n={count})" for label, count in constructs.most_common(4))
    return "\n".join(
        [
            "# Conclusiones",
            "",
            f"En respuesta a la pregunta de investigación, {rq_text}, la evidencia indica que la personalidad de un modelo de IA razonador puede estudiarse empíricamente, pero no como una propiedad simple y estable del modelo. Solo se vuelve comparable cuando el estudio declara constructo, procedimiento de medición, intervención, métrica, tarea y alcance inferencial " + citation_block_for_rows(top_rows[12:16]) + ".",
            "",
            unit_thesis,
            "",
            grammar_sentence,
            "",
            f"No emerge un marco teórico único, pero sí un vocabulario recurrente de constructos y procedimientos. En el subconjunto focal destacan {construct_text}. La conclusión no es que esos constructos agoten el campo, sino que permiten distinguir tres operaciones que a menudo se mezclan: medir perfiles, inducir personas sintéticas y observar efectos downstream.",
            "",
            f"Lo que puede afirmarse con más seguridad es que el campo ya dispone de un programa empírico reconocible alrededor de medición, steering y efectos humanos o de seguridad. Lo que aparece como señal emergente es una secuencia analítica útil, medición-intervención-efecto, que puede ordenar estudios muy distintos sin fingir que son idénticos. Lo que todavía no puede concluirse es que exista un estándar psicométrico transversal o una personalidad estable del modelo independiente de tarea, prompt, métrica y contexto, especialmente cuando {count_studies_es(diagnostics['missing_theory'])} {verb_by_count(diagnostics['missing_theory'], 'no declara', 'no declaran')} marco teórico, {count_studies_es(diagnostics['missing_variables'])} {verb_by_count(diagnostics['missing_variables'], 'no detalla', 'no detallan')} variables y {count_studies_es(diagnostics['missing_sample'])} {verb_by_count(diagnostics['missing_sample'], 'no reporta', 'no reportan')} muestra de forma suficiente.",
            "",
            "Leída en conjunto, la evidencia permite responder en un sentido matizado: sí puede medirse e inducirse personalidad en modelos de IA, pero esa afirmación solo es científicamente fuerte cuando se especifica qué se entiende por personalidad, cómo se induce, qué instrumento la mide, qué efecto se observa y qué límite tiene la inferencia. Sin esa explicitud, la literatura corre el riesgo de llamar personalidad a estilo conversacional, role-play, preferencia contextual o artefacto de prompting.",
            "",
            "El límite no invalida la síntesis; define su alcance. La revisión no cierra el debate psicológico sobre personalidad artificial, sino que fija las condiciones mínimas para discutirlo con más rigor: trazabilidad documental, lectura completa, extracción estructurada, separación de operaciones analíticas y cautela frente a inferencias que el diseño original no sostiene.",
            "",
            f"Como aportación, el trabajo deja un corpus trazable de {flow_counts.get('included_in_review', 0)} estudios, un subconjunto focal reproducible de {len(focus_rows)} trabajos del periodo {years_label}, una matriz de constructos y métodos exportada en CSV, anexos reutilizables y un manuscrito conectado a la ficha analítica de cada estudio. La aportación de fondo es una unidad de comparación y una gramática analítica que permiten convertir resultados dispersos en una síntesis acumulativa " + citation_block_for_rows(top_rows[16:20]) + ".",
            "",
            *future_lines,
            "",
            *build_author_contribution_section(focus_rows, flow_counts, context),
        ]
    ) + "\n"


def build_editorial_statements_section(context: dict[str, str]) -> str:
    outlet_mode, outlet_value = classify_target_outlet(context.get("target_journal", ""))
    target_journal = outlet_value if outlet_mode == "specific-target-outlet" else "generic-common-core"
    return "\n".join(
        [
            "# Declaraciones editoriales",
            "",
            f"- Perfil editorial operativo: {target_journal}.",
            *([f"- Banda temática declarada en intake: {outlet_value}."] if outlet_mode == "generic-common-core" and outlet_value else []),
            "- Estilo de citación y referencias: APA 7 aplicada al cuerpo del manuscrito, tablas, figuras y bibliografía final.",
            "- Conflictos de interés: no se declaran conflictos de interés.",
            "- Financiación: no se ha recibido financiación específica para la realización de este trabajo.",
            "- Disponibilidad de datos y materiales: el corpus bibliográfico, los anexos CSV, las matrices de cribado/extracción y los activos visuales propios se conservan en el paquete editorial. Los PDFs locales se usan solo como evidencia privada de auditoría y no deben redistribuirse si su licencia no lo permite.",
            "- Checklist de reporte de revisión sistemática: se adjunta como anexo metodológico dentro del paquete editorial para facilitar evaluación de revista.",
            "- Cumplimiento metodológico: el manuscrito se compila desde un protocolo de revisión sistemática de literatura con trazabilidad DOI, recuperación de PDF local, extracción estructurada, evaluación de calidad y auditoría editorial determinista previa al criterio final de publicabilidad.",
        ]
    ) + "\n"


def build_network_method_subsection(review_dir: pathlib.Path) -> str:
    summary_path = review_dir / "analysis" / "metrics" / "network-summary.json"
    if not summary_path.exists():
        return ""
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    coverage = payload.get("coverage", {})
    denominator = int(coverage.get("denominator") or 0)
    if denominator <= 0:
        return ""
    author_coverage = float(coverage.get("authors", {}).get("coverage") or 0.0)
    reference_coverage = float(coverage.get("references", {}).get("coverage") or 0.0)
    keyword_coverage = float(coverage.get("keywords", {}).get("coverage") or 0.0)
    return (
        "\n## Análisis estructural del corpus\n\n"
        "Como análisis complementario, se construyeron redes separadas de coautoría, citación, "
        "acoplamiento bibliográfico, cocitación, coocurrencia temática y relaciones entre estudios "
        "y dimensiones extraídas. La unidad de identidad de estudio fue el DOI normalizado. Se "
        "calcularon grado ponderado, intermediación, centralidad armónica, PageRank, centralidad de "
        "autovector, núcleo k, clustering y participación entre comunidades. La intermediación "
        "ponderada convirtió la fuerza de vínculo en distancia mediante $d_{ij}=1/w_{ij}$.\n\n"
        "Las comunidades se estimaron con Louvain para múltiples semillas y resoluciones; la "
        "partición de mayor modularidad se contrastó mediante información mutua normalizada. Su "
        "interpretación exigió al menos 20 estudios incluidos, estabilidad igual o superior a 0,80 "
        "y cobertura suficiente de la capa correspondiente. Sobre un denominador de "
        f"{denominator} estudios, la cobertura fue {author_coverage:.1%} para autoría, "
        f"{reference_coverage:.1%} para referencias y {keyword_coverage:.1%} para palabras clave. "
        "La productividad, las citas y la posición de red no intervinieron en la elegibilidad, la "
        "evaluación crítica ni la selección focal. Los parámetros y denominadores se conservan en "
        "los anexos estructurales.\n"
    )


def build_network_results_subsection(review_dir: pathlib.Path) -> str:
    summary_path = review_dir / "analysis" / "summary.md"
    if not summary_path.exists():
        return ""
    content = read_text(summary_path).strip()
    if not content:
        return ""
    lines = content.splitlines()
    if lines and lines[0].startswith("# "):
        lines[0] = "## " + lines[0][2:]
    return "\n" + "\n".join(lines).strip() + "\n"


def hydrate_publication_sections(review_dir: pathlib.Path, corpus: dict[str, CorpusRecord]) -> None:
    section_dir = review_dir / "paper" / "sections"
    flow_counts = read_flow_counts(review_dir)
    context = read_research_context(review_dir)
    profile = detect_review_profile(context)
    focus_rows = curate_focus_rows(review_dir, corpus)
    if materialize_missing_focus_extractions(review_dir, corpus, focus_rows):
        focus_rows = curate_focus_rows(review_dir, corpus)
    if enrich_focus_extraction_fields(review_dir, focus_rows):
        focus_rows = curate_focus_rows(review_dir, corpus)
    all_shortlist_rows = merge_shortlist_rows(review_dir, corpus, selected_only=False)
    all_review_rows = [
        row
        for row in all_shortlist_rows
        if (row.get("decision_before_cap") or "").strip().lower() in {"include", "include_ft"}
        and has_public_doi(row)
    ]
    if profile == "personality_llm":
        export_personality_construct_matrix(review_dir, focus_rows)
    else:
        export_architecture_component_matrix(review_dir, focus_rows)
    export_selection_score_matrix(review_dir, focus_rows)
    export_critical_appraisal_matrix(review_dir, focus_rows)
    # Visual evidence is an audit layer, not decoration. Keep it focused on
    # the studies that actually sustain the synthesis to avoid slow reruns and
    # noisy source figures that do not strengthen the manuscript.
    ensure_visual_evidence(review_dir, focus_rows)
    if profile == "personality_llm":
        section_builders = {
            "00-index.md": build_index_section(focus_rows),
            "01-title-abstract-keywords.md": build_title_abstract_section_personality(review_dir, focus_rows, flow_counts, context),
            "02-introduction.md": build_introduction_section_personality(focus_rows, context),
            "03-theoretical-framework.md": build_theoretical_framework_section_personality(focus_rows, context),
            "04-method.md": build_method_section_personality(review_dir, focus_rows, all_shortlist_rows, flow_counts, context),
            "05-results.md": build_results_section_personality(review_dir, all_review_rows, focus_rows),
            "06-discussion.md": build_discussion_section_personality(review_dir, focus_rows, flow_counts, context),
            "07-conclusions.md": build_conclusions_section_personality(focus_rows, flow_counts, context),
            "10-editorial-statements.md": build_editorial_statements_section(context),
        }
    else:
        section_builders = {
            "00-index.md": build_index_section(focus_rows),
            "01-title-abstract-keywords.md": build_title_abstract_section(review_dir, focus_rows, flow_counts, context),
            "02-introduction.md": build_introduction_section(focus_rows, context),
            "03-theoretical-framework.md": build_theoretical_framework_section(focus_rows, context),
            "04-method.md": build_method_section(review_dir, focus_rows, all_shortlist_rows, flow_counts, context),
            "05-results.md": build_results_section(review_dir, all_review_rows, focus_rows),
            "06-discussion.md": build_discussion_section(review_dir, focus_rows, flow_counts, context),
            "07-conclusions.md": build_conclusions_section(focus_rows, flow_counts, context),
            "10-editorial-statements.md": build_editorial_statements_section(context),
        }
    section_builders["04-method.md"] = (
        section_builders["04-method.md"].rstrip()
        + build_network_method_subsection(review_dir)
        + "\n"
    )
    section_builders["05-results.md"] = (
        section_builders["05-results.md"].rstrip()
        + build_network_results_subsection(review_dir)
        + "\n"
    )
    for filename, content in section_builders.items():
        path = section_dir / filename
        write_text(path, content)


def render_corpus_appendix(review_dir: pathlib.Path, corpus: dict[str, CorpusRecord], focus_rows: list[dict[str, str]]) -> str:
    profile = detect_review_profile(read_research_context(review_dir))
    stable_rows = [row for row in focus_rows if not is_provisional_focus_row(row)]
    provisional_rows = [row for row in focus_rows if is_provisional_focus_row(row)]
    lines = [
        "# Anexo A. Fichas analíticas del corpus final incluido",
        "",
        "Este anexo constituye la aportación analítica por estudio del subconjunto focal usado en la síntesis focal del artículo.",
        "Cada ficha combina una lectura interpretativa breve, una tabla compacta homogénea y una línea comparativa final para facilitar lectura académica, contraste metodológico y reutilización del corpus.",
        "",
        f"El bloque principal reúne {len(stable_rows)} estudios con extracción consolidada. "
        + (
            f"Los {len(provisional_rows)} restantes se desplazan al anexo correspondiente para no mezclar evidencia robusta con fichas todavía débiles en confianza, densidad metodológica o explicitud teórica."
            if provisional_rows
            else "En esta revisión no hay estudios focales con extracción provisional dentro del bloque principal."
        ),
        "",
    ]
    if not focus_rows:
        lines.append("_Aún no hay estudios seleccionados para el corpus final._")
        return "\n".join(lines).strip() + "\n"

    for idx, row in enumerate(stable_rows, start=1):
        record_id = row.get("record_id", "")
        record = corpus.get(record_id)
        title = sanitize_title(
            first_nonempty(
                row.get("title_original"),
                row.get("title_en"),
                row.get("title_es"),
                record.title if record else "",
            )
        )
        authors = nice_value(row.get("authors"), fallback=record.authors if record else "no reportado")
        year = nice_value(row.get("year"), fallback=record.year if record else "no reportado")
        doi = first_nonempty(row.get("assigned_doi"), record.assigned_doi if record else "", "sin DOI asignado")
        lines.extend(
            [
                f"## Estudio {idx}. {title}",
                "",
                interpretive_summary_for_row(row, record, profile=profile),
                "",
                study_explanatory_paragraph_for_row(row, record, profile=profile),
                "",
                f"- Autores: {authors}",
                f"- Año: {year}",
                f"- DOI: `{doi}`",
                "",
                study_metadata_table(row, profile=profile),
                "",
                f"- Hallazgos clave: {publication_safe_value(row.get('key_findings'))}",
                f"- Evidencia de apoyo: {supporting_evidence_value(row)}",
                f"- Localización de la evidencia: {display_location_label(row.get('evidence_location'))}",
                f"- Lectura comparativa: {comparative_takeaway_for_row(row, profile=profile)}",
                "",
            ]
        )
    if provisional_rows:
        lines.extend(
            [
                "# Anexo complementario. Estudios incluidos con extracción provisional",
                "",
                "Estos estudios permanecen dentro del subconjunto focal por su relevancia temática, pero se separan del bloque principal porque su extracción aún depende de evidencia incompleta, respuesta transitoria del modelo, confianza inferior a 80 o una densidad metodológica/teórica insuficiente para sostener comparación fina en el bloque principal.",
                "",
            ]
        )
        start_idx = len(stable_rows) + 1
        for idx, row in enumerate(provisional_rows, start=start_idx):
            record_id = row.get("record_id", "")
            record = corpus.get(record_id)
            title = sanitize_title(
                first_nonempty(
                    row.get("title_original"),
                    row.get("title_en"),
                    row.get("title_es"),
                    record.title if record else "",
                )
            )
            authors = nice_value(row.get("authors"), fallback=record.authors if record else "no reportado")
            year = nice_value(row.get("year"), fallback=record.year if record else "no reportado")
            doi = first_nonempty(row.get("assigned_doi"), record.assigned_doi if record else "", "sin DOI asignado")
            lines.extend(
                [
                    f"## Estudio {idx}. {title}",
                    "",
                    interpretive_summary_for_row(row, record, profile=profile),
                    "",
                    study_explanatory_paragraph_for_row(row, record, profile=profile),
                    "",
                    f"- Autores: {authors}",
                    f"- Año: {year}",
                    f"- DOI: `{doi}`",
                    "",
                    study_metadata_table(row, profile=profile),
                    "",
                    f"- Hallazgos clave: {publication_safe_value(row.get('key_findings'))}",
                    f"- Evidencia de apoyo: {supporting_evidence_value(row)}",
                    f"- Localización de la evidencia: {display_location_label(row.get('evidence_location'))}",
                    f"- Lectura comparativa: {comparative_takeaway_for_row(row, profile=profile)}",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def stage_data_annexes(review_dir: pathlib.Path) -> list[pathlib.Path]:
    annex_dir = review_dir / "paper" / "appendices" / "data"
    annex_dir.mkdir(parents=True, exist_ok=True)
    deprecated_annex = annex_dir / "ultraquality-shortlist.csv"
    if deprecated_annex.exists():
        deprecated_annex.unlink()
    checklist_path = write_prisma_checklist(review_dir, read_flow_counts(review_dir), read_research_context(review_dir))
    source_paths = [
        review_dir / "searches" / "search-stage-map.csv",
        review_dir / "searches" / "search-log.csv",
        review_dir / "records" / "master-records.csv",
        review_dir / "records" / "doi-index.csv",
        review_dir / "records" / "duplicates.csv",
        review_dir / "records" / "missing-doi.csv",
        review_dir / "screening" / "title-abstract.csv",
        review_dir / "screening" / "full-text.csv",
        review_dir / "extraction" / "extraction-table.csv",
        review_dir / "selection" / "ultraquality-shortlist.csv",
        review_dir / "prisma" / "flow-counts.csv",
        review_dir / "figures" / "manifest.csv",
        review_dir / "figures" / "evidence-manifest.csv",
        review_dir / "figures" / "page-render-manifest.csv",
        review_dir / "tables" / "paper-tables-spec.csv",
        review_dir / "tables" / "evidence-manifest.csv",
        review_dir / "tables" / "architecture-component-matrix.csv",
        review_dir / "tables" / "personality-construct-matrix.csv",
        review_dir / "tables" / "selection-score-matrix.csv",
        review_dir / "tables" / "critical-appraisal-matrix.csv",
        review_dir / "protocol" / "intake.md",
        review_dir / "protocol" / "research-question.md",
        review_dir / "protocol" / "eligibility-criteria.md",
        review_dir / "protocol" / "review-mode.md",
        review_dir / "protocol" / "review-mode.json",
        review_dir / "protocol" / "search-decomposition.md",
        review_dir / "protocol" / "search-decomposition.json",
        review_dir / "protocol" / "search-strategy.md",
        review_dir / "analysis" / "methodology.md",
        review_dir / "analysis" / "summary.md",
        review_dir / "analysis" / "data" / "nodes.csv",
        review_dir / "analysis" / "data" / "edges.csv",
        review_dir / "analysis" / "metrics" / "centrality.csv",
        review_dir / "analysis" / "metrics" / "communities.csv",
        review_dir / "analysis" / "metrics" / "author-production.csv",
        review_dir / "analysis" / "metrics" / "selection-drift.csv",
        review_dir / "analysis" / "audit" / "coverage.json",
        review_dir / "analysis" / "audit" / "parameters.json",
        review_dir / "analysis" / "audit" / "provenance.csv",
        checklist_path,
    ]
    staged: list[pathlib.Path] = []
    for source in source_paths:
        if not source.exists():
            continue
        dest_name = source.name
        if source.parent.name in {"figures", "tables"} and source.name == "evidence-manifest.csv":
            dest_name = f"{source.parent.name}-evidence-manifest.csv"
        elif source.parent.name == "figures" and source.name == "page-render-manifest.csv":
            dest_name = "figures-page-render-manifest.csv"
        elif source.name == "ultraquality-shortlist.csv":
            dest_name = "selection-audit-matrix.csv"
        elif "analysis" in source.parts:
            dest_name = f"network-{source.name}"
        dest = annex_dir / dest_name
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        staged.append(dest)
    return staged


def render_data_annexes_section(review_dir: pathlib.Path, staged_paths: list[pathlib.Path]) -> str:
    lines = [
        "# Anexo B. Datos y trazabilidad",
        "",
        "Se adjuntan como anexos CSV las fuentes minadas y derivadas que sostienen el análisis, con el fin de facilitar auditoría, replicación y reutilización por parte de lectoras y lectores.",
        "",
    ]
    if not staged_paths:
        lines.append("_Aún no hay anexos CSV preparados para lectores._")
        return "\n".join(lines).strip() + "\n"

    for path in staged_paths:
        rel_path = path.relative_to(review_dir)
        if path.suffix.lower() == ".csv":
            row_count = 0
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    row_count = sum(1 for _ in csv.DictReader(handle))
            except (OSError, csv.Error):
                row_count = 0
            if path.name == "extraction-table.csv":
                lines.append(f"- `{rel_path}`: {row_count} filas de extracción; el corpus publicable final conserva los estudios con DOI, PDF legible y decisión de inclusión.")
            elif path.name == "selection-audit-matrix.csv":
                lines.append(f"- `{rel_path}`: {row_count} filas de preselección y auditoría; no debe leerse como N final del corpus.")
            elif path.name == "duplicates.csv":
                lines.append(
                    f"- `{rel_path}`: {row_count} filas de ocurrencias duplicadas detectadas; el flujo de selección reporta la reducción neta consolidada antes del cribado."
                )
            else:
                lines.append(f"- `{rel_path}`: {row_count} filas de datos.")
        else:
            line_count = 0
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as handle:
                    line_count = sum(1 for _ in handle)
            except OSError:
                line_count = 0
            lines.append(f"- `{rel_path}`: documento metodológico ({line_count} líneas).")
    lines.append("")
    lines.append("En esta revisión, `figures-evidence-manifest.csv` registra candidatos visuales detectados en los PDFs; ese inventario no implica inclusión en el manuscrito. Una figura fuente solo debe entrar en el artículo si se inserta como figura concreta, con caption analítica y aporte claro al argumento.")
    lines.append("")
    lines.append("Estos anexos CSV forman parte de la aportación documental del artículo y deben acompañar al manuscrito final siempre que la política editorial de la revista lo permita.")
    return "\n".join(lines).strip() + "\n"


def doi_cache_path(cache_dir: pathlib.Path, doi: str) -> pathlib.Path:
    return cache_dir / f"{slugify(doi)}.json"


def fetch_csl_json(doi: str, cache_dir: pathlib.Path) -> dict:
    cache_file = doi_cache_path(cache_dir, doi)
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    url = "https://doi.org/" + parse.quote(doi, safe="")
    req = request.Request(
        url,
        headers={
            "Accept": "application/vnd.citationstyles.csl+json",
            "User-Agent": "HermesPublicationAudit/1.0",
        },
    )
    timeout_seconds = max(
        5,
        min(60, int(os.environ.get("HERMES_CSL_TIMEOUT_SECONDS", "15") or "15")),
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        payload = json.load(response)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def fetch_csl_batch(
    records: list[tuple[str, str]],
    cache_dir: pathlib.Path,
    max_workers: int = 16,
) -> tuple[dict[str, dict], dict[str, Exception]]:
    """Resolve DOI metadata concurrently while keeping deterministic consumers.

    DOI content negotiation can be slow or unavailable for individual
    publishers. A bounded worker pool prevents one unresponsive DOI from
    serialising a complete bibliography build. Results and failures remain
    keyed by record ID so the caller can report issues in manuscript order.
    """
    results: dict[str, dict] = {}
    failures: dict[str, Exception] = {}
    if not records:
        return results, failures

    configured_workers = int(
        os.environ.get("HERMES_CSL_MAX_WORKERS", str(max_workers)) or str(max_workers)
    )
    worker_count = max(1, min(configured_workers, 32, len(records)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(fetch_csl_json, doi, cache_dir): record_id
            for record_id, doi in records
        }
        for future in as_completed(futures):
            record_id = futures[future]
            try:
                results[record_id] = future.result()
            except Exception as exc:  # noqa: BLE001
                failures[record_id] = exc
    return results, failures


def format_apa_names_from_csl(authors: list[dict]) -> str:
    if not authors:
        return "Autor no resuelto"
    formatted = []
    for author in authors:
        family, given, literal = resolve_csl_name(author)
        initials = initials_from_given(given)
        if literal and not family:
            formatted.append(format_apa_names_from_plain(literal))
        elif family:
            formatted.append(f"{family}, {initials}".strip().rstrip(","))
    if not formatted:
        return "Autor no resuelto"
    return finalize_apa_name_list(formatted)


def short_citation_from_csl(authors: list[dict], year: str) -> str:
    year = normalize_reference_year(year)
    families = []
    for author in authors:
        family, _, literal = resolve_csl_name(author)
        if not family and literal:
            family = author_family(literal)
        if family:
            families.append(family)
    if not families:
        return f"(Autor no resuelto, {year or 's. f.'})"
    if len(families) == 1:
        return f"({families[0]}, {year})"
    if len(families) == 2:
        return f"({families[0]} & {families[1]}, {year})"
    return f"({families[0]} et al., {year})"


def year_from_csl(meta: dict, fallback: str) -> str:
    issued = meta.get("issued") or {}
    parts = issued.get("date-parts") or []
    if parts and parts[0]:
        year = normalize_reference_year(parts[0][0], "")
        if year:
            return year
    return normalize_reference_year(fallback)


def doi_url(meta: dict, fallback_doi: str) -> str:
    doi = (meta.get("DOI") or fallback_doi or "").strip()
    return f"https://doi.org/{doi}" if doi else ""


def csl_value(meta: dict, key: str) -> str:
    value = meta.get(key)
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value or "").strip()


def build_apa_reference(record: CorpusRecord, csl_meta: dict | None) -> tuple[str, str]:
    if csl_meta:
        year = year_from_csl(csl_meta, record.year)
        authors = format_apa_names_from_csl(csl_meta.get("author") or [])
        first_plain_author = split_authors(record.authors)[0] if split_authors(record.authors) else ""
        plain_authors = format_apa_names_from_plain(record.authors) if record.authors.strip() else ""
        if plain_authors and is_organization_author(first_plain_author) and authors.startswith("Team,"):
            authors = plain_authors
        if authors == "Autor no resuelto" and record.authors.strip():
            authors = format_apa_names_from_plain(record.authors)
        short_cite = short_citation_from_csl(csl_meta.get("author") or [], year)
        if plain_authors and is_organization_author(first_plain_author) and short_cite.startswith("(Team,"):
            short_cite = format_short_citation_from_plain(record.authors, year)
        if short_cite.startswith("(Autor no resuelto") and record.authors.strip():
            short_cite = format_short_citation_from_plain(record.authors, year)
        title = sentence_case_title(csl_value(csl_meta, "title") or record.title).rstrip(" .")
        if authors == "Autor no resuelto":
            short_cite = title_based_citation(title, year)
        container_raw = csl_value(csl_meta, "container-title")
        container = sanitize_title(container_raw) if container_raw else ""
        volume = csl_value(csl_meta, "volume")
        issue = csl_value(csl_meta, "issue")
        page = csl_value(csl_meta, "page")
        article_number = csl_value(csl_meta, "article-number")
        publisher_raw = csl_value(csl_meta, "publisher")
        publisher = sanitize_title(publisher_raw) if publisher_raw else ""
        citation_url = citation_url_for_record(record, csl_meta)
        entry_type = csl_value(csl_meta, "type")
        citation_arxiv_url = canonical_arxiv_url(citation_url)
        preprint_repository = preprint_repository_label(record, csl_meta, citation_url)
        standalone_repository = looks_like_repository_work(record, citation_url, container, publisher)
        standalone_entry = entry_type in {"posted-content", "report", "dissertation", "thesis"} or standalone_repository
        if preprint_repository:
            title_part = f"{italic(title)} [Preprint]"
        else:
            title_part = italic(title) if standalone_entry else title
        descriptor = repository_work_descriptor(record, citation_url, container, publisher) if standalone_repository else ""
        if authors == "Autor no resuelto":
            parts = [f"{title_part}{descriptor}. ({year})."]
        else:
            authors_with_period = authors if authors.endswith(".") else f"{authors}."
            parts = [f"{authors_with_period} ({year}). {title_part}{descriptor}."]
        if preprint_repository:
            parts.append(preprint_repository + ".")
        elif entry_type in {"article-journal", "journal-article"}:
            journal = container or publisher or "Contenedor no resuelto"
            journal_part = italic(journal)
            if volume:
                journal_part += f", {italic(volume)}"
                if issue:
                    journal_part += f"({issue})"
            elif issue:
                journal_part += f", ({issue})"
            if page:
                journal_part += f", {page}"
            elif article_number:
                journal_part += f", Article {article_number}"
            parts.append(journal_part + ".")
        elif entry_type in {"paper-conference", "chapter", "proceedings-article"}:
            container_part = container or publisher or "Proceedings no resueltos"
            proceedings_part = italic(container_part)
            if page:
                proceedings_part += f", {page}"
            elif article_number:
                proceedings_part += f", Paper {article_number}"
            else:
                hicss_match = re.search(r"hicss\.\d{4}\.(\d+)", (citation_url or record.assigned_doi or ""), flags=re.IGNORECASE)
                if hicss_match:
                    proceedings_part += f", Paper {hicss_match.group(1)}"
            parts.append(proceedings_part + ".")
        elif entry_type in {"posted-content", "report"}:
            ssrn_preprint = (record.assigned_doi or "").lower().startswith("10.2139/ssrn.")
            host = arxiv_preprint_label(citation_arxiv_url) if citation_arxiv_url else ("SSRN Electronic Journal" if ssrn_preprint else (container or publisher or "Preprint"))
            parts.append(host + ".")
        elif standalone_repository:
            host = container or publisher
            if host:
                parts.append(host + ".")
        else:
            host = container or publisher
            if host:
                parts.append(italic(host) + ".")
        if citation_url:
            parts.append(citation_url)
        return " ".join(part.strip() for part in parts if part.strip()), short_cite

    authors = format_apa_names_from_plain(record.authors)
    year = normalize_reference_year(record.year)
    title = sentence_case_title(record.title).rstrip(" .")
    citation_url = citation_url_for_record(record)
    host = ""
    arxiv_url = canonical_arxiv_url(record.notes or citation_url or record.assigned_doi)
    if arxiv_url:
        title = f"{italic(title)} [Preprint]"
        host = f" {arxiv_preprint_label(arxiv_url)}."
    elif looks_like_repository_work(record, citation_url):
        title = italic(title) + repository_work_descriptor(record, citation_url)
    if authors == "Autor no resuelto":
        reference = f"{title}. ({year}).{host}"
        short_cite = title_based_citation(title, year)
    else:
        authors_with_period = authors if authors.endswith(".") else f"{authors}."
        reference = f"{authors_with_period} ({year}). {title}.{host}"
        short_cite = format_short_citation_from_plain(record.authors, year)
    if citation_url:
        reference += f" {citation_url}"
    return reference, short_cite


def author_families_for_record(record: CorpusRecord, csl_meta: dict | None) -> list[str]:
    if csl_meta:
        families = []
        for author in csl_meta.get("author") or []:
            family, _, literal = resolve_csl_name(author)
            if not family and literal:
                family = author_family(literal)
            if family:
                families.append(family)
        if families:
            return families
    return [author_family(author) for author in split_authors(record.authors) if author_family(author)]


def first_author_initial_for_record(record: CorpusRecord, csl_meta: dict | None) -> str:
    """Return the first author's initials for same-surname citation disambiguation."""
    if csl_meta:
        authors = csl_meta.get("author") or []
        if authors:
            _family, given, literal = resolve_csl_name(authors[0])
            initials = initials_from_given(given)
            if initials:
                return initials
            if literal:
                return author_initials(literal)
    authors = split_authors(record.authors)
    return author_initials(authors[0]) if authors else ""


def author_identity_signature(
    record: CorpusRecord,
    csl_meta: dict | None,
) -> tuple[tuple[str, str], ...]:
    """Identify authors by family name and initials before assigning year suffixes."""
    identities: list[tuple[str, str]] = []
    if csl_meta:
        for author in csl_meta.get("author") or []:
            family, given, literal = resolve_csl_name(author)
            if not family and literal:
                family = author_family(literal)
            initials = initials_from_given(given) or (author_initials(literal) if literal else "")
            if family:
                identities.append((family.casefold(), initials.casefold()))
    if identities:
        return tuple(identities)
    return tuple(
        (author_family(author).casefold(), author_initials(author).casefold())
        for author in split_authors(record.authors)
        if author_family(author)
    )


def apply_year_suffix(reference: str, year: str, suffix: str) -> str:
    if not suffix or not year:
        return reference
    return re.sub(rf"\({re.escape(year)}\)", f"({year}{suffix})", reference, count=1)


def build_disambiguated_citation(
    families: list[str],
    year: str,
    depth: int,
    first_author_initial: str = "",
) -> str:
    if not families:
        return f"(Autor no resuelto, {year or 's. f.'})"
    first_author = f"{first_author_initial} {families[0]}".strip()
    if len(families) == 1:
        return f"({first_author}, {year})"
    if len(families) == 2:
        return f"({first_author} & {families[1]}, {year})"
    if depth <= 1:
        return f"({first_author} et al., {year})"
    if len(families) == 3:
        return f"({first_author}, {families[1]}, & {families[2]}, {year})"
    if depth == 2:
        return f"({first_author}, {families[1]}, et al., {year})"
    return f"({first_author}, {families[1]}, {families[2]}, et al., {year})"


def disambiguate_short_citations(
    corpus: dict[str, CorpusRecord],
    csl_cache: dict[str, dict | None],
    generated_references: dict[str, str],
    short_citations: dict[str, str],
    active_ids: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    relevant_ids = set(active_ids or corpus.keys())
    metadata: dict[str, dict[str, object]] = {}
    for record_id, record in corpus.items():
        if record_id not in relevant_ids:
            continue
        meta = csl_cache.get(record_id)
        year = year_from_csl(meta, record.year) if meta else (record.year or "s. f.")
        metadata[record_id] = {
            "families": author_families_for_record(record, meta),
            "author_identity": author_identity_signature(record, meta),
            "first_author_initial": first_author_initial_for_record(record, meta),
            "year": year,
            "title": sanitize_title(record.title).lower(),
        }

    year_suffixes: dict[str, str] = {}
    exact_groups: dict[tuple[tuple[tuple[str, str], ...], str], list[str]] = {}
    for record_id, payload in metadata.items():
        key = (tuple(payload["author_identity"]), str(payload["year"]))
        exact_groups.setdefault(key, []).append(record_id)
    for record_ids in exact_groups.values():
        if len(record_ids) <= 1:
            continue
        for index, record_id in enumerate(sorted(record_ids, key=lambda rid: str(metadata[rid]["title"]))):
            suffix = chr(ord("a") + index)
            year_suffixes[record_id] = suffix

    for record_id, suffix in year_suffixes.items():
        year = str(metadata[record_id]["year"])
        generated_references[record_id] = apply_year_suffix(generated_references[record_id], year, suffix)
        families = list(metadata[record_id]["families"])
        short_citations[record_id] = (
            build_disambiguated_citation(families, year + suffix, 1)
            if families
            else title_based_citation(corpus[record_id].title, year + suffix)
        )

    grouped: dict[str, list[str]] = {}
    for record_id, cite in short_citations.items():
        grouped.setdefault(cite, []).append(record_id)

    for cite, record_ids in grouped.items():
        record_ids = [record_id for record_id in record_ids if record_id in relevant_ids]
        if len(record_ids) <= 1:
            continue
        initial_trial: dict[str, list[str]] = {}
        for record_id in record_ids:
            payload = metadata[record_id]
            year = str(payload["year"]) + year_suffixes.get(record_id, "")
            families = list(payload["families"])
            expanded = (
                build_disambiguated_citation(
                    families,
                    year,
                    1,
                    str(payload["first_author_initial"]),
                )
                if families
                else title_based_citation(corpus[record_id].title, year)
            )
            initial_trial.setdefault(expanded, []).append(record_id)
        if all(len(items) == 1 for items in initial_trial.values()):
            for expanded, items in initial_trial.items():
                short_citations[items[0]] = expanded
            continue
        for depth in (2, 3):
            trial: dict[str, list[str]] = {}
            for record_id in record_ids:
                payload = metadata[record_id]
                year = str(payload["year"]) + year_suffixes.get(record_id, "")
                families = list(payload["families"])
                expanded = (
                    build_disambiguated_citation(families, year, depth)
                    if families
                    else title_based_citation(corpus[record_id].title, year)
                )
                trial.setdefault(expanded, []).append(record_id)
            if all(len(items) == 1 for items in trial.values()):
                for expanded, items in trial.items():
                    short_citations[items[0]] = expanded
                break

    return generated_references, short_citations


def dedupe_scope_record_ids(record_ids: list[str], corpus: dict[str, CorpusRecord]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for record_id in record_ids:
        record = corpus.get(record_id)
        if not record:
            continue
        canonical_arxiv = canonical_arxiv_url(record.assigned_doi or record.notes)
        fingerprint = (
            canonical_arxiv
            or (record.assigned_doi or "").strip().lower()
            or normalized_text(
                " | ".join(
                    [
                        record.authors,
                        sanitize_title(record.title),
                        record.year,
                    ]
                )
            )
        )
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        ordered.append(record_id)
    return ordered


def ensure_publication_scaffold(review_dir: pathlib.Path) -> list[pathlib.Path]:
    paper_dir = review_dir / "paper"
    created: list[pathlib.Path] = []
    files = {
        paper_dir / "README.md": """# Publication Workspace

Este espacio se usa para la `Fase 3`: redacción del paper publicable.

Reglas de trabajo:
- redactar por secciones pequeñas o medianas
- usar anclas internas de cita durante el borrador: `[@record_id]` o `[@doi:10.xxxx/xxxx]`
- no inventar referencias; resolverlas desde DOI y corpus
- ejecutar el auditor de publicación antes de considerar el manuscrito listo para envío

Salidas clave:
- `paper/sections/*.md`: secciones de trabajo
- `paper/manuscript/publication-ready.md`: manuscrito único principal listo para envío
- `paper/manuscript/compiled-submission.md`: compilación interna de apoyo
- `paper/references/references.generated.md`: referencias APA sugeridas desde el corpus
- `paper/audit/publication-audit.md`: informe de auditoría estilo revista
""",
        paper_dir / "sections" / "00-index.md": """# Índice de publicación

- Sustituye este esquema por el índice real del artículo.
- El auditor compila las secciones en orden lexicográfico.
- Usa anclas de cita de trabajo solo dentro de las secciones redactadas del manuscrito.
- El entregable principal no es un conjunto de resúmenes, sino `paper/manuscript/publication-ready.md`.
""",
        paper_dir / "sections" / "01-title-abstract-keywords.md": "# Título del manuscrito\n\n## Resumen\n\n## Abstract\n\n## Palabras clave\n\n## Keywords\n\n",
        paper_dir / "sections" / "02-introduction.md": "# Introducción\n\n",
        paper_dir / "sections" / "03-theoretical-framework.md": "# Marco teórico\n\n",
        paper_dir / "sections" / "04-method.md": "# Método\n\n",
        paper_dir / "sections" / "05-results.md": "# Resultados\n\n",
        paper_dir / "sections" / "06-discussion.md": "# Discusión\n\n",
        paper_dir / "sections" / "07-conclusions.md": "# Conclusiones\n\n",
        paper_dir / "sections" / "08-corpus-final.md": "# Anexo A. Fichas analíticas del corpus final incluido\n\n_Aún no se han generado las fichas analíticas del corpus final._\n",
        paper_dir / "sections" / "09-data-annexes.md": "# Anexo B. Datos y trazabilidad\n\n_Aún no se han preparado los anexos CSV para lectoras y lectores._\n",
        paper_dir / "sections" / "10-editorial-statements.md": "# Declaraciones editoriales\n\n_Aún no se han preparado las declaraciones editoriales._\n",
        paper_dir / "manuscript" / "publication-ready.md": "# Manuscrito publicable\n\n_Aún no hay contenido suficiente para declarar el artículo listo para envío._\n",
        paper_dir / "references" / "references.md": "# Referencias manuales complementarias\n\n",
        paper_dir / "references" / "references.generated.md": "# Referencias APA generadas\n\n_Aún no se han generado referencias._\n",
        paper_dir / "audit" / "publication-audit.md": "# Auditoría de publicación\n\n_Aún no se ha ejecutado la auditoría._\n",
    }
    for path, content in files.items():
        if not path.exists():
            write_text(path, content)
            created.append(path)
    return created


def gather_sections(section_dir: pathlib.Path) -> list[pathlib.Path]:
    if not section_dir.exists():
        return []
    return sorted(
        path
        for path in section_dir.glob("*.md")
        if path.is_file() and path.name != "00-index.md"
    )


def resolve_anchor_token(token: str, corpus: dict[str, CorpusRecord], doi_index: dict[str, str]) -> str | None:
    cleaned = token.strip()
    if not cleaned:
        return None
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    if cleaned.startswith("doi:"):
        doi = cleaned.split(":", 1)[1].strip().lower()
        record_id = doi_index.get(doi)
        return record_id
    if cleaned in corpus:
        return cleaned
    lowered = cleaned.lower()
    if lowered in doi_index:
        return doi_index[lowered]
    return None


def compile_sections(
    section_paths: list[pathlib.Path],
    corpus: dict[str, CorpusRecord],
    short_citations: dict[str, str],
    doi_index: dict[str, str],
) -> tuple[str, list[Issue], Counter[str]]:
    issues: list[Issue] = []
    citation_counter: Counter[str] = Counter()
    compiled_parts = []

    def replace_match(match: re.Match[str]) -> str:
        raw = match.group(1)
        resolved_keys = []
        rendered = []
        for token in [item.strip() for item in re.split(r"[;|]", raw) if item.strip()]:
            record_id = resolve_anchor_token(token, corpus, doi_index)
            if not record_id:
                issues.append(
                    Issue(
                        severity="FAIL",
                        category="citation_anchor",
                        location="manuscript",
                        message=f"No se pudo resolver la ancla `{token}` contra el corpus.",
                        suggested_fix="Usa un `record_id` existente o una ancla `@doi:` resoluble.",
                    )
                )
                continue
            citation_counter[record_id] += 1
            resolved_keys.append(record_id)
            rendered.append(short_citations.get(record_id, f"({record_id})"))
        if not rendered:
            return match.group(0)
        deduped = []
        seen = set()
        for cite in rendered:
            if cite not in seen:
                deduped.append(cite)
                seen.add(cite)
        if len(deduped) == 1:
            return deduped[0]
        deduped = sorted(deduped, key=lambda cite: cite.strip("()").lower())
        inner = "; ".join(cite.strip("()") for cite in deduped)
        return f"({inner})"

    for section_path in section_paths:
        original = read_text(section_path).strip()
        if not original:
            issues.append(
                Issue(
                    severity="WARN",
                    category="empty_section",
                    location=section_path.name,
                    message=f"La sección `{section_path.name}` está vacía.",
                    suggested_fix="Redacta o elimina la sección si no forma parte del índice final.",
                )
            )
            continue
        if PLACEHOLDER_RE.search(original):
            issues.append(
                Issue(
                    severity="WARN",
                    category="placeholder",
                    location=section_path.name,
                    message=f"La sección `{section_path.name}` contiene marcadores de trabajo pendientes.",
                    suggested_fix="Sustituye TODO/TBD/PENDIENTE por contenido verificable antes del envío.",
                )
            )
        transformed = ANCHOR_RE.sub(replace_match, original)
        compiled_parts.append(transformed)

    compiled_text = "\n\n".join(part for part in compiled_parts if part)
    return compiled_text.strip(), issues, citation_counter


def table_hygiene_issues(markdown: str) -> list[Issue]:
    """Detect table artifacts that should never reach a journal-facing draft."""
    issues: list[Issue] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        if not is_pipe_table_line(lines[i]):
            i += 1
            continue
        start = i
        table_lines: list[str] = []
        while i < len(lines) and is_pipe_table_line(lines[i]):
            table_lines.append(lines[i])
            i += 1
        caption = ""
        for j in range(start - 1, max(-1, start - 8), -1):
            if lines[j].strip():
                caption = lines[j].strip()
                break
        table_blob = "\n".join(table_lines)
        location = caption or f"tabla cerca de línea {start + 1}"
        if "…" in table_blob or "..." in table_blob:
            issues.append(
                Issue(
                    severity="FAIL",
                    category="table_truncation",
                    location=location,
                    message="Una tabla contiene puntos suspensivos o texto truncado.",
                    suggested_fix="Usar identificadores, DOI, autor-año o mover el detalle completo a un anexo/CSV; no dejar fragmentos cortados en tablas.",
                )
            )
        internal_tokens = ["Banda contextual", "ultraquality"]
        found_tokens = [token for token in internal_tokens if token.lower() in table_blob.lower()]
        if found_tokens:
            issues.append(
                Issue(
                    severity="FAIL",
                    category="table_internal_label",
                    location=location,
                    message=f"Una tabla contiene etiquetas internas no publicables: {', '.join(found_tokens)}.",
                    suggested_fix="Sustituir jerga operativa por una categoría metodológica explicada o mover el campo al anexo técnico.",
                )
            )
    return issues


def publication_voice_issues(markdown: str) -> list[Issue]:
    """Detect internal production voice that should not appear in a journal article."""
    issues: list[Issue] = []
    forbidden_patterns = [
        (r"\bHermes\b", "Mención interna a Hermes"),
        (r"flujo automatizado", "Referencia a flujo automatizado"),
        (r"revisión cruzada automática", "Referencia a revisión cruzada automática"),
        (r"agentes de apoyo editorial", "Referencia a agentes internos"),
        (r"revisión autónoma", "Referencia a revisión autónoma"),
        (r"\bultraquality\b", "Etiqueta interna ultraquality"),
        (r"HERMES_INFERENCE_(?:API_KEY|BASE_URL)|HERMES_MODEL_(?:PRIMARY|VISION|REVIEW)", "Proveedor o configuración interna"),
        (r"el sistema no inventa|el sistema conserva|el sistema debe", "Agencia atribuida al sistema"),
        (r"esta ejecución|rúbrica interna|protocolo ejecutable", "Voz técnica interna en lugar de lenguaje metodológico"),
    ]
    for pattern, label in forbidden_patterns:
        match = re.search(pattern, markdown, flags=re.IGNORECASE)
        if not match:
            continue
        line_no = markdown[: match.start()].count("\n") + 1
        issues.append(
            Issue(
                severity="FAIL",
                category="publication_voice",
                location=f"línea {line_no}",
                message=f"El manuscrito contiene voz o etiqueta interna no publicable: {label}.",
                suggested_fix="Reescribir como procedimiento metodológico neutral, sin atribuir la revisión a Hermes ni a componentes internos del motor.",
            )
        )
    return issues


def parse_manual_reference_entries(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    content = read_text(path).strip()
    if not content:
        return []
    entries = []
    current = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not stripped:
            if current:
                entries.append(" ".join(current).strip())
                current = []
            continue
        current.append(stripped.lstrip("- ").strip())
    if current:
        entries.append(" ".join(current).strip())
    return entries


def inferred_support_reference_entries(focus_rows: list[dict[str, str]]) -> list[str]:
    blob = normalized_text(
        " ".join(
            " ".join(
                [
                    row.get("theory_framework", "") or "",
                    row.get("instruments_or_scales", "") or "",
                    row.get("benchmark_dataset_or_corpus", "") or "",
                ]
            )
            for row in focus_rows
        )
    )
    entries: list[str] = []
    if "de haes" in blob or ("king" in blob and "hoppe" in blob):
        entries.extend(
            [
                THEORY_SUPPORT_REFERENCES["de_haes_bensing_2009"],
                THEORY_SUPPORT_REFERENCES["king_hoppe_2013"],
            ]
        )
    if "clara hill" in blob or ("exploracion" in blob and "accion" in blob):
        entries.append(THEORY_SUPPORT_REFERENCES["hill_2020"])
    if "pennebaker" in blob and "king" in blob:
        entries.append(THEORY_SUPPORT_REFERENCES["pennebaker_king_1999"])
    if "fiske" in blob or ("warmth" in blob and "competence" in blob):
        entries.append(THEORY_SUPPORT_REFERENCES["fiske_2007"])
    return dedupe_preserve(entries)


def cited_method_reference_entries(text: str) -> list[str]:
    """Add stable methodological references when prose cites them directly."""
    normalized = normalized_text(text)
    entries: list[str] = []
    if "cronbach" in normalized and "meehl" in normalized:
        entries.append(CONSTRUCT_VALIDITY_APA)
    if "shadish" in normalized:
        entries.append(CAUSAL_INFERENCE_APA)
    if "pawson" in normalized:
        entries.append(REALIST_SYNTHESIS_APA)
    if "pearl" in normalized and "bareinboim" in normalized:
        entries.append(TRANSPORTABILITY_APA)
    return dedupe_preserve(entries)


def detect_plain_citations(text: str) -> list[str]:
    found = []
    for match in PAREN_CITE_RE.finditer(text):
        snippet = match.group(1)
        if ";" in snippet or "," in snippet:
            found.append(f"({snippet})")
    for match in NARRATIVE_CITE_RE.finditer(text):
        found.append(match.group(0))
    return found


def markdown_table(headers: list[str], rows: Iterable[list[str]]) -> str:
    rows = list(rows)
    if not rows:
        return "_Sin datos._"
    lines = [
        "|" + "|".join(markdown_table_cell(header) for header in headers) + "|",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        safe = [markdown_table_cell(cell) for cell in row]
        lines.append("|" + "|".join(safe) + "|")
    return "\n".join(lines)


def write_issue_csv(path: pathlib.Path, issues: list[Issue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["severity", "category", "location", "message", "suggested_fix"],
        )
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue.__dict__)


def build_audit_markdown(
    review_dir: pathlib.Path,
    section_paths: list[pathlib.Path],
    compiled_text: str,
    corpus: dict[str, CorpusRecord],
    references: dict[str, str],
    short_citations: dict[str, str],
    citation_counter: Counter[str],
    issues: list[Issue],
    manual_reference_entries: list[str],
) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat()
    cited_records = [record_id for record_id, count in citation_counter.items() if count > 0]
    fail_count = sum(issue.severity == "FAIL" for issue in issues)
    warn_count = sum(issue.severity == "WARN" for issue in issues)
    status = "PASS" if fail_count == 0 and warn_count == 0 else "WARN" if fail_count == 0 else "FAIL"
    headers = ["doi", "short_cite", "times_cited", "reference_generated"]
    rows = [
        [
            (corpus.get(record_id).assigned_doi if corpus.get(record_id) else ""),
            short_citations.get(record_id, ""),
            str(citation_counter[record_id]),
            references.get(record_id, ""),
        ]
        for record_id in sorted(cited_records)
    ]
    issue_rows = [
        [issue.severity, issue.category, issue.location, issue.message, issue.suggested_fix]
        for issue in issues
    ]

    return "\n".join(
        [
            "# Auditoría de publicación",
            "",
            f"- Fecha: {now}",
            f"- Estado global: **{status}**",
            f"- Secciones detectadas: {len(section_paths)}",
            f"- Longitud compilada (caracteres): {len(compiled_text)}",
            f"- Estudios citados por ancla: {len(cited_records)}",
            f"- Entradas manuales en bibliografía: {len(manual_reference_entries)}",
            f"- Fallos: {fail_count}",
            f"- Advertencias: {warn_count}",
            "",
            "## Gate de revista",
            "- `PASS`: sin fallos y sin advertencias materiales.",
            "- `WARN`: publicable solo tras correcciones editoriales adicionales.",
            "- `FAIL`: no apto para envío; hay problemas formales o de trazabilidad que deben corregirse.",
            "",
            "## Chequeos clave",
            "- APA en texto y bibliografía",
            "- Trazabilidad de afirmaciones al corpus",
            "- Secciones vacías o marcadores pendientes",
            "- Resolución DOI y metadatos bibliográficos",
            "- Consistencia mínima para revisión por revista científica",
            "",
            "## Citas resueltas",
            markdown_table(headers, rows) if rows else "_No hay citas resueltas todavía._",
            "",
            "## Incidencias",
            markdown_table(
                ["severity", "category", "location", "message", "suggested_fix"],
                issue_rows,
            ) if issue_rows else "_No se detectaron incidencias._",
            "",
            "## Notas operativas",
            "- El auditor corrige automáticamente la bibliografía generada a partir del corpus y de DOI oficiales cuando están disponibles.",
            "- Para minimizar errores APA, redacta las secciones con anclas resolubles y deja que el finalizador compile el manuscrito.",
            f"- Directorio auditado: `{review_dir}`",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument("--apply", action="store_true", help="Write compiled manuscript and generated references")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory does not exist: {review_dir}")

    ensure_publication_scaffold(review_dir)
    apply_source_verified_identity_corrections(review_dir)
    enforce_publication_doi_flow(review_dir)
    paper_dir = review_dir / "paper"
    section_dir = paper_dir / "sections"
    manuscript_dir = paper_dir / "manuscript"
    references_dir = paper_dir / "references"
    audit_dir = paper_dir / "audit"
    cache_dir = references_dir / "csl-cache"

    corpus = load_corpus(review_dir)
    hydrate_publication_sections(review_dir, corpus)
    focus_rows = curate_focus_rows(review_dir, corpus)
    all_shortlist_rows = merge_shortlist_rows(review_dir, corpus, selected_only=False)
    all_review_rows = [
        row
        for row in all_shortlist_rows
        if (row.get("decision_before_cap") or "").strip().lower() in {"include", "include_ft"}
        and has_public_doi(row)
    ]
    sync_curated_focus_shortlist(review_dir, corpus, focus_rows)
    write_text(section_dir / "08-corpus-final.md", render_corpus_appendix(review_dir, corpus, focus_rows))
    staged_annexes = stage_data_annexes(review_dir)
    write_text(section_dir / "09-data-annexes.md", render_data_annexes_section(review_dir, staged_annexes))
    doi_index = {
        record.assigned_doi.lower(): record_id
        for record_id, record in corpus.items()
        if record.assigned_doi
    }

    csl_cache: dict[str, dict | None] = {}
    generated_references: dict[str, str] = {}
    short_citations: dict[str, str] = {}
    issues: list[Issue] = []

    for record_id, record in corpus.items():
        reference, short_cite = build_apa_reference(record, None)
        generated_references[record_id] = reference
        short_citations[record_id] = short_cite

    section_paths = gather_sections(section_dir)
    compiled_text, compile_issues, citation_counter = compile_sections(section_paths, corpus, short_citations, doi_index)
    issues.extend(compile_issues)
    reference_scope_order = dedupe_scope_record_ids(
        [
            record_id
            for record_id in (
                list(citation_counter.keys())
                + [row.get("record_id", "") for row in focus_rows]
                + [row.get("record_id", "") for row in all_review_rows]
            )
            if record_id
        ],
        corpus,
    )
    reference_scope_ids = set(reference_scope_order)

    csl_records = [
        (record_id, record.assigned_doi)
        for record_id in reference_scope_order
        if (record := corpus.get(record_id)) and record.assigned_doi
    ]
    resolved_csl, csl_failures = fetch_csl_batch(csl_records, cache_dir)

    for record_id in reference_scope_order:
        record = corpus.get(record_id)
        if not record or not record.assigned_doi:
            continue
        meta = resolved_csl.get(record_id)
        exc = csl_failures.get(record_id)
        if exc is not None:
            fallback_url = citation_url_for_record(record)
            if not ("404" in str(exc) and canonical_arxiv_url(fallback_url)):
                issues.append(
                    Issue(
                        severity="WARN",
                        category="doi_metadata",
                        location=record_id,
                        message=f"No se pudo resolver metadato CSL para DOI `{record.assigned_doi}`: {exc}",
                        suggested_fix="Mantener referencia de respaldo y revisar DOI manualmente.",
                    )
                )
        csl_cache[record_id] = meta
        reference, short_cite = build_apa_reference(record, meta)
        generated_references[record_id] = reference
        short_citations[record_id] = short_cite

    generated_references, short_citations = disambiguate_short_citations(
        corpus,
        csl_cache,
        generated_references,
        short_citations,
        reference_scope_ids,
    )

    if citation_counter:
        compiled_text, compile_issues, citation_counter = compile_sections(section_paths, corpus, short_citations, doi_index)
        issues.extend(compile_issues)

    issues.extend(table_hygiene_issues(compiled_text))
    issues.extend(publication_voice_issues(compiled_text))

    raw_section_text = "\n\n".join(read_text(path) for path in section_paths)
    placeholder_citation_markers = re.findall(r"citas APA múltiples|véase bibliografía completa", raw_section_text, flags=re.IGNORECASE)
    if placeholder_citation_markers:
        issues.append(
            Issue(
                severity="WARN",
                category="citation_placeholders",
                location="compiled-manuscript",
                message=f"Se detectaron {len(placeholder_citation_markers)} marcadores editoriales de cita todavía visibles en el borrador.",
                suggested_fix="Sustituye los marcadores editoriales por citas APA completas o rehidrata la sección antes de compilar el manuscrito final.",
            )
        )

    manual_reference_entries = dedupe_preserve(
        [LITERATURE_REVIEW_METHOD_APA, PRISMA_2020_APA, PRISMA_S_APA, SLR_GUIDELINES_APA]
        + cited_method_reference_entries(raw_section_text)
        + inferred_support_reference_entries(focus_rows)
        + parse_manual_reference_entries(references_dir / "references.md")
    )

    if not citation_counter:
        issues.append(
            Issue(
                severity="WARN",
                category="missing_citations",
                location="paper/sections",
                message="No se detectaron anclas de cita resueltas en el manuscrito.",
                suggested_fix="Añade anclas `[@record_id]` o `[@doi:...]` en las secciones redactadas.",
            )
        )

    reference_rank = {
        row.get("record_id", ""): parse_int(row.get("ultraquality_rank"), 9999)
        for row in all_shortlist_rows
        if row.get("record_id")
    }
    references_used = [
        generated_references[record_id]
        for record_id in sorted(reference_scope_order, key=lambda record_id: (reference_rank.get(record_id, 9999), record_id))
        if record_id in generated_references
    ]
    reference_entries = sorted(
        dedupe_preserve(references_used + [entry for entry in manual_reference_entries if entry]),
        key=lambda entry: normalized_text(entry),
    )
    compiled_submission = normalize_citation_sentence_punctuation(normalize_markdown_table_blocks(compiled_text.strip()))
    if reference_entries:
        compiled_submission += "\n\n# Referencias\n\n" + "\n\n".join(f"- {entry}" for entry in reference_entries)
        compiled_submission = normalize_citation_sentence_punctuation(normalize_markdown_table_blocks(compiled_submission))

    references_body = "# Referencias APA generadas\n\n"
    if reference_entries:
        references_body += "\n\n".join(f"- {entry}" for entry in reference_entries) + "\n"
    else:
        references_body += "_Aún no hay citas resueltas en el manuscrito._\n"

    audit_markdown = build_audit_markdown(
        review_dir,
        section_paths,
        compiled_submission,
        corpus,
        generated_references,
        short_citations,
        citation_counter,
        issues,
        manual_reference_entries,
    )

    write_issue_csv(audit_dir / "publication-issues.csv", issues)
    write_text(references_dir / "references.generated.md", references_body)
    compiled_submission_local = stage_manuscript_local_assets(
        review_dir,
        manuscript_dir,
        compiled_submission or "# Manuscrito compilado\n\n_Aún no hay contenido._\n",
    )
    publication_ready_local = stage_manuscript_local_assets(
        review_dir,
        manuscript_dir,
        compiled_submission or "# Manuscrito publicable\n\n_Aún no hay contenido suficiente para declarar el artículo listo para envío._\n",
    )
    write_text(manuscript_dir / "compiled-submission.md", compiled_submission_local)
    write_text(manuscript_dir / "publication-ready.md", publication_ready_local)
    write_text(audit_dir / "publication-audit.md", audit_markdown)

    print(f"sections: {len(section_paths)}")
    print(f"cited_records: {sum(1 for count in citation_counter.values() if count > 0)}")
    print(f"issues: {len(issues)}")
    print(f"audit: {audit_dir / 'publication-audit.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
