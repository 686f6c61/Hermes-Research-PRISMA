# Artifacts

Una instalación buena de Hermes Research Pack deja rastros muy concretos en
disco. Esa es una parte central del producto.

El primer archivo que debe abrir una persona al recibir una revisión es
`paper/package/index.html`. Es una guía offline, no una landing: resume estado y
métricas, explica el orden de lectura y enlaza los doce bloques de la entrega.
`paper/package/deliverables-manifest.json` contiene la misma estructura en
formato máquina, con tamaños y hashes SHA-256.

## Artefactos tempranos

Después de crear una revisión nueva deberían aparecer muy pronto:

- `protocol/intake.md`
- `protocol/research-question.md`
- `protocol/eligibility-criteria.md`
- `protocol/search-strategy.md`
- `protocol/intake.json`
- `protocol/method-contract.json`
- `protocol/synthesis-plan.json`
- `protocol/journal-profile.json`
- `protocol/deliverables-contract.json`
- `protocol/contracts-manifest.json`
- `protocol/amendments.jsonl`
- `notes/runtime-state.json`

Estos archivos fijan el alcance y permiten releer el estado sin depender del
chat ni de la memoria del operador.

## Artefactos intermedios

Cuando la revisión entra en búsqueda, cribado y extracción, deberían aparecer:

- `searches/search-log.csv`
- `records/master-records.csv`
- `screening/title-abstract.csv`
- `screening/title-abstract-dual-review.csv`
- `screening/full-text.csv`
- `screening/full-text-dual-review.csv`
- `screening/screening-reliability.json`
- `screening/full-text-review-checkpoint.json`
- `screening/pending-disagreements.json`
- `screening/disagreement-resolutions.jsonl`
- `extraction/extraction-table.csv`
- `selection/ultraquality-shortlist.csv`
- `fulltext/docling/manifest.csv`
- `fulltext/docling/<doi>.json`
- `fulltext/docling/<doi>.md`
- `tables/source/<doi>-table-XX.csv`
- `tables/source/<doi>-table-XX.html`
- `figures/source/<doi>-figure-XX.png`

Después de extracción también se genera la capa estructural:

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

El atlas es autónomo y no descarga librerías al abrirse. Las tablas conservan
denominadores y permiten recalcular o cuestionar la lectura visual.

Cada vista se puede descargar en PNG o SVG para comunicación y en GEXF para
análisis en Gephi. La exportación conserva la capa, la fase y el filtro de
búsqueda activos; `analysis/data/graph.graphml` mantiene la red completa como
formato de intercambio independiente.

`fulltext/docling/manifest.csv` registra el hash exacto del PDF, estado,
duración, páginas, tablas, figuras, versión y error saneado. Los nombres de los
activos se derivan del DOI; no se publican identificadores internos.

`full-text-review-checkpoint.json` vincula los dos juicios con el protocolo y
el hash del texto completo. `pending-disagreements.json` conserva todos los
casos A/B, incluso después de resolverlos, y distingue cuántos siguen
pendientes. `disagreement-resolutions.jsonl` es un registro append-only de las
decisiones firmadas por DOI y de su razón científica.

Estos tres archivos son privados: preservan trazabilidad y reanudación, pero no
entran en el paquete público con identidades internas o datos de firma.

## Artefactos de publicación

Cuando la capa editorial termina bien, deberían existir:

- `paper/manuscript/publication-ready.md`
- `paper/manuscript/publication-ready.tex`
- `paper/manuscript/publication-ready.pdf`
- `paper/audit/model-capabilities.json`
- `paper/audit/model-provenance.csv`
- `paper/audit/claim-evidence-ledger.csv`
- `paper/audit/evidence-coverage.json`
- `paper/audit/publication-gate.json`
- `paper/audit/gold/gold-manifest.json`
- `paper/audit/gold/title-abstract-gold.csv`
- `paper/audit/gold/full-text-gold.csv`
- `paper/audit/gold/extraction-gold.jsonl`
- `paper/package/index.html`
- `paper/package/deliverables-manifest.json`
- `paper/audit/publication-gate.md`
- `paper/package/publication-package.zip`
- `paper/package/publication-latex-editable.zip`

El ZIP de publicación abre también con `index.html`. Sus anexos eliminan
`record_id`, convierten `assigned_doi` en `doi`, sustituyen nombres de PDF
internos por DOI y sanea rutas locales. Los registros sin DOI pueden conservarse
en conteos de exclusión, pero no reciben una identidad pública opaca.

El directorio `paper/audit/gold/` contiene la referencia operacional generada
durante el ciclo. El manifiesto declara si cada etiqueta procede de consenso,
recomendación o decisión investigadora firmada y deja explícito que no es un
ground truth humano externo.

## Los doce bloques de entrega

1. Método y protocolo: frontera científica, unidad de comparación y lógica de síntesis.
2. Corpus bibliográfico: búsquedas, DOI, duplicados y referencias.
3. Cribado y selección: decisión, motivo y frontera focal.
4. Biblioteca de texto completo: documentos, hashes y extracción estructurada.
5. Matriz de evidencia: método, variables, resultados, fragmentos y páginas.
6. Síntesis y análisis: appraisal, sensibilidad, redes y comunidades.
7. Figuras y tablas: fuente editable, versión de publicación y justificación.
8. Manuscrito publicable: Markdown, LaTeX, PDF, referencias y anexos.
9. Preparación editorial: peer review, roadmap, carta, declaraciones y checklists.
10. Auditoría y procedencia: modelos, evidencia, integridad y gates.
11. Reanudación y actualización: estado por contenido, jobs y eventos.
12. Exploración interactiva: atlas offline y exportación GraphML/GEXF.

## Qué significa todo esto

La revisión no es solo un output textual. Es un conjunto de artefactos que
permiten comprobar:

- qué se buscó
- qué se excluyó
- qué se extrajo
- cómo se relacionan autores, temas, referencias y dimensiones analíticas
- con qué cobertura y estabilidad puede interpretarse esa estructura
- cómo se redactó
- por qué se cerró o por qué sigue bloqueada
