#!/usr/bin/env python3
"""Create paper figures derived from the review corpus and register them in the manifest."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import unicodedata
from collections import Counter, defaultdict

SPEC_FIELDS = [
    "figure_id",
    "paper_section",
    "figure_type",
    "purpose",
    "evidence_basis",
    "style_profile",
    "apa_caption",
    "recommended_status",
    "notes",
]

MANIFEST_FIELDS = [
    "figure_id",
    "title",
    "phase",
    "paper_section",
    "figure_type",
    "purpose",
    "evidence_basis",
    "style_profile",
    "apa_caption",
    "svg_path",
    "png_path",
    "status",
    "notes",
]

RANK_FIELDS = [
    "rank",
    "figure_id",
    "title",
    "style_profile",
    "paper_section",
    "figure_type",
    "score_total",
    "score_method",
    "score_substantive",
    "score_empirical_density",
    "score_nonredundancy",
    "score_traceability",
    "recommendation",
    "rationale",
]

FIGURE_GATE_FIELDS = [
    "figure_id",
    "section",
    "claim",
    "data_source",
    "denominator",
    "why_visual",
    "table_alternative",
    "redundancy_score",
    "scientific_value",
    "legibility_score",
    "decision",
]

MAIN_BODY_FIGURE_LIMIT = 4
INTERNAL_PROCESS_FIGURES = {
    "prisma-flow",
    "fig-publication-workflow",
    "fig-autopilot-evidence-traceability",
}

TASK_CATEGORIES = [
    ("Testing y QA", ["testing", "test", "quality assurance", "qa", "self-testing"]),
    ("Seguridad y fuzzing", ["security", "fuzz", "vulnerability", "penetration", "audit", "malicious"]),
    ("Benchmarking y evaluación", ["benchmark", "evaluation", "judge", "metric", "readiness"]),
    ("Code review y repositorios", ["code review", "repository", "repo", "pull request", "commit"]),
    ("Depuración y diagnóstico", ["debug", "bug", "failure", "root cause", "diagnosis"]),
    ("Workflow y automatización", ["workflow", "automation", "pipeline", "orchestration"]),
    ("Requirements y diseño", ["requirements", "design", "architecture", "software design"]),
]

PATTERN_CATEGORIES = [
    ("Orquestación y routing", ["orchestration", "orchestrator", "routing", "router", "supervisor"]),
    ("Multiagente modular", ["multi-agent", "multi agent", "sub-agent", "role", "specialization"]),
    ("Revisión y verificación", ["review", "verification", "verifier", "audit", "traceable"]),
    ("Herramientas y evaluación", ["tool", "benchmark", "judge", "metric", "harness"]),
]

GENERIC_THEME_CATEGORIES = [
    ("Prototipos y sistemas", ["prototype", "proof of concept", "system", "implementation", "deployment"]),
    ("RAG y recuperación", ["rag", "retrieval", "knowledge base", "vector", "embedding", "document"]),
    ("Agentes conversacionales", ["chatbot", "conversation", "conversational", "assistant", "dialog"]),
    ("Automatización de procesos", ["workflow", "automation", "process", "orchestration", "coordination"]),
    ("Evaluación y benchmarks", ["evaluation", "benchmark", "metric", "readiness", "failure", "validation"]),
    ("Dominios aplicados", ["health", "education", "business", "university", "service", "industry", "music"]),
]

GENERIC_PATTERN_CATEGORIES = [
    ("Orquestación explícita", ["orchestration", "orchestrator", "workflow", "routing", "supervisor"]),
    ("Multiagente y roles", ["multi-agent", "multi agent", "agent to agent", "a2a", "role", "specialization"]),
    ("Herramientas e integración", ["tool", "api", "function", "integration", "database", "retrieval"]),
    ("Memoria y contexto", ["memory", "context", "knowledge base", "vector", "embedding", "rag"]),
    ("Verificación y evaluación", ["verification", "validation", "evaluation", "benchmark", "metric", "audit"]),
]

AUTOPILOT_SYNTHESIS_SPEC = {
    "figure_id": "fig-autopilot-synthesis-bridge",
    "paper_section": "Resultados",
    "figure_type": "synthesis-diagram",
    "purpose": "Sintetizar en un diagrama único la relación entre corpus, patrones arquitectónicos y señal empírica cuando la revisión ya tiene suficiente densidad comparativa.",
    "evidence_basis": "selection/ultraquality-shortlist.csv, extraction/extraction-table.csv, flow-counts.csv",
    "style_profile": "monochrome-academic",
    "apa_caption": "Figura adicional. Diagrama de síntesis entre corpus, patrones arquitectónicos y señal empírica.",
    "recommended_status": "planned",
    "notes": "Autogenerada por autopilot cuando la revisión necesita una figura extra de síntesis comparativa.",
}

AUTOPILOT_TRACEABILITY_SPEC = {
    "figure_id": "fig-autopilot-evidence-traceability",
    "paper_section": "Discusión",
    "figure_type": "workflow-diagram",
    "purpose": "Mostrar la cadena de trazabilidad desde PDFs, figuras/tablas extraídas y matrices hasta las afirmaciones del manuscrito final.",
    "evidence_basis": "fulltext/pdf, figures/evidence-manifest.csv, tables/evidence-manifest.csv, paper/manuscript/publication-ready.md",
    "style_profile": "monochrome-academic",
    "apa_caption": "Figura adicional. Cadena de trazabilidad entre corpus PDF, evidencia extraída y afirmaciones del manuscrito.",
    "recommended_status": "planned",
    "notes": "Autogenerada por autopilot cuando la revisión acumula suficiente evidencia visual/tabular fuente.",
}

AUTOPILOT_TAXONOMY_SPEC = {
    "figure_id": "fig-autopilot-architecture-taxonomy",
    "paper_section": "Resultados",
    "figure_type": "taxonomy-diagram",
    "purpose": "Organizar el corpus focal en una taxonomía operativa de familias arquitectónicas, componentes dominantes y tareas de ingeniería.",
    "evidence_basis": "selection/ultraquality-shortlist.csv, extraction/extraction-table.csv, figures/evidence-manifest.csv",
    "style_profile": "monochrome-academic",
    "apa_caption": "Figura adicional. Taxonomía operativa de familias arquitectónicas y componentes del corpus focal.",
    "recommended_status": "planned",
    "notes": "Autogenerada por autopilot cuando la review de software necesita una síntesis taxonómica más explícita.",
}

AUTOPILOT_TIMELINE_SPEC = {
    "figure_id": "fig-autopilot-timeline-evolution",
    "paper_section": "Resultados",
    "figure_type": "timeline-diagram",
    "purpose": "Representar la evolución temporal del corpus cuando la revisión cubre varios años o una secuencia de maduración visible.",
    "evidence_basis": "selection/ultraquality-shortlist.csv, records/master-records.csv, flow-counts.csv",
    "style_profile": "monochrome-academic",
    "apa_caption": "Figura adicional. Evolución temporal del corpus focal y sus patrones dominantes.",
    "recommended_status": "planned",
    "notes": "Autogenerada por autopilot cuando la review cubre varios años y conviene una lectura temporal.",
}

AUTOPILOT_PERSONALITY_FLOW_SPEC = {
    "figure_id": "fig-autopilot-construct-flow",
    "paper_section": "Resultados",
    "figure_type": "construct-flow",
    "purpose": "Sintetizar el flujo entre medición de rasgos, steering de persona y efectos downstream en la literatura sobre personalidad en LLMs.",
    "evidence_basis": "selection/ultraquality-shortlist.csv, extraction/extraction-table.csv, figures/evidence-manifest.csv",
    "style_profile": "monochrome-academic",
    "apa_caption": "Figura adicional. Flujo entre constructos, steering y efectos downstream en el corpus focal.",
    "recommended_status": "planned",
    "notes": "Autogenerada por autopilot cuando la review es sobre personalidad en LLMs.",
}

ANALYTICAL_GRAMMAR_SPEC = {
    "figure_id": "fig-analytical-grammar",
    "paper_section": "Discusión",
    "figure_type": "contribution-model",
    "purpose": "Sintetizar la unidad de comparación, la gramática analítica, las condiciones de comparabilidad y la agenda científica que emergen de la revisión.",
    "evidence_basis": "extraction/extraction-table.csv, selection/ultraquality-shortlist.csv, paper/manuscript/publication-ready.md",
    "style_profile": "analytic-grayscale",
    "apa_caption": "Figura adicional. Modelo interpretativo de la gramática analítica propuesta por la revisión.",
    "recommended_status": "main_body",
    "notes": "Figura de aportación: debe cerrar el argumento científico y no describir el pipeline interno.",
}

CORE_FIGURE_SPECS = [
    {
        "figure_id": "fig-review-architecture",
        "paper_section": "Método",
        "figure_type": "review-architecture",
        "purpose": "Explicar cómo se conectan protocolo, búsqueda, texto completo, extracción, síntesis y auditoría editorial.",
        "evidence_basis": "protocol/intake.md, searches/search-log.csv, screening/full-text.csv, extraction/extraction-table.csv",
        "style_profile": "process-blueprint",
        "apa_caption": "Figura 1. Arquitectura operativa de revisión.",
        "recommended_status": "main_body",
        "notes": "Figura metodológica obligatoria: sustituye el exceso de énfasis visual en PRISMA por la arquitectura reproducible de la revisión.",
    },
    {
        "figure_id": "fig-corpus-map",
        "paper_section": "Resultados",
        "figure_type": "corpus-map",
        "purpose": "Mostrar la composición del corpus por tipo de trabajo, fuente y señal empírica.",
        "evidence_basis": "selection/ultraquality-shortlist.csv, extraction/extraction-table.csv, searches/search-log.csv",
        "style_profile": "analytic-grayscale",
        "apa_caption": "Figura 2. Mapa del corpus incluido por tipo de trabajo, fuente y diseño empírico.",
        "recommended_status": "main_body",
        "notes": "Figura sustantiva base para leer qué clase de evidencia sostiene la síntesis focal.",
    },
    {
        "figure_id": "fig-theme-landscape",
        "paper_section": "Resultados",
        "figure_type": "theme-landscape",
        "purpose": "Visualizar temas, métodos y focos analíticos del corpus sin imponer una taxonomía cerrada.",
        "evidence_basis": "selection/ultraquality-shortlist.csv, extraction/extraction-table.csv",
        "style_profile": "analytic-grayscale",
        "apa_caption": "Figura 3. Panorama temático y metodológico del corpus final.",
        "recommended_status": "main_body",
        "notes": "Figura sustantiva base para detectar concentración, dispersión y huecos temáticos.",
    },
    {
        "figure_id": "fig-agent-task-matrix",
        "paper_section": "Resultados",
        "figure_type": "matrix",
        "purpose": "Relacionar temas dominantes con patrones metodológicos y resultados observados del corpus.",
        "evidence_basis": "selection/ultraquality-shortlist.csv, extraction/extraction-table.csv",
        "style_profile": "analytic-grayscale",
        "apa_caption": "Figura 4. Matriz entre temas, métodos y resultados observados.",
        "recommended_status": "main_body",
        "notes": "Figura sustantiva base para evitar tablas con ceros excesivos y mostrar solo cruces con señal empírica.",
    },
    {
        "figure_id": "fig-method-profile",
        "paper_section": "Resultados",
        "figure_type": "method-profile",
        "purpose": "Comparar diseño empírico, criterios reportados y vacíos que limitan la comparabilidad metodológica.",
        "evidence_basis": "selection/ultraquality-shortlist.csv, extraction/extraction-table.csv",
        "style_profile": "analytic-grayscale",
        "apa_caption": "Figura 5. Mapa de comparabilidad metodológica de los estudios empíricos incluidos.",
        "recommended_status": "main_body",
        "notes": "Figura sustantiva base para separar diseño, método, muestra y trazabilidad de reporte.",
    },
    ANALYTICAL_GRAMMAR_SPEC,
]

PERSONALITY_THEME_CATEGORIES = [
    ("Constructos y teorías", ["big five", "ocean", "mbti", "hexaco", "trait", "traits", "psychometric"]),
    ("Assessment y profiling", ["assessment", "profil", "questionnaire", "validation", "benchmark", "ranking", "classification"]),
    ("Persona steering y control", ["persona", "role-play", "role playing", "steering", "slider", "control", "adaptation", "activation"]),
    ("Interacción y alineamiento", ["interaction", "conversation", "preference", "alignment", "self-concept", "tutor", "assistive", "dispute"]),
    ("Sesgo y seguridad", ["bias", "jailbreak", "risk", "moral", "fairness", "debunking"]),
]

PERSONALITY_PATTERN_CATEGORIES = [
    ("Medición y validación", ["assessment", "profil", "questionnaire", "validation", "benchmark", "ranking", "classification"]),
    ("Steering e inferencia", ["steering", "slider", "activation", "control", "adaptation", "decoding"]),
    ("Persona y role-play", ["persona", "role-play", "role playing"]),
    ("Efectos humanos", ["interaction", "preference", "alignment", "self-concept", "conversation", "tutor"]),
    ("Sesgo y riesgo", ["bias", "jailbreak", "risk", "moral", "fairness", "debunking"]),
]

CREATIVITY_THEME_CATEGORIES = [
    ("Escritura creativa", ["creative writing", "story", "narrative", "poem", "poetry", "fiction"]),
    ("Pensamiento divergente", ["divergent thinking", "alternative uses", "aut", "fluency", "flexibility", "elaboration"]),
    ("Originalidad y novedad", ["originality", "originalidad", "novelty", "novedad", "surprise", "usefulness"]),
    ("Resolución creativa", ["creative problem solving", "problem solving", "innovation", "ideation", "ideacion", "ideación"]),
    ("Evaluación humano-modelo", ["human evaluation", "human ratings", "rater", "judge", "expert", "comparison"]),
    ("Benchmarks y métricas", ["benchmark", "dataset", "metric", "evaluation", "scoring", "rubric", "torrance", "ttct"]),
]

CREATIVITY_PATTERN_CATEGORIES = [
    ("Prompting y condiciones", ["prompt", "prompting", "temperature", "condition", "instruction", "few-shot", "zero-shot"]),
    ("Evaluación humana", ["human evaluation", "human ratings", "expert", "rater", "participants", "survey"]),
    ("Evaluación automática", ["automatic", "automated", "metric", "embedding", "classifier", "judge", "llm-as-a-judge"]),
    ("Comparación de modelos", ["gpt", "claude", "gemini", "llama", "mistral", "qwen", "chatgpt", "models"]),
    ("Instrumentos creativos", ["torrance", "ttct", "alternative uses", "remote associates", "creativity test"]),
]

STYLE_PRESETS = {
    "systematic-selection-flow": {
        "bg": "#ffffff",
        "panel_fill": "#ffffff",
        "panel_stroke": "#111111",
        "title": "#111111",
        "subtitle": "#4a4a4a",
        "label": "#111111",
        "body": "#222222",
        "small": "#444444",
        "axis": "#111111",
        "grid": "#dcdcdc",
        "bar": "#414141",
        "bar2": "#8a8a8a",
        "box_fill": "#fbfbfb",
        "box_stroke": "#111111",
        "cell1": "#e4e4e4",
        "cell2": "#c7c7c7",
        "cell3": "#878787",
        "cell4": "#3f3f3f",
        "arrow": "#111111",
        "panel_dash": "none",
        "box_rx": "10",
        "panel_rx": "12",
    },
    "analytic-grayscale": {
        "bg": "#ffffff",
        "panel_fill": "#ffffff",
        "panel_stroke": "#111111",
        "title": "#111111",
        "subtitle": "#4a4a4a",
        "label": "#111111",
        "body": "#222222",
        "small": "#444444",
        "axis": "#111111",
        "grid": "#d8d8d8",
        "bar": "#414141",
        "bar2": "#8a8a8a",
        "box_fill": "#fbfbfb",
        "box_stroke": "#111111",
        "cell1": "#e4e4e4",
        "cell2": "#c7c7c7",
        "cell3": "#878787",
        "cell4": "#3f3f3f",
        "arrow": "#111111",
        "panel_dash": "none",
        "box_rx": "10",
        "panel_rx": "12",
    },
    "behavioral-academic": {
        "bg": "#ffffff",
        "panel_fill": "#ffffff",
        "panel_stroke": "#202020",
        "title": "#161616",
        "subtitle": "#585858",
        "label": "#202020",
        "body": "#2a2a2a",
        "small": "#5c5c5c",
        "axis": "#202020",
        "grid": "#dbdbdb",
        "bar": "#515151",
        "bar2": "#9c9c9c",
        "box_fill": "#fdfdfd",
        "box_stroke": "#202020",
        "cell1": "#e7e7e7",
        "cell2": "#cccccc",
        "cell3": "#8d8d8d",
        "cell4": "#494949",
        "arrow": "#202020",
        "panel_dash": "none",
        "box_rx": "12",
        "panel_rx": "12",
    },
    "process-blueprint": {
        "bg": "#ffffff",
        "panel_fill": "#fcfcfc",
        "panel_stroke": "#1d1d1d",
        "title": "#111111",
        "subtitle": "#505050",
        "label": "#111111",
        "body": "#222222",
        "small": "#4b4b4b",
        "axis": "#1d1d1d",
        "grid": "#cfcfcf",
        "bar": "#333333",
        "bar2": "#747474",
        "box_fill": "#f4f4f4",
        "box_stroke": "#1d1d1d",
        "cell1": "#e0e0e0",
        "cell2": "#c4c4c4",
        "cell3": "#7f7f7f",
        "cell4": "#393939",
        "arrow": "#1d1d1d",
        "panel_dash": "5 4",
        "box_rx": "14",
        "panel_rx": "16",
    },
    "supplementary-evidence": {
        "bg": "#ffffff",
        "panel_fill": "#ffffff",
        "panel_stroke": "#4f4f4f",
        "title": "#111111",
        "subtitle": "#5a5a5a",
        "label": "#111111",
        "body": "#2b2b2b",
        "small": "#5a5a5a",
        "axis": "#4f4f4f",
        "grid": "#e2e2e2",
        "bar": "#5b5b5b",
        "bar2": "#9b9b9b",
        "box_fill": "#ffffff",
        "box_stroke": "#4f4f4f",
        "cell1": "#ebebeb",
        "cell2": "#d4d4d4",
        "cell3": "#989898",
        "cell4": "#505050",
        "arrow": "#4f4f4f",
        "panel_dash": "3 3",
        "box_rx": "8",
        "panel_rx": "10",
    },
}


def read_research_context(review_dir: pathlib.Path) -> dict[str, str]:
    intake = review_dir / "protocol" / "intake.md"
    text = intake.read_text(encoding="utf-8", errors="ignore") if intake.exists() else ""
    def parse(label: str) -> str:
        import re
        match = re.search(rf"^- {label}:\s*(.*)$", text, flags=re.MULTILINE)
        return (match.group(1) if match else "").strip()
    target_outlet = (
        parse("Revista o medio objetivo \\(opcional; si se omite, o si solo indicas una familia temática amplia, Hermes usa `generic-common-core`\\)")
        or parse("Revista o medio objetivo \\(opcional; si se omite, Hermes usa `generic-common-core`\\)")
        or parse("Revista objetivo \\(opcional\\)")
    )
    return {
        "topic": parse("Tema"),
        "research_question": parse("Pregunta de investigación \\(opcional\\)"),
        "years": parse("Año o años"),
        "date_start": parse("Fecha inicial \\(opcional\\)"),
        "date_end": parse("Fecha final \\(opcional\\)"),
        "inclusion": parse("Criterios de inclusión"),
        "exclusion": parse("Criterios de exclusión"),
        "target_journal": target_outlet,
    }


def read_review_mode_playbook(review_dir: pathlib.Path) -> dict[str, object]:
    path = review_dir / "protocol" / "review-mode.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def detect_review_profile(context: dict[str, str]) -> str:
    blob = normalize(" ".join(context.values()))
    personality_tokens = (
        "personalidad",
        "persona",
        "trait",
        "traits",
        "mbti",
        "big five",
        "hexaco",
        "psychometric",
        "profiling",
        "perfil",
    )
    reasoning_model_tokens = (
        "llm",
        "llms",
        "large language model",
        "language model",
        "modelo de lenguaje",
        "modelos de lenguaje",
        "reasoning model",
        "reasoning models",
        "reasoning llm",
        "reasoning llms",
        "modelo razonador",
        "modelos razonadores",
        "modelos de ia razonadores",
        "modelo de ia razonador",
        "razonadores",
        "razonador",
        "ia razonador",
        "ia razonadores",
    )
    creativity_tokens = (
        "creatividad",
        "creativity",
        "creative",
        "creativo",
        "creativa",
        "criatividade",
        "divergent thinking",
        "pensamiento divergente",
        "creative writing",
        "originality",
        "originalidad",
        "novelty",
        "novedad",
        "ideation",
        "ideacion",
        "ideación",
    )
    ai_architecture_tokens = (
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
    )
    broad_ai_tokens = (
        "ia",
        "ai",
        "llm",
        "large language model",
        "modelo de lenguaje",
        "agent",
        "agente",
        "rag",
        "foundation model",
        "modelos fundacionales",
    )
    if any(token in blob for token in personality_tokens) and any(token in blob for token in reasoning_model_tokens):
        return "personality_llm"
    if any(token in blob for token in creativity_tokens) and any(token in blob for token in reasoning_model_tokens + ("generative ai", "ia generativa", "chatgpt", "gpt")):
        return "creativity_llm"
    if any(token in blob for token in ("software", "code", "development", "ingenieria del software", "desarrollo de software", "debug", "testing")):
        return "software_architecture"
    if any(token in blob for token in ai_architecture_tokens) and any(token in blob for token in broad_ai_tokens):
        return "ai_architecture"
    if "agente" in blob or "agent" in blob:
        return "agent_architecture"
    return "generic"


def category_sets(profile: str) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    if profile == "personality_llm":
        return PERSONALITY_THEME_CATEGORIES, PERSONALITY_PATTERN_CATEGORIES
    if profile == "creativity_llm":
        return CREATIVITY_THEME_CATEGORIES, CREATIVITY_PATTERN_CATEGORIES
    if profile == "software_architecture":
        return TASK_CATEGORIES, PATTERN_CATEGORIES
    return GENERIC_THEME_CATEGORIES, GENERIC_PATTERN_CATEGORIES


def ensure_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path: pathlib.Path, fields: list[str] | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if fields is None:
        return rows
    return [{field: row.get(field, "") for field in fields} for row in rows]


def write_manifest(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def title_from_figure_id(figure_id: str) -> str:
    return figure_id.replace("-", " ").replace("_", " ").strip().title()


def escape_xml(text: str) -> str:
    normalized = unicodedata.normalize("NFC", str(text))
    return (
        normalized
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def wrap_text(text: str, max_len: int = 72) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        projected = length + len(word) + (1 if current else 0)
        if current and projected > max_len:
            lines.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length = projected
    if current:
        lines.append(" ".join(current))
    return lines


def multiline_svg_text(lines: list[str], x: int, y: int, line_height: int, klass: str, anchor: str = "start") -> str:
    if klass == "body":
        line_height = max(line_height, 30)
    elif klass == "small":
        line_height = max(line_height, 22)
    tspans = []
    for index, line in enumerate(lines):
        dy = "0" if index == 0 else str(line_height)
        tspans.append(f'<tspan x="{x}" dy="{dy}">{escape_xml(line)}</tspan>')
    return f'<text x="{x}" y="{y}" class="{klass}" text-anchor="{anchor}">{"".join(tspans)}</text>'


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def first_nonempty(*values: str) -> str:
    for value in values:
        if str(value or "").strip():
            return str(value).strip()
    return ""


def figure_display_label(text: str | None) -> str:
    """Return a compact, uppercase label for figure axes and panels."""
    raw = str(text or "").strip().replace("_", " ")
    normalized = normalize(raw)
    labels = {
        "empirical": "EMPÍRICO",
        "theoretical": "TEÓRICO",
        "review": "REVISIÓN",
        "other": "OTROS",
        "unclassified": "SIN CLASIFICACIÓN",
        "experimental": "EXPERIMENTAL",
        "quantitative": "CUANTITATIVO",
        "qualitative": "CUALITATIVO",
        "mixed": "MIXTO",
        "mixed methods": "MIXTO",
        "other empirical": "OTROS",
        "no reportado": "NO REPORTADO",
        "not reported": "NO REPORTADO",
        "unknown": "DESCONOCIDA",
        "openalex": "OPENALEX",
        "crossref": "CROSSREF",
        "semantic scholar": "SEMANTIC SCHOLAR",
        "semanticscholar": "SEMANTIC SCHOLAR",
        "arxiv": "ARXIV",
        "openaire": "OPENAIRE",
        "europepmc": "EUROPE PMC",
        "pubmed": "PUBMED",
        "lens": "LENS",
    }
    return labels.get(normalized, (raw or "Sin datos").upper())


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def load_selected_rows(review_dir: pathlib.Path) -> list[dict[str, str]]:
    selection = {
        row.get("record_id", ""): row
        for row in read_csv(review_dir / "selection" / "ultraquality-shortlist.csv")
        if (row.get("selected_for_final_n") or "").strip().lower() == "yes"
    }
    extraction = {
        row.get("record_id", ""): row
        for row in read_csv(review_dir / "extraction" / "extraction-table.csv")
        if row.get("record_id")
    }
    records = {
        row.get("record_id", ""): row
        for row in read_csv(review_dir / "records" / "master-records.csv")
        if row.get("record_id")
    }

    rows: list[dict[str, str]] = []
    for record_id, selection_row in selection.items():
        merged = {}
        for source in (records.get(record_id, {}), extraction.get(record_id, {}), selection_row):
            merged.update({key: value for key, value in source.items() if value not in {"", None}})
        if (merged.get("assigned_doi") or "").strip():
            rows.append(merged)

    rows.sort(key=lambda row: parse_int(row.get("ultraquality_rank"), 9999))
    return rows


def load_flow_counts(review_dir: pathlib.Path) -> dict[str, int]:
    rows = read_csv(review_dir / "prisma" / "flow-counts.csv")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("stage", "")] = parse_int(row.get("count"), 0)
    missing_doi_included = sum(
        1
        for row in read_csv(review_dir / "screening" / "full-text.csv")
        if (row.get("decision") or "").strip().lower() in {"include", "include_ft"}
        and not (row.get("assigned_doi") or "").strip()
    )
    if missing_doi_included:
        counts["included_in_review"] = max(0, counts.get("included_in_review", 0) - missing_doi_included)
        counts["full_text_excluded"] = counts.get("full_text_excluded", 0) + missing_doi_included
    return counts


def load_source_counts(review_dir: pathlib.Path) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in read_csv(review_dir / "searches" / "search-log.csv"):
        source = (row.get("source") or "unknown").strip() or "unknown"
        counter[source] += 1
    return counter


def load_evidence_asset_count(review_dir: pathlib.Path) -> int:
    return len(read_csv(review_dir / "figures" / "evidence-manifest.csv")) + len(
        read_csv(review_dir / "tables" / "evidence-manifest.csv")
    )


def review_years(context: dict[str, str], rows: list[dict[str, str]]) -> list[int]:
    years = {parse_int(value, 0) for value in __import__("re").findall(r"\b(19\d{2}|20\d{2})\b", context.get("years", ""))}
    years.update(parse_int(row.get("year"), 0) for row in rows if parse_int(row.get("year"), 0))
    return sorted(year for year in years if year)


def classify_category(blob: str, categories: list[tuple[str, list[str]]], fallback: str) -> str:
    normalized = normalize(blob)
    for label, tokens in categories:
        if any(token in normalized for token in tokens):
            return label
    return fallback


def matching_categories(blob: str, categories: list[tuple[str, list[str]]], fallback: str) -> list[str]:
    """Return all category matches so matrices show co-occurrence, not one forced label."""
    normalized = normalize(blob)
    matches = [label for label, tokens in categories if any(token in normalized for token in tokens)]
    return matches or [fallback]


def build_theme_counts(rows: list[dict[str, str]], profile: str) -> Counter[str]:
    categories, _ = category_sets(profile)
    counter: Counter[str] = Counter()
    for row in rows:
        blob = " ".join(
            [
                row.get("title_original", ""),
                row.get("abstract_original", ""),
                row.get("keywords_normalized", ""),
                row.get("keywords_author", ""),
            ]
        )
        counter[classify_category(blob, categories, "Otros temas")] += 1
    return counter


def build_pattern_counts(rows: list[dict[str, str]], profile: str) -> Counter[str]:
    _, categories = category_sets(profile)
    counter: Counter[str] = Counter()
    for row in rows:
        blob = " ".join(
            [
                row.get("title_original", ""),
                row.get("abstract_original", ""),
                row.get("method_used", ""),
                row.get("key_findings", ""),
            ]
        )
        counter[classify_category(blob, categories, "Otros patrones")] += 1
    return counter


def build_agent_task_matrix(rows: list[dict[str, str]], profile: str) -> dict[str, dict[str, int]]:
    task_categories, pattern_categories = category_sets(profile)
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        blob = " ".join(
            [
                row.get("title_original", ""),
                row.get("abstract_original", ""),
                row.get("method_used", ""),
                row.get("keywords_normalized", ""),
            ]
        )
        tasks = matching_categories(blob, task_categories, "Otros temas")
        patterns = matching_categories(blob, pattern_categories, "Otros patrones")
        for pattern in patterns:
            for task in tasks:
                matrix[pattern][task] += 1
    return matrix


def count_reported(rows: list[dict[str, str]], field: str) -> int:
    return sum(
        1
        for row in rows
        if normalize(row.get(field, "")) not in {"", "no reportado", "no reportada", "not reported"}
    )


def detect_journal_family(context: dict[str, str]) -> str:
    blob = normalize(context.get("target_journal", ""))
    if any(token in blob for token in ("comportamiento", "behavior", "human-ai", "hci", "interaction", "interaccion")):
        return "behavioral-computing"
    if any(token in blob for token in ("artificial intelligence", "inteligencia artificial", "ai journal", "machine learning")):
        return "ai-journal"
    return "generic-common-core"


def resolve_style_profile(spec: dict[str, str], profile: str, context: dict[str, str] | None = None) -> str:
    figure_id = spec.get("figure_id", "")
    requested = (spec.get("style_profile", "") or "").strip().lower()
    journal_family = detect_journal_family(context or {})
    legacy_aliases = {
        "monochrome-academic": "analytic-grayscale",
        "strict-prisma": "systematic-selection-flow",
    }
    requested = legacy_aliases.get(requested, requested)
    locked_profiles = {"systematic-selection-flow", "process-blueprint", "supplementary-evidence", "behavioral-academic"}
    if requested in locked_profiles:
        return requested
    if figure_id == "fig-review-architecture":
        return "process-blueprint"
    if figure_id in {"fig-publication-workflow", "fig-autopilot-evidence-traceability", "fig-autopilot-timeline-evolution"}:
        return "supplementary-evidence"
    if figure_id in {
        "fig-corpus-map",
        "fig-theme-landscape",
        "fig-method-profile",
        "fig-agent-task-matrix",
        "fig-autopilot-construct-flow",
        "fig-autopilot-synthesis-bridge",
        "fig-autopilot-architecture-taxonomy",
        "fig-analytical-grammar",
    }:
        if journal_family == "behavioral-computing" or profile in {"personality_llm", "creativity_llm"}:
            return "behavioral-academic"
        return "analytic-grayscale"
    if profile in {"personality_llm", "creativity_llm"} and figure_id.startswith("fig-"):
        return "behavioral-academic"
    if requested in STYLE_PRESETS:
        return requested
    return "analytic-grayscale"


def curate_specs_for_portfolio(specs: list[dict[str, str]], profile: str, context: dict[str, str]) -> list[dict[str, str]]:
    curated: list[dict[str, str]] = []
    for spec in specs:
        row = dict(spec)
        row["style_profile"] = resolve_style_profile(row, profile, context)
        figure_id = row.get("figure_id", "")
        if profile == "personality_llm" and figure_id == "fig-publication-workflow":
            row["recommended_status"] = "supplementary"
            row["notes"] = "Mantener como apoyo metodológico o anexo; no debe competir con una figura sustantiva del campo."
        curated.append(row)
    return curated


SVG_FONT_FAMILY = "'Latin Modern Roman', 'LM Roman 10', 'Latin Modern Roman 10', 'Times New Roman', serif"


def svg_frame(title: str, subtitle: str, body: str, footer: str, style_profile: str = "analytic-grayscale") -> str:
    style = STYLE_PRESETS.get(style_profile, STYLE_PRESETS["analytic-grayscale"])
    panel_dash = style["panel_dash"]
    panel_dash_css = f"stroke-dasharray: {panel_dash};" if panel_dash != "none" else ""
    subtitle_svg = multiline_svg_text(wrap_text(subtitle, 110)[:2], 72, 122, 22, "subtitle")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img">
  <defs>
    <style>
      .bg {{ fill: {style["bg"]}; }}
      .panel {{ fill: {style["panel_fill"]}; stroke: {style["panel_stroke"]}; stroke-width: 2; {panel_dash_css} }}
      .title {{ font: 700 42px {SVG_FONT_FAMILY}; fill: {style["title"]}; }}
      .subtitle {{ font: 400 22px {SVG_FONT_FAMILY}; fill: {style["subtitle"]}; }}
      .label {{ font: 700 24px {SVG_FONT_FAMILY}; fill: {style["label"]}; }}
      .body {{ font: 400 22px {SVG_FONT_FAMILY}; fill: {style["body"]}; }}
      .small {{ font: 400 18px {SVG_FONT_FAMILY}; fill: {style["small"]}; }}
      .axis {{ stroke: {style["axis"]}; stroke-width: 2; }}
      .grid {{ stroke: {style["grid"]}; stroke-width: 1; }}
      .bar {{ fill: {style["bar"]}; }}
      .bar2 {{ fill: {style["bar2"]}; }}
      .box {{ fill: {style["box_fill"]}; stroke: {style["box_stroke"]}; stroke-width: 2; rx: {style["box_rx"]}; ry: {style["box_rx"]}; }}
      .cell0 {{ fill: #ffffff; stroke: #111111; stroke-width: 1; }}
      .cell1 {{ fill: {style["cell1"]}; stroke: #111111; stroke-width: 1; }}
      .cell2 {{ fill: {style["cell2"]}; stroke: #111111; stroke-width: 1; }}
      .cell3 {{ fill: {style["cell3"]}; stroke: #111111; stroke-width: 1; }}
      .cell4 {{ fill: {style["cell4"]}; stroke: #111111; stroke-width: 1; }}
      .valueLight {{ font: 700 20px {SVG_FONT_FAMILY}; fill: #111111; }}
      .valueDark {{ font: 700 20px {SVG_FONT_FAMILY}; fill: #ffffff; }}
      .arrow {{ stroke: {style["arrow"]}; stroke-width: 2.5; fill: none; marker-end: url(#arrow); }}
    </style>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M0,0 L12,6 L0,12 z" fill="{style["arrow"]}" />
    </marker>
  </defs>
  <rect class="bg" x="0" y="0" width="1600" height="900"/>
  <rect class="panel" x="32" y="32" width="1536" height="836" rx="{style["panel_rx"]}"/>
  <text x="72" y="90" class="title">{escape_xml(title)}</text>
  {subtitle_svg}
  {body}
  <text x="72" y="836" class="small">{escape_xml(footer)}</text>
</svg>"""


