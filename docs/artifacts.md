# Artifacts

Una instalación buena de Hermes Research Pack deja rastros muy concretos en
disco. Esa es una parte central del producto.

## Artefactos tempranos

Después de crear una revisión nueva deberían aparecer muy pronto:

- `protocol/intake.md`
- `protocol/research-question.md`
- `protocol/eligibility-criteria.md`
- `protocol/search-strategy.md`
- `notes/runtime-state.json`

Estos archivos fijan el alcance y permiten releer el estado sin depender del
chat ni de la memoria del operador.

## Artefactos intermedios

Cuando la revisión entra en búsqueda, cribado y extracción, deberían aparecer:

- `searches/search-log.csv`
- `records/master-records.csv`
- `screening/title-abstract.csv`
- `screening/full-text.csv`
- `extraction/extraction-table.csv`
- `selection/ultraquality-shortlist.csv`
- `fulltext/docling/manifest.csv`
- `fulltext/docling/<doi>.json`
- `fulltext/docling/<doi>.md`
- `tables/source/<doi>-table-XX.csv`
- `tables/source/<doi>-table-XX.html`
- `figures/source/<doi>-figure-XX.png`

`fulltext/docling/manifest.csv` registra el hash exacto del PDF, estado,
duración, páginas, tablas, figuras, versión y error saneado. Los nombres de los
activos se derivan del DOI; no se publican identificadores internos.

## Artefactos de publicación

Cuando la capa editorial termina bien, deberían existir:

- `paper/manuscript/publication-ready.md`
- `paper/manuscript/publication-ready.tex`
- `paper/manuscript/publication-ready.pdf`
- `paper/audit/publication-gate.md`
- `paper/package/publication-package.zip`
- `paper/package/publication-latex-editable.zip`

## Qué significa todo esto

La revisión no es solo un output textual. Es un conjunto de artefactos que
permiten comprobar:

- qué se buscó
- qué se excluyó
- qué se extrajo
- cómo se redactó
- por qué se cerró o por qué sigue bloqueada
