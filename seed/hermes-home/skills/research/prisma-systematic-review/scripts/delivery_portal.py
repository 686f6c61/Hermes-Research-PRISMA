"""Portable HTML guide and manifest for a complete review delivery."""

from __future__ import annotations

import csv
import html
import json
import pathlib
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
        "description": "Incluye evaluación crítica, sensibilidad, redes, comunidades y datos estructurales.",
        "patterns": [
            "analysis/manifest.json",
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
            "figures/*.md",
            "figures/png/*",
            "figures/svg/*",
            "tables/*.csv",
            "tables/*.md",
        ],
        "required": ["figures/manifest.csv", "figures/paper-figures-spec.csv", "tables/paper-tables-spec.csv"],
        "start": "figures/manifest.csv",
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
        "patterns": ["notes/runtime-state.*", "notes/pipeline-state.json", "notes/job-ledger.json"],
        "required": ["notes/pipeline-state.json"],
        "start": "notes/pipeline-state.json",
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
        and ".DS_Store" not in path.parts
        and path.name not in {"publication-package.zip"}
    )


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
      --ink:#11110f; --paper:#f3eee5; --white:#fffdf8; --yellow:#f7dc68;
      --blue:#c6d7f4; --green:#cfe4c8; --pink:#f1c9c1; --muted:#706b63;
      --border:3px solid var(--ink); --shadow:7px 7px 0 var(--ink);
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0; color:var(--ink); background:
      linear-gradient(90deg, rgba(17,17,15,.045) 1px, transparent 1px),
      linear-gradient(rgba(17,17,15,.045) 1px, transparent 1px), var(--paper);
      background-size:28px 28px; font-family:"Arial Narrow","Helvetica Neue",sans-serif;
    }}
    a {{ color:inherit; }}
    .shell {{ width:min(1500px, calc(100% - 36px)); margin:0 auto; }}
    header {{ padding:28px 0 18px; }}
    .strap {{
      display:flex; justify-content:space-between; gap:20px; padding:10px 14px;
      color:var(--paper); background:var(--ink); font:700 13px/1.2 ui-monospace,monospace;
      letter-spacing:.08em; text-transform:uppercase;
    }}
    h1 {{ max-width:1150px; margin:28px 0 14px; font-size:clamp(42px,7vw,104px); line-height:.9; letter-spacing:-.055em; }}
    .lead {{ max-width:900px; margin:0; font-size:clamp(19px,2vw,29px); line-height:1.25; }}
    .dashboard {{ display:grid; grid-template-columns:1.4fr repeat(4,1fr); gap:14px; margin:28px 0; }}
    .metric {{ min-height:116px; padding:16px; background:var(--white); border:var(--border); box-shadow:4px 4px 0 var(--ink); }}
    .metric:first-child {{ background:var(--yellow); }}
    .metric span {{ display:block; font:700 11px/1.2 ui-monospace,monospace; letter-spacing:.06em; text-transform:uppercase; }}
    .metric strong {{ display:block; margin-top:16px; font-size:clamp(26px,3vw,48px); line-height:.9; }}
    .route {{ display:grid; grid-template-columns:repeat(4,1fr); border:var(--border); margin:34px 0; background:var(--ink); gap:3px; }}
    .route div {{ min-height:140px; padding:18px; background:var(--white); }}
    .route div:nth-child(2) {{ background:var(--blue); }}
    .route div:nth-child(3) {{ background:var(--green); }}
    .route div:nth-child(4) {{ background:var(--pink); }}
    .route b {{ display:block; font-size:22px; margin-bottom:10px; }}
    section {{ padding:24px 0 58px; }}
    .section-head {{ display:flex; justify-content:space-between; align-items:end; gap:20px; margin-bottom:20px; }}
    h2 {{ margin:0; font-size:clamp(32px,4vw,64px); letter-spacing:-.04em; }}
    .section-head p {{ max-width:530px; margin:0; font-size:17px; line-height:1.35; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:20px; }}
    .deliverable {{ display:flex; flex-direction:column; min-height:365px; padding:18px; border:var(--border); box-shadow:var(--shadow); background:var(--white); }}
    .deliverable:nth-child(4n+1) {{ background:var(--yellow); }}
    .deliverable:nth-child(4n+2) {{ background:var(--blue); }}
    .deliverable:nth-child(4n+3) {{ background:var(--green); }}
    .deliverable:nth-child(4n+4) {{ background:var(--pink); }}
    .card-top {{ display:flex; justify-content:space-between; align-items:center; }}
    .number {{ font-size:48px; font-weight:900; letter-spacing:-.08em; }}
    .state {{ padding:7px 9px; color:var(--paper); background:var(--ink); font:700 11px/1 ui-monospace,monospace; }}
    .deliverable.partial .state {{ color:var(--ink); background:var(--paper); border:2px solid var(--ink); }}
    .deliverable.missing .state {{ color:var(--ink); background:var(--pink); border:2px solid var(--ink); }}
    h3 {{ margin:18px 0 8px; font-size:28px; letter-spacing:-.025em; }}
    .deliverable p {{ font-size:17px; line-height:1.4; }}
    .card-meta {{ display:flex; justify-content:space-between; margin-top:auto; padding-top:20px; border-top:2px solid var(--ink); }}
    .missing {{ font:700 12px/1.35 ui-monospace,monospace; }}
    .complete-note {{ font:700 12px/1.35 ui-monospace,monospace; }}
    .open {{ display:block; margin-top:14px; padding:12px; text-align:center; text-decoration:none; font-weight:900; border:2px solid var(--ink); background:var(--white); }}
    .open:hover, .open:focus {{ color:var(--paper); background:var(--ink); }}
    .open.disabled {{ color:var(--muted); background:transparent; cursor:not-allowed; }}
    .rule {{ margin:10px 0 64px; padding:24px; color:var(--paper); background:var(--ink); border:var(--border); font-size:clamp(20px,2.3vw,34px); line-height:1.2; }}
    footer {{ display:flex; justify-content:space-between; gap:20px; padding:18px 0 28px; border-top:3px solid var(--ink); font:12px/1.4 ui-monospace,monospace; }}
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
      .deliverable, .metric {{ box-shadow:none; break-inside:avoid; }}
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
    manifest = build_manifest(review_dir)
    manifest_path = write_json_atomic(package_dir / "deliverables-manifest.json", manifest)
    html_path = package_dir / "index.html"
    html_path.write_text(render_html(manifest, link_prefix="../../"), encoding="utf-8")
    return html_path, manifest_path, manifest
