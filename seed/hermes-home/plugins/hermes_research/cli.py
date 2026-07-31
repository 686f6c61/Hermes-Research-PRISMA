"""CLI entry points for ``hermes research``."""

from __future__ import annotations

import argparse
import sys

from .commands import _manifest_summary, _resume_review, _run_bootstrap, _show_status
from .intake import intake_template
from .runtime import prisma_scripts_dir, resolve_review_dir, run_command_capture


def register_cli(subparser: argparse.ArgumentParser) -> None:
    """Build the ``hermes research`` argparse tree."""
    subs = subparser.add_subparsers(dest="research_command")

    init_p = subs.add_parser("init", help="Create a review deterministically from intake fields")
    init_p.add_argument("--topic", required=True, help="Review topic")
    init_p.add_argument("--years", required=True, help="Year or year range, e.g. 2025-2026")
    init_p.add_argument("--include", required=True, help="Inclusion criteria")
    init_p.add_argument("--exclude", required=True, help="Exclusion criteria")
    init_p.add_argument("--question", default="", help="Optional research question")
    init_p.add_argument("--autonomous", default="sí", help="Autonomous mode flag")
    init_p.add_argument("--mode", default="", help="Optional methodological mode: biomédico, técnico, ciencias sociales, educación, management or mixto")
    init_p.add_argument("--final-n", default="37", help="Target final N")
    init_p.add_argument("--outlet", default="generic-common-core", help="Target outlet")

    status_p = subs.add_parser("status", help="Summarise the current review state")
    status_p.add_argument("review", nargs="?", default="", help="Optional review directory or name")

    resume_p = subs.add_parser("resume", help="Resume a review in the background")
    resume_p.add_argument("review", nargs="?", default="", help="Optional review directory or name")

    autopilot_p = subs.add_parser("autopilot", help="Run publication_autopilot.py on a review")
    autopilot_p.add_argument("review", help="Review directory or name")

    package_p = subs.add_parser("package", help="Create the publication bundle zip for a review")
    package_p.add_argument("review", help="Review directory or name")

    subs.add_parser("manifest", help="Show the migration summary")

    subparser.set_defaults(func=research_command)


def research_command(args: argparse.Namespace) -> int:
    """Dispatch ``hermes research`` subcommands."""
    sub = getattr(args, "research_command", None)
    if not sub:
        print("usage: hermes research {init,status,resume,autopilot,package,manifest}")
        return 2

    if sub == "init":
        payload = {
            "topic": args.topic,
            "year_or_years": args.years,
            "inclusion_criteria": args.include,
            "exclusion_criteria": args.exclude,
            "research_question": args.question,
            "autonomous_mode": args.autonomous,
            "review_mode": args.mode,
            "final_n": args.final_n,
            "target_outlet": args.outlet,
            "from_date": "",
            "to_date": "",
            "author_filters": "",
            "representativeness": "",
            "target_length": "",
        }
        print(_run_bootstrap("", "\n".join([
            f"Tema: {payload['topic']}",
            f"Año o años: {payload['year_or_years']}",
            f"Criterios de inclusión: {payload['inclusion_criteria']}",
            f"Criterios de exclusión: {payload['exclusion_criteria']}",
            f"Pregunta de investigación (opcional): {payload['research_question']}",
            f"Modo autónomo: {payload['autonomous_mode']}",
            f"Modo metodológico (opcional): {payload['review_mode']}",
            f"Límite final N: {payload['final_n']}",
            f"Revista o medio objetivo: {payload['target_outlet']}",
        ])))
        return 0

    if sub == "status":
        print(_show_status("", args.review))
        return 0

    if sub == "resume":
        print(_resume_review("", args.review))
        return 0

    if sub == "autopilot":
        review_dir = resolve_review_dir(args.review)
        if review_dir is None:
            print("No encuentro la revisión indicada.", file=sys.stderr)
            return 1
        output = run_command_capture(
            [
                "python3",
                str(prisma_scripts_dir() / "publication_autopilot.py"),
                str(review_dir),
            ],
            cwd=review_dir,
        )
        print(output.strip())
        return 0

    if sub == "package":
        review_dir = resolve_review_dir(args.review)
        if review_dir is None:
            print("No encuentro la revisión indicada.", file=sys.stderr)
            return 1
        output = run_command_capture(
            [
                "python3",
                str(prisma_scripts_dir() / "package_publication_bundle.py"),
                str(review_dir),
            ],
            cwd=review_dir,
        )
        print(output.strip())
        return 0

    if sub == "manifest":
        print(_manifest_summary())
        return 0

    print(intake_template())
    return 2
