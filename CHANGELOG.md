# Changelog

All notable changes to Hermes Research Pack are documented here. The project
uses semantic versioning for its public wrapper, plugin contract and release
bundle.

## Unreleased

No changes yet.

## 0.6.0 - 2026-08-02

### Added

- Evidence-position matrices that distinguish convergence, directional
  disagreement, null findings, qualified patterns and open questions.
- A reading-priority queue based on relevance, method transparency, evidence
  readiness, reproducibility and contrast, with zero bibliometric weight and
  no effect on eligibility.
- An optional, read-only paper-code audit that inventories declared
  repositories without cloning, installing, importing or executing them.
- SHA-256 artifact lineage across pipeline inputs and outputs.
- Private cross-review memory for queries, DOI, constructs and precedents,
  with decision reuse explicitly forbidden.
- CLI commands `intelligence`, `code-audit` and `memory`.
- An academic, offline figure gallery with publication PNG, editable SVG,
  scientific rationale and body/supplement/reserve decisions.
- Evidence-maturity, topic-network and coauthorship-network visuals as part of
  the review figure portfolio.
- A deterministic scientific figure gate that proposes up to four
  non-redundant visuals by default, or five substantive visuals for the
  security-harness profile, and retains the rest as downloadable supplementary
  material.
- A publication-oriented offline delivery index and atlas with accessible
  tables, downloadable PNG/SVG assets and GraphML/GEXF interoperability.
- A technical security-harness subprofile that extracts threat, control
  architecture, enforcement point, attacker adaptivity, security metrics,
  false positives, utility, latency, cost, robustness and failure modes.
- A security comparison matrix and conditional-dominance frontier that refuse
  to declare a universal winner across incompatible threats, baselines or
  operational trade-offs.
- Bilingual security taxonomies for prompt injection, jailbreak, tool and
  memory poisoning, exfiltration, operational control families and enforcement
  boundaries.
- A real-PDF multimodal acceptance artifact that renders the first page of a
  scientific document, asks the configured vision model to recover its title
  and compares that answer with the document text layer.
- A dedicated product download page that explains the complete distribution,
  links the versioned ZIP and checksum directly, and separates package
  inspection from installation guidance.

### Changed

- The manuscript results layer now reports evidence convergence,
  disagreements and open questions from extracted full text.
- Statistical direction and practical valence are now separate; cross-context
  alignment and descriptive alignment cannot be mislabeled as direct
  convergence.
- Delivery and schema contracts include scientific-intelligence outputs and
  public lineage while excluding private cross-review context.
- Direct intelligence, memory and paper-code commands now update resumable
  pipeline state; private memory transitions are removed from public state and
  lineage exports.
- Publication packaging avoids catastrophic path-sanitizer backtracking on
  large CSV cells while preserving local-path and internal-ID removal.
- Figure PNGs render at 2400 px by default, while the delivery index and
  structural atlas use a sober publication-oriented visual language.
- `package` rebuilds a missing or stale structural atlas before creating the
  ZIP, so interactive analysis cannot be advertised as an empty deliverable.
- LaTeX exports pin approved figures beside their explanatory text, constrain
  them to the printable area and synchronize manuscript-local assets from the
  canonical figure portfolio.
- The public package now treats the generated figure gallery, scientific
  intelligence and structural network analysis as first-class deliverables.
- Security-harness readiness now separates quantified effects, qualitative
  signals and metric mentions. Conditional dominance requires a quantified
  security outcome and a quantified operational trade-off.
- Official release archives now use the stable
  `hermes-research-pack-vX.Y.Z.zip` filename so documentation and product
  download links resolve to one reproducible asset.

### Fixed

- Removed stale PRISMA images, obsolete figure copies, `.DS_Store` files and
  placeholder markers from publication and editable-LaTeX archives.
- Prevented old manuscript-local assets from surviving a later figure
  regeneration.
- Kept the bundled systematic-review template inside public ZIP files while
  excluding only root-level generated review workspaces.
- Distinguished pending full-text retrievals from attempted failures in
  resumable manifests, preventing interrupted runs from skipping PDFs that had
  never been requested.
