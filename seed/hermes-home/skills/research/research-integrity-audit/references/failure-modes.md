# Failure Modes

Use these as the minimum failure taxonomy for Hermes integrity checks:

- `Citation support failure`: claims point to missing, weak, or absent references
- `Artifact traceability failure`: figures, tables, PDFs, or appendices are referenced but not actually present
- `Packaging failure`: expected bundle files are missing, stale, or obviously incomplete
- `Draft leakage`: TODOs, placeholders, pending notes, or reviewer scaffolding remain in the manuscript
- `Section completeness failure`: core sections are missing for the claimed article type

## Severity Guide

- `ERROR`: blocks trust or publication readiness
- `WARN`: should be fixed before claiming the document is polished
- `INFO`: useful editorial signal, not a blocker

