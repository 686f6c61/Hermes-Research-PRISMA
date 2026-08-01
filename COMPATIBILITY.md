# Compatibility

## Hermes Agent

Hermes Research Pack `0.5.1` is tested against:

- Hermes Agent release: `v2026.7.20`
- Hermes Agent commit: `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`
- Upstream package version: `0.19.0`

The Docker build verifies that the named release resolves to the pinned commit.
Changing either value is a maintainer operation and requires the full test,
image scan and clean-room release cycle.

## Host

- Linux or macOS
- Docker Engine or Docker Desktop with Compose v2
- Python 3.11 or newer
- `bash`, `curl`, `rsync`, `zip` and `unzip`
- Recommended: 4 CPU cores, 12 GB RAM and 20 GB free disk space

The Docling profile is CPU-only and optional. Without it, PDF processing falls
back to Poppler with reduced structural extraction.

## Inference provider

The provider must expose an OpenAI-compatible API under a base URL ending in
`/v1`, including:

- `GET /models`
- chat completions accepted by Hermes Agent
- a vision-capable model for rendered PDF pages

The primary, vision and independent-review model identifiers are configured
explicitly and checked by `doctor`.

## Public interfaces

- CLI: supported
- Telegram: supported and optional
- Slack: not included
- Obsidian synchronization: local bind mount, optional

## Upgrade boundary

The distribution uses a standalone Hermes plugin and does not replace pinned
CLI or gateway source files. `make plugin-only` compares the runtime modules
with the documented upstream commit and exercises plugin discovery, public
commands, the Telegram pre-dispatch hook, and gateway startup.
Therefore, installing the plugin into an arbitrary Hermes version is not a
supported upgrade path; use the supplied Docker distribution.
