"""Orchestrate the auditable network-analysis artifact set."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
from collections import Counter
from typing import Any

import networkx as nx

from .enrich import enrich_author_profiles, enrich_openalex
from .graph_builder import EVIDENCE_FIELDS, STAGE_ORDER, build_graphs, graph_rows, resolved_authors, resolved_keywords
from .io import group_by_stage, load_review_records, normalize_label, write_csv, write_json
from .metrics import DEFAULT_RESOLUTIONS, DEFAULT_SEEDS, analyze_graphs
from .render import build_atlas_payload, write_atlas, write_static_svgs

ANALYSIS_VERSION = "1.0.0"
NODE_FIELDS = [
    "node_id",
    "node_type",
    "label",
    "doi",
    "year",
    "openalex_id",
    "orcid",
    "institutions",
    "stages",
    "metadata_source",
    "resolution_confidence",
    "openalex_works_count",
    "openalex_cited_by_count",
    "layers",
]
EDGE_FIELDS = ["source", "target", "layer", "weight", "directed", "stage", "evidence_count"]
CENTRALITY_FIELDS = [
    "layer",
    "node_id",
    "node_type",
    "label",
    "degree_centrality",
    "weighted_degree",
    "betweenness",
    "harmonic",
    "pagerank",
    "eigenvector",
    "k_core",
    "clustering",
    "participation",
    "community_id",
    "claim_status",
]
COMMUNITY_FIELDS = [
    "layer",
    "community_id",
    "size",
    "top_nodes",
    "modularity",
    "stability",
    "claim_status",
]
DRIFT_FIELDS = [
    "entity_id",
    "entity_type",
    "label",
    *[f"{stage}_count" for stage in STAGE_ORDER],
    "included_retention",
    "focal_retention",
    "resolution_confidence",
]
AUTHOR_FIELDS = [
    "author_id",
    "author",
    "resolution_confidence",
    "corpus_studies",
    "included_studies",
    "focal_studies",
    "openalex_works_count",
    "openalex_cited_by_count",
    "note",
]
PROVENANCE_FIELDS = ["source", "path", "records", "status"]
STUDY_FIELDS = ["doi", "title", "year", "source", "work_type", "stages"]


def _generated_at() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch.isdigit():
        return dt.datetime.fromtimestamp(int(epoch), tz=dt.timezone.utc).isoformat()
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _review_title(review_dir: pathlib.Path) -> str:
    title_path = review_dir / "paper" / "sections" / "01-title-abstract-keywords.md"
    if title_path.exists():
        excluded = {
            "título, resumen y palabras clave",
            "titulo, resumen y palabras clave",
            "título",
            "titulo",
            "title",
        }
        for line in title_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title and title.casefold() not in excluded:
                    return title

    intake_path = review_dir / "protocol" / "intake.md"
    if intake_path.exists():
        match = re.search(
            r"^-\s*Tema:\s*(?P<title>.+?)\s*$",
            intake_path.read_text(encoding="utf-8", errors="replace"),
            flags=re.MULTILINE | re.IGNORECASE,
        )
        if match:
            return match.group("title").strip()

    research_question_path = review_dir / "protocol" / "research-question.md"
    if research_question_path.exists():
        excluded = {
            "pregunta de investigación",
            "pregunta de investigacion",
            "principal",
            "secundarias",
        }
        path = research_question_path
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title and title.casefold() not in excluded:
                    return title
    return review_dir.name.replace("-", " ").strip().title()


def _coverage(
    records: list[dict[str, Any]],
    openalex: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, float]]:
    stage_sets = group_by_stage(records)
    included = [record for record in records if "included" in record["stages"]]
    denominator = len(included)

    def ratio(count: int) -> float:
        return count / denominator if denominator else 0.0

    authors = sum(1 for record in included if resolved_authors(record, openalex.get(record["doi"])))
    references = sum(
        1
        for record in included
        if (openalex.get(record["doi"]) or {}).get("referenced_works")
    )
    keywords = sum(
        1
        for record in included
        if resolved_keywords(record, openalex.get(record["doi"]))
    )
    evidence = sum(1 for record in included if _has_structured_evidence(record))
    openalex_works = sum(1 for record in included if record["doi"] in openalex)
    coverage = {
        "denominator": denominator,
        "stage_counts": {stage: len(stage_sets.get(stage, set())) for stage in STAGE_ORDER},
        "authors": {"count": authors, "coverage": ratio(authors), "threshold": 0.85},
        "references": {"count": references, "coverage": ratio(references), "threshold": 0.70},
        "keywords": {"count": keywords, "coverage": ratio(keywords), "threshold": 0.70},
        "structured_evidence": {"count": evidence, "coverage": ratio(evidence), "threshold": 0.70},
        "openalex_works": {"count": openalex_works, "coverage": ratio(openalex_works)},
    }
    layer_coverage = {
        "authorship": ratio(authors),
        "coauthorship": ratio(authors),
        "citation": ratio(references),
        "bibliographic_coupling": ratio(references),
        "cocitation": ratio(references),
        "keyword_cooccurrence": ratio(keywords),
        "evidence": ratio(evidence),
    }
    return coverage, layer_coverage


def _has_structured_evidence(record: dict[str, Any]) -> bool:
    fields = record["fields"]
    return any(normalize_label(fields.get(field, "")) for candidates in EVIDENCE_FIELDS.values() for field in candidates)


def _author_production(
    graphs: dict[str, nx.Graph],
    selection_drift: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    drift = {row["entity_id"]: row for row in selection_drift if row["entity_type"] == "author"}
    rows = []
    for author_id, attrs in graphs["coauthorship"].nodes(data=True):
        author_drift = drift.get(author_id, {})
        rows.append(
            {
                "author_id": author_id,
                "author": attrs.get("label", author_id),
                "resolution_confidence": attrs.get("resolution_confidence", ""),
                "corpus_studies": author_drift.get("master_count", 0),
                "included_studies": author_drift.get("included_count", 0),
                "focal_studies": author_drift.get("focal_count", 0),
                "openalex_works_count": attrs.get("openalex_works_count", ""),
                "openalex_cited_by_count": attrs.get("openalex_cited_by_count", ""),
                "note": "Context only; not used for eligibility, appraisal, or focal selection.",
            }
        )
    return sorted(rows, key=lambda row: (-int(row["included_studies"]), row["author"].casefold()))


def _write_graphml(path: pathlib.Path, node_rows: list[dict[str, Any]], edge_rows: list[dict[str, Any]]) -> None:
    graph = nx.MultiDiGraph()
    for row in node_rows:
        graph.add_node(row["node_id"], **{key: str(value) for key, value in row.items() if key != "node_id"})
    for row in edge_rows:
        graph.add_edge(
            row["source"],
            row["target"],
            **{key: str(value) for key, value in row.items() if key not in {"source", "target"}},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(graph, path, infer_numeric_types=True)


def _write_methodology(
    path: pathlib.Path,
    title: str,
    coverage: dict[str, Any],
    layer_summaries: dict[str, Any],
    generated_at: str,
) -> None:
    statuses = Counter(summary["claim_status"] for summary in layer_summaries.values())
    status_text = ", ".join(
        (
            f"{statuses.get('interpretable', 0)} "
            f"{'capa interpretable' if statuses.get('interpretable', 0) == 1 else 'capas interpretables'}",
            f"{statuses.get('exploratory', 0)} "
            f"{'capa exploratoria' if statuses.get('exploratory', 0) == 1 else 'capas exploratorias'}",
            f"{statuses.get('entities_only', 0)} "
            f"{'capa limitada a entidades' if statuses.get('entities_only', 0) == 1 else 'capas limitadas a entidades'}",
        )
    )
    focal_mismatch = int(coverage.get("focal_outside_included_count") or 0)
    focal_note = ""
    if focal_mismatch:
        focal_note = (
            "\n\nEl fichero de preselección declaraba "
            f"{coverage.get('raw_focal_shortlist_count', 0)} registros focales, pero "
            f"{focal_mismatch} no pertenecían al corpus incluido. El análisis restringió "
            "automáticamente el subconjunto focal a estudios incluidos y conserva los DOI "
            "discordantes en `audit/coverage.json`."
        )
    path.write_text(
        f"""# Metodología del atlas estructural

