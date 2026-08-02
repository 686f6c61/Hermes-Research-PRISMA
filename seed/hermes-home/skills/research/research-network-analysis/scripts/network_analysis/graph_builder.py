"""Build semantically separate graph layers from review records."""

from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict
from typing import Any

import networkx as nx

from .io import normalized_key, split_values, stable_id

STAGE_ORDER = [
    "master",
    "title_abstract_retained",
    "full_text_assessed",
    "included",
    "focal",
]
EVIDENCE_FIELDS = {
    "theory": ("theory_framework", "theoretical_framework", "theory"),
    "method": ("method_used", "design_detail", "empirical_type"),
    "variable": (
        "variables_dependent",
        "variables_independent",
        "variables_moderating",
        "variables_mediating",
        "variables_control",
    ),
    "outcome": ("key_findings", "outcomes", "results"),
    "context": ("countries", "tasks_or_domains", "unit_of_analysis"),
}
GENERIC_OPENALEX_CONCEPTS = {
    "artificial intelligence",
    "biology",
    "business",
    "chemistry",
    "computer science",
    "economics",
    "education",
    "engineering",
    "environmental science",
    "geography",
    "history",
    "law",
    "linguistics",
    "materials science",
    "mathematics",
    "medicine",
    "philosophy",
    "physics",
    "political science",
    "psychology",
    "social science",
    "sociology",
    "code",
    "context",
    "key",
    "set",
    "task",
}


def descriptor_label(value: str) -> str:
    """Remove ontology disambiguators that do not belong in reader-facing topic maps."""
    label = str(value or "").strip()
    return re.sub(r"\s+\([^()]{2,40}\)\s*$", "", label).strip()


def _add_node(graph: nx.Graph, node_id: str, **attrs: Any) -> None:
    if node_id in graph:
        for key, value in attrs.items():
            if key == "stages" and value:
                existing = set(str(graph.nodes[node_id].get(key, "")).split("|"))
                incoming = set(str(value).split("|"))
                graph.nodes[node_id][key] = "|".join(
                    stage for stage in STAGE_ORDER if stage in existing | incoming
                )
                continue
            if value and not graph.nodes[node_id].get(key):
                graph.nodes[node_id][key] = value
        return
    graph.add_node(node_id, **attrs)


def _add_weighted_edge(graph: nx.Graph, source: str, target: str, **attrs: Any) -> None:
    if source == target:
        return
    if graph.has_edge(source, target):
        graph[source][target]["weight"] = int(graph[source][target].get("weight", 1)) + 1
        graph[source][target]["evidence_count"] = int(
            graph[source][target].get("evidence_count", 1)
        ) + 1
        return
    graph.add_edge(source, target, weight=1, evidence_count=1, **attrs)


def _fallback_authors(raw: str) -> list[dict[str, Any]]:
    authors = [
        value.strip()
        for value in re.split(r"\s*(?:;|\||\band\b|\by\b)\s*", raw, flags=re.IGNORECASE)
        if value.strip()
    ][:80]
    return [
        {
            "id": "",
            "display_name": author,
            "orcid": "",
            "institutions": [],
            "resolution_confidence": "name_only",
        }
        for author in authors
    ]


def resolved_authors(record: dict[str, Any], work: dict[str, Any] | None) -> list[dict[str, Any]]:
    if work and work.get("authors"):
        output = []
        for author in work["authors"]:
            if not author.get("display_name"):
                continue
            item = dict(author)
            item["resolution_confidence"] = "openalex_id" if author.get("id") else "name_only"
            output.append(item)
        if output:
            return output
    return _fallback_authors(record.get("authors_raw", ""))


