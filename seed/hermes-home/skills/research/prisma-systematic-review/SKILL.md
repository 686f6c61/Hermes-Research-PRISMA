---
name: prisma-systematic-review
description: DOI-first workflow for PRISMA-aligned systematic reviews. Use when the user needs protocol drafting, search logging, deduplication, title/abstract screening, full-text screening, exclusion reasons, extraction tables, or PRISMA counts with auditable traceability.
version: 0.1.0
author: Hermes Local Setup
license: MIT
metadata:
  hermes:
    tags: [research, systematic-review, prisma, doi, pico, screening, evidence-synthesis]
    category: research
    related_skills: [arxiv, ocr-and-documents, academic-paper-reviewer, research-integrity-audit, revision-roadmap]
    requires_toolsets: [terminal, file]
---

# PRISMA Systematic Review

Use this skill for **systematic reviews with PRISMA-style traceability**.
The workflow is **DOI-first**:

1. Build the protocol and search strategy.
2. Decompose the research question into auditable search stages before querying sources.
3. Import results from multiple sources: OpenAlex, Crossref, Semantic Scholar, arXiv, OpenAIRE, Lens when configured, and Europe PMC/PubMed when the topic is biomedical, health, psychology or explicitly enabled.
4. Normalize and deduplicate by DOI before screening.
5. Screen title/abstract with explicit inclusion and exclusion criteria.
6. Screen full text with auditable exclusion reasons.
7. Extract structured data.
8. Build an auditable structural atlas of authors, topics, references, evidence, and selection-stage drift.
9. Produce PRISMA counts, tables, and methods text.
10. Iterate on manuscript, figures, tables, and references until the publication gate passes or a real blocker is documented.

## Core Rules

- **DOI is the canonical record key** when present.
- Store the canonical DOI in a dedicated `assigned_doi` field.
- Never silently merge records on title similarity if DOI is missing.
- If DOI is absent, create a `needs_doi_resolution` state and try to resolve it via metadata search.
- Keep exclusion reasons explicit and one-per-record at the stage where exclusion happened.
- Every count shown in methods or PRISMA output must be reproducible from files in the workspace.
- Network position, author productivity, and citation counts must never influence eligibility, critical appraisal, or focal selection.
- After every material update, sync the review to Obsidian immediately. Do not wait until the end.
- In autonomous mode, continue phase by phase until every required artifact exists or a real blocker stops the workflow.
- Every review must declare or infer a methodological mode before search: `biomédico`, `técnico`, `ciencias sociales`, `educación`, `management` or `mixto`. Persist the decision in `protocol/review-mode.md`, `protocol/review-mode.json`, and `audit/mode-decision.md`.
- Title/abstract screening must be conservative: use `include` only for clearly relevant records, `maybe` for borderline ones, and do not over-include tangential domains.
- A study cannot enter the final included corpus unless a readable local PDF full-text artifact has been recovered.
- If an output is not semantically ready yet, sync a short pending note to Obsidian instead of exporting a misleading placeholder as if it were final.
- Before any source query, decompose the research question into search stages that cover population/context, exposure or construct, relation, outcome/decision, evidence method, and exclusion boundaries. Persist the result in `protocol/search-decomposition.md`, `protocol/search-decomposition.json`, and `searches/search-stage-map.csv`.
- Keep external-source credentials out of all review artefacts. Unpaywall uses an email contact, not a classic API key; configure it only as `HERMES_UNPAYWALL_EMAIL` or `UNPAYWALL_EMAIL`. Lens uses `HERMES_LENS_API_KEY` or `LENS_API_KEY`; if absent, Hermes must skip Lens cleanly.
- Freeze machine-readable intake, method, synthesis, journal and deliverable contracts before intensive screening.
- Treat a requested final N or N range as a planning target, never as an eligibility quota.
- Link every critical manuscript claim to DOI, evidence snippet and page or section before publication can pass.
- Public packages must use DOI identities, omit `record_id` fields and remove author-machine paths.

## Required Metadata Outputs

For every included candidate record, preserve or derive these fields:

- `assigned_doi`
- `authors`
- `title_original`
- `title_en`
- `title_es`
- `abstract_original`
- `abstract_en`
- `abstract_es`
- `keywords_author`
- `keywords_indexed`
- `keywords_normalized`

If the source only provides one language:

