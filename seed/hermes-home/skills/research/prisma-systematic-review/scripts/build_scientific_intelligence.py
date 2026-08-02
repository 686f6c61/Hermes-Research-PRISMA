#!/usr/bin/env python3
"""Build evidence-position and reading-priority artifacts from extracted studies.

This module deliberately keeps bibliometric influence separate from scientific
eligibility. Its scores only order subsequent reading and verification work;
they never alter screening, critical appraisal, or focal selection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from artifact_contracts import write_json_atomic
from build_security_harness_analysis import build as build_security_harness_analysis

POSITION_FIELDS = [
    "claim_id",
    "comparison_key",
    "raw_comparison",
    "intervention_family",
    "outcome_family",
    "context_family",
    "doi",
    "title",
    "scope",
    "study_design",
    "context",
    "position",
    "outcome_orientation",
    "practical_valence",
    "certainty",
    "key_finding",
    "evidence_snippet",
    "evidence_location",
]

PRIORITY_FIELDS = [
    "reading_rank",
    "doi",
    "title",
    "scope",
    "reading_tier",
    "reading_priority_score",
    "relevance_score",
    "method_transparency_score",
    "evidence_readiness_score",
    "reproducibility_score",
    "contrast_value_score",
    "position",
    "practical_valence",
    "priority_reason",
    "bibliometric_used_in_score",
    "eligibility_effect",
]

MISSING_VALUES = {
    "",
    "na",
    "n/a",
    "none",
    "no reportado",
    "not reported",
    "not specified",
    "unknown",
    "desconocido",
}

MIXED_MARKERS = (
    "mixed result",
    "mixed finding",
    "heterogeneous",
    "heterogene",
    "conditional",
    "depends on",
    "varies by",
    "moderated by",
    "resultados mixtos",
    "hallazgos mixtos",
    "depende de",
    "varia segun",
    "varía según",
)
NULL_MARKERS = (
    "no significant",
    "not significant",
    "no association",
    "no relationship",
    "null effect",
    "did not improve",
    "did not affect",
    "sin efecto",
    "no significativo",
    "no se encontro asociacion",
    "no se encontró asociación",
    "no mejoro",
    "no mejoró",
)
POSITIVE_MARKERS = (
    "positive association",
    "positively associated",
    "increased",
    "increase in",
    "improved",
    "enhanced",
    "higher",
    "beneficial",
    "asociacion positiva",
    "asociación positiva",
    "aumento",
    "incremento",
    "mejoro",
    "mejoró",
    "mayor",
)
NEGATIVE_MARKERS = (
    "negative association",
    "negatively associated",
    "inverse association",
    "decreased",
    "decrease in",
    "reduced",
    "lower",
    "worsened",
    "asociacion negativa",
    "asociación negativa",
    "relacion inversa",
    "relación inversa",
    "disminuyo",
    "disminuyó",
    "redujo",
    "menor",
    "empeoro",
    "empeoró",
)

FAVORABLE_MARKERS = (
    "improved",
    "enhanced",
    "beneficial",
    "more reliable",
    "more accurate",
    "reduced time",
    "reduced latency",
    "reduced cost",
    "reduced error",
    "reduced risk",
    "mejora",
    "mejoró",
    "mayor fiabilidad",
    "mayor precisión",
    "redujo el tiempo",
    "redujo el ciclo",
    "redujo la latencia",
    "redujo los errores",
    "redujo el riesgo",
    "reducción de tiempo",
    "reducción de latencia",
    "redução de tempo",
    "redução de latência",
    "redução drástica",
    "alcanzo una precision",
    "alcanzó una precisión",
    "concordancia sustancial",
    "desempenho promissor",
    "superando",
)

ADVERSE_MARKERS = (
    "worsened",
    "higher error",
    "higher risk",
    "increased burden",
    "increased cost",
    "longer time",
    "empeoró",
    "mayor error",
    "mayor riesgo",
    "aumentó la carga",
    "aumentó el coste",
    "aumento del tiempo",
)

QUALIFICATION_MARKERS = (
    "however",
    "although",
    "limited by",
    "requires further",
    "sin embargo",
    "aunque",
    "limitado por",
    "limitada por",
    "requiere mas",
    "requiere más",
    "no demuestra",
    "preliminary",
    "preliminar",
)

INTERVENTION_FAMILIES = (
    ("multi_agent_system", ("multiagent", "multi-agent", "multi agent", "multiagente", "multi-agente", "sistema de agentes")),
    ("retrieval_augmented_generation", ("retrieval augmented", "retrieval-augmented", " rag ", "pipeline rag")),
    ("reinforcement_learning", ("reinforcement learning", "aprendizaje por refuerzo", "marl")),
    ("large_language_model", ("large language model", "language model", "llm", "modelo de lenguaje")),
    ("machine_learning", ("machine learning", "aprendizaje automatico", "aprendizaje automático", "bert")),
    ("artificial_intelligence_system", ("artificial intelligence", "inteligencia artificial", "sistema de ia", "ia asistid", "ai adoption", "ai use")),
)

OUTCOME_FAMILIES = (
    (
        "attack_success_and_compromise",
        (
            "attack success rate",
            "attack success",
            "asr",
            "tasa de exito del ataque",
            "tasa de éxito del ataque",
            "tasa exito ataque",
            "compromise rate",
        ),
    ),
    (
        "defense_and_detection",
        (
            "defense success rate",
            "defence success rate",
            "tasa de exito de defensa",
            "tasa de éxito de defensa",
            "tasa exito defensa",
            "detection rate",
            "tasa de deteccion",
            "tasa de detección",
            "deteccion de ataques",
            "detección de ataques",
        ),
    ),
    (
        "false_positive_burden",
        (
            "false positive rate",
            "false positive",
            "fpr",
            "tasa de falsos positivos",
            "falsos positivos",
        ),
    ),
    (
        "utility_retention",
        (
            "utility retention",
            "utility impact",
            "task utility",
            "preservacion de utilidad",
            "preservación de utilidad",
            "impacto en utilidad",
        ),
    ),
    (
        "data_leakage_and_privacy",
        (
            "data leakage",
            "data exfiltration",
            "privacy leakage",
            "secret leakage",
            "fuga de datos",
            "filtracion de datos",
            "filtración de datos",
            "tasa de filtraciones",
        ),
    ),
    (
        "efficiency_and_resources",
        (
            "time",
            "tiempo",
            "hour",
            "hours",
            "hora",
            "horas",
            "latency",
            "latencia",
            "cost",
            "coste",
            "costo",
            "workload",
            "carga de trabajo",
            "waste",
            "desperdicio",
            "inactividad",
            "celeridad",
            "deployment",
            "despliegue",
        ),
    ),
    (
        "quality_and_performance",
        (
            "quality",
            "calidad",
            "accuracy",
            "precision",
            "precisión",
            "reliability",
            "fiabilidad",
            "concordance",
            "concordancia",
            "performance",
            "rendimiento",
            "error",
            "coherencia",
        ),
    ),
    (
        "safety_and_risk",
        (
            "risk",
            "riesgo",
            "safety",
            "seguridad",
            "hallucination",
            "alucinacion",
            "alucinación",
            "integrity",
            "integridad",
            "anomal",
        ),
    ),
    (
        "coordination_and_process",
        (
            "coordination",
            "coordinacion",
            "coordinación",
            "planning",
            "planificacion",
            "planificación",
            "decision",
            "decisión",
            "workflow",
            "flujo",
            "process",
            "proceso",
        ),
    ),
    ("trust_and_attitudes", ("trust", "confianza", "attitude", "actitud", "acceptance", "aceptacion", "aceptación")),
    ("health_and_wellbeing", ("health", "salud", "wellbeing", "bienestar", "diagnos", "disease", "enfermedad")),
    ("learning_and_education", ("learning", "aprendizaje", "education", "educacion", "educación", "pedagog")),
    ("economic_and_financial", ("economic", "economico", "económico", "financial", "financiero", "revenue", "ingresos")),
    ("governance_and_compliance", ("governance", "gobernanza", "compliance", "cumplimiento", "regulation", "regulacion")),
    ("adoption_and_behavior", ("adoption", "adopcion", "adopción", "behavior", "behaviour", "conducta", "uso")),
    ("environment_and_sustainability", ("environment", "ambiental", "sustainab", "sostenib", "emission", "emision")),
)

CONTEXT_FAMILIES = (
    ("healthcare", ("health", "salud", "clinical", "clinico", "clínico", "diagnos", "medic", "veterinar", "patient", "paciente")),
    ("industry_and_manufacturing", ("industry", "industrial", "manufactur", "fabricacion", "fabricación", "fabrica", "fábrica", "telecom")),
    ("education", ("education", "educacion", "educación", "teaching", "docen", "student", "estudiante", "pedagog")),
    ("public_sector_and_governance", ("public sector", "sector publico", "sector público", "police", "policia", "policía", "government", "gobierno", "legal", "norma")),
    ("software_engineering", ("software", "code", "codigo", "código", "low-code", "deployment", "despliegue")),
    ("games_and_simulation", ("game", "juego", "gaming", "simulacion", "simulación")),
    ("digital_communication", ("communication", "comunicacion", "comunicación", "social network", "red social", "platform", "plataforma")),
)

HIGHER_IS_BETTER = (
    "quality",
    "calidad",
    "accuracy",
    "precision",
    "precisión",
    "reliability",
    "fiabilidad",
    "concordance",
    "concordancia",
    "efficiency",
    "eficiencia",
    "trust",
    "confianza",
    "learning",
    "aprendizaje",
    "wellbeing",
    "bienestar",
)

LOWER_IS_BETTER = (
    "time",
    "tiempo",
    "latency",
    "latencia",
    "cost",
    "coste",
    "costo",
    "error",
    "risk",
    "riesgo",
    "burden",
    "carga",
    "waste",
    "desperdicio",
    "downtime",
    "inactividad",
    "hallucination",
    "alucinacion",
    "alucinación",
)

FALLBACK_STOPWORDS = {
    "para",
    "sobre",
    "entre",
    "desde",
    "hasta",
    "como",
    "with",
    "from",
    "into",
    "through",
    "system",
    "sistema",
    "study",
    "estudio",
    "model",
    "modelo",
    "based",
    "basado",
    "implementation",
    "implementacion",
}

FAMILY_DISPLAY = {
    "multi_agent_system": "Sistema multiagente",
    "retrieval_augmented_generation": "RAG",
    "reinforcement_learning": "Aprendizaje por refuerzo",
    "large_language_model": "LLM",
    "machine_learning": "Aprendizaje automático",
    "artificial_intelligence_system": "Sistema de IA",
    "efficiency_and_resources": "Eficiencia y recursos",
    "quality_and_performance": "Calidad y rendimiento",
    "safety_and_risk": "Seguridad y riesgo",
    "coordination_and_process": "Coordinación y proceso",
    "trust_and_attitudes": "Confianza y actitudes",
    "health_and_wellbeing": "Salud y bienestar",
    "learning_and_education": "Aprendizaje y educación",
    "economic_and_financial": "Resultado económico",
    "governance_and_compliance": "Gobernanza y cumplimiento",
    "adoption_and_behavior": "Adopción y conducta",
    "environment_and_sustainability": "Sostenibilidad",
    "attack_success_and_compromise": "Éxito del ataque",
    "defense_and_detection": "Defensa y detección",
    "false_positive_burden": "Falsos positivos",
    "utility_retention": "Utilidad preservada",
    "data_leakage_and_privacy": "Fuga de datos y privacidad",
}


def now_iso() -> str:
    """Return a timezone-aware generation timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def normalize(value: object) -> str:
    """Fold a value for conservative marker and missing-value matching."""
    folded = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in folded if not unicodedata.combining(char)).lower()


