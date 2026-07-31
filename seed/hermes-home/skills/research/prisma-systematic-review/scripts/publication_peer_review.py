#!/usr/bin/env python3
"""Run independent publication reviews with multiple OpenAI-compatible cloud models and summarize the outcome."""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib import error, request

from cloud_inference import configured_research_models

REQUIRED_FIELDS = [
    "reviewer_id",
    "role",
    "model",
    "provider",
    "base_url",
    "focus",
    "enabled",
    "notes",
]

RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
USER_AGENT = "HermesPublicationPeerReview/1.0"
VALID_VERDICTS = {"accept", "minor revision", "major revision", "reject"}

HERMES_HOME = pathlib.Path(__file__).resolve().parents[4]
RESEARCH_SKILLS = HERMES_HOME / "skills" / "research"
REVIEW_PACKET_SCRIPT = RESEARCH_SKILLS / "academic-paper-reviewer" / "scripts" / "build_review_packet.py"
REVISION_ROADMAP_SCRIPT = RESEARCH_SKILLS / "revision-roadmap" / "scripts" / "build_revision_roadmap.py"


@dataclass
class ReviewResult:
    reviewer_id: str
    role: str
    model: str
    status: str
    verdict: str
    output_path: str
    notes: str


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    normalized = []
    for row in rows:
        normalized.append({field: row.get(field, "") for field in REQUIRED_FIELDS})
    return normalized


