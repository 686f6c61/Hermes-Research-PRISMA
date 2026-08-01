#!/usr/bin/env python3
"""Record a signed researcher decision for one disputed DOI."""

from __future__ import annotations

import argparse
import json
import pathlib

from screening_disagreement import record_resolution, resolution_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    parser.add_argument("--list", action="store_true", help="Print the current cases as JSON")
    parser.add_argument("--doi")
    parser.add_argument("--decision", choices=["include", "exclude"])
    parser.add_argument("--reason")
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    if args.list:
        print(json.dumps(resolution_status(review_dir), ensure_ascii=False, indent=2))
        return 0
    if not args.doi or not args.decision or not (args.reason or "").strip():
        parser.error("--doi, --decision and --reason are required unless --list is used")
    path = record_resolution(
        review_dir,
        doi=args.doi,
        decision=args.decision,
        reason=args.reason,
    )
    print(
        json.dumps(
            {
                "resolution_path": str(path),
                **resolution_status(review_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
