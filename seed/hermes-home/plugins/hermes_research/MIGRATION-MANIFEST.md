# Hermes Research Plugin Migration Manifest

This manifest is the "nothing escapes" checklist for migrating the public
research product into a Hermes plugin.

## 1. Command and gateway surface

These are the product-facing entry points that should converge on the plugin:

| Current source | Current role | Target inside plugin | Status |
|---|---|---|---|
| Removed `build/overrides/gateway/run.py` | Public Telegram onboarding, intake parsing, status/resume routing | `hooks.py` + `commands.py` | Completed and verified on upstream |
| Removed `build/overrides/hermes_cli/commands.py` | Public menu shaping | plugin-native `/research`, `/nueva_revision`, `/estado`, `/reanudar`, `/cancelar`, `/ayuda` and CLI subcommand | Completed; Bot API menu remains distribution-owned |
| `seed/hermes-home/bin/start-gateway.sh` | Public Telegram description/menu sync | leave outside plugin for now | Keep outside |
| `seed/hermes-home/public-prisma-bindings.json` | Chat → review binding state | `bindings.py` | In progress |

## 2. Deterministic research workflow scripts

These scripts form the operational PRISMA runtime and should be callable
through plugin commands or plugin-owned tools.

| Current source | Target inside plugin | Status |
|---|---|---|
| `skills/research/prisma-systematic-review/scripts/bootstrap_public_intake.py` | plugin command `research init` | Wired |
| `skills/research/prisma-systematic-review/scripts/bootstrap_topic_review.py` | plugin data/runtime dependency | Pending vendor |
| `skills/research/prisma-systematic-review/scripts/bootstrap_architecture_review.py` | plugin data/runtime dependency | Pending vendor |
| `skills/research/prisma-systematic-review/scripts/doi_audit.py` | plugin data/runtime dependency | Pending vendor |
| `skills/research/prisma-systematic-review/scripts/complete_review.py` | plugin command `research resume` / CLI `run` | Wired |
| `skills/research/prisma-systematic-review/scripts/review_runtime_state.py` | plugin status helpers | Pending direct wiring |
| `skills/research/prisma-systematic-review/scripts/review_audit.py` | plugin diagnostics | Pending direct wiring |
| `skills/research/prisma-systematic-review/scripts/refresh_extraction_depth.py` | plugin maintenance command | Pending |
| `skills/research/prisma-systematic-review/scripts/publication_autopilot.py` | CLI `research autopilot` | Wired |
| `skills/research/prisma-systematic-review/scripts/publication_audit.py` | autopilot dependency | Indirect |
| `skills/research/prisma-systematic-review/scripts/publication_peer_review.py` | autopilot dependency | Indirect |
| `skills/research/prisma-systematic-review/scripts/publication_gate.py` | autopilot dependency | Indirect |
| `skills/research/prisma-systematic-review/scripts/export_publication_latex.py` | autopilot dependency | Indirect |
| `skills/research/prisma-systematic-review/scripts/prepare_paper_figures.py` | autopilot dependency | Indirect |
| `skills/research/prisma-systematic-review/scripts/render_review_figures.py` | autopilot dependency | Indirect |
| `skills/research/research-network-analysis/scripts/build_network_analysis.py` | review and autopilot dependency | Indirect |
| `skills/research/prisma-systematic-review/scripts/package_publication_bundle.py` | CLI `research package` | Wired |
| `skills/research/prisma-systematic-review/scripts/sync_review_to_obsidian.py` | publication dependency | Indirect |
| `skills/research/prisma-systematic-review/scripts/telegram_prisma_notify.py` | notification hook candidate | Pending |

## 3. Auxiliary research skills

These should eventually be re-exported or shipped natively by the plugin.

| Current source | Plugin role | Status |
|---|---|---|
| `skills/research/prisma-systematic-review/` | primary workflow skill | Re-exported |
| `skills/research/prisma-status/` | operational status skill | Re-exported |
| `skills/research/academic-paper-reviewer/` | peer review packet generation | Re-exported |
| `skills/research/research-integrity-audit/` | integrity checks | Re-exported |
| `skills/research/revision-roadmap/` | reviewer feedback roadmap | Re-exported |
| `skills/research/research-network-analysis/` | bibliometric and evidence-network atlas | Re-exported |

## 4. Template and data surface

These are part of the research product but not of the Hermes core.

| Current source | Target inside plugin | Status |
|---|---|---|
| `templates/systematic-review-template/` | plugin-owned data/templates | Pending vendor |
| `templates/systematic-review-template/paper/manuscript/publication-pattern.md` | plugin-owned data | Pending vendor |
| `templates/systematic-review-template/paper/review/reviewer-models.csv` | plugin-owned data | Pending vendor |
| `templates/systematic-review-template/AGENTS.md` | plugin-owned data | Pending vendor |
| `templates/systematic-review-template/telegram-prompts.md` | plugin-owned data | Pending vendor |
| `templates/systematic-review-template/obsidian-export.md` | plugin-owned data | Pending vendor |

## 5. Bundle-only infrastructure

These remain in the public package and should **not** move into the plugin.

| Current source | Why it stays outside |
|---|---|
| `Dockerfile.research` | image/runtime assembly |
| `docker-compose.research.yml` | container orchestration |
| `install.sh` | installer UX |
| `scripts/doctor.sh` | machine validation |
| `scripts/smoke-test.sh` | product smoke test |
| `scripts/cleanroom-validate.sh` | distribution validation |
| `scripts/release-bundle.sh` | release build |
| `scripts/verify-release-zip.sh` | release verification |
| `scripts/ship-release.sh` | release publishing |
| `scripts/sync-bundle-assets.sh` | maintainer sync |
| `examples/` | public onboarding/demo material |
| `docs/` | public documentation set |
| `.env.example` | product configuration contract |
| `seed/hermes-home/config.yaml` | provider policy and runtime defaults |

## 6. Core override retirement

The Hermes CLI and gateway overlays have been removed. The release gate now
fails if `Dockerfile.research` copies a replacement for:

- `hermes_cli/commands.py`
- `gateway/run.py`
- `gateway/slash_commands.py`

`scripts/plugin-only-test.sh` also compares all three installed modules byte
for byte with the pinned upstream commit before exercising plugin discovery,
commands, the Telegram hook, and gateway startup.

## 7. Migration phases

1. Ship the plugin shell and re-export the current research skills. Completed.
2. Route public Telegram intake and status/resume through plugin hooks and native public aliases. Completed.
3. Move wrapper-level workflows into `hermes research ...`. Completed.
4. Remove gateway and CLI core overlays. Completed and covered by CI.
5. Keep the distribution responsible for scientific dependencies, templates,
   watchdog, packaging, and release controls.
6. Vendor templates and skill payloads into a separately installable plugin
   archive if a plugin-only download is published in addition to the full
   distribution.
