"""Portable HTML guide and manifest for a complete review delivery."""

from __future__ import annotations

import csv
import html
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any

from artifact_contracts import sha256_file, write_json_atomic
from pipeline_state import pipeline_summary

DELIVERY_SCHEMA = "hermes.deliverables-manifest/v1"
DELIVERABLES = [
    {
        "id": "methodology",
        "number": "01",
        "title": "Método y protocolo",
        "description": "Define qué se pregunta, qué entra, cómo se compara y qué síntesis es defendible.",
        "patterns": [
            "protocol/intake.md",
            "protocol/intake.json",
            "protocol/research-question.md",
            "protocol/eligibility-criteria.md",
            "protocol/search-decomposition.*",
            "protocol/method-contract.json",
            "protocol/synthesis-plan.json",
            "protocol/journal-profile.json",
            "protocol/amendments.jsonl",
        ],
        "required": ["protocol/intake.json", "protocol/method-contract.json", "protocol/synthesis-plan.json"],
        "start": "protocol/method-contract.json",
    },
    {
        "id": "bibliography",
        "number": "02",
        "title": "Corpus bibliográfico",
        "description": "Conserva búsquedas, DOI normalizados, duplicados, ausencias y bibliografía exportable.",
        "patterns": ["searches/*.csv", "records/*.csv", "paper/references/*"],
        "required": ["searches/search-log.csv", "records/master-records.csv"],
        "start": "records/master-records.csv",
    },
    {
        "id": "screening",
        "number": "03",
        "title": "Cribado y selección",
        "description": "Muestra cada decisión, el motivo y la frontera entre corpus incluido y síntesis focal.",
        "patterns": ["screening/*.csv", "selection/*.csv", "prisma/flow-counts.csv"],
        "required": [
            "screening/title-abstract.csv",
            "screening/full-text.csv",
            "selection/ultraquality-shortlist.csv",
        ],
        "start": "screening/full-text.csv",
    },
    {
        "id": "full_text",
        "number": "04",
        "title": "Biblioteca de texto completo",
        "description": "Reúne documentos fuente, extracción estructurada, hashes y estado de lectura.",
        "patterns": ["fulltext/manifest.csv", "fulltext/docling/*", "fulltext/pdf/*.pdf"],
        "required": ["fulltext/manifest.csv"],
        "start": "fulltext/manifest.csv",
    },
    {
        "id": "evidence",
        "number": "05",
        "title": "Matriz de evidencia",
        "description": "Conecta DOI, método, variables, hallazgos, fragmentos y afirmaciones del manuscrito.",
        "patterns": [
            "extraction/*.csv",
            "tables/critical-appraisal-matrix.csv",
            "paper/audit/claim-evidence-ledger.csv",
            "paper/audit/evidence-coverage.*",
            "analysis/evidence/*",
        ],
        "required": [
            "extraction/extraction-table.csv",
            "paper/audit/claim-evidence-ledger.csv",
            "paper/audit/evidence-coverage.json",
        ],
        "start": "paper/audit/evidence-coverage.md",
    },
    {
        "id": "analysis",
        "number": "06",
        "title": "Síntesis y análisis",
        "description": "Incluye posiciones de evidencia, matrices especializadas, prioridad de lectura, evaluación crítica, sensibilidad, redes y comunidades.",
        "patterns": [
            "analysis/manifest.json",
            "analysis/scientific-intelligence.json",
            "analysis/reading-priority.csv",
            "analysis/evidence/*",
            "analysis/security/*",
            "analysis/reproducibility/*",
            "analysis/data/*",
            "analysis/metrics/*",
            "analysis/audit/*",
            "paper/appendices/data/*",
        ],
        "required": ["analysis/manifest.json", "analysis/metrics/network-summary.json"],
        "start": "analysis/metrics/network-summary.json",
    },
    {
        "id": "visuals",
        "number": "07",
        "title": "Figuras y tablas",
        "description": "Cada visual conserva fuente editable, versión de publicación y justificación analítica.",
        "patterns": [
            "figures/manifest.csv",
            "figures/*.html",
            "figures/*.md",
            "figures/png/*",
            "figures/svg/*",
            "analysis/figures/png/*",
            "analysis/figures/svg/*",
            "tables/*.csv",
            "tables/*.md",
        ],
        "required": [
            "figures/gallery.html",
            "figures/manifest.csv",
            "figures/paper-figures-spec.csv",
            "tables/paper-tables-spec.csv",
        ],
        "start": "figures/gallery.html",
    },
    {
        "id": "publication",
        "number": "08",
        "title": "Manuscrito publicable",
        "description": "Entrega el texto canónico, LaTeX editable, PDF compilado, referencias y anexos.",
        "patterns": [
            "paper/manuscript/publication-ready.md",
            "paper/manuscript/publication-ready.tex",
            "paper/manuscript/publication-ready.pdf",
            "paper/references/*",
            "paper/appendices/data/*",
        ],
        "required": [
            "paper/manuscript/publication-ready.md",
            "paper/manuscript/publication-ready.tex",
            "paper/manuscript/publication-ready.pdf",
        ],
        "start": "paper/manuscript/publication-ready.pdf",
    },
    {
        "id": "editorial",
        "number": "09",
        "title": "Preparación editorial",
        "description": "Reúne peer review, roadmap, carta, declaraciones, checklists y ajuste a revista.",
        "patterns": ["paper/review/**/*", "paper/journal-readiness/*"],
        "required": [
            "paper/review/peer-review-overview.md",
            "paper/journal-readiness/journal-readiness-report.md",
        ],
        "start": "paper/journal-readiness/journal-readiness-report.md",
    },
    {
        "id": "audit",
        "number": "10",
        "title": "Auditoría y procedencia",
        "description": "Prueba qué modelos actuaron, qué falló, qué gate pasó y qué evidencia sostiene el cierre.",
        "patterns": ["paper/audit/**/*"],
        "required": [
            "paper/audit/publication-gate.json",
            "paper/audit/model-capabilities.json",
            "paper/audit/evidence-coverage.json",
        ],
        "start": "paper/audit/publication-gate.md",
    },
    {
        "id": "update",
        "number": "11",
        "title": "Reanudación y actualización",
        "description": "Permite continuar por contenido cambiado sin repetir fases estables.",
        "patterns": [
            "notes/runtime-state.*",
            "notes/pipeline-state.json",
            "notes/artifact-lineage.json",
            "notes/job-ledger.json",
        ],
        "required": ["notes/pipeline-state.json", "notes/artifact-lineage.json"],
        "start": "notes/artifact-lineage.json",
    },
    {
        "id": "interactive",
        "number": "12",
        "title": "Exploración interactiva",
        "description": "Abre el atlas offline y exporta redes a GraphML o GEXF para Gephi.",
        "patterns": ["analysis/atlas/*", "analysis/data/*.graphml", "analysis/data/*.gexf"],
        "required": ["analysis/atlas/network-atlas.html"],
        "start": "analysis/atlas/network-atlas.html",
    },
]


