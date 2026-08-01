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
        "`/research approve` — firmar la aprobación final como investigador responsable\n"
        "`/research reject` — firmar un rechazo final motivado\n"
        "`/research disagreements` — revisar discrepancias de elegibilidad por DOI\n"
        "`/research resolve DOI include|exclude MOTIVO` — decidir una discrepancia y reanudar\n"
        "`/research changes` — explicar cualquier cambio pendiente del protocolo\n"
        "`/research approve-change` — aprobar el cambio exacto antes de aplicarlo\n"
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
                f"- Proceso supervisor: `{background_pid}`",
                f"- Estado durable: `{runtime.public_job_ledger_path(review_dir)}`",
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
    """Return whether the heartbeat-aware autonomous runner is still alive."""
    ledger = runtime.public_job_ledger_path(review_dir)
    if ledger.exists():
        try:
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            pid = int(payload.get("runner_pid", 0) or 0)
            status = str(payload.get("status") or "").lower()
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pid = 0
            status = ""
        if status in {"starting", "running"} and pid > 0:
            try:
                os.kill(pid, 0)
                return True, pid
            except OSError:
                return False, pid
        if status in {
            "completed",
            "failed",
            "cancelled",
            "waiting_for_researcher",
        }:
            return False, pid or None

    # Compatibility with jobs started before the durable ledger existed.
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

    pid = runtime.launch_public_autonomous_review(review_dir)
    log_path = review_dir / "notes" / "run.log"
    return (
        f"He reanudado la revisión `{review_dir.name}` en segundo plano.\n"
        f"- Proceso supervisor: `{pid}`\n"
        f"- Estado durable: `{runtime.public_job_ledger_path(review_dir)}`\n"
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


def _adjudication_user_allowed(binding_key: str) -> bool:
    """Allow signed decisions only for explicitly configured Telegram owners."""

    user_id = (binding_key or "").rsplit(":", 1)[-1].strip()
    configured = (
        os.getenv("HERMES_ADJUDICATION_ALLOWED_USERS", "").strip()
        or os.getenv("TELEGRAM_ALLOWED_USERS", "").strip()
    )
    allowed = {
        item.strip()
        for item in re.split(r"[\s,;]+", configured)
        if item.strip()
    }
    return bool(user_id and user_id in allowed)


def _adjudicate_review(binding_key: str, decision: str, reason: str) -> str:
    """Record a signed decision for the review bound to the requesting owner."""

    if not _adjudication_user_allowed(binding_key):
        return "Este usuario no está autorizado para firmar la adjudicación científica."
    review_dir = _resolve_review(binding_key, "")
    if review_dir is None:
        return "No encuentro ninguna revisión ligada a este chat."
    script = runtime.prisma_scripts_dir() / "record_human_adjudication.py"
    try:
        output = runtime.run_command_capture(
            [
                "python3",
                str(script),
                str(review_dir),
                "--decision",
                decision,
                "--reason",
                reason,
            ],
            timeout=120,
        ).strip()
    except Exception as exc:
        return f"No se pudo firmar la adjudicación: {str(exc)[:500]}"
    return (
        f"Decisión `{decision}` firmada para `{review_dir.name}`.\n"
        f"- Registro: `{output or review_dir / 'paper/audit/human-adjudication.json'}`\n"
        "- La firma queda vinculada al contrato metodológico actual."
    )


def _pending_change_summary(binding_key: str) -> str:
    """Explain the exact frozen-contract changes awaiting approval."""

    review_dir = _resolve_review(binding_key, "")
    if review_dir is None:
        return "No encuentro ninguna revisión ligada a este chat."
    path = review_dir / "protocol" / "pending-amendment.json"
    if not path.is_file():
        return "No hay ningún cambio metodológico pendiente."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "La propuesta pendiente no es un JSON válido y no puede aprobarse."
    lines = [
        f"Cambio metodológico pendiente en `{review_dir.name}`.",
        str(payload.get("explanation") or ""),
    ]
    for contract in payload.get("contracts") or []:
        lines.append(f"\n**{contract.get('contract', 'contrato')}**")
        for item in (contract.get("changes") or [])[:20]:
            lines.append(
                f"- `{item.get('path')}`: `{item.get('before')}` → `{item.get('after')}`"
            )
    lines.append(
        "\nSi la propuesta es correcta, usa `/research approve-change MOTIVO`. "
        "Nada se modifica antes de esa firma."
    )
    return "\n".join(lines)


def _approve_protocol_change(binding_key: str, reason: str) -> str:
    """Sign the exact pending amendment for an authorized researcher."""

    if not _adjudication_user_allowed(binding_key):
        return "Este usuario no está autorizado para aprobar cambios metodológicos."
    if not (reason or "").strip():
        return "Explica el motivo: `/research approve-change MOTIVO`."
    review_dir = _resolve_review(binding_key, "")
    if review_dir is None:
        return "No encuentro ninguna revisión ligada a este chat."
    script = runtime.prisma_scripts_dir() / "approve_protocol_change.py"
    try:
        output = runtime.run_command_capture(
            [
                "python3",
                str(script),
                str(review_dir),
                "--reason",
                reason,
            ],
            timeout=120,
        ).strip()
    except Exception as exc:
        return f"No se pudo aprobar el cambio: {str(exc)[:500]}"
    return (
        f"Cambio firmado para `{review_dir.name}`.\n"
        f"- Aprobación: `{output}`\n"
        "- Usa `/reanudar` para aplicar el contrato aprobado y continuar."
    )


def _disagreement_status(review_dir: Path) -> dict[str, object]:
    """Read signed resolution status through the shared deterministic helper."""

    script = runtime.prisma_scripts_dir() / "resolve_screening_disagreement.py"
    output = runtime.run_command_capture(
        [
            "python3",
            str(script),
            str(review_dir),
            "--list",
        ],
        timeout=120,
    ).strip()
    payload = json.loads(output)
    return payload if isinstance(payload, dict) else {}


def _pending_disagreements_summary(binding_key: str) -> str:
    """Show decisions and evidence without exposing internal record identifiers."""

    review_dir = _resolve_review(binding_key, "")
    if review_dir is None:
        return "No encuentro ninguna revisión ligada a este chat."
    try:
        status = _disagreement_status(review_dir)
    except (RuntimeError, json.JSONDecodeError) as exc:
        return f"No se pudieron leer las discrepancias: {str(exc)[:500]}"
    cases = status.get("unresolved_cases") or []
    if not isinstance(cases, list) or not cases:
        if int(status.get("resolved") or 0):
            return (
                "Todas las discrepancias ya tienen una decisión firmada. "
                "El ciclo puede continuar desde su checkpoint."
            )
        return "No hay discrepancias de elegibilidad pendientes."
    lines = [
        f"**Discrepancias pendientes en `{review_dir.name}`: {len(cases)}**",
        (
            "Ningún estudio de esta lista ha sido rechazado automáticamente. "
            "La recomendación orienta; tú decides si entra en el corpus final."
        ),
    ]
    for case in cases[:10]:
        if not isinstance(case, dict):
            continue
        doi = str(case.get("assigned_doi") or "").strip()
        title = " ".join(str(case.get("title") or "").split())
        if len(title) > 180:
            title = title[:177].rstrip() + "..."
        reviewer_a = (
            case.get("reviewer_a")
            if isinstance(case.get("reviewer_a"), dict)
            else {}
        )
        reviewer_b = (
            case.get("reviewer_b")
            if isinstance(case.get("reviewer_b"), dict)
            else {}
        )
        recommendation = (
            case.get("automatic_recommendation")
            if isinstance(case.get("automatic_recommendation"), dict)
            else {}
        )
        lines.extend(
            [
                "",
                f"**DOI:** `{doi}`",
                f"**Título:** {title}",
                (
                    f"- Juicio A: `{reviewer_a.get('decision', '')}`; "
                    f"juicio B: `{reviewer_b.get('decision', '')}`"
                ),
                (
                    "- Recomendación automática no vinculante: "
                    f"`{recommendation.get('decision', '')}`"
                ),
                (
                    f"- Decide: `/research resolve {doi} "
                    "include|exclude MOTIVO`"
                ),
            ]
        )
    if len(cases) > 10:
        lines.append(f"\nQuedan {len(cases) - 10} casos adicionales.")
    return "\n".join(lines)


def _resolve_screening_disagreement(binding_key: str, body: str) -> str:
    """Record one signed DOI-level choice and resume after the last conflict."""

    if not _adjudication_user_allowed(binding_key):
        return "Este usuario no está autorizado para decidir la elegibilidad final."
    parts = (body or "").strip().split(maxsplit=2)
    if len(parts) < 3:
        return (
            "Usa `/research resolve DOI include|exclude MOTIVO`. "
            "La justificación científica es obligatoria."
        )
    doi, raw_decision, reason = parts
    decision_map = {
        "include": "include",
        "incluir": "include",
        "seguir": "include",
        "continue": "include",
        "exclude": "exclude",
        "excluir": "exclude",
        "rechazar": "exclude",
        "reject": "exclude",
    }
    decision = decision_map.get(raw_decision.strip().lower(), "")
    if not decision:
        return "La decisión debe ser `include` o `exclude`."
    review_dir = _resolve_review(binding_key, "")
    if review_dir is None:
        return "No encuentro ninguna revisión ligada a este chat."
    script = runtime.prisma_scripts_dir() / "resolve_screening_disagreement.py"
    try:
        output = runtime.run_command_capture(
            [
                "python3",
                str(script),
                str(review_dir),
                "--doi",
                doi,
                "--decision",
                decision,
                "--reason",
                reason,
            ],
            timeout=120,
        ).strip()
        status = json.loads(output)
    except Exception as exc:
        return f"No se pudo registrar la decisión: {str(exc)[:500]}"
    unresolved = int(status.get("unresolved") or 0)
    if unresolved:
        return (
            f"Decisión `{decision}` firmada para `{doi}`.\n"
            f"Quedan {unresolved} discrepancia(s). No se pierde trabajo y el "
            "ciclo seguirá pausado hasta resolverlas todas.\n\n"
            "Usa `/research disagreements` para ver la siguiente."
        )
    resume_message = _resume_review(binding_key, "")
    return (
        f"Decisión `{decision}` firmada para `{doi}`.\n"
        "Ya no quedan discrepancias: el ciclo se reanuda automáticamente "
        "desde el checkpoint, sin repetir búsqueda ni juicios A/B.\n\n"
        f"{resume_message}"
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

    if subcommand in {"approve", "aprobar"}:
        return _adjudicate_review(binding_key, "approved", body)

    if subcommand in {"reject", "rechazar"}:
        return _adjudicate_review(binding_key, "rejected", body)

    if subcommand in {"disagreements", "discrepancias"}:
        return _pending_disagreements_summary(binding_key)

    if subcommand in {"resolve", "resolver"}:
        return _resolve_screening_disagreement(binding_key, body)

    if subcommand in {"changes", "cambios"}:
        return _pending_change_summary(binding_key)

    if subcommand in {"approve-change", "aprobar-cambio"}:
        return _approve_protocol_change(binding_key, body)

    return _help_text()
