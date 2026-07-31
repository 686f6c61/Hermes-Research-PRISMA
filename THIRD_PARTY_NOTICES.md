# Third-party notices

Hermes Research Pack includes or downloads the following principal
third-party components. Their own licenses govern those components.

## Hermes Agent

- Project: NousResearch/hermes-agent
- Source: https://github.com/NousResearch/hermes-agent
- Pinned release: `v2026.7.20`
- Pinned commit: `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`
- License: see the upstream repository

## Docling and Docling Serve

- Projects: docling-project/docling and docling-project/docling-serve
- Source: https://github.com/docling-project/docling
- Source: https://github.com/docling-project/docling-serve
- License: MIT
- Distribution: Docling Serve is pulled as a separately pinned container image.

## Tirith

- Project: sheeki03/tirith
- Source: https://github.com/sheeki03/tirith
- License: AGPL-3.0
- Distribution: no Tirith binary is included in this repository. The runtime
  may download a platform-specific upstream release after verifying its
  published checksum.

## Base images and packages

The Docker build uses pinned Debian-based Node and uv images and installs
Debian, Python and npm packages. The generated CycloneDX SBOM in each release
records the resolved component inventory. Refer to each package's metadata for
its license terms.
