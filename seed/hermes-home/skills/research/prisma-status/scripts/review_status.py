#!/usr/bin/env python3
"""Summarise the operational status of PRISMA review workspaces."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import subprocess
from typing import Iterable

SCRIPT_PATH = pathlib.Path(__file__).resolve()
HERMES_HOME = SCRIPT_PATH.parents[4]
RUNTIME_SCRIPT = HERMES_HOME / "skills" / "research" / "prisma-systematic-review" / "scripts" / "review_runtime_state.py"
AUDIT_SCRIPT = HERMES_HOME / "skills" / "research" / "prisma-systematic-review" / "scripts" / "review_audit.py"


def csv_rows(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def parse_key_values(md_path: pathlib.Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not md_path.exists():
        return data
    for line in md_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"-\s+([^:]+):\s+(.*)$", line.strip())
        if not match:
            continue
        key = match.group(1).strip().lower()
        value = match.group(2).strip().strip("`")
        data[key] = value
    return data


def parse_intake(md_path: pathlib.Path) -> dict[str, str]:
    data = {
        "tema": "",
        "año o años": "",
        "criterios de inclusión": "",
        "criterios de exclusión": "",
        "autores": "",
        "modo autónomo": "",
        "límite final n ultraquality": "",
        "criterio de representatividad ultraquality": "",
    }
    if not md_path.exists():
        return data
    for line in md_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"-\s+([^:]+):\s+(.*)$", line.strip())
        if not match:
            continue
        key = match.group(1).strip().lower()
        if key in data:
            data[key] = match.group(2).strip()
    return data


def parse_phase_audit(path: pathlib.Path) -> list[tuple[str, str]]:
    phases: list[tuple[str, str]] = []
    if not path.exists():
        return phases
    pattern = re.compile(r"^##\s+(.*?)\s+\[(PASS|WARN|FAIL)\]\s*$")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line.strip())
        if match:
            phases.append((match.group(1), match.group(2)))
    return phases


def parse_final_audit(path: pathlib.Path) -> str:
    if not path.exists():
        return "sin auditoría final"
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"Estado global:\s*`?([A-Z]+)`?", text)
    if match:
        return match.group(1)
    return "desconocido"


def count_decisions(rows: Iterable[dict]) -> dict[str, int]:
    counts = {"include": 0, "exclude": 0, "pending": 0, "other": 0}
    for row in rows:
        decision = (row.get("decision") or "").strip().lower()
        if decision in {"include", "include_ft", "include_ta"}:
            counts["include"] += 1
        elif decision in {"pending", "maybe"}:
            counts["pending"] += 1
        elif decision in counts:
            counts[decision] += 1
        else:
            counts["other"] += 1
    return counts


def find_reviews(workspace_root: pathlib.Path) -> list[pathlib.Path]:
    reviews = []
    for child in sorted(workspace_root.iterdir()) if workspace_root.exists() else []:
        if not child.is_dir():
            continue
        if not child.name.startswith("systematic-review"):
            continue
        if child.name == "systematic-review-template":
            continue
        reviews.append(child)
    return reviews


def review_sort_key(review_dir: pathlib.Path) -> tuple[int, float]:
    runtime_json = review_dir / "notes" / "runtime-state.json"
    status_priority = 9
    if runtime_json.exists():
        try:
            payload = json.loads(runtime_json.read_text(encoding="utf-8"))
            status = payload.get("status", "")
        except json.JSONDecodeError:
            status = ""
        status_priority = {"stalled": 0, "in_progress": 1, "blocked": 2, "completed": 3}.get(status, 9)
    return (status_priority, -review_dir.stat().st_mtime)


def resolve_review_dir(arg_review_dir: str | None, workspace_root: pathlib.Path) -> pathlib.Path | None:
    if arg_review_dir:
        return pathlib.Path(arg_review_dir).expanduser().resolve()
    reviews = sorted(find_reviews(workspace_root), key=review_sort_key)
    return reviews[0] if reviews else None


def refresh_review(review_dir: pathlib.Path, stalled_minutes: int) -> None:
    subprocess.run(
        ["python3", str(RUNTIME_SCRIPT), str(review_dir), "--stalled-minutes", str(stalled_minutes)],
        text=True,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["python3", str(AUDIT_SCRIPT), str(review_dir)],
        text=True,
        capture_output=True,
        check=False,
    )


def build_summary(review_dir: pathlib.Path) -> dict:
    intake = parse_intake(review_dir / "protocol" / "intake.md")
    runtime_md = parse_key_values(review_dir / "notes" / "runtime-state.md")
    runtime_json_path = review_dir / "notes" / "runtime-state.json"
    runtime_json = {}
    if runtime_json_path.exists():
        try:
            runtime_json = json.loads(runtime_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            runtime_json = {}

    search_rows = csv_rows(review_dir / "searches" / "search-log.csv")
    doi_rows = csv_rows(review_dir / "records" / "doi-index.csv")
    duplicate_rows = csv_rows(review_dir / "records" / "duplicates.csv")
    missing_doi_rows = csv_rows(review_dir / "records" / "missing-doi.csv")
    master_rows = csv_rows(review_dir / "records" / "master-records.csv")
    title_rows = csv_rows(review_dir / "screening" / "title-abstract.csv")
    full_text_rows = csv_rows(review_dir / "screening" / "full-text.csv")
    extraction_rows = csv_rows(review_dir / "extraction" / "extraction-table.csv")
    prisma_rows = csv_rows(review_dir / "prisma" / "flow-counts.csv")
    figure_rows = csv_rows(review_dir / "figures" / "manifest.csv")
    selection_rows = csv_rows(review_dir / "selection" / "ultraquality-shortlist.csv")

    title_counts = count_decisions(title_rows)
    full_text_counts = count_decisions(full_text_rows)
    phase_audit = parse_phase_audit(review_dir / "audit" / "phase-audit.md")

    return {
        "review_dir": str(review_dir),
        "topic": intake.get("tema") or review_dir.name,
        "years": intake.get("año o años") or "sin definir",
        "author_filters": intake.get("autores") or "sin definir",
        "autonomous_mode": intake.get("modo autónomo") or "sí",
        "ultraquality_limit_n": intake.get("límite final n ultraquality") or "sin límite",
        "ultraquality_representativeness": intake.get("criterio de representatividad ultraquality") or "sin definir",
        "status": runtime_json.get("status") or runtime_md.get("estado") or "desconocido",
        "current_phase": runtime_json.get("current_phase") or runtime_md.get("fase actual") or "desconocida",
        "next_phase": runtime_json.get("next_phase") or runtime_md.get("siguiente fase") or "desconocida",
        "next_action": runtime_json.get("next_action") or "sin acción registrada",
        "blocker": runtime_json.get("blocker") or "ninguno",
        "last_update": runtime_json.get("last_update") or runtime_md.get("última actualización detectada") or "desconocida",
        "search_count": len(search_rows),
        "doi_count": len(doi_rows),
        "duplicates_count": len(duplicate_rows),
        "missing_doi_count": len(missing_doi_rows),
        "master_count": len(master_rows),
        "title_abstract_total": len(title_rows),
        "title_abstract_counts": title_counts,
        "full_text_total": len(full_text_rows),
        "full_text_counts": full_text_counts,
        "extraction_count": len(extraction_rows),
        "prisma_count_rows": len(prisma_rows),
        "figure_count": len(figure_rows),
        "selection_count": len(selection_rows),
        "selection_selected_count": sum(
            1 for row in selection_rows
            if (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "sí", "si", "true", "1"}
        ),
        "phase_audit": phase_audit,
        "final_audit": parse_final_audit(review_dir / "audit" / "final-audit.md"),
    }


def render_markdown(summary: dict) -> str:
    audit_summary = ", ".join(f"{name}: {status}" for name, status in summary["phase_audit"]) or "sin auditoría por fases"
    ta = summary["title_abstract_counts"]
    ft = summary["full_text_counts"]
    lines = [
        "# Estado PRISMA",
        "",
        f"- Revisión: `{summary['review_dir']}`",
        f"- Tema: {summary['topic']}",
        f"- Año o años: {summary['years']}",
        f"- Autores: {summary['author_filters']}",
        f"- Modo autónomo: {summary['autonomous_mode']}",
        f"- Límite final N ultraquality: {summary['ultraquality_limit_n']}",
        f"- Representatividad ultraquality: {summary['ultraquality_representativeness']}",
        f"- Estado global: `{summary['status']}`",
        f"- Fase actual: `{summary['current_phase']}`",
        f"- Siguiente fase: `{summary['next_phase']}`",
        f"- Siguiente acción: {summary['next_action']}",
        f"- Bloqueo: {summary['blocker'] or 'ninguno'}",
        f"- Última actualización: {summary['last_update']}",
        "",
        "## Conteos",
        f"- Búsquedas registradas: {summary['search_count']}",
        f"- Registros maestros: {summary['master_count']}",
        f"- DOI indexados: {summary['doi_count']}",
        f"- Duplicados: {summary['duplicates_count']}",
        f"- Sin DOI: {summary['missing_doi_count']}",
        f"- Screening título/resumen: {summary['title_abstract_total']} (include={ta['include']}, exclude={ta['exclude']}, pending={ta['pending']}, other={ta['other']})",
        f"- Screening full text: {summary['full_text_total']} (include={ft['include']}, exclude={ft['exclude']}, pending={ft['pending']}, other={ft['other']})",
        f"- Filas de extracción: {summary['extraction_count']}",
        f"- Filas PRISMA: {summary['prisma_count_rows']}",
        f"- Shortlist ultraquality: {summary['selection_count']} filas ({summary['selection_selected_count']} seleccionadas para el N final)",
        f"- Figuras registradas: {summary['figure_count']}",
        "",
        "## Auditoría",
        f"- Fases: {audit_summary}",
        f"- Auditoría final: {summary['final_audit']}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", nargs="?", help="Specific review directory to inspect")
    parser.add_argument("--workspace-root", default="/workspace", help="Workspace root that contains systematic-review* folders")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    parser.add_argument("--stalled-minutes", type=int, default=15, help="Minutes without updates before runtime is considered stalled")
    args = parser.parse_args()

    workspace_root = pathlib.Path(args.workspace_root).expanduser().resolve()
    review_dir = resolve_review_dir(args.review_dir, workspace_root)
    if review_dir is None or not review_dir.exists():
        raise SystemExit("No se ha encontrado ninguna revisión PRISMA en el workspace.")

    refresh_review(review_dir, args.stalled_minutes)
    summary = build_summary(review_dir)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