def resolved_keywords(record: dict[str, Any], work: dict[str, Any] | None) -> list[str]:
    labels = [
        descriptor_label(value)
        for value in re.split(r"\s*(?:;|\||,|•|\n)\s*", record.get("keywords_raw", ""))
        if descriptor_label(value) and len(descriptor_label(value)) <= 100
    ][:80]
    if work:
        labels.extend(
            descriptor_label(keyword)
            for keyword in work.get("keywords") or []
            if normalized_key(descriptor_label(keyword)) not in GENERIC_OPENALEX_CONCEPTS
        )
        if not labels:
            labels.extend(
                descriptor_label(concept)
                for concept in work.get("concepts") or []
                if normalized_key(descriptor_label(concept)) not in GENERIC_OPENALEX_CONCEPTS
            )
    output: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = normalized_key(label)
        if not key or key in GENERIC_OPENALEX_CONCEPTS or key in seen:
            continue
        seen.add(key)
        output.append(label)
    return output[:60]


def build_graphs(
    records: list[dict[str, Any]],
    openalex: dict[str, dict[str, Any]],
    author_profiles: dict[str, dict[str, Any]] | None = None,
    *,
    max_references_per_study: int = 80,
    max_evidence_values_per_field: int = 12,
    min_cocitation_weight: int = 2,
    graph_stage: str = "included",
) -> tuple[dict[str, nx.Graph], dict[str, Any]]:
    author_profiles = author_profiles or {}
    graphs: dict[str, nx.Graph] = {
        "authorship": nx.Graph(layer="authorship", directed=False),
        "coauthorship": nx.Graph(layer="coauthorship", directed=False),
        "citation": nx.DiGraph(layer="citation", directed=True),
        "bibliographic_coupling": nx.Graph(layer="bibliographic_coupling", directed=False),
        "cocitation": nx.Graph(layer="cocitation", directed=False),
        "keyword_cooccurrence": nx.Graph(layer="keyword_cooccurrence", directed=False),
        "evidence": nx.Graph(layer="evidence", directed=False),
    }
    record_by_doi = {
        record["doi"]: record
        for record in records
        if graph_stage in record["stages"]
    }
    openalex_id_to_doi = {
        work.get("openalex_id"): doi
        for doi, work in openalex.items()
        if work.get("openalex_id") and doi in record_by_doi
    }
    memberships: dict[str, dict[str, set[str]]] = {
        "author": defaultdict(set),
        "keyword": defaultdict(set),
    }
    labels: dict[str, str] = {}
    author_resolution: dict[str, str] = {}
    study_references: dict[str, set[str]] = {}

    for record in records:
        doi = record["doi"]
        study_id = f"study:{doi}"
        work = openalex.get(doi)
        stages = record["stages"]
        active = graph_stage in stages
        common_study = {
            "node_type": "study",
            "label": record["title"] or doi,
            "doi": doi,
            "year": record["year"],
            "stages": "|".join(stages),
            "source": record["source"] or (work or {}).get("source", ""),
            "metadata_source": "openalex+review" if work else "review",
        }
        if active:
            for layer in ("authorship", "citation", "bibliographic_coupling", "evidence"):
                _add_node(graphs[layer], study_id, **common_study)

        author_ids: list[str] = []
        for author in resolved_authors(record, work):
            identity = author.get("id") or author.get("orcid") or normalized_key(author["display_name"])
            author_id = stable_id("author", identity)
            profile = author_profiles.get(author.get("id", ""), {})
            author_ids.append(author_id)
            labels[author_id] = author["display_name"]
            author_resolution[author_id] = author["resolution_confidence"]
            for stage in stages:
                memberships["author"][author_id].add(f"{stage}:{doi}")
            if active:
                _add_node(
                    graphs["authorship"],
                    author_id,
                    node_type="author",
                    label=author["display_name"],
                    openalex_id=author.get("id", ""),
                    orcid=author.get("orcid", ""),
                    institutions="|".join(author.get("institutions") or []),
                    openalex_works_count=profile.get("works_count", ""),
                    openalex_cited_by_count=profile.get("cited_by_count", ""),
                    resolution_confidence=author["resolution_confidence"],
                    stages="|".join(stages),
                    metadata_source="openalex" if work else "review",
                )
                _add_node(
                    graphs["coauthorship"],
                    author_id,
                    **graphs["authorship"].nodes[author_id],
                )
                graphs["authorship"].add_edge(
                    author_id,
                    study_id,
                    weight=1,
                    evidence_count=1,
                    stage=stages[-1],
                )
        if active:
            for source, target in itertools.combinations(sorted(set(author_ids)), 2):
                _add_weighted_edge(
                    graphs["coauthorship"],
                    source,
                    target,
                    stage=stages[-1],
                )

        keyword_ids: list[str] = []
        for keyword in resolved_keywords(record, work):
            key = normalized_key(keyword)
            keyword_id = stable_id("keyword", key)
            keyword_ids.append(keyword_id)
            labels.setdefault(keyword_id, keyword)
            for stage in stages:
                memberships["keyword"][keyword_id].add(f"{stage}:{doi}")
            if active:
                _add_node(
                    graphs["keyword_cooccurrence"],
                    keyword_id,
                    node_type="keyword",
                    label=labels[keyword_id],
                    stages="|".join(stages),
                    metadata_source="openalex+review" if work else "review",
                )
        if active:
            for source, target in itertools.combinations(sorted(set(keyword_ids)), 2):
                _add_weighted_edge(
                    graphs["keyword_cooccurrence"],
                    source,
                    target,
                    stage=stages[-1],
                )

        if not active:
            continue

        references = set((work or {}).get("referenced_works") or [])
        if len(references) > max_references_per_study:
            references = set(sorted(references)[:max_references_per_study])
        study_references[doi] = references
        for reference_id in references:
            target_doi = openalex_id_to_doi.get(reference_id)
            if not target_doi:
                continue
            target_id = f"study:{target_doi}"
            _add_node(
                graphs["citation"],
                target_id,
                node_type="study",
                label=record_by_doi[target_doi]["title"] or target_doi,
                doi=target_doi,
                year=record_by_doi[target_doi]["year"],
                stages="|".join(record_by_doi[target_doi]["stages"]),
                metadata_source="openalex+review",
            )
            if study_id != target_id:
                graphs["citation"].add_edge(
                    study_id,
                    target_id,
                    weight=1,
                    evidence_count=1,
                    stage=stages[-1],
                )

        _add_evidence_nodes(
            graphs["evidence"],
            study_id,
            record,
            stages,
            max_values=max_evidence_values_per_field,
        )

    _build_reference_similarity(
        graphs,
        study_references,
        record_by_doi,
        min_cocitation_weight=min_cocitation_weight,
    )
    drift = _build_selection_drift(memberships, labels, author_resolution)
    audit = {
        "openalex_work_count": len(openalex),
        "author_memberships": memberships["author"],
        "keyword_memberships": memberships["keyword"],
        "selection_drift": drift,
        "reference_counts": {doi: len(refs) for doi, refs in study_references.items()},
        "author_profiles": author_profiles,
        "graph_stage": graph_stage,
    }
    return graphs, audit


