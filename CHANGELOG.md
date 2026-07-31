# Changelog

All notable changes to Hermes Research Pack are documented here. The project
uses semantic versioning for its public wrapper, plugin contract and release
bundle.

## 0.3.0 - 2026-07-31

### Added

- Guided `setup`, `up`, `down` and `logs` commands.
- CLI, Telegram and combined installation modes.
- Exact or ranged final sample targets such as `37` or `23-63`.
- Provider-neutral OpenAI-compatible inference configuration.
- Separate Docling service for structured PDF, table, figure and OCR extraction.
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

### Removed

- Provider-specific names, credentials and private filesystem paths.
- Live review corpora, generated output and machine-specific runtime state.
- Bundled conference templates with separate redistribution obligations.
- The architecture-specific Tirith binary; installation is now verified at
  runtime against its upstream checksum.

## 0.2.0

- Initial internal distribution candidate.
