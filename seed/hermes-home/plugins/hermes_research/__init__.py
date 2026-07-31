"""Hermes Research plugin registration."""

from __future__ import annotations

import logging
from pathlib import Path

from .cli import register_cli as _register_cli
from .cli import research_command as _research_command
from .commands import (
    handle_cancel_command,
    handle_help_command,
    handle_new_review_command,
    handle_research_command,
    handle_resume_command,
    handle_status_command,
)
from .hooks import rewrite_public_research_flow
from .runtime import hermes_home, research_skill_dir

logger = logging.getLogger(__name__)

_RESEARCH_SKILLS = (
    "prisma-systematic-review",
    "prisma-status",
    "academic-paper-reviewer",
    "research-integrity-audit",
    "revision-roadmap",
)

_PUBLIC_COMMANDS = (
    (
        "nueva_revision",
        handle_new_review_command,
        "Create a systematic review through the guided intake.",
    ),
    ("estado", handle_status_command, "Show the material state of the current review."),
    ("reanudar", handle_resume_command, "Resume the current review from its saved state."),
    ("cancelar", handle_cancel_command, "Cancel the active guided intake."),
    ("ayuda", handle_help_command, "Show the public Hermes Research command guide."),
)


def _register_skill_reexports(ctx) -> None:
    """Expose the packaged research skills under the plugin namespace."""
    for skill_name in _RESEARCH_SKILLS:
        skill_md = research_skill_dir(skill_name) / "SKILL.md"
        if skill_md.exists():
            ctx.register_skill(skill_name, skill_md)


def register(ctx) -> None:
    """Register the Hermes Research plugin surfaces."""
    ctx.register_command(
        "research",
        handler=handle_research_command,
        description="Hermes Research workflows: init, status, resume, package and migration status.",
    )
    # Native aliases keep the public UX discoverable outside the Telegram hook.
    for name, handler, description in _PUBLIC_COMMANDS:
        ctx.register_command(name, handler=handler, description=description)
    ctx.register_cli_command(
        name="research",
        help="Hermes Research workflows",
        setup_fn=_register_cli,
        handler_fn=_research_command,
        description="Deterministic PRISMA bootstrap, review status/resume and publication workflows.",
    )
    ctx.register_hook("pre_gateway_dispatch", rewrite_public_research_flow)
    _register_skill_reexports(ctx)

    logger.info(
        "hermes_research plugin loaded from %s (home=%s)",
        Path(__file__).resolve().parent,
        hermes_home(),
    )
