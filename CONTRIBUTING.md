# Contributing

Hermes Research Pack accepts focused changes that improve reproducibility,
research quality, safety or installation reliability.

## Development workflow

1. Create a branch from the current default branch.
2. Keep credentials and real research data outside the repository.
3. Run `make install-dev` and `pre-commit install` once.
4. Add or update tests for behavioural changes.
5. Run `make check`.
6. Run `./hermes-research cleanroom-validate` for packaging or installation changes.
7. Describe user-facing changes in `CHANGELOG.md`.

`make check` is the local merge gate: Ruff, ShellCheck, publication metadata,
the complete pytest suite, and Docker Compose validation. CI repeats those
checks on Python 3.11 and 3.13 and scans the image for fixable HIGH or CRITICAL
vulnerabilities.

## Code quality

- Write comments and docstrings in English.
- Comment decisions, invariants, or failure handling; do not narrate obvious assignments.
- Prefer small pure helpers around filesystem, parsing, and policy boundaries.
- Use atomic writes for persistent state and restrict sensitive files to `0600`.
- Do not swallow broad exceptions when the expected failure modes can be named.
- Keep generated manuscripts, figures, PDFs, corpora, and runtime state out of Git.
- Add a regression test before changing a publication, screening, or migration contract.

## Design constraints

- Preserve the provider-neutral OpenAI-compatible configuration contract.
- Keep Telegram optional; the full workflow must remain usable from the CLI.
- Do not add a source or figure merely because it is available. Every artifact
  must have a declared methodological or interpretive purpose.
- Do not commit API keys, email addresses, private paths, runtime state, full
  research corpora or publisher-owned templates.
- Do not silently relax the publication gate or evidence requirements.
- Document new environment variables in `.env.example` and the configuration
  guide.
- Prefer official Hermes plugin APIs over core patches. Any unavoidable overlay
  must be listed in the migration manifest with a retirement condition.

## Pull requests

Keep each pull request narrow. State the problem, behavioral change, tests,
security impact and any migration step. A passing build is necessary but does
not replace a clean-room installation test.

By participating, you agree to follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
For usage questions use [SUPPORT.md](SUPPORT.md); report vulnerabilities only
through the private process in [SECURITY.md](SECURITY.md).
