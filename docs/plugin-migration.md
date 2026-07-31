# Hermes Research Plugin Integration

Hermes Research now integrates with the pinned Hermes Agent release through a
first-class standalone plugin. The runtime image no longer copies or modifies
`hermes_cli/commands.py`, `gateway/run.py`, or
`gateway/slash_commands.py`.

## Plugin-owned behaviour

`seed/hermes-home/plugins/hermes_research/` owns:

- `/research` and the public Telegram command aliases
- `hermes research`
- `/start`, advanced intake, and wizard routing through
  `pre_gateway_dispatch`
- safe chat-to-review bindings and durable wizard state
- status, resume, package, and publication orchestration
- namespaced re-exports of the research skills

## Distribution-owned behaviour

The installer, Docker image, scientific system packages, provider
configuration, watchdog, release scripts, and clean-room verification remain
outside the plugin because they belong to the reproducible distribution rather
than the Hermes extension API.

## Proof

`make plugin-only`:

1. rejects Dockerfiles that copy the removed core overlays
2. compares the three critical runtime modules byte for byte with the pinned
   upstream commit
3. loads `hermes_research` from an isolated credential-free home
4. verifies all public commands
5. exercises the official Telegram pre-dispatch hook
6. starts the upstream gateway and checks its plugin log

The detailed ownership inventory remains in
`seed/hermes-home/plugins/hermes_research/MIGRATION-MANIFEST.md`.
