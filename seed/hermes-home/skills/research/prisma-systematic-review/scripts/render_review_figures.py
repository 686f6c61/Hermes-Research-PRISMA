#!/usr/bin/env python3
"""Render SVG figures from a review folder into PNG assets and maintain a manifest."""

from __future__ import annotations

import argparse
import csv
import pathlib
import subprocess

MANIFEST_FIELDS = [
    "figure_id",
    "title",
    "phase",
    "paper_section",
    "figure_type",
    "purpose",
    "evidence_basis",
    "style_profile",
    "apa_caption",
    "svg_path",
    "png_path",
    "status",
    "notes",
]


def ensure_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_manifest(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    normalized: list[dict[str, str]] = []
    for row in rows:
        normalized.append({field: row.get(field, "") for field in MANIFEST_FIELDS})
    return normalized


def write_manifest(path: pathlib.Path, rows: list[dict[str, str]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def slug_from_name(name: str) -> str:
    cleaned = []
    for char in name.lower():
        cleaned.append(char if char.isalnum() else "-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "figure"


def render_svg(svg_path: pathlib.Path, png_path: pathlib.Path, width: int | None) -> None:
    ensure_dir(png_path.parent)
    cmd = ["rsvg-convert", str(svg_path), "-o", str(png_path)]
    if width:
        cmd.extend(["-w", str(width)])
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", help="Path to the review directory")
    parser.add_argument("--width", type=int, help="Optional PNG width in pixels")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    if not review_dir.exists():
        raise SystemExit(f"Review directory does not exist: {review_dir}")

    figures_dir = review_dir / "figures"
    svg_dir = figures_dir / "svg"
    png_dir = figures_dir / "png"
    manifest_path = figures_dir / "manifest.csv"

    ensure_dir(svg_dir)
    ensure_dir(png_dir)

    manifest_rows = read_manifest(manifest_path)
    existing = {row.get("figure_id", ""): row for row in manifest_rows}
    rendered = 0

    manifest_svg_paths = []
    for row in manifest_rows:
        svg_rel = (row.get("svg_path") or "").strip()
        if not svg_rel:
            continue
        svg_path = (review_dir / svg_rel).resolve()
        if svg_path.exists():
            manifest_svg_paths.append(svg_path)

    svg_targets = manifest_svg_paths or sorted(svg_dir.glob("*.svg"))

    for svg_path in svg_targets:
        figure_id = slug_from_name(svg_path.stem)
        png_path = png_dir / f"{figure_id}.png"
        render_svg(svg_path, png_path, args.width)
        rel_svg = svg_path.relative_to(review_dir).as_posix()
        rel_png = png_path.relative_to(review_dir).as_posix()
        row = existing.get(figure_id, {field: "" for field in MANIFEST_FIELDS})
        row["figure_id"] = figure_id
        row["title"] = row["title"] or svg_path.stem.replace("-", " ").replace("_", " ").title()
        row["svg_path"] = rel_svg
        row["png_path"] = rel_png
        row["status"] = "rendered"
        existing[figure_id] = row
        rendered += 1

    if manifest_rows:
        allowed_ids = {slug_from_name(path.stem) for path in svg_targets}
        existing = {
            figure_id: row
            for figure_id, row in existing.items()
            if not figure_id.startswith("fig-") or figure_id in allowed_ids
        }

    rows = [existing[key] for key in sorted(existing)]
    write_manifest(manifest_path, rows)

    print(f"manifest: {manifest_path}")
    print(f"rendered_png: {rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