- keep that text in `*_original`
- copy it into the matching language field when obvious
- generate the missing Spanish or English version as a translation
- note in `notes` when a translation is machine-generated rather than source-provided

If no abstract is available, leave the abstract fields blank and record that absence explicitly.

## Writing and Citation Standards

- All prose written in Spanish must follow Spanish from Spain and align with RAE norms.
- Every synthesis statement, interpretation, or comparative claim must point to one or more source papers in APA style.
- Use APA-style in-text citations in narrative outputs and keep references consistent across Markdown notes, protocol text, and final synthesis documents.
- If a field is raw source metadata rather than Hermes-authored prose, preserve the source text faithfully and do not rewrite it just for style.

## Exclusion Scoring

Every exclusion decision must include:

- `reason`
- `reason_detail`
- `exclusion_score`

Use `exclusion_score` as a reviewer confidence score from `0` to `100`:

- `0-24`: weak signal, likely needs another look
- `25-49`: leaning exclusion but uncertain
- `50-74`: solid exclusion signal
- `75-100`: strong exclusion confidence

The score is not a PRISMA field. It is an internal audit aid to help revisit borderline records.

## Topic Switching

The slash command is **generic**. The topic must come from the user's message,
not from a hardcoded review theme.

If the user gives a topic different from the current review:

1. Create a **new review workspace** instead of overwriting the old one.
2. Use a clear slug, for example:
   - `systematic-review-autonomous-agents-2026/`
   - `systematic-review-rag-security-2026/`
3. Copy the review skeleton from `workspace/systematic-review-template/` into the new folder.
4. Replace protocol, criteria, and search strategy with the new topic.
5. Preserve prior reviews as separate, auditable projects.

Only reuse an existing review folder when the user is clearly continuing the
same review topic.

## Intake Rules

Before starting a new review, collect these inputs:

1. `topic`
2. `research_question` (optional but strongly recommended)
3. `year_or_years`
4. `inclusion_criteria`
5. `exclusion_criteria`
6. `author_filters` (optional but important when the user wants to include or exclude named authors, labs, or teams)
7. `autonomous_mode` (optional; default to `yes` unless the user explicitly asks for a manual or pause-and-review mode)
8. `final_inclusion_limit_n` (optional; maximum number of studies to carry into the final ultraquality synthesis subset; accepts a range such as `11-75`)
9. `ultraquality_representativeness_criteria` (optional; how the top `N` should remain representative, e.g. methods, countries, sectors, architectures, years)
10. `review_mode` (optional but recommended: `biomédico`, `técnico`, `ciencias sociales`, `educación`, `management` or `mixto`; if omitted, Hermes infers it)
11. `target_outlet` (optional: revista o medio específico; si falta o solo se declara una banda temática amplia, usar `generic-common-core`)
12. `target_manuscript_length` (optional; default to a substantive journal manuscript, not a short summary)

If one or more are missing, ask only for the missing research inputs before doing
the search and screening work.

If the user invokes `/prisma_systematic_review` with no extra text, treat that as
an explicit request to start the full workflow.
In that case:

- do not ask what command to run
- do not ask for permission to continue between phases
- ask only for the missing research inputs in one Spanish message
- default `autonomous_mode=yes`
- begin execution as soon as the minimum intake is available

Use this exact intake shape:

```text
Tema:
Pregunta de investigación:
Año o años:
Criterios de inclusión:
Criterios de exclusión:
Autores:
Modo autónomo:
Límite final N ultraquality:
Criterio de representatividad ultraquality:
Modo metodológico:
Revista o medio objetivo:
Longitud objetivo del manuscrito:
```

Store the parsed intake in `protocol/intake.md`.

Interpretation rules:

