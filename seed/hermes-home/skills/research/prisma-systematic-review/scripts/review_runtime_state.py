#!/usr/bin/env python3
"""Compute runtime state for a systematic review and emit resumable status files."""

from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone

PHASES = [
    (
        "Fase 1. Intake y protocolo",
        [
            "protocol/intake.md",
            "protocol/intake.json",
            "protocol/review-mode.md",
            "protocol/review-mode.json",
            "protocol/method-contract.json",
            "protocol/synthesis-plan.json",
            "protocol/contracts-manifest.json",
            "protocol/research-question.md",
            "protocol/eligibility-criteria.md",
            "protocol/search-strategy.md",
        ],
        "Completada la base del protocolo.",
    ),
    (
        "Fase 2. Búsqueda, DOI y deduplicación",
        [
            "searches/search-log.csv",
            "records/master-records.csv",
            "records/doi-index.csv",
            "records/duplicates.csv",
            "records/missing-doi.csv",
        ],
        "Ejecutar búsquedas, registrar el search log y correr la auditoría DOI.",
    ),
    (
        "Fase 3. Screening",
        [
            "screening/title-abstract.csv",
            "screening/full-text.csv",
        ],
        "Continuar con screening title/abstract y full text con trazabilidad.",
    ),
    (
        "Fase 4. Extracción",
        [
            "extraction/extraction-table.csv",
            "selection/ultraquality-shortlist.csv",
        ],
        "Extraer metadatos, metodología, teoría y evidencia.",
    ),
    (
        "Fase 5. Análisis estructural y trazabilidad relacional",
        [
            "analysis/manifest.json",
            "analysis/atlas/network-atlas.html",
            "analysis/metrics/network-summary.json",
            "analysis/audit/coverage.json",
        ],
        "Construir redes, métricas, cobertura y atlas offline sin alterar decisiones de selección.",
    ),
    (
        "Fase 6. Síntesis y calidad editorial",
        [
            "prisma/flow-counts.csv",
            "paper/manuscript/publication-ready.md",
            "paper/review/peer-review-overview.md",
            "paper/audit/publication-gate.md",
            "paper/audit/publication-gate.json",
            "paper/audit/evidence-coverage.json",
        ],
        "Consolidar síntesis, figuras, evidencia, auditoría y revisión editorial.",
    ),
    (
        "Fase 7. Entrega navegable y reproducible",
        [
            "paper/manuscript/publication-ready.tex",
            "paper/manuscript/publication-ready.pdf",
            "paper/package/publication-package.zip",
            "paper/package/publication-latex-editable.zip",
            "paper/package/index.html",
            "paper/package/deliverables-manifest.json",
            "notes/pipeline-state.json",
        ],
        "Empaquetar manuscrito, datos, auditorías y guía HTML portátil.",
    ),
]