def read_csv_count(path: pathlib.Path) -> int:
    """Count data rows without loading large CSVs into the browser guide."""
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _row in csv.DictReader(handle))


def read_json(path: pathlib.Path) -> dict[str, Any]:
    """Read a JSON summary with a safe empty default."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def review_title(review_dir: pathlib.Path) -> str:
    """Read the full manuscript title rather than a shortened internal label."""
    manuscript = review_dir / "paper" / "manuscript" / "publication-ready.md"
    if manuscript.exists():
        for line in manuscript.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    intake = read_json(review_dir / "protocol" / "intake.json")
    return str(intake.get("topic") or review_dir.name)


def collect_files(review_dir: pathlib.Path, patterns: list[str]) -> list[pathlib.Path]:
    """Expand recursive patterns while excluding transient package products."""
    files: set[pathlib.Path] = set()
    for pattern in patterns:
        files.update(path for path in review_dir.glob(pattern) if path.is_file())
    return sorted(
        path
        for path in files
        if "__pycache__" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(review_dir).parts)
        and path.name not in {"publication-package.zip"}
    )


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    """Read a small CSV used to explain visual publication decisions."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def figure_asset_href(path_value: str) -> str:
    """Resolve a review-relative asset from figures/gallery.html."""
    value = path_value.strip().lstrip("/")
    if value.startswith("figures/"):
        return value[len("figures/") :]
    return "../" + value