## Alcance

Este análisis describe las relaciones bibliométricas y analíticas del corpus de
**{title}**. La unidad de estudio es el DOI normalizado. La topología no sustituye
la evaluación crítica y no interviene en inclusión, exclusión ni selección focal.

## Cobertura

El denominador es de {coverage["denominator"]} estudios incluidos. La autoría se
recuperó para {coverage["authors"]["count"]} ({coverage["authors"]["coverage"]:.1%}),
las referencias para {coverage["references"]["count"]}
({coverage["references"]["coverage"]:.1%}), las palabras clave para
{coverage["keywords"]["count"]} ({coverage["keywords"]["coverage"]:.1%}) y la
evidencia estructurada para {coverage["structured_evidence"]["count"]}
({coverage["structured_evidence"]["coverage"]:.1%}).{focal_note}

## Cálculo

Las redes se construyeron por separado para coautoría, citación, acoplamiento
bibliográfico, cocitación, coocurrencia temática y relaciones de evidencia. La
intermediación ponderada usa `distancia = 1 / peso`. Las comunidades se estimaron
con Louvain para semillas {", ".join(map(str, DEFAULT_SEEDS))} y resoluciones
{", ".join(map(str, DEFAULT_RESOLUTIONS))}; se eligió la partición de mayor
modularidad y se calculó estabilidad mediante información mutua normalizada.

