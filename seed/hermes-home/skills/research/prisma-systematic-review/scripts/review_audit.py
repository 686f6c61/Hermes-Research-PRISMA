#!/usr/bin/env python3
"""Audit a systematic review workspace by phase and generate Markdown reports."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
import unicodedata
from dataclasses import dataclass

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_mode_router import (  # noqa: E402
    infer_review_mode,
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


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def read_csv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    return fieldnames, rows


def has_nonempty_text(path: pathlib.Path) -> bool:
    return bool(read_text(path))


def check_file(path: pathlib.Path, label: str) -> CheckResult:
    if not path.exists():
        return CheckResult(label, "FAIL", f"No existe `{path.name}`.")
    if not has_nonempty_text(path):
        return CheckResult(label, "WARN", f"`{path.name}` existe pero está vacío.")
    return CheckResult(label, "PASS", f"`{path.name}` existe y tiene contenido.")


def check_columns(path: pathlib.Path, label: str, required: list[str]) -> CheckResult:
    headers, rows = read_csv(path)
    if not path.exists():
        return CheckResult(label, "FAIL", f"No existe `{path.name}`.")
    missing = [column for column in required if column not in headers]
    if missing:
        return CheckResult(label, "FAIL", f"Faltan columnas: {', '.join(missing)}.")
    if not rows:
        return CheckResult(label, "WARN", f"`{path.name}` no tiene filas de datos todavía.")
    return CheckResult(label, "PASS", f"`{path.name}` contiene {len(rows)} filas y las columnas mínimas.")


def count_missing(rows: list[dict[str, str]], fields: list[str]) -> int:
    count = 0
    for row in rows:
        if any(not (row.get(field) or "").strip() for field in fields):
            count += 1
    return count


def check_intake_fields(path: pathlib.Path) -> CheckResult:
    content = read_text(path)
    required = [
        "- Tema:",
        "- Año o años:",
        "- Criterios de inclusión:",
        "- Criterios de exclusión:",
        "- Autores:",
        "- Modo autónomo:",
        "- Modo metodológico (opcional):",
        "- Límite final N ultraquality:",
        "- Criterio de representatividad ultraquality:",
    ]
    missing = [item for item in required if item not in content]
    if missing:
        return CheckResult("Intake fields", "FAIL", f"Faltan marcadores de intake: {', '.join(missing)}.")
    return CheckResult("Intake fields", "PASS", "El intake contiene todos los campos esperados.")


def parse_intake_value(path: pathlib.Path, key: str) -> str:
    if not path.exists():
        return ""
    prefix = f"- {key}:"
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def parse_intake_value_any(path: pathlib.Path, keys: list[str]) -> str:
    for key in keys:
        value = parse_intake_value(path, key)
        if value:
            return value
    return ""


def ensure_review_mode_artifacts(review_dir: pathlib.Path) -> None:
    """Backfill review-mode artifacts for legacy workspaces before auditing."""
    protocol_dir = review_dir / "protocol"
    review_mode_json = protocol_dir / "review-mode.json"
    if (protocol_dir / "review-mode.md").exists() and review_mode_json.exists():
        try:
            payload = json.loads(review_mode_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict) and all(payload.get(key) for key in REVIEW_MODE_PLAYBOOK_KEYS):
            return
    intake_path = protocol_dir / "intake.md"
    if not intake_path.exists():
        return
    decision = infer_review_mode(
        topic=parse_intake_value(intake_path, "Tema"),
        question=parse_intake_value(intake_path, "Pregunta de investigación (opcional)"),
        inclusion=parse_intake_value(intake_path, "Criterios de inclusión"),
        exclusion=parse_intake_value(intake_path, "Criterios de exclusión"),
        target_outlet=parse_intake_value_any(
            intake_path,
            [
                "Revista o medio objetivo (opcional; si se omite, o si solo indicas una familia temática amplia, Hermes usa `generic-common-core`)",
                "Revista o medio objetivo (opcional; si se omite, Hermes usa `generic-common-core`)",
                "Revista objetivo (opcional)",
            ],
        ),
        explicit_mode=parse_intake_value_any(
            intake_path,
            [
                "Modo metodológico (opcional)",
                "Modo metodologico (opcional)",
                "Modo de revisión (opcional)",
                "Modo de revision (opcional)",
            ],
        ),
    )
    write_review_mode_artifacts(review_dir, decision)


def parse_ultraquality_limit(path: pathlib.Path) -> int | None:
    raw = parse_intake_value(path, "Límite final N ultraquality")
    if not raw or raw.lower() in {"sin límite", "sin limite", "none", "no"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def canonicalize_decision_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = " ".join(ascii_only.lower().split()).replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z_]+", "", ascii_only)


def canonicalize_screening_decision(text: str, stage: str) -> str:
    token = canonicalize_decision_token(text)
    if stage == "title_abstract":
        mapping = {
            "include": "include",
            "included": "include",
            "incluir": "include",
            "incluido": "include",
            "incluida": "include",
            "maybe": "maybe",
            "pending": "maybe",
            "pendiente": "maybe",
            "exclude": "exclude",
            "excluded": "exclude",
            "excluir": "exclude",
            "excluido": "exclude",
            "excluida": "exclude",
        }
    else:
        mapping = {
            "include": "include_ft",
            "included": "include_ft",
            "include_ft": "include_ft",
            "incluir": "include_ft",
            "incluido": "include_ft",
            "incluida": "include_ft",
            "exclude": "exclude",
            "excluded": "exclude",
            "excluir": "exclude",
            "excluido": "exclude",
            "excluida": "exclude",
            "exclude_ft": "exclude",
            "excluded_ft": "exclude",
            "no_full_text": "no_full_text",
            "no_fulltext": "no_full_text",
            "nada_texto": "no_full_text",
            "sin_texto_completo": "no_full_text",
        }
    # Map 'exclude' to 'exclude' so that excluded-at-full-text records
    # are counted in both full_text_assessed and full_text_excluded.
    mapping["exclude"] = "exclude"
    return mapping.get(token, "")


def check_exclusion_quality(path: pathlib.Path, label: str) -> CheckResult:
    headers, rows = read_csv(path)
    if not path.exists():
        return CheckResult(label, "FAIL", f"No existe `{path.name}`.")
    if not rows:
        return CheckResult(label, "WARN", f"`{path.name}` no tiene filas todavía.")
    needed = {"decision", "reason", "reason_detail", "exclusion_score"}
    if not needed.issubset(headers):
        return CheckResult(label, "FAIL", f"`{path.name}` no tiene todas las columnas de exclusión.")
    bad = 0
    for row in rows:
        if (row.get("decision") or "").strip().lower() == "exclude":
            if any(not (row.get(key) or "").strip() for key in ("reason", "reason_detail", "exclusion_score")):
                bad += 1
    if bad:
        return CheckResult(label, "WARN", f"Hay {bad} exclusiones sin justificación completa.")
    return CheckResult(label, "PASS", "Las exclusiones registradas tienen justificación y score.")


def check_master_metadata(path: pathlib.Path) -> CheckResult:
    headers, rows = read_csv(path)
    if not path.exists():
        return CheckResult("Master metadata", "FAIL", f"No existe `{path.name}`.")
    required = [
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
    ]
    missing_headers = [column for column in required if column not in headers]
    if missing_headers:
        return CheckResult("Master metadata", "FAIL", f"Faltan columnas de metadatos: {', '.join(missing_headers)}.")
    if not rows:
        return CheckResult("Master metadata", "WARN", "No hay registros maestros todavía.")
    # Skip records that are already excluded at any stage
    active_rows = [
        row for row in rows
        if not (row.get("status") or "").lower().startswith("excluded")
    ]
    missing_rows = count_missing(active_rows, ["authors", "title_original"])
    if missing_rows:
        return CheckResult("Master metadata", "WARN", f"Hay {missing_rows} filas con metadatos básicos incompletos.")
    return CheckResult("Master metadata", "PASS", "Los metadatos básicos del maestro están presentes.")


def check_extraction(path: pathlib.Path) -> CheckResult:
    headers, rows = read_csv(path)
    if not path.exists():
        return CheckResult("Extraction table", "FAIL", f"No existe `{path.name}`.")
    required = [
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
    ]
    missing_headers = [column for column in required if column not in headers]
    if missing_headers:
        return CheckResult("Extraction table", "FAIL", f"Faltan columnas de extracción: {', '.join(missing_headers)}.")
    if not rows:
        return CheckResult("Extraction table", "WARN", "La tabla de extracción aún no tiene filas.")
    weak_rows = count_missing(rows, ["work_type", "evidence_snippet", "evidence_location", "extraction_confidence"])
    if weak_rows:
        return CheckResult("Extraction table", "WARN", f"Hay {weak_rows} filas con soporte metodológico incompleto.")
    return CheckResult("Extraction table", "PASS", "La tabla de extracción contiene soporte metodológico básico.")


def check_prisma_counts(path: pathlib.Path) -> CheckResult:
    headers, rows = read_csv(path)
    if not path.exists():
        return CheckResult("PRISMA counts", "FAIL", f"No existe `{path.name}`.")
    if headers[:2] != ["stage", "count"]:
        return CheckResult("PRISMA counts", "FAIL", "La tabla PRISMA no empieza con `stage,count`.")
    if not rows:
        return CheckResult("PRISMA counts", "WARN", "La tabla PRISMA aún no tiene filas.")
    non_numeric = []
    for row in rows:
        count_value = (row.get("count") or "").strip()
        if count_value and not count_value.isdigit():
            non_numeric.append(row.get("stage") or "?")
    if non_numeric:
        return CheckResult("PRISMA counts", "WARN", f"Hay conteos no numéricos en: {', '.join(non_numeric)}.")
    review_dir = path.parent.parent
    _ta_headers, ta_rows = read_csv(review_dir / "screening" / "title-abstract.csv")
    _ft_headers, ft_rows = read_csv(review_dir / "screening" / "full-text.csv")
    stage_map = {row.get("stage", ""): int((row.get("count") or "0").strip() or 0) for row in rows if (row.get("count") or "").strip().isdigit()}
    # Count records that actually have a full-text path (i.e. were assessed from PDF).
    assessed_rows = [row for row in ft_rows if (row.get("full_text_path") or "").strip()]
    not_retrieved_rows = [row for row in ft_rows if not (row.get("full_text_path") or "").strip()]

    assessed_decisions = [canonicalize_screening_decision(row.get("decision"), "full_text") for row in assessed_rows]

    expected = {
        "screened_title_abstract": len(ta_rows),
        "excluded_title_abstract": sum(1 for row in ta_rows if canonicalize_screening_decision(row.get("decision"), "title_abstract") == "exclude"),
        "full_text_sought": sum(1 for row in ta_rows if canonicalize_screening_decision(row.get("decision"), "title_abstract") in {"include", "maybe"}),
        "full_text_retrieved": len(assessed_rows),
        "full_text_not_retrieved": len(not_retrieved_rows),
        "full_text_assessed": len(assessed_rows),
        "full_text_excluded": sum(1 for d in assessed_decisions if d == "exclude"),
        "included_in_review": sum(1 for d in assessed_decisions if d == "include_ft"),
    }
    mismatches = [
        f"{stage}: flujo={stage_map.get(stage, 'NA')} esperado={value}"
        for stage, value in expected.items()
        if stage in stage_map and stage_map.get(stage) != value
    ]
    invalid_ft = sorted(
        {
            (row.get("decision") or "").strip()
            for row in ft_rows
            if (row.get("decision") or "").strip()
            and not canonicalize_screening_decision(row.get("decision"), "full_text")
        }
    )
    if mismatches:
        return CheckResult("PRISMA counts", "FAIL", "Descuadre entre `flow-counts.csv` y los CSV de screening: " + "; ".join(mismatches) + ".")
    if invalid_ft:
        return CheckResult("PRISMA counts", "WARN", "Hay decisiones no canónicas en full text: " + ", ".join(invalid_ft) + ".")
    return CheckResult("PRISMA counts", "PASS", "La tabla PRISMA tiene estructura válida y cuadra con las decisiones canonizables del screening.")


def check_figures(figures_dir: pathlib.Path) -> CheckResult:
    manifest_path = figures_dir / "manifest.csv"
    if not manifest_path.exists():
        return CheckResult("Figure manifest", "WARN", "Todavía no existe `figures/manifest.csv`.")
    headers, rows = read_csv(manifest_path)
    required = ["figure_id", "svg_path", "png_path", "status"]
    missing_headers = [column for column in required if column not in headers]
    if missing_headers:
        return CheckResult("Figure manifest", "FAIL", f"Faltan columnas de figuras: {', '.join(missing_headers)}.")
    if not rows:
        return CheckResult("Figure manifest", "WARN", "El inventario de figuras existe pero no tiene filas.")
    missing_assets = 0
    for row in rows:
        svg_rel = (row.get("svg_path") or "").strip()
        png_rel = (row.get("png_path") or "").strip()
        if not svg_rel or not png_rel:
            missing_assets += 1
            continue
        svg_path = figures_dir.parent / svg_rel
        png_path = figures_dir.parent / png_rel
        if not svg_path.exists() or not png_path.exists():
            missing_assets += 1
    if missing_assets:
        return CheckResult("Figure manifest", "WARN", f"Hay {missing_assets} figuras sin SVG o PNG consistente.")
    return CheckResult("Figure manifest", "PASS", "El inventario de figuras y los renders PNG son consistentes.")


def check_ultraquality_selection(path: pathlib.Path, n_limit: int | None) -> CheckResult:
    if n_limit is None:
        return CheckResult("Ultraquality shortlist", "PASS", "No hay límite final `N` configurado.")
    headers, rows = read_csv(path)
    if not path.exists():
        return CheckResult("Ultraquality shortlist", "FAIL", f"Hay límite final `N={n_limit}` pero no existe `{path.name}`.")
    required = [
        "record_id",
        "assigned_doi",
        "decision_before_cap",
        "n_limit",
        "ultraquality_rank",
        "ultraquality_score",
        "representativeness_score",
        "methodological_quality_score",
        "relevance_score",
        "selected_for_final_n",
        "selection_reason",
        "cap_exclusion_reason",
    ]
    missing_headers = [column for column in required if column not in headers]
    if missing_headers:
        return CheckResult("Ultraquality shortlist", "FAIL", f"Faltan columnas de shortlist: {', '.join(missing_headers)}.")
    if not rows:
        return CheckResult("Ultraquality shortlist", "WARN", "El shortlist ultraquality existe pero no tiene filas.")
    selected_rows = [
        row for row in rows
        if (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "sí", "si", "true", "1"}
    ]
    if len(selected_rows) > n_limit:
        return CheckResult("Ultraquality shortlist", "FAIL", f"Hay {len(selected_rows)} estudios seleccionados y el límite es {n_limit}.")
    undocumented = 0
    for row in rows:
        chosen = (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "sí", "si", "true", "1"}
        if chosen and not (row.get("selection_reason") or "").strip():
            undocumented += 1
        if not chosen and not (row.get("cap_exclusion_reason") or "").strip():
            undocumented += 1
    if undocumented:
        return CheckResult("Ultraquality shortlist", "WARN", f"Hay {undocumented} filas sin justificación suficiente de shortlist.")
    return CheckResult("Ultraquality shortlist", "PASS", f"Shortlist ultraquality documentado con {len(selected_rows)} estudios dentro del límite N={n_limit}.")


def check_structural_analysis(analysis_dir: pathlib.Path) -> CheckResult:
    required = [
        analysis_dir / "manifest.json",
        analysis_dir / "methodology.md",
        analysis_dir / "summary.md",
        analysis_dir / "atlas" / "network-atlas.html",
        analysis_dir / "data" / "nodes.csv",
        analysis_dir / "data" / "edges.csv",
        analysis_dir / "data" / "graph.graphml",
        analysis_dir / "metrics" / "network-summary.json",
        analysis_dir / "metrics" / "centrality.csv",
        analysis_dir / "metrics" / "communities.csv",
        analysis_dir / "metrics" / "author-production.csv",
        analysis_dir / "metrics" / "selection-drift.csv",
        analysis_dir / "audit" / "coverage.json",
        analysis_dir / "audit" / "parameters.json",
        analysis_dir / "audit" / "provenance.csv",
    ]
    missing = [str(path.relative_to(analysis_dir)) for path in required if not path.exists()]
    if missing:
        return CheckResult(
            "Structural analysis",
            "FAIL",
            "Faltan artefactos estructurales: " + ", ".join(missing) + ".",
        )
    try:
        manifest = json.loads((analysis_dir / "manifest.json").read_text(encoding="utf-8"))
        coverage = json.loads((analysis_dir / "audit" / "coverage.json").read_text(encoding="utf-8"))
        parameters = json.loads((analysis_dir / "audit" / "parameters.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CheckResult("Structural analysis", "FAIL", "Los JSON estructurales no son legibles.")
    if manifest.get("atlas") != "atlas/network-atlas.html":
        return CheckResult("Structural analysis", "FAIL", "El manifiesto no declara el atlas offline canónico.")
    if parameters.get("study_identity") != "normalized_doi":
        return CheckResult("Structural analysis", "FAIL", "La identidad de estudio no está fijada en DOI normalizado.")
    headers, node_rows = read_csv(analysis_dir / "data" / "nodes.csv")
    required_headers = {"node_id", "node_type", "label", "layers"}
    if not required_headers.issubset(headers):
        return CheckResult("Structural analysis", "FAIL", "La tabla de nodos no tiene su esquema mínimo.")
    invalid_study_ids = [
        row.get("node_id", "")
        for row in node_rows
        if row.get("node_type") == "study" and not row.get("node_id", "").startswith("study:10.")
    ]
    if invalid_study_ids:
        return CheckResult(
            "Structural analysis",
            "FAIL",
            f"Hay {len(invalid_study_ids)} nodos de estudio que no usan DOI como identidad.",
        )
    denominator = int(coverage.get("denominator") or 0)
    if denominator <= 0:
        return CheckResult(
            "Structural analysis",
            "WARN",
            "Los artefactos existen, pero no hay estudios incluidos para interpretar las redes.",
        )
    focal_mismatch = int(coverage.get("focal_outside_included_count") or 0)
    if focal_mismatch:
        return CheckResult(
            "Structural analysis",
            "WARN",
            f"El atlas es válido, pero el shortlist fuente marcaba {focal_mismatch} DOI focales fuera del corpus incluido.",
        )
    return CheckResult(
        "Structural analysis",
        "PASS",
        f"Atlas, métricas y auditoría estructural completos para {denominator} estudios incluidos.",
    )


def phase_status(results: list[CheckResult]) -> str:
    statuses = {result.status for result in results}
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def render_results(title: str, results: list[CheckResult]) -> str:
    lines = [f"# {title}", ""]
    for result in results:
        lines.append(f"- **{result.name}** [{result.status}]: {result.detail}")
    return "\n".join(lines) + "\n"


def render_final(phases: list[tuple[str, str, list[CheckResult]]]) -> str:
    lines = ["# Final Audit", "", "| Fase | Estado | Resumen |", "| --- | --- | --- |"]
    for phase_name, status, results in phases:
        summary = "; ".join(result.detail for result in results[:2]) or "Sin detalles"
        lines.append(f"| {phase_name} | {status} | {summary} |")
    lines.extend(
        [
            "",
            "## Manual Review Checklist",
            "- [ ] Revisar redacción en español de España según RAE",
            "- [ ] Verificar citas y referencias APA en síntesis y notas narrativas",
            "- [ ] Confirmar que cada afirmación interpretativa está anclada a uno o varios papers",
            "- [ ] Confirmar que los cambios de modelo y bloqueos están registrados en `notes/decisions.md`",
            "- [ ] Si hay límite final N, confirmar que el shortlist ultraquality justifica por qué entran esos estudios y por qué otros válidos quedan fuera del subconjunto final",
            "- [ ] Interpretar comunidades y centralidad solo cuando cobertura, tamaño y estabilidad superan los umbrales declarados",
            "- [ ] Confirmar que productividad, citas y topología no influyeron en inclusión, calidad ni selección focal",
        ]
    )
    return "\n".join(lines) + "\n"


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory does not exist: {review_dir}")
    ensure_review_mode_artifacts(review_dir)

    protocol_dir = review_dir / "protocol"
    searches_dir = review_dir / "searches"
    records_dir = review_dir / "records"
    screening_dir = review_dir / "screening"
    extraction_dir = review_dir / "extraction"
    prisma_dir = review_dir / "prisma"
    notes_dir = review_dir / "notes"
    audit_dir = review_dir / "audit"
    figures_dir = review_dir / "figures"
    analysis_dir = review_dir / "analysis"
    selection_dir = review_dir / "selection"
    n_limit = parse_ultraquality_limit(protocol_dir / "intake.md")

    phase_one = [
        check_file(protocol_dir / "intake.md", "Intake file"),
        check_intake_fields(protocol_dir / "intake.md"),
        check_file(protocol_dir / "review-mode.md", "Review mode"),
        check_file(protocol_dir / "review-mode.json", "Review mode JSON"),
        check_file(protocol_dir / "research-question.md", "Research question"),
        check_file(protocol_dir / "eligibility-criteria.md", "Eligibility criteria"),
        check_file(protocol_dir / "search-strategy.md", "Search strategy"),
    ]
    phase_two = [
        check_columns(
            searches_dir / "search-log.csv",
            "Search log",
            ["source", "platform", "query_string", "author_filter", "run_date", "notes", "export_file"],
        ),
        check_master_metadata(records_dir / "master-records.csv"),
        check_file(records_dir / "doi-index.csv", "DOI index"),
        check_file(records_dir / "duplicates.csv", "Duplicates file"),
        check_file(records_dir / "missing-doi.csv", "Missing DOI file"),
    ]
    phase_three = [
        check_columns(
            screening_dir / "title-abstract.csv",
            "Title/abstract screening",
            ["record_id", "assigned_doi", "decision", "exclusion_score", "reason", "reason_detail"],
        ),
        check_exclusion_quality(screening_dir / "title-abstract.csv", "Title/abstract exclusion quality"),
        check_columns(
            screening_dir / "full-text.csv",
            "Full-text screening",
            ["record_id", "assigned_doi", "decision", "exclusion_score", "reason", "reason_detail", "full_text_path"],
        ),
        check_exclusion_quality(screening_dir / "full-text.csv", "Full-text exclusion quality"),
    ]
    phase_four = [check_extraction(extraction_dir / "extraction-table.csv")]
    phase_five = [check_structural_analysis(analysis_dir)]
    phase_six = [
        check_prisma_counts(prisma_dir / "flow-counts.csv"),
        check_ultraquality_selection(selection_dir / "ultraquality-shortlist.csv", n_limit),
        check_figures(figures_dir),
        check_file(notes_dir / "decisions.md", "Decisions log"),
        check_file(audit_dir / "checklist.md", "Audit checklist"),
    ]

    phases = [
        ("Fase 1. Intake y protocolo", phase_status(phase_one), phase_one),
        ("Fase 2. Búsqueda, DOI y deduplicación", phase_status(phase_two), phase_two),
        ("Fase 3. Screening", phase_status(phase_three), phase_three),
        ("Fase 4. Extracción", phase_status(phase_four), phase_four),
        ("Fase 5. Análisis estructural", phase_status(phase_five), phase_five),
        ("Fase 6. Síntesis y calidad editorial", phase_status(phase_six), phase_six),
    ]

    phase_lines = ["# Phase Audit", ""]
    for phase_name, status, results in phases:
        phase_lines.append(f"## {phase_name} [{status}]")
        for result in results:
            phase_lines.append(f"- **{result.name}** [{result.status}]: {result.detail}")
        phase_lines.append("")

    write_text(audit_dir / "phase-audit.md", "\n".join(phase_lines).strip() + "\n")
    if not (audit_dir / "checklist.md").exists():
        write_text(audit_dir / "checklist.md", "# Audit Checklist\n")
    write_text(audit_dir / "final-audit.md", render_final(phases))

    print(f"phase_audit: {audit_dir / 'phase-audit.md'}")
    print(f"final_audit: {audit_dir / 'final-audit.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
