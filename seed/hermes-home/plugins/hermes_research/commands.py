"""Slash-command handlers for the Hermes Research plugin."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

from . import bindings, intake, runtime

_BINDING_RE = re.compile(r"^\s*--binding\s+(\S+)(?:\s+|$)", re.DOTALL)


def _strip_binding(raw_args: str) -> tuple[str, str]:
    """Return ``(binding_key, remainder)`` from a raw argument string."""
    text = raw_args or ""
    match = _BINDING_RE.match(text)
    if not match:
        return "", text.strip()
    binding_key = match.group(1).strip()
    remainder = text[match.end() :].strip()
    return binding_key, remainder


def _resolve_review(binding_key: str, token: str) -> Path | None:
    """Resolve a review from explicit token, binding, or latest workspace state."""
    if (token or "").strip():
        explicit = runtime.resolve_review_dir(token)
        if explicit is not None:
            return explicit
    bound = bindings.resolve_bound_review(binding_key)
    if bound is not None:
        return bound
    return runtime.latest_review_dir()


def _help_text() -> str:
    """Return the public help text for `/research`."""
    return (
        "`/research wizard` — crear una revisión nueva pregunta a pregunta\n"
        "`/research init` — crear una revisión nueva desde un bloque de intake avanzado\n"
        "`/research status` — ver el estado real de la revisión más reciente o ligada al chat\n"
        "`/research resume` — relanzar la revisión desde el punto material en el que quedó\n"
        "`/research manifest` — ver qué parte del producto ya migra al plugin\n\n"
        "En Telegram público usa `/nueva_revision`: el hook lo convierte en un wizard conversacional."
    )


def _run_bootstrap(binding_key: str, block: str) -> str:
    """Create a review deterministically from an intake block."""
    payload, missing = intake.parse_intake_block(block)
    if missing:
        fields = ", ".join(missing)
        return (
            "Faltan campos obligatorios en el intake: "
            f"{fields}.\n\nUsa este bloque:\n\n{intake.intake_template()}"
        )

    temp_json = runtime.write_temp_json(payload)
    try:
        output = runtime.run_command_capture(
            [
                "python3",
                str(runtime.prisma_scripts_dir() / "bootstrap_public_intake.py"),
                "--workspace-root",
                str(runtime.ensure_workspace()),
                "--intake-json",
                str(temp_json),
            ],
            timeout=300,
        )
    finally:
        # The generated protocol is durable; the contact-bearing transport file is not.
        temp_json.unlink(missing_ok=True)
    summary = runtime.parse_json_line(output)
    review_dir = Path(summary["review_dir"]).resolve()
    if binding_key:
        bindings.bind_review(binding_key, review_dir)
    autonomous_enabled = runtime.autonomous_mode_enabled(summary.get("autonomous_mode"))
    background_pid = None
    if autonomous_enabled:
        background_pid = runtime.launch_public_autonomous_review(review_dir)

    lines = [
        f"He creado la revisión `{summary['review_name']}`.\n"
        f"- Ruta: `{review_dir}`\n"
        f"- Modo metodológico: `{summary.get('review_mode_label') or summary.get('review_mode') or 'inferido'}`"
        f" ({summary.get('review_mode_confidence') or 'sin confianza registrada'})\n"
        f"- Estado: `{summary['status']}`\n"
        f"- Siguiente fase: `{summary['next_phase']}`\n"
        f"- Siguiente acción: {summary['next_action']}"
    ]
    if background_pid is not None:
        lines.extend(
            [
                "",
                "Hermes ya la está continuando en segundo plano.",
                f"- PID: `{background_pid}`",
                f"- Marcador: `{runtime.public_autonomous_pid_path(review_dir)}`",
            ]
        )
    return "\n".join(lines)


def _start_wizard(binding_key: str, topic: str = "") -> str:
    """Start or restart the guided Telegram intake wizard."""
    payload = {"topic": topic.strip()} if topic.strip() else {}
    start_step = 1 if payload.get("topic") else 0
    intake.save_wizard_state(
        binding_key,
        {
            "step": start_step,
            "status": "collecting",
            "payload": payload,
        },
    )
    intro = "Vamos a crear una revisión nueva paso a paso."
    if payload.get("topic"):
        intro = f"He tomado como tema: `{payload['topic']}`."
    return f"{intro}\n\n{intake.wizard_question(start_step)}"


def _cancel_wizard(binding_key: str) -> str:
    """Cancel the guided Telegram intake wizard for one chat."""
    intake.clear_wizard_state(binding_key)
    return "He cancelado la revisión en preparación. Cuando quieras empezar otra, usa `/nueva_revision`."


def _advance_wizard(binding_key: str, user_text: str) -> str:
    """Advance a guided Telegram intake wizard by one user reply."""
    state = intake.get_wizard_state(binding_key)
    if not state:
        return _start_wizard(binding_key)

    normalized = intake.normalize_value(user_text)
    if normalized in {"cancelar", "cancel", "salir", "parar", "stop"}:
        return _cancel_wizard(binding_key)

    payload = dict(state.get("payload") or {})
    status = str(state.get("status") or "collecting")
    if status == "confirming":
        if normalized in {"crear", "confirmar", "si", "sí", "ok", "adelante", "lanzar"}:
            intake.clear_wizard_state(binding_key)
            return _run_bootstrap(binding_key, intake.payload_to_intake_block(payload))
        if normalized in {"no", "editar", "volver"}:
            state["status"] = "collecting"
            state["step"] = 0
            intake.save_wizard_state(binding_key, state)
            return "Sin problema. Empezamos de nuevo para que quede limpio.\n\n" + intake.wizard_question(0)
        return "Tengo el intake completo. Responde `crear` para generar la revisión, `editar` para empezar de nuevo o `cancelar` para salir."

    step_index = int(state.get("step") or 0)
    if step_index >= len(intake.WIZARD_STEPS):
        state["status"] = "confirming"
        intake.save_wizard_state(binding_key, state)
        return intake.wizard_summary(payload)

    step = intake.WIZARD_STEPS[step_index]
    field = str(step["field"])
    default = str(step.get("default", ""))
    required = bool(step.get("required", False))
    if not required and normalized in {"saltar", "skip", "omitir", ""}:
        payload[field] = default
    else:
        clean_value, error = intake.validate_wizard_value(field, user_text)
        if error:
            return f"{error}\n\n{intake.wizard_question(step_index)}"
        payload[field] = clean_value or default

    step_index += 1
    state["payload"] = payload
    state["step"] = step_index
    if step_index >= len(intake.WIZARD_STEPS):
        state["status"] = "confirming"
        intake.save_wizard_state(binding_key, state)
        return intake.wizard_summary(payload)

    intake.save_wizard_state(binding_key, state)
    return intake.wizard_question(step_index)


def _show_status(binding_key: str, token: str) -> str:
    """Return the operational status for a resolved review."""
    review_dir = _resolve_review(binding_key, token)
    if review_dir is None:
        return "No encuentro ninguna revisión para inspeccionar."
    status = runtime.run_command_capture(
        [
            "python3",
            str(runtime.prisma_status_script()),
            str(review_dir),
            "--format",
            "markdown",
        ]
    ).strip()
    return f"**Revisión activa:** `{review_dir.name}`\n\n{status}"


def _background_review_is_running(review_dir: Path) -> tuple[bool, int | None]:
    """Return whether the public autonomous review worker still appears alive."""
    marker = runtime.public_autonomous_pid_path(review_dir)
    if not marker.exists():
        return False, None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        pid = int(payload.get("pid", 0) or 0)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return False, None
    if pid <= 0:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except OSError:
        return False, pid


def _resume_review(binding_key: str, token: str) -> str:
    """Resume the PRISMA workflow in the background for a resolved review."""
    review_dir = _resolve_review(binding_key, token)
    if review_dir is None:
        return "No encuentro ninguna revisión para reanudar."

    if binding_key:
        bindings.bind_review(binding_key, review_dir)

    running, pid = _background_review_is_running(review_dir)
    if running:
        pid_text = f" (PID `{pid}`)" if pid else ""
        return (
            f"La revisión `{review_dir.name}` ya está en marcha{pid_text}.\n"
            "Usa `/estado` para seguir el avance real. Solo hace falta `/reanudar` si se queda parada."
        )

    log_path = review_dir / "notes" / "run.log"
    command = [
        "python3",
        "-u",
        str(runtime.prisma_scripts_dir() / "complete_review.py"),
        str(review_dir),
    ]
    pid = runtime.launch_background(command, log_path, cwd=review_dir)
    return (
        f"He reanudado la revisión `{review_dir.name}` en segundo plano.\n"
        f"- PID: `{pid}`\n"
        f"- Log: `{log_path}`"
    )


def _manifest_summary() -> str:
    """Return a short migration summary for quick inspection from chat."""
    manifest_path = runtime.plugin_dir() / "MIGRATION-MANIFEST.md"
    if not manifest_path.exists():
        return "No encuentro el manifiesto de migración del plugin."
    return (
        "El plugin `hermes_research` ya absorbe:\n"
        "- slash command `/research`\n"
        "- CLI `hermes research`\n"
        "- hook de reescritura del flujo público\n"
        "- binding de chat a revisión\n"
        "- re-export de skills de research\n\n"
        f"Manifiesto completo: `{manifest_path}`"
    )


def handle_new_review_command(raw_args: str) -> str:
    """Start the guided wizard or accept a complete advanced intake block."""
    binding_key, body = _strip_binding(raw_args)
    if body and intake.looks_like_intake_block(body):
        return _run_bootstrap(binding_key, body)
    return _start_wizard(binding_key, body)


def handle_status_command(raw_args: str) -> str:
    """Resolve and report the review associated with the current command."""
    binding_key, token = _strip_binding(raw_args)
    return _show_status(binding_key, token)


def handle_resume_command(raw_args: str) -> str:
    """Resume the review associated with the current command."""
    binding_key, token = _strip_binding(raw_args)
    return _resume_review(binding_key, token)


def handle_cancel_command(raw_args: str) -> str:
    """Cancel the active intake wizard for the current command."""
    binding_key, _body = _strip_binding(raw_args)
    return _cancel_wizard(binding_key)


def handle_help_command(_raw_args: str) -> str:
    """Return the concise public command guide."""
    return _help_text()


def handle_research_command(raw_args: str) -> str:
    """Dispatch `/research <subcommand>` calls."""
    remainder = (raw_args or "").strip()
    if not remainder:
        return _help_text()

    first_line, _, tail = remainder.partition("\n")
    parts = first_line.strip().split(maxsplit=1)
    subcommand = parts[0].lower() if parts else "help"
    inline_rest = parts[1] if len(parts) > 1 else ""
    binding_key, body = _strip_binding("\n".join(part for part in [inline_rest, tail] if part).strip())

    handlers: dict[str, Callable[[str, str], str] | Callable[[], str]] = {
        "help": _help_text,
        "manifest": _manifest_summary,
    }
    if subcommand in handlers:
        handler = handlers[subcommand]
        if callable(handler):
            return handler()  # type: ignore[misc]

    if subcommand == "init":
        if not body:
            return _start_wizard(binding_key)
        return _run_bootstrap(binding_key, body)

    if subcommand == "wizard":
        action, _, rest = body.partition(" ")
        action = action.strip().lower()
        if not action or action == "start":
            return _start_wizard(binding_key, rest)
        if action in {"cancel", "cancelar"}:
            return _cancel_wizard(binding_key)
        return _advance_wizard(binding_key, body)

    if subcommand in {"cancel", "cancelar"}:
        return _cancel_wizard(binding_key)

    if subcommand == "status":
        return _show_status(binding_key, body)

    if subcommand == "resume":
        return _resume_review(binding_key, body)

    return _help_text()
