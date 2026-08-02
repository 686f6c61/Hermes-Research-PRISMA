"""Render a self-contained analytical atlas and static SVG figures."""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import pathlib
from typing import Any

import networkx as nx

VIEW_LAYERS = {
    "authors": "coauthorship",
    "topics": "keyword_cooccurrence",
    "citations": "bibliographic_coupling",
    "evidence": "evidence",
}
STAGE_LABELS = {
    "master": "Corpus maestro",
    "title_abstract_retained": "Título/resumen",
    "full_text_assessed": "Texto completo",
    "included": "Incluido",
    "focal": "Focal",
}
PALETTE = ["#f3a6a0", "#8db8e8", "#f3d45b", "#9dceae", "#d0b5ed", "#f0ad68", "#87cfd0", "#d4d0c8"]


def _layout_graph(
    graph: nx.Graph,
    metrics_by_node: dict[str, dict[str, Any]],
    *,
    max_nodes: int,
) -> dict[str, Any]:
    ranked = sorted(
        graph,
        key=lambda node: (
            -float(metrics_by_node.get(node, {}).get("weighted_degree", 0.0)),
            graph.nodes[node].get("label", node),
        ),
    )
    selected = set(ranked[:max_nodes])
    subgraph = graph.subgraph(selected).copy()
    positions = _community_layout(subgraph, metrics_by_node)
    nodes = []
    for node in sorted(subgraph):
        attrs = subgraph.nodes[node]
        metric = metrics_by_node.get(node, {})
        position = positions.get(node, (0.0, 0.0))
        nodes.append(
            {
                "id": node,
                "label": attrs.get("label", node),
                "type": attrs.get("node_type", ""),
                "doi": attrs.get("doi", ""),
                "year": attrs.get("year", ""),
                "stages": str(attrs.get("stages", "")).split("|"),
                "community": metric.get("community_id", ""),
                "weightedDegree": metric.get("weighted_degree", 0.0),
                "betweenness": metric.get("betweenness", 0.0),
                "pagerank": metric.get("pagerank", 0.0),
                "participation": metric.get("participation", 0.0),
                "x": round(float(position[0]), 6),
                "y": round(float(position[1]), 6),
                "metadataSource": attrs.get("metadata_source", ""),
                "resolution": attrs.get("resolution_confidence", ""),
                "openalexWorks": attrs.get("openalex_works_count", ""),
                "openalexCitations": attrs.get("openalex_cited_by_count", ""),
            }
        )
    edges = [
        {
            "source": source,
            "target": target,
            "weight": attrs.get("weight", 1),
        }
        for source, target, attrs in subgraph.edges(data=True)
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": graph.number_of_nodes() > max_nodes,
        "totalNodes": graph.number_of_nodes(),
        "visibleNodes": subgraph.number_of_nodes(),
    }


def _community_layout(
    graph: nx.Graph,
    metrics_by_node: dict[str, dict[str, Any]],
) -> dict[str, tuple[float, float]]:
    """Place communities and nodes on deterministic concentric circles."""
    communities: dict[int, list[str]] = {}
    for node in graph:
        community = int(metrics_by_node.get(node, {}).get("community_id", 0) or 0)
        communities.setdefault(community, []).append(node)
    ordered = sorted(communities.items(), key=lambda item: (-len(item[1]), item[0]))
    positions: dict[str, tuple[float, float]] = {}
    community_count = max(len(ordered), 1)
    for community_index, (_, members) in enumerate(ordered):
        community_angle = 2 * math.pi * community_index / community_count
        center_radius = 0.58 if community_count > 1 else 0.0
        center_x = center_radius * math.cos(community_angle)
        center_y = center_radius * math.sin(community_angle)
        ranked = sorted(
            members,
            key=lambda node: (
                -float(metrics_by_node.get(node, {}).get("weighted_degree", 0.0)),
                graph.nodes[node].get("label", node),
            ),
        )
        member_count = max(len(ranked), 1)
        local_radius = min(0.34, 0.10 + 0.035 * math.sqrt(member_count))
        for member_index, node in enumerate(ranked):
            angle = 2 * math.pi * member_index / member_count + community_angle / 3
            radius = 0.0 if member_count == 1 else local_radius
            positions[node] = (
                max(-1.0, min(1.0, center_x + radius * math.cos(angle))),
                max(-1.0, min(1.0, center_y + radius * math.sin(angle))),
            )
    return positions


