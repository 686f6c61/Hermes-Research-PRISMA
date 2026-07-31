---
name: research-network-analysis
description: Build an auditable bibliometric and evidence-network atlas from a systematic-review workspace.
---

# Research Network Analysis

Use this skill after screening and extraction have produced DOI-based records.
It adds a structural view of the corpus without changing eligibility decisions.

## What it builds

- Authorship and co-authorship networks.
- Direct citation, bibliographic coupling, and co-citation networks when
  references are recoverable.
- Keyword co-occurrence and heterogeneous evidence networks.
- Selection-stage retention for authors and keywords.
- Centrality, concentration, community, stability, and coverage diagnostics.
- A self-contained offline HTML atlas plus CSV, JSON, GraphML, PNG, and SVG outputs.
- Per-view PNG, SVG, and GEXF exports that preserve the active filters; the
  GEXF can be opened directly in Gephi.

## Scientific boundary

Network position is descriptive evidence, not a proxy for quality, authority,
truth, or eligibility. Author productivity and citation counts must never
influence inclusion, exclusion, focal selection, or critical-appraisal scores.
Every metric must expose its denominator, source coverage, parameters, and
generation date.

Community interpretation follows these rules:

- Fewer than 10 included studies: report entities and links only.
- Between 10 and 19 included studies: communities are exploratory.
- At least 20 included studies: communities may be interpreted only when
  metadata coverage and multi-seed stability pass the declared thresholds.
- Unstable or low-coverage structures remain visible but are labelled
  exploratory rather than converted into substantive claims.

## Command

The end-to-end review invokes the analysis automatically. Maintainers can
rebuild it independently with:

```bash
python3 scripts/build_network_analysis.py /workspace/<review-dir>
```

The command is idempotent. It reads existing review artifacts, reuses cached
OpenAlex records, and writes only inside `<review-dir>/analysis/`.

## Required outputs

- `analysis/manifest.json`
- `analysis/methodology.md`
- `analysis/summary.md`
- `analysis/atlas/network-atlas.html`
- `analysis/data/nodes.csv`
- `analysis/data/edges.csv`
- `analysis/data/graph.graphml`
- `analysis/metrics/network-summary.json`
- `analysis/metrics/centrality.csv`
- `analysis/metrics/communities.csv`
- `analysis/metrics/author-production.csv`
- `analysis/metrics/selection-drift.csv`
- `analysis/audit/coverage.json`
- `analysis/audit/parameters.json`
- `analysis/audit/provenance.csv`

The HTML atlas generates a filtered GEXF client-side. This keeps the offline
artifact self-contained while letting a reader move the exact visible subgraph
into Gephi without changing the source workspace.

Read `references/methodology.md` before changing thresholds, graph semantics,
community detection, or the language used in manuscript synthesis.
