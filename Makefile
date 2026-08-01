.DEFAULT_GOAL := help

PYTHON ?= python3

.PHONY: help install-dev lint test compose-check check cleanroom plugin-only release-candidate

help: ## Show the available development commands.
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install-dev: ## Install local quality and test tools.
	$(PYTHON) -m pip install --disable-pip-version-check \
		-r build/research-requirements.txt \
		pre-commit pytest pyyaml ruff==0.15.22

lint: ## Run Python, shell and publication-metadata checks.
	ruff check seed/hermes-home/plugins seed/hermes-home/skills/research tests
	bash scripts/lint-shell.sh
	$(PYTHON) scripts/validate-publication-metadata.py

test: ## Run the public regression suite.
	$(PYTHON) -m pytest -q

compose-check: ## Validate the Docker Compose contract without starting services.
	cp -n .env.example .env 2>/dev/null || true
	HERMES_DOCLING_API_KEY=$${HERMES_DOCLING_API_KEY:-compose-validation-only-0000000000000000} \
		docker compose -f docker-compose.research.yml --profile docling config >/dev/null

check: lint test compose-check ## Run the local merge gate.

cleanroom: ## Validate a fresh, credential-free installation.
	./hermes-research cleanroom-validate

plugin-only: ## Prove the plugin runs on unmodified pinned Hermes core modules.
	bash scripts/plugin-only-test.sh

release-candidate: check plugin-only ## Build and verify a clean release ZIP.
	REQUIRE_CLEAN_RELEASE=1 ./hermes-research release-bundle
	./hermes-research verify-release