## Regla interpretativa

Hay {status_text}. Las comunidades solo se
interpretan cuando el tamaño del corpus, la cobertura de metadatos y la
estabilidad superan los umbrales declarados. Los parámetros completos están en
`audit/parameters.json`.

La cobertura de palabras clave informa disponibilidad, no validez semántica.
Descriptores indexados o derivados de taxonomías externas pueden ser más amplios
que el objeto concreto de la revisión; por eso una capa temática inestable se
mantiene exploratoria y requiere auditoría sustantiva antes de entrar en el
manuscrito.

## Procedencia y fecha

Los estados de selección proceden de los CSV de la revisión. OpenAlex aporta
resolución de autores y referencias cuando está disponible; sus respuestas se
conservan en caché. Artefacto generado el {generated_at}.
""",
        encoding="utf-8",
    )


def _write_summary(
    path: pathlib.Path,
    coverage: dict[str, Any],
    layer_summaries: dict[str, Any],
    centrality_rows: list[dict[str, Any]],
) -> None:
    included = coverage["stage_counts"]["included"]
    focal = coverage["stage_counts"]["focal"]
    author_top = _top_labels(centrality_rows, "coauthorship")
    topic_top = _top_labels(centrality_rows, "keyword_cooccurrence")
    author_status = _claim_status_es(layer_summaries["coauthorship"]["claim_status"])
    topic_status = _claim_status_es(layer_summaries["keyword_cooccurrence"]["claim_status"])
    citation_status = _claim_status_es(layer_summaries["bibliographic_coupling"]["claim_status"])
    topic_interpretation = (
        f"concentra su conectividad en {_join_labels(topic_top)}"
        if layer_summaries["keyword_cooccurrence"]["claim_status"] == "interpretable"
        else "no alcanza estabilidad suficiente para sostener un núcleo temático consolidado"
    )
    path.write_text(
        f"""# Estructura relacional del corpus

El análisis estructural parte de {included} estudios incluidos, de los que
{focal} forman el subconjunto focal. Su función no es reemplazar la síntesis
sustantiva, sino comprobar si autores, temas, referencias y dimensiones
analíticas forman concentraciones, puentes o vacíos que una tabla plana no
permite observar.

