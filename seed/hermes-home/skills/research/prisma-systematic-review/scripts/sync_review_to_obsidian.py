#!/usr/bin/env python3
"""Sync a systematic review folder into an Obsidian vault incrementally."""

from __future__ import annotations

import argparse
import csv
import os
import pathlib
import re
import shutil
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime

USER_AGENT = "HermesPRISMASync/1.0 (+https://local.hermes)"
SCRIPT_PATH = pathlib.Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[5]


THEME_RULES = [
    (
        "Benchmarks y evaluacion",
        [
            "benchmark",
            "evaluation",
            "eval",
            "metric",
            "failure mode",
            "swe-bench",
            "featurebench",
            "devagentbench",
            "devagenteval",
        ],
    ),
    (
        "Pull requests y revision",
        [
            "pull request",
            "pull requests",
            "pr ",
            "github",
            "code review",
            "merge",
            "review",
        ],
    ),
    (
        "Pruebas y depuracion",
        [
            "test",
            "testing",
            "debug",
            "bug",
            "mock",
            "regression",
        ],
    ),
    (
        "Arquitecturas y marcos",
        [
            "framework",
            "architecture",
            "pipeline",
            "system",
            "orchestration",
            "multi-agent",
            "multi agent",
        ],
    ),
    (
        "Productividad y adopcion",
        [
            "productivity",
            "adoption",
            "collaboration",
            "teammate",
            "engagement",
            "impact",
            "developer productivity",
        ],
    ),
    (
        "Calidad, riesgo y mantenibilidad",
        [
            "quality",
            "technical debt",
            "maintainability",
            "risk",
            "security",
            "robustness",
        ],
    ),
]


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "review"


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def csv_to_markdown(path: pathlib.Path) -> str:
    if not path.exists():
        return "_No data yet._"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return "_No data yet._"
    header = rows[0]
    body = rows[1:]
    if not body:
        return "_No data yet._"
    lines = [
        "|" + "|".join(header) + "|",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in body:
        padded = row + [""] * (len(header) - len(row))
        safe = [cell.replace("\n", "<br>") for cell in padded[: len(header)]]
        lines.append("|" + "|".join(safe) + "|")
    return "\n".join(lines)


def csv_has_rows(path: pathlib.Path) -> bool:
    return bool(read_csv_rows(path))


def pending_note(message: str) -> str:
    return f"_Pendiente: {message}_"


PLACEHOLDER_BODIES = {
    "_No data yet._",
    "_No figures yet._",
    "_No paper figure plan yet._",
    "_No paper table plan yet._",
}


def is_placeholder_body(body: str) -> bool:
    cleaned = (body or "").strip()
    if not cleaned:
        return True
    if cleaned.startswith("_Pendiente:"):
        return True
    return cleaned in PLACEHOLDER_BODIES


def publication_references_ready(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if "Aún no hay citas resueltas en el manuscrito" in cleaned:
        return False
    return bool(re.search(r"^- ", cleaned, flags=re.MULTILINE))


def publication_manuscript_ready(text: str, references_ready: bool) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if "Aún no hay contenido suficiente para declarar el paper listo para envío" in cleaned:
        return False
    if not references_ready:
        return False
    word_count = len(re.findall(r"\b\w+\b", cleaned, flags=re.UNICODE))
    return word_count >= 1500


def publication_audit_ready(text: str, manuscript_ready: bool) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or not manuscript_ready:
        return False
    if "No se detectaron anclas de cita resueltas" in cleaned:
        return False
    return True


def read_manifest_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_role(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def reviewer_note_source_by_role(review_dir: pathlib.Path, target_role: str) -> str:
    normalized_target = normalize_role(target_role)
    review_manifest = read_csv_rows(review_dir / "paper" / "review" / "review-manifest.csv")
    for row in review_manifest:
        if normalize_role(row.get("role", "")) != normalized_target:
            continue
        output_rel = (row.get("output_path") or "").strip()
        if not output_rel:
            continue
        source = read_text(review_dir / output_rel)
        if source:
            return source

    reviewer_models = read_csv_rows(review_dir / "paper" / "review" / "reviewer-models.csv")
    for row in reviewer_models:
        if normalize_role(row.get("role", "")) != normalized_target:
            continue
        reviewer_id = (row.get("reviewer_id") or "").strip()
        if not reviewer_id:
            continue
        source = read_text(review_dir / "paper" / "review" / "reviews" / f"{reviewer_id}.md")
        if source:
            return source
    return ""


def detect_topic_slug(review_dir: pathlib.Path) -> str:
    folder_name = review_dir.name.strip()
    if folder_name and folder_name != "systematic-review":
        if folder_name.startswith("systematic-review-"):
            derived = slugify(folder_name[len("systematic-review-"):])
            if derived:
                return derived
        derived = slugify(folder_name)
        if derived:
            return derived
    intake = read_text(review_dir / "protocol" / "intake.md")
    for line in intake.splitlines():
        if line.lower().startswith("- tema:"):
            topic = line.split(":", 1)[1].strip()
            if topic:
                return slugify(topic)
    return slugify(review_dir.name)


def ensure_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_note(path: pathlib.Path, title: str, body: str) -> None:
    ensure_dir(path.parent)
    cleaned_body = body.strip()
    duplicate_heading = f"# {title}"
    if cleaned_body.startswith(duplicate_heading):
        cleaned_body = cleaned_body[len(duplicate_heading):].lstrip()
    content = f"# {title}\n\n{cleaned_body}\n"
    path.write_text(content, encoding="utf-8")


def remove_note(path: pathlib.Path) -> None:
    if path.exists():
        path.unlink()


def sync_note(path: pathlib.Path, title: str, body: str, *, keep_placeholder: bool = False) -> None:
    if keep_placeholder or not is_placeholder_body(body):
        write_note(path, title, body)
        return
    remove_note(path)


def adapt_manuscript_paths_for_obsidian(text: str) -> str:
    def rewrite_path(path: str) -> str:
        if path.startswith("../../figures/png/"):
            return path.replace("../../figures/png/", "_artifacts/figures/png/", 1)
        if path.startswith("../../figures/svg/"):
            return path.replace("../../figures/svg/", "_artifacts/figures/svg/", 1)
        if path.startswith("../../figures/extracted/"):
            return path.replace("../../figures/extracted/", "_artifacts/figures/extracted/", 1)
        if path.startswith("../../figures/page-renders/"):
            return path.replace("../../figures/page-renders/", "_artifacts/figures/page-renders/", 1)
        if path.startswith("../../tables/extracted/"):
            return path.replace("../../tables/extracted/", "_artifacts/tables/extracted/", 1)
        if path.startswith("figures/png/"):
            return path.replace("figures/png/", "_artifacts/paper/manuscript/figures/png/", 1)
        if path.startswith("figures/svg/"):
            return path.replace("figures/svg/", "_artifacts/paper/manuscript/figures/svg/", 1)
        if path.startswith("figures/extracted/"):
            return path.replace("figures/extracted/", "_artifacts/paper/manuscript/figures/extracted/", 1)
        if path.startswith("figures/page-renders/"):
            return path.replace("figures/page-renders/", "_artifacts/paper/manuscript/figures/page-renders/", 1)
        if path.startswith("tables/extracted/"):
            return path.replace("tables/extracted/", "_artifacts/paper/manuscript/tables/extracted/", 1)
        return path

    def replace_match(match: re.Match[str]) -> str:
        prefix = match.group(1)
        path = match.group(2)
        suffix = match.group(3)
        return f"{prefix}{rewrite_path(path)}{suffix}"

    return re.sub(r"(\]\()([^)]+)(\))", replace_match, text or "")


def copy_artifacts(review_dir: pathlib.Path, dest: pathlib.Path) -> list[pathlib.Path]:
    artifacts_root = dest / "_artifacts"
    copied: list[pathlib.Path] = []
    for source in sorted(review_dir.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(review_dir)
        target = artifacts_root / rel
        ensure_dir(target.parent)
        shutil.copy2(source, target)
        copied.append(target)
    return copied


def summarize_counts(csv_path: pathlib.Path) -> tuple[int, int]:
    if not csv_path.exists():
        return 0, 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return 0, 0
    return max(0, len(rows) - 1), len(rows[0]) if rows else 0


def normalize_cell(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_present(value: str | None) -> bool:
    text = normalize_cell(value)
    return bool(text) and text.lower() not in {"no reportado", "none", "nan", "null"}


def normalized_text(*parts: str | None) -> str:
    return " ".join(normalize_cell(part).lower() for part in parts if normalize_cell(part))


def parse_multi_value(value: str | None) -> list[str]:
    text = normalize_cell(value)
    if not text:
        return []
    parts = re.split(r"[;,|]", text)
    values = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        if item.lower() == "no reportado":
            continue
        values.append(item)
    return values


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No data yet._"
    def safe_cell(value: object) -> str:
        return normalize_cell(value).replace("|", r"\|").replace("\n", "<br>").strip()

    lines = [
        "|" + "|".join(safe_cell(header) for header in headers) + "|",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        padded = row + [""] * (len(headers) - len(row))
        safe = [safe_cell(cell) for cell in padded[: len(headers)]]
        lines.append("|" + "|".join(safe) + "|")
    return "\n".join(lines)


def counter_to_table(counter: Counter[str], left_header: str, right_header: str = "count") -> str:
    rows = [[label, str(count)] for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]
    return markdown_table([left_header, right_header], rows)


def read_flow_counts(path: pathlib.Path) -> dict[str, str]:
    counts: dict[str, str] = {}
    for row in read_csv_rows(path):
        stage = normalize_cell(row.get("stage"))
        count = normalize_cell(row.get("count"))
        notes = normalize_cell(row.get("notes"))
        if stage:
            counts[stage] = count
            if notes:
                counts[f"{stage}_notes"] = notes
    return counts


def build_prisma_flow_note(review_dir: pathlib.Path, flow_counts: dict[str, str]) -> str:
    identified = parse_int(flow_counts.get("identified"))
    screened = parse_int(flow_counts.get("screened_title_abstract"))
    assessed = parse_int(flow_counts.get("full_text_assessed"))
    included = parse_int(flow_counts.get("included_in_review"))
    if max(identified, screened, assessed, included) <= 0:
        return "\n".join(
            [
                "#research/prisma #hermes/review",
                "",
                "- Estado: flujo PRISMA todavía no consolidado",
                "- Lectura: Hermes aún no ha generado conteos útiles porque la revisión está en bootstrap o antes del cribado inicial.",
            ]
        )

    if included > 0:
        status = "Flujo PRISMA consolidado"
        explanation = "Los conteos ya reflejan estudios incluidos y sirven como base del manuscrito."
    elif assessed > 0:
        status = "Flujo PRISMA parcial con texto completo"
        explanation = "Hermes ya está evaluando PDFs completos, pero el corpus final todavía no está cerrado."
    elif screened > 0:
        status = "Flujo PRISMA parcial tras screening inicial"
        explanation = "Hermes ya cerró el cribado de título/resumen y ahora está recuperando y leyendo PDFs."
    else:
        status = "Flujo PRISMA inicial"
        explanation = "La búsqueda ya arrancó, pero el cribado aún no se ha consolidado."

    return "\n".join(
        [
            "#research/prisma #hermes/review",
            "",
            f"- Estado: {status}",
            f"- Lectura: {explanation}",
            "",
            "## Conteos actuales",
            csv_to_markdown(review_dir / "prisma" / "flow-counts.csv"),
        ]
    )


def build_search_log_note(review_dir: pathlib.Path) -> str:
    rows = read_csv_rows(review_dir / "searches" / "search-log.csv")
    if not rows:
        return pending_note("Hermes aún no ha registrado búsquedas reproducibles para esta revisión.")
    source_counter = Counter(normalize_cell(row.get("source")) or "desconocido" for row in rows)
    platform_counter = Counter(normalize_cell(row.get("platform")) or "desconocido" for row in rows)
    author_filtered = sum(1 for row in rows if is_present(row.get("author_filter")))
    failed_runs = sum(1 for row in rows if "error" in normalize_cell(row.get("notes")).lower())
    date_values = sorted({normalize_cell(row.get("run_date")) for row in rows if is_present(row.get("run_date"))})
    sample_rows = []
    for row in rows[: min(6, len(rows))]:
        sample_rows.append(
            [
                normalize_cell(row.get("source")) or "no reportado",
                normalize_cell(row.get("query_string")) or "no reportado",
                normalize_cell(row.get("notes")) or "sin notas",
            ]
        )
    return "\n".join(
        [
            "#research/search #hermes/review",
            "",
            f"- Corridas registradas: {len(rows)}",
            f"- Fuentes activadas: {len(source_counter)}",
            f"- Plataformas activadas: {len(platform_counter)}",
            f"- Búsquedas con filtro de autor: {author_filtered}",
            f"- Corridas con error registrado: {failed_runs}",
            f"- Fechas de ejecución: {', '.join(date_values) if date_values else 'no reportado'}",
            f"- Artefacto crudo: {attachment_link(pathlib.Path('_artifacts/searches/search-log.csv'), 'search-log.csv')}",
            "",
            "## Distribución por fuente",
            counter_to_table(source_counter, "source"),
            "",
            "## Distribución por plataforma",
            counter_to_table(platform_counter, "platform"),
            "",
            "## Muestra de queries",
            markdown_table(["source", "query", "notes"], sample_rows),
        ]
    )


def build_records_note(review_dir: pathlib.Path) -> str:
    rows = read_csv_rows(review_dir / "records" / "master-records.csv")
    if not rows:
        return pending_note("Hermes aún no ha consolidado el registro maestro de estudios.")
    source_counter = Counter(normalize_cell(row.get("source")) or "desconocido" for row in rows)
    year_counter = Counter(normalize_cell(row.get("year")) or "desconocido" for row in rows)
    status_counter = Counter(normalize_cell(row.get("status")) or "sin estado" for row in rows)
    doi_present = sum(1 for row in rows if is_present(row.get("assigned_doi")))
    doi_missing = len(rows) - doi_present
    doi_resolution_needed = sum(1 for row in rows if normalize_cell(row.get("needs_doi_resolution")) == "yes")
    sample_rows = []
    for row in rows[: min(8, len(rows))]:
        sample_rows.append(
            [
                normalize_cell(row.get("record_id")) or "no reportado",
                normalize_cell(row.get("source")) or "no reportado",
                normalize_cell(row.get("year")) or "no reportado",
                normalize_cell(row.get("assigned_doi")) or "sin DOI",
                (normalize_cell(row.get("title_original")) or normalize_cell(row.get("title_en")) or "sin título")[:90],
            ]
        )
    return "\n".join(
        [
            "#research/records #hermes/review",
            "",
            f"- Registros maestros consolidados: {len(rows)}",
            f"- DOI asignado: {doi_present}",
            f"- DOI ausente: {doi_missing}",
            f"- DOI aún por resolver: {doi_resolution_needed}",
            f"- Artefacto crudo: {attachment_link(pathlib.Path('_artifacts/records/master-records.csv'), 'master-records.csv')}",
            "",
            "## Distribución por fuente",
            counter_to_table(source_counter, "source"),
            "",
            "## Distribución por año",
            counter_to_table(year_counter, "year"),
            "",
            "## Estado de normalización",
            counter_to_table(status_counter, "status"),
            "",
            "## Muestra de registros",
            markdown_table(["record_id", "source", "year", "doi", "title"], sample_rows),
        ]
    )


def build_title_abstract_note(
    review_dir: pathlib.Path,
    flow_counts: dict[str, str],
    has_ta: bool,
    detail_ready: bool,
) -> str:
    if not has_ta:
        return pending_note("Hermes aún no ha cerrado el screening de título y resumen.")
    assessed = parse_int(flow_counts.get("full_text_assessed"))
    included = parse_int(flow_counts.get("included_in_review"))
    if detail_ready and (assessed > 0 or included > 0):
        return csv_to_markdown(review_dir / "screening" / "title-abstract.csv")
    screened = parse_int(flow_counts.get("screened_title_abstract"))
    excluded = parse_int(flow_counts.get("excluded_title_abstract"))
    sought = parse_int(flow_counts.get("full_text_sought"))
    return "\n".join(
        [
            "#research/screening #hermes/review",
            "",
            "- Estado: screening de título/resumen cerrado, a la espera de lectura completa en PDF.",
            f"- Registros cribados: {screened}",
            f"- Registros excluidos en esta fase: {excluded}",
            f"- Candidatos enviados a recuperación de PDF/texto completo: {sought}",
            f"- Artefacto crudo: {attachment_link(pathlib.Path('_artifacts/screening/title-abstract.csv'), 'title-abstract.csv')}",
        ]
    )


def build_full_text_note(
    review_dir: pathlib.Path,
    flow_counts: dict[str, str],
    has_ft: bool,
    detail_ready: bool,
) -> str:
    assessed = parse_int(flow_counts.get("full_text_assessed"))
    included = parse_int(flow_counts.get("included_in_review"))
    sought = parse_int(flow_counts.get("full_text_sought"))
    retrieved = parse_int(flow_counts.get("full_text_retrieved"))
    not_retrieved = parse_int(flow_counts.get("full_text_not_retrieved"))
    excluded = parse_int(flow_counts.get("full_text_excluded"))
    if detail_ready and included > 0 and has_ft:
        return csv_to_markdown(review_dir / "screening" / "full-text.csv")
    if max(sought, retrieved, not_retrieved, assessed, excluded, included) <= 0:
        return pending_note("Hermes aún no ha llegado a la fase de texto completo.")
    status = "recuperación de PDFs en curso"
    if assessed > 0:
        status = "screening a texto completo en curso"
    return "\n".join(
        [
            "#research/fulltext #hermes/review",
            "",
            f"- Estado: {status}.",
            f"- Candidatos a texto completo: {sought}",
            f"- PDFs recuperados: {retrieved}",
            f"- PDFs no recuperados: {not_retrieved}",
            f"- Estudios evaluados a texto completo: {assessed}",
            f"- Estudios excluidos tras lectura completa: {excluded}",
            f"- Estudios ya incluidos en la revisión: {included}",
            f"- Artefacto crudo: {attachment_link(pathlib.Path('_artifacts/screening/full-text.csv'), 'full-text.csv')}",
        ]
    )


def study_note_relpath(record_id: str) -> pathlib.Path:
    return pathlib.Path("Studies") / f"{slugify(record_id)}.md"


def graph_note_relpath(kind: str, label: str) -> pathlib.Path:
    return pathlib.Path("Graph") / kind / f"{slugify(label)}.md"


def note_link(relpath: pathlib.Path, alias: str | None = None) -> str:
    target = relpath.as_posix()
    if target.endswith(".md"):
        target = target[:-3]
    if alias:
        return f"[[{target}|{alias}]]"
    return f"[[{target}]]"


def attachment_link(relpath: pathlib.Path, alias: str | None = None) -> str:
    target = relpath.as_posix()
    if alias:
        return f"[[{target}|{alias}]]"
    return f"[[{target}]]"


def derive_arxiv_pdf_url(row: dict[str, str]) -> str:
    doi = normalize_cell(row.get("assigned_doi")).lower()
    if doi.startswith("10.48550/arxiv."):
        arxiv_id = doi.split("10.48550/arxiv.", 1)[1]
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    source_url = normalize_cell(row.get("full_text_path"))
    if "arxiv.org/abs/" in source_url:
        return source_url.replace("/abs/", "/pdf/") + ".pdf"
    return ""


def find_local_fulltext(review_dir: pathlib.Path, row: dict[str, str]) -> tuple[pathlib.Path | None, str]:
    record_id = normalize_cell(row.get("record_id"))
    stem = slugify(record_id)
    candidates = [
        review_dir / "fulltext" / "pdf" / f"{stem}.pdf",
        review_dir / "fulltext" / f"{stem}.pdf",
    ]
    full_text_path = normalize_cell(row.get("full_text_path"))
    if full_text_path and not full_text_path.startswith(("http://", "https://")):
        local_path = pathlib.Path(full_text_path).expanduser()
        if local_path.suffix.lower() == ".pdf":
            candidates.insert(0, local_path)
    for candidate in candidates:
        if candidate.exists():
            suffix = candidate.suffix.lower().lstrip(".") or "file"
            return candidate, suffix
    return None, ""


def try_download_fulltext_attachment(
    row: dict[str, str],
    attachment_dir: pathlib.Path,
) -> tuple[pathlib.Path | None, str, str]:
    record_id = normalize_cell(row.get("record_id"))
    stem = slugify(record_id)
    source_url = derive_arxiv_pdf_url(row) or normalize_cell(row.get("full_text_path"))
    if not source_url:
        return None, "", "missing_source_url"
    if not source_url.startswith(("http://", "https://")):
        return None, source_url, "unsupported_local_source"

    request = urllib.request.Request(source_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            final_url = response.geturl()
            body = response.read()
    except Exception:
        return None, source_url, "download_failed"

    if "pdf" in content_type or final_url.lower().endswith(".pdf") or source_url.lower().endswith(".pdf"):
        target = attachment_dir / f"{stem}.pdf"
        target.write_bytes(body)
        return target, final_url or source_url, "downloaded_pdf"

    return None, final_url or source_url, "unsupported_content_type"


def ensure_selected_fulltext_attachments(
    review_dir: pathlib.Path,
    dest: pathlib.Path,
    included_rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    attachment_dir = dest / "Attachments" / "Selected Full Text"
    if not included_rows:
        if attachment_dir.exists():
            shutil.rmtree(attachment_dir)
        attachments_root = dest / "Attachments"
        if attachments_root.exists() and not any(attachments_root.iterdir()):
            attachments_root.rmdir()
        return {}
    ensure_dir(attachment_dir)
    attachment_map: dict[str, dict[str, str]] = {}
    for row in included_rows:
        if normalize_cell(row.get("selected_for_final_n")) != "yes":
            continue
        record_id = normalize_cell(row.get("record_id"))
        if not record_id:
            continue
        source_url = normalize_cell(row.get("full_text_path"))
        local_path, kind = find_local_fulltext(review_dir, row)
        if local_path:
            target = attachment_dir / f"{slugify(record_id)}{local_path.suffix.lower()}"
            shutil.copy2(local_path, target)
            attachment_map[record_id] = {
                "attachment_relpath": str(target.relative_to(dest)),
                "attachment_kind": kind or target.suffix.lstrip("."),
                "status": "local_copy",
                "source_url": source_url,
            }
            continue

        downloaded_path, resolved_url, status = try_download_fulltext_attachment(row, attachment_dir)
        if downloaded_path:
            attachment_map[record_id] = {
                "attachment_relpath": str(downloaded_path.relative_to(dest)),
                "attachment_kind": downloaded_path.suffix.lower().lstrip("."),
                "status": status,
                "source_url": resolved_url or source_url,
            }
            continue

        attachment_map[record_id] = {
            "attachment_relpath": "",
            "attachment_kind": "",
            "status": status,
            "source_url": resolved_url or source_url,
        }
    return attachment_map


def merge_row_data(existing: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    overwrite_keys = {
        "work_type",
        "empirical_type",
        "countries",
        "sample_description",
        "sample_size",
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
        "selected_for_final_n",
        "ultraquality_rank",
        "ultraquality_score",
        "representativeness_score",
        "methodological_quality_score",
        "relevance_score",
        "selection_reason",
        "cap_exclusion_reason",
    }
    merged = dict(existing)
    for key, value in incoming.items():
        if not is_present(value):
            continue
        if key in overwrite_keys or not is_present(merged.get(key)):
            merged[key] = value
    return merged


def build_combined_rows(
    master_rows: list[dict[str, str]],
    full_text_rows: list[dict[str, str]],
    extraction_rows: list[dict[str, str]],
    selection_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    records: dict[str, dict[str, str]] = {}
    for row in master_rows:
        record_id = normalize_cell(row.get("record_id"))
        if not record_id:
            continue
        records[record_id] = merge_row_data(records.get(record_id, {}), row)
    for row in full_text_rows + extraction_rows + selection_rows:
        record_id = normalize_cell(row.get("record_id"))
        if not record_id:
            continue
        records[record_id] = merge_row_data(records.get(record_id, {}), row)

    included_ids = {
        normalize_cell(row.get("record_id"))
        for row in full_text_rows
        if normalize_cell(row.get("decision")) == "include"
    }
    included_ids.update(normalize_cell(row.get("record_id")) for row in selection_rows if normalize_cell(row.get("record_id")))
    combined = [records[record_id] for record_id in included_ids if record_id in records]
    combined.sort(
        key=lambda row: (
            normalize_cell(row.get("selected_for_final_n")) != "yes",
            parse_int(row.get("ultraquality_rank"), 9999),
            normalize_cell(row.get("title_original")) or normalize_cell(row.get("record_id")),
        )
    )
    return combined, records


def classify_themes(row: dict[str, str]) -> list[str]:
    text = normalized_text(
        row.get("title_original"),
        row.get("title_en"),
        row.get("abstract_en"),
        row.get("abstract_original"),
        row.get("keywords_normalized"),
        row.get("keywords_author"),
        row.get("key_findings"),
    )
    themes: list[str] = []
    for label, needles in THEME_RULES:
        if any(needle in text for needle in needles):
            themes.append(label)
    if not themes:
        themes = ["Otros temas"]
    return themes[:3]


def extraction_warning_summary(included_rows: list[dict[str, str]]) -> list[str]:
    warnings = []
    fallback_count = sum("fallback_dedup_postprocess=yes" in normalize_cell(row.get("notes")) for row in included_rows)
    missing_method_count = sum(not is_present(row.get("method_used")) for row in included_rows)
    missing_theory_count = sum(not is_present(row.get("theory_framework")) for row in included_rows)
    missing_country_count = sum(not is_present(row.get("countries")) for row in included_rows)
    if fallback_count:
        warnings.append(
            f"- {fallback_count} estudios incluidos siguen con extracción de respaldo y requieren lectura/depuración adicional."
        )
    if missing_method_count:
        warnings.append(f"- {missing_method_count} estudios no informan todavía método con suficiente detalle.")
    if missing_theory_count:
        warnings.append(f"- {missing_theory_count} estudios no tienen marco teórico explícito capturado.")
    if missing_country_count:
        warnings.append(f"- {missing_country_count} estudios no tienen país o contexto geográfico normalizado.")
    return warnings


def build_overview(
    review_dir: pathlib.Path,
    topic_slug: str,
    flow_counts: dict[str, str],
    included_rows: list[dict[str, str]],
) -> str:
    files = {
        "search_log": review_dir / "searches" / "search-log.csv",
        "master_records": review_dir / "records" / "master-records.csv",
        "title_abstract": review_dir / "screening" / "title-abstract.csv",
        "full_text": review_dir / "screening" / "full-text.csv",
        "selection": review_dir / "selection" / "ultraquality-shortlist.csv",
        "extraction": review_dir / "extraction" / "extraction-table.csv",
        "figures_manifest": review_dir / "figures" / "manifest.csv",
    }
    search_rows, _ = summarize_counts(files["search_log"])
    master_rows, _ = summarize_counts(files["master_records"])
    ta_rows, _ = summarize_counts(files["title_abstract"])
    ft_rows, _ = summarize_counts(files["full_text"])
    selection_rows, _ = summarize_counts(files["selection"])
    extraction_rows, _ = summarize_counts(files["extraction"])
    figure_rows, _ = summarize_counts(files["figures_manifest"])
    included_count = parse_int(flow_counts.get("included_in_review"))
    final_n = sum(normalize_cell(row.get("selected_for_final_n")) == "yes" for row in included_rows)
    dossier_state = "Registro fuerte y síntesis preliminar; todavía no es un manuscrito final."
    if final_n and extraction_rows >= final_n:
        dossier_state = "Registro fuerte con shortlist final; falta cierre editorial y síntesis narrativa completa."
    lines = [
        "#research/prisma #hermes/review #obsidian/graph",
        "",
        f"- Topic slug: `{topic_slug}`",
        f"- Review folder: `{review_dir}`",
        f"- Estado del dossier: {dossier_state}",
        "",
        "## Navegacion sugerida",
        f"- {note_link(pathlib.Path('01 Intake.md'), 'Intake')}",
        f"- {note_link(pathlib.Path('01 Review Mode.md'), 'Modo metodológico')}",
        f"- {note_link(pathlib.Path('02 Protocol.md'), 'Protocolo')}",
        f"- {note_link(pathlib.Path('03 Search Log.md'), 'Búsquedas')}",
        f"- {note_link(pathlib.Path('04 Records.md'), 'Registros maestros')}",
        f"- {note_link(pathlib.Path('08 PRISMA Flow.md'), 'Estado PRISMA')}",
        f"- {note_link(pathlib.Path('09 Decisions.md'), 'Decisiones')}",
        f"- {note_link(pathlib.Path('10 Runtime State.md'), 'Estado de ejecución')}",
        f"- {note_link(pathlib.Path('12 Phase Audit.md'), 'Auditoría por fases')}",
        f"- {note_link(pathlib.Path('22 Phase Model.md'), 'Modelo de fases')}",
        f"- {note_link(pathlib.Path('24 Publication Package.md'), 'Paquete de publicacion')}",
        f"- {note_link(pathlib.Path('25 APA Reference Workflow.md'), 'Flujo APA')}",
        f"- {note_link(pathlib.Path('26 Figure Intelligence Workflow.md'), 'Flujo de figuras y vision')}",
        f"- {note_link(pathlib.Path('30 Publication Workspace.md'), 'Workspace de publicacion')}",
        "- Las notas avanzadas de screening, extracción, figuras, manuscrito y revisión cruzada solo aparecen cuando Hermes ya tiene contenido maduro para exportarlas.",
        "",
        "## Current Counts",
        f"- Search log rows: {search_rows}",
        f"- Master records: {master_rows}",
        f"- Title/abstract rows: {ta_rows}",
        f"- Full-text rows: {ft_rows}",
        f"- Included in review: {included_count}",
        f"- Ultraquality shortlist rows: {selection_rows}",
        f"- Selected for final N: {final_n}",
        f"- Extraction rows: {extraction_rows}",
        f"- Figures in manifest: {figure_rows}",
        "",
        "## Advertencias metodologicas",
        "- Esta carpeta mezcla artefactos crudos y una capa curada para lectura investigadora.",
        "- El flujo tecnicamente esta cerrado, pero la validacion editorial RAE/APA sigue pendiente.",
        "- Las corridas nuevas exigen PDF completo; las revisiones heredadas pueden reflejar reglas históricas más laxas.",
        "- El vault ya no debería llenarse de notas vacías: los documentos aparecen cuando la fase correspondiente ya aporta contenido real.",
    ]
    warnings = extraction_warning_summary(included_rows)
    if warnings:
        lines.extend(warnings)
    lines.extend(
        [
            "",
            "## Notes",
            "- Esta carpeta se refresca incrementalmente tras actualizaciones materiales.",
            "- Los ficheros crudos siguen espejados bajo `_artifacts/` para trazabilidad completa.",
        ]
    )
    return "\n".join(lines)


def build_figures_note(review_dir: pathlib.Path) -> str:
    manifest_path = review_dir / "figures" / "manifest.csv"
    ranking_csv_path = review_dir / "figures" / "figure-ranking.csv"
    ranking_md_path = review_dir / "figures" / "figure-ranking.md"
    catalog_path = review_dir / "figures" / "figure-catalog.md"
    rows = read_manifest_rows(manifest_path)
    if not rows:
        return "_No figures yet._"
    lines = ["#research/figures #obsidian/graph", ""]
    if catalog_path.exists() or ranking_csv_path.exists() or ranking_md_path.exists():
        lines.append("## Curaduría")
        if catalog_path.exists():
            lines.append("- Catálogo: `figures/figure-catalog.md`")
        if ranking_csv_path.exists():
            lines.append("- Ranking CSV: `figures/figure-ranking.csv`")
        if ranking_md_path.exists():
            lines.append("- Ranking MD: `figures/figure-ranking.md`")
        lines.append("")
    for row in rows:
        figure_id = (row.get("figure_id") or "").strip() or "figure"
        title = (row.get("title") or "").strip() or figure_id
        phase = (row.get("phase") or "").strip()
        paper_section = (row.get("paper_section") or "").strip()
        figure_type = (row.get("figure_type") or "").strip()
        purpose = (row.get("purpose") or "").strip()
        evidence_basis = (row.get("evidence_basis") or "").strip()
        style_profile = (row.get("style_profile") or "").strip()
        apa_caption = (row.get("apa_caption") or "").strip()
        status = (row.get("status") or "").strip()
        png_path = (row.get("png_path") or "").strip()
        notes = (row.get("notes") or "").strip()
        lines.append(f"## {title}")
        if phase:
            lines.append(f"- Fase: {phase}")
        if paper_section:
            lines.append(f"- Sección del paper: {paper_section}")
        if figure_type:
            lines.append(f"- Tipo: {figure_type}")
        if purpose:
            lines.append(f"- Propósito: {purpose}")
        if evidence_basis:
            lines.append(f"- Base de evidencia: {evidence_basis}")
        if style_profile:
            lines.append(f"- Estilo: {style_profile}")
        if apa_caption:
            lines.append(f"- Leyenda APA base: {apa_caption}")
        if status:
            lines.append(f"- Estado: {status}")
        if png_path:
            lines.append(f"- PNG: `{png_path}`")
            lines.append(f"![](_artifacts/{png_path})")
        if notes:
            lines.append(f"- Notas: {notes}")
        lines.append("")
    return "\n".join(lines).strip() or "_No figures yet._"


def build_executive_summary(
    flow_counts: dict[str, str],
    included_rows: list[dict[str, str]],
) -> str:
    identified = parse_int(flow_counts.get("identified"))
    screened = parse_int(flow_counts.get("screened_title_abstract"))
    assessed = parse_int(flow_counts.get("full_text_assessed"))
    included = parse_int(flow_counts.get("included_in_review"))
    selected = sum(normalize_cell(row.get("selected_for_final_n")) == "yes" for row in included_rows)
    top_rows = [row for row in included_rows if normalize_cell(row.get("selected_for_final_n")) == "yes"][:5]
    lines = [
        "#research/summary #hermes/review",
        "",
        "> Resumen ejecutivo automatizado y orientado a investigador. Requiere validacion editorial final antes de usarlo como texto de manuscrito.",
        "",
        "## Foto rapida",
        f"- Registros identificados: {identified}",
        f"- Registros cribados en titulo/resumen: {screened}",
        f"- Registros evaluados en fase final: {assessed}",
        f"- Estudios incluidos en la revision: {included}",
        f"- Subconjunto ultraquality seleccionado: {selected}",
        "",
        "## Lectura general",
        "- El corpus ya permite una primera lectura investigadora, pero sigue siendo una sintesis preliminar.",
        "- Predominan trabajos sobre evaluacion de agentes de software, benchmarks, pull requests y tareas de testing/debugging.",
        "- La evidencia apunta a una tension recurrente entre ganancia de productividad y riesgos de calidad, mantenibilidad o necesidad de supervision humana.",
        "- La capa metodologica aun es desigual: algunos estudios tienen muy buena señal empirica, mientras otros siguen con extraccion basada en metadatos.",
        "",
        "## Estudios que ahora mismo conviene leer primero",
    ]
    if not top_rows:
        lines.append("- Todavia no hay estudios destacados seleccionados.")
    for row in top_rows:
        relpath = study_note_relpath(normalize_cell(row.get("record_id")))
        title = normalize_cell(row.get("title_original")) or normalize_cell(row.get("title_en")) or normalize_cell(row.get("record_id"))
        finding = normalize_cell(row.get("key_findings")) or "Pendiente de sintesis interpretativa."
        lines.append(f"- {note_link(relpath, title)}: {finding}")
    lines.extend(
        [
            "",
            "## Advertencias",
            "- No todo lo incluido tiene todavia el mismo nivel de profundidad de lectura o extraccion.",
            "- La redaccion RAE y las referencias APA siguen pendientes de auditoria manual final.",
        ]
    )
    return "\n".join(lines)


def build_corpus_characterization(included_rows: list[dict[str, str]]) -> str:
    source_counter = Counter(normalize_cell(row.get("source")) or "desconocido" for row in included_rows)
    work_type_counter = Counter(normalize_cell(row.get("work_type")) or "desconocido" for row in included_rows)
    empirical_counter = Counter(
        normalize_cell(row.get("empirical_type")) or "no reportado" for row in included_rows
    )
    doi_missing = sum(not is_present(row.get("assigned_doi")) for row in included_rows)
    method_missing = sum(not is_present(row.get("method_used")) for row in included_rows)
    theory_missing = sum(not is_present(row.get("theory_framework")) for row in included_rows)
    country_missing = sum(not is_present(row.get("countries")) for row in included_rows)
    selected_rows = [row for row in included_rows if normalize_cell(row.get("selected_for_final_n")) == "yes"]
    table_rows = []
    for row in selected_rows[:12]:
        relpath = study_note_relpath(normalize_cell(row.get("record_id")))
        table_rows.append(
            [
                note_link(relpath, normalize_cell(row.get("title_original")) or normalize_cell(row.get("record_id"))),
                normalize_cell(row.get("work_type")) or "no reportado",
                normalize_cell(row.get("empirical_type")) or "no reportado",
                normalize_cell(row.get("source")) or "no reportado",
                normalize_cell(row.get("assigned_doi")) or "sin DOI",
            ]
        )
    lines = [
        "#research/corpus #obsidian/graph",
        "",
        "## Distribucion por fuente",
        counter_to_table(source_counter, "source"),
        "",
        "## Distribucion por tipo de trabajo",
        counter_to_table(work_type_counter, "work_type"),
        "",
        "## Distribucion por tipo empirico",
        counter_to_table(empirical_counter, "empirical_type"),
        "",
        "## Cobertura de metadatos",
        f"- Estudios incluidos sin DOI asignado: {doi_missing}",
        f"- Estudios incluidos sin metodo capturado: {method_missing}",
        f"- Estudios incluidos sin teoria capturada: {theory_missing}",
        f"- Estudios incluidos sin pais/contexto geografico capturado: {country_missing}",
        "",
        "## Muestra de estudios del shortlist",
    ]
    if table_rows:
        lines.append(
            markdown_table(
                ["study", "work_type", "empirical_type", "source", "doi"],
                table_rows,
            )
        )
    else:
        lines.append("- Hermes aún no ha cerrado el shortlist final; esta muestra aparecerá cuando exista selección ultraquality.")
    return "\n".join(lines)


def build_thematic_synthesis(included_rows: list[dict[str, str]]) -> str:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in included_rows:
        for theme in classify_themes(row):
            grouped[theme].append(row)
    lines = [
        "#research/synthesis #research/themes #obsidian/graph",
        "",
        "> Sintesis tematica preliminar. Pensada para orientar lectura y analisis, no para sustituir una redaccion final con citas APA validadas.",
    ]
    for theme in sorted(grouped):
        relpath = graph_note_relpath("Themes", theme)
        lines.extend(["", f"## {note_link(relpath, theme)}"])
        top_rows = sorted(
            grouped[theme],
            key=lambda row: (
                normalize_cell(row.get("selected_for_final_n")) != "yes",
                parse_int(row.get("ultraquality_rank"), 9999),
                normalize_cell(row.get("title_original")),
            ),
        )[:6]
        for row in top_rows:
            study_link = note_link(
                study_note_relpath(normalize_cell(row.get("record_id"))),
                normalize_cell(row.get("title_original")) or normalize_cell(row.get("record_id")),
            )
            finding = normalize_cell(row.get("key_findings")) or "Sin hallazgo sintetizado todavia; revisar ficha del estudio."
            lines.append(f"- {study_link}: {finding}")
    return "\n".join(lines)


def build_methodological_synthesis(included_rows: list[dict[str, str]]) -> str:
    empirical_rows = [row for row in included_rows if normalize_cell(row.get("work_type")) == "empirical"]
    reported_sample = sum(is_present(row.get("sample_size")) or is_present(row.get("sample_description")) for row in empirical_rows)
    reported_method = sum(is_present(row.get("method_used")) for row in empirical_rows)
    reported_theory = sum(is_present(row.get("theory_framework")) for row in included_rows)
    high_conf_rows = [row for row in included_rows if parse_int(row.get("extraction_confidence")) >= 80]
    table_rows = []
    for row in sorted(high_conf_rows, key=lambda item: -parse_int(item.get("extraction_confidence")))[:10]:
        table_rows.append(
            [
                note_link(study_note_relpath(normalize_cell(row.get("record_id"))), normalize_cell(row.get("title_original")) or normalize_cell(row.get("record_id"))),
                normalize_cell(row.get("work_type")) or "no reportado",
                normalize_cell(row.get("empirical_type")) or "no reportado",
                normalize_cell(row.get("method_used")) or "no reportado",
                normalize_cell(row.get("sample_size")) or "no reportado",
                normalize_cell(row.get("extraction_confidence")) or "0",
            ]
        )
    lines = [
        "#research/methodology #obsidian/graph",
        "",
        "## Lectura metodologica",
        f"- Estudios empiricos identificados: {len(empirical_rows)}",
        f"- Estudios empiricos con muestra reportada: {reported_sample}",
        f"- Estudios empiricos con metodo explicitado: {reported_method}",
        f"- Estudios incluidos con marco teorico explicitado: {reported_theory}",
        "",
        "## Lo que ya se puede sostener",
        "- Hay suficiente base para una caracterizacion inicial del corpus por tipo de trabajo, foco y nivel de evidencia.",
        "- Todavia no hay homogeneidad suficiente para tratar todo el corpus como extraccion profunda equivalente.",
        "",
        "## Estudios con mejor señal metodologica capturada",
        "",
        "## Alertas metodologicas",
    ]
    if table_rows:
        lines.insert(
            -2,
            markdown_table(
                ["study", "work_type", "empirical_type", "method", "sample_size", "confidence"],
                table_rows,
            ),
        )
    else:
        lines.insert(-2, "- Aún no hay estudios con extracción metodológica suficientemente madura para destacar un subconjunto fiable.")
    warnings = extraction_warning_summary(included_rows)
    if warnings:
        lines.extend(warnings)
    else:
        lines.append("- No se detectaron alertas obvias de completitud.")
    return "\n".join(lines)


def build_studies_hub(included_rows: list[dict[str, str]]) -> str:
    rows = []
    for row in included_rows:
        record_id = normalize_cell(row.get("record_id"))
        title = normalize_cell(row.get("title_original")) or normalize_cell(row.get("record_id"))
        themes = ", ".join(classify_themes(row))
        rows.append(
            [
                note_link(study_note_relpath(record_id), title),
                "yes" if normalize_cell(row.get("selected_for_final_n")) == "yes" else "no",
                normalize_cell(row.get("work_type")) or "no reportado",
                normalize_cell(row.get("source")) or "no reportado",
                normalize_cell(row.get("assigned_doi")) or "sin DOI",
                themes,
            ]
        )
    return "\n".join(
        [
            "#research/studies #obsidian/graph",
            "",
            markdown_table(
                ["study", "selected_final_n", "work_type", "source", "doi", "themes"],
                rows,
            ),
        ]
    )


def build_phase_model() -> str:
    return "\n".join(
        [
            "#research/phases #hermes/review",
            "",
            "## Fase 1: Construccion del corpus",
            "- 1.1 Intake y protocolo",
            "- 1.2 Busqueda, DOI y deduplicacion",
            "- 1.3 Screening de titulo/resumen",
            "- 1.4 Screening final y shortlist ultraquality",
            "- 1.5 Extraccion base, auditoria y trazabilidad",
            "",
            "## Fase 2: Explotacion del corpus",
            "- 2.1 Biblioteca de textos completos de los estudios seleccionados",
            "- 2.2 Extraccion profunda a partir de PDF completo",
            "- 2.3 Desarrollo del indice o esquema que marque el investigador",
            "- 2.4 Sintesis narrativa, comparativa y metodologica",
            "- 2.5 Figuras, tablas, trazabilidad y cierre del dossier de evidencia",
            "",
            "## Fase 3: Redaccion del paper publicable",
            "- 3.1 Convertir el indice del investigador en secciones de manuscrito",
            "- 3.2 Redactar cada seccion con llamadas parciales y contexto acotado",
            "- 3.3 Consolidar citas en estilo APA y verificar que cada afirmacion interpretativa este anclada a uno o varios estudios",
            "- 3.4 Ajustar tono, estructura y aparato critico al tipo de revista cientifica objetivo",
            "- 3.5 Ejecutar auditoria editorial final antes de considerar el paper listo para envio",
            "",
            "## Regla operativa",
            "- La Fase 2 solo debe consolidarse cuando el corpus de investigacion ya esta suficientemente estable.",
            "- El indice del investigador actua como esqueleto de la Fase 2.",
            "- La Fase 3 no debe ejecutarse como una sola llamada larga al LLM; se debe componer por secciones y sub-secciones para no degradar calidad ni perder trazabilidad.",
        ]
    )


def build_publication_package() -> str:
    return "\n".join(
        [
            "#research/publication #hermes/writing",
            "",
            "## Objetivo",
            "- Convertir el corpus ya estabilizado en un paper con rango académico y potencial de envio a revista.",
            "",
            "## Principios",
            "- El indice del investigador es el esqueleto del paper.",
            "- La escritura debe hacerse por bloques pequeños o medianos, no en una sola llamada de contexto masivo.",
            "- Cada seccion debe trabajar sobre un subconjunto delimitado del corpus, con sus notas y citas de apoyo.",
            "- Las afirmaciones interpretativas deben quedar vinculadas a estudios concretos y luego traducirse a referencias APA.",
            "",
            "## Unidades de trabajo sugeridas",
            "- Titulo, resumen y palabras clave",
            "- Introduccion",
            "- Marco teorico / antecedentes",
            "- Metodo de revision",
            "- Resultados / sintesis",
            "- Discusion",
            "- Conclusiones e implicaciones",
            "- Referencias APA",
            "- Anexos, figuras y tablas",
            "",
            "## Criterios de calidad para revista",
            "- Coherencia argumental y posicionamiento frente al estado del arte",
            "- Claridad metodologica y trazabilidad del corpus",
            "- Sintesis critica, no solo descriptiva",
            "- Ajuste al estilo de la revista objetivo",
            "- Cumplimiento formal de referencias APA",
        ]
    )


def build_apa_reference_workflow(included_rows: list[dict[str, str]]) -> str:
    doi_count = sum(is_present(row.get("assigned_doi")) for row in included_rows)
    no_doi_count = len(included_rows) - doi_count
    return "\n".join(
        [
            "#research/apa #hermes/references",
            "",
            "## Regla general",
            "- Toda sintesis academica debe citarse en APA y luego resolverse a una referencia bibliografica completa.",
            "",
            "## Flujo de trabajo recomendado",
            "- 1. Redactar por secciones, no en una sola llamada al modelo.",
            "- 2. En cada seccion, trabajar con el subconjunto de estudios realmente usados.",
            "- 3. Marcar cada afirmacion con sus estudios de respaldo.",
            "- 4. Generar las referencias APA solo para los estudios efectivamente citados en esa seccion.",
            "- 5. Consolidar y desduplicar la bibliografia al final del manuscrito.",
            "- 6. Ejecutar una auditoria final de citas en texto y lista de referencias.",
            "",
            "## Estado actual del corpus",
            f"- Estudios incluidos con DOI asignado: {doi_count}",
            f"- Estudios incluidos sin DOI asignado: {no_doi_count}",
            "",
            "## Advertencias",
            "- Un DOI no sustituye la referencia APA completa; solo facilita su resolucion.",
            "- Los estudios sin DOI deben resolverse por metadatos antes del cierre bibliografico final.",
        ]
    )


def build_figure_intelligence_workflow() -> str:
    return "\n".join(
        [
            "#research/figures #research/vision #hermes/workflow",
            "",
            "## Rol dentro de las fases",
            "- En `Fase 2`, las figuras y tablas de los papers sirven para enriquecer la extracción profunda del corpus.",
            "- En `Fase 3`, las figuras y tablas finales del paper deben construirse a partir de la evidencia consolidada.",
            "",
            "## Flujo recomendado",
            "- 1. Detectar en los estudios seleccionados las figuras, tablas y diagramas realmente relevantes para el manuscrito.",
            "- 2. Guardar el activo visual o tabular fuente y registrarlo en su manifiesto.",
            "- 3. Si hay que interpretar imagen, leerla con el modelo auxiliar de visión.",
            "- 4. Convertir la evidencia visual en datos, notas o hallazgos trazables.",
            "- 5. Diseñar la figura final del paper en SVG y renderizarla a PNG.",
            "",
            "## Routing de modelos",
            "- Modelo principal configurado: planificación de búsqueda, extracción profunda, síntesis y ensamblaje del manuscrito.",
            "- Modelo visual configurado: lectura de páginas PDF renderizadas, tablas densas y figuras científicas.",
            "- Modelo revisor configurado: segunda lectura independiente para claridad, consistencia y riesgos de interpretación.",
            "",
            "## Regla de trazabilidad",
            "- Cada figura final del paper debería poder remontarse a uno o varios estudios, activos visuales fuente o tablas extraídas.",
        ]
    )


def build_visual_evidence_library(review_dir: pathlib.Path) -> str:
    figure_rows = read_manifest_rows(review_dir / "figures" / "evidence-manifest.csv")
    page_render_rows = read_manifest_rows(review_dir / "figures" / "page-render-manifest.csv")
    table_rows = read_manifest_rows(review_dir / "tables" / "evidence-manifest.csv")
    lines = [
        "#research/visual-evidence #obsidian/graph",
        "",
        "## Figuras extraídas de papers",
    ]
    if figure_rows:
        rows = []
        for row in figure_rows:
            rows.append(
                [
                    normalize_cell(row.get("record_id")) or "no reportado",
                    normalize_cell(row.get("asset_id")) or "no reportado",
                    normalize_cell(row.get("source_path")) or "no reportado",
                    normalize_cell(row.get("page_or_location")) or "no reportado",
                    normalize_cell(row.get("extracted_asset_path")) or "no reportado",
                    normalize_cell(row.get("vision_model")) or "no reportado",
                    normalize_cell(row.get("status")) or "no reportado",
                ]
            )
        lines.append(
            markdown_table(
                ["record_id", "asset_id", "source_path", "page_or_location", "extracted_asset_path", "vision_model", "status"],
                rows,
            )
        )
    else:
        lines.append("_Todavía no hay figuras extraídas registradas._")
    lines.extend(["", "## Renders de página de apoyo"])
    if page_render_rows:
        rows = []
        for row in page_render_rows:
            rows.append(
                [
                    normalize_cell(row.get("record_id")) or "no reportado",
                    normalize_cell(row.get("asset_id")) or "no reportado",
                    normalize_cell(row.get("source_path")) or "no reportado",
                    normalize_cell(row.get("page_or_location")) or "no reportado",
                    normalize_cell(row.get("extracted_asset_path")) or "no reportado",
                    normalize_cell(row.get("vision_model")) or "no reportado",
                    normalize_cell(row.get("status")) or "no reportado",
                ]
            )
        lines.extend(
            [
                "Estos activos son renders diagnósticos de páginas completas del PDF. Se conservan como apoyo de trazabilidad, pero no deben tratarse como figuras científicas extraídas ni como paneles válidos para el manuscrito final.",
                markdown_table(
                    ["record_id", "asset_id", "source_path", "page_or_location", "extracted_asset_path", "vision_model", "status"],
                    rows,
                ),
            ]
        )
    else:
        lines.append("_No hay renders de página de apoyo registrados._")
    lines.extend(["", "## Tablas extraídas de papers"])
    if table_rows:
        rows = []
        for row in table_rows:
            rows.append(
                [
                    normalize_cell(row.get("record_id")) or "no reportado",
                    normalize_cell(row.get("table_id")) or "no reportado",
                    normalize_cell(row.get("source_path")) or "no reportado",
                    normalize_cell(row.get("page_or_location")) or "no reportado",
                    normalize_cell(row.get("extracted_table_path")) or "no reportado",
                    normalize_cell(row.get("vision_model")) or "no reportado",
                    normalize_cell(row.get("status")) or "no reportado",
                ]
            )
        lines.append(
            markdown_table(
                ["record_id", "table_id", "source_path", "page_or_location", "extracted_table_path", "vision_model", "status"],
                rows,
            )
        )
    else:
        lines.append("_Todavía no hay tablas extraídas registradas._")
    return "\n".join(lines)


def build_paper_figures_plan(review_dir: pathlib.Path) -> str:
    rows = read_manifest_rows(review_dir / "figures" / "paper-figures-spec.csv")
    if not rows:
        return "_No paper figure plan yet._"
    table_rows = []
    for row in rows:
        table_rows.append(
            [
                normalize_cell(row.get("figure_id")) or "no reportado",
                normalize_cell(row.get("paper_section")) or "no reportado",
                normalize_cell(row.get("figure_type")) or "no reportado",
                normalize_cell(row.get("purpose")) or "no reportado",
                normalize_cell(row.get("evidence_basis")) or "no reportado",
                normalize_cell(row.get("style_profile")) or "no reportado",
                normalize_cell(row.get("apa_caption")) or "no reportado",
                normalize_cell(row.get("recommended_status")) or "no reportado",
            ]
        )
    return "\n".join(
        [
            "#research/publication #research/figures",
            "",
            "> Plan editorial para figuras del paper. Deben aportar evidencia o claridad conceptual; no se deben usar figuras genéricas decorativas.",
            "",
            markdown_table(
                [
                    "figure_id",
                    "paper_section",
                    "figure_type",
                    "purpose",
                    "evidence_basis",
                    "style_profile",
                    "apa_caption",
                    "recommended_status",
                ],
                table_rows,
            ),
        ]
    )


def build_paper_tables_plan(review_dir: pathlib.Path) -> str:
    rows = read_manifest_rows(review_dir / "tables" / "paper-tables-spec.csv")
    if not rows:
        return "_No paper table plan yet._"
    table_rows = []
    for row in rows:
        table_rows.append(
            [
                normalize_cell(row.get("table_id")) or "no reportado",
                normalize_cell(row.get("paper_section")) or "no reportado",
                normalize_cell(row.get("table_type")) or "no reportado",
                normalize_cell(row.get("purpose")) or "no reportado",
                normalize_cell(row.get("evidence_basis")) or "no reportado",
                normalize_cell(row.get("style_profile")) or "no reportado",
                normalize_cell(row.get("apa_caption")) or "no reportado",
                normalize_cell(row.get("recommended_status")) or "no reportado",
            ]
        )
    return "\n".join(
        [
            "#research/publication #research/tables",
            "",
            "> Plan editorial para tablas del paper. Las tablas deben condensar evidencia relevante y facilitar comparacion académica.",
            "",
            markdown_table(
                [
                    "table_id",
                    "paper_section",
                    "table_type",
                    "purpose",
                    "evidence_basis",
                    "style_profile",
                    "apa_caption",
                    "recommended_status",
                ],
                table_rows,
            ),
        ]
    )


def build_empirical_evidence_matrix(included_rows: list[dict[str, str]]) -> str:
    empirical_rows = []
    for row in included_rows:
        work_type = normalize_cell(row.get("work_type")).lower()
        if work_type == "empirical":
            empirical_rows.append(row)
    rows = []
    for row in sorted(
        empirical_rows,
        key=lambda item: (
            normalize_cell(item.get("selected_for_final_n")) != "yes",
            parse_int(item.get("ultraquality_rank"), 9999),
            normalize_cell(item.get("title_original")),
        ),
    ):
        rows.append(
            [
                note_link(
                    study_note_relpath(normalize_cell(row.get("record_id"))),
                    normalize_cell(row.get("title_original")) or normalize_cell(row.get("record_id")),
                ),
                normalize_cell(row.get("empirical_type")) or "no reportado",
                normalize_cell(row.get("countries")) or "no reportado",
                normalize_cell(row.get("sample_description")) or "no reportado",
                normalize_cell(row.get("sample_size")) or "no reportado",
                normalize_cell(row.get("method_used")) or "no reportado",
                normalize_cell(row.get("variables_dependent")) or "no reportado",
                normalize_cell(row.get("variables_independent")) or "no reportado",
                normalize_cell(row.get("variables_moderating")) or "no reportado",
                normalize_cell(row.get("variables_mediating")) or "no reportado",
                normalize_cell(row.get("variables_control")) or "no reportado",
                normalize_cell(row.get("theory_framework")) or "no reportado",
            ]
        )
    if not rows:
        return pending_note("Hermes aún no ha consolidado una extracción empírica suficiente para construir la matriz de evidencia.")
    return "\n".join(
        [
            "#research/empirical #obsidian/graph",
            "",
            "> Matriz pensada para lectura investigadora de trabajos empíricos. Si un campo sale como `no reportado`, conviene volver al paper o marcarlo como ausencia real de información.",
            "",
            markdown_table(
                [
                    "study",
                    "empirical_type",
                    "countries",
                    "sample_description",
                    "sample_size",
                    "method_used",
                    "variables_dependent",
                    "variables_independent",
                    "variables_moderating",
                    "variables_mediating",
                    "variables_control",
                    "theory_framework",
                ],
                rows,
            ),
        ]
    )


def build_selected_fulltext_library(
    included_rows: list[dict[str, str]],
    attachment_map: dict[str, dict[str, str]],
) -> str:
    rows = []
    for row in included_rows:
        if normalize_cell(row.get("selected_for_final_n")) != "yes":
            continue
        record_id = normalize_cell(row.get("record_id"))
        info = attachment_map.get(record_id, {})
        relpath = normalize_cell(info.get("attachment_relpath"))
        source_url = normalize_cell(info.get("source_url")) or normalize_cell(row.get("full_text_path"))
        rows.append(
            [
                note_link(
                    study_note_relpath(record_id),
                    normalize_cell(row.get("title_original")) or record_id,
                ),
                attachment_link(pathlib.Path(relpath), "adjunto") if relpath else "sin adjunto local",
                normalize_cell(info.get("attachment_kind")) or "sin adjunto",
                normalize_cell(info.get("status")) or "sin estado",
                source_url or "sin enlace origen",
            ]
        )
    if not rows:
        return pending_note("Hermes aún no ha cerrado el corpus final seleccionado; la biblioteca de PDFs aparecerá cuando exista un shortlist definitivo.")
    return "\n".join(
        [
            "#research/fulltext #obsidian/graph",
            "",
            "> Biblioteca de PDFs completos de los estudios seleccionados. Si no hay PDF local, se conserva el enlace origen para recuperacion manual o automatizada posterior, pero el estudio no debe tratarse como evidencia final publicable.",
            "",
            markdown_table(
                ["study", "attachment", "kind", "status", "source_url"],
                rows,
            ),
        ]
    )


def build_study_note(row: dict[str, str], attachment_map: dict[str, dict[str, str]]) -> tuple[str, str]:
    record_id = normalize_cell(row.get("record_id"))
    title = normalize_cell(row.get("title_original")) or normalize_cell(row.get("title_en")) or record_id
    source = normalize_cell(row.get("source")) or "desconocido"
    work_type = normalize_cell(row.get("work_type")) or "no reportado"
    empirical_type = normalize_cell(row.get("empirical_type")) or "no reportado"
    themes = classify_themes(row)
    attachment = attachment_map.get(record_id, {})
    attachment_relpath = normalize_cell(attachment.get("attachment_relpath"))
    attachment_status = normalize_cell(attachment.get("status")) or "sin adjunto"
    attachment_source_url = normalize_cell(attachment.get("source_url")) or normalize_cell(row.get("full_text_path"))
    graph_links = [
        note_link(pathlib.Path("19 Included Studies Hub.md"), "Hub de estudios incluidos"),
        note_link(graph_note_relpath("Sources", source), source),
        note_link(graph_note_relpath("Work Types", work_type), work_type),
        note_link(graph_note_relpath("Years", normalize_cell(row.get("year")) or "desconocido"), normalize_cell(row.get("year")) or "desconocido"),
    ]
    if empirical_type != "no reportado":
        graph_links.append(note_link(graph_note_relpath("Empirical Types", empirical_type), empirical_type))
    graph_links.extend(note_link(graph_note_relpath("Themes", theme), theme) for theme in themes)
    lines = [
        "#paper #research/study #obsidian/graph",
        "",
        "## Identificacion",
        f"- Record ID: `{record_id}`",
        f"- DOI: {normalize_cell(row.get('assigned_doi')) or 'sin DOI'}",
        f"- Autores: {normalize_cell(row.get('authors')) or 'no reportado'}",
        f"- Año: {normalize_cell(row.get('year')) or 'no reportado'}",
        f"- Fuente: {source}",
        f"- Tipo de trabajo: {work_type}",
        f"- Tipo empirico: {empirical_type}",
        f"- Seleccionado para N final: {'si' if normalize_cell(row.get('selected_for_final_n')) == 'yes' else 'no'}",
        f"- Confianza de extraccion: {normalize_cell(row.get('extraction_confidence')) or 'no reportado'}",
        "",
        "## Enlaces de grafo",
        "- " + " | ".join(graph_links),
        "",
        "## Hallazgo clave",
        normalize_cell(row.get("key_findings")) or "Pendiente de sintesis interpretativa.",
        "",
        "## Clasificacion del trabajo",
        f"- Tipo de trabajo: {work_type}",
        f"- Tipo empirico: {empirical_type}",
        "",
        "## Texto completo",
        f"- PDF local: {attachment_link(pathlib.Path(attachment_relpath), 'abrir PDF') if attachment_relpath else 'no disponible'}",
        f"- Estado del adjunto: {attachment_status}",
        f"- Enlace origen: {attachment_source_url or 'no reportado'}",
        "",
        "## Resumen",
        normalize_cell(row.get("abstract_es"))
        or normalize_cell(row.get("abstract_en"))
        or normalize_cell(row.get("abstract_original"))
        or "No hay abstract suficientemente capturado todavia.",
        "",
        "## Diseno empirico",
        f"- País o países: {normalize_cell(row.get('countries')) or 'no reportado'}",
        f"- Muestra: {normalize_cell(row.get('sample_description')) or 'no reportado'}",
        f"- Tamaño de la muestra: {normalize_cell(row.get('sample_size')) or 'no reportado'}",
        f"- Método usado: {normalize_cell(row.get('method_used')) or 'no reportado'}",
        "",
        "## Variables empleadas",
        f"- Variable dependiente: {normalize_cell(row.get('variables_dependent')) or 'no reportado'}",
        f"- Variables independientes: {normalize_cell(row.get('variables_independent')) or 'no reportado'}",
        f"- Variables moderadoras: {normalize_cell(row.get('variables_moderating')) or 'no reportado'}",
        f"- Variables mediadoras: {normalize_cell(row.get('variables_mediating')) or 'no reportado'}",
        f"- Variables de control: {normalize_cell(row.get('variables_control')) or 'no reportado'}",
        "",
        "## Marco teorico",
        normalize_cell(row.get("theory_framework")) or "no reportado",
        "",
        "## Evidencia capturada",
        f"- Fragmento: {normalize_cell(row.get('evidence_snippet')) or 'no reportado'}",
        f"- Localizacion: {normalize_cell(row.get('evidence_location')) or 'no reportado'}",
        f"- Metodo: {normalize_cell(row.get('method_used')) or 'no reportado'}",
        f"- Muestra: {normalize_cell(row.get('sample_description')) or 'no reportado'}",
        f"- Tamano muestral: {normalize_cell(row.get('sample_size')) or 'no reportado'}",
        f"- Pais o contexto: {normalize_cell(row.get('countries')) or 'no reportado'}",
        "",
        "## Notas",
        normalize_cell(row.get("notes")) or "Sin notas adicionales.",
    ]
    return title, "\n".join(lines)


def build_graph_node(
    kind: str,
    label: str,
    rows: list[dict[str, str]],
) -> tuple[str, str]:
    title = label
    lines = [
        "#obsidian/graph #research/node",
        "",
        f"- Tipo de nodo: {kind}",
        f"- Estudios conectados: {len(rows)}",
        "",
        "## Estudios conectados",
    ]
    for row in sorted(
        rows,
        key=lambda item: (
            normalize_cell(item.get("selected_for_final_n")) != "yes",
            parse_int(item.get("ultraquality_rank"), 9999),
            normalize_cell(item.get("title_original")),
        ),
    ):
        lines.append(
            f"- {note_link(study_note_relpath(normalize_cell(row.get('record_id'))), normalize_cell(row.get('title_original')) or normalize_cell(row.get('record_id')))}"
        )
    return title, "\n".join(lines)


def build_graph_guide(included_rows: list[dict[str, str]]) -> str:
    if not included_rows:
        return "\n".join(
            [
                "#obsidian/graph #research/navigation",
                "",
                "## Estado actual",
                "- El grafo analítico aún no se ha generado porque Hermes no ha cerrado un corpus final incluido.",
                "- Mientras tanto, usa [[00 Overview|Overview]], [[08 PRISMA Flow|Estado PRISMA]] y [[10 Runtime State|Estado de ejecución]] para seguir la revisión.",
            ]
        )
    theme_counter = Counter()
    for row in included_rows:
        for theme in classify_themes(row):
            theme_counter[theme] += 1
    lines = [
        "#obsidian/graph #research/navigation",
        "",
        "## Como leer este vault en Obsidian",
        "- Empieza por [[00 Overview|Overview]] y [[15 Executive Summary|Resumen ejecutivo]].",
        "- Usa [[19 Included Studies Hub|Hub de estudios incluidos]] para saltar a fichas por paper.",
        "- Si vas a trabajar con estudios empíricos, abre [[21 Empirical Evidence Matrix|Matriz empirica]] como vista de trabajo.",
        "- Si necesitas abrir los documentos base, revisa [[23 Selected Full Text Library|Biblioteca de PDFs completos seleccionados]].",
        "- Si empiezas a redactar el paper, usa [[24 Publication Package|Paquete de publicacion]] y [[25 APA Reference Workflow|Flujo APA]].",
        "- Si vas a trabajar con figuras o tablas, usa [[26 Figure Intelligence Workflow|Flujo de figuras y vision]] y [[27 Visual Evidence Library|Biblioteca de evidencia visual]].",
        "- Para planificar resultados visuales del manuscrito, abre [[28 Paper Figures Plan|Plan de figuras del paper]] y [[29 Paper Tables Plan|Plan de tablas del paper]].",
        "- Abre el grafo local desde esta nota o desde una ficha de estudio para ver conexiones entre estudios, temas, fuentes y tipos de trabajo.",
        "",
        "## Nodos principales generados",
        "- [[Graph/Years/2026|2026]]",
        "- [[Graph/Sources/openalex|openalex]]",
        "- [[Graph/Sources/crossref|crossref]]",
        "- [[Graph/Work Types/empirical|empirical]]",
    ]
    for theme, _count in theme_counter.most_common(6):
        lines.append(f"- {note_link(graph_note_relpath('Themes', theme), theme)}")
    lines.extend(
        [
            "",
            "## Consejo practico",
            "- Si quieres un grafo legible, filtra por este folder y activa el grafo local alrededor de un estudio o de una nota de sintesis.",
            "- Las notas `Graph/` estan pensadas para conectar conceptos; `_artifacts/` conserva la trazabilidad pero mete mucho ruido visual.",
        ]
    )
    return "\n".join(lines)


def write_graph_notes(dest: pathlib.Path, included_rows: list[dict[str, str]]) -> None:
    graph_root = dest / "Graph"
    if not included_rows:
        if graph_root.exists():
            shutil.rmtree(graph_root)
        return
    nodes: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in included_rows:
        source = normalize_cell(row.get("source")) or "desconocido"
        work_type = normalize_cell(row.get("work_type")) or "no reportado"
        year = normalize_cell(row.get("year")) or "desconocido"
        empirical_type = normalize_cell(row.get("empirical_type")) or "no reportado"
        nodes[("Sources", source)].append(row)
        nodes[("Work Types", work_type)].append(row)
        nodes[("Years", year)].append(row)
        if empirical_type != "no reportado":
            nodes[("Empirical Types", empirical_type)].append(row)
        for theme in classify_themes(row):
            nodes[("Themes", theme)].append(row)
    for (kind, label), rows in nodes.items():
        title, body = build_graph_node(kind, label, rows)
        write_note(dest / graph_note_relpath(kind, label), title, body)


def write_study_notes(
    dest: pathlib.Path,
    included_rows: list[dict[str, str]],
    attachment_map: dict[str, dict[str, str]],
) -> None:
    studies_root = dest / "Studies"
    if not included_rows:
        if studies_root.exists():
            shutil.rmtree(studies_root)
        return
    for row in included_rows:
        record_id = normalize_cell(row.get("record_id"))
        if not record_id:
            continue
        title, body = build_study_note(row, attachment_map)
        write_note(dest / study_note_relpath(record_id), title, body)


def resolve_vault_path(raw_value: str) -> pathlib.Path:
    candidate = pathlib.Path(raw_value).expanduser() if raw_value else pathlib.Path()
    if raw_value and candidate.exists():
        return candidate
    compose_path = REPO_ROOT / "docker-compose.yml"
    if compose_path.exists():
        pattern = re.compile(r'^\s*-\s*"?(.*?)\s*:/vaults/obsidian"?\s*$')
        for line in compose_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.match(line)
            if not match:
                continue
            host_path = pathlib.Path(match.group(1)).expanduser()
            if host_path.exists():
                return host_path
    return candidate


def parse_runtime_value(path: pathlib.Path, label: str) -> str:
    text = read_text(path)
    match = re.search(rf"^- {re.escape(label)}:\s*`?(.*?)`?$", text, flags=re.MULTILINE)
    return (match.group(1) if match else "").strip()


def review_sort_key(review_dir: pathlib.Path) -> tuple[float, str]:
    intake = review_dir / "protocol" / "intake.md"
    state = review_dir / "notes" / "runtime-state.md"
    target = intake if intake.exists() else state if state.exists() else review_dir
    return (target.stat().st_mtime, review_dir.name)


def review_registry_rows() -> list[dict[str, str]]:
    workspace_root = REPO_ROOT / "workspace"
    rows: list[dict[str, str]] = []
    review_dirs = [
        path
        for path in workspace_root.glob("systematic-review*")
        if path.is_dir() and path.name != "systematic-review-template"
    ]
    for index, review_dir in enumerate(sorted(review_dirs, key=review_sort_key), start=1):
        intake_path = review_dir / "protocol" / "intake.md"
        state_path = review_dir / "notes" / "runtime-state.md"
        topic = ""
        years = ""
        if intake_path.exists():
            intake_text = read_text(intake_path)
            topic_match = re.search(r"^- Tema:\s*(.*)$", intake_text, flags=re.MULTILINE)
            years_match = re.search(r"^- Año o años:\s*(.*)$", intake_text, flags=re.MULTILINE)
            topic = (topic_match.group(1) if topic_match else "").strip()
            years = (years_match.group(1) if years_match else "").strip()
        created_source = intake_path if intake_path.exists() else state_path if state_path.exists() else review_dir
        created_at = datetime.fromtimestamp(created_source.stat().st_mtime).astimezone().isoformat()
        rows.append(
            {
                "order": f"{index:02d}",
                "review_dir": review_dir.name,
                "topic_slug": detect_topic_slug(review_dir),
                "topic": topic or review_dir.name,
                "years": years or "no reportado",
                "status": parse_runtime_value(state_path, "Estado") if state_path.exists() else "unknown",
                "phase": parse_runtime_value(state_path, "Fase actual") if state_path.exists() else "unknown",
                "created_at": created_at,
                "updated_at": parse_runtime_value(state_path, "Runtime actualizado en") if state_path.exists() else "",
            }
        )
    return rows


def write_review_registry(vault_path: pathlib.Path) -> None:
    rows = review_registry_rows()
    registry_md = pathlib.Path("/tmp/systematic-review-registry.md")
    registry_csv = pathlib.Path("/tmp/systematic-review-registry.csv")
    headers = ["order", "review_dir", "topic", "years", "status", "phase", "created_at", "updated_at"]
    with registry_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
    registry_md.write_text(
        "\n".join(
            [
                "# Review Registry",
                "",
                "Listado maestro numerado de revisiones PRISMA generadas por Hermes, con fecha base y estado operativo más reciente.",
                "",
                markdown_table(
                    ["Orden", "Carpeta", "Tema", "Año/s", "Estado", "Fase", "Creada", "Actualizada"],
                    [[row.get(header, "") for header in headers] for row in rows],
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    root = vault_path / "Hermes" / "Systematic Reviews"
    ensure_dir(root)
    note_lines = [
        "# Review Registry",
        "",
        "Este índice maestro numera las revisiones ya hechas para saber cuáles hemos ido haciendo, en qué fecha y en qué estado están.",
        "",
    ]
    for row in rows:
        slug = row.get("topic_slug", "")
        note_lines.extend(
            [
                f"## {row['order']} - {row['topic']}",
                "",
                f"- Carpeta: `{row['review_dir']}`",
                f"- Año o años: `{row['years']}`",
                f"- Estado: `{row['status']}`",
                f"- Fase actual: `{row['phase']}`",
                f"- Fecha base: `{row['created_at']}`",
                f"- Última actualización: `{row['updated_at']}`",
                f"- Overview: [{slug or row['review_dir']}](./{slug}/00%20Overview.md)",
                "",
            ]
        )
    write_note(root / "00 Review Registry.md", "Review Registry", "\n".join(note_lines).strip() + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument("--vault", help="Obsidian vault path; defaults to OBSIDIAN_VAULT_PATH")
    parser.add_argument("--topic-slug", help="Override topic slug")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    raw_vault = args.vault or os.environ.get("OBSIDIAN_VAULT_PATH", "")
    vault_path = resolve_vault_path(raw_vault)
    if not raw_vault and not vault_path:
        raise SystemExit("OBSIDIAN_VAULT_PATH is not set")
    if not review_dir.exists():
        raise SystemExit(f"Review directory does not exist: {review_dir}")

    topic_slug = args.topic_slug or detect_topic_slug(review_dir)
    dest = vault_path / "Hermes" / "Systematic Reviews" / topic_slug
    ensure_dir(dest)
    write_review_registry(vault_path)
    for obsolete_name in [
        "32 Compiled Manuscript.md",
    ]:
        remove_note(dest / obsolete_name)

    flow_counts = read_flow_counts(review_dir / "prisma" / "flow-counts.csv")
    included_count = parse_int(flow_counts.get("included_in_review"))
    master_rows = read_csv_rows(review_dir / "records" / "master-records.csv")
    ta_path = review_dir / "screening" / "title-abstract.csv"
    ft_path = review_dir / "screening" / "full-text.csv"
    extraction_path = review_dir / "extraction" / "extraction-table.csv"
    selection_path = review_dir / "selection" / "ultraquality-shortlist.csv"
    full_text_rows = read_csv_rows(review_dir / "screening" / "full-text.csv")
    extraction_rows = read_csv_rows(review_dir / "extraction" / "extraction-table.csv")
    selection_rows = read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")
    raw_included_rows, _all_rows = build_combined_rows(master_rows, full_text_rows, extraction_rows, selection_rows)
    included_rows = raw_included_rows if included_count > 0 else []
    attachment_map = ensure_selected_fulltext_attachments(review_dir, dest, included_rows)
    has_ta = csv_has_rows(ta_path)
    has_ft = csv_has_rows(ft_path)
    has_extraction = csv_has_rows(extraction_path)
    has_selection = csv_has_rows(selection_path)
    screening_detail_ready = has_selection
    manuscript_source = read_text(review_dir / "paper" / "manuscript" / "publication-ready.md") or read_text(review_dir / "paper" / "manuscript" / "compiled-submission.md")
    references_source = read_text(review_dir / "paper" / "references" / "references.generated.md")
    publication_audit_source = read_text(review_dir / "paper" / "audit" / "publication-audit.md")
    peer_overview_source = read_text(review_dir / "paper" / "review" / "peer-review-overview.md")
    reviewer_a_source = reviewer_note_source_by_role(review_dir, "Revisor A")
    reviewer_b_source = reviewer_note_source_by_role(review_dir, "Revisor B")
    gate_source = read_text(review_dir / "paper" / "audit" / "publication-gate.md")
    review_packet_source = read_text(review_dir / "paper" / "review" / "review-packet" / "review-packet.md")
    integrity_source = read_text(review_dir / "paper" / "audit" / "integrity-audit" / "integrity-audit.md")
    roadmap_source = read_text(review_dir / "paper" / "review" / "revision-roadmap" / "revision-roadmap.md")
    references_ready = publication_references_ready(references_source)
    manuscript_ready = publication_manuscript_ready(manuscript_source, references_ready)
    audit_ready = publication_audit_ready(publication_audit_source, manuscript_ready)
    prisma_flow_note = build_prisma_flow_note(review_dir, flow_counts)
    figures_note = build_figures_note(review_dir)
    visual_evidence_note = build_visual_evidence_library(review_dir)
    has_visual_evidence = bool(
        read_manifest_rows(review_dir / "figures" / "evidence-manifest.csv")
        or read_manifest_rows(review_dir / "figures" / "page-render-manifest.csv")
        or read_manifest_rows(review_dir / "tables" / "evidence-manifest.csv")
    )

    write_note(dest / "00 Overview.md", "Overview", build_overview(review_dir, topic_slug, flow_counts, included_rows))
    write_note(dest / "01 Intake.md", "Intake", read_text(review_dir / "protocol" / "intake.md") or "_No data yet._")
    write_note(dest / "01 Review Mode.md", "Review Mode", read_text(review_dir / "protocol" / "review-mode.md") or "_No data yet._")
    write_note(
        dest / "02 Protocol.md",
        "Protocol",
        "\n\n".join(
            part
            for part in [
                read_text(review_dir / "protocol" / "review-mode.md"),
                read_text(review_dir / "protocol" / "research-question.md"),
                read_text(review_dir / "protocol" / "eligibility-criteria.md"),
                read_text(review_dir / "protocol" / "search-strategy.md"),
            ]
            if part
        )
        or "_No data yet._",
    )
    sync_note(dest / "03 Search Log.md", "Search Log", build_search_log_note(review_dir))
    sync_note(dest / "04 Records.md", "Records", build_records_note(review_dir))
    sync_note(dest / "05 Screening Title Abstract.md", "Screening Title Abstract", build_title_abstract_note(review_dir, flow_counts, has_ta, screening_detail_ready))
    sync_note(dest / "06 Screening Full Text.md", "Screening Full Text", build_full_text_note(review_dir, flow_counts, has_ft, screening_detail_ready))
    sync_note(dest / "07 Extraction.md", "Extraction", csv_to_markdown(extraction_path) if has_extraction else pending_note("Hermes aún no ha completado la extracción estructurada del corpus final."))
    sync_note(dest / "08A Ultraquality Selection.md", "Ultraquality Selection", csv_to_markdown(selection_path) if has_selection else pending_note("Hermes aún no ha calculado el shortlist ultraquality."))
    sync_note(dest / "08 PRISMA Flow.md", "PRISMA Flow", prisma_flow_note)
    write_note(dest / "09 Decisions.md", "Decisions", read_text(review_dir / "notes" / "decisions.md") or "_No data yet._")
    write_note(dest / "10 Runtime State.md", "Runtime State", read_text(review_dir / "notes" / "runtime-state.md") or "_No data yet._")
    write_note(dest / "11 Audit Checklist.md", "Audit Checklist", read_text(review_dir / "audit" / "checklist.md") or "_No data yet._")
    write_note(dest / "12 Phase Audit.md", "Phase Audit", read_text(review_dir / "audit" / "phase-audit.md") or "_No data yet._")
    write_note(dest / "13 Final Audit.md", "Final Audit", read_text(review_dir / "audit" / "final-audit.md") or "_No data yet._")
    sync_note(dest / "14 Figures.md", "Figures", figures_note)
    sync_note(dest / "15 Executive Summary.md", "Executive Summary", build_executive_summary(flow_counts, included_rows) if included_rows else pending_note("Hermes aún no ha generado un corpus incluido suficiente para redactar el resumen ejecutivo."))
    sync_note(dest / "16 Corpus Characterization.md", "Corpus Characterization", build_corpus_characterization(included_rows) if included_rows else pending_note("Hermes aún no ha consolidado estudios incluidos para caracterizar el corpus."))
    sync_note(dest / "17 Thematic Synthesis.md", "Thematic Synthesis", build_thematic_synthesis(included_rows) if included_rows else pending_note("Hermes aún no ha llegado a la síntesis temática basada en estudios incluidos."))
    sync_note(dest / "18 Methodological Synthesis.md", "Methodological Synthesis", build_methodological_synthesis(included_rows) if included_rows else pending_note("Hermes aún no ha llegado a la síntesis metodológica basada en estudios incluidos."))
    sync_note(dest / "19 Included Studies Hub.md", "Included Studies Hub", build_studies_hub(included_rows) if included_rows else pending_note("Hermes aún no ha generado fichas del corpus incluido."))
    write_note(dest / "20 Obsidian Graph Guide.md", "Obsidian Graph Guide", build_graph_guide(included_rows))
    sync_note(dest / "21 Empirical Evidence Matrix.md", "Empirical Evidence Matrix", build_empirical_evidence_matrix(included_rows) if included_rows else pending_note("Hermes aún no ha completado la extracción suficiente para construir la matriz empírica."))
    write_note(dest / "22 Phase Model.md", "Phase Model", build_phase_model())
    sync_note(dest / "23 Selected Full Text Library.md", "Selected Full Text Library", build_selected_fulltext_library(included_rows, attachment_map) if included_rows else pending_note("Hermes aún no ha seleccionado textos completos para la biblioteca final."))
    write_note(dest / "24 Publication Package.md", "Publication Package", build_publication_package())
    write_note(dest / "25 APA Reference Workflow.md", "APA Reference Workflow", build_apa_reference_workflow(included_rows))
    write_note(dest / "26 Figure Intelligence Workflow.md", "Figure Intelligence Workflow", build_figure_intelligence_workflow())
    sync_note(dest / "27 Visual Evidence Library.md", "Visual Evidence Library", visual_evidence_note if has_visual_evidence else pending_note("Hermes aún no ha extraído figuras o tablas fuente desde los papers."))
    sync_note(dest / "28 Paper Figures Plan.md", "Paper Figures Plan", build_paper_figures_plan(review_dir))
    sync_note(dest / "29 Paper Tables Plan.md", "Paper Tables Plan", build_paper_tables_plan(review_dir))
    write_note(dest / "30 Publication Workspace.md", "Publication Workspace", read_text(review_dir / "paper" / "README.md") or "_No data yet._")
    sync_note(dest / "31 Generated References.md", "Generated References", references_source if references_ready else pending_note("Hermes aún no ha resuelto referencias APA suficientes para mostrar una bibliografía final."))
    manuscript_text = manuscript_source
    manuscript_text = adapt_manuscript_paths_for_obsidian(manuscript_text)
    sync_note(dest / "32 Publication Manuscript.md", "Publication Manuscript", manuscript_text if manuscript_ready else pending_note("Hermes aún no ha compilado un manuscrito final con citas y bibliografía suficientes."))
    sync_note(dest / "33 Publication Audit.md", "Publication Audit", publication_audit_source if audit_ready else pending_note("Hermes aún no ha completado una auditoría de publicación útil sobre un manuscrito maduro."))
    sync_note(dest / "34 Peer Review Overview.md", "Peer Review Overview", peer_overview_source if audit_ready and peer_overview_source.strip() else pending_note("La revisión cruzada externa aún no se ha ejecutado sobre un manuscrito publicable."))
    sync_note(dest / "35 Reviewer A.md", "Reviewer A", reviewer_a_source if audit_ready and reviewer_a_source.strip() else pending_note("El dictamen del Revisor A aún no es relevante porque Hermes no ha cerrado el manuscrito final."))
    sync_note(dest / "36 Reviewer B.md", "Reviewer B", reviewer_b_source if audit_ready and reviewer_b_source.strip() else pending_note("El dictamen del Revisor B aún no es relevante porque Hermes no ha cerrado el manuscrito final."))
    sync_note(dest / "37 Publication Gate.md", "Publication Gate", gate_source if audit_ready and gate_source.strip() else pending_note("El gate de publicación aún no es representativo porque Hermes no ha cerrado el manuscrito final."))
    sync_note(dest / "38 Review Packet.md", "Review Packet", review_packet_source if review_packet_source.strip() else pending_note("Hermes aún no ha generado el packet determinista de revisión editorial."))
    sync_note(dest / "39 Integrity Audit.md", "Integrity Audit", integrity_source if integrity_source.strip() else pending_note("Hermes aún no ha ejecutado la auditoría estática de integridad editorial."))
    sync_note(dest / "40 Revision Roadmap.md", "Revision Roadmap", roadmap_source if roadmap_source.strip() else pending_note("Hermes aún no ha convertido la revisión cruzada en una matriz accionable de cambios."))

    write_study_notes(dest, included_rows, attachment_map)
    write_graph_notes(dest, included_rows)

    copied = copy_artifacts(review_dir, dest)
    print(f"obsidian_sync_destination: {dest}")
    print(f"included_study_notes: {len(included_rows)}")
    print(f"files_mirrored: {len(copied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
