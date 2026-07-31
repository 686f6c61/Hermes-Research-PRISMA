#!/usr/bin/env bash
set -euo pipefail

./hermes-research init \
  --topic "personality in reasoning AI models" \
  --years 2025-2026 \
  --include "empirical studies with an experiment and readable full text" \
  --exclude "opinions, editorials, abstracts only, or records without a useful PDF" \
  --final-n 33 \
  --autonomous "sí"
