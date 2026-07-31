# Security policy

## Supported version

Security fixes are applied to the latest minor release only. The supported
version is listed in `VERSION`.

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, private research
corpus or identifying participant data. Use the repository's private GitHub
Security Advisory form instead.

Include the affected version, reproduction steps, impact, relevant logs with
secrets removed and any proposed mitigation. You should receive an initial
triage response within seven days.

## Runtime security model

- Containers run as a non-root user.
- The root filesystem is read-only.
- Linux capabilities are dropped and `no-new-privileges` is enabled.
- No inbound port is published by the default Compose file.
- Secrets stay in a local `.env` file with mode `0600`.
- Research data is stored in explicit host bind mounts and is never bundled.
- Release images are scanned for fixable HIGH and CRITICAL vulnerabilities.
- Every release contains a checksum, manifest and CycloneDX SBOM.

## User responsibilities

Use a dedicated Telegram bot, restrict access to the host, rotate provider
credentials, encrypt sensitive research data at rest and verify the legal basis
for processing PDFs or participant information. Generated manuscripts require
human scholarly review before submission.
