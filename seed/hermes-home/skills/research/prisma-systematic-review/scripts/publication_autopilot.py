#!/usr/bin/env python3
"""Iterate the publication layer until PASS or a stable documented blocker."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from pipeline_state import record_step, should_run

SCRIPTS = pathlib.Path(__file__).resolve().parent
RESEARCH_SKILLS = SCRIPTS.parent.parent
INTEGRITY_AUDIT_SCRIPT = RESEARCH_SKILLS / "research-integrity-audit" / "scripts" / "check_manuscript_integrity.py"
NETWORK_ANALYSIS_SCRIPT = (
    RESEARCH_SKILLS
    / "research-network-analysis"
    / "scripts"
    / "build_network_analysis.py"
)
STEP_TIMEOUTS = {
    "build_review_contracts.py": 120,
    "model_capability_probe.py": 120,
    "build_network_analysis.py": 1800,
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
    "build_evidence_ledger.py": 120,
    "build_scientific_intelligence.py": 180,
    "build_research_memory.py": 180,
    "validate_artifact_schemas.py": 120,
}


def resolved_step_timeout(script_name: str, review_dir: pathlib.Path) -> int | None:
    """Scale the publication audit to the focal corpus instead of imposing a 30-minute ceiling."""
    configured = STEP_TIMEOUTS.get(script_name)
    if script_name != "publication_audit.py":
        return configured
    explicit = (os.environ.get("HERMES_PUBLICATION_AUDIT_TIMEOUT") or "").strip()
    if explicit:
        try:
            return max(int(explicit), configured or 0)
        except ValueError:
            pass
    shortlist = review_dir / "selection" / "ultraquality-shortlist.csv"
    selected = 0
    if shortlist.is_file():
        with shortlist.open(encoding="utf-8-sig", newline="") as handle:
            selected = sum(
                1
                for row in csv.DictReader(handle)
                if (row.get("selected_for_final_n") or "").strip().lower() in {"yes", "si", "sí", "true", "1"}
            )
    per_document = max(60, int(os.environ.get("HERMES_DOCLING_DOCUMENT_TIMEOUT", "600")))
    return max(configured or 0, selected * per_document + 1800)
STEP_CONTRACTS = {
    "contracts": {
        "inputs": ["protocol/*.md", "protocol/review-mode.json"],
        "outputs": [
            "protocol/contracts-manifest.json",
            "protocol/intake.json",
            "protocol/method-contract.json",
            "protocol/synthesis-plan.json",
            "protocol/journal-profile.json",
            "protocol/deliverables-contract.json",
        ],
    },
    "model_capabilities": {
        "inputs": ["protocol/contracts-manifest.json"],
        "outputs": ["paper/audit/model-capabilities.json"],
    },
    "network_analysis": {
        "inputs": [
            "records/master-records.csv",
            "screening/*.csv",
            "extraction/extraction-table.csv",
            "searches/search-log.csv",
        ],
        "outputs": ["analysis/manifest.json", "analysis/atlas/network-atlas.html"],
    },
    "research_memory": {
        "inputs": [
            "protocol/*.json",
            "protocol/*.md",
            "searches/search-log.csv",
            "records/master-records.csv",
            "screening/*.csv",
            "extraction/extraction-table.csv",
        ],
        "outputs": [
            "notes/prior-research-context.json",
            "notes/prior-research-context.md",
        ],
    },
    "scientific_intelligence": {
        "inputs": [
            "protocol/method-contract.json",
            "extraction/extraction-table.csv",
            "selection/ultraquality-shortlist.csv",
        ],
        "outputs": [
            "analysis/scientific-intelligence.json",
            "analysis/reading-priority.csv",
            "analysis/evidence/claim-position-matrix.csv",
            "analysis/evidence/evidence-position-summary.json",
            "analysis/evidence/consensus-disagreements-open-questions.md",
        ],
    },
    "prepare_figures": {
        "inputs": [
            "protocol/method-contract.json",
            "extraction/extraction-table.csv",
            "selection/ultraquality-shortlist.csv",
            "paper/sections/*.md",
            "analysis/evidence/*",
            "analysis/reading-priority.csv",
        ],
        "outputs": ["figures/paper-figures-spec.csv", "tables/paper-tables-spec.csv"],
    },
    "render_figures": {
        "inputs": [
            "figures/paper-figures-spec.csv",
            "tables/paper-tables-spec.csv",
            "figures/svg/*.svg",
            "prisma/flow-counts.csv",
            "extraction/extraction-table.csv",
        ],
        "outputs": ["figures/manifest.csv"],
    },
    "publication_audit": {
        "inputs": [
            "protocol/*.json",
            "paper/sections/*.md",
            "extraction/extraction-table.csv",
            "selection/ultraquality-shortlist.csv",
            "figures/manifest.csv",
            "tables/*.csv",
            "analysis/evidence/*",
            "analysis/reading-priority.csv",
        ],
        "outputs": ["paper/manuscript/publication-ready.md", "paper/audit/publication-audit.md"],
    },
    "latex": {
        "inputs": [
            "paper/manuscript/publication-ready.md",
            "paper/references/*",
            "figures/png/*",
            "figures/svg/*",
        ],
        "outputs": [
            "paper/manuscript/publication-ready.tex",
            "paper/manuscript/publication-ready.pdf",
        ],
    },
    "peer_review": {
        "inputs": [
            "paper/manuscript/publication-ready.md",
            "paper/references/*",
            "paper/audit/publication-audit.md",
            "paper/review/reviewer-models.csv",
        ],
        "outputs": ["paper/review/review-manifest.csv", "paper/review/peer-review-overview.md"],
    },
    "integrity": {
        "inputs": [
            "paper/manuscript/publication-ready.md",
            "paper/references/*",
            "extraction/extraction-table.csv",
        ],
        "outputs": ["paper/audit/integrity-audit/integrity-audit.json"],
    },
    "evidence_ledger": {
        "inputs": [
            "paper/manuscript/publication-ready.md",
            "extraction/extraction-table.csv",
        ],
        "outputs": [
            "paper/audit/claim-evidence-ledger.csv",
            "paper/audit/evidence-coverage.json",
            "paper/audit/evidence-coverage.md",
        ],
    },
    "schema_validation": {
        "inputs": [
            "protocol/*.json",
            "notes/pipeline-state.json",
            "searches/*.csv",
            "records/*.csv",
            "screening/*.csv",
            "selection/*.csv",
            "extraction/*.csv",
            "figures/*.csv",
            "tables/*.csv",
            "paper/audit/evidence-coverage.json",
            "paper/audit/model-capabilities.json",
            "analysis/scientific-intelligence.json",
            "analysis/evidence/evidence-position-summary.json",
            "notes/artifact-lineage.json",
        ],
        "outputs": [
            "paper/audit/schema-validation.json",
            "paper/audit/schema-validation.md",
        ],
    },
    "package": {
        "inputs": [
            "protocol/*",
            "searches/*.csv",
            "records/*.csv",
            "screening/*.csv",
            "selection/*.csv",
            "extraction/*.csv",
            "analysis/manifest.json",
            "analysis/atlas/*",
            "analysis/data/*",
            "analysis/metrics/*",
            "analysis/evidence/*",
            "analysis/reproducibility/*",
            "analysis/reading-priority.csv",
            "analysis/scientific-intelligence.json",
            "figures/*.csv",
            "figures/png/*",
            "figures/svg/*",
            "tables/*.csv",
            "paper/manuscript/*",
            "paper/references/*",
            "paper/review/**/*.md",
            "paper/review/**/*.csv",
            "paper/audit/**/*.md",
            "paper/audit/**/*.json",
            "paper/audit/**/*.csv",
            "paper/journal-readiness/*",
        ],
        "outputs": [
            "paper/package/publication-package.zip",
            "paper/package/publication-latex-editable.zip",
            "paper/package/index.html",
            "paper/package/deliverables-manifest.json",
        ],
    },
    "publication_gate": {
        "inputs": [
            "protocol/*.json",
            "paper/manuscript/*",
            "paper/review/**/*.csv",
            "paper/audit/integrity-audit/*",
            "paper/audit/evidence-coverage.json",
            "paper/audit/schema-validation.json",
            "analysis/scientific-intelligence.json",
            "paper/package/*.zip",
            "figures/manifest.csv",
            "tables/*.csv",
        ],
        "outputs": ["paper/audit/publication-gate.md", "paper/audit/publication-gate.json"],
    },
    "journal_readiness": {
        "inputs": [
            "protocol/*",
            "searches/*.csv",
            "screening/*.csv",
            "extraction/*.csv",
            "paper/manuscript/publication-ready.md",
            "paper/audit/publication-gate.json",
        ],
        "outputs": [
            "paper/journal-readiness/journal-readiness-report.md",
            "paper/journal-readiness/journal-readiness-gate.csv",
        ],
    },
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


def parse_gate_status(review_dir: pathlib.Path, stem: str) -> str:
    """Prefer the machine-readable gate and retain Markdown compatibility."""
    json_path = review_dir / "paper" / "audit" / f"{stem}.json"
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            status = str(payload.get("status") or payload.get("overall") or "").upper()
            if status in {"PASS", "WARN", "FAIL"}:
                return status
        except (OSError, json.JSONDecodeError):
            pass
    return parse_markdown_status(review_dir / "paper" / "audit" / f"{stem}.md")


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
    timeout = resolved_step_timeout(script_name, review_dir)
    try:
        subprocess.run(
            cmd,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{script_name} timed out after {timeout}s.") from exc


def run_cached(
    review_dir: pathlib.Path,
    step_id: str,
    runner: Callable[[], None],
    *,
    force: bool = False,
) -> bool:
    """Run one content-addressed step and persist every transition."""
    contract = STEP_CONTRACTS[step_id]
    inputs = contract["inputs"]
    outputs = contract["outputs"]
    dirty, _input_hash = should_run(
        review_dir,
        step_id,
        inputs=inputs,
        outputs=outputs,
        force=force,
    )
    if not dirty:
        record_step(
            review_dir,
            step_id,
            status="skipped",
            inputs=inputs,
            outputs=outputs,
            detail="Inputs and outputs match the last completed content hash.",
        )
        return False
    record_step(
        review_dir,
        step_id,
        status="running",
        inputs=inputs,
        outputs=outputs,
    )
    try:
        runner()
    except Exception as exc:
        record_step(
            review_dir,
            step_id,
            status="failed",
            inputs=inputs,
            outputs=outputs,
            detail=str(exc),
        )
        raise
    record_step(
        review_dir,
        step_id,
        status="completed",
        inputs=inputs,
        outputs=outputs,
    )
    return True


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


def run_network_analysis(review_dir: pathlib.Path) -> None:
    try:
        subprocess.run(
            [sys.executable, str(NETWORK_ANALYSIS_SCRIPT), str(review_dir)],
            check=True,
            timeout=STEP_TIMEOUTS["build_network_analysis.py"],
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"build_network_analysis.py timed out after {STEP_TIMEOUTS['build_network_analysis.py']}s."
        ) from exc


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

    try:
        run_cached(
            review_dir,
            "contracts",
            lambda: run_step("build_review_contracts.py", review_dir),
        )
        run_cached(
            review_dir,
            "model_capabilities",
            lambda: run_step(
                "model_capability_probe.py",
                review_dir,
                [
                    "--review-dir",
                    str(review_dir),
                    "--output",
                    str(review_dir / "paper" / "audit" / "model-capabilities.json"),
                ],
            ),
        )
        run_cached(review_dir, "network_analysis", lambda: run_network_analysis(review_dir))
        run_cached(
            review_dir,
            "research_memory",
            lambda: run_step(
                "build_research_memory.py",
                review_dir,
                ["--workspace-root", str(review_dir.parent)],
            ),
            force=True,
        )
        run_cached(
            review_dir,
            "scientific_intelligence",
            lambda: run_step("build_scientific_intelligence.py", review_dir),
        )
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        write_report(review_dir, rounds, f"Bloqueo en preparación metodológica o análisis estructural: {exc}")
        return 1

    for round_number in range(1, max(args.max_rounds, 1) + 1):
        try:
            run_cached(
                review_dir,
                "prepare_figures",
                lambda: run_step("prepare_paper_figures.py", review_dir, ["--autopilot", "--force"]),
            )
            run_cached(
                review_dir,
                "render_figures",
                lambda: run_step("render_review_figures.py", review_dir),
            )
            run_cached(
                review_dir,
                "publication_audit",
                lambda: run_step("publication_audit.py", review_dir, ["--apply"]),
            )
            run_cached(
                review_dir,
                "latex",
                lambda: run_step("export_publication_latex.py", review_dir),
            )
            run_cached(
                review_dir,
                "peer_review",
                lambda: run_step("publication_peer_review.py", review_dir),
            )
            run_cached(review_dir, "integrity", lambda: run_integrity_audit(review_dir))
            run_cached(
                review_dir,
                "evidence_ledger",
                lambda: run_step("build_evidence_ledger.py", review_dir),
            )
            run_cached(
                review_dir,
                "schema_validation",
                lambda: run_step("validate_artifact_schemas.py", review_dir),
            )
            run_cached(
                review_dir,
                "package",
                lambda: run_step("package_publication_bundle.py", review_dir),
            )
            run_cached(
                review_dir,
                "publication_gate",
                lambda: run_step("publication_gate.py", review_dir),
            )
            run_cached(
                review_dir,
                "journal_readiness",
                lambda: run_step("journal_readiness_gate.py", review_dir),
            )
            run_cached(
                review_dir,
                "package",
                lambda: run_step("package_publication_bundle.py", review_dir),
            )
            run_step("sync_review_to_obsidian.py", review_dir)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            write_report(review_dir, rounds, f"Bloqueo operativo en ronda {round_number}: {exc}")
            return 1

        gate_status = parse_gate_status(review_dir, "publication-gate")
        audit_status = parse_gate_status(review_dir, "publication-audit")
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
