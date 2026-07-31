---
name: research-integrity-audit
description: Audit academic manuscripts and review bundles for citation, evidence, packaging, and consistency issues before declaring them publication-ready. Use for pre-submission checks, publication gates, or claim-support audits.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [research, integrity, audit, citations, evidence, publication]
    category: research
    related_skills: [academic-paper-reviewer, revision-roadmap, prisma-systematic-review]
    requires_toolsets: [terminal, file]
---

# Research Integrity Audit

Use this skill when the user needs a hard-nosed audit of a manuscript, review package, or publication bundle.

## Best Fits

- Pre-submission integrity checks
- Claim-support and citation-support audits
- Packaging checks for figures, appendices, PDFs, and ZIP bundles
- Fast quality gates before a peer-review round

## Default Workflow

1. Locate the principal manuscript.
2. If a review workspace exists, also inspect the adjacent `paper/`, `figures/`, `tables/`, `fulltext/`, and `package/` artifacts.
3. Run the deterministic checker first:

```bash
python3 SKILL_DIR/scripts/check_manuscript_integrity.py /abs/path/to/manuscript.md --review-dir /abs/path/to/review-dir
```

4. Treat `ERROR` items as blockers until resolved or explicitly documented.
5. Convert surviving `WARN` items into revision tasks if they threaten clarity, traceability, or editorial fit.

## What This Audit Checks

- placeholder tokens and unfinished text
- missing core sections
- missing references despite in-text citations
- figure/table mentions without visible assets
- broken local links
- missing appendices, PDFs, or package files in review workspaces

## References

- Failure taxonomy: `references/failure-modes.md`
