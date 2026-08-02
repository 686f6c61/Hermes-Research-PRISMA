#!/usr/bin/env python3
"""Build comparison artifacts for reviews of AI security harnesses.

The analysis is intentionally conservative. It reports whether studies expose
the information needed for a fair comparison, but it never converts unlike
threat models, baselines, or metrics into a synthetic winner.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

from artifact_contracts import write_json_atomic

COMPARISON_FIELDS = [
    "doi",
    "title",
    "scope",
    "work_type",
    "study_design",
    "security_harness_name",
    "control_family",
    "control_architecture",
    "enforcement_point",
    "threat_family",
    "threat_model",
    "attack_type",
    "attacker_adaptivity",
    "evaluation_setting",
    "baselines_or_comparators",
    "security_metrics",
    "attack_success_rate",
    "false_positive_rate",
    "utility_impact",
    "latency_overhead",
    "cost_overhead",
    "robustness_evidence",
    "failure_modes",
    "code_or_artifact_availability",
    "security_conclusion",
    "evidence_snippet",
    "evidence_location",
    "security_effect_evidence",
    "operational_tradeoff_evidence",
    "comparison_readiness",
    "dominance_status",
    "dominance_reason",
]

FRONTIER_FIELDS = [
    "threat_family",
    "control_family",
    "studies",
    "dois",
    "with_explicit_baseline",
    "with_adaptive_attacker",
    "with_security_metric",
    "with_attack_success_rate",
    "with_false_positive_rate",
    "with_utility_impact",
    "with_latency_or_cost",
    "with_robustness_evidence",
    "with_failure_modes",
    "with_open_artifact",
    "frontier_status",
    "interpretation",
]

MISSING_VALUES = {
    "",
    "na",
    "n/a",
    "none",
    "no reportado",
    "no aplica",
    "not reported",
    "not applicable",
    "not specified",
    "unknown",
    "desconocido",
}

THREAT_RULES = (
    (
        "prompt_injection",
        (
            "prompt injection",
            "indirect injection",
            "inyeccion de instrucciones",
            "inyeccion indirecta",
            "inyeccion de prompts",
        ),
    ),
    ("jailbreak", ("jailbreak", "guardrail bypass", "policy bypass")),
    (
        "tool_poisoning_or_misuse",
        (
            "tool misuse",
            "unsafe tool",
            "tool abuse",
            "function call",
            "tool poisoning",
            "tool description poisoning",
            "descriptor",
            "herramienta maliciosa",
            "envenenamiento de herramientas",
            "envenenamiento de descripciones",
        ),
    ),
    (
        "memory_or_retrieval_poisoning",
        (
            "memory poisoning",
            "retrieval poisoning",
            "rag poisoning",
            "persistent state",
            "envenenamiento de memoria",
            "envenenamiento de rag",
            "estado persistente",
            "gusano persistente",
        ),
    ),
    (
        "data_exfiltration",
        (
            "exfiltration",
            "data leakage",
            "privacy leakage",
            "secret leakage",
            "exfiltracion",
            "fuga de datos",
            "fugas de privacidad",
        ),
    ),
    (
        "privilege_or_identity_abuse",
        (
            "privilege escalation",
            "unauthorized action",
            "identity spoofing",
            "escalada de privilegios",
            "accion no autorizada",
            "suplantacion",
        ),
    ),
    ("harmful_output", ("harmful output", "unsafe generation", "toxicity", "harmful content")),
    ("model_or_agent_manipulation", ("agent hijack", "model manipulation", "goal hijack")),
)

CONTROL_RULES = (
    (
        "activation_or_representation_monitor",
        (
            "activation",
            "hidden state",
            "representation",
            "embedding",
            "refusal direction",
            "linear probe",
            "curvature",
            "intrinsic dimension",
            "circuit breaker",
            "activaciones",
            "representaciones",
            "direccion de rechazo",
        ),
    ),
    (
        "cryptographic_or_structural_containment",
        (
            "cryptographic",
            "authenticated envelope",
            "token containment",
            "containment",
            "hmac",
            "xml",
            "criptografic",
            "contencion",
            "envoltura",
        ),
    ),
    (
        "provenance_or_information_flow",
        (
            "provenance",
            "information flow",
            "non-malleable",
            "origin binding",
            "trust lattice",
            "procedencia",
            "flujo de informacion",
            "origen",
            "reticulo de confianza",
        ),
    ),
    (
        "tool_authorization",
        (
            "tool authorization",
            "tool permission",
            "least privilege",
            "capability control",
            "tool policy",
            "authorization graph",
            "capability contract",
            "autorizacion",
            "permiso",
            "contrato de capacidad",
            "contratos de capacidad",
            "grafo de autorizacion",
        ),
    ),
    (
        "causal_or_counterfactual_verification",
        (
            "causal",
            "counterfactual",
            "shadow replay",
            "masked re-execution",
            "re-execution",
            "contrafactual",
            "re-ejecucion",
            "reproduccion en sombra",
            "atribucion",
        ),
    ),
    (
        "memory_or_retrieval_control",
        (
            "memory",
            "retrieval",
            "rag",
            "context filtering",
            "context isolation",
            "memoria",
            "recuperacion",
            "sanitization",
            "sanitizacion",
        ),
    ),
    (
        "input_filtering",
        (
            "input filter",
            "prompt filter",
            "input guard",
            "input validation",
            "pre-processing",
            "preproces",
            "canonicalization",
            "canonicalizacion",
            "filtro de entrada",
            "sanitizacion de texto",
        ),
    ),
    (
        "output_filtering",
        (
            "output filter",
            "response filter",
            "output guard",
            "post-processing",
            "post-proces",
            "filtro de salida",
            "clasificador de intercambio",
        ),
    ),
    (
        "policy_or_intent_guardrail",
        (
            "policy guard",
            "guardrail",
            "policy engine",
            "intent graph",
            "intent alignment",
            "control graph",
            "grafo de intenciones",
            "alineacion de tarea",
            "reglas confirmadas",
            "adjudicator",
        ),
    ),
    (
        "runtime_trajectory_monitor",
        (
            "runtime monitor",
            "monitoring",
            "trajectory",
            "detector",
            "verifier",
            "monitor",
            "trayectoria",
            "verificador",
            "supervision",
        ),
    ),
    ("sandboxing_or_isolation", ("sandbox", "isolation", "container", "aislamiento")),
    (
        "multi_layer_defense",
        (
            "multi-layer",
            "multilayer",
            "defense in depth",
            "pipeline",
            "layered",
            "en capas",
            "doble capa",
            "cascada",
        ),
    ),
)


def now_iso() -> str:
    """Return a stable UTC timestamp for audit metadata."""
    return datetime.now(timezone.utc).isoformat()


def normalize(value: object) -> str:
    """Normalize text for deterministic matching."""
    folded = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", folded.casefold()).strip()


def clean(value: object) -> str:
    """Collapse whitespace while preserving reader-facing wording."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def reported(value: object) -> bool:
    """Return whether a field contains material rather than a missing marker."""
    normalized = normalize(value)
    if normalized in MISSING_VALUES:
        return False
    missing_prefixes = tuple(
        f"{marker}{separator}"
        for marker in MISSING_VALUES
        if marker
        for separator in (" ", ":", "(", "-", ";")
    )
    return not normalized.startswith(missing_prefixes)


