# Expected Artifacts

Después de una creación mínima y un primer arranque autónomo, el paquete debería
dejar al menos estos rastros materiales:

- `protocol/intake.md`
- `protocol/research-question.md`
- `protocol/eligibility-criteria.md`
- `protocol/search-strategy.md`
- `notes/runtime-state.json`
- `searches/search-log.csv`
- `records/master-records.csv`

Más adelante, cuando la revisión avanza, deberían aparecer también:

- `screening/title-abstract.csv`
- `screening/full-text.csv`
- `extraction/extraction-table.csv`
- `fulltext/docling/manifest.csv`
- `fulltext/docling/status.json`
- `fulltext/docling/<doi>.md`
- `fulltext/docling/<doi>.json`
- `tables/source/<doi>-table-XX.csv`
- `figures/source/<doi>-figure-XX.<ext>`
- `paper/manuscript/publication-ready.md`
- `paper/manuscript/publication-ready.tex`
- `paper/manuscript/publication-ready.pdf`
- `paper/package/publication-package.zip`
- `paper/package/publication-latex-editable.zip`
- `paper/review/peer-review-overview.md`
- `paper/audit/publication-gate.md`

El cierre solo se considera completo cuando `paper/audit/publication-gate.md`
marca `Estado global: **PASS**`.

Los artefactos de Docling solo aparecen para documentos con DOI válido y PDF
recuperado. Sus nombres deben derivarse del DOI, nunca de identificadores
internos. Si el worker no está disponible, `fulltext/docling/status.json` debe
registrar `unavailable_fallback_poppler` y el ciclo debe continuar por la ruta
Poppler sin presentar esa extracción como estructurada.
