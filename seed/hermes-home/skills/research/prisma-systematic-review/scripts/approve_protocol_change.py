#!/usr/bin/env python3
"""Approve the exact protocol change currently pending for a review."""

from __future__ import annotations

import argparse
import pathlib

from protocol_change_control import create_change_approval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        path = create_change_approval(
            args.review_dir.expanduser().resolve(),
            reason=args.reason,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