- `year_or_years` may be a single year (`2026`) or a range/list (`2024-2026`, `2025,2026`)
- If the user gives a domain filter such as `solo arquitectura A2A`, convert it into a formal inclusion criterion
- If the user says `excluye todo lo que no use A2A`, keep that as an explicit exclusion rule
- If the user names authors, preserve them as explicit search and screening constraints
- If the user provides a research question, use it as the main analytic axis of the full review and the paper
- If the user does not provide a research question, infer one from the topic and record it explicitly
- If the user does not mention `modo autónomo`, treat it as `sí`
- If the user says `modo autónomo`, treat it as permission to continue across phases until the workflow is complete or blocked
- If the user explicitly asks for a manual mode, pause-and-review mode, or phased approval mode, disable autonomous mode
- If the user sets a final `N` range, treat the lower bound as the desired minimum for a publishable focal synthesis and the upper bound as the cap; do not inflate the corpus if the evidence does not reach the lower bound.
- If the user sets a final `N`, do not discard valid studies silently. Keep the full valid set, then create a documented ultraquality subset of at most `N` studies for the final synthesis.
- If the user sets a final `N`, also preserve the representativeness rule they want, for example methods, countries, sectors, architectures, study types, or a balanced mix.
- If the user declares a methodological mode, preserve it. If not, infer it from topic, question, inclusion, exclusion and target outlet. If several logics are active, use `mixto` with a primary and secondary mode.
- If mode confidence is low and the interface is interactive, ask exactly one field question before searching: `¿En qué campo quieres ubicar la revisión?` Offer `biomédico`, `técnico`, `ciencias sociales`, `educación`, `management` or `mixto`.
- If the run is autonomous, never stop only because the mode was not supplied. Infer the best mode or use common-core, persist the rationale, and continue.
- The review mode changes the question framework, source strategy, screening axes, critical appraisal, score weighting, synthesis mode, figures/tables and writing rules. It is not a cosmetic label.
- If the user gives both broad and narrow criteria, preserve them verbatim in the protocol and normalize later only if needed
- If the user gives a target journal, adapt structure, depth, and final gate to that venue
- If the user gives no target manuscript length, assume a journal-length manuscript with substantive method, results, discussion, figures, and tables

Before execution, restate the intake in a compact summary so the user can spot
errors early.

## Methodological Review Modes

Hermes must not force every systematic review through the same epistemic mold.
Before the first source query, run the discipline router and persist:

```text
protocol/review-mode.md
protocol/review-mode.json
audit/mode-decision.md
```

Modes and expected logic:

- `biomédico`: use PICO/PICOS logic, specialist health sources, intervention/exposure/outcome thinking, and named risk-of-bias families such as RoB 2, ROBINS-I, ROBIS, AMSTAR 2, JBI or GRADE when applicable.
- `técnico`: compare systems, architectures, datasets, benchmarks, metrics, robustness, cost, latency and reproducibility. Do not reduce the review to model names.
- `ciencias sociales`: use construct-context-method-evidence logic. Evaluate theory, construct clarity, context, sample/case, reflexivity, coherence and transferability. Do not penalize qualitative work for not being experimental.
- `educación`: treat educational level, actor, pedagogical activity, tool/practice, outcome, institutional context, ethics and equity as core extraction axes.
- `management`: use CIMO/TCCM logic. Extract theory, unit of analysis, variables, mechanisms, moderators, mediators, sample, sector, country, endogeneity controls, robustness and limits of causal inference.
- `mixto`: declare a primary mode and one or more secondary modes. The primary mode owns the unit of analysis; secondary modes add appraisal and synthesis safeguards.

The mode must affect:

- search decomposition
- source activation
- title/abstract and full-text rules
- extraction fields and prompts
- focal-score weighting
- critical-appraisal matrix
- synthesis strategy
- theoretical implications, practical implications, conclusions and future lines

Every mode must also define a publication playbook:

- when to ask the user for the field and when to infer it
- minimum tables for a publishable paper
- recommended analytical figures
- mode-specific outputs and annexes
- section-level writing requirements
- red flags that should block or warn before publication
- an excellence checklist for a 10/10 review

Current per-field minimum visual/table contract:

- `biomédico`: PICO/PICOS table, characteristics table, risk-of-bias matrix, evidence profile, and outcome-oriented figures only when they clarify certainty or effect.
- `técnico`: system-architecture matrix, dataset/benchmark/metric table, reproducibility table, results-comparability table, and figures that explain architecture, coverage or task-component-result relationships.
- `ciencias sociales`: construct-theory-context-method table, sample/context table, design table, mechanism/transferability matrix, and figures that map constructs, mechanisms, contexts or gaps.
- `educación`: level-actor-activity table, tool/practice-outcome table, context/duration table, ethics/equity/governance matrix, and figures that explain pedagogical activity, actor flow or adoption.
- `management`: TCCM/CIMO table, variable-role matrix, sector/country/unit table, endogeneity/robustness table, and figures that explain mechanisms, causal caution or strategic decision patterns.
- `mixto`: primary/secondary mode table, evidence-type matrix, cross-mode appraisal table, integration matrix, and figures that show synthesis layers and comparability boundaries.

