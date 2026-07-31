# Hermes Research Plugin

This plugin is the command and lifecycle layer of the public Hermes Research
workflow. The release bundle installs it together with:

- bundled research skills and scripts
- Telegram public-product overrides
- the `hermes-research` wrapper
- template/data assets in the public bundle

It follows Hermes' standalone plugin contract: a manifest, one `register(ctx)`
entry point, namespaced skills, slash and CLI commands, and a
`pre_gateway_dispatch` hook for the stateful Telegram wizard.

## What this plugin does

- Registers a single slash command: `/research`
- Registers a CLI command: `hermes research`
- Rewrites the public Telegram flow into plugin-native commands via
  `pre_gateway_dispatch`
- Re-exports the existing research skills into the plugin namespace
- Maintains chat-to-review bindings in `public-prisma-bindings.json`
- Searches OpenAlex, Crossref, Semantic Scholar, arXiv and OpenAIRE by default.
- Adds Lens when `HERMES_LENS_API_KEY` or `LENS_API_KEY` exists.
- Adds Europe PMC and PubMed automatically for biomedical/health/psychology topics, or when forced with environment flags.
- Uses Unpaywall as a DOI-to-open-access/full-text resolver when `HERMES_UNPAYWALL_EMAIL` or `UNPAYWALL_EMAIL` is configured. This value is treated as a secret/contact setting and is never written to review artifacts.
- Asks for an optional methodological field in the Telegram wizard, but can also infer it automatically and persist the rationale in `protocol/review-mode.md`.

## Optional Research Source Environment

- `HERMES_UNPAYWALL_EMAIL` or `UNPAYWALL_EMAIL`: contact email for Unpaywall full-text resolution.
- `HERMES_LENS_API_KEY` or `LENS_API_KEY`: optional Lens Scholarly API token; if absent, Lens is skipped without failing the review.
- `HERMES_ENABLE_EUROPEPMC=1` and `HERMES_ENABLE_PUBMED=1`: force specialist biomedical sources.
- `HERMES_DISABLE_OPENAIRE=1`, `HERMES_DISABLE_LENS=1`, `HERMES_DISABLE_EUROPEPMC=1`, `HERMES_DISABLE_PUBMED=1`: disable specific sources.
- `HERMES_NCBI_EMAIL` and `HERMES_NCBI_API_KEY`: optional NCBI contact/rate-limit settings.
- `SEMANTIC_SCHOLAR_API_KEY` or `HERMES_SEMANTIC_SCHOLAR_API_KEY`: optional Semantic Scholar API key.

## Bundle-level responsibilities

- Docker packaging and release tooling
- provider policy and environment secrets
- bundle installer, doctor, smoke test, clean-room validation
- compatibility overrides required by the public Telegram menu

See `MIGRATION-MANIFEST.md` for the exhaustive inventory.
