#!/usr/bin/env python3
"""Create the navigable HTML guide for one review delivery."""

from __future__ import annotations

import argparse
import json
import pathlib

from delivery_portal import build_delivery_assets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    html_path, manifest_path, manifest = build_delivery_assets(review_dir)
    print(
        json.dumps(
            {
                "status": "pass",
                "delivery_status": manifest.get("status"),
                "html": str(html_path),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
