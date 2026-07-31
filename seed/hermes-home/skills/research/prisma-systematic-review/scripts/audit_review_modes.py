#!/usr/bin/env python3
"""Audit Hermes methodological review modes and render the publication playbook.

This script is deliberately deterministic: it checks that every mode has enough
disciplinary content to guide search, screening, appraisal, writing, figures and
tables without relying on ad-hoc prompting during a review run.
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys

from review_mode_router import MODE_ORDER, mode_config, selection_weights

REQUIRED_KEYS = [
    "label_public_es",
    "default_framework",
    "question_frameworks",
    "core_logic",
    "primary_unit",
    "recommended_sources",
    "screening_axes",
    "appraisal_tools",
    "critical_appraisal_domains",
    "synthesis_modes",
    "selection_score_weights",
    "writing_rules",
    "mode_question_es",
    "ask_policy",
    "minimum_tables",
    "recommended_tables",
    "minimum_figures",
    "recommended_figures",
    "mode_specific_outputs",
    "publication_section_requirements",
    "red_flags",
    "excellence_checklist",
]


LIST_MINIMUMS = {
    "question_frameworks": 1,
    "recommended_sources": 3,
    "screening_axes": 5,
    "appraisal_tools": 2,
    "critical_appraisal_domains": 5,
    "synthesis_modes": 2,
    "writing_rules": 3,
    "ask_policy": 3,
    "minimum_tables": 5,
    "minimum_figures": 3,
    "mode_specific_outputs": 3,
    "publication_section_requirements": 4,
    "red_flags": 4,
    "excellence_checklist": 4,
}


def as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    def clean(value: object) -> str:
        text = str(value or "").replace("\n", " ").strip()
        return text.replace("|", "\\|")

    lines = [
        "| " + " | ".join(clean(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(clean(cell) for cell in row) + " |")
    return "\n".join(lines)


def audit_mode(mode: str) -> tuple[list[str], dict[str, object]]:
    cfg = mode_config(mode)
    issues: list[str] = []
    for key in REQUIRED_KEYS:
        value = cfg.get(key)
        if value in (None, "", [], {}):
            issues.append(f"missing:{key}")
    for key, minimum in LIST_MINIMUMS.items():
        count = len(as_list(cfg.get(key)))
        if count < minimum:
            issues.append(f"too_short:{key}:{count}/{minimum}")
    wr, wq, wp = selection_weights(mode)
    if abs((wr + wq + wp) - 1.0) > 0.001:
        issues.append("score_weights_do_not_sum_to_1")
    payload = {
        "mode": mode,
        "label": cfg.get("label_public_es", ""),
        "framework": cfg.get("default_framework", ""),
        "question": cfg.get("mode_question_es", ""),
        "sources_n": len(as_list(cfg.get("recommended_sources"))),
        "axes_n": len(as_list(cfg.get("screening_axes"))),
        "appraisal_n": len(as_list(cfg.get("appraisal_tools"))),
        "tables_min_n": len(as_list(cfg.get("minimum_tables"))),
        "figures_min_n": len(as_list(cfg.get("minimum_figures"))),
        "outputs_n": len(as_list(cfg.get("mode_specific_outputs"))),
        "red_flags_n": len(as_list(cfg.get("red_flags"))),
        "score_weights": f"{wr:.2f}/{wq:.2f}/{wp:.2f}",
        "status": "PASS" if not issues else "FAIL",
        "issues": "; ".join(issues),
    }
    return issues, payload


def render_mode_section(mode: str) -> str:
    cfg = mode_config(mode)
    wr, wq, wp = selection_weights(mode)

    def bullets(key: str) -> list[str]:
        return [f"- {item}" for item in as_list(cfg.get(key))]

    lines = [
        f"## {cfg.get('label_public_es', mode)}",
        "",
        f"- Campo interno: `{mode}`",
        f"- Marco por defecto: {cfg.get('default_framework', '')}",
        f"- Unidad de comparación: {cfg.get('primary_unit', '')}",
        f"- Pregunta que puede hacerse al usuario: {cfg.get('mode_question_es', '')}",
        f"- Score focal: Rel={wr:.2f}, Cal={wq:.2f}, Rep={wp:.2f}",
        "",
        "### Cuándo preguntar o inferir",
        *bullets("ask_policy"),
        "",
        "### Qué debe buscar y extraer",
        *bullets("screening_axes"),
        "",
        "### Fuentes recomendadas",
        *bullets("recommended_sources"),
        "",
        "### Evaluación crítica",
        *bullets("critical_appraisal_domains"),
        "",
        "### Tablas mínimas",
        *bullets("minimum_tables"),
        "",
        "### Figuras con valor analítico",
        *bullets("minimum_figures"),
        "",
        "### Salidas específicas",
        *bullets("mode_specific_outputs"),
        "",
        "### Requisitos de escritura",
        *bullets("publication_section_requirements"),
        "",
        "### Red flags",
        *bullets("red_flags"),
        "",
        "### Qué lo hace sobresaliente",
        *bullets("excellence_checklist"),
        "",
    ]
    return "\n".join(lines).rstrip()


def write_csv(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "mode",
        "label",
        "framework",
        "question",
        "sources_n",
        "axes_n",
        "appraisal_n",
        "tables_min_n",
        "figures_min_n",
        "outputs_n",
        "red_flags_n",
        "score_weights",
        "status",
        "issues",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def render_audit(rows: list[dict[str, object]], total_issues: int) -> str:
    summary_rows = [
        [
            row["mode"],
            row["label"],
            row["framework"],
            row["score_weights"],
            row["tables_min_n"],
            row["figures_min_n"],
            row["status"],
        ]
        for row in rows
    ]
    status = "PASS" if total_issues == 0 else "FAIL"
    lines = [
        "# Auditoría de modos metodológicos Hermes",
        "",
        f"- Estado global: **{status}**",
        f"- Modos auditados: {len(rows)}",
        f"- Problemas detectados: {total_issues}",
        "",
        "## Política general",
        "Hermes puede preguntar o ubicar el campo. Si el usuario declara un modo, se respeta. Si no lo declara y la inferencia es alta o media, se persiste la inferencia con justificación. Si la confianza es baja y la interfaz es interactiva, se formula una sola pregunta de campo. Si el flujo es autónomo, no se bloquea: se aplica common-core o modo mixto documentado y se deja trazabilidad en `protocol/review-mode.md`.",
        "",
        "## Matriz de cobertura",
        markdown_table(
            ["Modo", "Etiqueta", "Marco", "Score Rel/Cal/Rep", "Tablas mín.", "Figuras mín.", "Estado"],
            summary_rows,
        ),
        "",
        "## Catálogo por campo",
        "",
        *(render_mode_section(str(row["mode"])) for row in rows),
        "",
        "## Regla editorial transversal",
        "Una figura o tabla entra en el cuerpo del paper solo si reduce complejidad, muestra una relación analítica, permite auditar una decisión o sostiene una tesis. Si solo decora, se mueve a anexo o se elimina.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-md", default=str(root / "review-modes-audit.md"))
    parser.add_argument("--output-csv", default=str(root / "review-modes-matrix.csv"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    rows: list[dict[str, object]] = []
    total_issues = 0
    for mode in MODE_ORDER:
        issues, row = audit_mode(mode)
        rows.append(row)
        total_issues += len(issues)
    output_md = pathlib.Path(args.output_md).expanduser().resolve()
    output_csv = pathlib.Path(args.output_csv).expanduser().resolve()
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_audit(rows, total_issues), encoding="utf-8")
    write_csv(output_csv, rows)
    print(f"status={'PASS' if total_issues == 0 else 'FAIL'} modes={len(rows)} issues={total_issues}")
    print(f"md={output_md}")
    print(f"csv={output_csv}")
    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