def clean_text(value: object) -> str:
    """Collapse whitespace without rewriting source evidence."""
    return " ".join(str(value or "").split())


def clean_doi(value: object) -> str:
    """Return a public DOI or an empty string."""
    doi = clean_text(value).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi if doi.startswith("10.") and "/" in doi else ""


def reported(value: object) -> bool:
    """Return whether an extracted field contains material information."""
    return normalize(value).strip() not in MISSING_VALUES


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    """Read one CSV using UTF-8 with optional BOM support."""
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: pathlib.Path, fields: list[str], rows: Iterable[dict[str, object]]) -> pathlib.Path:
    """Write a deterministic CSV artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def parse_score(value: object, default: int) -> int:
    """Parse and clamp a percentage-like score."""
    try:
        return max(0, min(100, int(round(float(str(value).strip())))))
    except (TypeError, ValueError):
        return default


def shortlist_index(review_dir: pathlib.Path) -> dict[str, dict[str, str]]:
    """Index focal-selection metadata by DOI without reusing internal IDs."""
    rows = read_csv(review_dir / "selection" / "ultraquality-shortlist.csv")
    malformed = [
        row
        for row in rows
        if row.get("record_id")
        and not any(
            clean_text(row.get(field))
            for field in ("assigned_doi", "title_original", "selected_for_final_n", "ultraquality_score")
        )
    ]
    if len(malformed) > max(5, len(rows) // 4):
        raise RuntimeError(
            "selection/ultraquality-shortlist.csv is malformed: "
            f"{len(malformed)} of {len(rows)} rows contain no material selection fields."
        )
    return {
        doi: row
        for row in rows
        if (doi := clean_doi(row.get("assigned_doi") or row.get("doi")))
    }


def raw_comparison(row: dict[str, str]) -> str:
    """Build the source-facing comparison without changing extracted wording."""
    threat = clean_text(row.get("threat_model") or row.get("attack_type"))
    control = clean_text(row.get("control_architecture") or row.get("security_harness_name"))
    if reported(threat) and reported(control):
        return f"{threat} -> {control}"[:220]
    independent = clean_text(row.get("variables_independent"))
    dependent = clean_text(row.get("variables_dependent"))
    if reported(independent) and reported(dependent):
        return f"{independent} -> {dependent}"[:220]
    task = clean_text(row.get("tasks_or_domains"))
    outcome = clean_text(row.get("key_findings"))
    if reported(task):
        return task[:220]
    theory = clean_text(row.get("theory_framework"))
    if reported(theory):
        return theory[:220]
    title = clean_text(row.get("title_original") or row.get("title_en") or row.get("title_es"))
    tokens = [token for token in re.findall(r"[A-Za-zÀ-ÿ0-9-]+", title) if len(token) > 3]
    return " ".join(tokens[:8]) or outcome[:220] or "comparación no especificada"


def lexical_fallback(text: str, prefix: str) -> str:
    """Create a stable fallback family from informative source tokens."""
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalize(text))
        if len(token) > 3 and token not in FALLBACK_STOPWORDS
    ]
    unique: list[str] = []
    for token in tokens:
        if token not in unique:
            unique.append(token)
    return f"{prefix}:{'_'.join(unique[:3])}" if unique else f"{prefix}:unspecified"


def semantic_families(
    text: str,
    rules: tuple[tuple[str, tuple[str, ...]], ...],
    prefix: str,
) -> str:
    """Map wording to broad, reusable families while retaining a fallback."""
    folded = f" {normalize(text)} "
    matches = [
        label
        for label, markers in rules
        if any(f" {normalize(marker).strip()} " in folded or normalize(marker).strip() in folded for marker in markers)
    ]
    return "+".join(matches[:2]) if matches else lexical_fallback(text, prefix)


def family_display(value: str) -> str:
    """Translate internal family identifiers into compact reader labels."""
    labels: list[str] = []
    for item in value.split("+"):
        if item in FAMILY_DISPLAY:
            labels.append(FAMILY_DISPLAY[item])
            continue
        fallback = item.split(":", 1)[-1].replace("_", " ").strip()
        labels.append(fallback[:36].capitalize() or "No especificado")
    return " + ".join(labels)


def comparison_parts(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    """Return canonical and raw comparison units for cross-study grouping."""
    raw = raw_comparison(row)
    independent = clean_text(row.get("variables_independent"))
    dependent = clean_text(row.get("variables_dependent"))
    intervention_text = " ".join(
        filter(
            None,
            [
                independent if reported(independent) else "",
                clean_text(row.get("control_architecture")),
                clean_text(row.get("security_harness_name")),
                clean_text(row.get("enforcement_point")),
                clean_text(row.get("models_or_systems_studied")),
                clean_text(row.get("method_used")),
                clean_text(row.get("key_findings")) if not reported(independent) else "",
            ],
        )
    )
    outcome_text = (
        dependent
        if reported(dependent)
        else " ".join(
            filter(
                None,
                [
                    clean_text(row.get("key_findings")),
                    clean_text(row.get("security_metrics")),
                    clean_text(row.get("security_conclusion")),
                    clean_text(row.get("tasks_or_domains")),
                ],
            )
        )
    )
    intervention = semantic_families(intervention_text, INTERVENTION_FAMILIES, "intervention")
    outcome = semantic_families(outcome_text, OUTCOME_FAMILIES, "outcome")
    context_text = " ".join(
        filter(
            None,
            [
                clean_text(row.get("tasks_or_domains")),
                clean_text(row.get("threat_model")),
                clean_text(row.get("attack_type")),
                clean_text(row.get("attacker_adaptivity")),
                clean_text(row.get("evaluation_setting")),
                clean_text(row.get("sample_description")),
                clean_text(row.get("unit_of_analysis")),
                clean_text(row.get("title_original")),
            ],
        )
    )
    context = semantic_families(context_text, CONTEXT_FAMILIES, "context")
    return f"{intervention} -> {outcome}", raw, intervention, outcome, context


def evidence_position(row: dict[str, str]) -> str:
    """Classify reported direction conservatively without inventing a claim."""
    text = normalize(
        " ".join(
            [
                clean_text(row.get("key_findings")),
                clean_text(row.get("evidence_snippet")),
                clean_text(row.get("variables_dependent")),
                clean_text(row.get("variables_independent")),
            ]
        )
    )
    has_mixed = any(normalize(marker) in text for marker in MIXED_MARKERS)
    has_null = any(normalize(marker) in text for marker in NULL_MARKERS)
    has_positive = any(normalize(marker) in text for marker in POSITIVE_MARKERS)
    has_negative = any(normalize(marker) in text for marker in NEGATIVE_MARKERS)
    if has_mixed or (has_positive and has_negative):
        return "mixed_or_conditional"
    if has_null:
        return "null_finding"
    if has_positive:
        return "positive_association"
    if has_negative:
        return "negative_association"
    work_type = normalize(row.get("work_type"))
    if any(marker in work_type for marker in ("review", "theor", "concept", "framework")):
        return "descriptive_or_theoretical"
    return "direction_unclear"


def outcome_orientation(row: dict[str, str]) -> str:
    """State whether a higher or lower outcome is normally desirable."""
    text = normalize(
        " ".join(
            [
                clean_text(row.get("variables_dependent")),
                clean_text(row.get("key_findings")),
            ]
        )
    )
    higher = any(normalize(marker) in text for marker in HIGHER_IS_BETTER)
    lower = any(normalize(marker) in text for marker in LOWER_IS_BETTER)
    if higher and lower:
        return "mixed_or_multidimensional"
    if higher:
        return "higher_is_better"
    if lower:
        return "lower_is_better"
    return "neutral_or_contextual"


def practical_valence(row: dict[str, str], position: str, orientation: str) -> str:
    """Separate statistical direction from whether the reported change helps."""
    text = normalize(" ".join([clean_text(row.get("key_findings")), clean_text(row.get("evidence_snippet"))]))
    favorable = any(normalize(marker) in text for marker in FAVORABLE_MARKERS)
    adverse = any(normalize(marker) in text for marker in ADVERSE_MARKERS)
    qualified = any(normalize(marker) in text for marker in QUALIFICATION_MARKERS)
    if position == "descriptive_or_theoretical":
        return "not_applicable"
    if position == "null_finding":
        return "no_detectable_change"
    if position == "mixed_or_conditional":
        return "tradeoff_or_mixed"
    if favorable and adverse:
        return "tradeoff_or_mixed"
    if favorable:
        return "favorable_but_qualified" if qualified else "favorable"
    if adverse:
        return "adverse"
    if orientation == "mixed_or_multidimensional":
        return "tradeoff_or_contextual"
    if position == "positive_association":
        return "favorable" if orientation == "higher_is_better" else "adverse" if orientation == "lower_is_better" else "contextual"
    if position == "negative_association":
        return "favorable" if orientation == "lower_is_better" else "adverse" if orientation == "higher_is_better" else "contextual"
    return "unclear"


def certainty(row: dict[str, str]) -> str:
    """Convert extraction confidence and anchoring into a cautious label."""
    confidence = parse_score(row.get("extraction_confidence"), 60)
    anchored = reported(row.get("evidence_snippet")) and reported(row.get("evidence_location"))
    if confidence >= 85 and anchored:
        return "high"
    if confidence >= 70 and reported(row.get("evidence_snippet")):
        return "medium"
    return "low"


def claim_rows(review_dir: pathlib.Path) -> list[dict[str, str]]:
    """Create one evidence-position row per DOI-valid extracted study."""
    shortlist = shortlist_index(review_dir)
    output: list[dict[str, str]] = []
    for row in read_csv(review_dir / "extraction" / "extraction-table.csv"):
        doi = clean_doi(row.get("assigned_doi") or row.get("doi"))
        if not doi:
            continue
        selection = shortlist.get(doi, {})
        scope = "focal" if normalize(selection.get("selected_for_final_n")) in {"yes", "si", "sí", "true", "1"} else "included_context"
        finding = clean_text(row.get("key_findings"))
        snippet = clean_text(row.get("evidence_snippet"))
        key, raw, intervention, outcome, context_family = comparison_parts(row)
        position = evidence_position(row)
        orientation = outcome_orientation(row)
        digest = hashlib.sha256(f"{doi}\n{key}\n{finding}\n{snippet}".encode()).hexdigest()[:12]
        output.append(
            {
                "claim_id": f"evidence-{digest}",
                "comparison_key": key,
                "raw_comparison": raw,
                "intervention_family": intervention,
                "outcome_family": outcome,
                "context_family": context_family,
                "doi": doi,
                "title": clean_text(row.get("title_original") or row.get("title_en") or row.get("title_es")),
                "scope": scope,
                "study_design": clean_text(
                    row.get("design_detail") or row.get("empirical_type") or row.get("method_used")
                ),
                "context": clean_text(
                    row.get("countries") or row.get("sample_description") or row.get("tasks_or_domains")
                ),
                "position": position,
                "outcome_orientation": orientation,
                "practical_valence": practical_valence(row, position, orientation),
                "certainty": certainty(row),
                "key_finding": finding,
                "evidence_snippet": snippet,
                "evidence_location": clean_text(row.get("evidence_location")),
            }
        )
    return sorted(output, key=lambda row: (row["comparison_key"].casefold(), row["doi"]))


def group_status(positions: set[str], count: int, contexts: set[str]) -> str:
    """Describe whether a comparison converges, conflicts, or remains open."""
    directional = positions & {"positive_association", "negative_association"}
    if len(directional) > 1:
        return "directional_disagreement"
    if directional and "null_finding" in positions:
        return "inconsistent_evidence"
    if directional and "mixed_or_conditional" in positions:
        return "qualified_pattern"
    if len(directional) == 1 and count >= 2:
        return "convergence" if len(contexts) == 1 else "cross_context_alignment"
    if positions <= {"descriptive_or_theoretical", "direction_unclear"} and count >= 2:
        return "descriptive_alignment"
    if positions <= {"descriptive_or_theoretical", "direction_unclear"}:
        return "open_question"
    return "insufficient_evidence"


def evidence_summary(rows: list[dict[str, str]]) -> dict[str, object]:
    """Summarize comparison-level convergence without pooling unlike studies."""
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["comparison_key"]].append(row)
    comparisons: list[dict[str, object]] = []
    for key, members in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        positions = {member["position"] for member in members}
        contexts = {member["context_family"] for member in members}
        comparisons.append(
            {
                "comparison_key": key,
                "comparison_label": (
                    f"{family_display(members[0]['intervention_family'])} → "
                    f"{family_display(members[0]['outcome_family'])}"
                ),
                "studies": len(members),
                "status": group_status(positions, len(members), contexts),
                "positions": sorted(positions),
                "context_families": sorted(contexts),
                "dois": sorted({member["doi"] for member in members}),
            }
        )
    status_counts: dict[str, int] = defaultdict(int)
    for comparison in comparisons:
        status_counts[str(comparison["status"])] += 1
    domain_members: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        for domain in row["outcome_family"].split("+"):
            domain_members[domain].append(row)
    outcome_domains = [
        {
            "outcome_family": domain,
            "outcome_label": family_display(domain),
            "studies": len(members),
            "claim_status": "cross_study_signal" if len(members) >= 2 else "isolated_signal",
            "positions": sorted({member["position"] for member in members}),
            "practical_valence": sorted({member["practical_valence"] for member in members}),
            "dois": sorted({member["doi"] for member in members}),
        }
        for domain, members in sorted(domain_members.items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    return {
        "schema_version": "hermes.evidence-position-synthesis/v1",
        "generated_at": now_iso(),
        "scientific_boundary": (
            "Positions are extracted direction labels, not causal judgments. "
            "Unlike comparison units are never pooled automatically."
        ),
        "studies": len(rows),
        "comparisons": len(comparisons),
        "status_counts": dict(sorted(status_counts.items())),
        "comparison_groups": comparisons,
        "outcome_domains": outcome_domains,
    }


def method_transparency(row: dict[str, str], selection: dict[str, str]) -> int:
    """Score whether the study exposes enough method to deserve early reading."""
    explicit = [
        row.get("method_used"),
        row.get("design_detail"),
        row.get("sample_description") or row.get("sample_size"),
        row.get("baselines_or_comparators"),
        row.get("instruments_or_scales"),
    ]
    coverage = sum(1 for value in explicit if reported(value))
    derived = 35 + coverage * 13
    return parse_score(selection.get("methodological_quality_score"), min(100, derived))


def evidence_readiness(row: dict[str, str]) -> int:
    """Score material anchoring, not the desirability of a reported result."""
    score = 20
    if reported(row.get("key_findings")):
        score += 20
    if reported(row.get("evidence_snippet")):
        score += 30
    if reported(row.get("evidence_location")):
        score += 20
    score += round(parse_score(row.get("extraction_confidence"), 60) * 0.10)
    return min(100, score)


def reproducibility_score(row: dict[str, str]) -> int:
    """Estimate reported reproducibility signals without executing source code."""
    fields = [
        row.get("method_used"),
        row.get("benchmark_dataset_or_corpus"),
        row.get("baselines_or_comparators"),
        row.get("models_or_systems_studied"),
        row.get("tasks_or_domains"),
    ]
    score = 15 + 14 * sum(1 for value in fields if reported(value))
    text = normalize(" ".join(clean_text(row.get(field)) for field in ("notes", "key_findings", "evidence_snippet")))
    if any(marker in text for marker in ("github", "repository", "code available", "source code", "codigo")):
        score += 15
    return min(100, score)


def reading_priority_rows(
    review_dir: pathlib.Path,
    positions: list[dict[str, str]],
    summary: dict[str, object],
) -> list[dict[str, object]]:
    """Rank reading attention while proving that bibliography has zero weight."""
    shortlist = shortlist_index(review_dir)
    position_by_doi = {row["doi"]: row["position"] for row in positions}
    valence_by_doi = {row["doi"]: row["practical_valence"] for row in positions}
    status_by_key = {
        str(group["comparison_key"]): str(group["status"])
        for group in summary.get("comparison_groups", [])
        if isinstance(group, dict)
    }
    key_by_doi = {row["doi"]: row["comparison_key"] for row in positions}
    contrast_base = {
        "mixed_or_conditional": 85,
        "null_finding": 80,
        "negative_association": 70,
        "positive_association": 50,
        "descriptive_or_theoretical": 35,
        "direction_unclear": 25,
    }
    rows: list[dict[str, object]] = []
    for source in read_csv(review_dir / "extraction" / "extraction-table.csv"):
        doi = clean_doi(source.get("assigned_doi") or source.get("doi"))
        if not doi:
            continue
        selection = shortlist.get(doi, {})
        scope = "focal" if normalize(selection.get("selected_for_final_n")) in {"yes", "si", "sí", "true", "1"} else "included_context"
        position = position_by_doi.get(doi, "direction_unclear")
        contrast = contrast_base[position]
        if status_by_key.get(key_by_doi.get(doi, "")) in {"directional_disagreement", "inconsistent_evidence"}:
            contrast = 100
        relevance = parse_score(selection.get("relevance_score"), 70)
        method = method_transparency(source, selection)
        evidence = evidence_readiness(source)
        reproducibility = reproducibility_score(source)
        score = round(
            relevance * 0.30
            + method * 0.25
            + evidence * 0.20
            + reproducibility * 0.15
            + contrast * 0.10,
            2,
        )
        reasons = [
            f"relevancia={relevance}",
            f"método={method}",
            f"evidencia={evidence}",
            f"reproducibilidad={reproducibility}",
            f"contraste={contrast}",
        ]
        rows.append(
            {
                "reading_rank": 0,
                "doi": doi,
                "title": clean_text(source.get("title_original") or source.get("title_en") or source.get("title_es")),
                "scope": scope,
                "reading_tier": "",
                "reading_priority_score": score,
                "relevance_score": relevance,
                "method_transparency_score": method,
                "evidence_readiness_score": evidence,
                "reproducibility_score": reproducibility,
                "contrast_value_score": contrast,
                "position": position,
                "practical_valence": valence_by_doi.get(doi, "unclear"),
                "priority_reason": "; ".join(reasons),
                "bibliometric_used_in_score": "no",
                "eligibility_effect": "none",
            }
        )
    rows.sort(key=lambda row: (-float(row["reading_priority_score"]), str(row["doi"])))
    for index, row in enumerate(rows, start=1):
        row["reading_rank"] = index
        percentile = index / max(len(rows), 1)
        row["reading_tier"] = "read_first" if percentile <= 0.25 else "standard" if percentile <= 0.75 else "later"
    return rows


def write_reader_summary(
    path: pathlib.Path,
    summary: dict[str, object],
    priority_rows: list[dict[str, object]],
) -> pathlib.Path:
    """Write a compact scientific interpretation guide."""
    status_counts = summary.get("status_counts") or {}
    lines = [
        "# Posiciones de evidencia y prioridad de lectura",
        "",
        "Esta capa separa dos tareas que no deben confundirse: interpretar cómo se posicionan los hallazgos "
        "y decidir qué documentos merecen antes una lectura o verificación más costosa.",
        "",
        "Las etiquetas de dirección no son juicios causales. Los grupos con unidades de comparación distintas "
        "no se agregan automáticamente, y ninguna puntuación de esta carpeta modifica inclusión, exclusión, "
        "evaluación crítica ni selección focal.",
        "",
        "## Estado del mapa de evidencia",
        "",
        f"- Estudios con posición materializada: {summary.get('studies', 0)}",
        f"- Unidades de comparación: {summary.get('comparisons', 0)}",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(
        [
            "",
            "## Qué leer primero",
            "",
            "| Rank | DOI | Tier | Score | Dirección | Lectura práctica |",
            "|---:|---|---|---:|---|---|",
        ]
    )
    for row in priority_rows[:20]:
        lines.append(
            f"| {row['reading_rank']} | {row['doi']} | {row['reading_tier']} | "
            f"{row['reading_priority_score']} | {row['position']} | {row['practical_valence']} |"
        )
    lines.extend(
        [
            "",
            "La fórmula de prioridad es `0,30 relevancia + 0,25 transparencia metodológica + "
            "0,20 evidencia localizada + 0,15 reproducibilidad reportada + 0,10 valor de contraste`. "
            "Citas, PageRank, centralidad y prestigio editorial tienen peso cero.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build(review_dir: pathlib.Path) -> dict[str, object]:
    """Build the complete scientific-intelligence artifact set."""
    positions = claim_rows(review_dir)
    summary = evidence_summary(positions)
    priority = reading_priority_rows(review_dir, positions, summary)
    evidence_dir = review_dir / "analysis" / "evidence"
    write_csv(evidence_dir / "claim-position-matrix.csv", POSITION_FIELDS, positions)
    write_json_atomic(evidence_dir / "evidence-position-summary.json", summary)
    write_csv(review_dir / "analysis" / "reading-priority.csv", PRIORITY_FIELDS, priority)
    write_reader_summary(evidence_dir / "consensus-disagreements-open-questions.md", summary, priority)
    security_analysis = build_security_harness_analysis(review_dir)
    result = {
        "schema_version": "hermes.scientific-intelligence/v1",
        "generated_at": now_iso(),
        "positions": len(positions),
        "reading_priorities": len(priority),
        "bibliometric_used_in_score": False,
        "eligibility_effect": "none",
        "security_harness_analysis": security_analysis,
        "artifacts": [
            "analysis/evidence/claim-position-matrix.csv",
            "analysis/evidence/evidence-position-summary.json",
            "analysis/evidence/consensus-disagreements-open-questions.md",
            "analysis/reading-priority.csv",
            *security_analysis.get("artifacts", []),
        ],
    }
    write_json_atomic(review_dir / "analysis" / "scientific-intelligence.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    if not review_dir.is_dir():
        raise SystemExit(f"Review directory not found: {review_dir}")
    result = build(review_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
