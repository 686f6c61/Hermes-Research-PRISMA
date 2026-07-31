# Quality Gate

This document is the public release rulebook for Hermes Research Mode. It is
written as an operational checklist so a maintainer can decide whether a review
or a release bundle is ready without relying on private context.

## Publication gate for a review

A review can be called publication-ready only when all of these artifacts exist:

- `paper/manuscript/publication-ready.md`
- `paper/manuscript/publication-ready.tex`
- `paper/manuscript/publication-ready.pdf`
- `paper/package/publication-package.zip`
- `paper/package/publication-latex-editable.zip`
- `paper/audit/publication-audit.md`
- `paper/audit/integrity-audit/`
- `paper/audit/publication-gate.md`
- `paper/review/peer-review-overview.md`
- `prisma/flow-counts.csv`
- `selection/ultraquality-shortlist.csv`
- `extraction/extraction-table.csv`

The final `publication-gate.md` must report `Estado global: **PASS**`. A
deterministic audit pass is not enough if peer review blocks publication.

## Scientific rules

- The manuscript must distinguish the full PRISMA corpus from any focal
  synthesis subset.
- If a focal subset is used, the method must report the formula, hard gates,
  target N, ranking rule, and the included-but-not-focal studies.
- No study enters the final scientific corpus without locally readable full
  text.
- Tables and figures must be generated as real artifacts, not placeholders.
- The manuscript must cite PRISMA 2020 and keep the full reference in the final
  bibliography.
- Citations in text and bibliography must be internally consistent before a
  package is declared ready.

## Release hygiene

Public bundles must not include:

- real API keys or bearer tokens
- `.env` files with secrets
- personal local paths or host-specific home directories
- private provider names unless intentionally documented for public use
- author email addresses embedded in code
- bytecode caches, local runtime state, or generated review workspaces

Public examples should use the portable secret name
`HERMES_INFERENCE_API_KEY`. Provider-specific aliases are not part of the
public configuration contract.

## Required validation

Before publishing a ZIP, run:

```bash
bash scripts/sync-bundle-assets.sh
bash scripts/security-audit.sh
./hermes-research ship-release
```

Then scan the staged or extracted bundle for obvious leaks: personal filesystem
paths, bearer headers, private provider URLs, author email addresses, and
environment variables populated with real-looking values.

The scan should return no public-release blockers. If it does, fix the source,
sync again, rebuild the ZIP, and re-run validation.