def build_atlas_payload(
    title: str,
    graphs: dict[str, nx.Graph],
    centrality_rows: list[dict[str, Any]],
    layer_summaries: dict[str, Any],
    selection_drift: list[dict[str, Any]],
    coverage: dict[str, Any],
    author_production: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = {
        layer: {
            row["node_id"]: row
            for row in centrality_rows
            if row["layer"] == layer
        }
        for layer in graphs
    }
    views = {
        view: _layout_graph(graphs[layer], metrics[layer], max_nodes=200)
        for view, layer in VIEW_LAYERS.items()
    }
    views["selection"] = _selection_layout(selection_drift)
    summaries = dict(layer_summaries)
    summaries["selection"] = {
        "layer": "selection",
        "nodes": views["selection"]["totalNodes"],
        "edges": len(views["selection"]["edges"]),
        "coverage": 1.0,
        "community_count": 2,
        "community_stability": None,
        "claim_status": "descriptive",
        "stage_counts": coverage.get("stage_counts", {}),
    }
    return {
        "title": title,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "views": views,
        "layerSummaries": summaries,
        "coverage": coverage,
        "authorProductionCount": len(author_production),
        "definitions": {
            "weightedDegree": "Suma de la fuerza de los vínculos directos del nodo.",
            "betweenness": "Proporción de caminos mínimos ponderados que atraviesan el nodo.",
            "pagerank": "Centralidad recursiva basada en la posición de los nodos vecinos.",
            "participation": "Diversidad de conexiones del nodo entre comunidades.",
            "hhi": "Concentración de la conectividad; no mide calidad científica.",
        },
    }


def _selection_layout(selection_drift: list[dict[str, Any]]) -> dict[str, Any]:
    selected_rows: list[dict[str, Any]] = []
    for entity_type in ("author", "keyword"):
        candidates = [row for row in selection_drift if row["entity_type"] == entity_type]
        candidates.sort(
            key=lambda row: (
                -int(row.get("master_count", 0)),
                -int(row.get("included_count", 0)),
                row["label"].casefold(),
            )
        )
        selected_rows.extend(candidates[:90])

    stages = list(STAGE_LABELS)
    nodes = [
        {
            "id": f"stage:{stage}",
            "label": STAGE_LABELS[stage],
            "type": "stage",
            "doi": "",
            "year": "",
            "stages": [stage],
            "community": 2,
            "weightedDegree": sum(int(row.get(f"{stage}_count", 0)) for row in selected_rows),
            "betweenness": 0.0,
            "pagerank": 0.0,
            "participation": 0.0,
            "x": -0.9 + 1.8 * index / max(len(stages) - 1, 1),
            "y": -0.72,
            "metadataSource": "review",
            "resolution": "not_applicable",
            "openalexWorks": "",
            "openalexCitations": "",
            "counts": {},
        }
        for index, stage in enumerate(stages)
    ]
    edges = []
    grouped = {
        entity_type: [row for row in selected_rows if row["entity_type"] == entity_type]
        for entity_type in ("author", "keyword")
    }
    for group_index, (entity_type, rows) in enumerate(grouped.items()):
        count = max(len(rows), 1)
        for index, row in enumerate(rows):
            counts = {stage: int(row.get(f"{stage}_count", 0)) for stage in stages}
            active_stages = [stage for stage, value in counts.items() if value > 0]
            nodes.append(
                {
                    "id": row["entity_id"],
                    "label": row["label"],
                    "type": entity_type,
                    "doi": "",
                    "year": "",
                    "stages": active_stages,
                    "community": group_index,
                    "weightedDegree": sum(counts.values()),
                    "betweenness": 0.0,
                    "pagerank": 0.0,
                    "participation": 0.0,
                    "x": -0.95 + 1.9 * index / max(count - 1, 1),
                    "y": -0.05 + 0.62 * group_index,
                    "metadataSource": "review+openalex",
                    "resolution": row.get("resolution_confidence", ""),
                    "openalexWorks": "",
                    "openalexCitations": "",
                    "counts": counts,
                }
            )
            for stage, value in counts.items():
                if value:
                    edges.append(
                        {
                            "source": row["entity_id"],
                            "target": f"stage:{stage}",
                            "weight": value,
                        }
                    )
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": len(selected_rows) < len(selection_drift),
        "totalNodes": len(selection_drift) + len(stages),
        "visibleNodes": len(nodes),
    }


def write_atlas(path: pathlib.Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    markup = ATLAS_TEMPLATE.replace("__TITLE__", html.escape(payload["title"]))
    generated_at = dt.datetime.fromisoformat(payload["generatedAt"].replace("Z", "+00:00"))
    generated_stamp = generated_at.strftime("%Y-%m-%d<br>%H:%M UTC")
    markup = markup.replace("__GENERATED__", generated_stamp)
    markup = markup.replace("__DATA__", encoded)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markup, encoding="utf-8")