To audit this layer after changes, run:

```bash
python3 hermes-home/skills/research/prisma-systematic-review/scripts/audit_review_modes.py
```

## Publication Quality Gate

Treat publication readiness as a hard gate, not as a cosmetic preference.

A manuscript is not publishable unless all these conditions hold:

- `paper/audit/publication-audit.md` is `PASS`
- `paper/audit/publication-gate.md` is `PASS`
- no reviewer returns `reject` or `major revision`
- APA issues are zero
- the manuscript is journal-length and scientifically substantive, not a short digest

The publication gate should also check support objects:

- at least one PRISMA flow diagram
- at least one architecture or workflow diagram for the method
- at least one results-side visual evidence object
- at least one paper-ready table
- a complete structural-analysis manifest, coverage audit, and offline atlas; network figures enter the manuscript only when they add a defensible analytical finding
- `protocol/contracts-manifest.json` and a passing artifact-schema validation
- `paper/audit/model-capabilities.json` and credential-free model provenance
- `paper/audit/claim-evidence-ledger.csv` with no unsupported critical claims
- `paper/package/index.html` plus a twelve-category deliverables manifest
- a valid human adjudication record when `validation_mode=adjudicated`

If the user asks for a standalone manuscript critique outside the built-in PRISMA review loop, use `academic-paper-reviewer`.
If the user asks for a static preflight before sending the paper, use `research-integrity-audit`.
If the user wants reviewer comments converted into an action matrix, use `revision-roadmap`.

If the gate fails:

- keep rewriting the manuscript
- enrich figures and tables
- resolve reviewer objections
- improve bibliographic completeness
- repeat until the gate passes or a real blocker is documented

## Recommended Workspace Layout

Create or reuse a review folder inside the active workspace:

```text
systematic-review/
  protocol/
    intake.md
    research-question.md
    eligibility-criteria.md
    search-decomposition.md
    search-decomposition.json
    search-strategy.md
  searches/
    search-stage-map.csv
    search-log.csv
    raw/
  records/
    doi-index.csv
    duplicates.csv
    missing-doi.csv
    master-records.csv
  screening/
    title-abstract.csv
    full-text.csv
  selection/
    ultraquality-shortlist.csv
  extraction/
    extraction-table.csv
  analysis/
    manifest.json
    methodology.md
    summary.md
    atlas/
      network-atlas.html
    data/
      nodes.csv
      edges.csv
      graph.graphml
    metrics/
      network-summary.json
      centrality.csv
      communities.csv
      author-production.csv
      selection-drift.csv
    audit/
      coverage.json
      parameters.json
      provenance.csv
  prisma/
    flow-counts.csv
    checklist-notes.md
  notes/
    decisions.md
```

## Structural Analysis Contract

Run structural analysis after extraction and before manuscript generation. It
is automatic in the end-to-end cycle; the standalone maintainer command is:

```bash
python3 HERMES_HOME/skills/research/research-network-analysis/scripts/build_network_analysis.py /workspace/<review-dir>
```

The analysis must:

- identify studies only by normalized DOI;
- distinguish corpus publication counts from external OpenAlex productivity;
- keep authorship, citation, bibliographic coupling, co-citation, keyword, and
  evidence networks as separate layers;
- report coverage, denominator, parameters, and claim status for every layer;
- run community detection across multiple seeds and resolutions and report
  stability;
- label communities exploratory below the size, coverage, or stability
  threshold;
- export a self-contained HTML atlas with no CDN or runtime upload;
- preserve CSV, JSON, GraphML, SVG, provenance, and methodology outputs;
- avoid a composite authority score or causal language based only on topology.

Read `research-network-analysis/references/methodology.md` for the exact
thresholds and graph semantics.

## Obsidian Sync

Sync to Obsidian after every material update to:

- `protocol/intake.md`
- `protocol/research-question.md`
- `protocol/eligibility-criteria.md`
- `protocol/search-decomposition.md`
- `protocol/search-decomposition.json`
- `protocol/search-strategy.md`
- `searches/search-stage-map.csv`
- `searches/search-log.csv`
- `records/master-records.csv`
- `screening/title-abstract.csv`
- `screening/full-text.csv`
- `selection/ultraquality-shortlist.csv`
- `extraction/extraction-table.csv`
- `prisma/flow-counts.csv`
- `notes/decisions.md`
- `notes/runtime-state.md`
- `notes/runtime-state.json`
- `audit/checklist.md`
- `audit/phase-audit.md`
- `audit/final-audit.md`
- `figures/manifest.csv`

Run:

```bash
python3 SKILL_DIR/scripts/sync_review_to_obsidian.py /workspace/<review-dir>
```

This creates or refreshes Markdown notes inside:

```text
$OBSIDIAN_VAULT_PATH/Hermes/Systematic Reviews/<topic-slug>/
```

Also mirror the raw source files into `_artifacts/` so the vault contains both:

- readable notes
- exact CSV/Markdown source artifacts

## Ultraquality Cap

When the user defines a maximum final `N`, treat it as a **cap on the final synthesis subset**, not as a replacement for normal screening.

Workflow rules:

1. Complete the normal review flow first: search, DOI, deduplication, screening, and extraction.
2. Preserve the full valid included set in the review artifacts.
3. If the valid included set is larger than the configured `N`, create:
   - `selection/ultraquality-shortlist.csv`
   - `selection/n-range-audit.md`
4. Rank the valid included studies using documented dimensions such as:
   - direct topical relevance
   - methodological strength
   - richness of evidence and extractability
   - representativeness of the configured mix
5. Keep the selection auditable:
   - every candidate should have a score and rank
   - every selected record should have `selection_reason`
   - every non-selected valid record should have `cap_exclusion_reason`
6. Never claim that non-selected valid studies were excluded from the review itself; they were excluded only from the final ultraquality synthesis subset because of the user-defined cap.
7. In narrative outputs, state the difference clearly:
   - full valid included set
   - final ultraquality synthesis subset of size `N`
8. If a range was configured, report whether the final focal subset satisfies the minimum and maximum bounds.

## Figure Workflow

Create paper figures as editable SVG first and then render them to PNG.

Recommended figure folders:

```text
figures/
  manifest.csv
  README.md
  svg/
  png/
```

Use the figure pipeline for assets such as:

- PRISMA flow diagram
- taxonomy of study types or agent types
- evidence map by year, method, or geography
- methodological distribution charts
- concept or architecture diagrams derived from the reviewed literature

Render SVG to PNG with:

```bash
python3 SKILL_DIR/scripts/render_review_figures.py /workspace/<review-dir>
```

Figure rules:

- Keep SVG as the editable source of truth.
- Store each figure in `figures/svg/` and the rendered PNG in `figures/png/`.
- Register each figure in `figures/manifest.csv`.
- When a figure changes, sync the updated assets to Obsidian immediately.
- Mention newly created or updated figures in the next Telegram progress message.

## Audit Workflow

Audit the review after every phase and once again at the end.

Run:

```bash
python3 SKILL_DIR/scripts/review_audit.py /workspace/<review-dir>
```

The audit must produce:

- `audit/checklist.md`
- `audit/phase-audit.md`
- `audit/final-audit.md`

The checklist should cover at least:

- intake completeness
- protocol completeness
- search log traceability
- DOI audit and deduplication status
- screening completeness and exclusion rationale quality
- extraction completeness
- PRISMA counts consistency
- figure inventory and render status
- RAE compliance review pending/done
- APA citation coverage pending/done

Include audit results in the Telegram phase updates so the user does not have to wait until the end to spot problems.

## Runtime State and Resume

Track execution state explicitly so the review can resume after interruptions.

Run:

```bash
python3 SKILL_DIR/scripts/review_runtime_state.py /workspace/<review-dir>
```

This must maintain:

- `notes/runtime-state.md`
- `notes/runtime-state.json`
- `notes/pipeline-state.json`
- `notes/job-ledger.json` for background executions

The runtime state should record at least:

- current status: `in_progress`, `stalled`, `blocked`, `completed`
- current phase
- next phase
- next action
- last update timestamp
- known blocker, if any

Resume rules:

- If an existing review is incomplete, inspect `notes/runtime-state.*` and `audit/phase-audit.md` before asking anything.
- If the user says `continúa`, `retoma`, or `reanuda la revisión`, resume from the first incomplete phase automatically.
- If runtime state says `stalled` and there is no blocker, resume from the pending phase automatically.
- If runtime state says `blocked`, ask only for the missing research input or inaccessible source needed to continue.
- Skip a completed phase only when both its input content hash and required
  outputs still match. A stale success marker is not enough.
- Write running, completed, skipped and failed transitions atomically so a host
  restart cannot leave a false completed phase.

## Telegram Progress Reporting

Do not stay silent until the whole review is finished.

Send a Telegram progress message in Spanish after:

- intake confirmation
- protocol draft completion
- DOI audit and deduplication completion
- title/abstract screening completion
- full-text retrieval completion
- full-text screening completion
- extraction completion
- PRISMA counts or synthesis completion
- any hard blocker that prevents continuation
- any automatic resume after a stall or interruption

Each update should be short but explicit and use this shape:

```text
Fase: <nombre>
Hecho: <qué se ha completado>
Hallazgos: <conteos, fuentes o cambios más importantes>
Siguiente paso: <qué hará Hermes ahora>
Bloqueos: <solo si existen; si no, indicar "ninguno">
```

If the review is running in autonomous mode:

- keep going after sending the update
- only stop when a mandatory input is missing, a source is inaccessible, or the requested workflow is complete
- when blocked, explain exactly what is missing and what the user needs to provide
- never ask operational confirmation questions such as whether to execute the next phase, run the audit, sync Obsidian, or render figures

## Start Every Review This Way

1. Collect the intake:
   - topic
   - year or years
   - inclusion criteria
   - exclusion criteria
2. Write the review question and framework:
   - biomedical: `PICO`, `PICOS`, `PECO` or `PIRD`
   - technical: `system-task-benchmark-metric` or architecture-capability-evaluation
   - social sciences: `SPIDER`, `PEO`, `PICo`, or theory-context-method-evidence
   - education: `SPIDER`, `PEO`, `PICo`, or educational `CIMO`
   - management: `CIMO`, `TCCM`, theory-context-characteristics-method, or variables-mechanisms-results
   - mixed: explicit combination of primary and secondary mode rules
3. Write explicit inclusion and exclusion criteria.
4. Write the search log before running searches.
5. Export all database results without deleting anything manually first.
6. Run DOI audit and deduplication before screening.

## Search Log Minimum Fields

Use `searches/search-log.csv` with at least these columns:

```csv
source,platform,query_string,author_filter,run_date,from_date,to_date,notes,export_file
```

Good sources depend on domain, but commonly include:
- `OpenAlex`
- `Crossref`
- `Semantic Scholar`
- `OpenAIRE`
- `arXiv`
- `Lens` when `HERMES_LENS_API_KEY` or `LENS_API_KEY` is configured
- `Europe PMC` and `PubMed` for biomedical, health, psychology, neuroscience or explicitly enabled searches
- domain-specific databases such as `Scopus`, `Web of Science`, `Embase`, `PsycINFO`, `ERIC`, `CINAHL`

## Optional Search and Full-Text Environment Variables

- `HERMES_UNPAYWALL_EMAIL` or `UNPAYWALL_EMAIL`: contact email required by Unpaywall for DOI-to-OA/full-text resolution. Never write this value into repository files, logs, CSV outputs, screenshots or public packages.
- `HERMES_LENS_API_KEY` or `LENS_API_KEY`: enables Lens Scholarly API. If missing, Hermes records Lens as skipped and continues.
- `HERMES_ENABLE_EUROPEPMC=1`: forces Europe PMC even when the topic is not auto-detected as biomedical/health/psychology.
- `HERMES_ENABLE_PUBMED=1`: forces PubMed even when the topic is not auto-detected as biomedical/health/psychology.
- `HERMES_DISABLE_OPENAIRE=1`, `HERMES_DISABLE_LENS=1`, `HERMES_DISABLE_EUROPEPMC=1`, `HERMES_DISABLE_PUBMED=1`: disables individual sources for debugging or journal-specific replication.
- `HERMES_ENABLE_ARXIV=1`: forces arXiv for non-technical topics; otherwise Hermes uses arXiv only when the topic is technical/preprint-heavy.
- `HERMES_ENABLE_SEMANTIC_SCHOLAR=1`: uses Semantic Scholar without an API key; otherwise Hermes skips it unless `SEMANTIC_SCHOLAR_API_KEY` or `HERMES_SEMANTIC_SCHOLAR_API_KEY` is configured.
- `HERMES_DISABLE_ARXIV=1` and `HERMES_DISABLE_SEMANTIC_SCHOLAR=1`: disables rate-limited sources during public clean-room runs.
- `HERMES_NCBI_EMAIL` and `HERMES_NCBI_API_KEY`: optional PubMed/NCBI contact and rate-limit configuration.
- `SEMANTIC_SCHOLAR_API_KEY` or `HERMES_SEMANTIC_SCHOLAR_API_KEY`: optional Semantic Scholar API key.