def evidence_level(value: object) -> str:
    """Separate quantified results from qualitative signals and mere mentions."""
    if not reported(value):
        return "missing"
    normalized = normalize(value)
    unit_pattern = re.compile(
        r"(?:\d+(?:[.,]\d+)?\s*(?:%|ms\b|milliseconds?\b|s\b|seconds?\b|"
        r"tokens?\b|points?\b|pp\b|x\b|times?\b|usd\b|eur\b|"
        r"false positives?\b|falsos positivos?\b))|"
        r"(?:\b(?:asr|fpr|accuracy|precision|recall|rate|false positive|"
        r"falso positivo|utility|latency|cost|"
        r"overhead|throughput)\b[^.;\n]{0,32}\d+(?:[.,]\d+)?)"
    )
    if unit_pattern.search(normalized):
        return "quantified"
    directional_terms = (
        "increase",
        "decrease",
        "reduce",
        "improve",
        "outperform",
        "higher",
        "lower",
        "minimal",
        "notable",
        "negligible",
        "worse",
        "better",
        "aument",
        "reduc",
        "mejor",
        "super",
        "inferior",
        "mayor",
        "menor",
        "minim",
        "notable",
        "despreciable",
    )
    if any(term in normalized for term in directional_terms):
        return "qualitative"
    return "mention_only"