def write_static_svgs(
    output_dir: pathlib.Path,
    payload: dict[str, Any],
) -> list[pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for view in ("authors", "topics"):
        view_data = payload["views"][view]
        summary = payload["layerSummaries"][VIEW_LAYERS[view]]
        path = output_dir / f"{view}-network.svg"
        path.write_text(
            _static_svg(payload["title"], view, view_data, summary),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _svg_text_lines(
    value: str,
    *,
    width: int,
    x: float,
    y: float,
    line_height: int,
) -> str:
    words = str(value).split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "".join(
        f'<tspan x="{x:.1f}" y="{y + index * line_height:.1f}">{html.escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )


def _static_svg(
    title: str,
    view: str,
    data: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    width, height = 1600, 1000
    left, top, graph_width, graph_height = 105, 285, 990, 555
    labels = {
        "authors": "Red de coautoría",
        "topics": (
            "Mapa exploratorio de descriptores"
            if summary.get("claim_status") != "interpretable"
            else "Red de coocurrencia temática"
        ),
    }
    max_degree = max((float(node["weightedDegree"]) for node in data["nodes"]), default=1.0) or 1.0
    nodes_by_id = {node["id"]: node for node in data["nodes"]}
    ranked = sorted(
        data["nodes"],
        key=lambda node: (-float(node["weightedDegree"]), str(node["label"]).casefold()),
    )
    callout_nodes = ranked[:8]
    callout_ids = {node["id"]: index + 1 for index, node in enumerate(callout_nodes)}
    edge_markup = []
    for edge in data["edges"]:
        source = nodes_by_id.get(edge["source"])
        target = nodes_by_id.get(edge["target"])
        if not source or not target:
            continue
        x1 = left + (source["x"] + 1) * graph_width / 2
        y1 = top + (source["y"] + 1) * graph_height / 2
        x2 = left + (target["x"] + 1) * graph_width / 2
        y2 = top + (target["y"] + 1) * graph_height / 2
        edge_markup.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#111" stroke-opacity=".14" stroke-width="{min(4, 0.7 + float(edge["weight"]) ** 0.5):.1f}"/>'
        )
    node_markup = []
    for node in data["nodes"]:
        x = left + (node["x"] + 1) * graph_width / 2
        y = top + (node["y"] + 1) * graph_height / 2
        radius = 5 + 18 * math.sqrt(float(node["weightedDegree"]) / max_degree)
        color = PALETTE[int(node["community"] or 0) % len(PALETTE)]
        node_markup.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{color}" '
            'stroke="#111" stroke-width="3"/>'
        )
        callout = callout_ids.get(node["id"])
        if callout:
            node_markup.append(
                f'<text x="{x:.1f}" y="{y + 5:.1f}" text-anchor="middle" '
                'font-family="Avenir Next, Segoe UI, sans-serif" font-size="14" '
                f'font-weight="700">{callout}</text>'
            )
    callout_markup = []
    for index, node in enumerate(callout_nodes):
        row_y = 354 + index * 64
        color = PALETTE[int(node["community"] or 0) % len(PALETTE)]
        label = str(node["label"])
        degree_label = format(float(node["weightedDegree"]), ".3g")
        callout_markup.append(
            f'<circle cx="1210" cy="{row_y:.1f}" r="17" fill="{color}" stroke="#111" stroke-width="3"/>'
            f'<text x="1210" y="{row_y + 5:.1f}" text-anchor="middle" '
            'font-family="Avenir Next, Segoe UI, sans-serif" font-size="14" '
            f'font-weight="700">{index + 1}</text>'
            f'<text x="1242" y="{row_y - 3:.1f}" fill="#111" '
            'font-family="Avenir Next, Segoe UI, sans-serif" font-size="17" font-weight="700">'
            f'{_svg_text_lines(label, width=29, x=1242, y=row_y - 3, line_height=19)}</text>'
            f'<text x="1242" y="{row_y + 35:.1f}" fill="#555" '
            'font-family="Avenir Next, Segoe UI, sans-serif" font-size="13">'
            f'Grado ponderado {html.escape(degree_label)}</text>'
        )
    status_labels = {
        "interpretable": "INTERPRETABLE",
        "exploratory": "EXPLORATORIO",
        "entities_only": "SOLO ENTIDADES",
        "descriptive": "DESCRIPTIVO",
    }
    status = status_labels.get(summary.get("claim_status"), str(summary.get("claim_status", "")).upper())
    stability = float(summary.get("community_stability") or 0.0)
    review_title = _svg_text_lines(title, width=118, x=75, y=207, line_height=25)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="network-title network-description">
<title id="network-title">{html.escape(labels[view])}</title>
<desc id="network-description">{html.escape(title)}</desc>
<rect width="1600" height="1000" fill="#ffffff"/>
<rect x="65" y="42" width="90" height="7" fill="#30343b"/>
<text x="65" y="112" fill="#111" font-family="Iowan Old Style, Palatino Linotype, Georgia, serif" font-size="48" font-weight="700">{html.escape(labels[view])}</text>
<text fill="#4f555e" font-family="Avenir Next, Segoe UI, sans-serif" font-size="21">{review_title}</text>
<rect x="65" y="255" width="1060" height="625" fill="#fbfbfa" stroke="#b9bec5" stroke-width="1.5"/>
{"".join(edge_markup)}
{"".join(node_markup)}
<rect x="1150" y="255" width="385" height="625" fill="#ffffff" stroke="#b9bec5" stroke-width="1.5"/>
<text x="1177" y="303" fill="#111" font-family="Iowan Old Style, Palatino Linotype, Georgia, serif" font-size="24" font-weight="700">Nodos principales</text>
<line x1="1177" y1="322" x2="1508" y2="322" stroke="#b9bec5" stroke-width="1"/>
{"".join(callout_markup)}
<line x1="65" y1="915" x2="1535" y2="915" stroke="#b9bec5" stroke-width="1"/>
<text x="65" y="948" fill="#4f555e" font-family="Avenir Next, Segoe UI, sans-serif" font-size="16">
{data["visibleNodes"]} de {data["totalNodes"]} nodos · {len(data["edges"])} vínculos · {int(round(float(summary.get("coverage", 0)) * 100))}% cobertura · {int(round(stability * 100))}% estabilidad · {html.escape(status.title())}
</text>
</svg>
"""


ATLAS_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">
  <title>Atlas estructural · __TITLE__</title>
  <style>
    :root{color-scheme:light;--ink:#20242a;--muted:#626a75;--rule:#c9ced5;--paper:#f4f5f6;--panel:#fff;--soft:#eef1f4;--accent:#334b68;--focus:#8db8e8}
    *{box-sizing:border-box}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "Avenir Next","Segoe UI",sans-serif}
    button,input,select{font:inherit}.shell{max-width:1640px;margin:auto;padding:38px 28px 64px}.mast{display:grid;grid-template-columns:1fr auto;gap:32px;align-items:end;border-top:7px solid var(--ink);border-bottom:1px solid var(--rule);background:var(--panel);padding:30px 32px 26px}
    .eyebrow{display:inline-block;color:var(--accent);font:700 12px/1.2 "Avenir Next","Segoe UI",sans-serif;text-transform:uppercase;letter-spacing:.14em}
    h1,h2,h3{font-family:"Iowan Old Style","Palatino Linotype",Georgia,serif}h1{font-size:clamp(36px,4.7vw,68px);line-height:1.02;margin:14px 0 10px;max-width:1100px}.mast p{max-width:920px;margin:0;color:var(--muted);font-size:18px}.stamp{color:var(--muted);font:600 12px/1.55 "Avenir Next","Segoe UI",sans-serif;text-align:right;letter-spacing:.04em}
    .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;margin:22px 0;background:var(--rule);border:1px solid var(--rule)}.kpi{padding:17px 18px;background:var(--panel)}.kpi strong{display:block;font-family:"Iowan Old Style","Palatino Linotype",Georgia,serif;font-size:30px;line-height:1.1}.kpi span{display:block;margin-bottom:5px;color:var(--muted);font-size:11px;text-transform:uppercase;font-weight:700;letter-spacing:.09em}
    .controls{display:flex;gap:8px;flex-wrap:wrap;border:1px solid var(--rule);background:var(--panel);padding:12px}.controls button,.controls input,.controls select,.controls a{border:1px solid var(--rule);border-radius:3px;padding:9px 12px;background:#fff;color:var(--ink)}.controls button:hover,.controls a:hover{border-color:var(--accent)}.controls button:focus-visible,.controls input:focus-visible,.controls select:focus-visible,.controls a:focus-visible{outline:3px solid color-mix(in srgb,var(--focus) 65%,transparent);outline-offset:2px}.controls button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}.controls input{min-width:230px}.controls a{display:inline-flex;align-items:center;font-weight:650;text-decoration:none}.export{background:var(--soft)!important;font-weight:700}.export-group{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
    .grid{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:18px;margin-top:18px}.canvas,.side,.table-wrap,.method{border:1px solid var(--rule);background:var(--panel)}.canvas{min-height:690px;position:relative;overflow:hidden}.canvas svg{width:100%;height:690px;display:block}
    .legend{position:absolute;left:18px;bottom:18px;max-width:460px;border:1px solid var(--rule);background:rgba(255,255,255,.94);padding:10px 12px;color:var(--muted);font-size:12px}.side{padding:24px}.side h2{font-size:29px;line-height:1.08;margin:12px 0 18px}.status{display:inline-block;padding:4px 8px;border:1px solid var(--rule);background:var(--soft);color:var(--accent);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}.metric{border-top:1px solid var(--rule);padding:10px 0;display:flex;justify-content:space-between;gap:12px}.metric b{text-align:right}
    .table-wrap,.method{margin-top:18px;padding:24px;overflow:auto}.table-wrap{max-height:720px}.table-wrap h2{margin-top:0}.table-wrap table{border-collapse:collapse;width:100%;min-width:900px}.table-wrap th,.table-wrap td{border-bottom:1px solid var(--rule);padding:10px;text-align:left}.table-wrap th{position:sticky;top:0;background:var(--soft);z-index:1;color:var(--accent);font-size:12px;text-transform:uppercase;letter-spacing:.05em}.method{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}.method article{padding:4px 6px;background:#fff}.method article+article{border-left:1px solid var(--rule);padding-left:28px}.method h3{margin:0 0 8px;font-size:22px}
    .edge{stroke:#4f5964;stroke-opacity:.16}.node{stroke:#30343b;stroke-width:2;cursor:pointer}.node:focus{stroke-width:5;outline:none}.label{font-size:11px;font-weight:700;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}
    .empty{padding:80px 30px;text-align:center;font:600 22px "Iowan Old Style","Palatino Linotype",Georgia,serif}@media(max-width:1050px){.kpis{grid-template-columns:repeat(3,1fr)}.grid{grid-template-columns:1fr}.canvas svg{height:620px}.method{grid-template-columns:1fr}.method article+article{border-left:0;border-top:1px solid var(--rule);padding:22px 6px 4px}.stamp{text-align:left}.export-group{width:100%;margin-left:0}}@media(max-width:620px){.shell{padding:18px 10px 40px}.mast{grid-template-columns:1fr;padding:22px 18px}.kpis{grid-template-columns:repeat(2,1fr)}.controls button{flex:1 1 calc(33.333% - 10px)}.controls label,.controls input,.controls select{width:100%}.export-group{display:grid;grid-template-columns:1fr 1fr;width:100%}.export-group button,.export-group a{justify-content:center}.canvas{min-height:530px}.canvas svg{height:530px}}
    @media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}@media print{body{background:#fff}.controls{display:none}.shell{max-width:none;padding:0}.canvas{break-inside:avoid}.side{break-inside:avoid}}
  </style>
</head>
<body>
<main class="shell">
  <header class="mast"><div><span class="eyebrow">Atlas estructural reproducible</span><h1>__TITLE__</h1><p>Relaciones del corpus, comunidades, centralidad y deriva entre fases con cobertura y límites visibles.</p></div><div class="stamp">GENERADO<br>__GENERATED__<br>OFFLINE · SIN CDN</div></header>
  <section class="kpis" id="kpis" aria-label="Indicadores principales"></section>
  <nav class="controls" aria-label="Controles del atlas">
    <button data-view="authors" aria-pressed="true">Autores</button><button data-view="topics" aria-pressed="false">Temas</button><button data-view="citations" aria-pressed="false">Citas</button><button data-view="evidence" aria-pressed="false">Evidencia</button><button data-view="selection" aria-pressed="false">Fases</button>
    <label><span class="sr-only">Fase</span><select id="stage"><option value="">Todas las fases</option><option value="master">Corpus maestro</option><option value="title_abstract_retained">Retenido en título/resumen</option><option value="full_text_assessed">Texto completo</option><option value="included">Incluido</option><option value="focal">Focal</option></select></label>
    <input id="search" type="search" placeholder="Buscar nodo…" aria-label="Buscar nodo">
    <span class="export-group" aria-label="Descargas de la vista">
      <button class="export" id="download-png" type="button">PNG</button>
      <button class="export" id="download-svg" type="button">SVG</button>
      <button class="export" id="download-gexf" type="button">GEXF · Gephi</button>
      <a href="../data/graph.graphml" download>GraphML completo</a>
    </span>
  </nav>
  <section class="grid"><div class="canvas" id="canvas" aria-label="Visualización de red"></div><aside class="side" id="detail" aria-live="polite"></aside></section>
  <section class="table-wrap"><h2>Tabla accesible de nodos visibles</h2><table><thead><tr><th>Entidad</th><th>Tipo</th><th>Comunidad</th><th>Grado ponderado</th><th>Intermediación</th><th>Fases</th></tr></thead><tbody id="node-table"></tbody></table></section>
  <section class="method"><article><h3>Qué significa</h3><p>La topología describe cómo se conectan las entidades recuperadas. No demuestra calidad, influencia causal ni autoridad científica.</p></article><article><h3>Cómo leerla</h3><p>El tamaño representa grado ponderado y el color una comunidad algorítmica. La interpretación depende del estado y la cobertura mostrados.</p></article><article><h3>Qué no hace</h3><p>La productividad, las citas y la centralidad no intervienen en inclusión, exclusión, evaluación crítica ni selección focal.</p></article></section>
</main>
<script>
const DATA=__DATA__;
const COLORS=["#f3a6a0","#8db8e8","#f3d45b","#9dceae","#d0b5ed","#f0ad68","#87cfd0","#d4d0c8"];
const LAYERS={authors:"coauthorship",topics:"keyword_cooccurrence",citations:"bibliographic_coupling",evidence:"evidence",selection:"selection"};
const LABELS={authors:"Coautoría",topics:"Coocurrencia temática",citations:"Acoplamiento bibliográfico",evidence:"Relaciones de evidencia",selection:"Deriva entre fases"};
const STATUS_LABELS={interpretable:"Interpretable",exploratory:"Exploratorio",entities_only:"Solo entidades",descriptive:"Descriptivo"};
let state={view:"authors",stage:"",search:"",selected:null};
const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[char]));
const xml=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&apos;"}[char]));
const fmt=value=>Number(value||0).toLocaleString("es-ES",{maximumFractionDigits:3});
const stability=value=>value===null||value===undefined?"No aplica":`${fmt(Number(value)*100)}%`;
const status=value=>STATUS_LABELS[value]||value;
const slug=value=>String(value||"atlas").normalize("NFD").replace(/[\\u0300-\\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,70);
function current(){return DATA.views[state.view]}
function filtered(){
  const view=current(),query=state.search.trim().toLocaleLowerCase("es");
  const nodes=view.nodes.filter(node=>(!state.stage||node.stages.includes(state.stage))&&(!query||node.label.toLocaleLowerCase("es").includes(query)));
  const ids=new Set(nodes.map(node=>node.id)); return {nodes,edges:view.edges.filter(edge=>ids.has(edge.source)&&ids.has(edge.target))};
}
function renderKpis(){
  const summary=DATA.layerSummaries[LAYERS[state.view]],cards=[
    ["Nodos",summary.nodes],["Vínculos",summary.edges],["Cobertura",`${fmt(summary.coverage*100)}%`],["Comunidades",summary.community_count],["Estabilidad",stability(summary.community_stability)],["Estado",status(summary.claim_status)]
  ]; document.querySelector("#kpis").innerHTML=cards.map(([label,value])=>`<article class="kpi"><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`).join("");
}
function renderGraph(){
  const target=document.querySelector("#canvas"),data=filtered(); if(!data.nodes.length){target.innerHTML='<div class="empty">No hay nodos para este filtro.</div>';renderTable(data.nodes);return}
  const width=1100,height=690,pad=55,mapX=x=>pad+(x+1)*(width-2*pad)/2,mapY=y=>pad+(y+1)*(height-2*pad)/2,max=Math.max(...data.nodes.map(n=>Number(n.weightedDegree)||0),1),byId=new Map(data.nodes.map(n=>[n.id,n]));
  const edges=data.edges.map(edge=>{const a=byId.get(edge.source),b=byId.get(edge.target);return `<line class="edge" x1="${mapX(a.x)}" y1="${mapY(a.y)}" x2="${mapX(b.x)}" y2="${mapY(b.y)}" stroke-width="${Math.min(7,1+Number(edge.weight||1))}"/>`}).join("");
  const ranked=[...data.nodes].sort((a,b)=>b.weightedDegree-a.weightedDegree),labelIds=new Set(ranked.slice(0,16).map(n=>n.id));
  const nodes=data.nodes.map(node=>{const r=7+19*Number(node.weightedDegree||0)/max,color=COLORS[Number(node.community||0)%COLORS.length],label=labelIds.has(node.id)?`<text class="label" x="${mapX(node.x)+r+5}" y="${mapY(node.y)+4}">${esc(node.label.slice(0,34))}</text>`:"";return `<g><circle class="node" role="button" tabindex="0" aria-label="${esc(node.label)}" data-id="${esc(node.id)}" cx="${mapX(node.x)}" cy="${mapY(node.y)}" r="${r}" fill="${color}"/>${label}</g>`}).join("");
  target.innerHTML=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(LABELS[state.view])}">${edges}${nodes}</svg><div class="legend">${esc(LABELS[state.view])}. Tamaño: grado ponderado. Color: comunidad. Se muestran ${data.nodes.length} nodos${current().truncated?" sobre una vista truncada para legibilidad":""}.</div>`;
  target.querySelectorAll(".node").forEach(node=>{const choose=()=>{state.selected=byId.get(node.dataset.id);renderDetail()};node.addEventListener("click",choose);node.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();choose()}})});
  renderTable(data.nodes); if(!state.selected||!byId.has(state.selected.id)){state.selected=ranked[0]} renderDetail();
}
function renderDetail(){
  const summary=DATA.layerSummaries[LAYERS[state.view]],node=state.selected,box=document.querySelector("#detail");
  if(!node){box.innerHTML="<h2>Selecciona un nodo</h2>";return}
  const counts=node.counts?Object.entries(node.counts).map(([stage,value])=>`<div class="metric"><span>${esc(stage)}</span><b>${esc(value)}</b></div>`).join(""):"";
  const stabilityText=summary.community_stability===null||summary.community_stability===undefined?"No aplica a esta vista":`${stability(summary.community_stability)} (umbral ≥ 80%)`;
  box.innerHTML=`<span class="status">${esc(status(summary.claim_status))}</span><h2>${esc(node.label)}</h2><p>${esc(node.type)}${node.doi?` · DOI ${esc(node.doi)}`:""}</p><div class="metric"><span>Grado ponderado</span><b>${fmt(node.weightedDegree)}</b></div>${state.view!=="selection"?`<div class="metric"><span>Intermediación</span><b>${fmt(node.betweenness)}</b></div><div class="metric"><span>PageRank</span><b>${fmt(node.pagerank)}</b></div><div class="metric"><span>Participación</span><b>${fmt(node.participation)}</b></div><div class="metric"><span>Comunidad</span><b>${esc(node.community)}</b></div>`:""}${counts}${node.openalexWorks!==""?`<div class="metric"><span>Obras en OpenAlex</span><b>${esc(node.openalexWorks)}</b></div>`:""}<p><b>Cobertura:</b> ${fmt(summary.coverage*100)}%. <b>Estabilidad:</b> ${stabilityText}.</p>`;
}
function renderTable(nodes){document.querySelector("#node-table").innerHTML=[...nodes].sort((a,b)=>b.weightedDegree-a.weightedDegree).slice(0,250).map(node=>`<tr><td>${esc(node.label)}</td><td>${esc(node.type)}</td><td>${esc(node.community)}</td><td>${fmt(node.weightedDegree)}</td><td>${fmt(node.betweenness)}</td><td>${esc(node.stages.join(", "))}</td></tr>`).join("")}
function saveBlob(blob,name){
  const url=URL.createObjectURL(blob),link=document.createElement("a");
  link.href=url;link.download=name;document.body.append(link);link.click();link.remove();
  window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function wrapTitle(value,limit=78){
  const words=String(value).split(/\\s+/),lines=[];let line="";
  words.forEach(word=>{const candidate=line?`${line} ${word}`:word;if(line&&candidate.length>limit){lines.push(line);line=word}else{line=candidate}});
  if(line)lines.push(line);return lines.slice(0,2);
}
function exportSvgMarkup(){
  const source=document.querySelector("#canvas svg");
  if(!source)return "";
  const summary=DATA.layerSummaries[LAYERS[state.view]],data=filtered(),titleLines=wrapTitle(DATA.title);
  const titleMarkup=titleLines.map((line,index)=>`<text x="62" y="${142+index*35}" fill="#4f555e" font-family="Avenir Next, Segoe UI, sans-serif" font-size="24">${xml(line)}</text>`).join("");
  const graphTop=titleLines.length>1?205:180;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
  <rect width="1600" height="1000" fill="#fff"/>
  <style>.edge{stroke:#4f5964;stroke-opacity:.16}.node{stroke:#30343b;stroke-width:2}.label{font:700 11px Avenir Next,Segoe UI,sans-serif;paint-order:stroke;stroke:#fff;stroke-width:4px;stroke-linejoin:round}</style>
  <rect x="36" y="30" width="90" height="7" fill="#30343b"/>
  <text x="62" y="92" fill="#111" font-family="Iowan Old Style, Palatino Linotype, Georgia, serif" font-size="38" font-weight="700">${xml(LABELS[state.view])}</text>
  ${titleMarkup}
  <rect x="36" y="${graphTop}" width="1528" height="${900-graphTop}" fill="#fbfbfa" stroke="#b9bec5" stroke-width="1.5"/>
  <svg x="50" y="${graphTop+10}" width="1500" height="${870-graphTop}" viewBox="0 0 1100 690">${source.innerHTML}</svg>
  <line x1="36" y1="930" x2="1564" y2="930" stroke="#b9bec5" stroke-width="1"/>
  <text x="58" y="960" fill="#4f555e" font-family="Avenir Next, Segoe UI, sans-serif" font-size="16">${data.nodes.length} nodos · ${data.edges.length} vínculos · ${fmt(summary.coverage*100)}% cobertura · ${xml(status(summary.claim_status))}</text>
  </svg>`;
}
function downloadSvg(){
  const markup=exportSvgMarkup();if(!markup)return;
  saveBlob(new Blob([markup],{type:"image/svg+xml;charset=utf-8"}),`${slug(DATA.title)}-${state.view}.svg`);
}
function downloadPng(){
  const markup=exportSvgMarkup();if(!markup)return;
  const image=new Image();
  image.onload=()=>{
    const canvas=document.createElement("canvas");canvas.width=3200;canvas.height=2000;
    const context=canvas.getContext("2d");context.scale(2,2);context.drawImage(image,0,0,1600,1000);
    canvas.toBlob(blob=>{if(blob)saveBlob(blob,`${slug(DATA.title)}-${state.view}.png`)},"image/png");
  };
  image.src=`data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
}
function downloadGexf(){
  const data=filtered(),date=String(DATA.generatedAt||"").slice(0,10);
  const attributes=[
    ["0","type","string"],["1","doi","string"],["2","year","string"],["3","community","integer"],
    ["4","weighted_degree","double"],["5","betweenness","double"],["6","pagerank","double"],
    ["7","participation","double"],["8","stages","string"],["9","metadata_source","string"],["10","resolution","string"]
  ];
  const attributeXml=attributes.map(([id,title,type])=>`<attribute id="${id}" title="${title}" type="${type}"/>`).join("");
  const nodes=data.nodes.map(node=>{
    const values=[node.type,node.doi,node.year,Number(node.community||0),Number(node.weightedDegree||0),Number(node.betweenness||0),Number(node.pagerank||0),Number(node.participation||0),node.stages.join("|"),node.metadataSource,node.resolution];
    return `<node id="${xml(node.id)}" label="${xml(node.label)}"><attvalues>${values.map((value,index)=>`<attvalue for="${index}" value="${xml(value)}"/>`).join("")}</attvalues></node>`;
  }).join("");
  const edges=data.edges.map((edge,index)=>`<edge id="${index}" source="${xml(edge.source)}" target="${xml(edge.target)}" weight="${xml(Number(edge.weight||1))}"/>`).join("");
  const markup=`<?xml version="1.0" encoding="UTF-8"?><gexf xmlns="http://www.gexf.net/1.2draft" version="1.2"><meta lastmodifieddate="${xml(date)}"><creator>Hermes Research Pack</creator><description>${xml(LABELS[state.view])} · ${xml(DATA.title)}</description></meta><graph mode="static" defaultedgetype="undirected"><attributes class="node">${attributeXml}</attributes><nodes>${nodes}</nodes><edges>${edges}</edges></graph></gexf>`;
  saveBlob(new Blob([markup],{type:"application/gexf+xml;charset=utf-8"}),`${slug(DATA.title)}-${state.view}.gexf`);
}
function render(){state.selected=null;renderKpis();renderGraph()}
document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{state.view=button.dataset.view;document.querySelectorAll("[data-view]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));render()}));
document.querySelector("#stage").addEventListener("change",event=>{state.stage=event.target.value;render()});
document.querySelector("#search").addEventListener("input",event=>{state.search=event.target.value;renderGraph()});
document.querySelector("#download-png").addEventListener("click",downloadPng);
document.querySelector("#download-svg").addEventListener("click",downloadSvg);
document.querySelector("#download-gexf").addEventListener("click",downloadGexf);
render();
</script>
</body>
</html>
"""
