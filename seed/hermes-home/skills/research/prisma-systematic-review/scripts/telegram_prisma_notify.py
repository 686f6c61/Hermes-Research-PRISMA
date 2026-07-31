#!/usr/bin/env python3
"""Send deduplicated PRISMA phase and delivery notifications to Telegram."""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from review_runtime_state import determine_state

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[4]
DEFAULT_ENV_PATHS = [
    pathlib.Path("/opt/data/.env"),
    REPO_ROOT / "hermes-home" / ".env",
]
TELEGRAM_OVERRIDE_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_HOME_CHANNEL",
    "TELEGRAM_HOME_CHANNEL_NAME",
    "TELEGRAM_PRISMA_CHAT_ID",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_dotenv_fallback() -> None:
    for env_path in DEFAULT_ENV_PATHS:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in TELEGRAM_OVERRIDE_KEYS:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)


def send_telegram_message(text: str) -> bool:
    load_dotenv_fallback()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = (
        os.getenv("TELEGRAM_PRISMA_CHAT_ID", "").strip()
        or os.getenv("TELEGRAM_HOME_CHANNEL", "").strip()
    )
    if not token or not chat_id:
        return False
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text})
    request = urllib.request.Request(api, data=payload.encode("utf-8"), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
        return True
    except urllib.error.URLError:
        return False


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_intake_value(intake_path: pathlib.Path, label: str) -> str:
    text = read_text(intake_path)
    match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", text, flags=re.MULTILINE)
    return (match.group(1) if match else "").strip()


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_flow_counts(review_dir: pathlib.Path) -> dict[str, str]:
    rows = read_csv_rows(review_dir / "prisma" / "flow-counts.csv")
    counts: dict[str, str] = {}
    for row in rows:
        stage = (row.get("stage") or "").strip()
        count = (row.get("count") or "").strip()
        if stage:
            counts[stage] = count
    return counts


def figure_count(review_dir: pathlib.Path) -> int:
    manifest = review_dir / "figures" / "manifest.csv"
    if not manifest.exists():
        return 0
    return max(sum(1 for _ in manifest.open("r", encoding="utf-8")) - 1, 0)


def package_path(review_dir: pathlib.Path) -> pathlib.Path:
    return review_dir / "paper" / "package" / "publication-package.zip"


def notes_state_path(review_dir: pathlib.Path) -> pathlib.Path:
    return review_dir / "notes" / "telegram-notify-state.json"


def load_notify_state(review_dir: pathlib.Path) -> dict[str, object]:
    path = notes_state_path(review_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_notify_state(review_dir: pathlib.Path, state: dict[str, object]) -> None:
    path = notes_state_path(review_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def review_label(review_dir: pathlib.Path) -> str:
    topic = parse_intake_value(review_dir / "protocol" / "intake.md", "Tema")
    return topic or review_dir.name


def build_counts_line(review_dir: pathlib.Path) -> str:
    counts = read_flow_counts(review_dir)
    parts: list[str] = []
    for stage, label in [
        ("identified_records", "identificados"),
        ("records_screened_title_abstract", "screening TA"),
        ("full_text_retrieved", "pdf"),
        ("full_text_assessed", "full text"),
        ("included_in_review", "incluidos"),
        ("shortlisted_final_n", "top N"),
    ]:
        value = counts.get(stage)
        if value:
            parts.append(f"{label}={value}")
    return ", ".join(parts)


def phase_message(review_dir: pathlib.Path, label: str = "") -> tuple[str, str]:
    state_path = review_dir / "notes" / "runtime-state.json"
    if state_path.exists():
        runtime = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        runtime = determine_state(review_dir, stalled_minutes=10)
    key = f"{runtime.get('status','')}|{runtime.get('current_phase','')}|{runtime.get('next_phase','')}"
    headline = label or "Cambio de fase detectado"
    counts_line = build_counts_line(review_dir)
    lines = [
        "Hermes PRISMA",
        headline,
        f"Revision: {review_label(review_dir)}",
        f"Carpeta: {review_dir.name}",
        f"Estado: {runtime.get('status', 'unknown')}",
        f"Fase actual: {runtime.get('current_phase', 'desconocida')}",
        f"Siguiente fase: {runtime.get('next_phase', 'desconocida')}",
    ]
    if counts_line:
        lines.append(f"Conteos: {counts_line}")
    next_action = (runtime.get("next_action") or "").strip()
    if next_action:
        lines.append(f"Siguiente accion: {next_action}")
    return key, "\n".join(lines)


def peer_review_summary(review_dir: pathlib.Path) -> str:
    overview = read_text(review_dir / "paper" / "review" / "peer-review-overview.md")
    verdicts = re.findall(r"`([^`]+)`", overview)
    if not verdicts:
        return ""
    return " / ".join(verdicts[:2])


def final_message(review_dir: pathlib.Path) -> tuple[str, str]:
    gate_path = review_dir / "paper" / "audit" / "publication-gate.md"
    gate_text = read_text(gate_path)
    gate_status_match = re.search(r"- Estado general:\s*`([^`]+)`", gate_text)
    gate_status = gate_status_match.group(1) if gate_status_match else "desconocido"
    zip_path = package_path(review_dir)
    package_stamp = str(int(zip_path.stat().st_mtime)) if zip_path.exists() else "missing"
    key = f"{gate_status}|{package_stamp}"
    counts_line = build_counts_line(review_dir)
    lines = [
        "Hermes PRISMA",
        "Entrega final actualizada",
        f"Revision: {review_label(review_dir)}",
        f"Carpeta: {review_dir.name}",
        f"Gate editorial: {gate_status}",
    ]
    review_summary = peer_review_summary(review_dir)
    if review_summary:
        lines.append(f"Peer review: {review_summary}")
    if counts_line:
        lines.append(f"Conteos: {counts_line}")
    lines.append(f"Figuras renderizadas: {figure_count(review_dir)}")
    lines.append(f"Paquete ZIP: {'listo' if zip_path.exists() else 'pendiente'}")
    lines.append(f"Actualizado: {now_iso()}")
    return key, "\n".join(lines)


def bootstrap_message(review_dir: pathlib.Path) -> tuple[str, str]:
    key = f"bootstrap|{review_dir.name}"
    lines = [
        "Hermes PRISMA",
        "Nueva revision creada",
        f"Revision: {review_label(review_dir)}",
        f"Carpeta: {review_dir.name}",
        "Estado: bootstrap completado y lista para continuar de forma autonoma.",
    ]
    counts_line = build_counts_line(review_dir)
    if counts_line:
        lines.append(f"Conteos iniciales: {counts_line}")
    return key, "\n".join(lines)


def dispatch(review_dir: pathlib.Path, bucket: str, key: str, text: str, force: bool = False) -> int:
    state = load_notify_state(review_dir)
    last_key = str(state.get(bucket, ""))
    if not force and last_key == key:
        return 0
    sent = send_telegram_message(text)
    if sent:
        state[bucket] = key
        state[f"{bucket}_sent_at"] = now_iso()
        save_notify_state(review_dir, state)
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    phase_parser = subparsers.add_parser("phase", help="Notify only when phase/status changed")
    phase_parser.add_argument("review_dir")
    phase_parser.add_argument("--label", default="")
    phase_parser.add_argument("--force", action="store_true")

    event_parser = subparsers.add_parser("event", help="Send a named lifecycle event")
    event_parser.add_argument("event_name", choices=["bootstrap", "start", "final"])
    event_parser.add_argument("review_dir")
    event_parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()

    if args.command == "phase":
        key, text = phase_message(review_dir, label=args.label)
        return dispatch(review_dir, "phase", key, text, force=args.force)

    if args.event_name == "bootstrap":
        key, text = bootstrap_message(review_dir)
        return dispatch(review_dir, "bootstrap", key, text, force=args.force)

    if args.event_name == "start":
        key, text = phase_message(review_dir, label="Inicio de ejecucion autonoma")
        return dispatch(review_dir, "start", f"{key}|{now_iso()[:16]}", text, force=args.force)

    key, text = final_message(review_dir)
    return dispatch(review_dir, "final", key, text, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
