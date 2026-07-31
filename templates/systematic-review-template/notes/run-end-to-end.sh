#!/bin/sh
set -eu

REVIEW_DIR="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-/opt/data}"
SCRIPTS="$HERMES_HOME/skills/research/prisma-systematic-review/scripts"
LOG_FILE="$REVIEW_DIR/notes/run.log"

mkdir -p "$REVIEW_DIR/notes"
{
  printf '\n[%s] START run-end-to-end\n' "$(date -Iseconds)"

  python3 -u "$SCRIPTS/telegram_prisma_notify.py" event start "$REVIEW_DIR" --force || true

  python3 -u "$SCRIPTS/complete_review.py" "$REVIEW_DIR"
  python3 -u "$SCRIPTS/review_runtime_state.py" "$REVIEW_DIR"
  python3 -u "$SCRIPTS/telegram_prisma_notify.py" phase "$REVIEW_DIR" || true
  python3 -u "$SCRIPTS/review_audit.py" "$REVIEW_DIR"
  python3 -u "$SCRIPTS/prepare_paper_figures.py" "$REVIEW_DIR"
  python3 -u "$SCRIPTS/render_review_figures.py" "$REVIEW_DIR" --width 2000
  python3 -u "$SCRIPTS/publication_autopilot.py" "$REVIEW_DIR"
  python3 -u "$SCRIPTS/telegram_prisma_notify.py" event final "$REVIEW_DIR" || true

  printf '[%s] END run-end-to-end\n' "$(date -Iseconds)"
} >>"$LOG_FILE" 2>&1
