#!/usr/bin/env python3
"""Iterate the publication layer until PASS or a stable documented blocker."""

from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

SCRIPTS = pathlib.Path(__file__).resolve().parent
RESEARCH_SKILLS = SCRIPTS.parent.parent
INTEGRITY_AUDIT_SCRIPT = RESEARCH_SKILLS / "research-integrity-audit" / "scripts" / "check_manuscript_integrity.py"
STEP_TIMEOUTS = {
    "prepare_paper_figures.py": 1800,
    "render_review_figures.py": 900,
    "publication_audit.py": 1800,
    "export_publication_latex.py": 1200,
    "publication_peer_review.py": 2400,
    "package_publication_bundle.py": 900,
    "publication_gate.py": 300,
    "journal_readiness_gate.py": 300,
    "sync_review_to_obsidian.py": 900,
    "integrity_audit": 900,
}


@dataclass
class RoundStatus:
    round_number: int
    gate_status: str
    audit_status: str
    reviewer_summary: str
    manuscript_hash: str


def read_text(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_markdown_status(path: pathlib.Path) -> str:
    text = read_text(path)
    match = re.search(r"Estado global:\s+\*\*(PASS|WARN|FAIL)\*\*", text)
    return match.group(1) if match else "UNKNOWN"


def parse_reviewer_summary(path: pathlib.Path) -> str:
    if not path.exists():
        return "no_reviews"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    verdicts = sorted((row.get("verdict") or "unknown").strip().lower() for row in rows)
    return "|".join(verdicts) if verdicts else "no_reviews"


def manuscript_hash(path: pathlib.Path) -> str:
    content = read_text(path).encode("utf-8", errors="ignore")
    return hashlib.sha256(content).hexdigest()[:16] if content else "empty"


def run_step(script_name: str, review_dir: pathlib.Path, extra_args: list[str] | None = None) -> None:
    script_path = SCRIPTS / script_name
    cmd = [sys.executable, str(script_path), str(review_dir)]
    if extra_args:
        cmd.extend(extra_args)
    timeout = STEP_TIMEOUTS.get(script_name)
    try:
        subprocess.run(
            cmd,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{script_name} timed out after {timeout}s.") from exc


def run_integrity_audit(review_dir: pathlib.Path) -> None:
    publication_ready = review_dir / "paper" / "manuscript" / "publication-ready.md"
    compiled_submission = review_dir / "paper" / "manuscript" / "compiled-submission.md"
    manuscript_path = publication_ready if publication_ready.exists() else compiled_submission
    output_dir = review_dir / "paper" / "audit" / "integrity-audit"
    cmd = [
        sys.executable,
        str(INTEGRITY_AUDIT_SCRIPT),
        str(manuscript_path),
        "--review-dir",
        str(review_dir),
        "--output-dir",
        str(output_dir),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=STEP_TIMEOUTS["integrity_audit"])
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"integrity_audit timed out after {STEP_TIMEOUTS['integrity_audit']}s.") from exc


def write_report(review_dir: pathlib.Path, rounds: list[RoundStatus], final_note: str) -> pathlib.Path:
    report_path = review_dir / "paper" / "audit" / "publication-autopilot.md"
    lines = [
        "# Publication Autopilot",
        "",
        f"- Fecha: {datetime.now(timezone.utc).astimezone().isoformat()}",
        f"- Rondas ejecutadas: {len(rounds)}",
        f"- Resultado final: {final_note}",
        "",
        "## Historial",
    ]
    for row in rounds:
        lines.append(
            f"- Ronda {row.round_number}: gate={row.gate_status}, audit={row.audit_status}, "
            f"reviewers={row.reviewer_summary}, manuscript_hash={row.manuscript_hash}"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument("--max-rounds", type=int, default=4, help="Maximum publication rounds")
    parser.add_argument(
        "--retry-wait-seconds",
        type=int,
        default=900,
        help="Sleep between rounds when the only blocker is unresolved cloud peer review.",
    )
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory not found: {review_dir}")

    rounds: list[RoundStatus] = []
    repeated_signature_count = 0
    previous_signature: tuple[str, str, str] | None = None

    for round_number in range(1, max(args.max_rounds, 1) + 1):
        try:
            run_step("prepare_paper_figures.py", review_dir, ["--autopilot", "--force"])
            run_step("render_review_figures.py", review_dir)
            run_step("publication_audit.py", review_dir, ["--apply"])
            run_step("export_publication_latex.py", review_dir)
            run_step("publication_peer_review.py", review_dir)
            run_step("package_publication_bundle.py", review_dir)
            run_integrity_audit(review_dir)
            run_step("publication_gate.py", review_dir)
            run_step("journal_readiness_gate.py", review_dir)
            run_step("package_publication_bundle.py", review_dir)
            run_step("sync_review_to_obsidian.py", review_dir)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            write_report(review_dir, rounds, f"Bloqueo operativo en ronda {round_number}: {exc}")
            return 1

        gate_status = parse_markdown_status(review_dir / "paper" / "audit" / "publication-gate.md")
        audit_status = parse_markdown_status(review_dir / "paper" / "audit" / "publication-audit.md")
        reviewer_summary = parse_reviewer_summary(review_dir / "paper" / "review" / "review-manifest.csv")
        manuscript_sig = manuscript_hash(review_dir / "paper" / "manuscript" / "publication-ready.md")
        current_signature = (gate_status, reviewer_summary, manuscript_sig)

        rounds.append(
            RoundStatus(
                round_number=round_number,
                gate_status=gate_status,
                audit_status=audit_status,
                reviewer_summary=reviewer_summary,
                manuscript_hash=manuscript_sig,
            )
        )

        if gate_status == "PASS":
            write_report(review_dir, rounds, "PASS")
            return 0

        if current_signature == previous_signature:
            repeated_signature_count += 1
        else:
            repeated_signature_count = 0
        previous_signature = current_signature

        if gate_status == "FAIL" and "unresolved" in reviewer_summary and round_number < max(args.max_rounds, 1):
            time.sleep(max(args.retry_wait_seconds, 60))
            continue

        if repeated_signature_count >= 1:
            write_report(
                review_dir,
                rounds,
                "Bloqueo estable: la capa editorial dejó de cambiar entre rondas consecutivas.",
            )
            return 1

    write_report(review_dir, rounds, "Máximo de rondas agotado sin PASS.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
