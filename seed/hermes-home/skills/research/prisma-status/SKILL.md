---
name: prisma-status
description: Detailed status reporting for PRISMA systematic reviews in the workspace. Use when the user asks how a PRISMA review is progressing, what phase it is in, what remains, or whether it is blocked.
version: 0.1.0
author: Hermes Local Setup
license: MIT
metadata:
  hermes:
    tags: [research, systematic-review, prisma, status, audit]
    category: research
    related_skills: [prisma-systematic-review]
    requires_toolsets: [terminal, file]
---

# PRISMA Status

Use this skill when the user wants the current status of a PRISMA review.

## Default Behavior

If the user invokes `/prisma_status` with no extra text:

1. Inspect `/workspace` for review folders whose name starts with `systematic-review`.
2. Ignore `systematic-review-template`.
3. Prefer a review whose runtime state is `stalled`, `in_progress`, or `blocked`.
4. If several reviews match, prefer the most recently updated one.
5. Report a single active review by default. Only compare several reviews if the user explicitly asks for a comparison.

If the user names a review topic or path, use that review instead.

## Required Checks

Read these artifacts when they exist:

- `protocol/intake.md`
- `notes/runtime-state.md`
- `notes/runtime-state.json`
- `audit/phase-audit.md`
- `audit/final-audit.md`
- `searches/search-log.csv`
- `records/doi-index.csv`
- `records/duplicates.csv`
- `records/missing-doi.csv`
- `records/master-records.csv`
- `screening/title-abstract.csv`
- `screening/full-text.csv`
- `extraction/extraction-table.csv`
- `prisma/flow-counts.csv`
- `figures/manifest.csv`

Prefer using this deterministic helper:

```bash
python3 /opt/data/skills/research/prisma-status/scripts/review_status.py --workspace-root /workspace --format markdown
```

If the user points to a specific review path, pass it as the positional review directory:

```bash
python3 /opt/data/skills/research/prisma-status/scripts/review_status.py /workspace/<review-dir> --format markdown
```

## Output Shape

Answer in Spanish from Spain with a concise operational status that includes:

- review path
- topic
- years
- autonomous mode
- global status
- current phase
- next action
- blocker
- last update
- counts for search, DOI, screening, extraction, PRISMA, and figures
- phase audit summary

If the review is blocked or stalled, say so explicitly and explain the first missing artifact or the declared blocker.