def horizontal_bar_chart(items: list[tuple[str, int]], x: int, y: int, width: int, row_height: int, css_class: str = "bar") -> str:
    if not items:
        return ""
    max_value = max(value for _, value in items) or 1
    parts = [
        f'<line class="axis" x1="{x}" y1="{y - 20}" x2="{x}" y2="{y + row_height * len(items)}"/>',
        f'<line class="axis" x1="{x}" y1="{y + row_height * len(items)}" x2="{x + width}" y2="{y + row_height * len(items)}"/>',
    ]
    for index, (label, value) in enumerate(items):
        bar_width = max(4, int((value / max_value) * width))
        y_pos = y + index * row_height
        bar_start = x + 260
        parts.append(f'<text x="{x}" y="{y_pos + 18}" class="body">{escape_xml(label)}</text>')
        parts.append(f'<rect class="{css_class}" x="{bar_start}" y="{y_pos + 2}" width="{bar_width}" height="22"/>')
        if bar_width > width - 52:
            parts.append(
                f'<text x="{bar_start + bar_width - 10}" y="{y_pos + 18}" class="valueDark" text-anchor="end">{value}</text>'
            )
        else:
            parts.append(f'<text x="{bar_start + bar_width + 10}" y="{y_pos + 18}" class="valueLight">{value}</text>')
    return "".join(parts)