- Added bounded JSON retries for malformed or truncated full-text judgments,
  plus opt-in structured-output and reasoning controls for providers that pass
  the capability contract.
- Prevented the visual and independent-review models from acting as silent
  fallbacks for the primary scientific role.
- Applied the same bounded structured-output recovery to deep extraction and
  stopped doubling output budgets when reasoning is explicitly disabled.
- Hardened screening and extraction prompts so adversarial payloads reproduced
  inside security papers are treated as untrusted evidence, never instructions.
- Froze focal ranking before deep extraction so resumed runs cannot change the
  selected set merely because some candidates already have richer cached
  fields.
- Preserved canonical DOI, author, title, year and keyword identity when model
  extraction rows are merged from cache.
- Stopped treating section headings, table references, non-adaptive attack
  labels and negative artifact statements as positive comparison evidence.
- Replaced the synthetic-only vision check with a scientific-page verification
  that records the effective model and result without storing credentials.

### Security

- Public bundle manifests are recomputed after DOI/path sanitization and now
  exclude private cross-review memory, hidden operating-system files and stale
  generated assets.
- Release staging rejects virtual environments, local databases, credentials,
  runtime workspaces, nested archives and machine-specific caches before any
  manifest or ZIP is written.

## 0.5.1 - 2026-08-01

### Changed

- Reconciled the README, guided setup, operator guides, plugin policy and
  quality gate with the behavior shipped in `0.5.0`.
- Documented authenticated Docling traffic, bounded watchdog retries,
  protected full-text retrieval, dual screening, signed disagreement
  resolution, protocol amendments and operational gold datasets as one
  coherent contract.
- Clarified that restoring an existing review requires preserving the original
  adjudication secret; generating a new `.env` can invalidate prior signatures.
- Clarified cloud and local OpenAI-compatible inference routing from Docker
  without treating container loopback addresses as host services.
- Replaced the README product screenshots with reviewed renders of the current
  landing and documented their product role.
- Corrected release guidance so it matches the tag checks actually enforced by
  CI.

### Fixed

- Removed stale `0.4.1` issue-template metadata and contradictory statements
  about Docling authentication and cloud-only inference.
- Expanded troubleshooting for Telegram authentication, researcher
  checkpoints and pending protocol amendments.

## 0.5.0 - 2026-08-01

### Added

- Two independent screening judgments, agreement metrics and an automatic,
  non-binding recommendation for full-text eligibility disagreements.
- A recoverable `waiting_for_researcher` checkpoint: disputed studies are
  decided by DOI with a scientific reason and a signature bound to the frozen
  protocol and exact case.
- CLI and Telegram commands to inspect and resolve screening disagreements,
  with automatic resume only after the final pending case.
- Durable full-text judgment checkpoints that preserve completed search,
  downloads and A/B decisions across restarts.
- Signed protocol change proposals and approvals, with an inspectable
  explanation before any material amendment is applied.
- Operational gold datasets for screening, extraction and evidence location,
  with explicit provenance and no claim of external human ground truth.
- Optional institutional adapters for Scopus, Web of Science, Embase and IEEE
  Xplore, including traceable omission when credentials are unavailable.
- Required researcher identity, contact email, adjudication secret and Docling
  service key in the guided installation.

### Changed

- Full-text disagreements can no longer become automatic final exclusions.
  Resolved cases remain preserved so a later interruption cannot ask the
  researcher to decide the same evidence again.
- The watchdog now uses the versioned deterministic runner by default, applies
  bounded retries with exponential backoff and never overrides a researcher
  checkpoint.
- PDF retrieval validates destination, redirect, size, content type and PDF
  magic before storing a document.
- Public Telegram bindings are imposed by the gateway event instead of trusting
  user-supplied binding text.
- Research defaults now enable PII redaction, remove free Telegram terminal and
  file tools, clear broad command allowlists and use a neutral personality.
- Docling is isolated on an internal network and requires a generated API key.
- The publication gate now requires paired screening evidence, reliability
  metrics and signed resolution of every full-text disagreement.
