---
name: revision-roadmap
description: Turn reviewer comments, audit findings, or editorial notes into an actionable revision matrix with priorities, categories, response placeholders, and manuscript targets. Use for revise-and-resubmit work or final polishing passes.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [research, revision, roadmap, peer-review, manuscript, editorial]
    category: research
    related_skills: [academic-paper-reviewer, research-integrity-audit, prisma-systematic-review]
    requires_toolsets: [terminal, file]
---

# Revision Roadmap

Use this skill when the user has reviewer comments, audit findings, or a mixed bag of revision notes and needs them turned into a trackable plan.

## Best Fits

- Reviewer reports -> change plan
- Integrity audit -> action matrix
- Response-to-reviewers preparation
- Final polish queue before packaging

## Default Workflow

1. Gather one or more source files with comments or findings.
2. Build the roadmap first:

```bash
python3 SKILL_DIR/scripts/build_revision_roadmap.py /abs/path/to/comments.md /abs/path/to/audit.md
```

3. Review the generated CSV and Markdown matrix.
4. Merge or rewrite duplicated issues if several reviewers say the same thing.
5. Use the roadmap as the source of truth for implementation and response letters.

## Output Columns

- `item_id`
- `source_file`
- `reviewer`
- `category`
- `priority`
- `section_hint`
- `comment`
- `action_needed`
- `evidence_needed`
- `response_placeholder`
- `status`

## References

- Schema and status lifecycle: `references/roadmap-schema.md`