## DOI Workflow

### 1. Audit exports

Run the helper script on all exports:

```bash
python3 SKILL_DIR/scripts/doi_audit.py searches/raw/*.csv \
  --index records/doi-index.csv \
  --duplicates records/duplicates.csv \
  --missing records/missing-doi.csv
```

What the outputs mean:
- `doi-index.csv`: every parsed record with raw DOI, normalized DOI, assigned DOI, title, year, source
- `duplicates.csv`: duplicate DOI clusters to merge before screening
- `missing-doi.csv`: records with no DOI resolved yet

### 2. Normalize

The helper script normalizes:
- `doi:10.xxxx/...`
- `https://doi.org/10.xxxx/...`
- `http://dx.doi.org/10.xxxx/...`
- uppercase DOI strings

All are reduced to canonical lowercase DOI form.

### 3. Missing DOI resolution

For records without DOI:
- search by title + year using OpenAlex, Crossref, or PubMed
- only fill DOI when metadata match is strong
- otherwise leave DOI blank and mark `needs_doi_resolution=yes`

Do not invent a DOI from fuzzy matches.

## Screening Data Model

### Title/abstract screening

Use `screening/title-abstract.csv` with these minimum columns:

```csv
record_id,assigned_doi,authors,title_original,title_en,title_es,abstract_original,abstract_en,abstract_es,keywords_author,keywords_indexed,keywords_normalized,year,source,decision,exclusion_score,reason,reason_detail,reviewer,reviewed_at,notes
```

Where:
- `decision`: `include`, `exclude`, `maybe`
- `reason`: only for `exclude`

### Full-text screening

Use `screening/full-text.csv` with:

```csv
record_id,assigned_doi,authors,title_original,title_en,title_es,abstract_original,abstract_en,abstract_es,keywords_author,keywords_indexed,keywords_normalized,decision,exclusion_score,reason,reason_detail,reviewer,reviewed_at,full_text_path,notes
```

Typical full-text exclusion reasons:
- wrong population
- wrong intervention/exposure
- wrong outcome
- wrong study design
- wrong publication type
- no full text
- duplicate publication
- outside date range
- wrong language

Keep reasons stable and reusable so PRISMA reporting stays clean.

## PRISMA Counts

At minimum, track:
- records identified
- duplicates removed
- records screened
- records excluded at title/abstract
- reports sought for retrieval
- reports not retrieved
- full-text reports assessed
- full-text reports excluded, with reasons
- studies included in synthesis

Store the counts in `prisma/flow-counts.csv`:

```csv
stage,count,notes
identified,0,
duplicates_removed,0,
screened_title_abstract,0,
excluded_title_abstract,0,
full_text_sought,0,
full_text_not_retrieved,0,
full_text_assessed,0,
full_text_excluded,0,
included_in_review,0,
```

## Extraction Data Model

Use `extraction/extraction-table.csv` with at least:

```csv
record_id,assigned_doi,authors,title_original,title_en,title_es,abstract_original,abstract_en,abstract_es,keywords_author,keywords_indexed,keywords_normalized,year,work_type,empirical_type,countries,sample_description,sample_size,method_used,variables_dependent,variables_independent,variables_moderating,variables_mediating,variables_control,theory_framework,evidence_snippet,evidence_location,extraction_confidence,key_findings,notes
```

Where:

