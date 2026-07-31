#!/usr/bin/env python3
"""Refresh deep extraction fields for already-included PRISMA studies.

This helper reuses the existing complete_review extraction pipeline but limits
work to studies that are already included in full text and selected for the
final corpus. It is useful when the extraction schema becomes richer and older
reviews need denser fichas without rerunning search or screening.
"""

from __future__ import annotations

import argparse
import os
import pathlib

import complete_review as cr


def load_selected_ids(review_dir: pathlib.Path) -> list[str]:
    shortlist_rows = cr.read_csv(review_dir / "selection" / "ultraquality-shortlist.csv")
    return [
        row["record_id"]
        for row in shortlist_rows
        if str(row.get("selected_for_final_n", "")).lower() in {"yes", "si", "sí", "true", "1"}
    ]


def build_included_rows(review_dir: pathlib.Path, selected_ids: set[str]) -> list[dict[str, str]]:
    full_text_rows = cr.read_csv(review_dir / "screening" / "full-text.csv")
    master_rows = cr.read_csv(review_dir / "records" / "master-records.csv")
    master_map = {row["record_id"]: row for row in master_rows if row.get("record_id")}
    included_rows: list[dict[str, str]] = []
    for ft in full_text_rows:
        if (ft.get("decision") or "").strip() != "include_ft":
            continue
        record_id = ft.get("record_id", "")
        if selected_ids and record_id not in selected_ids:
            continue
        row = dict(master_map.get(record_id, {}))
        row.update(ft)
        pdf_path = pathlib.Path(ft.get("full_text_path", "") or "")
        txt_path = review_dir / "fulltext" / "txt" / f"{pdf_path.stem}.txt" if pdf_path.name else None
        row["full_text_text"] = txt_path.read_text(encoding="utf-8", errors="ignore") if txt_path and txt_path.exists() else ""
        included_rows.append(row)
    return included_rows


def rewrite_selected_extraction_table(review_dir: pathlib.Path, selected_ids: set[str]) -> None:
    current_rows = cr.read_csv(review_dir / "extraction" / "extraction-table.csv")
    selected_rows = [row for row in current_rows if row.get("record_id") in selected_ids]
    cr.write_csv(review_dir / "extraction" / "extraction-table.csv", cr.EXTRACTION_FIELDS, selected_rows)


def acquire_lock(lock_path: pathlib.Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


def build_heuristic_item(source_row: dict[str, str]) -> dict[str, object]:
    item = cr.fallback_extraction_item(
        source_row,
        "Extraccion heuristica reforzada desde el texto completo del PDF tras una pasada de refresco focal.",
    )
    item.setdefault("assigned_doi", source_row.get("assigned_doi", ""))
    item.setdefault("authors", source_row.get("authors", ""))
    item.setdefault("title_original", source_row.get("title_original", ""))
    item.setdefault("keywords_author", source_row.get("keywords_author", ""))
    item.setdefault("keywords_indexed", source_row.get("keywords_indexed", ""))
    item.setdefault("keywords_normalized", source_row.get("keywords_normalized", ""))
    item.setdefault("year", source_row.get("year", ""))
    cr.heuristically_enrich_extraction_item(source_row, item)
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh deep extraction fields for selected included studies.")
    parser.add_argument("review_dir", help="Path to the review workspace")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of missing studies to refresh in this run (0 = all)")
    parser.add_argument("--record-id", default="", help="Refresh only this specific record_id")
    parser.add_argument("--heuristics-only", action="store_true", help="Fill missing records using full-text heuristics only, without LLM calls")
    args = parser.parse_args()

    review_dir = pathlib.Path(args.review_dir).expanduser().resolve()
    lock_path = review_dir / "extraction" / ".refresh-extraction.lock"
    lock_fd = -1
    try:
        lock_fd = acquire_lock(lock_path)
    except FileExistsError:
        print(f"lock_active={lock_path}", flush=True)
        return 2

    context = cr.read_research_context(review_dir)
    try:
        selected_ids = load_selected_ids(review_dir)
        selected_set = set(selected_ids)
        included_rows = build_included_rows(review_dir, selected_set)
        existing_rows = cr.read_csv(review_dir / "extraction" / "extraction-table.csv")
        complete_ids = {row["record_id"] for row in existing_rows if cr.extraction_row_complete(row)}
        provisional_ids = {
            row["record_id"]
            for row in existing_rows
            if row.get("record_id")
            and (
                cr.has_fallback_extraction_marker(str(row.get("key_findings", "")))
                or cr.has_fallback_extraction_marker(str(row.get("notes", "")))
            )
        }
        missing_rows = [
            row
            for row in included_rows
            if row.get("record_id") not in complete_ids or row.get("record_id") in provisional_ids
        ]
        if args.record_id:
            missing_rows = [row for row in missing_rows if row.get("record_id") == args.record_id]
        if args.limit > 0:
            missing_rows = missing_rows[: args.limit]

        print(f"selected={len(selected_ids)} complete={len(complete_ids)} pending={len(missing_rows)}", flush=True)
        model_log: list[str] = []
        if args.heuristics_only:
            current_rows = cr.read_csv(review_dir / "extraction" / "extraction-table.csv")
            by_id = {row["record_id"]: row for row in current_rows if row.get("record_id")}
            for index, row in enumerate(missing_rows, start=1):
                print(f"[refresh-extraction-heuristic] {index}/{len(missing_rows)} {row.get('record_id', '')}", flush=True)
                by_id[row["record_id"]] = build_heuristic_item(row)
            cr.write_csv(review_dir / "extraction" / "extraction-table.csv", cr.EXTRACTION_FIELDS, [by_id[key] for key in sorted(by_id)])
        else:
            for index, row in enumerate(missing_rows, start=1):
                print(f"[refresh-extraction] {index}/{len(missing_rows)} {row.get('record_id', '')}", flush=True)
                cr.extract_included([row], review_dir, model_log, context)

        rewrite_selected_extraction_table(review_dir, selected_set)
        refreshed_rows = cr.read_csv(review_dir / "extraction" / "extraction-table.csv")
        refreshed_complete = sum(1 for row in refreshed_rows if cr.extraction_row_complete(row))
        print(f"complete_after={refreshed_complete} models_used={', '.join(model_log) if model_log else 'sin_registro'}", flush=True)
        return 0
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        if lock_path.exists():
            lock_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