def strongest_evidence_level(values: list[object]) -> str:
    """Return the strongest evidence level across related fields."""
    levels = [evidence_level(value) for value in values]
    for level in ("quantified", "qualitative", "mention_only", "missing"):
        if level in levels:
            return level
    return "missing"


def adaptive_attacker_reported(value: object) -> bool:
    """Count adaptive attackers, not merely a populated adaptivity field."""
    normalized = normalize(value)
    if not reported(value):
        return False
    non_adaptive = (
        "no adaptativo",
        "non-adaptive",
        "non adaptive",
        "static",
        "estatico",
        "estatica",
        "predefin",
    )
    return ("adapt" in normalized or "red team" in normalized) and not any(
        marker in normalized for marker in non_adaptive
    )


def open_artifact_reported(value: object) -> bool:
    """Require a positive artifact availability signal."""
    normalized = normalize(value)
    if not reported(value):
        return False
    negative = ("no se", "sin codigo", "sin artefact", "not available", "unavailable")
    if any(normalized.startswith(marker) for marker in negative):
        return False
    positive = ("http", "github", "code", "codigo", "artefact", "open source", "disponible", "available", "si")
    return any(marker in normalized for marker in positive)


def clean_doi(value: object) -> str:
    """Return a bare DOI identity."""
    doi = clean(value)
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    doi = doi.casefold()
    return re.sub(r"^(10\.48550/arxiv\..+?)v\d+$", r"\1", doi)


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    """Read a CSV file as dictionaries."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: pathlib.Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    """Write a stable UTF-8 CSV artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def review_is_security_focused(review_dir: pathlib.Path) -> bool:
    """Detect the security profile from protocol material."""
    protocol_text = " ".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted((review_dir / "protocol").glob("*"))
        if path.is_file() and path.suffix in {".md", ".json"}
    )
    normalized = normalize(protocol_text)
    markers = (
        "security harness",
        "harnesses de seguridad",
        "prompt injection",
        "jailbreak",
        "tool misuse",
        "fuga de datos",
    )
    return any(marker in normalized for marker in markers)


def classify(text: str, rules: tuple[tuple[str, tuple[str, ...]], ...], fallback: str) -> str:
    """Map source wording to a broad comparison family."""
    normalized = normalize(text)
    matches = [
        label
        for label, markers in rules
        if any(normalize(marker) in normalized for marker in markers)
    ]
    return "+".join(matches[:2]) if matches else fallback


def shortlist_scope(review_dir: pathlib.Path) -> dict[str, str]:
    """Map DOI identities to focal or contextual scope."""
    scopes: dict[str, str] = {}
    for row in read_csv(review_dir / "selection" / "ultraquality-shortlist.csv"):
        doi = clean_doi(row.get("assigned_doi") or row.get("doi"))
        if not doi:
            continue
        selected = normalize(row.get("selected_for_final_n")) in {"yes", "si", "true", "1"}
        scopes[doi] = "focal" if selected else "included_context"
    return scopes


