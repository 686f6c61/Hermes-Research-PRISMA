#!/usr/bin/env python3
"""Record a researcher-signed approval or rejection for one review."""

from __future__ import annotations

import argparse
import pathlib

from adjudication_security import create_adjudication


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    review_dir = args.review_dir.expanduser().resolve()
    if not review_dir.is_dir():
        parser.error(f"Review directory not found: {review_dir}")
    try:
        path = create_adjudication(
            review_dir,
            decision=args.decision,
            reason=args.reason,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
