# Changelog

All notable changes to Hermes Research Pack are documented here. The project
uses semantic versioning for its public wrapper, plugin contract and release
bundle.

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
