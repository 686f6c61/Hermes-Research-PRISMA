"""Gateway hooks for the Hermes Research plugin."""

from __future__ import annotations

import os
from typing import Any

from . import intake


def _public_mode_enabled() -> bool:
    """Return True when the public Telegram UX should be active."""
    return os.getenv("HERMES_TELEGRAM_PUBLIC_MENU_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _binding_key(event: Any) -> str:
    """Derive a stable per-user binding key from a gateway event."""
    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", "") or ""
    chat_id = getattr(source, "chat_id", "") or getattr(source, "channel_id", "") or ""
    user_id = (
        getattr(source, "user_id", "")
        or getattr(source, "sender_id", "")
        or getattr(event, "user_id", "")
        or getattr(event, "sender_id", "")
        or ""
    )
    if not platform or not chat_id:
        return ""
    return f"{platform}:{chat_id}:{user_id}" if user_id else f"{platform}:{chat_id}"


def _inject_binding(text: str, binding_key: str) -> str:
    """Add ``--binding`` to a /research command if it is not present yet."""
    if not binding_key or "--binding " in text:
        return text
    if "\n" in text:
        first, rest = text.split("\n", 1)
        return f"{first} --binding {binding_key}\n{rest}"
    return f"{text} --binding {binding_key}"


def _command_parts(text: str) -> tuple[str, str]:
    """Return a Telegram command without its optional bot suffix and its arguments."""
    head, _, tail = (text or "").strip().partition(" ")
    command = head.split("@", 1)[0].lower()
    return command, tail.strip()


def rewrite_public_research_flow(event: Any, **kwargs: Any) -> dict[str, str] | None:
    """Rewrite public Telegram research messages into plugin-native commands.

    This hook is the migration bridge away from hard-coded gateway logic. It
    rewrites the current public-product commands into the plugin's single
    `/research ...` command tree and attaches the chat binding key when
    possible.
    """
    del kwargs
    if not _public_mode_enabled():
        return None

    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", "") or ""
    if platform != "telegram":
        return None

    text = (getattr(event, "text", "") or "").strip()
    if not text:
        return None

    binding_key = _binding_key(event)
    command, suffix = _command_parts(text)

    if not text.startswith("/") and binding_key and intake.wizard_active(binding_key):
        return {"action": "rewrite", "text": f"/research wizard --binding {binding_key} {text}"}

    if not text.startswith("/") and intake.looks_like_intake_block(text):
        rewritten = f"/research init --binding {binding_key}\n{text}" if binding_key else f"/research init\n{text}"
        return {"action": "rewrite", "text": rewritten}

    if command == "/start":
        return {
            "action": "rewrite",
            "text": _inject_binding("/research help", binding_key),
        }

    if command == "/nueva_revision":
        if suffix and intake.looks_like_intake_block(suffix):
            rewritten = "/research init"
            if binding_key:
                rewritten += f" --binding {binding_key}"
            if suffix:
                rewritten += f" {suffix}"
        else:
            rewritten = "/research wizard"
            if binding_key:
                rewritten += f" --binding {binding_key}"
            rewritten += " start"
            if suffix:
                rewritten += f" {suffix}"
        return {"action": "rewrite", "text": rewritten}

    if command in {"/cancelar", "/cancel"}:
        rewritten = "/research wizard"
        if binding_key:
            rewritten += f" --binding {binding_key}"
        rewritten += " cancel"
        return {"action": "rewrite", "text": rewritten}

    if command == "/estado":
        rewritten = "/research status"
        if binding_key:
            rewritten += f" --binding {binding_key}"
        if suffix:
            rewritten += f" {suffix}"
        return {"action": "rewrite", "text": rewritten}

    if command == "/reanudar":
        rewritten = "/research resume"
        if binding_key:
            rewritten += f" --binding {binding_key}"
        if suffix:
            rewritten += f" {suffix}"
        return {"action": "rewrite", "text": rewritten}

    if command == "/research" and suffix:
        text = f"/research {suffix}"
        return {"action": "rewrite", "text": _inject_binding(text, binding_key)}

    return None