HEADER_ONLY_VALID_CSVS = {
    "records/doi-index.csv",
    "records/duplicates.csv",
    "records/missing-doi.csv",
    "screening/title-abstract.csv",
    "screening/full-text.csv",
    "extraction/extraction-table.csv",
    "selection/ultraquality-shortlist.csv",
    "prisma/flow-counts.csv",
    "figures/manifest.csv",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def has_meaningful_content(path: pathlib.Path) -> bool:
    if not path.exists():
        return False
    if path.suffix.lower() in {".csv", ".tsv"}:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        relative = "/".join(path.parts[-2:])
        if relative in HEADER_ONLY_VALID_CSVS:
            return len(lines) >= 1
        return len(lines) > 1
    return bool(path.read_text(encoding="utf-8", errors="ignore").strip())


def latest_mtime(review_dir: pathlib.Path) -> datetime | None:
    latest = None
    for path in review_dir.rglob("*"):
        if not path.is_file():
            continue
        if "audit" in path.parts:
            continue
        if path.name in {"runtime-state.md", "runtime-state.json"}:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone()
        if latest is None or mtime > latest:
            latest = mtime
    return latest


REQUIRED_FILE_SCHEMES = [
    # Phase 0: fallback mappings for common path variants
    [
        "paper/audit/publication-gate.md",
        "audit/publication-gate.md",
    ],
    # Phase 6: peer-review-overview may exist as review-manifest.csv or individual reviews
    [
        "paper/review/peer-review-overview.md",
        "paper/review/review-manifest.csv",
        "paper/review/reviewer-models.csv",
    ],
]


def _any_exists(review_dir: pathlib.Path, candidates: list[str]) -> bool:
    """Return True if at least one candidate path exists and has meaningful content."""
    for c in candidates:
        if has_meaningful_content(review_dir / c):
            return True
    return False


def _load_existing_state(notes_dir: pathlib.Path) -> dict | None:
    """Load existing runtime-state.json if it exists and has a 'status' field."""
    path = notes_dir / "runtime-state.json"
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(raw)
            if isinstance(data, dict) and "status" in data:
                return data
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    return None


def determine_state(review_dir: pathlib.Path, stalled_minutes: int) -> dict:
    last_update = latest_mtime(review_dir)
    blocker = ""
    current_phase = PHASES[0][0]
    next_phase = PHASES[0][0]
    next_action = PHASES[0][2]
    status = "completed"

    # Check if a manual 'completed' state should be preserved
    notes_dir = review_dir / "notes"
    existing_state = _load_existing_state(notes_dir)
    if existing_state and existing_state.get("status") == "completed":
        # Verify the review still has core artifacts before preserving
        core_manuscript = review_dir / "paper/manuscript/publication-ready.md"
        core_prisma = review_dir / "prisma/flow-counts.csv"
        core_analysis = review_dir / "analysis/manifest.json"
        core_guide = review_dir / "paper/package/index.html"
        core_gate = review_dir / "paper/audit/publication-gate.json"
        if (
            has_meaningful_content(core_manuscript)
            and has_meaningful_content(core_prisma)
            and has_meaningful_content(core_analysis)
            and has_meaningful_content(core_guide)
            and has_meaningful_content(core_gate)
        ):
            return {
                "status": "completed",
                "current_phase": PHASES[-1][0],
                "next_phase": "ninguna",
                "next_action": "Revisión completa; solo quedan mantenimientos o ampliaciones.",
                "blocker": "",
                "last_update": last_update.isoformat() if last_update else "",
                "updated_at": now_iso(),
                "resume_message": "La revisión está completada.",
            }

    for phase_name, required_files, action in PHASES:
        all_present = True
        for rel_path in required_files:
            target = review_dir / rel_path
            if not has_meaningful_content(target):
                # Try fallback path schemes
                schemata = REQUIRED_FILE_SCHEMES
                found = False
                for scheme in schemata:
                    if rel_path in scheme:
                        found = _any_exists(review_dir, scheme)
                        break
                if not found:
                    all_present = False
                    break
        if not all_present:
            status = "in_progress"
            current_phase = phase_name
            next_phase = phase_name
            next_action = action
            break

    if status == "completed":
        current_phase = PHASES[-1][0]
        next_phase = "ninguna"
        next_action = "Revisión completa; solo quedan mantenimientos o ampliaciones."

    if last_update and status != "completed":
        age_minutes = (datetime.now(timezone.utc).astimezone() - last_update).total_seconds() / 60
        if age_minutes >= stalled_minutes:
            status = "stalled"

    if not last_update:
        blocker = "No hay artefactos en la carpeta de la revisión."
        status = "blocked"

    resume_message = (
        f"Retoma la revisión actual desde {next_phase}. {next_action}"
        if status in {"in_progress", "stalled"}
        else "La revisión está completada."
    )

    return {
        "status": status,
        "current_phase": current_phase,
        "next_phase": next_phase,
        "next_action": next_action,
        "blocker": blocker,
        "last_update": last_update.isoformat() if last_update else "",
        "updated_at": now_iso(),
        "resume_message": resume_message,
    }


def write_markdown(path: pathlib.Path, state: dict) -> None:
    content = f"""# Runtime State

- Estado: `{state['status']}`
- Fase actual: `{state['current_phase']}`
- Siguiente fase: `{state['next_phase']}`
- Última actualización detectada: `{state['last_update'] or 'desconocida'}`
- Runtime actualizado en: `{state['updated_at']}`

## Siguiente acción
{state['next_action']}

## Bloqueo
{state['blocker'] or 'ninguno'}

## Mensaje de reanudación
{state['resume_message']}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument("--stalled-minutes", type=int, default=120, help="Minutes without changes before marking a review as stalled (default 120)")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory does not exist: {review_dir}")

    state = determine_state(review_dir, args.stalled_minutes)
    notes_dir = review_dir / "notes"
    md_path = notes_dir / "runtime-state.md"
    json_path = notes_dir / "runtime-state.json"
    write_markdown(md_path, state)
    write_json(json_path, state)
    print(f"runtime_state_md: {md_path}")
    print(f"runtime_state_json: {json_path}")
    print(f"status: {state['status']}")
    print(f"next_phase: {state['next_phase']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