La red de coautoría tiene estado **{author_status}**. Los nodos con mayor
conectividad directa son {_join_labels(author_top)}. Esta posición describe
colaboración dentro del corpus, no calidad ni autoridad. La red de descriptores
tiene estado **{topic_status}** y {topic_interpretation}; su interpretación debe mantenerse dentro de la
cobertura de palabras clave reportada ({coverage["keywords"]["coverage"]:.1%}).

El acoplamiento bibliográfico tiene estado **{citation_status}** y cobertura de
referencias del {coverage["references"]["coverage"]:.1%}. Cuando esa cobertura o
la estabilidad de comunidades no alcanza el umbral, el patrón se conserva como
señal exploratoria y no como prueba de escuelas consolidadas. El atlas HTML
permite contrastar estas relaciones por fase de selección y consultar las
definiciones de cada indicador.
""",
        encoding="utf-8",
    )


def _top_labels(rows: list[dict[str, Any]], layer: str, limit: int = 5) -> list[str]:
    selected = [row for row in rows if row["layer"] == layer]
    selected.sort(key=lambda row: (-float(row["weighted_degree"]), row["label"].casefold()))
    return [row["label"] for row in selected[:limit]]


def _claim_status_es(value: str) -> str:
    return {
        "interpretable": "interpretable",
        "exploratory": "exploratorio",
        "entities_only": "limitado a entidades",
        "descriptive": "descriptivo",
    }.get(value, value)


def _join_labels(labels: list[str]) -> str:
    if not labels:
        return "ningún nodo recuperable"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" y {labels[-1]}"


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_pngs(svg_paths: list[pathlib.Path]) -> list[pathlib.Path]:
    converter = shutil.which("rsvg-convert")
    if not converter:
        return []
    output = []
    for svg_path in svg_paths:
        png_path = svg_path.parents[1] / "png" / f"{svg_path.stem}.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [converter, "-w", "2400", "-o", str(png_path), str(svg_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and png_path.exists():
            output.append(png_path)
    return output


def build_analysis(
    review_dir: pathlib.Path,
    *,
    offline: bool = False,
    max_openalex_requests: int = 100,
    max_author_requests: int = 80,
) -> dict[str, Any]:
    review_dir = review_dir.expanduser().resolve()
    if not review_dir.exists():
        raise FileNotFoundError(f"Review directory does not exist: {review_dir}")
    analysis_dir = review_dir / "analysis"
    for relative in (
        "atlas",
        "data",
        "metrics",
        "audit",
        "cache/openalex",
        "figures/svg",
        "figures/png",
    ):
        (analysis_dir / relative).mkdir(parents=True, exist_ok=True)

    generated_at = _generated_at()
    title = _review_title(review_dir)
    records, source_audit = load_review_records(review_dir)
    if not records:
        raise RuntimeError("No DOI-resolved records were found in the review workspace.")

    openalex, provenance = enrich_openalex(
        review_dir,
        records,
        offline=offline,
        max_requests=max_openalex_requests,
    )
    included_dois = {record["doi"] for record in records if "included" in record["stages"]}
    author_profiles, author_provenance = enrich_author_profiles(
        review_dir,
        openalex,
        included_dois,
        offline=offline,
        max_requests=max_author_requests,
    )
    provenance.extend(author_provenance)
    graphs, graph_audit = build_graphs(records, openalex, author_profiles)
    coverage, layer_coverage = _coverage(records, openalex)
    centrality_rows, community_rows, layer_summaries = analyze_graphs(
        graphs,
        included_studies=coverage["stage_counts"]["included"],
        coverage_by_layer=layer_coverage,
    )
    node_rows, edge_rows = graph_rows(graphs)
    selection_drift = graph_audit["selection_drift"]
    author_production = _author_production(graphs, selection_drift)

    write_csv(analysis_dir / "data" / "nodes.csv", NODE_FIELDS, node_rows)
    write_csv(analysis_dir / "data" / "edges.csv", EDGE_FIELDS, edge_rows)
    write_csv(
        analysis_dir / "data" / "studies.csv",
        STUDY_FIELDS,
        (
            {
                "doi": record["doi"],
                "title": record["title"],
                "year": record["year"],
                "source": record["source"],
                "work_type": record["work_type"],
                "stages": record["stages"],
            }
            for record in records
        ),
    )
    _write_graphml(analysis_dir / "data" / "graph.graphml", node_rows, edge_rows)
    write_csv(analysis_dir / "metrics" / "centrality.csv", CENTRALITY_FIELDS, centrality_rows)
    write_csv(analysis_dir / "metrics" / "communities.csv", COMMUNITY_FIELDS, community_rows)
    write_csv(analysis_dir / "metrics" / "selection-drift.csv", DRIFT_FIELDS, selection_drift)
    write_csv(analysis_dir / "metrics" / "author-production.csv", AUTHOR_FIELDS, author_production)

    summary_payload = {
        "analysis_version": ANALYSIS_VERSION,
        "generated_at": generated_at,
        "title": title,
        "coverage": coverage,
        "layers": layer_summaries,
    }
    write_json(analysis_dir / "metrics" / "network-summary.json", summary_payload)
    coverage_payload = {
        **source_audit,
        **coverage,
        "interpretation": {
            "author_threshold": 0.85,
            "reference_threshold": 0.70,
            "keyword_threshold": 0.70,
            "community_stability_threshold": 0.80,
        },
    }
    write_json(analysis_dir / "audit" / "coverage.json", coverage_payload)
    write_json(
        analysis_dir / "audit" / "parameters.json",
        {
            "analysis_version": ANALYSIS_VERSION,
            "generated_at": generated_at,
            "study_identity": "normalized_doi",
            "metric_graph_stage": "included",
            "community_algorithm": "networkx_louvain",
            "community_seeds": DEFAULT_SEEDS,
            "community_resolutions": DEFAULT_RESOLUTIONS,
            "community_stability_metric": "normalized_mutual_information",
            "community_stability_threshold": 0.80,
            "weighted_shortest_path_distance": "1 / edge_weight",
            "max_references_per_study": 80,
            "max_evidence_values_per_field": 12,
            "minimum_cocitation_weight": 2,
            "selection_influence": "none",
        },
    )
    write_csv(analysis_dir / "audit" / "provenance.csv", PROVENANCE_FIELDS, provenance)
    _write_methodology(
        analysis_dir / "methodology.md",
        title,
        coverage_payload,
        layer_summaries,
        generated_at,
    )
    _write_summary(
        analysis_dir / "summary.md",
        coverage,
        layer_summaries,
        centrality_rows,
    )

    atlas_payload = build_atlas_payload(
        title,
        graphs,
        centrality_rows,
        layer_summaries,
        selection_drift,
        coverage,
        author_production,
    )
    atlas_payload["generatedAt"] = generated_at
    write_atlas(analysis_dir / "atlas" / "network-atlas.html", atlas_payload)
    svg_paths = write_static_svgs(analysis_dir / "figures" / "svg", atlas_payload)
    png_paths = _render_pngs(svg_paths)

    artifact_paths = sorted(
        path
        for path in analysis_dir.rglob("*")
        if path.is_file() and "cache" not in path.relative_to(analysis_dir).parts and path.name != "manifest.json"
    )
    manifest = {
        "analysis_version": ANALYSIS_VERSION,
        "generated_at": generated_at,
        "title": title,
        "study_count": len(records),
        "included_study_count": coverage["stage_counts"]["included"],
        "focal_study_count": coverage["stage_counts"]["focal"],
        "atlas": "atlas/network-atlas.html",
        "static_figures": [str(path.relative_to(analysis_dir)) for path in [*svg_paths, *png_paths]],
        "artifacts": [
            {
                "path": str(path.relative_to(analysis_dir)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in artifact_paths
        ],
    }
    write_json(analysis_dir / "manifest.json", manifest)
    return manifest
