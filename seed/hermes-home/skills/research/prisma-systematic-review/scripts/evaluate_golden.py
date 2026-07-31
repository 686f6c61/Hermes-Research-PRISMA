#!/usr/bin/env python3
"""Evaluate screening, extraction, and evidence localization against gold labels."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import struct
import unicodedata
import zlib
from datetime import datetime, timezone

from artifact_contracts import write_json_atomic

ERROR_FIELDS = ["task", "doi", "field_or_claim", "gold", "predicted", "error_type"]
GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "T": ("111", "010", "010", "010", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "F": ("111", "100", "110", "100", "100"),
    "N": ("101", "111", "111", "111", "101"),
    " ": ("000", "000", "000", "000", "000"),
}


def normalize(value: object) -> str:
    """Normalize labels and extracted values for reproducible comparison."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.strip().lower())


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    """Read a gold CSV or return an empty collection."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_predictions(path: pathlib.Path) -> list[dict[str, object]]:
    """Read one JSON object per line and reject malformed evaluation input."""
    rows: list[dict[str, object]] = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError(f"Prediction line {line_number} is not an object")
        rows.append(parsed)
    return rows


def safe_div(numerator: int, denominator: int) -> float:
    """Avoid undefined metrics while preserving a perfect empty-case score."""
    return numerator / denominator if denominator else 1.0


def prediction_index(rows: list[dict[str, object]], task: str) -> dict[tuple[str, str], dict[str, object]]:
    """Index task predictions by DOI and optional field/claim identifier."""
    indexed: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        if normalize(row.get("task")) != task:
            continue
        doi = normalize(row.get("doi"))
        key = normalize(row.get("field") or row.get("claim_id"))
        indexed[(doi, key)] = row
    return indexed


def evaluate_screening(
    gold_rows: list[dict[str, str]],
    predictions: list[dict[str, object]],
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Compute include-vs-not-include classification metrics."""
    pred = prediction_index(predictions, "screening")
    tp = fp = fn = tn = 0
    errors: list[dict[str, str]] = []
    for row in gold_rows:
        doi = normalize(row.get("doi"))
        expected = normalize(row.get("gold_decision"))
        actual_row = pred.get((doi, ""), {})
        actual = normalize(actual_row.get("decision"))
        gold_positive = expected == "include"
        predicted_positive = actual == "include"
        if gold_positive and predicted_positive:
            tp += 1
        elif not gold_positive and predicted_positive:
            fp += 1
        elif gold_positive:
            fn += 1
        else:
            tn += 1
        if expected != actual:
            errors.append(
                {
                    "task": "screening",
                    "doi": row.get("doi", ""),
                    "field_or_claim": "decision",
                    "gold": expected,
                    "predicted": actual or "missing",
                    "error_type": "false_negative" if gold_positive else "false_positive_or_label_mismatch",
                }
            )
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    metrics = {
        "n": len(gold_rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(safe_div(2 * precision * recall, precision + recall), 4),
        "specificity": round(safe_div(tn, tn + fp), 4),
    }
    return metrics, errors


def evaluate_extraction(
    gold_rows: list[dict[str, str]],
    predictions: list[dict[str, object]],
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Measure normalized exact agreement for every gold extraction cell."""
    pred = prediction_index(predictions, "extraction")
    correct = 0
    errors: list[dict[str, str]] = []
    field_totals: dict[str, list[int]] = {}
    for row in gold_rows:
        doi = normalize(row.get("doi"))
        field = normalize(row.get("field"))
        expected = normalize(row.get("gold_value"))
        actual_row = pred.get((doi, field), {})
        actual = normalize(actual_row.get("value"))
        matched = expected == actual
        correct += int(matched)
        totals = field_totals.setdefault(field or "unknown", [0, 0])
        totals[1] += 1
        totals[0] += int(matched)
        if not matched:
            errors.append(
                {
                    "task": "extraction",
                    "doi": row.get("doi", ""),
                    "field_or_claim": row.get("field", ""),
                    "gold": row.get("gold_value", ""),
                    "predicted": str(actual_row.get("value") or "missing"),
                    "error_type": "value_mismatch",
                }
            )
    return (
        {
            "n": len(gold_rows),
            "correct": correct,
            "accuracy": round(safe_div(correct, len(gold_rows)), 4),
            "by_field": {
                field: {"correct": values[0], "n": values[1], "accuracy": round(safe_div(*values), 4)}
                for field, values in sorted(field_totals.items())
            },
        },
        errors,
    )


def evaluate_evidence(
    gold_rows: list[dict[str, str]],
    predictions: list[dict[str, object]],
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Verify page and snippet localization for gold evidence anchors."""
    pred = prediction_index(predictions, "evidence")
    located = 0
    errors: list[dict[str, str]] = []
    for row in gold_rows:
        doi = normalize(row.get("doi"))
        claim_id = normalize(row.get("claim_id"))
        actual_row = pred.get((doi, claim_id), {})
        expected_page = normalize(row.get("gold_page"))
        expected_snippet = normalize(row.get("gold_snippet"))
        actual_page = normalize(actual_row.get("page"))
        actual_snippet = normalize(actual_row.get("snippet"))
        page_ok = not expected_page or expected_page == actual_page
        snippet_ok = not expected_snippet or expected_snippet in actual_snippet or actual_snippet in expected_snippet
        matched = bool(actual_row) and page_ok and snippet_ok
        located += int(matched)
        if not matched:
            errors.append(
                {
                    "task": "evidence",
                    "doi": row.get("doi", ""),
                    "field_or_claim": row.get("claim_id", ""),
                    "gold": f"page={row.get('gold_page', '')}; snippet={row.get('gold_snippet', '')}",
                    "predicted": (
                        f"page={actual_row.get('page', 'missing')}; "
                        f"snippet={actual_row.get('snippet', 'missing')}"
                    ),
                    "error_type": "evidence_not_located",
                }
            )
    return (
        {
            "n": len(gold_rows),
            "located": located,
            "location_accuracy": round(safe_div(located, len(gold_rows)), 4),
        },
        errors,
    )


def _set_pixel(canvas: bytearray, width: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if x < 0 or y < 0 or x >= width:
        return
    offset = (y * width + x) * 3
    if offset < 0 or offset + 2 >= len(canvas):
        return
    canvas[offset : offset + 3] = bytes(color)


def _rectangle(
    canvas: bytearray,
    width: int,
    height: int,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    border: tuple[int, int, int] = (17, 17, 17),
) -> None:
    left, top, right, bottom = box
    for y in range(max(0, top), min(height, bottom)):
        for x in range(max(0, left), min(width, right)):
            color = border if x in {left, right - 1} or y in {top, bottom - 1} else fill
            _set_pixel(canvas, width, x, y, color)


def _draw_text(
    canvas: bytearray,
    width: int,
    x: int,
    y: int,
    text: str,
    *,
    scale: int = 7,
    color: tuple[int, int, int] = (17, 17, 17),
) -> None:
    cursor = x
    for char in text:
        glyph = GLYPHS.get(char, GLYPHS[" "])
        for row_index, row in enumerate(glyph):
            for column_index, value in enumerate(row):
                if value != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        _set_pixel(
                            canvas,
                            width,
                            cursor + column_index * scale + dx,
                            y + row_index * scale + dy,
                            color,
                        )
        cursor += 4 * scale


def write_confusion_png(path: pathlib.Path, metrics: dict[str, object]) -> pathlib.Path:
    """Write a portable confusion-matrix PNG without a plotting dependency."""
    width, height = 720, 520
    canvas = bytearray([246, 242, 235] * width * height)
    cells = [
        ((40, 40, 350, 250), (207, 230, 201), f"TP {metrics['tp']}"),
        ((370, 40, 680, 250), (244, 205, 196), f"FP {metrics['fp']}"),
        ((40, 270, 350, 480), (244, 225, 155), f"FN {metrics['fn']}"),
        ((370, 270, 680, 480), (205, 215, 235), f"TN {metrics['tn']}"),
    ]
    for box, fill, label in cells:
        _rectangle(canvas, width, height, box, fill)
        _draw_text(canvas, width, box[0] + 55, box[1] + 75, label, scale=10)
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(canvas[y * stride : (y + 1) * stride])
    signature = b"\x89PNG\r\n\x1a\n"

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = signature
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def evaluate(
    gold_dir: pathlib.Path,
    predictions_path: pathlib.Path,
    output_dir: pathlib.Path,
    *,
    recall_threshold: float,
    precision_threshold: float,
    extraction_threshold: float,
    evidence_threshold: float,
) -> dict[str, object]:
    """Run every evaluation task and materialize a regression report."""
    predictions = read_predictions(predictions_path)
    screening, screening_errors = evaluate_screening(read_csv(gold_dir / "gold-records.csv"), predictions)
    extraction, extraction_errors = evaluate_extraction(read_csv(gold_dir / "gold-extraction.csv"), predictions)
    evidence, evidence_errors = evaluate_evidence(read_csv(gold_dir / "gold-evidence.csv"), predictions)
    errors = [*screening_errors, *extraction_errors, *evidence_errors]
    checks = {
        "screening_recall": screening["recall"] >= recall_threshold,
        "screening_precision": screening["precision"] >= precision_threshold,
        "extraction_accuracy": extraction["accuracy"] >= extraction_threshold,
        "evidence_location_accuracy": evidence["location_accuracy"] >= evidence_threshold,
    }
    metrics: dict[str, object] = {
        "schema_version": "hermes.golden-evaluation/v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "gold_dir": str(gold_dir),
        "screening": screening,
        "extraction": extraction,
        "evidence": evidence,
        "thresholds": {
            "screening_recall": recall_threshold,
            "screening_precision": precision_threshold,
            "extraction_accuracy": extraction_threshold,
            "evidence_location_accuracy": evidence_threshold,
        },
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_dir / "metrics.json", metrics)
    with (output_dir / "error-analysis.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ERROR_FIELDS)
        writer.writeheader()
        writer.writerows(errors)
    write_confusion_png(output_dir / "screening-confusion-matrix.png", screening)
    report = [
        "# Golden evaluation report",
        "",
        f"- Status: **{str(metrics['status']).upper()}**",
        f"- Screening recall: {float(screening['recall']):.1%}",
        f"- Screening precision: {float(screening['precision']):.1%}",
        f"- Screening F1: {float(screening['f1']):.1%}",
        f"- Extraction accuracy: {float(extraction['accuracy']):.1%}",
        f"- Evidence localization accuracy: {float(evidence['location_accuracy']):.1%}",
        f"- Errors retained for analysis: {len(errors)}",
        "",
        "This evaluation measures the research system against human-approved labels. "
        "It does not evaluate whether a manuscript merely sounds plausible.",
    ]
    (output_dir / "evaluation-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gold_dir", type=pathlib.Path)
    parser.add_argument("predictions", type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--screening-recall", type=float, default=0.95)
    parser.add_argument("--screening-precision", type=float, default=0.80)
    parser.add_argument("--extraction-accuracy", type=float, default=0.85)
    parser.add_argument("--evidence-accuracy", type=float, default=0.95)
    args = parser.parse_args()
    metrics = evaluate(
        args.gold_dir.expanduser().resolve(),
        args.predictions.expanduser().resolve(),
        args.output_dir.expanduser().resolve(),
        recall_threshold=args.screening_recall,
        precision_threshold=args.screening_precision,
        extraction_threshold=args.extraction_accuracy,
        evidence_threshold=args.evidence_accuracy,
    )
    print(json.dumps({"status": metrics["status"], "output": str(args.output_dir)}, ensure_ascii=False))
    return 0 if metrics["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
