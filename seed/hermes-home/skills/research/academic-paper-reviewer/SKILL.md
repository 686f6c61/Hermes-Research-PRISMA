---
name: academic-paper-reviewer
description: Multi-perspective review of academic manuscripts, revised drafts, or publication bundles. Use when the user wants a publication-style assessment, a focused methods review, a re-review against prior comments, or an auditable decision letter with prioritized findings.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [research, peer-review, manuscript, revision, editorial, publication]
    category: research
    related_skills: [research-integrity-audit, revision-roadmap, prisma-systematic-review]
    requires_toolsets: [terminal, file]
---

# Academic Paper Reviewer

Use this skill when the user has a manuscript, draft, or review package and wants a structured academic assessment.

## Best Fits

- Pre-submission review of a paper or report
- Focused review of methods, evidence, or presentation
- Re-review after revisions
- Decision support: accept, minor, major, reject
- Building a reviewer packet before a model-based critique

## Modes

- `full`: editorial + methods + contribution + presentation + residual risks
- `quick`: fast quality screen when a full review is unnecessary
- `methodology-focus`: methods, sample, variables, inference, reproducibility
- `re-review`: compare prior comments, response letter, and revised draft

## Default Workflow

1. Identify the main manuscript path.
2. If a review workspace exists, also inspect:
   - `paper/manuscript/publication-ready.md`
   - `paper/audit/*.md`
   - `paper/review/`
   - `paper/package/`
3. Build a deterministic review packet first:

```bash
python3 SKILL_DIR/scripts/build_review_packet.py /abs/path/to/manuscript.md --review-dir /abs/path/to/review-dir
```

4. Use the packet to ground the review before drafting findings.
5. Deliver findings first, ordered by severity, with file references when possible.

## Output Shape

Default to this structure:

1. `Decision`
2. `Major Findings`
3. `Minor Findings`
4. `Strengths`
5. `Revision Priorities`
6. `Residual Risks`

For `re-review`, add:

1. `Addressed`
2. `Partially Addressed`
3. `Unresolved`

## Review Rules

- Do not praise by default; lead with the most decision-relevant issues.
- Tie major claims to concrete evidence in the manuscript or bundle.
- Distinguish unsupported claims from merely under-explained ones.
- If the manuscript is a PRISMA-style review, check that synthesis claims are supported by extracted studies, figures, and appendices.
- If the packet shows missing artifacts, treat that as a review finding, not as a hidden assumption.

## References

- Rubric and verdict mapping: `references/review-rubric.md`