- Setup, doctor, methodology, artifacts and command documentation now explain
  the human decision boundary and institutional-source coverage.

### Security

- Added SSRF and oversized-download regression tests, signed-adjudication tests,
  Telegram binding-spoof tests, bounded-watchdog tests and checkpoint recovery
  tests.
- Secret-bearing adjudication and disagreement records use private permissions,
  atomic replacement and filesystem synchronization.

## 0.4.1 - 2026-07-31

### Added

- `Setup_Hermes.txt`, an agent-facing acceptance runbook that guides a person
  through prerequisites, providers, scholarly APIs, Telegram, privacy and tests.
- Safe Telegram bot identity, private-user discovery and notification-chat
  validation without printing or placing the bot token in shell commands.
- Guided configuration for Unpaywall, Semantic Scholar, Lens and NCBI/PubMed.

### Changed

- `setup` now creates an explicit Telegram user allowlist and notification route
  instead of treating the bot token as a complete configuration.
- `doctor` now validates Telegram authorization and reports scholarly-source
  coverage without exposing credential values.
- Installation, configuration, quickstart and product documentation now explain
  how Hermes can supervise the complete setup.

## 0.4.0 - 2026-07-31

### Added

- Guided `setup`, `up`, `down` and `logs` commands.
- CLI, Telegram and combined installation modes.
- Exact or ranged final sample targets such as `37` or `23-63`.
- Provider-neutral OpenAI-compatible inference configuration.
- Separate Docling service for structured PDF, table, figure and OCR extraction.
- Executable intake, method, synthesis, journal and deliverables contracts with
  immutable hashes and an amendments ledger.
- Six methodological profiles for biomedical, technical, social-science,
  education, management and mixed-domain reviews.
- A claim-evidence ledger that links critical manuscript claims to citations,
  DOI, source fragments and page locations.
- A twelve-part offline delivery guide with a machine-readable manifest,
  availability state, file size and SHA-256 for every public deliverable.
- Durable background jobs with heartbeat, event ledger, content-addressed phase
  state and safe resume after an interruption.
- Capability probes for text, structured JSON and visual document reading, with
  model provenance and silent-substitution detection.
- Golden evaluation for screening, extraction and evidence localisation, with
  precision, recall, F1, specificity and field-level error analysis.
- Declarative topic packs and versioned artifact schemas.
- Release manifest, SHA-256 checksum, SBOM and fixable-vulnerability gate.
- Clean-room ZIP verification and public release documentation.
- Citation metadata, community health files, issue forms and pull-request checks.
- Ruff, pre-commit, cross-version CI and tag-driven GitHub release automation.
- Native plugin registration for the public Telegram command aliases.
- A plugin-only integration gate that compares critical Hermes modules with
  upstream and exercises discovery, commands, hooks, and gateway startup.
- Bounded smoke-test acquisition that exits before costly screening and
  publication while still proving two live bibliographic sources.

### Changed

- Pinned Hermes Agent to release `v2026.7.20` and commit
  `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`.
- Hardened the runtime with a multi-stage build, non-root execution,
  read-only filesystems, dropped capabilities and no-new-privileges.
- Reduced the runtime image and removed compilers, Git and unrelated skills.
- Made the repository the only source of truth for public bundle assets.
- Removed the Hermes CLI and gateway source overlays; the research product now
  integrates through the standalone plugin API.
- Removed temporary intake payloads immediately after bootstrap and hardened
  persistent state writes against partial filesystem updates.
- Made the publication autopilot incremental: stable phases are reused only
  while their input hashes remain unchanged.
- Sanitized public publication bundles by removing internal record identifiers,
  absolute paths and private PDF names while preserving DOI-based traceability.

### Removed

- Provider-specific names, credentials and private filesystem paths.
- Live review corpora, generated output and machine-specific runtime state.
- Bundled conference templates with separate redistribution obligations.
- The architecture-specific Tirith binary; installation is now verified at
  runtime against its upstream checksum.

## 0.0.3

- Initial internal distribution candidate.
