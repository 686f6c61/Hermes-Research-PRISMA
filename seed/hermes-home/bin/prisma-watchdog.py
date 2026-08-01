#!/usr/bin/env python3
"""Autonomous watchdog that relaunches stalled PRISMA reviews."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


HERMES_HOME = pathlib.Path(os.getenv("HERMES_HOME", "/opt/data")).resolve()
WORKSPACE_ROOT = pathlib.Path(os.getenv("PRISMA_WORKSPACE_ROOT", "/workspace")).resolve()
STATUS_SCRIPT = HERMES_HOME / "skills" / "research" / "prisma-status" / "scripts" / "review_status.py"
RUNTIME_SCRIPT = HERMES_HOME / "skills" / "research" / "prisma-systematic-review" / "scripts" / "review_runtime_state.py"
AUDIT_SCRIPT = HERMES_HOME / "skills" / "research" / "prisma-systematic-review" / "scripts" / "review_audit.py"
RESEARCH_SCRIPTS = HERMES_HOME / "skills" / "research" / "prisma-systematic-review" / "scripts"
JOB_RUNNER = HERMES_HOME / "plugins" / "hermes_research" / "job_runner.py"
STATE_PATH = HERMES_HOME / "watchdog" / "prisma-watchdog-state.json"


def now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"reviews": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"reviews": {}}


def save_state(payload: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_cmd(args: list[str], timeout: int | None = None, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(WORKSPACE_ROOT),
        text=True,
        capture_output=capture,
        timeout=timeout,
        check=False,
    )


def refresh_review(review_dir: pathlib.Path, stalled_minutes: int) -> None:
    run_cmd(["python3", str(RUNTIME_SCRIPT), str(review_dir), "--stalled-minutes", str(stalled_minutes)], timeout=120)
    run_cmd(["python3", str(AUDIT_SCRIPT), str(review_dir)], timeout=120)


def list_review_dirs() -> list[pathlib.Path]:
    if not WORKSPACE_ROOT.exists():
        return []
    reviews = []
    for child in sorted(WORKSPACE_ROOT.iterdir()):
        if not child.is_dir():
            continue
        if not child.name.startswith("systematic-review"):
            continue
        if child.name == "systematic-review-template":
            continue
        reviews.append(child.resolve())
    return reviews


def parse_intake_mode(review_dir: pathlib.Path) -> str:
    intake = review_dir / "protocol" / "intake.md"
    if not intake.exists():
        return "sí"
    for line in intake.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.lower().startswith("- modo autónomo:"):
            return line.split(":", 1)[1].strip().lower()
    return "sí"


def load_runtime(review_dir: pathlib.Path) -> dict:
    payload = {}
    runtime_json = review_dir / "notes" / "runtime-state.json"
    if runtime_json.exists():
        try:
            payload = json.loads(runtime_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    return payload


def candidate_signature(runtime_state: dict) -> str:
    return "|".join(
        [
            runtime_state.get("status", ""),
            runtime_state.get("current_phase", ""),
            runtime_state.get("next_phase", ""),
            runtime_state.get("next_action", ""),
            runtime_state.get("last_update", ""),
            runtime_state.get("blocker", ""),
        ]
    )


def should_skip(
    entry: dict,
    signature: str,
    cooldown_minutes: int,
    max_backoff_minutes: int,
) -> bool:
    last_attempt = entry.get("last_attempt_at")
    if not last_attempt:
        return False
    if entry.get("last_signature") != signature:
        return False
    try:
        attempted_at = datetime.fromisoformat(last_attempt)
    except ValueError:
        return False
    attempts = max(int(entry.get("attempts_for_signature", 1)), 1)
    backoff = min(cooldown_minutes * (2 ** max(attempts - 1, 0)), max_backoff_minutes)
    return now() - attempted_at < timedelta(minutes=backoff)


def choose_model(entry: dict, signature: str, models: list[str]) -> tuple[str, int]:
    attempts = 0
    if entry.get("last_signature") == signature:
        attempts = int(entry.get("attempts_for_signature", 0))
    index = min(attempts, len(models) - 1)
    return models[index], attempts


def mark_attempt(entry: dict, signature: str) -> None:
    if entry.get("last_signature") == signature:
        entry["attempts_for_signature"] = int(entry.get("attempts_for_signature", 0)) + 1
    else:
        entry["last_signature"] = signature
        entry["attempts_for_signature"] = 1
    entry["last_attempt_at"] = now().isoformat()
    entry["total_attempts"] = int(entry.get("total_attempts", 0)) + 1


def send_telegram_message(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_HOME_CHANNEL", "").strip()
    if not token or not chat_id:
        return False
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text})
    request = urllib.request.Request(api, data=payload.encode("utf-8"), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
        return True
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        print(f"[watchdog] Telegram notification failed: {type(exc).__name__}", file=sys.stderr)
        return False


def write_needs_human(review_dir: pathlib.Path, reason: str) -> None:
    """Persist a terminal watchdog state outside the model-controlled prompt."""

    path = review_dir / "notes" / "watchdog-needs-human.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "hermes.watchdog-needs-human/v1",
        "status": "needs_human",
        "reason": reason,
        "updated_at": now().isoformat(),
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = pathlib.Path(handle.name)
    os.replace(temporary, path)


def build_prompt(review_dir: pathlib.Path, runtime_state: dict) -> str:
    return (
        "Continúa de forma autónoma la revisión PRISMA ubicada en "
        f"{review_dir}. "
        "Lee notes/runtime-state.md y audit/phase-audit.md para identificar la primera fase incompleta. "
        f"Retoma exactamente desde {runtime_state.get('next_phase', 'la siguiente fase pendiente')}: "
        f"{runtime_state.get('next_action', 'continúa el flujo')}. "
        "No pidas confirmaciones operativas. "
        "Ejecuta trabajo real hasta dejar al menos un avance material o un bloqueo real. "
        "Tras cada actualización material, sincroniza a Obsidian, actualiza notes/runtime-state.md y notes/runtime-state.json, "
        "y ejecuta la auditoría por fase y la final. "
        "Si falta input humano imprescindible, deja el bloqueo explícito en notes/runtime-state.* y notes/decisions.md. "
        "Responde al final con un resumen muy breve en español de España con: Estado, Fase, Artefactos actualizados, Siguiente paso y Bloqueo."
    )


def select_candidate(
    stalled_minutes: int,
    cooldown_minutes: int,
    max_backoff_minutes: int,
    max_attempts_per_state: int,
    max_total_attempts: int,
    state_db: dict,
) -> tuple[pathlib.Path | None, dict | None]:
    candidates: list[tuple[pathlib.Path, dict]] = []
    for review_dir in list_review_dirs():
        if parse_intake_mode(review_dir) not in {"sí", "si", "yes", "true"}:
            continue
        refresh_review(review_dir, stalled_minutes)
        runtime_state = load_runtime(review_dir)
        if runtime_state.get("status") != "stalled":
            continue
        if (runtime_state.get("blocker") or "").strip() not in {"", "ninguno"}:
            continue
        review_key = str(review_dir)
        entry = state_db.setdefault("reviews", {}).setdefault(review_key, {})
        if entry.get("status") == "needs_human":
            continue
        signature = candidate_signature(runtime_state)
        attempts_for_state = (
            int(entry.get("attempts_for_signature", 0))
            if entry.get("last_signature") == signature
            else 0
        )
        total_attempts = int(entry.get("total_attempts", 0))
        if attempts_for_state >= max_attempts_per_state or total_attempts >= max_total_attempts:
            reason = (
                "El watchdog alcanzó su límite de reintentos "
                f"({attempts_for_state}/{max_attempts_per_state} para este estado; "
                f"{total_attempts}/{max_total_attempts} totales)."
            )
            entry["status"] = "needs_human"
            entry["terminal_reason"] = reason
            entry["terminal_at"] = now().isoformat()
            write_needs_human(review_dir, reason)
            send_telegram_message(f"Watchdog PRISMA\n`{review_dir.name}` necesita revisión humana.\n{reason}")
            save_state(state_db)
            continue
        if should_skip(entry, signature, cooldown_minutes, max_backoff_minutes):
            continue
        candidates.append((review_dir, runtime_state))

    if not candidates:
        return None, None

    candidates.sort(key=lambda item: item[1].get("last_update", ""), reverse=True)
    return candidates[0]


def status_markdown(review_dir: pathlib.Path) -> str:
    result = run_cmd(
        ["python3", str(STATUS_SCRIPT), str(review_dir), "--workspace-root", str(WORKSPACE_ROOT), "--format", "markdown"],
        timeout=120,
    )
    if result.returncode != 0:
        return f"Estado no disponible para {review_dir.name}."
    return result.stdout.strip()


def resume_review(
    review_dir: pathlib.Path,
    runtime_state: dict,
    state_db: dict,
    models: list[str],
    agent_timeout: int,
    execution_mode: str,
    allow_yolo: bool,
) -> None:
    review_key = str(review_dir)
    entry = state_db.setdefault("reviews", {}).setdefault(review_key, {})
    signature = candidate_signature(runtime_state)
    model, attempts = choose_model(entry, signature, models)
    mark_attempt(entry, signature)
    save_state(state_db)

    execution_detail = (
        f"`{execution_mode}`; modelo: `{model}`."
        if execution_mode == "agentic"
        else "`deterministic`; solo scripts versionados."
    )
    send_telegram_message(
        "Watchdog PRISMA\n"
        f"Reanudo `{review_dir.name}` desde `{runtime_state.get('next_phase', 'fase pendiente')}`.\n"
        f"Ejecución: {execution_detail}\n"
        f"Acción: {runtime_state.get('next_action', 'continuar flujo')}."
    )

    if execution_mode == "deterministic":
        cmd = [
            "python3",
            "-u",
            str(JOB_RUNNER),
            "--review-dir",
            str(review_dir),
            "--scripts-dir",
            str(RESEARCH_SCRIPTS),
            "--job-id",
            f"watchdog-{int(time.time())}",
        ]
    else:
        prompt = build_prompt(review_dir, runtime_state)
        cmd = [
            "hermes",
            "chat",
            "-Q",
            "--source",
            "tool",
            "-m",
            model,
            "-s",
            "prisma-systematic-review",
            "-s",
            "prisma-status",
            "-q",
            prompt,
        ]
        if allow_yolo:
            cmd.insert(3, "--yolo")

    try:
        result = run_cmd(cmd, timeout=agent_timeout)
    except subprocess.TimeoutExpired as exc:
        refresh_review(review_dir, env_int("PRISMA_WATCHDOG_STALLED_MINUTES", 15))
        summary = status_markdown(review_dir)
        send_telegram_message(
            "Watchdog PRISMA\n"
            f"La reanudación automática de `{review_dir.name}` ha alcanzado el tiempo máximo y se reintentará en el siguiente ciclo.\n\n"
            f"{summary}"
        )
        raise exc
    refresh_review(review_dir, env_int("PRISMA_WATCHDOG_STALLED_MINUTES", 15))
    summary = status_markdown(review_dir)

    if result.returncode == 0:
        send_telegram_message(
            "Watchdog PRISMA\n"
            f"Reanudación completada para `{review_dir.name}`.\n\n"
            f"{summary}"
        )
        return

    if execution_mode == "agentic" and attempts + 1 < len(models):
        fallback = models[min(attempts + 1, len(models) - 1)]
        send_telegram_message(
            "Watchdog PRISMA\n"
            f"Falló el intento con `{model}` en `{review_dir.name}`. "
            f"El siguiente intento usará `{fallback}`.\n"
            f"Salida: {(result.stderr or result.stdout or '').strip()[:800]}"
        )
    else:
        exhausted_detail = (
            "ya se agotó la cadena de modelos prevista"
            if execution_mode == "agentic"
            else "falló el runner determinista versionado"
        )
        send_telegram_message(
            "Watchdog PRISMA\n"
            f"La reanudación de `{review_dir.name}` no se completó: {exhausted_detail}.\n\n"
            f"{summary}\n\n"
            f"Salida: {(result.stderr or result.stdout or '').strip()[:800]}"
        )


def pass_once(
    stalled_minutes: int,
    cooldown_minutes: int,
    models: list[str],
    agent_timeout: int,
    dry_run: bool = False,
) -> int:
    state_db = load_state()
    max_backoff_minutes = env_int("PRISMA_WATCHDOG_MAX_BACKOFF_MINUTES", 360)
    max_attempts_per_state = env_int("PRISMA_WATCHDOG_MAX_ATTEMPTS_PER_STATE", 3)
    max_total_attempts = env_int("PRISMA_WATCHDOG_MAX_TOTAL_ATTEMPTS", 12)
    execution_mode = os.getenv("PRISMA_WATCHDOG_EXECUTION_MODE", "deterministic").strip().lower()
    if execution_mode not in {"deterministic", "agentic"}:
        execution_mode = "deterministic"
    allow_yolo = os.getenv("PRISMA_WATCHDOG_ALLOW_YOLO", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    review_dir, runtime_state = select_candidate(
        stalled_minutes,
        cooldown_minutes,
        max_backoff_minutes,
        max_attempts_per_state,
        max_total_attempts,
        state_db,
    )
    if review_dir is None or runtime_state is None:
        if dry_run:
            print("candidate: none")
        return 0
    if dry_run:
        print(json.dumps({"review_dir": str(review_dir), "runtime_state": runtime_state}, ensure_ascii=False, indent=2))
        return 0
    resume_review(
        review_dir,
        runtime_state,
        state_db,
        models,
        agent_timeout,
        execution_mode,
        allow_yolo,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run a single watchdog pass and exit")
    parser.add_argument("--dry-run", action="store_true", help="Show the selected stalled review without relaunching it")
    args = parser.parse_args()

    interval_seconds = env_int("PRISMA_WATCHDOG_INTERVAL_SECONDS", 300)
    stalled_minutes = env_int("PRISMA_WATCHDOG_STALLED_MINUTES", 15)
    cooldown_minutes = env_int("PRISMA_WATCHDOG_COOLDOWN_MINUTES", 30)
    agent_timeout = env_int("PRISMA_WATCHDOG_AGENT_TIMEOUT_SECONDS", 3600)
    configured_models = [
        os.getenv("HERMES_MODEL_PRIMARY", "").strip(),
        os.getenv("HERMES_MODEL_VISION", "").strip(),
        os.getenv("HERMES_MODEL_REVIEW", "").strip(),
    ]
    configured_models = list(dict.fromkeys(model for model in configured_models if model))
    if not configured_models:
        raise SystemExit("No watchdog models are configured. Run ./hermes-research setup.")
    models = env_list("PRISMA_WATCHDOG_MODELS", configured_models)

    if args.once:
        try:
            return pass_once(stalled_minutes, cooldown_minutes, models, agent_timeout, dry_run=args.dry_run)
        except subprocess.TimeoutExpired:
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"[watchdog] error: {exc}", file=sys.stderr, flush=True)
            return 1

    while True:
        try:
            pass_once(stalled_minutes, cooldown_minutes, models, agent_timeout)
        except subprocess.TimeoutExpired:
            send_telegram_message("Watchdog PRISMA\nLa reanudación automática ha excedido el tiempo máximo y se reintentará en el siguiente ciclo.")
        except Exception as exc:  # noqa: BLE001
            print(f"[watchdog] error: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
