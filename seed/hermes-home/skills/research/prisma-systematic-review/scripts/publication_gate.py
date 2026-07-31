#!/usr/bin/env python3
"""Compute a strict publication gate for a review manuscript."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from review_mode_router import MODE_CONFIG

FALLBACK_EXTRACTION_MARKERS = [
    "extraccion de respaldo por respuesta incompleta o error transitorio del modelo",
    "extracción de respaldo por respuesta incompleta o error transitorio del modelo",
]


@dataclass
class Check:
    name: str
    status: str
    detail: str


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {}


def normalize_label(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower().replace("_", "-").strip()
    return re.sub(r"\s+", " ", normalized)


def main_argument_text(manuscript: str) -> str:
    """Return the argumentative manuscript body, excluding appendices and references."""
    return re.split(
        r"(?m)^#\s+(?:Anexo|Corpus final incluido|Declaraciones editoriales|Referencias)\b",
        manuscript or "",
        maxsplit=1,
    )[0]


def remove_method_section(manuscript: str) -> str:
    """Remove the methods section so reporting-standard mentions do not mask argument quality."""
    return re.sub(
        r"(?ms)^#\s+(?:Método|Metodo|Method)\b.*?(?=^#\s+|\Z)",
        "",
        manuscript or "",
    )


def parse_status(audit_text: str) -> str:
    match = re.search(r"Estado global:\s+\*\*(PASS|WARN|FAIL)\*\*", audit_text)
    return match.group(1) if match else "UNKNOWN"


def parse_intake_value(intake_text: str, label: str) -> str:
    pattern = rf"^- {re.escape(label)}:\s*(.*)$"
    match = re.search(pattern, intake_text, flags=re.MULTILINE)
    return (match.group(1) if match else "").strip()


def infer_word_target(raw: str) -> int:
    text = (raw or "").strip().lower()
    explicit = re.search(r"(\d{3,5})", text)
    if explicit:
        return int(explicit.group(1))
    if "corta" in text or "short" in text:
        return 3000
    if "media" in text:
        return 4500
    if "larga" in text or "extensa" in text or "journal" in text:
        return 6000
    return 5000


def parse_int(raw: str, default: int = 0) -> int:
    text = (raw or "").strip()
    try:
        return int(text)
    except ValueError:
        return default


def resolve_review_path(review_dir: pathlib.Path, raw_path: str) -> pathlib.Path | None:
    """Resolve paths written inside Docker back to the local review directory."""
    raw = (raw_path or "").strip()
    if not raw:
        return None
    path = pathlib.Path(raw)
    if not path.is_absolute():
        return review_dir / path
    if path.exists():
        return path
    parts = path.parts
    if review_dir.name in parts:
        review_index = parts.index(review_dir.name)
        return review_dir.joinpath(*parts[review_index + 1 :])
    return path


def file_mtime(path: pathlib.Path | None) -> float:
    """Return a file timestamp without making freshness checks crash on missing files."""
    if path is None:
        return 0.0
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def has_public_doi(row: dict[str, str]) -> bool:
    return bool(((row.get("assigned_doi") or row.get("doi") or "").strip()))


def has_fallback_marker(text: str) -> bool:
    blob = normalize_label(text)
    return any(marker in blob for marker in FALLBACK_EXTRACTION_MARKERS)


def build_gate(review_dir: pathlib.Path) -> tuple[str, list[Check], dict[str, int | str]]:
    publication_audit = read_text(review_dir / "paper" / "audit" / "publication-audit.md")
    publication_status = parse_status(publication_audit)
    publication_issues = read_csv_rows(review_dir / "paper" / "audit" / "publication-issues.csv")
    integrity_payload = read_json(review_dir / "paper" / "audit" / "integrity-audit" / "integrity-audit.json")

    review_manifest = read_csv_rows(review_dir / "paper" / "review" / "review-manifest.csv")
    revision_roadmap_rows = read_csv_rows(review_dir / "paper" / "review" / "revision-roadmap" / "revision-roadmap.csv")
    figures = read_csv_rows(review_dir / "figures" / "manifest.csv")
    figure_evidence = read_csv_rows(review_dir / "figures" / "evidence-manifest.csv")
    page_render_evidence = read_csv_rows(review_dir / "figures" / "page-render-manifest.csv")
    table_evidence = read_csv_rows(review_dir / "tables" / "evidence-manifest.csv")
    full_text_rows = read_csv_rows(review_dir / "screening" / "full-text.csv")
    full_text_manifest_rows = read_csv_rows(review_dir / "fulltext" / "manifest.csv")
    extraction_rows = read_csv_rows(review_dir / "extraction" / "extraction-table.csv")
    shortlist_rows = read_csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")
    intake = read_text(review_dir / "protocol" / "intake.md")
    manuscript = read_text(review_dir / "paper" / "manuscript" / "publication-ready.md")
    manuscript_md = review_dir / "paper" / "manuscript" / "publication-ready.md"
    references_md = review_dir / "paper" / "references" / "references.generated.md"
    manuscript_tex = review_dir / "paper" / "manuscript" / "publication-ready.tex"
    manuscript_pdf = review_dir / "paper" / "manuscript" / "publication-ready.pdf"
    publication_bundle = review_dir / "paper" / "package" / "publication-package.zip"
    latex_bundle = review_dir / "paper" / "package" / "publication-latex-editable.zip"
    review_mode_md = review_dir / "protocol" / "review-mode.md"
    review_mode_json = review_dir / "protocol" / "review-mode.json"
    review_mode_payload = read_json(review_mode_json)

    checks: list[Check] = []

    non_material_warnings = {"doi_metadata"}
    audit_issue_categories = {
        (row.get("category") or "").strip()
        for row in publication_issues
        if (row.get("severity") or "").strip().upper() in {"WARN", "FAIL"}
    }
    audit_status_ok = publication_status == "PASS" or (
        publication_status == "WARN" and audit_issue_categories and audit_issue_categories.issubset(non_material_warnings)
    )
    checks.append(
        Check(
            "auditoria_determinista",
            "PASS" if audit_status_ok else "FAIL",
            f"Estado de publication-audit: {publication_status}.",
        )
    )
    checks.append(
        Check(
            "modo_metodologico",
            "PASS" if review_mode_md.exists() and review_mode_json.exists() and review_mode_md.stat().st_size > 0 and review_mode_json.stat().st_size > 0 else "FAIL",
            "Existe modo metodológico persistido antes del cierre editorial."
            if review_mode_md.exists() and review_mode_json.exists()
            else "Faltan protocol/review-mode.md o protocol/review-mode.json; la revisión no puede cerrarse sin lógica disciplinar declarada.",
        )
    )
    mode_playbook_keys = [
        "mode_question_es",
        "ask_policy",
        "minimum_tables",
        "minimum_figures",
        "mode_specific_outputs",
        "publication_section_requirements",
        "red_flags",
        "excellence_checklist",
    ]
    mode_key = str(review_mode_payload.get("mode") or "").strip()
    missing_playbook = [
        key
        for key in mode_playbook_keys
        if not review_mode_payload.get(key)
    ]
    checks.append(
        Check(
            "modo_playbook_publicable",
            "PASS" if mode_key in MODE_CONFIG and not missing_playbook else "FAIL",
            f"El modo `{mode_key}` incluye pregunta/inferencia, tablas, figuras, salidas, red flags y checklist editorial."
            if mode_key in MODE_CONFIG and not missing_playbook
            else (
                f"El modo metodológico no tiene contrato editorial completo; faltan: {', '.join(missing_playbook) or 'modo válido'}."
            ),
        )
    )
    integrity_summary = integrity_payload.get("summary", {}) if isinstance(integrity_payload, dict) else {}
    integrity_issue_counts = integrity_summary.get("issue_counts", {}) if isinstance(integrity_summary, dict) else {}
    integrity_errors = parse_int(str(integrity_issue_counts.get("error", 0)), 0)
    integrity_warnings = parse_int(str(integrity_issue_counts.get("warn", 0)), 0)
    if not integrity_payload:
        checks.append(Check("integrity_audit", "FAIL", "Falta la auditoría de integridad previa al gate editorial."))
    elif integrity_errors:
        checks.append(
            Check(
                "integrity_audit",
                "FAIL",
                f"La auditoría de integridad detecta {integrity_errors} error(es) y {integrity_warnings} warning(s).",
            )
        )
    elif integrity_warnings:
        checks.append(
            Check(
                "integrity_audit",
                "WARN",
                f"La auditoría de integridad no detecta errores, pero mantiene {integrity_warnings} warning(s).",
            )
        )
    else:
        checks.append(Check("integrity_audit", "PASS", "La auditoría de integridad está presente y no detecta errores ni warnings."))

    reviewer_verdicts = [row.get("verdict", "").strip().lower() for row in review_manifest]
    reviewer_statuses = [row.get("status", "").strip().lower() for row in review_manifest]
    completed_models = {
        (row.get("model", "") or "").strip().lower()
        for row in review_manifest
        if (row.get("status", "") or "").strip().lower() in {"completed", "success", "ok"}
        and (row.get("model", "") or "").strip()
    }
    review_output_paths = [
        resolve_review_path(review_dir, row.get("output_path", ""))
        for row in review_manifest
        if (row.get("status", "") or "").strip().lower() in {"completed", "success", "ok"}
    ]
    missing_review_outputs = sum(1 for path in review_output_paths if not path or not path.exists())
    freshness_sources = [
        manuscript_md,
        references_md,
        review_dir / "paper" / "audit" / "publication-audit.md",
    ]
    latest_source_mtime = max((file_mtime(path) for path in freshness_sources), default=0.0)
    oldest_review_mtime = min((file_mtime(path) for path in review_output_paths if path and path.exists()), default=0.0)
    review_manifest_mtime = file_mtime(review_dir / "paper" / "review" / "review-manifest.csv")
    reviews_are_stale = bool(
        latest_source_mtime
        and oldest_review_mtime
        and review_manifest_mtime
        and (oldest_review_mtime < latest_source_mtime or review_manifest_mtime < latest_source_mtime)
    )
    completed_reviews = sum(1 for status in reviewer_statuses if status in {"completed", "success", "ok"})
    unresolved_reviews = sum(1 for verdict in reviewer_verdicts if verdict in {"", "unresolved", "unknown"})
    errored_reviews = sum(1 for status in reviewer_statuses if status in {"error", "failed", "timeout"})
    if len(review_manifest) < 2:
        checks.append(Check("revision_cruzada", "FAIL", "Faltan dos revisiones independientes completas."))
    elif completed_reviews < 2:
        checks.append(
            Check(
                "revision_cruzada",
                "FAIL",
                f"La revisión cruzada no es resolutiva todavía: {completed_reviews}/2 revisiones completadas, {errored_reviews} con error y {unresolved_reviews} con veredicto no resuelto.",
            )
        )
    elif unresolved_reviews > 0:
        checks.append(
            Check(
                "revision_cruzada",
                "FAIL",
                f"La revisión cruzada sigue abierta: {unresolved_reviews} veredicto(s) sin resolver.",
            )
        )
    elif missing_review_outputs:
        checks.append(
            Check(
                "revision_cruzada",
                "FAIL",
                f"La revisión cruzada declara resultados, pero faltan {missing_review_outputs} archivo(s) de dictamen.",
            )
        )
    elif reviews_are_stale:
        checks.append(
            Check(
                "revision_cruzada",
                "FAIL",
                "La revisión cruzada es anterior al manuscrito, referencias o auditoría actuales; debe regenerarse antes del PASS editorial.",
            )
        )
    elif len(completed_models) < 2:
        model_list = ", ".join(sorted(completed_models)) or "sin modelo registrado"
        checks.append(
            Check(
                "revision_cruzada",
                "FAIL",
                f"La revisión cruzada no es suficientemente independiente: solo hay {len(completed_models)} modelo(s) efectivo(s) entre las revisiones completadas ({model_list}).",
            )
        )
    elif any(verdict in {"reject", "major revision"} for verdict in reviewer_verdicts):
        checks.append(
            Check(
                "revision_cruzada",
                "FAIL",
                "Al menos un revisor independiente considera que el manuscrito no es publicable todavía.",
            )
        )
    else:
        checks.append(Check("revision_cruzada", "PASS", "Las revisiones independientes están completas y no bloquean la publicación."))
    roadmap_path = review_dir / "paper" / "review" / "revision-roadmap" / "revision-roadmap.csv"
    checks.append(
        Check(
            "revision_roadmap",
            "PASS" if roadmap_path.exists() else "FAIL",
            f"Matriz de revisión generada con {len(revision_roadmap_rows)} item(s) accionables."
            if roadmap_path.exists()
            else "Falta la matriz de revisión accionable derivada de la peer review.",
        )
    )

    rendered_figures: list[dict[str, str]] = []
    for row in figures:
        status = normalize_label(row.get("status", ""))
        png_rel = (row.get("png_path") or "").strip()
        svg_rel = (row.get("svg_path") or "").strip()
        png_path = pathlib.Path(png_rel) if png_rel else None
        svg_path = pathlib.Path(svg_rel) if svg_rel else None
        if png_path is not None and not png_path.is_absolute():
            png_path = review_dir / png_path
        if svg_path is not None and not svg_path.is_absolute():
            svg_path = review_dir / svg_path
        has_rendered_files = bool(png_path and svg_path and png_path.exists() and svg_path.exists())
        if status == "rendered" or has_rendered_files:
            rendered_figures.append(row)
    available_svg_figures = 0
    conceptual_svg_figures = 0
    for row in rendered_figures:
        svg_rel = (row.get("svg_path") or "").strip()
        if not svg_rel:
            continue
        svg_path = pathlib.Path(svg_rel)
        if not svg_path.is_absolute():
            svg_path = review_dir / svg_path
        if not svg_path.exists():
            continue
        available_svg_figures += 1
        if normalize_label(row.get("figure_type", "")) in {
            "review-architecture",
            "concept-map",
            "workflow",
            "workflow-diagram",
            "flow-diagram",
            "flow diagram",
            "architecture",
        }:
            conceptual_svg_figures += 1
    has_selection_visual = any(
        normalize_label(row.get("figure_type", "")) in {"selection-flow", "flow-diagram", "flow diagram"}
        and (
            "seleccion" in normalize_label(row.get("title", ""))
            or "selection" in normalize_label(row.get("figure_id", ""))
            or "prisma-flow" in normalize_label(row.get("figure_id", ""))
            or "identificacion" in normalize_label(row.get("apa_caption", ""))
        )
        for row in rendered_figures
    )
    has_selection_table = bool(
        re.search(r"Tabla\s+1\.\s+Flujo\s+de\s+selecci[oó]n\s+de\s+estudios", manuscript, flags=re.IGNORECASE)
        or (
            "Registros identificados" in manuscript
            and "Estudios de síntesis focal" in manuscript
            and "Texto completo evaluado" in manuscript
        )
    )
    has_method_arch = any(
        normalize_label(row.get("paper_section", "")) in {"metodo", "method"}
        and normalize_label(row.get("figure_type", "")) in {"architecture", "review-architecture", "workflow", "workflow-diagram", "flow-diagram", "flow diagram"}
        for row in rendered_figures
    )
    has_results_visual = any(
        normalize_label(row.get("paper_section", "")) in {"resultados", "results", "discusion", "discussion"}
        for row in rendered_figures
    )
    manuscript_table_mentions = len(re.findall(r"\bTabla\s+\d+\b", manuscript, flags=re.IGNORECASE))
    non_method_argument = remove_method_section(main_argument_text(manuscript))
    prisma_mentions_outside_method = len(re.findall(r"\bPRISMA(?:-S)?\b", non_method_argument, flags=re.IGNORECASE))

    checks.append(
        Check(
            "selection_flow",
            "PASS" if has_selection_table or has_selection_visual else "FAIL",
            "Existe flujo de selección reportado como tabla metodológica."
            if has_selection_table
            else (
                "Existe diagrama de selección de estudios renderizado."
                if has_selection_visual
                else "Falta reportar el flujo de selección como tabla metodológica o diagrama."
            ),
        )
    )
    checks.append(Check("figura_metodo", "PASS" if has_method_arch else "FAIL", "Existe figura metodológica/arquitectónica." if has_method_arch else "Falta una figura de método o arquitectura."))
    checks.append(Check("visual_resultados", "PASS" if has_results_visual else "FAIL", "Existe al menos una figura de resultados/discusión." if has_results_visual else "Falta al menos una figura de resultados o discusión."))
    checks.append(Check("tablas_paper", "PASS" if manuscript_table_mentions >= 1 else "FAIL", f"El manuscrito menciona {manuscript_table_mentions} tablas." if manuscript_table_mentions >= 1 else "No hay tablas integradas en el manuscrito final."))
    checks.append(
        Check(
            "tesis_sustantiva_no_prisma",
            "PASS" if prisma_mentions_outside_method == 0 else "FAIL",
            "El cuerpo argumental no usa PRISMA fuera del método; la tesis se sostiene por síntesis y evidencia."
            if prisma_mentions_outside_method == 0
            else f"Se detectan {prisma_mentions_outside_method} mención(es) a PRISMA fuera de método/anexos/referencias; moverlas o reescribirlas como tesis sustantiva.",
        )
    )
    normalized_manuscript = normalize_label(manuscript)
    has_authorial_position = "posicionamiento interpretativo del articulo" in normalized_manuscript
    has_stance_matrix = "matriz de toma de posicion interpretativa" in normalized_manuscript
    has_yes_no_claims = "afirmacion que si sostiene" in normalized_manuscript and "afirmacion que no sostiene" in normalized_manuscript
    has_decision_opening = "decision cientifica" in normalized_manuscript and (
        "senal contextual" in normalized_manuscript
        or "solo senales" in normalized_manuscript
        or "afirmaciones son defendibles" in normalized_manuscript
    )
    checks.append(
        Check(
            "toma_posicion_autoral",
            "PASS" if has_authorial_position and has_stance_matrix and has_yes_no_claims and has_decision_opening else "FAIL",
            "El manuscrito declara posición interpretativa, abre Resultados con una decisión científica, diferencia lo que afirma de lo que no afirma y conecta resultados con una matriz de tesis/cautela."
            if has_authorial_position and has_stance_matrix and has_yes_no_claims and has_decision_opening
            else "Falta una toma de posición determinista: añadir posicionamiento interpretativo, apertura de Resultados con decisión científica y matriz de afirmación/no afirmación antes del cierre editorial.",
        )
    )
    review_mode_key = normalize_label(
        str(review_mode_payload.get("primary_review_mode") or review_mode_payload.get("review_mode") or "")
    )
    social_forbidden_fragments = [
        "productividad local y ahorro de tiempo",
        "carga de trabajo y presion operativa",
        "reduccion neta del trabajo humano",
        "desplazamiento del trabajo",
        "capas del trabajo",
    ]
    social_contamination = [
        fragment
        for fragment in social_forbidden_fragments
        if review_mode_key == "social-sciences" and fragment in normalized_manuscript
    ]
    checks.append(
        Check(
            "contaminacion_tematica",
            "FAIL" if social_contamination else "PASS",
            "No se detectan plantillas ajenas al modo metodológico declarado."
            if not social_contamination
            else "La revisión de ciencias sociales contiene vocabulario de otra plantilla: "
            + ", ".join(social_contamination),
        )
    )

    selected_ids = {
        (row.get("record_id") or "").strip()
        for row in shortlist_rows
        if (row.get("selected_for_final_n") or "").strip().lower() == "yes"
    }
    selected_doi_ok = {
        (row.get("record_id") or "").strip()
        for row in shortlist_rows
        if (row.get("selected_for_final_n") or "").strip().lower() == "yes"
        and has_public_doi(row)
    }
    full_text_map = {(row.get("record_id") or "").strip(): row for row in full_text_rows}
    full_text_manifest_map = {(row.get("record_id") or "").strip(): row for row in full_text_manifest_rows}
    extraction_map = {(row.get("record_id") or "").strip(): row for row in extraction_rows}
    selected_pdf_ok = 0
    for record_id in selected_ids:
        row = full_text_map.get(record_id, {})
        manifest_row = full_text_manifest_map.get(record_id, {})
        full_text_path = resolve_review_path(review_dir, row.get("full_text_path") or manifest_row.get("pdf_path") or "")
        if full_text_path and full_text_path.suffix.lower() == ".pdf" and full_text_path.exists():
            selected_pdf_ok += 1
    checks.append(
        Check(
            "pdfs_corpus_final",
            "PASS" if selected_ids and selected_pdf_ok == len(selected_ids) else "FAIL",
            f"PDFs locales válidos para {selected_pdf_ok}/{len(selected_ids)} estudios seleccionados.",
        )
    )
    checks.append(
        Check(
            "doi_corpus_final",
            "PASS" if selected_ids and len(selected_doi_ok) == len(selected_ids) else "FAIL",
            f"DOI normalizado para {len(selected_doi_ok)}/{len(selected_ids)} estudios seleccionados.",
        )
    )

    selected_extraction_rows = [extraction_map.get(record_id, {}) for record_id in sorted(selected_ids)]
    missing_extraction = sum(1 for row in selected_extraction_rows if not row)
    placeholder_rows = sum(
        1
        for row in selected_extraction_rows
        if row and (has_fallback_marker(row.get("key_findings", "")) or has_fallback_marker(row.get("notes", "")))
    )
    low_conf_rows = sum(
        1
        for row in selected_extraction_rows
        if row and parse_int(row.get("extraction_confidence", "0"), 0) < 80
    )
    non_full_text_rows = sum(
        1
        for row in selected_extraction_rows
        if row and normalize_label(row.get("evidence_location", "")) not in {"full text", "texto completo"}
    )
    if not selected_ids:
        checks.append(Check("sintesis_focal_robusta", "FAIL", "No hay estudios seleccionados para el N final."))
    elif missing_extraction:
        checks.append(
            Check(
                "sintesis_focal_robusta",
                "FAIL",
                f"Faltan fichas de extracción para {missing_extraction}/{len(selected_ids)} estudios focales.",
            )
        )
    elif placeholder_rows:
        checks.append(
            Check(
                "sintesis_focal_robusta",
                "FAIL",
                f"Hay {placeholder_rows}/{len(selected_ids)} estudios focales con marcadores de extracción provisional o fallback.",
            )
        )
    elif low_conf_rows:
        checks.append(
            Check(
                "sintesis_focal_robusta",
                "FAIL",
                f"Hay {low_conf_rows}/{len(selected_ids)} estudios focales con confianza de extracción inferior a 80.",
            )
        )
    elif non_full_text_rows:
        checks.append(
            Check(
                "sintesis_focal_robusta",
                "FAIL",
                f"Hay {non_full_text_rows}/{len(selected_ids)} estudios focales cuya evidencia no está anclada a full text.",
            )
        )
    else:
        checks.append(
            Check(
                "sintesis_focal_robusta",
                "PASS",
                f"Las {len(selected_ids)} fichas del subconjunto focal tienen extracción robusta, confianza >= 80 y evidencia en full text.",
            )
        )
    checks.append(
        Check(
            "manuscrito_sin_placeholders",
            "FAIL" if has_fallback_marker(manuscript) else "PASS",
            "El manuscrito final contiene marcadores de fallback de extracción."
            if has_fallback_marker(manuscript)
            else "El manuscrito final no contiene marcadores de fallback de extracción.",
        )
    )

    annex_paths = [
        review_dir / "searches" / "search-log.csv",
        review_dir / "records" / "doi-index.csv",
        review_dir / "screening" / "title-abstract.csv",
        review_dir / "screening" / "full-text.csv",
        review_dir / "extraction" / "extraction-table.csv",
        review_dir / "selection" / "ultraquality-shortlist.csv",
    ]
    annex_ready = sum(1 for path in annex_paths if path.exists() and path.stat().st_size > 0)
    checks.append(
        Check(
            "anexos_csv",
            "PASS" if annex_ready == len(annex_paths) else "FAIL",
            f"Anexos CSV listos: {annex_ready}/{len(annex_paths)}.",
        )
    )
    checks.append(
        Check(
            "package_zip",
            "PASS" if publication_bundle.exists() and publication_bundle.stat().st_size > 0 else "FAIL",
            "Existe un zip editorial con manuscrito, figuras y anexos de trazabilidad."
            if publication_bundle.exists() and publication_bundle.stat().st_size > 0
            else "Falta el zip editorial final con manuscrito, figuras y anexos.",
        )
    )
    checks.append(
        Check(
            "latex_manuscript",
            "PASS" if manuscript_tex.exists() and manuscript_tex.stat().st_size > 0 else "FAIL",
            "Existe el manuscrito LaTeX editable `publication-ready.tex`."
            if manuscript_tex.exists() and manuscript_tex.stat().st_size > 0
            else "Falta el manuscrito LaTeX editable `publication-ready.tex`.",
        )
    )
    checks.append(
        Check(
            "pdf_manuscript",
            "PASS" if manuscript_pdf.exists() and manuscript_pdf.stat().st_size > 0 else "FAIL",
            "Existe el PDF compilado del manuscrito."
            if manuscript_pdf.exists() and manuscript_pdf.stat().st_size > 0
            else "Falta el PDF compilado del manuscrito.",
        )
    )
    checks.append(
        Check(
            "latex_bundle",
            "PASS" if latex_bundle.exists() and latex_bundle.stat().st_size > 0 else "FAIL",
            "Existe el zip LaTeX editable para Overleaf o adaptación editorial."
            if latex_bundle.exists() and latex_bundle.stat().st_size > 0
            else "Falta el zip LaTeX editable para Overleaf o adaptación editorial.",
        )
    )

    source_visual_assets = len(figure_evidence) + len(table_evidence)
    checks.append(
        Check(
            "evidencia_visual_fuente",
            "PASS" if source_visual_assets > 0 else "FAIL",
            f"Activos de auditoría visual/tabular vinculados a los estudios: {source_visual_assets}. Renders diagnósticos de página conservados aparte: {len(page_render_evidence)}. Las figuras fuente solo deben entrar al manuscrito si aportan una relación analítica concreta.",
        )
    )

    target_words = infer_word_target(parse_intake_value(intake, "Longitud objetivo del manuscrito (opcional)"))
    word_count = len(re.findall(r"\b\w+\b", manuscript, flags=re.UNICODE))
    checks.append(
        Check(
            "longitud_manuscrito",
            "PASS" if word_count >= target_words else "FAIL",
            f"Longitud aproximada: {word_count} palabras; objetivo mínimo: {target_words}.",
        )
    )

    rq = parse_intake_value(intake, "Pregunta de investigación (opcional)")
    checks.append(
        Check(
            "pregunta_investigacion",
            "PASS" if rq else "WARN",
            "Hay una pregunta de investigación explícita en el intake." if rq else "No hay pregunta de investigación explícita; se está infiriendo desde el tema.",
        )
    )

    blocking = [check for check in checks if check.status == "FAIL"]
    warning = [check for check in checks if check.status == "WARN"]
    overall = "PASS" if not blocking and not warning else ("WARN" if not blocking else "FAIL")
    metrics = {
        "rendered_figures": len(rendered_figures),
        "svg_figures": available_svg_figures,
        "conceptual_svg_figures": conceptual_svg_figures,
        "source_visual_assets": source_visual_assets,
        "page_render_assets": len(page_render_evidence),
        "table_mentions": manuscript_table_mentions,
        "word_count": word_count,
        "target_words": target_words,
        "peer_reviews": len(review_manifest),
        "integrity_errors": integrity_errors,
        "integrity_warnings": integrity_warnings,
        "revision_roadmap_items": len(revision_roadmap_rows),
        "selected_final": len(selected_ids),
        "selected_pdf_ok": selected_pdf_ok,
        "selected_doi_ok": len(selected_doi_ok),
        "selected_missing_extraction": missing_extraction,
        "selected_placeholder_rows": placeholder_rows,
        "selected_low_conf_rows": low_conf_rows,
        "selected_non_full_text_rows": non_full_text_rows,
        "annex_ready": annex_ready,
        "annex_expected": len(annex_paths),
        "bundle_ready": int(publication_bundle.exists() and publication_bundle.stat().st_size > 0),
        "latex_ready": int(manuscript_tex.exists() and manuscript_tex.stat().st_size > 0),
        "pdf_ready": int(manuscript_pdf.exists() and manuscript_pdf.stat().st_size > 0),
        "latex_bundle_ready": int(latex_bundle.exists() and latex_bundle.stat().st_size > 0),
        "review_mode_ready": int(review_mode_md.exists() and review_mode_json.exists()),
    }
    return overall, checks, metrics


def render_report(review_dir: pathlib.Path, overall: str, checks: list[Check], metrics: dict[str, int | str]) -> pathlib.Path:
    now = datetime.now(timezone.utc).astimezone().isoformat()
    lines = [
        "# Publication Gate",
        "",
        f"- Fecha: {now}",
        f"- Estado global: **{overall}**",
        f"- Figuras renderizadas: {metrics['rendered_figures']}",
        f"- Figuras SVG disponibles: {metrics['svg_figures']}",
        f"- Diagramas/mapas conceptuales SVG: {metrics['conceptual_svg_figures']}",
        f"- Activos visuales/tabulares fuente: {metrics['source_visual_assets']}",
        f"- Renders diagnósticos de página: {metrics['page_render_assets']}",
        f"- Tablas integradas en manuscrito: {metrics['table_mentions']}",
        f"- Palabras aproximadas del manuscrito: {metrics['word_count']}",
        f"- Objetivo mínimo de palabras: {metrics['target_words']}",
        f"- Revisiones cruzadas detectadas: {metrics['peer_reviews']}",
        f"- Errores de integridad: {metrics['integrity_errors']}",
        f"- Warnings de integridad: {metrics['integrity_warnings']}",
        f"- Ítems en revision-roadmap: {metrics['revision_roadmap_items']}",
        f"- Estudios seleccionados para el N final: {metrics['selected_final']}",
        f"- DOIs válidos en el corpus final: {metrics['selected_doi_ok']}",
        f"- PDFs válidos en el corpus final: {metrics['selected_pdf_ok']}",
        f"- Anexos CSV listos: {metrics['annex_ready']}/{metrics['annex_expected']}",
        f"- Modo metodológico persistido: {'sí' if metrics['review_mode_ready'] else 'no'}",
        f"- Zip editorial generado: {'sí' if metrics['bundle_ready'] else 'no'}",
        "",
        "## Chequeos",
    ]
    for check in checks:
        lines.append(f"- `{check.status}` {check.name}: {check.detail}")
    lines.extend(
        [
            "",
            "## Regla editorial",
            "- PASS: apto para declarar publicable desde el propio sistema.",
            "- WARN: no bloquea técnicamente, pero aún requiere mejora editorial o estratégica.",
            "- FAIL: no publicable; el sistema debe seguir iterando o documentar un bloqueo real.",
        ]
    )
    out = review_dir / "paper" / "audit" / "publication-gate.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    overall, checks, metrics = build_gate(review_dir)
    report = render_report(review_dir, overall, checks, metrics)
    print(f"publication_gate: {report}")
    print(f"status: {overall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