def write_manifest(path: pathlib.Path, rows: Iterable[ReviewResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["reviewer_id", "role", "model", "status", "verdict", "output_path", "notes"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def prune_stale_review_files(review_files_dir: pathlib.Path, review_models: list[dict[str, str]]) -> None:
    active_ids = {
        (row.get("reviewer_id") or "").strip()
        for row in review_models
        if boolish(row.get("enabled", ""))
    }
    if not review_files_dir.exists():
        return
    for path in review_files_dir.iterdir():
        if not path.is_file():
            continue
        reviewer_id = ""
        if path.name.endswith(".prompt.md"):
            reviewer_id = path.name[: -len(".prompt.md")]
        elif path.name.endswith(".json"):
            reviewer_id = path.stem
        elif path.name.endswith(".md"):
            reviewer_id = path.stem
        if not reviewer_id.startswith("reviewer_"):
            continue
        if reviewer_id and reviewer_id not in active_ids:
            path.unlink(missing_ok=True)


def run_subprocess(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def load_env_file(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_env_value(review_dir: pathlib.Path, *keys: str) -> str:
    for key in keys:
        env_value = os.environ.get(key, "").strip()
        if env_value:
            return env_value
    candidate_env_files = [
        review_dir / ".env",
        review_dir.parent / ".env",
        HERMES_HOME / ".env",
    ]
    for env_file in candidate_env_files:
        values = load_env_file(env_file)
        for key in keys:
            value = values.get(key, "").strip()
            if value:
                return value
    return ""


def boolish(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def is_local_base_url(base_url: str) -> bool:
    normalized = (base_url or "").strip().lower()
    return normalized.startswith("http://127.0.0.1") or normalized.startswith("http://localhost")


def normalize_openai_base_url(base_url: str) -> str:
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.endswith("/chat/completions"):
        return raw[: -len("/chat/completions")]
    if raw.endswith("/api"):
        return raw[: -len("/api")] + "/v1"
    if raw.endswith("/api/chat"):
        return raw[: -len("/api/chat")] + "/v1"
    return raw


def provider_from_base_url(base_url: str) -> str:
    return "openai_compatible" if normalize_openai_base_url(base_url) else ""


def provider_from_model(model: str) -> str:
    return "openai_compatible" if (model or "").strip() else ""


def resolve_provider_api_key(review_dir: pathlib.Path, provider_name: str) -> str:
    del provider_name
    return resolve_env_value(
        review_dir,
        "HERMES_INFERENCE_API_KEY",
        "HERMES_MODEL_API_KEY",
        "PRIMARY_OPENAI_API_KEY",
        "OPENAI_API_KEY",
    )


def resolve_primary_base_url(review_dir: pathlib.Path) -> str:
    configured = resolve_env_value(
        review_dir,
        "HERMES_INFERENCE_BASE_URL",
        "HERMES_MODEL_BASE_URL",
        "PRIMARY_OPENAI_BASE_URL",
        "OPENAI_BASE_URL",
    )
    if configured:
        return normalize_openai_base_url(configured)
    return ""


def resolve_reviewer_endpoint(model: str, configured_base_url: str, review_dir: pathlib.Path) -> tuple[str, str, str]:
    normalized = normalize_openai_base_url(configured_base_url)
    model_provider = provider_from_model(model)
    configured_provider = provider_from_base_url(normalized) if normalized else ""
    provider_name = configured_provider or model_provider
    base_url = normalized or resolve_primary_base_url(review_dir)
    api_key = resolve_provider_api_key(review_dir, provider_name)
    if not base_url:
        return "", "", "missing_base_url"
    if normalized:
        if is_local_base_url(normalized):
            return "", "", "local_base_url_disallowed"
    if is_local_base_url(base_url):
        return "", "", "local_base_url_disallowed"
    if not api_key:
        return "", "", "missing_inference_api_key"
    return base_url, api_key, ""


def extract_verdict(text: str) -> str:
    def clean(value: str) -> str:
        value = value.strip()
        value = re.sub(r"[*_`]+", "", value)
        value = re.sub(r"[.;:]+$", "", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip().lower()

    def normalize_candidate(value: str) -> str:
        cleaned = clean(value)
        if not cleaned:
            return "unresolved"
        placeholder_markers = (
            "<accept",
            "accept | minor revision",
            "minor revision | major revision",
            "major revision | reject",
        )
        if any(marker in cleaned for marker in placeholder_markers):
            return "unresolved"
        if cleaned in VALID_VERDICTS:
            return cleaned
        match = re.match(r"^(accept|minor revision|major revision|reject)\b", cleaned)
        if match:
            return match.group(1)
        return "unresolved"

    patterns = [
        r"(?im)^\s*(?:[-*]\s*)?veredicto(?:\s+final)?\s*:\s*(.+)$",
        r"(?im)^\s*(?:[-*]\s*)?decision\s*:\s*(.+)$",
        r"(?im)^\s*(?:[-*]\s*)?recommendation\s*:\s*(.+)$",
    ]
    saw_labeled_verdict = False
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            saw_labeled_verdict = True
            normalized_matches = [normalize_candidate(match) for match in matches]
            valid_matches = [match for match in normalized_matches if match != "unresolved"]
            if len(set(valid_matches)) > 1:
                return "unresolved"
            for match in reversed(matches):
                normalized = normalize_candidate(match)
                if normalized != "unresolved":
                    return normalized
    if saw_labeled_verdict:
        return "unresolved"

    # Reviewer models sometimes echo the rubric before giving the final answer.
    # Scan from the bottom and ignore obvious instruction/template lines so that
    # an option list such as "accept | minor revision | major revision | reject"
    # cannot be misread as a rejection.
    instruction_markers = (
        "<",
        "|",
        "secciones exactas",
        "estructura de la respuesta",
        "ejemplos válidos",
        "ejemplos validos",
        "debo entregar",
        "opciones",
        "veredicto:",
    )
    for line in reversed(text.splitlines()):
        lowered = clean(line)
        if not lowered or any(marker in lowered for marker in instruction_markers):
            continue
        for verdict in ("accept", "minor revision", "major revision", "reject"):
            if re.search(rf"\b{re.escape(verdict)}\b", lowered):
                return verdict
        if "revisión menor" in lowered or "revision menor" in lowered:
            return "minor revision"
        if "revisión mayor" in lowered or "revision mayor" in lowered:
            return "major revision"
        if "rechazo" in lowered or "rechazar" in lowered:
            return "reject"
        if "acept" in lowered:
            return "accept"
    return "unresolved"


def is_structured_review_response(text: str) -> bool:
    lowered = text.lower()
    if "el usuario solicita" in lowered or "necesito interpretar" in lowered or "debo revisar" in lowered:
        return False
    required = ["veredicto:", "## apa", "## problemas mayores", "## dictamen final"]
    return all(marker in lowered for marker in required)


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_Sin datos._"
    def safe_cell(value: object) -> str:
        return str(value).replace("|", r"\|").replace("\n", "<br>").strip()

    lines = [
        "|" + "|".join(safe_cell(header) for header in headers) + "|",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        safe = [safe_cell(cell) for cell in row]
        lines.append("|" + "|".join(safe) + "|")
    return "\n".join(lines)


def parse_intake_value(intake_text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", intake_text, flags=re.MULTILINE)
    return (match.group(1) if match else "").strip()


def detect_review_profile(intake_text: str) -> str:
    blob = " ".join(
        [
            parse_intake_value(intake_text, "Tema"),
            parse_intake_value(intake_text, "Pregunta de investigación (opcional)"),
            parse_intake_value(intake_text, "Criterios de inclusión"),
        ]
    ).lower()
    if any(token in blob for token in ("personalidad", "persona", "trait", "big five", "mbti", "hexaco")) and any(token in blob for token in ("llm", "large language model", "language model", "modelo de lenguaje")):
        return "personality_llm"
    if any(token in blob for token in ("software", "code", "software development", "ingeniería del software", "desarrollo de software")):
        return "software_architecture"
    return "generic"


def build_review_packet(manuscript: str, mode: str = "standard") -> str:
    text = manuscript.strip()
    if not text:
        return text

    def normalize_heading(value: str) -> str:
        lowered = value.strip().lower()
        return (
            lowered.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("ü", "u")
            .replace("ñ", "n")
        )

    def section_char_budget(heading_line: str) -> int:
        heading = normalize_heading(heading_line)
        if mode == "ultralight":
            factor = 0.46
        elif mode == "light":
            factor = 0.68
        elif mode == "method_review":
            factor = 0.9
        elif mode == "focused_apa":
            factor = 0.58
        else:
            factor = 1.0
        if "revision sistematica" in heading or "revisión sistemática" in heading:
            return int(6200 * factor)
        if "titulo, resumen" in heading or "title, abstract" in heading:
            return int(4200 * factor)
        if heading.startswith("# introduccion"):
            return int(5200 * factor)
        if heading.startswith("# marco teorico"):
            return int(5200 * factor)
        if heading.startswith("# metodo"):
            if mode == "method_review":
                return 18000
            return int(14000 * factor)
        if heading.startswith("# resultados"):
            if mode == "method_review":
                return 15000
            return int(12000 * factor)
        if heading.startswith("# discusion"):
            if mode == "method_review":
                return 9000
            return int(7000 * factor)
        if heading.startswith("# conclusiones"):
            if mode == "method_review":
                return 7000
            return int(5000 * factor)
        return int(4200 * factor)

    def compact_markdown_tables(block: str, max_lines: int = 10) -> str:
        if mode == "ultralight":
            max_lines = max(max_lines, 16)
        elif mode in {"light", "focused_apa"}:
            max_lines = max(max_lines, 34)
        elif mode == "method_review":
            max_lines = max(max_lines, 90)
        else:
            max_lines = max(max_lines, 60)
        lines = block.splitlines()
        compacted: list[str] = []
        index = 0
        while index < len(lines):
            stripped = lines[index].lstrip()
            if stripped.startswith("|"):
                start = index
                while index < len(lines) and lines[index].lstrip().startswith("|"):
                    index += 1
                table_lines = lines[start:index]
                compacted.extend(table_lines[:max_lines])
                continue
            compacted.append(lines[index])
            index += 1
        return "\n".join(compacted)

    def clip_block(block: str, budget: int) -> str:
        if len(block) <= budget:
            return block
        clipped = block[:budget].rstrip()
        last_break = max(clipped.rfind("\n\n"), clipped.rfind("\n- "), clipped.rfind("\n|"))
        if last_break > budget * 0.6:
            clipped = clipped[:last_break].rstrip()
        return clipped

    parts = re.split(r"(?m)^# ", text)
    kept = []
    for part in parts:
        if not part.strip():
            continue
        chunk = "# " + part if not part.startswith("# ") else part
        heading = chunk.splitlines()[0].strip().lower()
        if (
            heading.startswith("# corpus final incluido")
            or heading.startswith("# anexos de datos y trazabilidad")
            or heading.startswith("# referencias")
        ):
            continue
        kept.append(chunk.strip())
    packet = "\n\n".join(kept)
    if packet != text:
        packet += (
            "\n\n## Nota para revisión editorial\n"
            "El manuscrito completo dispone además de un apéndice analítico por estudio y anexos CSV de trazabilidad. "
            "Esa capa documental existe para auditoría y replicación, pero se omite en este paquete de revisión para centrar la evaluación en la publicabilidad del artículo principal.\n"
        )

    def collapse_images(block: str) -> str:
        lines = block.splitlines()
        compacted: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("![") and "](" in stripped:
                path = re.search(r"\]\(([^)]+)\)", stripped)
                figure_path = path.group(1) if path else "ruta no resuelta"
                compacted.append(f"[Elemento visual disponible en el manuscrito completo: {figure_path}]")
                continue
            compacted.append(line)
        text_block = "\n".join(compacted)
        text_block = re.sub(r"\n{3,}", "\n\n", text_block)
        return text_block.strip()

    review_sections = []
    for chunk in kept:
        lines = chunk.splitlines()
        heading_line = lines[0].strip()
        body = collapse_images("\n".join(lines[1:]).strip())
        body = compact_markdown_tables(body)
        body = clip_block(body, section_char_budget(heading_line))
        review_sections.append("\n\n".join(part for part in [heading_line, body] if part))
    return "\n\n".join(review_sections)


def compact_references(references: str, limit: int = 200) -> str:
    text = references.strip()
    if not text:
        return text
    entries = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
    if len(entries) <= limit:
        return text
    kept = entries[:limit]
    omitted = len(entries) - limit
    return "\n".join(
        [
            "# Referencias APA generadas (muestra compacta)",
            "",
            *kept,
            "",
            f"_Se omiten {omitted} referencias en este paquete breve; la bibliografía completa existe en el manuscrito y en `references.generated.md`._",
        ]
    )


def summarize_references(references: str, sample_size: int = 10) -> str:
    text = references.strip()
    if not text:
        return text
    entries = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
    if len(entries) <= sample_size:
        sample = entries
    else:
        head_count = max(1, sample_size // 2)
        tail_count = max(1, sample_size - head_count)
        sample = entries[:head_count] + ["- [...]"] + entries[-tail_count:]
    return "\n".join(
        [
            "# Resumen bibliográfico",
            "",
            f"- Entradas bibliográficas totales: {len(entries)}",
            "- La bibliografía completa existe en `references.generated.md` y ya pasó por auditoría editorial determinista.",
            "- Muestra breve de entradas para control contextual del revisor:",
            "",
            *sample,
        ]
    )


def compact_references_for_apa_review(references: str, sample_size: int = 80) -> str:
    text = references.strip()
    if not text:
        return text
    entries = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
    if len(entries) <= sample_size:
        sample = entries
    else:
        head_count = max(4, sample_size // 2)
        tail_count = max(4, sample_size - head_count)
        sample = entries[:head_count] + ["- [...]"] + entries[-tail_count:]
    return "\n".join(
        [
            "# Referencias APA generadas (paquete de contraste)",
            "",
            f"- Entradas bibliográficas totales: {len(entries)}",
            "- Usa esta bibliografía de contraste para detectar errores sistemáticos de estilo o trazabilidad; no marques una referencia como ausente si aparece aquí.",
            "",
            *sample,
        ]
    )


def compact_publication_audit(publication_audit: str) -> str:
    if not publication_audit.strip():
        return publication_audit
    lines = publication_audit.splitlines()
    kept: list[str] = []
    in_incidents = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Citas resueltas"):
            break
        if stripped.startswith("## Incidencias"):
            in_incidents = True
        kept.append(line)
        if in_incidents and not stripped:
            break
    compacted = "\n".join(kept).strip()
    return compacted or publication_audit


def build_prompt(
    reviewer: dict[str, str],
    manuscript: str,
    references: str,
    publication_audit: str,
    intake_text: str,
) -> str:
    reviewer_id = (reviewer.get("reviewer_id", "") or "").strip().lower()
    role = reviewer.get("role", "Reviewer")
    focus = reviewer.get("focus", "")
    focus_lower = focus.lower()
    apa_intensive = (
        "apa" in focus_lower
        or "bibliograf" in focus_lower
        or "citas" in focus_lower
        or "gemma" in reviewer_id
        or reviewer_id.endswith("_b")
    )
    review_packet = build_review_packet(manuscript, mode="focused_apa" if apa_intensive else "method_review")
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    profile = detect_review_profile(intake_text)
    if profile == "personality_llm":
        domain_note = "El manuscrito pertenece al ámbito de personalidad en LLMs, interacción humano-IA y ciencias del comportamiento computacional; la ausencia de registro PROSPERO no es, por sí sola, motivo automático de rechazo si el protocolo y los artefactos quedan transparentemente documentados."
        supplement_note = "Existe material suplementario real fuera de este paquete breve: matrices temáticas/constructivas CSV, strategy strings de búsqueda, intake, criterios, PDFs locales y anexos de datos. Evalúa la publicabilidad del artículo principal, no la ausencia de esos anexos dentro del cuerpo compacto que recibes aquí."
    elif profile == "software_architecture":
        domain_note = "El manuscrito pertenece al ámbito de ingeniería del software; la ausencia de registro PROSPERO no es, por sí sola, motivo automático de rechazo si el protocolo y los artefactos quedan transparentemente documentados."
        supplement_note = "Existe material suplementario real fuera de este paquete breve: matriz arquitectónica CSV, strategy strings de búsqueda, intake, criterios, PDFs locales y anexos de datos. Evalúa la publicabilidad del artículo principal, no la ausencia de esos anexos dentro del cuerpo compacto que recibes aquí."
    else:
        domain_note = "El manuscrito pertenece a una revisión sistemática temática de 2026; la ausencia de registro PROSPERO no es, por sí sola, motivo automático de rechazo si el protocolo y los artefactos quedan transparentemente documentados."
        supplement_note = "Existe material suplementario real fuera de este paquete breve: matrices CSV, strategy strings de búsqueda, intake, criterios, PDFs locales y anexos de datos. Evalúa la publicabilidad del artículo principal, no la ausencia de esos anexos dentro del cuerpo compacto que recibes aquí."
    audit_packet = compact_publication_audit(publication_audit)
    reference_packet = compact_references_for_apa_review(references) if apa_intensive else summarize_references(references)
    priority_note = (
        "Prioridad máxima: exactitud de referencias APA y trazabilidad de afirmaciones al corpus."
        if apa_intensive
        else "Prioridad máxima: publicabilidad, trazabilidad metodológica, coherencia argumental y riesgos metodológicos; la APA se revisa como control secundario apoyado en la auditoría determinista."
    )
    bibliography_note = (
        "Debes revisar activamente citas en texto y bibliografía."
        if apa_intensive
        else "No conviertas la revisión en una auditoría bibliográfica exhaustiva: prioriza problemas materiales del manuscrito y usa el resumen bibliográfico solo como contraste contextual."
    )
    return f"""Actúa como {role} de una revista científica internacional revisando un manuscrito de revisión sistemática.

Tu evaluación debe ser independiente y no asumir la opinión de otros revisores.
Idioma de salida: español de España.
Norma lingüística: RAE.
{priority_note}
Longitud objetivo de tu dictamen: entre 900 y 1600 palabras. Sé preciso, no exhaustivo.

	Contexto editorial importante:
		- La fecha efectiva de esta revisión es {today}. No trates la literatura de 2026 como futurista o hipotética.
			- {domain_note}
			- {supplement_note}
			- {bibliography_note}
			- Los marcadores `[Sección compactada para revisión: ...]` o `[Tabla compactada para revisión: ...]` pertenecen solo a este paquete compacto de dictamen y NO aparecen como contenido omitido en el PDF/Markdown final. No los marques como problema del manuscrito ni como falta de trazabilidad; evalúa únicamente el contenido visible y los artefactos declarados.
			- El bloque de referencias incluido en este prompt puede estar resumido para ahorrar contexto. No declares que faltan referencias completas solo porque el paquete breve no muestre toda `references.generated.md`; usa la auditoría determinista como fuente principal para errores bibliográficos y marca ausencia solo si el manuscrito final o la auditoría dicen que falta.
			- Si una figura aparece resumida como marcador textual con ruta local, debes asumir que el activo visual existe y evaluar su papel científico, no marcarlo como ausente por no ver la imagen binaria en el prompt.
	- No declares una cita como "sin referencia" si existe una entrada bibliográfica compatible por apellido principal, inicial o variante de desambiguación. Marca el problema solo cuando la ausencia sea inequívoca.
	- Antes de afirmar que falta una referencia, busca explícitamente el apellido principal en la bibliografía incluida al final del manuscrito. Si la referencia aparece, no la marques como ausente.
	- En APA 7, las citas parentéticas estándar usan apellido(s) y año; no exijas iniciales en la cita en texto salvo que exista una colisión real que requiera desambiguación.
	- Si el manuscrito explica explícitamente que el corpus incluido de la revisión sistemática coincide con el corpus analizado en profundidad, no lo trates como defecto metodológico automático; evalúa si la justificación está clara y auditada.
	- Las tablas en Markdown forman parte del manuscrito recibido. No asumas que están truncadas o ausentes salvo que el contenido visible esté realmente incompleto.
		- No declares inconsistencias entre tablas salvo que puedas recomputarlas a partir de los valores explícitamente visibles en el manuscrito recibido. Si una tabla no muestra una columna, no infieras su valor desde otra.
		- Las celdas ajustadas por anchura indican compactación visual, no ausencia de datos. No marques una discrepancia por salto de línea o truncamiento tipográfico; exige títulos completos cuando la tabla declare "Título completo".
		- Si detectas una tensión cuantitativa, cita exactamente qué tabla, qué fila y qué cifras visibles la sostienen. Si no puedes señalar esas cifras de forma explícita, trátalo como duda menor y no como problema mayor.
		- Distingue "muestra o unidad empírica reportada" de "tamaño muestral detallado". No declares contradicción si una tabla dice que todos los estudios reportan unidad/muestra y otra registra cuántos no informan un tamaño muestral numérico.
		- Si el manuscrito declara de forma explícita que no hubo doble revisor humano y aporta protocolo, CSV, DOI, PDF, scores, sensibilidad, revisión cruzada y anexos auditables, evalúalo como amenaza a la validez o límite metodológico, pero no lo conviertas por sí solo en "major revision". Solo debe ser problema mayor si además faltan artefactos, hay contradicciones materiales o las decisiones no son auditables.
		- En corpus heterogéneos no clínicos, no exijas automáticamente ROBINS-I, Cochrane o una herramienta biomédica concreta. Una rúbrica estructurada de riesgo de reporting/trazabilidad por estudio puede ser aceptable si explica indicadores, límites y matriz auditable; marca como major solo si no existe evaluación crítica recuperable.

Enfoque adicional del revisor:
{focus or 'Evaluación general de calidad científica y formal.'}

Entrega tu respuesta con estas secciones exactas:
Veredicto: <accept | minor revision | major revision | reject>

## APA
- lista de errores APA en citas en texto
- lista de errores APA en bibliografía
- corrección propuesta para cada uno

## Problemas mayores
- solo problemas que comprometan publicabilidad

## Problemas menores
- mejoras no bloqueantes

## Sobreafirmaciones o falta de evidencia
- afirmaciones que no estén suficientemente apoyadas

## Correcciones accionables
- lista priorizada de cambios concretos que el autor debe hacer

## Dictamen final
- síntesis corta orientada a editor

Manuscrito:
{review_packet}

Referencias generadas:
{reference_packet}

Auditoría editorial determinista previa:
{audit_packet}
"""


def build_verdict_retry_prompt(review_text: str) -> str:
    return f"""Extrae el veredicto editorial de la revisión siguiente.

Debes elegir una única opción real. No copies una plantilla ni una lista de opciones.
Responde con una sola línea exacta y sin explicación adicional, usando exactamente una de estas cuatro formas:
Veredicto: accept
Veredicto: minor revision
Veredicto: major revision
Veredicto: reject

Revisión:
{review_text}
"""


def review_timeout_for_model(model: str) -> int:
    lowered = (model or "").strip().lower()
    if "mimo" in lowered or "qwen" in lowered:
        return 120
    if "gemma" in lowered:
        return 90
    return 90


def review_max_tokens_for_model(model: str) -> int:
    lowered = (model or "").strip().lower()
    if "mimo" in lowered:
        return 6000
    if "qwen" in lowered:
        return 3200
    if "gemma" in lowered:
        return 3600
    return 3200


def review_attempts_for_model(model: str) -> int:
    return 1


@contextmanager
def hard_timeout(seconds: int, message: str):
    """Add a wall-clock timeout around provider calls that keep sockets open."""
    if seconds <= 0 or not hasattr(signal, "setitimer"):
        yield
        return

    def handle_timeout(_signum, _frame):
        raise TimeoutError(message)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer and previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def reviewer_fallback_models(model: str) -> list[str]:
    candidates = list(configured_research_models({}))
    unique: list[str] = []
    for candidate in candidates:
        if not candidate or candidate == model or candidate in unique:
            continue
        unique.append(candidate)
    return unique


def extract_message_text(message: object) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts: list[str] = []
        for item in message:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item)
        return "\n".join(parts).strip()
    return ""


def call_openai_compatible_chat(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: int = 240,
    max_tokens: int = 4000,
) -> tuple[str, str]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un revisor científico estricto, independiente y orientado a exactitud APA. "
                    "No muestres razonamiento privado ni cadena de pensamiento; entrega solo la respuesta final solicitada."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "stream": False,
    }
    normalized_base = base_url.strip().lower()
    is_local = normalized_base.startswith("http://127.0.0.1") or normalized_base.startswith("http://localhost")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    if api_key and not is_local:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    curl_path = shutil.which("curl")
    if curl_path:
        config_path = ""
        payload_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as payload_file:
                payload_path = payload_file.name
                payload_file.write(json.dumps(payload))
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
                config_path = config_file.name
                os.chmod(config_path, 0o600)

                def curl_config_value(value: str) -> str:
                    safe = (value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
                    return f'"{safe}"'

                config_lines = [
                    f"url = {curl_config_value(endpoint)}",
                    'request = "POST"',
                    "silent",
                    "show-error",
                    f"max-time = {timeout + 15}",
                    f"connect-timeout = {min(20, max(5, timeout // 4))}",
                    f"data-binary = {curl_config_value('@' + payload_path)}",
                ]
                for key, value in headers.items():
                    config_lines.append(f"header = {curl_config_value(f'{key}: {value}')}")
                config_file.write("\n".join(config_lines) + "\n")
            completed = subprocess.run(
                [curl_path, "--config", config_path],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout + 25,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"curl error for `{model}`: {detail or f'exit {completed.returncode}'}")
            stdout = completed.stdout
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Hard timeout while calling `{model}` after {timeout + 25}s.") from exc
        finally:
            if config_path:
                pathlib.Path(config_path).unlink(missing_ok=True)
            if payload_path:
                pathlib.Path(payload_path).unlink(missing_ok=True)
    else:
        try:
            with hard_timeout(timeout + 25, f"Hard timeout while calling `{model}` after {timeout + 25}s."):
                with request.urlopen(req, timeout=timeout + 15) as response:
                    stdout = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code} for `{model}`: {detail or exc.reason}") from None
        except error.URLError as exc:
            raise RuntimeError(f"Connection error for `{model}`: {exc.reason}") from None
        except TimeoutError as exc:
            raise RuntimeError(f"Timeout while calling `{model}` after {timeout}s.") from exc
    data = json.loads(stdout)
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = extract_message_text(message.get("content", ""))
    if content:
        return content, "content"
    if extract_message_text(message.get("reasoning", "")):
        raise RuntimeError(f"Model `{model}` returned reasoning without final content.")
    raise RuntimeError(f"Empty response from model `{model}`.")


def build_overview(results: list[ReviewResult]) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat()
    rows = [
        [result.reviewer_id, result.role, result.model, result.status, result.verdict, result.output_path]
        for result in results
    ]
    verdicts = {}
    for result in results:
        verdicts[result.verdict] = verdicts.get(result.verdict, 0) + 1
    verdict_summary = ", ".join(f"{key}: {value}" for key, value in sorted(verdicts.items())) or "sin resultados"
    return "\n".join(
        [
            "# Peer Review Overview",
            "",
            f"- Fecha: {now}",
            f"- Revisiones ejecutadas: {len(results)}",
            f"- Resumen de veredictos: {verdict_summary}",
            "",
            markdown_table(
                ["reviewer_id", "role", "model", "status", "verdict", "output_path"],
                rows,
            ),
            "",
            "## Regla editorial",
            "- Estas revisiones son independientes y buscan reducir sesgo de un único modelo.",
            "- Un desacuerdo entre revisores debe resolverse con una tercera lectura humana o una meta-revisión posterior.",
        ]
    )


def ensure_review_scaffold(review_dir: pathlib.Path) -> None:
    paper_review_dir = review_dir / "paper" / "review"
    base_url = resolve_primary_base_url(review_dir)
    primary = resolve_env_value(review_dir, "HERMES_MODEL_PRIMARY")
    vision = resolve_env_value(review_dir, "HERMES_MODEL_VISION") or primary
    reviewer = resolve_env_value(review_dir, "HERMES_MODEL_REVIEW") or vision
    default_reviewer_models = (
        "reviewer_id,role,model,provider,base_url,focus,enabled,notes\n"
        f'reviewer_a,Revisor A,{reviewer},openai_compatible,{base_url},"Revisión de publicabilidad, trazabilidad metodológica, coherencia argumental y riesgos metodológicos del manuscrito.",yes,Revisión independiente configurada por el operador.\n'
        f'reviewer_b,Revisor B,{vision},openai_compatible,{base_url},"Revisión crítica de consistencia científica, claridad expositiva, soporte visual y sesgos de interpretación.",yes,Contraste visual y metodológico configurado por el operador.\n'
    )
    paths = {
        paper_review_dir / "reviewer-models.csv": default_reviewer_models,
        paper_review_dir / "README.md": """# Peer Review Workspace

Este espacio contiene la revisión cruzada del manuscrito final.

Reglas:
- usar al menos dos modelos revisores distintos al modelo escritor
- guardar cada dictamen por separado
- no mezclar las respuestas antes de conservar el dictamen individual
- tratar los errores APA como bloqueantes

Artefactos:
- `reviewer-models.csv`
- `review-packet/`
- `reviews/*.md`
- `revision-roadmap/`
- `review-manifest.csv`
- `peer-review-overview.md`
""",
        paper_review_dir / "peer-review-overview.md": "# Peer Review Overview\n\n_Aún no se han ejecutado revisiones._\n",
    }
    for path, content in paths.items():
        if not path.exists():
            write_text(path, content)


def build_review_packet_artifact(review_dir: pathlib.Path, review_dir_out: pathlib.Path, manuscript_path: pathlib.Path) -> pathlib.Path:
    output_dir = review_dir_out / "review-packet"
    cmd = [
        os.environ.get("PYTHON", "python3"),
        str(REVIEW_PACKET_SCRIPT),
        str(manuscript_path),
        "--review-dir",
        str(review_dir),
        "--output-dir",
        str(output_dir),
    ]
    run_subprocess(cmd)
    return output_dir


def build_revision_roadmap_artifact(review_dir: pathlib.Path, review_dir_out: pathlib.Path, results: list[ReviewResult]) -> pathlib.Path:
    input_paths: list[pathlib.Path] = []
    for result in results:
        output_rel = (result.output_path or "").strip()
        if not output_rel:
            continue
        path = review_dir / output_rel
        if path.exists():
            input_paths.append(path)
    for extra in (
        review_dir / "paper" / "audit" / "publication-audit.md",
        review_dir / "paper" / "audit" / "publication-gate.md",
    ):
        if extra.exists():
            input_paths.append(extra)
    output_dir = review_dir_out / "revision-roadmap"
    cmd = [
        os.environ.get("PYTHON", "python3"),
        str(REVISION_ROADMAP_SCRIPT),
        *[str(path) for path in input_paths],
        "--output-dir",
        str(output_dir),
    ]
    run_subprocess(cmd)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory does not exist: {review_dir}")

    ensure_review_scaffold(review_dir)
    paper_dir = review_dir / "paper"
    review_dir_out = paper_dir / "review"
    review_models = read_csv_rows(review_dir_out / "reviewer-models.csv")
    manuscript_path = paper_dir / "manuscript" / "publication-ready.md"
    manuscript = read_text(manuscript_path).strip()
    if not manuscript:
        manuscript_path = paper_dir / "manuscript" / "compiled-submission.md"
        manuscript = read_text(manuscript_path).strip()
    references = read_text(paper_dir / "references" / "references.generated.md").strip()
    publication_audit = read_text(paper_dir / "audit" / "publication-audit.md").strip()
    intake_text = "\n\n".join(
        part
        for part in [
            read_text(review_dir / "protocol" / "intake.md"),
            read_text(review_dir / "protocol" / "review-mode.md"),
        ]
        if part.strip()
    )
    if not manuscript:
        raise SystemExit("The compiled manuscript is empty. Run the publication auditor after drafting sections.")

    results: list[ReviewResult] = []
    used_effective_models: set[str] = set()
    review_files_dir = review_dir_out / "reviews"
    review_files_dir.mkdir(parents=True, exist_ok=True)
    prune_stale_review_files(review_files_dir, review_models)
    build_review_packet_artifact(review_dir, review_dir_out, manuscript_path)

    for reviewer in review_models:
        if not boolish(reviewer.get("enabled", "")):
            continue
        reviewer_id = reviewer.get("reviewer_id", "").strip() or "reviewer"
        requested_model = reviewer.get("model", "").strip()
        prompt = build_prompt(reviewer, manuscript, references, publication_audit, intake_text)
        prompt_path = review_files_dir / f"{reviewer_id}.prompt.md"
        response_path = review_files_dir / f"{reviewer_id}.md"
        meta_path = review_files_dir / f"{reviewer_id}.json"
        write_text(prompt_path, prompt)
        status = "ok"
        verdict = "unresolved"
        notes = reviewer.get("notes", "")
        response_text = ""
        model = requested_model
        base_url = ""
        api_key = ""
        attempt_errors: list[str] = []
        candidate_models = [requested_model, *reviewer_fallback_models(requested_model)]
        if used_effective_models:
            preferred = [
                candidate
                for candidate in candidate_models
                if (candidate or "").strip().lower() not in used_effective_models
            ]
            repeated = [
                candidate
                for candidate in candidate_models
                if (candidate or "").strip().lower() in used_effective_models
            ]
            candidate_models = preferred + repeated
        for candidate_model in candidate_models:
            model = candidate_model
            base_url, api_key, base_url_note = resolve_reviewer_endpoint(
                candidate_model,
                reviewer.get("base_url", ""),
                review_dir,
            )
            if not base_url:
                attempt_errors.append(f"{candidate_model}: {base_url_note or 'cloud_runtime_unavailable'}")
                continue
            timeout = review_timeout_for_model(candidate_model)
            max_tokens = review_max_tokens_for_model(candidate_model)
            max_attempts = review_attempts_for_model(candidate_model)
            attempt_notes = notes
            if base_url_note:
                attempt_notes = (attempt_notes + " | " + base_url_note).strip(" |")
            model_succeeded = False
            for attempt_number in range(1, max_attempts + 1):
                try:
                    response_text, channel = call_openai_compatible_chat(
                        base_url,
                        api_key,
                        candidate_model,
                        prompt,
                        timeout=timeout,
                        max_tokens=max_tokens,
                    )
                    notes = attempt_notes
                    if candidate_model != requested_model:
                        notes = (notes + f" | fallback_from={requested_model} | fallback_model={candidate_model}").strip(" |")
                    verdict = extract_verdict(response_text)
                    if verdict == "unresolved":
                        retry_timeout = min(120, max(90, timeout // 3))
                        retry_text, _ = call_openai_compatible_chat(
                            base_url,
                            api_key,
                            candidate_model,
                            build_verdict_retry_prompt(response_text),
                            timeout=retry_timeout,
                            max_tokens=256,
                        )
                        retry_verdict = extract_verdict(retry_text)
                        if retry_verdict != "unresolved":
                            verdict = retry_verdict
                            response_text = response_text.rstrip() + "\n\n## Meta-veredicto\n" + retry_text.strip() + "\n"
                            notes = (notes + " | retry_verdict").strip(" |")
                    if verdict == "unresolved":
                        attempt_errors.append(f"{candidate_model}: invalid_editorial_verdict")
                        continue
                    if not is_structured_review_response(response_text):
                        attempt_errors.append(f"{candidate_model}: malformed_review_response")
                        verdict = "unresolved"
                        response_text = ""
                        continue
                    model_succeeded = True
                    break
                except error.HTTPError as exc:
                    attempt_errors.append(
                        f"{candidate_model}: HTTP {exc.code} {exc.reason} (attempt {attempt_number}/{max_attempts})"
                    )
                    if exc.code in RETRYABLE_HTTP_CODES and attempt_number < max_attempts:
                        time.sleep(20 * attempt_number)
                        continue
                    break
                except Exception as exc:  # noqa: BLE001
                    attempt_errors.append(f"{candidate_model}: {exc} (attempt {attempt_number}/{max_attempts})")
                    message = str(exc).lower()
                    retryable_runtime = (
                        "timed out" in message
                        or "timeout" in message
                        or "connection reset" in message
                        or "returned error: 429" in message
                        or "http 429" in message
                    )
                    if attempt_number < max_attempts and retryable_runtime:
                        sleep_seconds = 45 * attempt_number if "429" in message else 15 * attempt_number
                        time.sleep(sleep_seconds)
                        continue
                    break
            if model_succeeded:
                used_effective_models.add((candidate_model or "").strip().lower())
                time.sleep(8)
                break
        else:
            status = "error"
            response_text = "# {reviewer_id}\n\nError while calling reviewer models.\n\n".format(reviewer_id=reviewer_id)
            response_text += "\n".join(f"- {entry}" for entry in attempt_errors) + "\n"
            notes = (notes + " | RuntimeError").strip(" |")
        write_text(response_path, response_text)
        meta = {
            "reviewer_id": reviewer_id,
            "role": reviewer.get("role", ""),
            "model": model,
            "requested_model": requested_model,
            "provider": reviewer.get("provider", ""),
            "base_url": base_url,
            "status": status,
            "verdict": verdict,
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "prompt_path": str(prompt_path),
            "response_path": str(response_path),
        }
        write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
        results.append(
            ReviewResult(
                reviewer_id=reviewer_id,
                role=reviewer.get("role", ""),
                model=model,
                status=status,
                verdict=verdict,
                output_path=f"paper/review/reviews/{reviewer_id}.md",
                notes=notes,
            )
        )

    write_manifest(review_dir_out / "review-manifest.csv", results)
    write_text(review_dir_out / "peer-review-overview.md", build_overview(results))
    build_revision_roadmap_artifact(review_dir, review_dir_out, results)

    print(f"reviewers_run: {len(results)}")
    for result in results:
        print(f"{result.reviewer_id}: {result.status} {result.verdict}")
    print(f"overview: {review_dir_out / 'peer-review-overview.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
