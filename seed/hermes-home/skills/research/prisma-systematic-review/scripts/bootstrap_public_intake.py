#!/usr/bin/env python3
"""Deterministic public bootstrap for a PRISMA review workspace.

Creates the review folder from the template, writes the intake, generates the
initial protocol artifacts, and refreshes runtime/audit state without running
the full search-and-screening pipeline yet.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import unicodedata


def load_bootstrap_module(script_dir: pathlib.Path):
    path = script_dir / "bootstrap_topic_review.py"
    spec = importlib.util.spec_from_file_location("bootstrap_topic_review", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load bootstrap module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_label(text: str) -> str:
    value = (text or "").strip()
    value = value.lstrip("-").strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def parse_final_n_range(raw: str) -> tuple[int | None, int]:
    numbers = [int(match) for match in re.findall(r"\d+", raw or "")]
    if len(numbers) >= 2:
        low, high = sorted(numbers[:2])
        return max(1, low), max(1, high)
    if len(numbers) == 1:
        return None, max(1, numbers[0])
    return None, 37


def review_dir_name(module, workspace_root: pathlib.Path, topic: str, year_label: str, final_n: int, final_n_min: int | None = None) -> str:
    slug = module.slugify(topic or "revision-prisma")
    n_label = f"n{final_n_min}-{final_n}" if final_n_min else f"n{final_n}"
    base = f"systematic-review-{slug}-{year_label}-{n_label}"
    candidate = workspace_root / base
    if not candidate.exists():
        return base
    for idx in range(2, 100):
        suffix = f"-r{idx:02d}"
        candidate = workspace_root / f"{base}{suffix}"
        if not candidate.exists():
            return f"{base}{suffix}"
    raise RuntimeError("Could not allocate a unique review directory name.")


def write_intake(path: pathlib.Path, data: dict[str, str]) -> None:
    lines = [
        "# Intake",
        "",
        f"- Tema: {data.get('topic', '').strip()}",
        f"- Pregunta de investigación (opcional): {data.get('research_question', '').strip()}",
        f"- Año o años: {data.get('year_or_years', '').strip()}",
        f"- Fecha inicial (opcional): {data.get('from_date', '').strip()}",
        f"- Fecha final (opcional): {data.get('to_date', '').strip()}",
        f"- Criterios de inclusión: {data.get('inclusion_criteria', '').strip()}",
        f"- Criterios de exclusión: {data.get('exclusion_criteria', '').strip()}",
        f"- Autores: {data.get('author_filters', '').strip()}",
        f"- Autoría del manuscrito (opcional): {data.get('manuscript_authors', '').strip()}",
        f"- Correo de contacto (opcional): {data.get('manuscript_email', '').strip()}",
        f"- Fecha del manuscrito (opcional): {data.get('manuscript_date', '').strip()}",
        f"- Modo autónomo: {data.get('autonomous_mode', 'sí').strip()}",
        f"- Modo metodológico (opcional): {(data.get('review_mode') or data.get('methodological_mode') or '').strip()}",
        f"- Límite final N ultraquality: {data.get('final_n', '').strip()}",
        f"- Criterio de representatividad ultraquality: {data.get('representativeness', '').strip()}",
        (
            "- Revista o medio objetivo (opcional; si se omite, o si solo indicas "
            f"una familia temática amplia, Hermes usa `generic-common-core`): {data.get('target_outlet', '').strip()}"
        ),
        f"- Longitud objetivo del manuscrito (opcional): {data.get('target_length', '').strip()}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def remove_generated_placeholders(review_dir: pathlib.Path) -> None:
    """Delete copied output artifacts that should not exist in a fresh review.

    The review template intentionally documents the expected artifact layout,
    but a newly bootstrapped review must start from protocol + empty runtime
    state only. If generated CSVs or publication placeholders survive the copy,
    downstream routing can mistake a new review for a partially completed one.
    """

    generated_patterns = [
        "searches/*.csv",
        "records/*.csv",
        "prisma/*.csv",
        "screening/*.csv",
        "extraction/*.csv",
        "selection/*.csv",
        "paper/audit/publication-*.md",
        "paper/audit/publication-*.csv",
        "paper/manuscript/compiled-submission.md",
        "paper/manuscript/publication-ready.*",
        "paper/package/*.zip",
        "paper/references/references.generated.*",
        "paper/review/peer-review-overview.md",
        "paper/review/review-manifest.csv",
        "paper/review/revision-roadmap/**",
        "paper/review/review-packet/**",
        "figures/manifest.csv",
        "notes/run.log",
        "notes/public-autonomous.pid",
    ]
    for pattern in generated_patterns:
        for path in review_dir.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def limited_refresh(script_dir: pathlib.Path, review_dir: pathlib.Path) -> None:
    commands = [
        [sys.executable, str(script_dir / "review_runtime_state.py"), str(review_dir)],
        [sys.executable, str(script_dir / "review_audit.py"), str(review_dir)],
        [sys.executable, str(script_dir / "sync_review_to_obsidian.py"), str(review_dir)],
    ]
    for command in commands:
        try:
            subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            continue


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, help="Workspace root containing systematic-review-template")
    parser.add_argument("--intake-json", required=True, help="Path to a JSON file with the normalized intake payload")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    workspace_root = pathlib.Path(args.workspace_root).expanduser().resolve()
    template_dir = workspace_root / "systematic-review-template"
    if not template_dir.exists():
        raise SystemExit(f"Template directory does not exist: {template_dir}")

    intake_payload = json.loads(pathlib.Path(args.intake_json).read_text(encoding="utf-8"))
    script_dir = pathlib.Path(__file__).resolve().parent
    bootstrap = load_bootstrap_module(script_dir)

    year_text = (intake_payload.get("year_or_years") or "").strip()
    year_start = year_end = 2026
    if "-" in year_text:
        parts = [part.strip() for part in year_text.split("-", 1)]
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            year_start, year_end = int(parts[0]), int(parts[1])
    elif year_text.isdigit():
        year_start = year_end = int(year_text)
    year_label = str(year_start) if year_start == year_end else f"{year_start}-{year_end}"

    final_n_raw = (intake_payload.get("final_n") or "").strip()
    final_n_min, final_n = parse_final_n_range(final_n_raw)
    if not final_n_raw:
        intake_payload["final_n"] = str(final_n)

    review_name = review_dir_name(
        bootstrap,
        workspace_root,
        intake_payload.get("topic", ""),
        year_label,
        final_n,
        final_n_min,
    )
    review_dir = workspace_root / review_name
    shutil.copytree(template_dir, review_dir)
    remove_generated_placeholders(review_dir)

    intake_path = review_dir / "protocol" / "intake.md"
    write_intake(intake_path, intake_payload)

    parsed_year_start, parsed_year_end = bootstrap.parse_years(intake_path)
    from_date, to_date = bootstrap.parse_date_window(intake_path, parsed_year_start, parsed_year_end)
    topic = bootstrap.parse_topic(intake_path) or "tema no especificado"
    question = bootstrap.parse_question(intake_path)
    inclusion = bootstrap.parse_intake_value(intake_path, "Criterios de inclusión")
    exclusion = bootstrap.parse_intake_value(intake_path, "Criterios de exclusión")
    mode_decision = bootstrap.infer_review_mode_from_intake(intake_path, topic, question, inclusion, exclusion)
    bootstrap.write_review_mode_artifacts(review_dir, mode_decision)
    # Telegram creation must respond immediately. The autonomous phase can
    # refine this auditable baseline with a cloud model after the review exists.
    decomposition = bootstrap.build_deterministic_search_decomposition(
        topic,
        question,
        inclusion,
        exclusion,
        mode_decision,
    )
    plan = bootstrap.extend_search_plan(bootstrap.flatten_search_plan(decomposition), topic, question, inclusion, mode_decision)
    if not any(plan.values()):
        plan = bootstrap.extend_search_plan(bootstrap.normalize_plan(bootstrap.query_plan(topic, question, inclusion)), topic, question, inclusion, mode_decision)
    bootstrap.write_search_decomposition_files(review_dir, decomposition, plan)

    bootstrap.ensure_protocol(
        review_dir,
        parsed_year_start,
        parsed_year_end,
        from_date,
        to_date,
        final_n,
        topic,
        question,
        inclusion,
        exclusion,
        plan,
        decomposition,
        mode_decision,
    )
    bootstrap.append_decision(
        review_dir,
        search_count=0,
        master_count=0,
        year_label=year_label,
        from_date=from_date,
        to_date=to_date,
        final_n=final_n,
        topic=topic,
        inclusion=inclusion,
        exclusion=exclusion,
        decomposition=decomposition,
        mode_decision=mode_decision,
    )
    limited_refresh(script_dir, review_dir)

    runtime_state_path = review_dir / "notes" / "runtime-state.json"
    runtime_state = {}
    if runtime_state_path.exists():
        runtime_state = json.loads(runtime_state_path.read_text(encoding="utf-8"))

    summary = {
        "review_dir": str(review_dir),
        "review_name": review_name,
        "topic": topic,
        "question": question,
        "year_label": year_label,
        "from_date": from_date,
        "to_date": to_date,
        "final_n": final_n,
        "final_n_min": final_n_min or "",
        "final_n_max": final_n,
        "autonomous_mode": (intake_payload.get("autonomous_mode") or "sí").strip(),
        "review_mode": mode_decision.get("mode", ""),
        "review_mode_label": mode_decision.get("mode_label", ""),
        "review_mode_confidence": mode_decision.get("confidence", ""),
        "target_outlet": (intake_payload.get("target_outlet") or "generic-common-core").strip(),
        "status": runtime_state.get("status", "in_progress"),
        "next_phase": runtime_state.get("next_phase", "Fase 2. Búsqueda, DOI y deduplicación"),
        "next_action": runtime_state.get("next_action", "Ejecutar búsquedas, registrar el search log y correr la auditoría DOI."),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
