"""Compute transparent network metrics and community robustness."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import fmean
from typing import Any, Iterable

import networkx as nx

DEFAULT_SEEDS = (11, 29, 47, 71, 101)
DEFAULT_RESOLUTIONS = (0.8, 1.0, 1.2)


def _stable_float(value: float) -> float:
    """Normalize platform-level float noise while retaining 12 significant digits."""
    return float(format(float(value), ".12g"))


def _safe_mean(values: Iterable[float]) -> float:
    items = list(values)
    return fmean(items) if items else 0.0


def _distance_graph(graph: nx.Graph) -> nx.Graph:
    output = graph.copy()
    for source, target, attrs in output.edges(data=True):
        weight = max(float(attrs.get("weight", 1.0)), 1e-12)
        output[source][target]["distance"] = 1.0 / weight
    return output


def normalized_mutual_information(
    partition_a: list[set[str]],
    partition_b: list[set[str]],
) -> float:
    """Compute arithmetic-mean NMI without an additional dependency."""
    labels_a = {node: index for index, community in enumerate(partition_a) for node in community}
    labels_b = {node: index for index, community in enumerate(partition_b) for node in community}
    nodes = sorted(set(labels_a) & set(labels_b))
    if not nodes:
        return 0.0
    counts_a = Counter(labels_a[node] for node in nodes)
    counts_b = Counter(labels_b[node] for node in nodes)
    joint = Counter((labels_a[node], labels_b[node]) for node in nodes)
    size = len(nodes)
    mutual_information = 0.0
    for (label_a, label_b), count in joint.items():
        probability = count / size
        mutual_information += probability * math.log(
            (count * size) / (counts_a[label_a] * counts_b[label_b])
        )
    entropy_a = -sum((count / size) * math.log(count / size) for count in counts_a.values())
    entropy_b = -sum((count / size) * math.log(count / size) for count in counts_b.values())
    denominator = (entropy_a + entropy_b) / 2.0
    if denominator == 0:
        return 1.0
    return max(0.0, min(1.0, mutual_information / denominator))


def community_runs(
    graph: nx.Graph,
    *,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    resolutions: tuple[float, ...] = DEFAULT_RESOLUTIONS,
) -> tuple[list[set[str]], dict[str, Any]]:
    if graph.number_of_nodes() == 0:
        return [], {
            "modularity": 0.0,
            "stability": 0.0,
            "seed": None,
            "resolution": None,
            "runs": [],
        }
    if graph.number_of_edges() == 0:
        singleton = [{node} for node in sorted(graph)]
        return singleton, {
            "modularity": 0.0,
            "stability": 1.0,
            "seed": None,
            "resolution": None,
            "runs": [],
        }
    runs: list[dict[str, Any]] = []
    for resolution in resolutions:
        for seed in seeds:
            partition = nx.community.louvain_communities(
                graph,
                weight="weight",
                resolution=resolution,
                seed=seed,
            )
            modularity = nx.community.modularity(
                graph,
                partition,
                weight="weight",
                resolution=resolution,
            )
            runs.append(
                {
                    "seed": seed,
                    "resolution": resolution,
                    "partition": partition,
                    "modularity": _stable_float(modularity),
                }
            )
    selected = max(runs, key=lambda item: (item["modularity"], -item["resolution"], -item["seed"]))
    stability = _safe_mean(
        normalized_mutual_information(selected["partition"], run["partition"])
        for run in runs
        if run is not selected
    )
    return selected["partition"], {
        "modularity": selected["modularity"],
        "stability": stability,
        "seed": selected["seed"],
        "resolution": selected["resolution"],
        "runs": [
            {
                "seed": run["seed"],
                "resolution": run["resolution"],
                "modularity": run["modularity"],
                "community_count": len(run["partition"]),
            }
            for run in runs
        ],
    }


def _eigenvector(graph: nx.Graph) -> dict[str, float]:
    if graph.number_of_nodes() < 2 or graph.number_of_edges() == 0:
        return {node: 0.0 for node in graph}
    try:
        return nx.eigenvector_centrality(graph, max_iter=2000, weight="weight")
    except (nx.PowerIterationFailedConvergence, nx.NetworkXException):
        return {node: 0.0 for node in graph}


def _pagerank(
    graph: nx.Graph,
    *,
    alpha: float = 0.85,
    max_iter: int = 200,
    tolerance: float = 1e-10,
) -> dict[str, float]:
    """Compute weighted PageRank in pure Python to keep dependencies minimal."""
    nodes = sorted(graph)
    size = len(nodes)
    if not size:
        return {}
    rank = {node: 1.0 / size for node in nodes}
    outgoing = {
        node: sum(float(attrs.get("weight", 1.0)) for _, _, attrs in graph.edges(node, data=True))
        for node in nodes
    }
    for _ in range(max_iter):
        dangling = alpha * sum(rank[node] for node in nodes if outgoing[node] == 0.0) / size
        updated = {node: (1.0 - alpha) / size + dangling for node in nodes}
        for source in nodes:
            if outgoing[source] == 0.0:
                continue
            for target, attrs in graph[source].items():
                weight = float(attrs.get("weight", 1.0))
                updated[target] += alpha * rank[source] * weight / outgoing[source]
        delta = sum(abs(updated[node] - rank[node]) for node in nodes)
        rank = updated
        if delta < tolerance:
            break
    return rank


def _weighted_clustering(graph: nx.Graph) -> dict[str, float]:
    """Compute Onnela weighted clustering without NumPy."""
    maximum_weight = max(
        (float(attrs.get("weight", 1.0)) for _, _, attrs in graph.edges(data=True)),
        default=1.0,
    )
    maximum_weight = max(maximum_weight, 1e-12)
    values: dict[str, float] = {}
    for node in graph:
        neighbors = sorted(graph.neighbors(node))
        degree = len(neighbors)
        if degree < 2:
            values[node] = 0.0
            continue
        triangle_strength = 0.0
        for left_index, left in enumerate(neighbors):
            left_weight = float(graph[node][left].get("weight", 1.0)) / maximum_weight
            for right in neighbors[left_index + 1 :]:
                if not graph.has_edge(left, right):
                    continue
                right_weight = float(graph[node][right].get("weight", 1.0)) / maximum_weight
                closing_weight = float(graph[left][right].get("weight", 1.0)) / maximum_weight
                triangle_strength += (left_weight * right_weight * closing_weight) ** (1.0 / 3.0)
        values[node] = 2.0 * triangle_strength / (degree * (degree - 1))
    return values


def _participation(
    graph: nx.Graph,
    community_by_node: dict[str, int],
) -> dict[str, float]:
    values: dict[str, float] = {}
    for node in graph:
        total_weight = sum(float(attrs.get("weight", 1.0)) for _, _, attrs in graph.edges(node, data=True))
        if total_weight == 0:
            values[node] = 0.0
            continue
        by_community: dict[int, float] = defaultdict(float)
        for neighbor, attrs in graph[node].items():
            by_community[community_by_node.get(neighbor, -1)] += float(attrs.get("weight", 1.0))
        values[node] = 1.0 - sum((weight / total_weight) ** 2 for weight in by_community.values())
    return values


def _degree_centralization(degrees: dict[str, float]) -> float:
    size = len(degrees)
    if size <= 2:
        return 0.0
    maximum = max(degrees.values(), default=0.0)
    denominator = (size - 1) * (size - 2)
    return sum(maximum - value for value in degrees.values()) / denominator if denominator else 0.0


def _hhi(values: Iterable[float]) -> float:
    numbers = [max(0.0, float(value)) for value in values]
    total = sum(numbers)
    if total == 0:
        return 0.0
    return sum((value / total) ** 2 for value in numbers)


def analyze_layer(
    layer: str,
    graph: nx.Graph,
    *,
    included_studies: int,
    coverage: float,
    coverage_threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    undirected = graph.to_undirected()
    partition, community_audit = community_runs(undirected)
    community_by_node = {
        node: community_id
        for community_id, community in enumerate(
            sorted(partition, key=lambda item: (-len(item), sorted(item)[0] if item else ""))
        )
        for node in community
    }
    distance_graph = _distance_graph(undirected)
    degree = nx.degree_centrality(undirected)
    weighted_degree = dict(undirected.degree(weight="weight"))
    betweenness = nx.betweenness_centrality(distance_graph, weight="distance", normalized=True)
    harmonic = nx.harmonic_centrality(distance_graph, distance="distance")
    pagerank = _pagerank(graph)
    eigenvector = _eigenvector(undirected)
    clustering = _weighted_clustering(undirected)
    core = (
        nx.core_number(nx.Graph(undirected))
        if undirected.number_of_nodes() and undirected.number_of_edges()
        else {node: 0 for node in undirected}
    )
    participation = _participation(undirected, community_by_node)

    claim_status = "descriptive"
    reasons: list[str] = []
    if included_studies < 10:
        claim_status = "entities_only"
        reasons.append("fewer_than_10_included_studies")
    elif included_studies < 20:
        claim_status = "exploratory"
        reasons.append("fewer_than_20_included_studies")
    if coverage < coverage_threshold:
        claim_status = "exploratory" if claim_status != "entities_only" else claim_status
        reasons.append("coverage_below_threshold")
    if community_audit["stability"] < 0.80:
        claim_status = "exploratory" if claim_status != "entities_only" else claim_status
        reasons.append("community_stability_below_threshold")
    if not reasons:
        claim_status = "interpretable"

    node_rows = []
    for node in sorted(graph):
        attrs = graph.nodes[node]
        node_rows.append(
            {
                "layer": layer,
                "node_id": node,
                "node_type": attrs.get("node_type", ""),
                "label": attrs.get("label", node),
                "degree_centrality": degree.get(node, 0.0),
                "weighted_degree": weighted_degree.get(node, 0.0),
                "betweenness": _stable_float(betweenness.get(node, 0.0)),
                "harmonic": _stable_float(harmonic.get(node, 0.0)),
                "pagerank": _stable_float(pagerank.get(node, 0.0)),
                "eigenvector": _stable_float(eigenvector.get(node, 0.0)),
                "k_core": core.get(node, 0),
                "clustering": _stable_float(clustering.get(node, 0.0)),
                "participation": _stable_float(participation.get(node, 0.0)),
                "community_id": community_by_node.get(node, ""),
                "claim_status": claim_status,
            }
        )

    community_rows = []
    for community_id, community in enumerate(
        sorted(partition, key=lambda item: (-len(item), sorted(item)[0] if item else ""))
    ):
        ranked = sorted(
            community,
            key=lambda node: (-weighted_degree.get(node, 0.0), graph.nodes[node].get("label", node)),
        )
        community_rows.append(
            {
                "layer": layer,
                "community_id": community_id,
                "size": len(community),
                "top_nodes": "; ".join(graph.nodes[node].get("label", node) for node in ranked[:8]),
                "modularity": _stable_float(community_audit["modularity"]),
                "stability": _stable_float(community_audit["stability"]),
                "claim_status": claim_status,
            }
        )

    components = list(nx.connected_components(undirected)) if undirected.number_of_nodes() else []
    giant_share = max((len(component) for component in components), default=0) / max(
        undirected.number_of_nodes(), 1
    )
    summary = {
        "layer": layer,
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "density": _stable_float(nx.density(graph) if graph.number_of_nodes() > 1 else 0.0),
        "components": len(components),
        "giant_component_share": _stable_float(giant_share),
        "transitivity": _stable_float(
            nx.transitivity(undirected) if undirected.number_of_nodes() > 2 else 0.0
        ),
        "average_clustering": _stable_float(_safe_mean(clustering.values())),
        "degree_centralization": _stable_float(_degree_centralization(degree)),
        "weighted_degree_hhi": _stable_float(_hhi(weighted_degree.values())),
        "community_count": len(partition),
        "modularity": _stable_float(community_audit["modularity"]),
        "community_stability": _stable_float(community_audit["stability"]),
        "community_seed": community_audit["seed"],
        "community_resolution": community_audit["resolution"],
        "coverage": coverage,
        "coverage_threshold": coverage_threshold,
        "claim_status": claim_status,
        "claim_reasons": reasons,
        "community_runs": community_audit["runs"],
    }
    for run in summary["community_runs"]:
        run["modularity"] = _stable_float(run["modularity"])
    return node_rows, community_rows, summary


def analyze_graphs(
    graphs: dict[str, nx.Graph],
    *,
    included_studies: int,
    coverage_by_layer: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    centrality_rows: list[dict[str, Any]] = []
    community_rows: list[dict[str, Any]] = []
    layer_summaries: dict[str, Any] = {}
    thresholds = {
        "authorship": 0.85,
        "coauthorship": 0.85,
        "citation": 0.70,
        "bibliographic_coupling": 0.70,
        "cocitation": 0.70,
        "keyword_cooccurrence": 0.70,
        "evidence": 0.70,
    }
    for layer, graph in graphs.items():
        nodes, communities, summary = analyze_layer(
            layer,
            graph,
            included_studies=included_studies,
            coverage=coverage_by_layer.get(layer, 0.0),
            coverage_threshold=thresholds[layer],
        )
        centrality_rows.extend(nodes)
        community_rows.extend(communities)
        layer_summaries[layer] = summary
    return centrality_rows, community_rows, layer_summaries