def _add_evidence_nodes(
    graph: nx.Graph,
    study_id: str,
    record: dict[str, Any],
    stages: list[str],
    *,
    max_values: int,
) -> None:
    fields = record["fields"]
    for entity_type, candidates in EVIDENCE_FIELDS.items():
        values: list[str] = []
        for field in candidates:
            values.extend(split_values(fields.get(field, ""), max_items=max_values, max_length=120))
        seen: set[str] = set()
        for value in values:
            key = normalized_key(value)
            if not key or key in seen:
                continue
            seen.add(key)
            node_id = stable_id(entity_type, key)
            _add_node(
                graph,
                node_id,
                node_type=entity_type,
                label=value,
                stages="|".join(stages),
                metadata_source="extraction",
            )
            _add_weighted_edge(graph, study_id, node_id, stage=stages[-1])


def _build_reference_similarity(
    graphs: dict[str, nx.Graph],
    study_references: dict[str, set[str]],
    records: dict[str, dict[str, Any]],
    *,
    min_cocitation_weight: int,
) -> None:
    reference_to_studies: dict[str, set[str]] = defaultdict(set)
    for doi, references in study_references.items():
        study_id = f"study:{doi}"
        _add_node(
            graphs["bibliographic_coupling"],
            study_id,
            node_type="study",
            label=records[doi]["title"] or doi,
            doi=doi,
            year=records[doi]["year"],
            stages="|".join(records[doi]["stages"]),
            metadata_source="review",
        )
        for reference in references:
            reference_to_studies[reference].add(doi)

    for source_doi, target_doi in itertools.combinations(sorted(study_references), 2):
        shared = study_references[source_doi] & study_references[target_doi]
        if shared:
            graphs["bibliographic_coupling"].add_edge(
                f"study:{source_doi}",
                f"study:{target_doi}",
                weight=len(shared),
                evidence_count=len(shared),
                stage="included",
            )

    pair_counts: Counter[tuple[str, str]] = Counter()
    for references in study_references.values():
        for left, right in itertools.combinations(sorted(references), 2):
            pair_counts[(left, right)] += 1
    for (left, right), shared_count in pair_counts.items():
        if shared_count < min_cocitation_weight:
            continue
        left_id = stable_id("reference", left)
        right_id = stable_id("reference", right)
        for node_id, reference in ((left_id, left), (right_id, right)):
            _add_node(
                graphs["cocitation"],
                node_id,
                node_type="reference",
                label=reference.rsplit("/", 1)[-1],
                openalex_id=reference,
                stages="included",
                metadata_source="openalex",
            )
        graphs["cocitation"].add_edge(
            left_id,
            right_id,
            weight=shared_count,
            evidence_count=shared_count,
            stage="included",
        )