- `work_type`: `theoretical`, `empirical`, `review`, `other`
- `empirical_type`: `quantitative`, `qualitative`, `experimental`, `mixed`, `other`
- `countries`: country or countries where the empirical work is carried out
- `sample_description`: firms, individuals, SMEs, listed firms, automotive sector, cases, repositories, etc.
- `sample_size`: numeric or narrative sample size as reported
- `method_used`: regression, panel data, OLS, logistic, machine learning, fsQCA, interviews, case study, etc.
- `variables_*`: keep blank when the paper does not report them
- `theory_framework`: explicit or inferred theoretical framing
- `evidence_snippet`: short supporting quote or extracted evidence for the row
- `evidence_location`: page, section, table, or figure reference
- `extraction_confidence`: reviewer confidence from `0` to `100`

## How to Use the Existing Hermes Skills

- `arxiv`: useful for discovery, not enough as the sole review source
- `ocr-and-documents`: for full-text extraction from PDFs
- `llm-wiki`: maintain notes, rationale, and synthesis pages over long reviews

## Recommended External Layers

Use these as companions, not replacements for traceability:

- `ASReview`: screening prioritization and active learning
- `Rayyan` or `Covidence`: collaborative screening workflows
- `OpenAlex`, `Crossref`, `Semantic Scholar`, `OpenAIRE`, `Europe PMC`, `PubMed`, `Lens` and `Unpaywall`: DOI resolution, metadata cross-checking and OA/full-text recovery where allowed

## Model Policy

- This Hermes deployment is cloud-only: do not route research calls to `localhost`, `127.0.0.1`, or `host.docker.internal`.
- Public provider contract: an OpenAI-compatible `/v1` endpoint configured with
  `HERMES_INFERENCE_BASE_URL` and `HERMES_INFERENCE_API_KEY`.
- Primary model: read from `HERMES_MODEL_PRIMARY` for search planning,
  extraction, synthesis and manuscript assembly.
- Vision specialist: read from `HERMES_MODEL_VISION` for rendered PDF pages,
  dense tables and figure interpretation.
- Independent review model: read from `HERMES_MODEL_REVIEW` for methodological
  contrast, visual checks, clarity and interpretation risks.
- The configured catalog must pass `doctor`, and the vision model must also
  pass the bundle's image-input probe before a real review is launched.
- The primary and review roles must pass the live text/JSON capability probe.
- Reject provider-side model substitution unless an explicit, audited fallback
  policy allows it.
- Record requested model, effective model, role, capability, finish status and
  token usage in `paper/audit/model-provenance.csv`; never record secrets.
- When a fallback is used:
  - retry from the last stable state
  - record the switch in `notes/decisions.md`
  - mention it in the next Telegram progress update

## Default Operating Pattern

When this skill is active:

1. Inspect the review folder and orient on existing logs and tables.
2. If the user topic does not match the current folder, create a new review folder first.
3. If the intake is incomplete, ask only for the missing intake fields.
4. If raw exports exist, run DOI audit first.
5. If no protocol exists, draft the question, criteria, and search log structure from the intake.
6. If screening has started, preserve prior decisions and append only auditable updates.
7. After each material update, run the Obsidian sync script immediately.
8. After each completed phase, run the audit script and update the audit files.
9. After each completed phase or interruption check, run the runtime-state script and update the runtime-state files.
10. After each completed phase or hard blocker, send a Telegram progress update with what changed, key counts, next action, blockers, audit status, and whether execution resumed automatically.
11. If the user asked for autonomous mode, continue into the next phase automatically unless a real blocker appears.
12. If an incomplete review is reopened later, resume from the first incomplete phase instead of restarting from scratch.
13. Before producing PRISMA text or counts, reconcile them against the CSV files.
14. Before delivering synthesis text, verify RAE-style Spanish and APA references.
15. Before final packaging, run `journal_readiness_gate.py` so the ZIP includes protocol-ready files, PRISMA 2020 and PRISMA-S checklists, full-text exclusions, risk/reporting appraisal, AI disclosure, data/code availability statements, cover-letter draft, and journal-fit report.
16. Build the claim-evidence ledger and fail unsupported critical claims.
17. Validate artifact schemas instead of inferring malformed CSV or JSON.
18. Package an offline `index.html` that explains all twelve deliverable
    families and links to their useful entry points.

## What Not To Do

- Do not call a review “systematic” if the search log and exclusion reasons are missing.
- Do not deduplicate only by title when DOI exists in any source.
- Do not overwrite reviewer judgments without leaving a trace.
- Do not output PRISMA counts that cannot be recomputed from files.