def render_corpus_map(review_dir: pathlib.Path, rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    work = Counter((row.get("work_type") or "other").strip().lower() or "other" for row in rows)
    source_counts = load_source_counts(review_dir)
    sources = [(figure_display_label(label), count) for label, count in source_counts.most_common(5)]
    source_total = len(source_counts)
    empirical = Counter((row.get("empirical_type") or "other").strip().lower() or "other" for row in rows if (row.get("work_type") or "").strip().lower() == "empirical")
    context = read_research_context(review_dir)
    years_label = context.get("years") or "sin rango declarado"
    work_items = [(figure_display_label(label), count) for label, count in work.most_common()]
    empirical_items = [(figure_display_label(label), count) for label, count in empirical.most_common()]
    body = [
        '<text x="80" y="180" class="label">(a) TIPO DE TRABAJO EN EL SUBCONJUNTO FOCAL</text>',
        horizontal_bar_chart(work_items, 80, 200, 360, 42, "bar"),
        '<text x="820" y="180" class="label">(b) FUENTES MÁS ACTIVAS EN LA BÚSQUEDA</text>',
        horizontal_bar_chart(sources, 820, 200, 360, 42, "bar2"),
        '<text x="80" y="520" class="label">(c) DISEÑO DE LOS ESTUDIOS EMPÍRICOS</text>',
        horizontal_bar_chart(empirical_items, 80, 540, 360, 42, "bar"),
        '<rect class="box" x="820" y="520" width="540" height="180"/>',
        '<text x="850" y="560" class="label">(d) LECTURA DEL CORPUS</text>',
        multiline_svg_text(
            [
                f"- Subconjunto focal: {len(rows)} estudios",
                f"- Estudios empíricos: {work.get('empirical', 0)}",
                f"- Fuentes activas en la búsqueda: {source_total}",
                f"- Ventana revisada: {years_label}",
            ],
            850,
            600,
            24,
            "body",
        ),
    ]
    footer = f"Base: {len(rows)} estudios del subconjunto focal y search-log.csv para la distribución de fuentes."
    subtitle = "Composición del corpus focal por tipo de trabajo, fuentes y diseño empírico."
    if profile == "personality_llm":
        subtitle = "Composición del corpus focal sobre personalidad en LLMs por tipo de trabajo, fuentes y diseño empírico."
    elif profile == "creativity_llm":
        subtitle = "Composición del corpus focal sobre creatividad en LLMs por tipo de trabajo, fuentes y diseño empírico."
    return svg_frame("Mapa del corpus", subtitle, "".join(body), footer, style_profile=style_profile)


def render_theme_landscape(rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    themes = build_theme_counts(rows, profile).most_common(7)
    patterns = build_pattern_counts(rows, profile).most_common(6)
    dominant_theme = themes[0] if themes else ("Sin tema dominante", 0)
    dominant_pattern = patterns[0] if patterns else ("Sin patron dominante", 0)
    body = [
        '<text x="80" y="180" class="label">(a) Temas dominantes</text>',
        horizontal_bar_chart(themes, 80, 200, 420, 44, "bar"),
        '<text x="860" y="180" class="label">(b) Patrones analíticos más frecuentes</text>',
        horizontal_bar_chart(patterns, 860, 200, 420, 44, "bar2"),
        '<rect class="box" x="80" y="520" width="1320" height="180"/>',
        '<text x="110" y="560" class="label">(c) Lectura comparativa</text>',
        multiline_svg_text(
            [
                f"- El constructo dominante es {dominant_theme[0]} (n={dominant_theme[1]}).",
                f"- El patrón analítico más visible es {dominant_pattern[0]} (n={dominant_pattern[1]}).",
                "- La asimetría principal del corpus está entre diseño operativo, evaluación y evidencia comparable.",
            ],
            110,
            600,
            26,
            "body",
        ),
    ]
    footer = "Clasificación heurística derivada de título, abstract, keywords, método y hallazgos del subconjunto focal."
    subtitle = "Distribución de dominios, tareas y familias arquitectónicas recurrentes."
    if profile == "personality_llm":
        subtitle = "Distribución de constructos, estrategias y focos analíticos en la literatura sobre personalidad en LLMs."
    elif profile == "creativity_llm":
        subtitle = "Distribución de tareas creativas, instrumentos y estrategias de evaluación en LLMs."
    elif profile == "generic":
        subtitle = "Distribución de temas, métodos y focos analíticos del corpus final."
    return svg_frame("Panorama temático del corpus final", subtitle, "".join(body), footer, style_profile=style_profile)


def render_method_profile(rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    empirical_rows = [row for row in rows if (row.get("work_type") or "").strip().lower() == "empirical"]
    reporting_base = empirical_rows or rows
    empirical = Counter((row.get("empirical_type") or "other").strip().lower() or "other" for row in empirical_rows)
    empirical_items = [(figure_display_label(label), count) for label, count in empirical.most_common()]

    def reported(row: dict[str, str], *fields: str) -> bool:
        return any(normalize(row.get(field, "")) not in {"", "no reportado", "no reportada", "not reported", "not specified", "no aplica", "n/a"} for field in fields)

    def invalid_sample_size(value: str) -> bool:
        normalized = normalize(value)
        normalized = re.sub(r"^n\s*=\s*", "", normalized).strip()
        return not normalized or bool(re.fullmatch(r"0+(?:[.,]0+)?|\d[,.]\d{4,}", normalized))

    def sample_reported(row: dict[str, str]) -> bool:
        return reported(row, "sample_size") and not invalid_sample_size(row.get("sample_size", ""))

    def comparator_reported(row: dict[str, str]) -> bool:
        return reported(row, "baselines_or_comparators") or has_signal(row, ("benchmark", "baseline", "compar", "control", "metric", "dataset", "evaluation"))

    def validation_reported(row: dict[str, str]) -> bool:
        value = normalize(" ".join([row.get("validation_signal", ""), row.get("limitations", "")]))
        if value and value not in {"no reportado", "not reported", "not specified"} and "no report" not in value:
            return True
        return False

    def has_signal(row: dict[str, str], tokens: tuple[str, ...]) -> bool:
        blob = normalize(
            " ".join(
                [
                    row.get("method_used", ""),
                    row.get("key_findings", ""),
                    row.get("results_summary", ""),
                    row.get("variables_dependent", ""),
                    row.get("variables_independent", ""),
                    row.get("limitations", ""),
                ]
            )
        )
        return any(token in blob for token in tokens)

    missing_sample = sum(1 for row in reporting_base if not sample_reported(row))
    missing_country = sum(1 for row in reporting_base if not reported(row, "countries", "country_or_countries"))
    missing_theory = sum(1 for row in reporting_base if not reported(row, "theory_framework"))
    missing_variables = sum(
        1
        for row in reporting_base
        if not reported(row, "variables_dependent", "variables_independent", "variables_moderators", "variables_mediators", "variables_control")
        and not has_signal(row, ("variable", "construct", "dimension", "metric", "outcome"))
    )
    missing_benchmark = sum(
        1
        for row in reporting_base
        if not comparator_reported(row)
    )
    weak_validation = sum(1 for row in reporting_base if not validation_reported(row))
    reporting = [
        ("MÉTODO", sum(1 for row in reporting_base if reported(row, "method_used"))),
        ("MUESTRA", sum(1 for row in reporting_base if sample_reported(row))),
        ("CONTEXTO", sum(1 for row in reporting_base if reported(row, "countries", "country_or_countries"))),
        ("MARCO", sum(1 for row in reporting_base if reported(row, "theory_framework"))),
        (
            "VARIABLES",
            sum(
                1
                for row in reporting_base
                if reported(row, "variables_dependent", "variables_independent", "variables_moderators", "variables_mediators", "variables_control")
                or has_signal(row, ("variable", "construct", "dimension", "metric", "outcome"))
            ),
        ),
        ("COMPARADOR", sum(1 for row in reporting_base if comparator_reported(row))),
        ("VALIDACIÓN", sum(1 for row in reporting_base if validation_reported(row))),
    ]
    body = [
        f'<text x="80" y="180" class="label">(a) DISEÑOS EMPÍRICOS (n={len(empirical_rows)})</text>',
        horizontal_bar_chart(empirical_items, 80, 200, 420, 44, "bar"),
        f'<text x="860" y="180" class="label">(b) CRITERIOS REPORTADOS (base n={len(reporting_base)})</text>',
        horizontal_bar_chart(reporting, 860, 200, 420, 40, "bar2"),
        '<rect class="box" x="80" y="500" width="1320" height="250"/>',
        '<text x="110" y="540" class="label">(c) VACÍOS QUE LIMITAN COMPARABILIDAD</text>',
        multiline_svg_text(
            [
                f"- Sin tamaño/corpus explícito: {missing_sample}",
                f"- Sin país o contexto empírico declarado: {missing_country}",
                f"- Sin marco teórico declarado: {missing_theory}",
                f"- Sin variables o dimensiones analíticas suficientes: {missing_variables}",
                f"- Sin benchmark, baseline o comparador claro: {missing_benchmark}",
                f"- Sin validación externa, replicación o prueba longitudinal fuerte: {weak_validation}",
            ],
            110,
            580,
            22,
            "body",
        ),
    ]
    footer = f"Base: {len(reporting_base)} estudios con lectura metodológica; diseños empíricos n={len(empirical_rows)}."
    subtitle = "Diseños empíricos, criterios reportados y vacíos que limitan la comparación acumulativa."
    if profile == "personality_llm":
        subtitle = "Diseños empíricos, criterios reportados y vacíos de comparabilidad en estudios sobre personalidad en LLMs."
    elif profile == "creativity_llm":
        subtitle = "Diseños empíricos, criterios reportados y vacíos de comparabilidad en estudios sobre creatividad en LLMs."
    return svg_frame("Mapa de comparabilidad metodológica", subtitle, "".join(body), footer, style_profile=style_profile)


def render_analytical_grammar_model(review_dir: pathlib.Path, rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    context = read_research_context(review_dir)
    topic = context.get("topic") or "el campo revisado"
    component_line = analytical_grammar_signal_line(rows, profile)
    if profile == "ai_architecture":
        unit = "sistema completo de IA"
        grammar = "recuperación, memoria, herramientas, orquestación, inferencia y verificación"
    elif profile == "software_architecture":
        unit = "arquitectura de agente aplicada al ciclo de software"
        grammar = "roles, repositorios, herramientas, pruebas, routing y control de fallo"
    elif profile == "personality_llm":
        unit = "configuración constructo-steering-efecto"
        grammar = "constructos, instrumentos, steering, contexto de interacción y efectos downstream"
    elif profile == "creativity_llm":
        unit = "configuración tarea-instrumento-evaluación"
        grammar = "tarea creativa, prompt, criterio de originalidad, evaluación y comparador"
    elif profile == "social_sciences":
        unit = "relación social situada"
        grammar = "constructo, mecanismo, medición, unidad, temporalidad, contexto y alcance inferencial"
    else:
        unit = "unidad analítica completa del fenómeno revisado"
        grammar = "constructos, métodos, variables, comparadores, resultados y límites"

    boxes = [
        (
            90,
            "1. UNIDAD",
            [
                f"Comparar por {unit}.",
                "No por etiqueta aislada, modelo o métrica única.",
            ],
        ),
        (
            455,
            "2. GRAMÁTICA",
            [
                f"Dimensiones: {grammar}.",
                "Comparar relaciones, no etiquetas aisladas.",
            ],
        ),
        (
            820,
            "3. COMPARABILIDAD",
            [
                "Separar certeza, señal emergente y vacío.",
                "Declarar muestra, contexto, variables, comparador y validación.",
            ],
        ),
        (
            1185,
            "4. APORTE",
            [
                "Convertir frecuencias en interpretación científica.",
                "Derivar futuras líneas desde los fallos de reporte.",
            ],
        ),
    ]
    parts: list[str] = []
    for x, label, lines in boxes:
        parts.append(f'<rect class="box" x="{x}" y="250" width="300" height="300"/>')
        parts.append(f'<text x="{x + 24}" y="292" class="label">{escape_xml(label)}</text>')
        wrapped_lines: list[str] = []
        for line in lines:
            wrapped_lines.extend(wrap_text(line, 27))
        parts.append(multiline_svg_text(wrapped_lines[:7], x + 24, 340, 24, "body"))
    parts.extend(
        [
            '<line class="arrow" x1="390" y1="385" x2="440" y2="385"/>',
            '<line class="arrow" x1="755" y1="385" x2="805" y2="385"/>',
            '<line class="arrow" x1="1120" y1="385" x2="1170" y2="385"/>',
            '<rect class="box" x="90" y="610" width="1395" height="120"/>',
            '<text x="120" y="650" class="label">Lectura de cierre</text>',
            multiline_svg_text(
                wrap_text(
                    "La revisión aporta valor cuando transforma el corpus en un modelo de comparación: qué unidad se compara, qué dimensiones explican el campo, qué evidencia sostiene la señal y qué vacíos impiden una conclusión más fuerte.",
                    115,
                ),
                120,
                690,
                22,
                "body",
            ),
            multiline_svg_text(
                wrap_text(f"Señales dominantes del corpus: {component_line}.", 120)[:2],
                120,
                765,
                20,
                "small",
            ),
        ]
    )
    footer = f"Base: {len(rows)} estudios focales; figura de aportación derivada de extracción estructurada y síntesis interpretativa."
    subtitle = f"Modelo interpretativo para convertir la revisión sobre {topic} en una gramática comparativa."
    return svg_frame("Gramática analítica de la revisión", subtitle, "".join(parts), footer, style_profile=style_profile)


def render_agent_task_matrix(rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    task_categories, pattern_categories = category_sets(profile)
    matrix = build_agent_task_matrix(rows, profile)
    all_rows = [label for label, _ in pattern_categories] + ["Otros patrones"]
    all_cols = [label for label, _ in task_categories] + ["Otros temas"]
    row_totals = {label: sum(matrix[label][col] for col in all_cols) for label in all_rows}
    col_totals = {label: sum(matrix[row][label] for row in all_rows) for label in all_cols}
    row_labels = sorted([label for label in all_rows if row_totals.get(label, 0) > 0], key=lambda label: (-row_totals[label], label))[:5]
    col_labels = sorted([label for label in all_cols if col_totals.get(label, 0) > 0], key=lambda label: (-col_totals[label], label))[:5]
    if not row_labels:
        row_labels = all_rows[:4]
    if not col_labels:
        col_labels = all_cols[:4]
    x0 = 360
    y0 = 250
    cell_w = max(132, min(176, 900 // max(len(col_labels), 1)))
    cell_h = 58
    matrix_label = "Cruce entre familia arquitectónica y tarea principal"
    title = "Matriz agente-tarea"
    subtitle = "Cruces observados entre familias arquitectónicas y dominios; las celdas vacías no se fuerzan a cero."
    if profile == "personality_llm":
        matrix_label = "Cruce entre estrategia analítica y constructo dominante"
        title = "Matriz constructo-estrategia"
        subtitle = "Cruces observados entre constructos, estrategias metodológicas y focos analíticos."
    elif profile == "creativity_llm":
        matrix_label = "Cruce entre tarea creativa y estrategia de evaluación"
        title = "Matriz tarea-evaluación"
        subtitle = "Cruces observados entre tareas creativas, instrumentos y criterios de evaluación."
    elif profile == "generic":
        matrix_label = "Cruce entre tema dominante y patrón metodológico"
        title = "Matriz tema-método"
        subtitle = "Cruces observados entre temas, métodos y resultados; se ocultan filas y columnas sin señal."
    dominant = max(
        ((matrix[row][col], row, col) for row in row_labels for col in col_labels),
        default=(0, "Sin cruce dominante", "Sin cruce dominante"),
    )
    shown_zero_cells = sum(1 for row in row_labels for col in col_labels if matrix[row][col] == 0)
    def compact_matrix_label(label: str) -> str:
        replacements = {
            "Verificación y evaluación": "Verificación",
            "Evaluación y benchmarks": "Evaluación",
            "Automatización de procesos": "Automatización",
            "Herramientas e integración": "Herramientas",
            "Orquestación explícita": "Orquestación",
            "Agentes conversacionales": "Conversacionales",
        }
        return replacements.get(label, label)

    parts = [f'<text x="80" y="165" class="label">{escape_xml(matrix_label.upper())}</text>']
    for col_index, label in enumerate(col_labels):
        x = x0 + col_index * cell_w + cell_w // 2
        parts.append(multiline_svg_text(wrap_text(figure_display_label(compact_matrix_label(label)), 13), x, 195, 15, "small", anchor="middle"))
    for row_index, label in enumerate(row_labels):
        y = y0 + row_index * cell_h + 35
        parts.append(multiline_svg_text(wrap_text(figure_display_label(compact_matrix_label(label)), 22), 80, y, 15, "small"))
        for col_index, col_label in enumerate(col_labels):
            value = matrix[label][col_label]
            x = x0 + col_index * cell_w
            y_cell = y0 + row_index * cell_h
            bucket = 0 if value == 0 else 1 if value == 1 else 2 if value <= 3 else 3 if value <= 5 else 4
            value_class = "valueDark" if bucket >= 3 else "valueLight"
            parts.append(f'<rect class="cell{bucket}" x="{x}" y="{y_cell}" width="{cell_w}" height="{cell_h}"/>')
            if value:
                parts.append(f'<text x="{x + cell_w/2:.0f}" y="{y_cell + 36}" class="{value_class}" text-anchor="middle">{value}</text>')
    parts.append('<rect class="box" x="250" y="585" width="1000" height="140"/>')
    parts.append('<text x="280" y="620" class="label">LECTURA COMPARATIVA</text>')
    summary_lines = [
        f"- Cruce principal: {compact_matrix_label(dominant[1])} x {compact_matrix_label(dominant[2])} (n={dominant[0]}).",
        f"- Se ocultan filas/columnas sin señal; vacíos visibles={shown_zero_cells}.",
    ]
    wrapped_summary: list[str] = []
    for line in summary_lines:
        wrapped_summary.extend(wrap_text(line, 94))
    parts.append(multiline_svg_text(wrapped_summary, 280, 656, 21, "small"))
    footer = "Matriz multietiqueta: un estudio puede aportar más de una tarea o patrón; la intensidad aumenta con la frecuencia."
    return svg_frame(title, subtitle, "".join(parts), footer, style_profile=style_profile)


def render_review_architecture(review_dir: pathlib.Path, rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    counts = load_flow_counts(review_dir)
    boxes = [
        ("Intake y protocolo", "Pregunta, años, inclusión, exclusión, PDF obligatorio"),
        ("Búsqueda y DOI", f"{counts.get('identified', 0)} registros identificados; trazabilidad DOI"),
        ("Cribado T/A", f"{counts.get('screened_title_abstract', 0)} cribados; {counts.get('excluded_title_abstract', 0)} excluidos"),
        ("PDF completo", f"{counts.get('full_text_assessed', 0)} textos completos evaluados"),
        ("Extracción", f"{len(rows)} estudios en síntesis focal; lectura completa de PDF"),
        ("Auditoría y paper", "APA, revisión cruzada, gate editorial y anexos"),
    ]
    x_positions = [90, 560, 1030]
    y_positions = [210, 210, 210, 450, 450, 450]
    parts = []
    for index, (title, desc) in enumerate(boxes):
        x = x_positions[index % 3]
        y = y_positions[index]
        parts.append(f'<rect class="box" x="{x}" y="{y}" width="360" height="120"/>')
        parts.append(f'<text x="{x + 20}" y="{y + 36}" class="label">{escape_xml(title)}</text>')
        parts.append(multiline_svg_text(wrap_text(desc, 34), x + 20, y + 66, 18, "body"))
    arrows = [
        (450, 270, 560, 270),
        (920, 270, 1030, 270),
        (1210, 330, 1210, 450),
        (1030, 510, 920, 510),
        (560, 510, 450, 510),
    ]
    for x1, y1, x2, y2 in arrows:
        parts.append(f'<line class="arrow" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    footer = "Figura metodológica generada a partir del protocolo SLR, la regla de PDF legible y la cadena de auditoría editorial."
    subtitle = "Pipeline end-to-end desde el intake hasta el manuscrito auditable."
    if profile == "personality_llm":
        subtitle = "Pipeline end-to-end para revisar personalidad en LLMs desde el intake hasta el manuscrito auditable."
    elif profile == "creativity_llm":
        subtitle = "Pipeline end-to-end para revisar creatividad en LLMs desde el intake hasta el manuscrito auditable."
    return svg_frame("Arquitectura operativa de revisión", subtitle, "".join(parts), footer, style_profile=style_profile)


def render_publication_workflow(review_dir: pathlib.Path, rows: list[dict[str, str]], style_profile: str) -> str:
    counts = load_flow_counts(review_dir)
    parts = [
        '<rect class="box" x="90" y="220" width="410" height="190"/>',
        '<text x="120" y="260" class="label">Fase 1. Construcción del corpus</text>',
        multiline_svg_text(
            [
                f"{counts.get('identified', 0)} registros identificados",
                f"{counts.get('full_text_assessed', 0)} PDFs evaluados",
                f"{counts.get('included_in_review', 0)} estudios incluidos",
            ],
            120,
            300,
            24,
            "body",
        ),
        '<rect class="box" x="595" y="220" width="410" height="190"/>',
        '<text x="625" y="260" class="label">Fase 2. Explotación del corpus</text>',
        multiline_svg_text(
            [
                f"{len(rows)} estudios en la síntesis focal",
                "Extracción metodológica por estudio",
                "Matrices, gráficos, figuras y anexos",
            ],
            625,
            300,
            24,
            "body",
        ),
        '<rect class="box" x="1100" y="220" width="410" height="190"/>',
        '<text x="1130" y="260" class="label">Fase 3. Manuscrito publicable</text>',
        multiline_svg_text(
            [
                "Redacción modular del paper",
                "APA, RAE, revisión cruzada y gate",
                "Vault, CSV y evidencia PDF reutilizable",
            ],
            1130,
            300,
            24,
            "body",
        ),
        '<line class="arrow" x1="500" y1="315" x2="595" y2="315"/>',
        '<line class="arrow" x1="1005" y1="315" x2="1100" y2="315"/>',
    ]
    footer = "Flujo de publicación: corpus incluido, síntesis reproducible y manuscrito final auditado."
    return svg_frame("Flujo corpus-síntesis-manuscrito", "Modelo de tres fases para pasar del corpus a un paper auditable.", "".join(parts), footer, style_profile=style_profile)


def render_autopilot_synthesis_bridge(review_dir: pathlib.Path, rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    themes = build_theme_counts(rows, profile).most_common(4)
    patterns = build_pattern_counts(rows, profile).most_common(4)
    components = component_counter_like(rows).most_common(4)
    empirical_n = sum(1 for row in rows if normalize(row.get("work_type", "")) == "empirical")
    evidence_assets = load_evidence_asset_count(review_dir)
    parts = [
        '<rect class="box" x="90" y="220" width="360" height="300"/>',
        '<text x="120" y="260" class="label">Corpus focal</text>',
        multiline_svg_text(
            [
                f"{len(rows)} estudios focales",
                f"{empirical_n} empíricos",
                f"{count_reported(rows, 'method_used')} con método explicitado",
                f"{count_reported(rows, 'theory_framework')} con marco teórico",
            ],
            120,
            300,
            24,
            "body",
        ),
        '<rect class="box" x="620" y="160" width="360" height="420"/>',
        '<text x="650" y="200" class="label">Núcleo de síntesis</text>',
        multiline_svg_text(
            ["Patrones analíticos y temas", "", "Temas dominantes:"]
            + [f"- {label} (n={count})" for label, count in themes[:3]]
            + ["", "Patrones recurrentes:"]
            + [f"- {label} (n={count})" for label, count in patterns[:3]],
            650,
            240,
            22,
            "body",
        ),
        '<rect class="box" x="1150" y="220" width="360" height="300"/>',
        '<text x="1180" y="260" class="label">Salida comparativa</text>',
        multiline_svg_text(
            ["Componentes más visibles:"]
            + [f"- {label} (n={count})" for label, count in components[:3]]
            + ["", f"{evidence_assets} activos de evidencia", "Tablas y figuras comparativas", "Claims auditables en el manuscrito"],
            1180,
            300,
            24,
            "body",
        ),
        '<line class="arrow" x1="450" y1="370" x2="620" y2="370"/>',
        '<line class="arrow" x1="980" y1="370" x2="1150" y2="370"/>',
    ]
    subtitle = "Puente conceptual entre composición del corpus, patrón analítico y resultado sintético."
    if profile == "creativity_llm":
        subtitle = "Puente conceptual entre tareas creativas, estrategias de evaluación y resultado sintético."
    footer = "Figura extra autogenerada por autopilot para reforzar la síntesis transversal cuando el corpus ya tiene densidad suficiente."
    return svg_frame("Puente de síntesis del corpus", subtitle, "".join(parts), footer, style_profile=style_profile)


def render_autopilot_architecture_taxonomy(review_dir: pathlib.Path, rows: list[dict[str, str]], profile: str, style_profile: str) -> str:
    themes = build_theme_counts(rows, profile).most_common(4)
    patterns = build_pattern_counts(rows, profile).most_common(4)
    components = component_counter_like(rows).most_common(5)
    parts = [
        '<rect class="box" x="80" y="170" width="420" height="520"/>',
        '<text x="110" y="210" class="label">Familias arquitectónicas</text>',
        multiline_svg_text(
            [f"- {label} (n={count})" for label, count in patterns[:4]] or ["Sin patrón dominante claro"],
            110,
            250,
            26,
            "body",
        ),
        '<rect class="box" x="590" y="170" width="420" height="520"/>',
        '<text x="620" y="210" class="label">Componentes dominantes</text>',
        multiline_svg_text(
            [f"- {label} (n={count})" for label, count in components[:5]] or ["Sin componente dominante claro"],
            620,
            250,
            26,
            "body",
        ),
        '<rect class="box" x="1100" y="170" width="420" height="520"/>',
        '<text x="1130" y="210" class="label">Tareas y focos del corpus</text>',
        multiline_svg_text(
            [f"- {label} (n={count})" for label, count in themes[:4]] or ["Sin foco temático dominante"],
            1130,
            250,
            26,
            "body",
        ),
        '<line class="arrow" x1="500" y1="430" x2="590" y2="430"/>',
        '<line class="arrow" x1="1010" y1="430" x2="1100" y2="430"/>',
    ]
    subtitle = "Taxonomía operativa del corpus focal: familias, componentes y tareas de aplicación."
    footer = "Figura extra autogenerada por autopilot cuando la review necesita una síntesis taxonómica más explícita."
    return svg_frame("Taxonomía operativa del corpus", subtitle, "".join(parts), footer, style_profile=style_profile)


def render_autopilot_timeline(review_dir: pathlib.Path, rows: list[dict[str, str]], context: dict[str, str], style_profile: str) -> str:
    years = review_years(context, rows)
    year_counter = Counter(parse_int(row.get("year"), 0) for row in rows if parse_int(row.get("year"), 0))
    patterns = build_pattern_counts(rows, detect_review_profile(context)).most_common(3)
    parts = ['<text x="80" y="180" class="label">Evolución del corpus focal</text>']
    x = 130
    for year in years[:6]:
        parts.append(f'<rect class="box" x="{x}" y="260" width="180" height="180"/>')
        parts.append(f'<text x="{x + 25}" y="305" class="label">{year}</text>')
        parts.append(
            multiline_svg_text(
                [
                    f"{year_counter.get(year, 0)} estudios",
                    f"{sum(1 for row in rows if parse_int(row.get('year'), 0) == year and normalize(row.get('work_type', '')) == 'empirical')} empíricos",
                ],
                x + 25,
                345,
                24,
                "body",
            )
        )
        if year != years[min(len(years), 6) - 1]:
            parts.append(f'<line class="arrow" x1="{x + 180}" y1="350" x2="{x + 250}" y2="350"/>')
        x += 250
    parts.append(
        multiline_svg_text(
            ["Patrones dominantes en el periodo:"]
            + [f"- {label} (n={count})" for label, count in patterns],
            120,
            560,
            26,
            "body",
        )
    )
    subtitle = "Secuencia temporal de la composición del corpus y de sus patrones dominantes."
    footer = "Figura extra autogenerada por autopilot cuando la review cubre varios años y conviene una lectura temporal."
    return svg_frame("Evolución temporal del corpus", subtitle, "".join(parts), footer, style_profile=style_profile)


def render_autopilot_personality_construct_flow(review_dir: pathlib.Path, rows: list[dict[str, str]], style_profile: str) -> str:
    constructs = build_theme_counts(rows, "personality_llm").most_common(4)
    patterns = build_pattern_counts(rows, "personality_llm").most_common(4)
    parts = [
        '<rect class="box" x="80" y="250" width="280" height="220"/>',
        '<text x="110" y="290" class="label">Medición y constructos</text>',
        multiline_svg_text(
            [f"- {label} (n={count})" for label, count in constructs[:3]],
            110,
            330,
            24,
            "body",
        ),
        '<rect class="box" x="470" y="250" width="280" height="220"/>',
        '<text x="500" y="290" class="label">Steering y control</text>',
        multiline_svg_text(
            [f"- {label} (n={count})" for label, count in patterns if "Steering" in label or "Persona" in label][:3] or ["- Steering e inferencia", "- Persona y role-play"],
            500,
            330,
            24,
            "body",
        ),
        '<rect class="box" x="860" y="250" width="280" height="220"/>',
        '<text x="890" y="290" class="label">Efectos downstream</text>',
        multiline_svg_text(
            [f"- {label} (n={count})" for label, count in patterns if "Efectos" in label or "Sesgo" in label][:3] or ["- Efectos humanos", "- Sesgo y riesgo"],
            890,
            330,
            24,
            "body",
        ),
        '<rect class="box" x="1250" y="250" width="280" height="220"/>',
        '<text x="1280" y="290" class="label">Implicación editorial</text>',
        multiline_svg_text(
            [
                "Comparación de constructos",
                "Trazabilidad de efectos",
                "Síntesis focal del corpus",
            ],
            1280,
            330,
            24,
            "body",
        ),
        '<line class="arrow" x1="360" y1="360" x2="470" y2="360"/>',
        '<line class="arrow" x1="750" y1="360" x2="860" y2="360"/>',
        '<line class="arrow" x1="1140" y1="360" x2="1250" y2="360"/>',
        '<rect class="box" x="80" y="560" width="1450" height="110"/>',
        '<text x="110" y="596" class="label">Lectura editorial</text>',
        multiline_svg_text(
            [
                "- El corpus se acumula con más fuerza en medición y steering que en efectos downstream comparables.",
                "- Esta figura se reserva para el cuerpo principal porque sintetiza la pregunta de investigación mejor que el workflow editorial.",
            ],
            110,
            632,
            22,
            "body",
        ),
    ]
    subtitle = "Flujo entre constructos medidos, steering aplicado y efectos observados en el corpus."
    footer = "Figura extra autogenerada por autopilot para revisiones sobre personalidad en LLMs."
    return svg_frame("Flujo constructo-steering-efectos", subtitle, "".join(parts), footer, style_profile=style_profile)


def component_counter_like(rows: list[dict[str, str]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    token_map = {
        "roles": ("role", "roles", "specializ", "planner", "reviewer", "worker", "researcher", "coordinator", "multi-agent", "multi agent", "team-based"),
        "orquestador": ("orchestrat", "orchestrator", "routing", "router", "supervisor", "handoff", "manager", "delegat"),
        "herramientas": ("tool", "tools", "benchmark", "mcp", "api", "retrieval", "rag", "repository", "github"),
        "memoria": ("memory", "memoria", "context", "session", "state", "history", "rag"),
        "verificador": ("verif", "validation", "judge", "evaluation", "review", "audit", "guardrail", "critic", "testing"),
    }
    for row in rows:
        blob = normalize(
            " ".join(
                [
                    row.get("title_original", ""),
                    row.get("abstract_original", ""),
                    row.get("method_used", ""),
                    row.get("key_findings", ""),
                    row.get("keywords_normalized", ""),
                ]
            )
        )
        for label, tokens in token_map.items():
            if any(token in blob for token in tokens):
                counter[label] += 1
    return counter


def analytical_grammar_signal_line(rows: list[dict[str, str]], profile: str) -> str:
    """Return a domain-aware evidence summary for the analytical grammar figure."""
    if profile == "social_sciences":
        return "exposición digital, polarización/identidad, confianza institucional e información/desinformación"

    component_counts = component_counter_like(rows)
    top_components = component_counts.most_common(3)
    return ", ".join(f"{label} n={count}" for label, count in top_components) if top_components else "componentes comparativos no estabilizados"


def render_autopilot_evidence_traceability(review_dir: pathlib.Path, rows: list[dict[str, str]], style_profile: str) -> str:
    flow = load_flow_counts(review_dir)
    evidence_assets = load_evidence_asset_count(review_dir)
    table_assets = len(read_csv(review_dir / "tables" / "evidence-manifest.csv"))
    figure_assets = len(read_csv(review_dir / "figures" / "evidence-manifest.csv"))
    boxes = [
        (
            60,
            "PDFs con DOI",
            [
                f"{flow.get('full_text_assessed', 0)} PDFs evaluados",
                f"{len(rows)} PDFs en síntesis",
                "DOI normalizado",
                "Lectura completa",
            ],
        ),
        (
            360,
            "Extracción fuente",
            [
                f"{figure_assets} activos visuales",
                f"{table_assets} activos tabulares",
                "Notas MD por estudio",
            ],
        ),
        (
            660,
            "Matrices y anexos",
            [
                "CSV de trazabilidad",
                "Tablas comparativas",
                "Matriz de componentes",
            ],
        ),
        (
            960,
            "Síntesis manuscrita",
            [
                "Resultados",
                "Discusión",
                "Claims auditables",
                f"{evidence_assets} evidencias",
            ],
        ),
        (
            1260,
            "Paquete final",
            [
                "ZIP editorial",
                "PNG + SVG",
                "Anexos",
                "Bundle final",
            ],
        ),
    ]
    parts = [
        part
        for x, title, lines in boxes
        for part in (
            f'<rect class="box" x="{x}" y="260" width="260" height="220"/>',
            f'<text x="{x + 24}" y="305" class="label">{escape_xml(title)}</text>',
            multiline_svg_text(lines, x + 24, 345, 20, "body"),
        )
    ]
    for x1, x2 in [(320, 360), (620, 660), (920, 960), (1220, 1260)]:
        parts.append(f'<line class="arrow" x1="{x1}" y1="370" x2="{x2}" y2="370"/>')
    subtitle = "Cadena de trazabilidad desde el PDF fuente hasta el paquete editorial final."
    footer = "Figura extra autogenerada por autopilot cuando la review ya acumula evidencia fuente suficiente para explicitar la trazabilidad."
    return svg_frame("Cadena de trazabilidad de la evidencia", subtitle, "".join(parts), footer, style_profile=style_profile)


def build_svg(spec: dict[str, str], review_dir: pathlib.Path, profile: str) -> str:
    rows = load_selected_rows(review_dir)
    figure_id = spec.get("figure_id", "")
    context = read_research_context(review_dir)
    style_profile = resolve_style_profile(spec, profile, context)
    if figure_id == "fig-review-architecture":
        return render_review_architecture(review_dir, rows, profile, style_profile)
    if figure_id == "fig-corpus-map":
        return render_corpus_map(review_dir, rows, profile, style_profile)
    if figure_id == "fig-theme-landscape":
        return render_theme_landscape(rows, profile, style_profile)
    if figure_id == "fig-method-profile":
        return render_method_profile(rows, profile, style_profile)
    if figure_id == "fig-agent-task-matrix":
        return render_agent_task_matrix(rows, profile, style_profile)
    if figure_id == "fig-analytical-grammar":
        return render_analytical_grammar_model(review_dir, rows, profile, style_profile)
    if figure_id == "fig-publication-workflow":
        return render_publication_workflow(review_dir, rows, style_profile)
    if figure_id == "fig-autopilot-synthesis-bridge":
        return render_autopilot_synthesis_bridge(review_dir, rows, profile, style_profile)
    if figure_id == "fig-autopilot-architecture-taxonomy":
        return render_autopilot_architecture_taxonomy(review_dir, rows, profile, style_profile)
    if figure_id == "fig-autopilot-timeline-evolution":
        return render_autopilot_timeline(review_dir, rows, context, style_profile)
    if figure_id == "fig-autopilot-construct-flow":
        return render_autopilot_personality_construct_flow(review_dir, rows, style_profile)
    if figure_id == "fig-autopilot-evidence-traceability":
        return render_autopilot_evidence_traceability(review_dir, rows, style_profile)
    return svg_frame(
        title_from_figure_id(figure_id),
        spec.get("paper_section", ""),
        multiline_svg_text(wrap_text(spec.get("purpose", "Figura sin datos"), 60), 80, 200, 24, "body"),
        spec.get("apa_caption", ""),
        style_profile=style_profile,
    )


def adapt_specs_for_profile(specs: list[dict[str, str]], profile: str) -> list[dict[str, str]]:
    if profile not in {"personality_llm", "creativity_llm", "generic"}:
        return specs
    adapted = []
    for spec in specs:
        row = dict(spec)
        figure_id = row.get("figure_id", "")
        if figure_id == "fig-review-architecture":
            row["apa_caption"] = "Figura 1. Arquitectura operativa de revisión."
            row["purpose"] = "Explicar cómo se conectan protocolo, búsqueda, texto completo, extracción, síntesis y auditoría editorial."
        elif profile == "creativity_llm" and figure_id == "fig-corpus-map":
            row["apa_caption"] = "Figura 2. Mapa del corpus incluido por tipo de trabajo, fuente y diseño empírico."
            row["purpose"] = "Mostrar la composición del corpus sobre creatividad en LLMs por tipo de trabajo, fuente y señal empírica."
        elif profile == "creativity_llm" and figure_id == "fig-theme-landscape":
            row["apa_caption"] = "Figura 3. Panorama temático de la investigación sobre creatividad en LLMs."
            row["purpose"] = "Visualizar la densidad relativa de tareas creativas, instrumentos y estrategias de evaluación."
        elif profile == "creativity_llm" and figure_id == "fig-agent-task-matrix":
            row["apa_caption"] = "Figura 4. Matriz entre tareas creativas, estrategias de evaluación y resultados observados."
            row["purpose"] = "Relacionar tareas creativas con estrategias de evaluación, instrumentos y focos analíticos del corpus."
        elif profile == "creativity_llm" and figure_id == "fig-method-profile":
            row["apa_caption"] = "Figura 5. Mapa de comparabilidad metodológica de los estudios empíricos incluidos."
            row["purpose"] = "Comparar diseño empírico, criterios reportados y vacíos que limitan la comparabilidad metodológica."
        elif profile == "creativity_llm" and figure_id == "fig-publication-workflow":
            row["recommended_status"] = "supplementary"
        elif profile == "generic" and figure_id == "fig-agent-task-matrix":
            row["apa_caption"] = "Figura 4. Matriz entre temas, métodos y resultados observados."
            row["purpose"] = "Relacionar temas dominantes con patrones metodológicos y resultados del corpus."
        elif profile == "generic" and figure_id == "fig-theme-landscape":
            row["apa_caption"] = "Figura 3. Panorama temático y metodológico del corpus final."
            row["purpose"] = "Visualizar temas, métodos y focos analíticos del corpus sin imponer una taxonomía de agentes."
        elif profile == "generic" and figure_id == "fig-corpus-map":
            row["apa_caption"] = "Figura 2. Mapa del corpus incluido por tipo de trabajo, fuente y diseño empírico."
            row["purpose"] = "Mostrar la composición del corpus por tipo de trabajo, fuente y señal empírica."
        elif profile == "generic" and figure_id == "fig-method-profile":
            row["apa_caption"] = "Figura 5. Mapa de comparabilidad metodológica de los estudios empíricos incluidos."
            row["purpose"] = "Comparar diseño empírico, criterios reportados y vacíos que limitan la comparabilidad metodológica."
        elif profile == "generic" and figure_id == "fig-publication-workflow":
            row["recommended_status"] = "supplementary"
        elif profile == "personality_llm" and figure_id == "fig-corpus-map":
            row["apa_caption"] = "Figura 2. Mapa del corpus incluido por tipo de trabajo, fuente y diseño empírico."
            row["purpose"] = "Mostrar la composición del corpus sobre personalidad en LLMs por tipo de trabajo, fuente y señal empírica."
        elif profile == "personality_llm" and figure_id == "fig-theme-landscape":
            row["apa_caption"] = "Figura 3. Panorama temático de la investigación sobre personalidad en LLMs."
            row["purpose"] = "Visualizar la densidad relativa de constructos, estrategias y focos analíticos del corpus."
        elif profile == "personality_llm" and figure_id == "fig-agent-task-matrix":
            row["apa_caption"] = "Figura 4. Matriz entre constructos de personalidad, estrategias metodológicas y resultados observados."
            row["purpose"] = "Relacionar constructos de personalidad con estrategias metodológicas y focos analíticos del corpus."
        elif profile == "personality_llm" and figure_id == "fig-method-profile":
            row["apa_caption"] = "Figura 5. Mapa de comparabilidad metodológica de los estudios empíricos incluidos."
            row["purpose"] = "Comparar diseño empírico, criterios reportados y vacíos que limitan la comparabilidad metodológica."
        elif profile == "personality_llm" and figure_id == "fig-publication-workflow":
            row["recommended_status"] = "supplementary"
        adapted.append(row)
    return adapted


def ensure_core_figure_specs(specs: list[dict[str, str]]) -> list[dict[str, str]]:
    """Add the standard body-figure portfolio when a review has no custom spec file.

    The manuscript generator always references these figures in the main paper.
    Keeping them as generated defaults prevents a completed review from failing
    at LaTeX time only because `figures/paper-figures-spec.csv` was absent.
    """
    known_ids = {(row.get("figure_id") or "").strip() for row in specs}
    enriched = list(specs)
    for spec in CORE_FIGURE_SPECS:
        if spec["figure_id"] not in known_ids:
            enriched.append(dict(spec))
            known_ids.add(spec["figure_id"])
    return enriched


def choose_primary_autopilot_spec(review_dir: pathlib.Path, rows: list[dict[str, str]], profile: str, context: dict[str, str]) -> dict[str, str] | None:
    years = review_years(context, rows)
    if profile == "personality_llm":
        return dict(AUTOPILOT_PERSONALITY_FLOW_SPEC)
    if len(years) >= 3:
        return dict(AUTOPILOT_TIMELINE_SPEC)
    if profile == "software_architecture":
        pattern_count = len([count for count in build_pattern_counts(rows, profile).values() if count > 0])
        component_count = len([count for count in component_counter_like(rows).values() if count > 0])
        if len(rows) >= 15 and pattern_count >= 3 and component_count >= 3:
            return dict(AUTOPILOT_TAXONOMY_SPEC)
    if len(rows) >= 15:
        return dict(AUTOPILOT_SYNTHESIS_SPEC)
    return None


def derive_autopilot_specs(review_dir: pathlib.Path, specs: list[dict[str, str]], profile: str, context: dict[str, str]) -> list[dict[str, str]]:
    rows = load_selected_rows(review_dir)
    if not rows:
        return specs
    spec_ids = {row.get("figure_id", "").strip() for row in specs}
    enriched = list(specs)
    evidence_assets = load_evidence_asset_count(review_dir)
    primary_spec = choose_primary_autopilot_spec(review_dir, rows, profile, context)
    if primary_spec and primary_spec["figure_id"] not in spec_ids:
        enriched.append(primary_spec)
        spec_ids.add(primary_spec["figure_id"])
    if evidence_assets >= 20 and "fig-autopilot-evidence-traceability" not in spec_ids:
        enriched.append(dict(AUTOPILOT_TRACEABILITY_SPEC))
    return enriched


def empirical_row_share(rows: list[dict[str, str]]) -> float:
    if not rows:
        return 0.0
    empirical = sum(1 for row in rows if normalize(row.get("work_type", "")) == "empirical")
    return empirical / max(len(rows), 1)


def score_rationale(
    figure_id: str,
    recommendation: str,
    method_score: int,
    substantive_score: int,
    empirical_score: int,
    nonredundancy_score: int,
    traceability_score: int,
) -> str:
    if figure_id == "prisma-flow":
        return "Se conserva como apoyo o suplemento; el cuerpo principal reporta la selección mediante tabla metodológica."
    if figure_id == "fig-review-architecture":
        return "Ancla metodológica de la arquitectura operativa y de la reproducibilidad de la revisión."
    if figure_id == "fig-analytical-grammar":
        return "Figura de aportación: convierte hallazgos, límites y agenda futura en un modelo comparativo del campo."
    if figure_id in {"fig-publication-workflow", "fig-autopilot-evidence-traceability"}:
        return "Muy útil para auditoría y replicación, pero compite poco con las figuras sustantivas del argumento principal."
    if figure_id.startswith("fig-autopilot-"):
        return "Se conserva como suplemento salvo decisión editorial explícita; las figuras del cuerpo principal no deben exponer lógica interna de autopilot."
    clauses: list[str] = []
    if substantive_score >= 22:
        clauses.append("resume una parte central de la contribución sustantiva")
    if method_score >= 18:
        clauses.append("mantiene un valor metodológico alto")
    if empirical_score >= 16:
        clauses.append("condensa bastante densidad empírica del corpus")
    if nonredundancy_score >= 14:
        clauses.append("aporta información poco redundante frente al resto del portfolio")
    if traceability_score >= 12:
        clauses.append("queda bien anclada a fuentes y anexos auditables")
    if not clauses:
        clauses.append("aporta valor, pero de forma más secundaria")
    recommendation_label = {
        "main_body": "Se recomienda para cuerpo principal porque",
        "supplementary": "Se recomienda como suplemento porque",
        "reserve": "Se deja en reserva porque",
    }.get(recommendation, "Se incluye porque")
    return recommendation_label + " " + "; ".join(clauses) + "."


def rank_figure_portfolio(
    review_dir: pathlib.Path,
    specs: list[dict[str, str]],
    profile: str,
    context: dict[str, str],
) -> list[dict[str, str]]:
    rows = load_selected_rows(review_dir)
    evidence_assets = load_evidence_asset_count(review_dir)
    empirical_share = empirical_row_share(rows)
    journal_family = detect_journal_family(context)
    body_target = MAIN_BODY_FIGURE_LIMIT
    mandatory_body = {"fig-review-architecture"}
    forced_supplementary = set(INTERNAL_PROCESS_FIGURES)
    scoring_defaults = {
        "method": 10,
        "substantive": 10,
        "empirical": 8,
        "nonredundancy": 10,
        "traceability": 8,
    }
    figure_bases = {
        "prisma-flow": {"method": 18, "substantive": 4, "empirical": 8, "nonredundancy": 8, "traceability": 22},
        "fig-review-architecture": {"method": 25, "substantive": 10, "empirical": 8, "nonredundancy": 16, "traceability": 18},
        "fig-corpus-map": {"method": 12, "substantive": 22, "empirical": 18, "nonredundancy": 14, "traceability": 12},
        "fig-theme-landscape": {"method": 10, "substantive": 25, "empirical": 12, "nonredundancy": 16, "traceability": 10},
        "fig-agent-task-matrix": {"method": 14, "substantive": 26, "empirical": 18, "nonredundancy": 17, "traceability": 11},
        "fig-method-profile": {"method": 18, "substantive": 19, "empirical": 20, "nonredundancy": 13, "traceability": 12},
        "fig-autopilot-construct-flow": {"method": 12, "substantive": 24, "empirical": 16, "nonredundancy": 15, "traceability": 13},
        "fig-publication-workflow": {"method": 18, "substantive": 6, "empirical": 4, "nonredundancy": 8, "traceability": 18},
        "fig-autopilot-evidence-traceability": {"method": 17, "substantive": 5, "empirical": 4, "nonredundancy": 9, "traceability": 22},
        "fig-analytical-grammar": {"method": 8, "substantive": 28, "empirical": 16, "nonredundancy": 20, "traceability": 10},
    }
    ranked_rows: list[dict[str, str]] = []
    for spec in specs:
        figure_id = (spec.get("figure_id") or "").strip()
        if not figure_id:
            continue
        base = dict(scoring_defaults)
        base.update(figure_bases.get(figure_id, {}))
        method_score = base["method"]
        substantive_score = base["substantive"]
        empirical_score = base["empirical"]
        nonredundancy_score = base["nonredundancy"]
        traceability_score = base["traceability"]

        if profile == "personality_llm" and figure_id in {
            "fig-corpus-map",
            "fig-theme-landscape",
            "fig-agent-task-matrix",
            "fig-method-profile",
            "fig-autopilot-construct-flow",
        }:
            substantive_score += 4
        if journal_family == "behavioral-computing" and spec.get("style_profile") == "behavioral-academic":
            nonredundancy_score += 2
        if evidence_assets >= 40:
            traceability_score += 2
        if figure_id in {"fig-corpus-map", "fig-agent-task-matrix", "fig-method-profile", "fig-autopilot-construct-flow"}:
            empirical_score += round(empirical_share * 4)
        if figure_id == "fig-theme-landscape" and "fig-agent-task-matrix" in {row.get("figure_id", "") for row in specs}:
            nonredundancy_score -= 2
        if figure_id == "fig-publication-workflow" and any(
            row.get("figure_id", "") == "fig-autopilot-construct-flow" for row in specs
        ):
            substantive_score -= 2
        if figure_id == "fig-autopilot-evidence-traceability":
            nonredundancy_score -= 1

        method_score = max(method_score, 0)
        substantive_score = max(substantive_score, 0)
        empirical_score = max(empirical_score, 0)
        nonredundancy_score = max(nonredundancy_score, 0)
        traceability_score = max(traceability_score, 0)
        total = method_score + substantive_score + empirical_score + nonredundancy_score + traceability_score

        ranked_rows.append(
            {
                "figure_id": figure_id,
                "title": title_from_figure_id(figure_id),
                "style_profile": spec.get("style_profile", ""),
                "paper_section": spec.get("paper_section", ""),
                "figure_type": spec.get("figure_type", ""),
                "score_total": str(total),
                "score_method": str(method_score),
                "score_substantive": str(substantive_score),
                "score_empirical_density": str(empirical_score),
                "score_nonredundancy": str(nonredundancy_score),
                "score_traceability": str(traceability_score),
                "recommendation": "",
                "rationale": "",
            }
        )

    ranked_rows.sort(
        key=lambda row: (
            -int(row.get("score_total", "0") or 0),
            row.get("paper_section", ""),
            row.get("figure_id", ""),
        )
    )

    chosen_body = {row["figure_id"] for row in ranked_rows if row["figure_id"] in mandatory_body}
    for row in ranked_rows:
        figure_id = row["figure_id"]
        if figure_id in mandatory_body or figure_id in forced_supplementary or figure_id.startswith("fig-autopilot-"):
            continue
        if len(chosen_body) < body_target:
            chosen_body.add(figure_id)

    for index, row in enumerate(ranked_rows, start=1):
        figure_id = row["figure_id"]
        total = int(row.get("score_total", "0") or 0)
        if figure_id in chosen_body:
            recommendation = "main_body"
        elif figure_id in forced_supplementary or figure_id.startswith("fig-autopilot-") or total >= 50:
            recommendation = "supplementary"
        else:
            recommendation = "reserve"
        row["rank"] = str(index)
        row["recommendation"] = recommendation
        row["rationale"] = score_rationale(
            figure_id,
            recommendation,
            int(row["score_method"]),
            int(row["score_substantive"]),
            int(row["score_empirical_density"]),
            int(row["score_nonredundancy"]),
            int(row["score_traceability"]),
        )
    return ranked_rows


def write_figure_ranking(review_dir: pathlib.Path, ranked_rows: list[dict[str, str]]) -> None:
    csv_path = review_dir / "figures" / "figure-ranking.csv"
    md_path = review_dir / "figures" / "figure-ranking.md"
    ensure_dir(csv_path.parent)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RANK_FIELDS)
        writer.writeheader()
        writer.writerows(ranked_rows)

    lines = [
        "# Figure Ranking",
        "",
        "Rúbrica: `método + contribución sustantiva + densidad empírica + no redundancia + trazabilidad`.",
        "",
        "| Rank | Figure ID | Score | Recommendation | Rationale |",
        "|---|---|---:|---|---|",
    ]
    for row in ranked_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.get("rank", ""),
                    row.get("figure_id", ""),
                    row.get("score_total", ""),
                    row.get("recommendation", ""),
                    (row.get("rationale", "") or "").replace("|", "/"),
                ]
            )
            + " |"
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def figure_gate_defaults(figure_id: str, spec: dict[str, str], row: dict[str, str], focus_count: int) -> dict[str, str]:
    """Translate the numeric portfolio ranking into an editorial yes/no gate."""
    purpose = spec.get("purpose", "").strip()
    evidence_basis = spec.get("evidence_basis", "").strip()
    figure_type = spec.get("figure_type", "").strip()
    denominator = f"n={focus_count} estudios focales" if focus_count else "denominador no disponible"
    why_visual = "Muestra una relación visual que sería difícil de leer en texto corrido."
    table_alternative = "Tabla si solo quedan conteos simples."
    if figure_id == "fig-review-architecture":
        why_visual = "Resume dependencias metodológicas entre protocolo, búsqueda, full text, extracción y auditoría."
        table_alternative = "Tabla de artefactos metodológicos si la revista limita figuras."
    elif figure_id == "fig-corpus-map":
        why_visual = "Solo debe entrar si combina composición, densidad y cobertura del corpus en una lectura compacta."
        table_alternative = "Tabla de flujo y composición si no añade relación analítica."
    elif figure_id == "fig-theme-landscape":
        why_visual = "Debe mostrar concentración, dispersión o familias de temas, no solo barras de frecuencia."
        table_alternative = "Tabla de temas si no hay mapa o agrupación sustantiva."
    elif figure_id == "fig-agent-task-matrix":
        why_visual = "Cruza dimensiones del campo y permite ver co-ocurrencias, no una lista de conteos."
        table_alternative = "Tabla anexa de matriz completa con ceros y valores bajos."
    elif figure_id == "fig-method-profile":
        why_visual = "Debe explicar comparabilidad metodológica: teoría, muestra, contexto, variables, comparador y validación."
        table_alternative = "Tabla de riesgo/reporting si el gráfico no revela patrón."
    elif figure_id == "fig-analytical-grammar":
        why_visual = "Cierra la aportación transformando hallazgos y vacíos en un modelo comparativo reutilizable."
        table_alternative = "Tabla de aportaciones si el modelo no sintetiza una tesis propia."
    elif figure_id.startswith("fig-autopilot-") or figure_id in INTERNAL_PROCESS_FIGURES:
        why_visual = "Útil para auditoría interna, no para sostener la tesis científica principal."
        table_alternative = "Anexo técnico o inventario de trazabilidad."
    legibility = "90"
    if figure_id.startswith("fig-autopilot-") or figure_id in INTERNAL_PROCESS_FIGURES:
        legibility = "75"
    if figure_type in {"matrix", "contribution-model", "method-profile"}:
        legibility = "85"
    return {
        "figure_id": figure_id,
        "section": spec.get("paper_section", ""),
        "claim": purpose or row.get("rationale", ""),
        "data_source": evidence_basis,
        "denominator": denominator,
        "why_visual": why_visual,
        "table_alternative": table_alternative,
        "redundancy_score": row.get("score_nonredundancy", "0"),
        "scientific_value": row.get("score_substantive", "0"),
        "legibility_score": legibility,
        "decision": row.get("recommendation", "reserve"),
    }


def write_figure_gate(
    review_dir: pathlib.Path,
    specs: list[dict[str, str]],
    ranked_rows: list[dict[str, str]],
) -> None:
    gate_csv = review_dir / "figures" / "figure-gate.csv"
    gate_md = review_dir / "figures" / "figure-gate.md"
    ranking_by_id = {row.get("figure_id", ""): row for row in ranked_rows}
    spec_by_id = {spec.get("figure_id", ""): spec for spec in specs}
    focus_count = len(load_selected_rows(review_dir))
    gate_rows = [
        figure_gate_defaults(figure_id, spec_by_id.get(figure_id, {}), row, focus_count)
        for figure_id, row in ranking_by_id.items()
        if figure_id
    ]
    ensure_dir(gate_csv.parent)
    with gate_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIGURE_GATE_FIELDS)
        writer.writeheader()
        writer.writerows(gate_rows)

    lines = [
        "# Figure Gate",
        "",
        "Regla editorial: una figura entra en el manuscrito solo si sostiene una afirmación científica que no se expresa mejor como tabla o texto.",
        "",
        "| Figure ID | Decision | Claim | Why visual | Table alternative |",
        "|---|---|---|---|---|",
    ]
    for row in gate_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.get("figure_id", ""),
                    row.get("decision", ""),
                    row.get("claim", "").replace("|", "/"),
                    row.get("why_visual", "").replace("|", "/"),
                    row.get("table_alternative", "").replace("|", "/"),
                ]
            )
            + " |"
        )
    gate_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def append_manifest_only_specs(
    review_dir: pathlib.Path,
    specs: list[dict[str, str]],
) -> list[dict[str, str]]:
    manifest_rows = read_csv(review_dir / "figures" / "manifest.csv", MANIFEST_FIELDS)
    known_ids = {(row.get("figure_id") or "").strip() for row in specs}
    combined = list(specs)
    for row in manifest_rows:
        figure_id = (row.get("figure_id") or "").strip()
        if not figure_id or figure_id in known_ids:
            continue
        combined.append(
            {
                "figure_id": figure_id,
                "paper_section": row.get("paper_section", ""),
                "figure_type": row.get("figure_type", ""),
                "purpose": row.get("purpose", ""),
                "evidence_basis": row.get("evidence_basis", ""),
                "style_profile": row.get("style_profile", ""),
                "apa_caption": row.get("apa_caption", ""),
                "recommended_status": row.get("status", ""),
                "notes": row.get("notes", ""),
                "preserve_existing_svg": "yes",
            }
        )
    return combined


def write_figure_catalog(
    review_dir: pathlib.Path,
    specs: list[dict[str, str]],
    profile: str,
    context: dict[str, str],
    ranked_rows: list[dict[str, str]],
) -> None:
    catalog_path = review_dir / "figures" / "figure-catalog.md"
    journal_family = detect_journal_family(context)
    body_portfolio = [row.get("figure_id", "") for row in ranked_rows if row.get("recommendation") == "main_body"]
    supplementary_portfolio = [row.get("figure_id", "") for row in ranked_rows if row.get("recommendation") == "supplementary"]
    ranking_by_id = {row.get("figure_id", ""): row for row in ranked_rows}
    lines = [
        "# Figure Catalog",
        "",
        f"- Review profile detected: `{profile}`",
        f"- Journal family detected: `{journal_family}`",
        "- Style families: `systematic-selection-flow`, `analytic-grayscale`, `behavioral-academic`, `process-blueprint`, `supplementary-evidence`.",
        "- Portfolio rule: selección reportada como tabla metodológica, una figura de arquitectura operativa y prioridad para figuras sustantivas del corpus.",
        f"- Main-body cap: máximo {MAIN_BODY_FIGURE_LIMIT} figuras; el resto queda como suplemento o reserva.",
        f"- Recommended body portfolio: `{', '.join(body_portfolio)}`",
        f"- Recommended supplementary portfolio: `{', '.join(supplementary_portfolio)}`",
        "- Gate artifacts: `figures/figure-gate.csv` y `figures/figure-gate.md`.",
        "- Ranking artifacts: `figures/figure-ranking.csv` y `figures/figure-ranking.md`.",
        "",
        "| Figure ID | Section | Type | Style | Recommendation | Score | Rationale |",
        "|---|---|---|---|---|---:|---|",
    ]
    for spec in specs:
        figure_id = spec.get("figure_id", "").strip()
        if not figure_id:
            continue
        rank = ranking_by_id.get(figure_id, {})
        rationale = (spec.get("notes", "") or spec.get("purpose", "") or "").strip().replace("|", "/")
        if rank.get("rationale"):
            rationale = rank["rationale"].replace("|", "/")
        lines.append(
            "| "
            + " | ".join(
                [
                    figure_id,
                    spec.get("paper_section", ""),
                    spec.get("figure_type", ""),
                    spec.get("style_profile", ""),
                    rank.get("recommendation", "") or spec.get("recommended_status", "") or "planned",
                    rank.get("score_total", "") or "0",
                    rationale,
                ]
            )
            + " |"
        )
    catalog_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_mode_publication_plan(review_dir: pathlib.Path, mode_decision: dict[str, object]) -> None:
    """Persist the discipline-specific figure/table contract next to outputs."""

    if not mode_decision:
        return

    def as_list(key: str) -> list[str]:
        value = mode_decision.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    mode_label = str(mode_decision.get("mode_label") or mode_decision.get("mode") or "modo no declarado")
    figure_rows = [
        {"priority": "minimum", "item": item}
        for item in as_list("minimum_figures")
    ] + [
        {"priority": "recommended", "item": item}
        for item in as_list("recommended_figures")
    ]
    table_rows = [
        {"priority": "minimum", "item": item}
        for item in as_list("minimum_tables")
    ] + [
        {"priority": "recommended", "item": item}
        for item in as_list("recommended_tables")
    ]

    figure_csv = review_dir / "figures" / "mode-figure-plan.csv"
    figure_md = review_dir / "figures" / "mode-figure-plan.md"
    table_csv = review_dir / "tables" / "mode-table-plan.csv"
    table_md = review_dir / "tables" / "mode-table-plan.md"
    for path in (figure_csv, figure_md, table_csv, table_md):
        ensure_dir(path.parent)

    fields = ["mode", "priority", "item", "rule"]
    for path, rows, rule in (
        (figure_csv, figure_rows, "Include only if the visual explains an analytical relation or audit decision."),
        (table_csv, table_rows, "Include as body table or annex depending on journal space and analytical value."),
    ):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "mode": mode_label,
                        "priority": row["priority"],
                        "item": row["item"],
                        "rule": rule,
                    }
                )

    figure_lines = [
        "# Mode Figure Plan",
        "",
        f"- Modo aplicado: {mode_label}",
        "- Regla: una figura entra solo si reduce complejidad, muestra una relación analítica o permite auditar una decisión.",
        "",
        "| Priority | Figure need |",
        "|---|---|",
    ]
    for row in figure_rows:
        figure_lines.append(f"| {row['priority']} | {row['item'].replace('|', '/')} |")
    figure_md.write_text("\n".join(figure_lines).rstrip() + "\n", encoding="utf-8")

    table_lines = [
        "# Mode Table Plan",
        "",
        f"- Modo aplicado: {mode_label}",
        "- Regla: las tablas mínimas deben sostener método, resultados, evaluación crítica y aportación original.",
        "",
        "| Priority | Table need |",
        "|---|---|",
    ]
    for row in table_rows:
        table_lines.append(f"| {row['priority']} | {row['item'].replace('|', '/')} |")
    table_md.write_text("\n".join(table_lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument("--force", action="store_true", help="Overwrite existing SVG figures")
    parser.add_argument("--autopilot", action="store_true", help="Allow heuristic addition of supplemental SVG synthesis diagrams")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory does not exist: {review_dir}")

    figures_dir = review_dir / "figures"
    svg_dir = figures_dir / "svg"
    manifest_path = figures_dir / "manifest.csv"
    spec_path = figures_dir / "paper-figures-spec.csv"

    ensure_dir(svg_dir)
    context = read_research_context(review_dir)
    profile = detect_review_profile(context)
    mode_playbook = read_review_mode_playbook(review_dir)
    declared_mode = str(mode_playbook.get("primary_mode") or mode_playbook.get("mode") or "").strip()
    if declared_mode:
        profile = declared_mode
    specs = adapt_specs_for_profile(ensure_core_figure_specs(read_csv(spec_path, SPEC_FIELDS)), profile)
    if args.autopilot:
        specs = derive_autopilot_specs(review_dir, specs, profile, context)
    specs = curate_specs_for_portfolio(specs, profile, context)
    specs = append_manifest_only_specs(review_dir, specs)
    ranked_rows = rank_figure_portfolio(review_dir, specs, profile, context)
    existing_manifest = {row.get("figure_id", ""): row for row in read_csv(manifest_path, MANIFEST_FIELDS)}
    spec_ids = {row.get("figure_id", "").strip() for row in specs if row.get("figure_id", "").strip()}
    for figure_id in list(existing_manifest):
        if figure_id.startswith("fig-") and figure_id not in spec_ids:
            existing_manifest.pop(figure_id, None)

    created = 0
    updated = 0
    for spec in specs:
        figure_id = spec.get("figure_id", "").strip()
        if not figure_id:
            continue
        svg_path = svg_dir / f"{figure_id}.svg"
        png_path = figures_dir / "png" / f"{figure_id}.png"
        preserve_existing_svg = normalize(spec.get("preserve_existing_svg", "")) in {"yes", "si", "sí", "true", "1"}
        if not (preserve_existing_svg and svg_path.exists()) and (args.force or not svg_path.exists()):
            svg_path.write_text(build_svg(spec, review_dir, profile), encoding="utf-8")
            created += 1

        current = existing_manifest.get(figure_id, {field: "" for field in MANIFEST_FIELDS})
        current["figure_id"] = figure_id
        if figure_id == "fig-review-architecture":
            current["title"] = "Arquitectura operativa de revisión"
        elif figure_id == "fig-method-profile":
            current["title"] = "Mapa de comparabilidad metodológica"
        elif figure_id == "fig-analytical-grammar":
            current["title"] = "Gramática analítica de la revisión"
        elif figure_id == "prisma-flow":
            current["title"] = "Flujo de selección de estudios"
        else:
            current["title"] = current.get("title") or title_from_figure_id(figure_id)
        current["phase"] = current.get("phase") or "Fase 2-3"
        current["paper_section"] = spec.get("paper_section", "")
        current["figure_type"] = spec.get("figure_type", "")
        current["purpose"] = spec.get("purpose", "")
        current["evidence_basis"] = spec.get("evidence_basis", "")
        current["style_profile"] = spec.get("style_profile", "") or "analytic-grayscale"
        current["apa_caption"] = spec.get("apa_caption", "")
        current["svg_path"] = svg_path.relative_to(review_dir).as_posix()
        current["png_path"] = png_path.relative_to(review_dir).as_posix()
        files_are_rendered = svg_path.exists() and png_path.exists()
        if files_are_rendered:
            current["status"] = "rendered"
        else:
            current["status"] = spec.get("recommended_status", "") or current.get("status") or "planned"
        current["notes"] = spec.get("notes", "")
        existing_manifest[figure_id] = current
        updated += 1

    rows = [existing_manifest[key] for key in sorted(existing_manifest)]
    write_manifest(manifest_path, rows)
    write_figure_ranking(review_dir, ranked_rows)
    write_figure_gate(review_dir, specs, ranked_rows)
    write_figure_catalog(review_dir, specs, profile, context, ranked_rows)
    write_mode_publication_plan(review_dir, read_review_mode_playbook(review_dir))
    print(f"created_svg: {created}")
    print(f"updated_manifest_rows: {updated}")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