def _build_selection_drift(
    memberships: dict[str, dict[str, set[str]]],
    labels: dict[str, str],
    author_resolution: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entity_type, entities in memberships.items():
        for entity_id, memberships_for_entity in entities.items():
            counts = {
                stage: sum(1 for item in memberships_for_entity if item.startswith(f"{stage}:"))
                for stage in STAGE_ORDER
            }
            master_count = counts["master"]
            rows.append(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "label": labels.get(entity_id, entity_id),
                    **{f"{stage}_count": counts[stage] for stage in STAGE_ORDER},
                    "included_retention": counts["included"] / master_count if master_count else 0.0,
                    "focal_retention": counts["focal"] / master_count if master_count else 0.0,
                    "resolution_confidence": author_resolution.get(entity_id, "not_applicable"),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["entity_type"],
            -row["included_count"],
            normalized_key(row["label"]),
        ),
    )


def graph_rows(graphs: dict[str, nx.Graph]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for layer, graph in graphs.items():
        for node_id, attrs in graph.nodes(data=True):
            current = nodes.setdefault(
                node_id,
                {
                    "node_id": node_id,
                    "node_type": attrs.get("node_type", ""),
                    "label": attrs.get("label", node_id),
                    "doi": attrs.get("doi", ""),
                    "year": attrs.get("year", ""),
                    "openalex_id": attrs.get("openalex_id", ""),
                    "orcid": attrs.get("orcid", ""),
                    "institutions": attrs.get("institutions", ""),
                    "stages": attrs.get("stages", ""),
                    "metadata_source": attrs.get("metadata_source", ""),
                    "resolution_confidence": attrs.get("resolution_confidence", ""),
                    "openalex_works_count": attrs.get("openalex_works_count", ""),
                    "openalex_cited_by_count": attrs.get("openalex_cited_by_count", ""),
                    "layers": set(),
                },
            )
            current["layers"].add(layer)
        for source, target, attrs in graph.edges(data=True):
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "layer": layer,
                    "weight": attrs.get("weight", 1),
                    "directed": 1 if graph.is_directed() else 0,
                    "stage": attrs.get("stage", ""),
                    "evidence_count": attrs.get("evidence_count", attrs.get("weight", 1)),
                }
            )
    node_rows = []
    for node in nodes.values():
        node["layers"] = "|".join(sorted(node["layers"]))
        node_rows.append(node)
    return sorted(node_rows, key=lambda row: row["node_id"]), sorted(
        edges,
        key=lambda row: (row["layer"], row["source"], row["target"]),
    )
