# Methodological contract

## Unit of identity

A study node is identified only by a normalized DOI. Internal row identifiers
must not appear in reader-facing tables, figures, or atlas labels. Records
without a DOI may be counted in upstream acquisition diagnostics, but they do
not enter the inferential network.

Authors are resolved in this order:

1. OpenAlex author identifier attached to a DOI-resolved work.
2. ORCID attached to that author.
3. A conservative normalized display-name key scoped to the available corpus.

Name-only matches are explicitly marked as lower-confidence resolution. They
must not be silently merged when names are ambiguous.

## Corpus stages

Every study may belong to one or more cumulative stages:

- `master`: normalized DOI record exists.
- `title_abstract_retained`: title/abstract screening did not exclude it.
- `full_text_assessed`: a full-text decision was recorded.
- `included`: full-text screening included it.
- `focal`: the intensive-synthesis shortlist selected it.

Stage analysis reports counts and retention rates. It does not reinterpret an
eligibility decision.

## Graph semantics

- `authorship`: bipartite author-study links.
- `coauthorship`: undirected author links weighted by shared studies.
- `citation`: directed study-to-study links when a source references a target.
- `bibliographic_coupling`: undirected study links weighted by shared
  references.
- `cocitation`: undirected referenced-work links weighted by joint citation.
- `keyword_cooccurrence`: undirected keyword links weighted by shared studies.
- `evidence`: study-to-theory, method, variable, outcome, and context links.

Each exported edge declares its graph layer, weight, source, and stage.
Centrality, concentration, and community metrics use the `included` subgraph.
Earlier stages remain available through selection-drift counts and are never
silently mixed into the inferential topology.

## Metrics

Node-level outputs may include degree centrality, weighted degree,
betweenness, harmonic centrality, PageRank, eigenvector centrality, k-core,
clustering, and participation coefficient. Metrics that are mathematically
undefined for a graph remain empty and receive an explanation in the audit.

Global outputs include nodes, edges, density, connected components, giant
component share, transitivity, average clustering, modularity, community count,
centralization, Herfindahl-Hirschman concentration, and metadata coverage.

Weighted betweenness uses `distance = 1 / weight`. This conversion and every
community seed, resolution, and threshold are recorded in
`analysis/audit/parameters.json`.

## Community robustness

Louvain partitions are run across deterministic seeds and candidate
resolutions. The selected partition maximizes modularity. Stability is the mean
normalized mutual information between the selected partition and the remaining
runs over the shared node set.

Interpretation requires:

- at least 20 included studies;
- author coverage of at least 85% for author-network claims;
- reference coverage of at least 70% for citation-family claims;
- keyword coverage of at least 70% for topic-network claims;
- partition stability of at least 0.80.

Failing a threshold does not delete the graph. It changes the claim status to
`exploratory`.

## Provenance and limits

Local review CSV files are the authority for screening stages. OpenAlex is used
for identifier resolution and citation metadata, with raw responses cached.
External metadata may be incomplete or lag the source publication. Coverage
must therefore accompany every interpretation.

The analysis must never create an aggregate authority score, rank authors as
better researchers, or imply causality from topology.
