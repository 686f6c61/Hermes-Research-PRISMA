#!/usr/bin/env python3
"""Build the offline bibliometric and evidence-network atlas for a review."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from network_analysis import build_analysis  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an auditable network-analysis artifact set from a review workspace."
    )
    parser.add_argument("review_dir", type=pathlib.Path)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use only review files and cached OpenAlex metadata.",
    )
    parser.add_argument(
        "--max-openalex-requests",
        type=int,
        default=100,
        help="Maximum missing DOI records to request from OpenAlex.",
    )
    parser.add_argument(
        "--max-author-requests",
        type=int,
        default=80,
        help="Maximum included-author profiles to request from OpenAlex.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = build_analysis(
            args.review_dir,
            offline=args.offline,
            max_openalex_requests=max(0, args.max_openalex_requests),
            max_author_requests=max(0, args.max_author_requests),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"network-analysis: {error}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