def build_figure_gallery(review_dir: pathlib.Path) -> pathlib.Path:
    """Create an offline academic gallery for every publication-ready visual."""
    figures_dir = review_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = read_csv_rows(figures_dir / "manifest.csv")
    manifest_ids = {(row.get("figure_id") or "").strip() for row in manifest_rows}
    for figure_id, title, stem in (
        ("fig-topic-network", "Red temática del corpus", "topics-network"),
        ("fig-author-network", "Red de coautoría del corpus", "authors-network"),
    ):
        png_path = review_dir / "analysis" / "figures" / "png" / f"{stem}.png"
        svg_path = review_dir / "analysis" / "figures" / "svg" / f"{stem}.svg"
        if figure_id in manifest_ids or not png_path.exists():
            continue
        manifest_rows.append(
            {
                "figure_id": figure_id,
                "title": title,
                "apa_caption": (
                    "Figura de análisis estructural del corpus. "
                    "Su uso en el manuscrito depende de cobertura, estabilidad y valor no redundante."
                ),
                "notes": "Activo estructural generado junto al atlas interactivo.",
                "png_path": png_path.relative_to(review_dir).as_posix(),
                "svg_path": svg_path.relative_to(review_dir).as_posix() if svg_path.exists() else "",
            }
        )
    ranking = {
        row.get("figure_id", ""): row
        for row in read_csv_rows(figures_dir / "figure-ranking.csv")
    }
    gate = {
        row.get("figure_id", ""): row
        for row in read_csv_rows(figures_dir / "figure-gate.csv")
    }
    grouped: dict[str, list[str]] = {
        "main_body": [],
        "supplementary": [],
        "reserve": [],
    }
    labels = {
        "main_body": "Cuerpo propuesto",
        "supplementary": "Material suplementario",
        "reserve": "Reserva editorial",
    }
    descriptions = {
        "main_body": "Figuras que mejor sostienen el argumento de esta revisión según valor científico, densidad y no redundancia.",
        "supplementary": "Visuales útiles para auditoría, réplica o exploración sin ocupar el espacio central del manuscrito.",
        "reserve": "Activos editables disponibles si la revista, el revisor o una pregunta secundaria justifican su uso.",
    }
    for row in manifest_rows:
        figure_id = (row.get("figure_id") or "").strip()
        png_path = (row.get("png_path") or "").strip()
        svg_path = (row.get("svg_path") or "").strip()
        if not figure_id or not png_path or not (review_dir / png_path).exists():
            continue
        decision = (
            gate.get(figure_id, {}).get("decision")
            or ranking.get(figure_id, {}).get("recommendation")
            or "supplementary"
        ).strip()
        if decision not in grouped:
            decision = "reserve"
        title = html.escape(row.get("title") or figure_id)
        raw_caption = row.get("apa_caption") or row.get("purpose") or ""
        raw_caption = re.sub(
            r"^Figura(?:\s+\d+|\s+adicional|\s+suplementaria)?\.\s*",
            "",
            raw_caption,
            flags=re.IGNORECASE,
        )
        caption = html.escape(raw_caption)
        rationale = html.escape(
            ranking.get(figure_id, {}).get("rationale")
            or row.get("notes")
            or "Activo visual trazable y editable."
        )
        png_href = html.escape(figure_asset_href(png_path))
        svg_href = html.escape(figure_asset_href(svg_path)) if svg_path else ""
        svg_link = (
            f'<a href="{svg_href}" download>Descargar SVG</a>'
            if svg_path and (review_dir / svg_path).exists()
            else ""
        )
        grouped[decision].append(
            f"""
            <article class="figure-card">
              <div class="figure-meta"><span>{html.escape(row.get("paper_section") or "Catálogo visual")}</span><span>{html.escape(decision.replace("_", " "))}</span></div>
              <a class="preview" href="{png_href}"><img src="{png_href}" alt="{title}" loading="lazy"></a>
              <div class="figure-copy">
                <h3>{title}</h3>
                <p>{caption}</p>
                <p class="rationale">{rationale}</p>
                <div class="downloads">
                  <a href="{png_href}" download>Descargar PNG</a>
                  {svg_link}
                </div>
              </div>
            </article>
            """
        )
    sections = []
    for key in ("main_body", "supplementary", "reserve"):
        if not grouped[key]:
            continue
        sections.append(
            f"""
            <section>
              <header class="section-heading">
                <h2>{labels[key]}</h2>
                <p>{descriptions[key]}</p>
              </header>
              <div class="gallery">{''.join(grouped[key])}</div>
            </section>
            """
        )
    title = html.escape(review_title(review_dir))
    gallery_path = figures_dir / "gallery.html"
    gallery_path.write_text(
        f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Catálogo de figuras · {title}</title>
  <style>
    :root {{ --ink:#20201d; --muted:#66645d; --rule:#c9c7bf; --paper:#fbfaf6; --panel:#fff; --accent:#173f63; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--paper); font-family:Georgia,"Times New Roman",serif; }}
    a {{ color:var(--accent); }}
    .page {{ width:min(1420px,calc(100% - 40px)); margin:0 auto; }}
    .masthead {{ padding:46px 0 30px; border-bottom:1px solid var(--ink); }}
    .eyebrow {{ margin:0 0 14px; color:var(--muted); font:600 12px/1.4 ui-sans-serif,sans-serif; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ max-width:1100px; margin:0; font-size:clamp(38px,5vw,72px); line-height:1.02; font-weight:500; }}
    .lead {{ max-width:900px; margin:18px 0 0; color:var(--muted); font-size:20px; line-height:1.5; }}
    section {{ padding:42px 0; border-bottom:1px solid var(--rule); }}
    .section-heading {{ display:grid; grid-template-columns:minmax(260px,.7fr) minmax(320px,1fr); gap:40px; align-items:start; margin-bottom:24px; }}
    h2 {{ margin:0; font-size:31px; font-weight:500; }}
    .section-heading p {{ margin:0; color:var(--muted); font-size:17px; line-height:1.55; }}
    .gallery {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:28px; }}
    .figure-card {{ overflow:hidden; background:var(--panel); border:1px solid var(--rule); }}
    .figure-meta {{ display:flex; justify-content:space-between; gap:16px; padding:10px 14px; border-bottom:1px solid var(--rule); color:var(--muted); font:600 11px/1.2 ui-sans-serif,sans-serif; letter-spacing:.06em; text-transform:uppercase; }}
    .preview {{ display:block; padding:14px; background:#f3f2ed; border-bottom:1px solid var(--rule); }}
    .preview img {{ display:block; width:100%; height:auto; background:white; }}
    .figure-copy {{ padding:20px; }}
    h3 {{ margin:0 0 9px; font-size:24px; font-weight:500; }}
    .figure-copy p {{ margin:0 0 12px; font-size:16px; line-height:1.5; }}
    .rationale {{ color:var(--muted); }}
    .downloads {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }}
    .downloads a {{ padding:9px 12px; border:1px solid var(--accent); text-decoration:none; font:600 13px/1 ui-sans-serif,sans-serif; }}
    .downloads a:hover,.downloads a:focus {{ color:white; background:var(--accent); }}
    footer {{ padding:24px 0 40px; color:var(--muted); font-size:13px; }}
    @media (max-width:820px) {{ .gallery,.section-heading {{ grid-template-columns:1fr; }} .page {{ width:min(100% - 22px,1420px); }} }}
    @media print {{ .downloads {{ display:none; }} .figure-card {{ break-inside:avoid; }} }}
  </style>
</head>
<body>
  <main class="page">
    <header class="masthead">
      <p class="eyebrow">Catálogo científico de figuras · PNG y SVG editables</p>
      <h1>{title}</h1>
      <p class="lead">El catálogo separa propuesta de cuerpo, suplemento y reserva. La decisión se basa en utilidad científica y trazabilidad; una figura no entra en el manuscrito solo por estar disponible.</p>
    </header>
    {''.join(sections) if sections else '<section><p>No hay figuras renderizadas disponibles.</p></section>'}
    <footer>Catálogo autónomo y sin dependencias externas. Los SVG conservan la fuente editable de cada figura.</footer>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return gallery_path


def build_manifest(review_dir: pathlib.Path) -> dict[str, Any]:
    """Build a hashed, reader-oriented inventory for every deliverable family."""
    categories: list[dict[str, Any]] = []
    for spec in DELIVERABLES:
        files = collect_files(review_dir, list(spec["patterns"]))
        required = [review_dir / value for value in spec["required"]]
        missing = [path.relative_to(review_dir).as_posix() for path in required if not path.is_file() or path.stat().st_size == 0]
        available_paths = {path.relative_to(review_dir).as_posix() for path in files}
        requested_start = str(spec["start"])
        start_path = (
            requested_start
            if requested_start in available_paths
            else (files[0].relative_to(review_dir).as_posix() if files else "")
        )
        categories.append(
            {
                "id": spec["id"],
                "number": spec["number"],
                "title": spec["title"],
                "description": spec["description"],
                "status": "complete" if not missing else ("partial" if files else "missing"),
                "required_missing": missing,
                "start_path": start_path,
                "file_count": len(files),
                "byte_count": sum(path.stat().st_size for path in files),
                "files": [
                    {
                        "path": path.relative_to(review_dir).as_posix(),
                        "size": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                    for path in files
                ],
            }
        )
    gate = read_json(review_dir / "paper" / "audit" / "publication-gate.json")
    evidence = read_json(review_dir / "paper" / "audit" / "evidence-coverage.json")
    return {
        "schema_version": DELIVERY_SCHEMA,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "review": {
            "title": review_title(review_dir),
            "workspace_name": review_dir.name,
        },
        "status": str(gate.get("status") or "in_progress"),
        "metrics": {
            "master_records": read_csv_count(review_dir / "records" / "master-records.csv"),
            "full_text_decisions": read_csv_count(review_dir / "screening" / "full-text.csv"),
            "focal_studies": read_csv_count(review_dir / "extraction" / "extraction-table.csv"),
            "critical_claims": evidence.get("critical_claims", 0),
            "critical_claims_located": evidence.get("critical_located", 0),
            **pipeline_summary(review_dir),
        },
        "categories": categories,
        "closure_rule": (
            "Una revisión solo se cierra cuando están completos el manuscrito científico, "
            "la trazabilidad de la evidencia, los controles editoriales y la entrega portátil. "
            "Un PDF por sí solo no es suficiente."
        ),
    }


def format_bytes(value: int) -> str:
    """Render a compact byte count for the HTML cards."""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def render_html(manifest: dict[str, Any], *, link_prefix: str = "") -> str:
    """Render a standalone guide with no external fonts, scripts, or trackers."""
    title = html.escape(str(manifest["review"]["title"]))
    raw_status = str(manifest.get("status") or "in_progress").lower()
    status = html.escape(
        {
            "pass": "APROBADO",
            "fail": "BLOQUEADO",
            "in_progress": "EN CURSO",
        }.get(raw_status, raw_status.upper())
    )
    metrics = manifest.get("metrics") or {}
    cards: list[str] = []
    for category in manifest.get("categories") or []:
        category_status = str(category.get("status") or "missing")
        category_status_label = {
            "complete": "COMPLETO",
            "partial": "PARCIAL",
            "missing": "AUSENTE",
        }.get(category_status, category_status.upper())
        start_path = str(category.get("start_path") or "")
        link = html.escape(link_prefix + start_path)
        open_link = (
            f'<a class="open" href="{link}">Abrir punto de entrada</a>'
            if start_path
            else '<span class="open disabled">Sin archivo disponible</span>'
        )
        missing = category.get("required_missing") or []
        missing_html = (
            "<p class=\"missing\">Falta: " + html.escape(", ".join(missing)) + "</p>"
            if missing
            else "<p class=\"complete-note\">Contrato mínimo completo.</p>"
        )
        cards.append(
            f"""
            <article class="deliverable {html.escape(category_status)}">
              <div class="card-top">
                <span class="number">{html.escape(str(category.get("number")))}</span>
                <span class="state">{html.escape(category_status_label)}</span>
              </div>
              <h3>{html.escape(str(category.get("title")))}</h3>
              <p>{html.escape(str(category.get("description")))}</p>
              <div class="card-meta">
                <strong>{int(category.get("file_count") or 0)} archivos</strong>
                <span>{format_bytes(int(category.get("byte_count") or 0))}</span>
              </div>
              {missing_html}
              {open_link}
            </article>
            """
        )
    generated = html.escape(str(manifest.get("generated_at") or ""))
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' fill='%2311110f'/%3E%3Cpath d='M14 13h10v14h16V13h10v38H40V37H24v14H14z' fill='%23f7dc68'/%3E%3C/svg%3E">
  <title>Guía de entrega · {title}</title>
  <style>
    :root {{
      --ink:#20201d; --paper:#fbfaf6; --white:#ffffff; --muted:#66645d;
      --rule:#c9c7bf; --accent:#173f63; --complete:#e9f0e8; --partial:#f6efd9; --missing:#f5e4e1;
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; color:var(--ink); background:var(--paper); font-family:Georgia,"Times New Roman",serif; }}
    a {{ color:var(--accent); }}
    .shell {{ width:min(1420px, calc(100% - 40px)); margin:0 auto; }}
    header {{ padding:42px 0 22px; }}
    .strap {{
      display:flex; justify-content:space-between; gap:20px; padding:0 0 12px;
      color:var(--muted); border-bottom:1px solid var(--ink);
      font:600 12px/1.2 ui-sans-serif,sans-serif; letter-spacing:.1em; text-transform:uppercase;
    }}
    h1 {{ max-width:1160px; margin:30px 0 16px; font-size:clamp(40px,6vw,82px); line-height:1.01; font-weight:500; }}
    .lead {{ max-width:900px; margin:0; color:var(--muted); font-size:clamp(18px,2vw,24px); line-height:1.45; }}
    .dashboard {{ display:grid; grid-template-columns:1.3fr repeat(4,1fr); margin:34px 0 24px; border:1px solid var(--rule); background:var(--white); }}
    .metric {{ min-height:112px; padding:18px; border-right:1px solid var(--rule); }}
    .metric:last-child {{ border-right:0; }}
    .metric:first-child {{ background:#eef3f7; }}
    .metric span {{ display:block; color:var(--muted); font:600 11px/1.2 ui-sans-serif,sans-serif; letter-spacing:.07em; text-transform:uppercase; }}
    .metric strong {{ display:block; margin-top:18px; font-size:clamp(25px,3vw,42px); line-height:1; font-weight:500; }}
    .route {{ display:grid; grid-template-columns:repeat(4,1fr); margin:24px 0 36px; border-top:1px solid var(--ink); border-bottom:1px solid var(--ink); }}
    .route div {{ min-height:124px; padding:19px; border-right:1px solid var(--rule); }}
    .route div:last-child {{ border-right:0; }}
    .route b {{ display:block; margin-bottom:10px; font-size:21px; font-weight:500; }}
    section {{ padding:34px 0 58px; }}
    .section-head {{ display:flex; justify-content:space-between; align-items:end; gap:20px; margin-bottom:20px; }}
    h2 {{ margin:0; font-size:clamp(32px,4vw,52px); font-weight:500; }}
    .section-head p {{ max-width:570px; margin:0; color:var(--muted); font-size:17px; line-height:1.5; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:20px; }}
    .deliverable {{ display:flex; flex-direction:column; min-height:340px; padding:20px; border:1px solid var(--rule); background:var(--white); }}
    .deliverable.complete {{ border-top:4px solid #657d62; }}
    .deliverable.partial {{ border-top:4px solid #a58436; }}
    .deliverable.missing {{ border-top:4px solid #9b5148; }}
    .card-top {{ display:flex; justify-content:space-between; align-items:center; }}
    .number {{ color:var(--muted); font-size:38px; font-weight:500; }}
    .state {{ padding:6px 8px; border:1px solid var(--rule); background:var(--complete); font:600 10px/1 ui-sans-serif,sans-serif; letter-spacing:.05em; }}
    .deliverable.partial .state {{ background:var(--partial); }}
    .deliverable.missing .state {{ background:var(--missing); }}
    h3 {{ margin:18px 0 8px; font-size:26px; font-weight:500; }}
    .deliverable p {{ font-size:16px; line-height:1.5; }}
    .card-meta {{ display:flex; justify-content:space-between; margin-top:auto; padding-top:20px; border-top:1px solid var(--rule); }}
    .missing,.complete-note {{ color:var(--muted); font:600 12px/1.4 ui-sans-serif,sans-serif; }}
    .open {{ display:block; margin-top:14px; padding:11px; text-align:center; text-decoration:none; font:600 13px/1 ui-sans-serif,sans-serif; border:1px solid var(--accent); }}
    .open:hover, .open:focus {{ color:white; background:var(--accent); }}
    .open.disabled {{ color:var(--muted); border-color:var(--rule); cursor:not-allowed; }}
    .rule {{ margin:10px 0 64px; padding:24px 0; border-top:1px solid var(--ink); border-bottom:1px solid var(--ink); font-size:clamp(20px,2.3vw,30px); line-height:1.35; }}
    footer {{ display:flex; justify-content:space-between; gap:20px; padding:18px 0 28px; border-top:1px solid var(--ink); color:var(--muted); font:12px/1.4 ui-sans-serif,sans-serif; }}
    @media (max-width:980px) {{
      .dashboard {{ grid-template-columns:repeat(2,1fr); }}
      .dashboard .metric:first-child {{ grid-column:1/-1; }}
      .route {{ grid-template-columns:repeat(2,1fr); }}
      .grid {{ grid-template-columns:repeat(2,1fr); }}
    }}
    @media (max-width:650px) {{
      .shell {{ width:min(100% - 20px, 1500px); }}
      .strap, .section-head, footer {{ align-items:flex-start; flex-direction:column; }}
      .dashboard, .route, .grid {{ grid-template-columns:1fr; }}
      .deliverable {{ min-height:320px; }}
    }}
    @media print {{
      body {{ background:white; }}
      .deliverable,.metric {{ break-inside:avoid; }}
    }}
  </style>
</head>
<body>
  <header class="shell">
    <div class="strap"><span>HERMES · ENTREGA CIENTÍFICA NAVEGABLE</span><span>ESTADO {status}</span></div>
    <h1>{title}</h1>
    <p class="lead">Esta página explica qué contiene la revisión, qué está completo y dónde empezar. No hace falta interpretar una estructura de carpetas para encontrar el manuscrito, comprobar una afirmación o reutilizar los datos.</p>
    <div class="dashboard">
      <div class="metric"><span>Estado editorial</span><strong>{status}</strong></div>
      <div class="metric"><span>Corpus maestro</span><strong>{int(metrics.get("master_records") or 0)}</strong></div>
      <div class="metric"><span>Texto completo</span><strong>{int(metrics.get("full_text_decisions") or 0)}</strong></div>
      <div class="metric"><span>Síntesis focal</span><strong>{int(metrics.get("focal_studies") or 0)}</strong></div>
      <div class="metric"><span>Evidencia localizada</span><strong>{int(metrics.get("critical_claims_located") or 0)}/{int(metrics.get("critical_claims") or 0)}</strong></div>
    </div>
    <div class="route">
      <div><b>1. Leer</b>Abre primero el PDF o el Markdown canónico.</div>
      <div><b>2. Comprobar</b>Usa el ledger para viajar de una afirmación al DOI y al fragmento.</div>
      <div><b>3. Explorar</b>Navega por tablas, figuras, redes, centralidad y comunidades.</div>
      <div><b>4. Reutilizar</b>Edita LaTeX, CSV, SVG o exporta GraphML/GEXF a Gephi.</div>
    </div>
  </header>
  <main class="shell">
    <section>
      <div class="section-head">
        <h2>12 paquetes, una revisión</h2>
        <p>Cada bloque tiene un contrato mínimo. COMPLETO significa que están presentes sus archivos imprescindibles; PARCIAL señala exactamente qué falta.</p>
      </div>
      <div class="grid">{''.join(cards)}</div>
    </section>
    <div class="rule">{html.escape(str(manifest.get("closure_rule") or ""))}</div>
  </main>
  <footer class="shell">
    <span>Generado: {generated}</span>
    <span>Sin dependencias externas · Funciona offline · Manifiesto: deliverables-manifest.json</span>
  </footer>
</body>
</html>
"""


def build_delivery_assets(review_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, dict[str, Any]]:
    """Write the workspace guide and its machine-readable manifest."""
    package_dir = review_dir / "paper" / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    build_figure_gallery(review_dir)
    manifest = build_manifest(review_dir)
    manifest_path = write_json_atomic(package_dir / "deliverables-manifest.json", manifest)
    html_path = package_dir / "index.html"
    html_path.write_text(render_html(manifest, link_prefix="../../"), encoding="utf-8")
    return html_path, manifest_path, manifest