def comparison_readiness(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    """Classify whether a study can support a security comparison."""
    threat_ready = reported(row.get("threat_model") or row.get("attack_type"))
    control_ready = reported(row.get("control_architecture") or row.get("security_harness_name"))
    baseline_ready = reported(row.get("baselines_or_comparators"))
    security_effect = strongest_evidence_level(
        [
            row.get("attack_success_rate"),
            row.get("false_positive_rate"),
            row.get("security_conclusion"),
        ]
    )
    operational_tradeoff = strongest_evidence_level(
        [
            row.get("false_positive_rate"),
            row.get("utility_impact"),
            row.get("latency_overhead"),
            row.get("cost_overhead"),
        ]
    )
    metric_ready = reported(row.get("security_metrics")) and security_effect == "quantified"
    tradeoff_ready = operational_tradeoff == "quantified"
    robustness_ready = reported(row.get("robustness_evidence"))
    core_ready = threat_ready and control_ready and baseline_ready and metric_ready
    if core_ready and tradeoff_ready and robustness_ready:
        return (
            "frontier_ready",
            "conditional_dominance_candidate",
            "Reports threat, control, baseline, quantified security outcome, quantified operational "
            "trade-off, and robustness evidence; source-level metric equivalence still requires verification.",
            security_effect,
            operational_tradeoff,
        )
    if core_ready and tradeoff_ready:
        return (
            "tradeoff_ready",
            "comparison_candidate",
            "Reports a quantified security effect and trade-off, but robustness is incomplete.",
            security_effect,
            operational_tradeoff,
        )
    if core_ready:
        return (
            "security_effect_ready",
            "security_only_comparison",
            "Supports a quantified security-effect comparison but not a defensible overall winner because "
            "quantified trade-offs are absent.",
            security_effect,
            operational_tradeoff,
        )
    missing = []
    if not threat_ready:
        missing.append("threat")
    if not control_ready:
        missing.append("control")
    if not baseline_ready:
        missing.append("baseline")
    if not metric_ready:
        missing.append("quantified security outcome")
    return (
        "insufficient_comparability",
        "not_established",
        "Missing " + ", ".join(missing) + "; superiority cannot be inferred.",
        security_effect,
        operational_tradeoff,
    )


def comparison_rows(review_dir: pathlib.Path) -> list[dict[str, object]]:
    """Create one transparent security comparison row per DOI-valid study."""
    scopes = shortlist_scope(review_dir)
    rows: list[dict[str, object]] = []
    for source in read_csv(review_dir / "extraction" / "extraction-table.csv"):
        doi = clean_doi(source.get("assigned_doi") or source.get("doi"))
        if not doi:
            continue
        readiness, dominance, reason, security_effect, operational_tradeoff = comparison_readiness(source)
        threat_text = " ".join(
            clean(source.get(field))
            for field in ("threat_model", "attack_type", "key_findings", "title_original")
        )
        control_text = " ".join(
            clean(source.get(field))
            for field in (
                "security_harness_name",
                "control_architecture",
                "enforcement_point",
                "models_or_systems_studied",
            )
        )
        row: dict[str, object] = {
            "doi": doi,
            "title": clean(source.get("title_original") or source.get("title_en") or source.get("title_es")),
            "scope": scopes.get(doi, "included_context"),
            "work_type": clean(source.get("work_type")),
            "study_design": clean(source.get("design_detail") or source.get("empirical_type")),
            "security_harness_name": clean(source.get("security_harness_name")),
            "control_family": classify(control_text, CONTROL_RULES, "other_or_unspecified"),
            "control_architecture": clean(source.get("control_architecture")),
            "enforcement_point": clean(source.get("enforcement_point")),
            "threat_family": classify(threat_text, THREAT_RULES, "other_or_unspecified"),
            "threat_model": clean(source.get("threat_model")),
            "attack_type": clean(source.get("attack_type")),
            "attacker_adaptivity": clean(source.get("attacker_adaptivity")),
            "evaluation_setting": clean(source.get("evaluation_setting")),
            "baselines_or_comparators": clean(source.get("baselines_or_comparators")),
            "security_metrics": clean(source.get("security_metrics")),
            "attack_success_rate": clean(source.get("attack_success_rate")),
            "false_positive_rate": clean(source.get("false_positive_rate")),
            "utility_impact": clean(source.get("utility_impact")),
            "latency_overhead": clean(source.get("latency_overhead")),
            "cost_overhead": clean(source.get("cost_overhead")),
            "robustness_evidence": clean(source.get("robustness_evidence")),
            "failure_modes": clean(source.get("failure_modes")),
            "code_or_artifact_availability": clean(source.get("code_or_artifact_availability")),
            "security_conclusion": clean(source.get("security_conclusion")),
            "evidence_snippet": clean(source.get("evidence_snippet")),
            "evidence_location": clean(source.get("evidence_location")),
            "security_effect_evidence": security_effect,
            "operational_tradeoff_evidence": operational_tradeoff,
            "comparison_readiness": readiness,
            "dominance_status": dominance,
            "dominance_reason": reason,
        }
        rows.append(row)
    return sorted(rows, key=lambda row: (str(row["scope"]) != "focal", str(row["doi"])))


def count_reported(rows: list[dict[str, object]], field: str) -> int:
    """Count material field coverage."""
    return sum(1 for row in rows if reported(row.get(field)))


def frontier_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Aggregate evidence coverage without pooling heterogeneous effect sizes."""
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["threat_family"]), str(row["control_family"]))].append(row)
    output: list[dict[str, object]] = []
    for (threat, control), members in groups.items():
        frontier_ready = sum(1 for row in members if row["comparison_readiness"] == "frontier_ready")
        tradeoff_ready = sum(
            1
            for row in members
            if row["comparison_readiness"] in {"frontier_ready", "tradeoff_ready"}
        )
        if "other_or_unspecified" in {threat, control}:
            status = "insufficient_taxonomy"
            interpretation = (
                "The residual family cannot support replication or superiority claims until the threat "
                "and control are classified into a shared operational mechanism."
            )
        elif frontier_ready >= 2:
            status = "replicated_frontier_candidate"
            interpretation = (
                "At least two studies report the dimensions needed to test conditional dominance; "
                "metric and threat equivalence must still be checked source by source."
            )
        elif frontier_ready == 1 or tradeoff_ready >= 2:
            status = "emerging_frontier"
            interpretation = "Trade-off evidence exists, but replication or robustness remains incomplete."
        elif any(row["comparison_readiness"] == "security_effect_ready" for row in members):
            status = "security_effect_only"
            interpretation = "Security efficacy is reported without enough operational trade-off evidence."
        else:
            status = "insufficient_comparability"
            interpretation = "The cluster cannot support a fair superiority claim."
        output.append(
            {
                "threat_family": threat,
                "control_family": control,
                "studies": len(members),
                "dois": "; ".join(sorted(str(row["doi"]) for row in members)),
                "with_explicit_baseline": count_reported(members, "baselines_or_comparators"),
                "with_adaptive_attacker": sum(
                    1 for row in members if adaptive_attacker_reported(row.get("attacker_adaptivity"))
                ),
                "with_security_metric": count_reported(members, "security_metrics"),
                "with_attack_success_rate": sum(
                    1 for row in members if evidence_level(row.get("attack_success_rate")) == "quantified"
                ),
                "with_false_positive_rate": sum(
                    1 for row in members if evidence_level(row.get("false_positive_rate")) == "quantified"
                ),
                "with_utility_impact": sum(
                    1 for row in members if evidence_level(row.get("utility_impact")) == "quantified"
                ),
                "with_latency_or_cost": sum(
                    1
                    for row in members
                    if evidence_level(row.get("latency_overhead")) == "quantified"
                    or evidence_level(row.get("cost_overhead")) == "quantified"
                ),
                "with_robustness_evidence": count_reported(members, "robustness_evidence"),
                "with_failure_modes": count_reported(members, "failure_modes"),
                "with_open_artifact": sum(
                    1 for row in members if open_artifact_reported(row.get("code_or_artifact_availability"))
                ),
                "frontier_status": status,
                "interpretation": interpretation,
            }
        )
    return sorted(output, key=lambda row: (-int(row["studies"]), str(row["threat_family"]), str(row["control_family"])))


def write_summary(
    path: pathlib.Path,
    rows: list[dict[str, object]],
    frontier: list[dict[str, object]],
) -> None:
    """Write the reader-facing interpretation of the comparison boundary."""
    statuses: dict[str, int] = defaultdict(int)
    for row in rows:
        statuses[str(row["comparison_readiness"])] += 1
    lines = [
        "# Comparación de harnesses de seguridad",
        "",
        "La pregunta útil no es qué harness gana en abstracto, sino qué control domina bajo una amenaza, "
        "un atacante, un baseline y un presupuesto operacional comparables. Esta carpeta materializa esa "
        "frontera sin agregar métricas incompatibles.",
        "",
        "## Cobertura de comparación",
        "",
        f"- Estudios DOI-válidos analizados: {len(rows)}",
    ]
    for status, count in sorted(statuses.items()):
        lines.append(f"- {status}: {count}")
    lines.extend(
        [
            "",
            "## Regla de lectura",
            "",
            "Un `conditional_dominance_candidate` no es un ganador automático. Significa que el estudio "
            "reporta amenaza, control, baseline, resultado de seguridad, coste o impacto operativo y "
            "robustez. La equivalencia de métricas y condiciones debe verificarse en el PDF antes de "
            "formular una conclusión comparativa.",
            "",
            "Los valores ausentes no se transforman en cero. Los estudios que solo miden tasa de ataque "
            "pueden informar eficacia defensiva, pero no superioridad global si omiten falsos positivos, "
            "utilidad, latencia, coste o adaptación del atacante.",
            "",
            "## Frontera por familias",
            "",
            "| Amenaza | Control | Estudios | Estado |",
            "|---|---|---:|---|",
        ]
    )
    for row in frontier:
        lines.append(
            f"| {row['threat_family']} | {row['control_family']} | {row['studies']} | {row['frontier_status']} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(review_dir: pathlib.Path) -> dict[str, object]:
    """Build security-harness artifacts when the review uses that profile."""
    if not review_is_security_focused(review_dir):
        return {
            "schema_version": "hermes.security-harness-analysis/v1",
            "generated_at": now_iso(),
            "enabled": False,
            "artifacts": [],
        }
    rows = comparison_rows(review_dir)
    frontier = frontier_rows(rows)
    output_dir = review_dir / "analysis" / "security"
    write_csv(output_dir / "security-harness-comparison.csv", COMPARISON_FIELDS, rows)
    write_csv(output_dir / "dominance-frontier.csv", FRONTIER_FIELDS, frontier)
    write_summary(output_dir / "README.md", rows, frontier)
    readiness_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        readiness_counts[str(row["comparison_readiness"])] += 1
    result = {
        "schema_version": "hermes.security-harness-analysis/v1",
        "generated_at": now_iso(),
        "enabled": True,
        "scientific_boundary": (
            "No universal winner is inferred. Conditional dominance requires comparable threat, baseline, "
            "security outcome, operational trade-off, and robustness evidence."
        ),
        "studies": len(rows),
        "frontier_clusters": len(frontier),
        "readiness_counts": dict(sorted(readiness_counts.items())),
        "artifacts": [
            "analysis/security/security-harness-comparison.csv",
            "analysis/security/dominance-frontier.csv",
            "analysis/security/README.md",
        ],
    }
    write_json_atomic(output_dir / "security-harness-summary.json", result)
    result["artifacts"].append("analysis/security/security-harness-summary.json")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    if not review_dir.is_dir():
        raise SystemExit(f"Review directory not found: {review_dir}")
    print(json.dumps(build(review_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
