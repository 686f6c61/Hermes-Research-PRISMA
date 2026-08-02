#!/usr/bin/env python3
"""Extract structured full-text evidence through an isolated Docling service.

The Hermes gateway intentionally does not install Docling or PyTorch. This
client sends one local PDF at a time to an internal Docling Serve worker and
materializes DOI-addressed Markdown, JSON, tables, figures, and audit metadata.
Any unavailable service, timeout, or malformed response is recoverable: the
calling pipeline can continue with its existing Poppler extraction path.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import html
import json
import mimetypes
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Iterable

DOCLING_MANIFEST_FIELDS = [
    "doi",
    "source_path",
    "source_sha256",
    "status",
    "duration_seconds",
    "page_count",
    "table_count",
    "figure_count",
    "markdown_path",
    "json_path",
    "docling_version",
    "confidence_grade",
    "error",
]
TABLE_EVIDENCE_FIELDS = [
    "record_id",
    "table_id",
    "source_path",
    "page_or_location",
    "extracted_table_path",
    "vision_model",
    "status",
]
FIGURE_EVIDENCE_FIELDS = [
    "record_id",
    "asset_id",
    "source_path",
    "page_or_location",
    "extracted_asset_path",
    "vision_model",
    "status",
]
DEFAULT_SERVICE_URL = "http://docling:5001"
DEFAULT_DOCUMENT_TIMEOUT = 600
DEFAULT_MAX_FILE_MB = 50


class DoclingExtractionError(RuntimeError):
    """Raised for a recoverable Docling conversion or response error."""


def is_truthy(value: str | None) -> bool:
    """Return whether a public yes/no environment value is enabled."""

    return (value or "").strip().lower() in {"1", "true", "yes", "on", "auto"}


def normalize_doi(value: str) -> str:
    """Normalize a DOI without inventing an internal identifier."""

    text = html.unescape(value or "").strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().rstrip(".,;)")
    if not (text.startswith("10.") and "/" in text):
        return ""
    normalized = text.lower()
    return re.sub(r"^(10\.48550/arxiv\..+?)v\d+$", r"\1", normalized)


def doi_file_stem(doi: str) -> str:
    """Create a readable filesystem-safe name derived only from the DOI."""

    normalized = normalize_doi(doi)
    if not normalized:
        raise ValueError("A valid DOI is required for Docling artifacts")
    prefix, suffix = normalized.split("/", 1)
    safe_suffix = re.sub(r"[^a-z0-9._()-]+", "-", suffix).strip("-")
    if not safe_suffix:
        raise ValueError("The DOI suffix cannot be converted to a safe filename")
    return f"{prefix}__{safe_suffix}"


def sha256_file(path: pathlib.Path) -> str:
    """Hash the exact source PDF used for extraction."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: pathlib.Path, review_dir: pathlib.Path) -> str:
    """Return a portable review-relative path."""

    try:
        return path.resolve().relative_to(review_dir.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def read_csv_rows(path: pathlib.Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file when it exists."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv_rows(path: pathlib.Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    """Write a stable UTF-8 CSV artifact atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def service_url() -> str:
    """Return the internal Docling endpoint without a trailing slash."""

    return (os.environ.get("DOCLING_SERVE_URL") or DEFAULT_SERVICE_URL).strip().rstrip("/")


def request_headers() -> dict[str, str]:
    """Build internal request headers without persisting credentials."""

    headers = {
        "Accept": "application/json",
        "X-Docling-Log-RequestID": f"hermes-{uuid.uuid4().hex[:16]}",
    }
    api_key = (os.environ.get("HERMES_DOCLING_API_KEY") or "").strip()
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def safe_error(exc: BaseException) -> str:
    """Return a bounded error summary with URL credentials removed."""

    message = re.sub(r"https?://[^/\s]+", "[docling-service]", str(exc))
    api_key = (os.environ.get("HERMES_DOCLING_API_KEY") or "").strip()
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return re.sub(r"\s+", " ", message).strip()[:500]


def docling_health(timeout: int = 10) -> tuple[bool, str]:
    """Check the isolated service and report its package version when available."""

    for endpoint in ("/version", "/health"):
        request = urllib.request.Request(f"{service_url()}{endpoint}", headers=request_headers())
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                versions = payload.get("versions") or payload
                if isinstance(versions, dict):
                    version = (
                        versions.get("docling-serve")
                        or versions.get("docling_serve")
                        or versions.get("docling")
                        or ""
                    )
                    return True, str(version)
            return True, ""
        except (OSError, ValueError, urllib.error.URLError):
            continue
    return False, ""


def encode_multipart(fields: list[tuple[str, str]], pdf_path: pathlib.Path) -> tuple[bytes, str]:
    """Encode one PDF and repeated form fields for Docling's file endpoint."""

    boundary = f"----HermesDocling{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")
    content_type = mimetypes.guess_type(pdf_path.name)[0] or "application/pdf"
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="files"; filename="{pdf_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
    )
    body.extend(pdf_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), boundary


def convert_pdf(pdf_path: pathlib.Path, timeout: int) -> dict[str, Any]:
    """Convert one PDF with bounded, deterministic standard-pipeline options."""

    max_file_mb = max(1, int(os.environ.get("HERMES_DOCLING_MAX_FILE_MB", DEFAULT_MAX_FILE_MB)))
    if pdf_path.stat().st_size > max_file_mb * 1024 * 1024:
        raise DoclingExtractionError(f"PDF exceeds the configured {max_file_mb} MB limit")

    fields = [
        ("from_formats", "pdf"),
        ("to_formats", "md"),
        ("to_formats", "json"),
        ("image_export_mode", "embedded"),
        ("do_ocr", "true"),
        ("force_ocr", "false"),
        ("ocr_lang", "en"),
        ("ocr_lang", "es"),
        ("pdf_backend", "docling_parse"),
        ("table_mode", "accurate"),
        ("table_cell_matching", "true"),
        ("do_table_structure", "true"),
        ("include_images", "true"),
        ("include_page_images", "false"),
        ("images_scale", "2.0"),
        ("abort_on_error", "false"),
        ("document_timeout", str(timeout)),
    ]
    body, boundary = encode_multipart(fields, pdf_path)
    headers = request_headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request = urllib.request.Request(
        f"{service_url()}/v1/convert/file",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout + 30) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise DoclingExtractionError(f"Docling HTTP {exc.code}: {detail}") from exc
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise DoclingExtractionError(safe_error(exc)) from exc
    if not isinstance(payload, dict):
        raise DoclingExtractionError("Docling returned a non-object response")
    return payload


def find_document_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Find the converted document across compatible Docling Serve responses."""

    candidates: list[Any] = [
        payload.get("document"),
        payload.get("result"),
        payload.get("documents"),
        payload.get("results"),
    ]
    for candidate in candidates:
        values = candidate if isinstance(candidate, list) else [candidate]
        for value in values:
            if isinstance(value, dict) and any(
                key in value
                for key in ("md_content", "json_content", "markdown", "document")
            ):
                nested = value.get("document")
                return nested if isinstance(nested, dict) else value
    if any(key in payload for key in ("md_content", "json_content", "markdown")):
        return payload
    raise DoclingExtractionError("Docling response does not contain a converted document")


def decode_json_content(document: dict[str, Any]) -> dict[str, Any]:
    """Decode the lossless DoclingDocument JSON output."""

    content = document.get("json_content") or document.get("json") or document.get("docling_document")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as exc:
            raise DoclingExtractionError("Docling JSON output is malformed") from exc
        if isinstance(decoded, dict):
            return decoded
    raise DoclingExtractionError("Docling response is missing JSON output")


def markdown_content(document: dict[str, Any]) -> str:
    """Return Markdown while preventing embedded images from bloating the file."""

    content = document.get("md_content") or document.get("markdown") or ""
    if not isinstance(content, str):
        return ""
    return re.sub(
        r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+",
        "embedded-image-exported-separately",
        content,
        flags=re.IGNORECASE,
    )


def page_location(item: dict[str, Any]) -> str:
    """Read a page reference from Docling provenance metadata."""

    provenance = item.get("prov")
    if isinstance(provenance, list) and provenance and isinstance(provenance[0], dict):
        raw_page = provenance[0].get("page_no")
        if isinstance(raw_page, int):
            return f"Página {raw_page}"
        if str(raw_page or "").strip():
            return f"Página {raw_page}"
    return "Página no reportada por Docling"


def cell_text(cell: Any) -> str:
    """Extract text from a Docling table cell."""

    if isinstance(cell, dict):
        return str(cell.get("text") or cell.get("content") or "").strip()
    return str(cell or "").strip()


def table_grid(table: dict[str, Any]) -> list[list[str]]:
    """Convert a Docling table structure into a rectangular text grid."""

    data = table.get("data")
    if not isinstance(data, dict):
        return []
    grid = data.get("grid")
    if isinstance(grid, list):
        rows = [[cell_text(cell) for cell in row] for row in grid if isinstance(row, list)]
        return [row for row in rows if any(cell for cell in row)]

    cells = data.get("table_cells")
    if not isinstance(cells, list):
        return []
    max_row = -1
    max_col = -1
    parsed: list[tuple[int, int, str]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        try:
            row = int(cell.get("start_row_offset_idx", cell.get("row", 0)))
            col = int(cell.get("start_col_offset_idx", cell.get("col", 0)))
        except (TypeError, ValueError):
            continue
        parsed.append((row, col, cell_text(cell)))
        max_row = max(max_row, row)
        max_col = max(max_col, col)
    if max_row < 0 or max_col < 0:
        return []
    grid = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
    for row, col, text in parsed:
        grid[row][col] = text
    return [row for row in grid if any(cell for cell in row)]


def write_table_assets(
    review_dir: pathlib.Path,
    doi: str,
    source_path: pathlib.Path,
    doc_json: dict[str, Any],
) -> list[dict[str, str]]:
    """Export source tables to CSV and HTML with DOI/page provenance."""

    output_dir = review_dir / "tables" / "source"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = doi_file_stem(doi)
    evidence_rows: list[dict[str, str]] = []
    tables = doc_json.get("tables")
    if not isinstance(tables, list):
        return evidence_rows
    for index, table in enumerate(tables, start=1):
        if not isinstance(table, dict):
            continue
        grid = table_grid(table)
        if not grid:
            continue
        csv_path = output_dir / f"{stem}-table-{index:02d}.csv"
        html_path = output_dir / f"{stem}-table-{index:02d}.html"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(grid)
        html_rows = "\n".join(
            "  <tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
            for row in grid
        )
        html_path.write_text(
            "<!doctype html>\n<meta charset=\"utf-8\">\n"
            f"<title>Tabla fuente {html.escape(doi)} {index}</title>\n"
            f"<table>\n{html_rows}\n</table>\n",
            encoding="utf-8",
        )
        evidence_rows.append(
            {
                "record_id": doi,
                "table_id": f"{doi}-table-{index:02d}",
                "source_path": str(source_path),
                "page_or_location": page_location(table),
                "extracted_table_path": relative_path(csv_path, review_dir),
                "vision_model": "",
                "status": "extracted_from_pdf_by_docling",
            }
        )
    return evidence_rows


def embedded_image(item: dict[str, Any]) -> tuple[bytes, str] | None:
    """Decode an embedded Docling picture image."""

    image = item.get("image")
    if not isinstance(image, dict):
        return None
    uri = image.get("uri")
    if not isinstance(uri, str):
        return None
    match = re.match(r"data:image/([a-z0-9.+-]+);base64,(.+)", uri, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    extension = {
        "jpeg": "jpg",
        "svg+xml": "svg",
    }.get(match.group(1).lower(), match.group(1).lower())
    try:
        return base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True), extension
    except (ValueError, binascii.Error):
        return None


def write_figure_assets(
    review_dir: pathlib.Path,
    doi: str,
    source_path: pathlib.Path,
    doc_json: dict[str, Any],
) -> list[dict[str, str]]:
    """Export non-page source pictures with DOI/page provenance."""

    output_dir = review_dir / "figures" / "source"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = doi_file_stem(doi)
    evidence_rows: list[dict[str, str]] = []
    pictures = doc_json.get("pictures")
    if not isinstance(pictures, list):
        return evidence_rows
    for index, picture in enumerate(pictures, start=1):
        if not isinstance(picture, dict):
            continue
        decoded = embedded_image(picture)
        if decoded is None:
            continue
        image_bytes, extension = decoded
        if len(image_bytes) < 4096:
            continue
        image_path = output_dir / f"{stem}-figure-{index:02d}.{extension}"
        image_path.write_bytes(image_bytes)
        evidence_rows.append(
            {
                "record_id": doi,
                "asset_id": f"{doi}-figure-{index:02d}",
                "source_path": str(source_path),
                "page_or_location": page_location(picture),
                "extracted_asset_path": relative_path(image_path, review_dir),
                "vision_model": "",
                "status": "extracted_from_pdf_by_docling",
            }
        )
    return evidence_rows


def confidence_grade(payload: dict[str, Any], document: dict[str, Any]) -> str:
    """Read an optional aggregate confidence grade without inventing one."""

    candidates = [
        document.get("confidence"),
        document.get("confidence_grade"),
        payload.get("confidence"),
        payload.get("confidence_grade"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("mean_grade", "grade", "label"):
                if str(candidate.get(key) or "").strip():
                    return str(candidate[key])
        elif str(candidate or "").strip():
            return str(candidate)
    return ""


def page_count(doc_json: dict[str, Any]) -> int:
    """Count structured pages from a DoclingDocument."""

    pages = doc_json.get("pages")
    if isinstance(pages, (list, dict)):
        return len(pages)
    return 0


def clear_source_assets(review_dir: pathlib.Path, doi: str) -> None:
    """Remove prior table and figure exports for one DOI before regeneration."""

    stem = doi_file_stem(doi)
    for directory, pattern in (
        (review_dir / "tables" / "source", f"{stem}-table-*"),
        (review_dir / "figures" / "source", f"{stem}-figure-*"),
    ):
        if not directory.exists():
            continue
        for path in directory.glob(pattern):
            if path.is_file():
                path.unlink()


def process_pdf(
    review_dir: pathlib.Path,
    pdf_path: pathlib.Path,
    doi: str,
    *,
    docling_version: str = "",
    force: bool = False,
) -> tuple[dict[str, str], list[dict[str, str]], list[dict[str, str]]]:
    """Process one DOI/PDF pair and return manifest, table, and figure rows."""

    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        raise DoclingExtractionError("Docling extraction requires a valid DOI")
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        raise DoclingExtractionError("The source PDF does not exist")

    output_dir = review_dir / "fulltext" / "docling"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = doi_file_stem(normalized_doi)
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    source_hash = sha256_file(pdf_path)
    existing = {
        row.get("doi", ""): row
        for row in read_csv_rows(output_dir / "manifest.csv")
        if row.get("doi")
    }.get(normalized_doi)
    if (
        not force
        and existing
        and existing.get("status") == "success"
        and existing.get("source_sha256") == source_hash
        and markdown_path.exists()
        and json_path.exists()
    ):
        doc_json = json.loads(json_path.read_text(encoding="utf-8"))
        clear_source_assets(review_dir, normalized_doi)
        table_rows = write_table_assets(review_dir, normalized_doi, pdf_path, doc_json)
        figure_rows = write_figure_assets(review_dir, normalized_doi, pdf_path, doc_json)
        return existing, table_rows, figure_rows

    # A changed source must never inherit structured evidence from an older
    # PDF version, especially if the replacement conversion later fails.
    clear_source_assets(review_dir, normalized_doi)
    markdown_path.unlink(missing_ok=True)
    json_path.unlink(missing_ok=True)
    started = time.monotonic()
    timeout = max(30, int(os.environ.get("HERMES_DOCLING_DOCUMENT_TIMEOUT", DEFAULT_DOCUMENT_TIMEOUT)))
    try:
        payload = convert_pdf(pdf_path, timeout)
        document = find_document_payload(payload)
        doc_json = decode_json_content(document)
        markdown = markdown_content(document)
        json_path.write_text(json.dumps(doc_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        table_rows = write_table_assets(review_dir, normalized_doi, pdf_path, doc_json)
        figure_rows = write_figure_assets(review_dir, normalized_doi, pdf_path, doc_json)
        row = {
            "doi": normalized_doi,
            "source_path": str(pdf_path),
            "source_sha256": source_hash,
            "status": "success",
            "duration_seconds": f"{time.monotonic() - started:.2f}",
            "page_count": str(page_count(doc_json)),
            "table_count": str(len(table_rows)),
            "figure_count": str(len(figure_rows)),
            "markdown_path": relative_path(markdown_path, review_dir),
            "json_path": relative_path(json_path, review_dir),
            "docling_version": docling_version,
            "confidence_grade": confidence_grade(payload, document),
            "error": "",
        }
        return row, table_rows, figure_rows
    except Exception as exc:
        row = {
            "doi": normalized_doi,
            "source_path": str(pdf_path),
            "source_sha256": source_hash,
            "status": "failed_fallback_poppler",
            "duration_seconds": f"{time.monotonic() - started:.2f}",
            "page_count": "0",
            "table_count": "0",
            "figure_count": "0",
            "markdown_path": "",
            "json_path": "",
            "docling_version": docling_version,
            "confidence_grade": "",
            "error": safe_error(exc),
        }
        return row, [], []


def extract_review_documents(
    review_dir: pathlib.Path,
    selected_rows: list[dict[str, str]],
    *,
    force: bool = False,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Enhance focal PDF evidence and preserve all prior successful rows."""

    if not is_truthy(os.environ.get("HERMES_DOCLING_ENABLED", "auto")):
        return [], []
    output_dir = review_dir / "fulltext" / "docling"
    output_dir.mkdir(parents=True, exist_ok=True)
    healthy, version = docling_health()
    if not healthy:
        (output_dir / "status.json").write_text(
            json.dumps(
                {
                    "status": "unavailable_fallback_poppler",
                    "checked_at_epoch": int(time.time()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return [], []

    prior_rows = read_csv_rows(output_dir / "manifest.csv")
    merged = {normalize_doi(row.get("doi", "")): row for row in prior_rows if normalize_doi(row.get("doi", ""))}
    table_rows = read_csv_rows(output_dir / "table-evidence.csv")
    figure_rows = read_csv_rows(output_dir / "figure-evidence.csv")

    # Recover successful DOI-addressed conversions left by an older interrupted
    # run. The source hash prevents a stale cache from being accepted when its
    # PDF has changed.
    for source in selected_rows:
        doi = normalize_doi(source.get("assigned_doi") or source.get("doi") or "")
        source_path = pathlib.Path(source.get("full_text_path") or "")
        if doi in merged or not doi or not source_path.is_file():
            continue
        stem = doi_file_stem(doi)
        markdown_path = output_dir / f"{stem}.md"
        json_path = output_dir / f"{stem}.json"
        if not markdown_path.is_file() or not json_path.is_file():
            continue
        try:
            doc_json = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc_json, dict) or not markdown.strip():
            continue
        merged[doi] = {
            "doi": doi,
            "source_path": str(source_path),
            "source_sha256": sha256_file(source_path),
            "status": "success",
            "duration_seconds": "0.00",
            "page_count": str(page_count(doc_json)),
            "table_count": "",
            "figure_count": "",
            "markdown_path": relative_path(markdown_path, review_dir),
            "json_path": relative_path(json_path, review_dir),
            "docling_version": version,
            "confidence_grade": "recovered_checkpoint",
            "error": "",
        }
    write_csv_rows(
        output_dir / "manifest.csv",
        DOCLING_MANIFEST_FIELDS,
        [merged[key] for key in sorted(merged)],
    )
    raw_limit = (os.environ.get("HERMES_DOCLING_DOCUMENT_LIMIT") or "0").strip()
    try:
        limit = max(0, int(raw_limit))
    except ValueError:
        limit = 0
    processed = 0
    for source in selected_rows:
        doi = normalize_doi(source.get("assigned_doi") or source.get("doi") or "")
        source_path = pathlib.Path(source.get("full_text_path") or "")
        if not doi or not source_path.exists() or source_path.suffix.lower() != ".pdf":
            continue
        if limit and processed >= limit:
            break
        existing = merged.get(doi, {})
        stem = doi_file_stem(doi)
        # Prefer the paths recorded by the successful conversion. An arXiv
        # source can retain a version suffix (v1/v3) while the focal record uses
        # its canonical DOI; deriving the filenames again would miss a valid
        # cache and needlessly reconvert the same PDF.
        markdown_path = (
            review_dir / existing["markdown_path"]
            if existing.get("markdown_path")
            else output_dir / f"{stem}.md"
        )
        json_path = (
            review_dir / existing["json_path"]
            if existing.get("json_path")
            else output_dir / f"{stem}.json"
        )
        cached_tables = [
            row for row in table_rows if normalize_doi(row.get("record_id", "")) == doi
        ]
        cached_figures = [
            row for row in figure_rows if normalize_doi(row.get("record_id", "")) == doi
        ]

        def cached_assets_exist(
            rows: list[dict[str, str]],
            path_field: str,
            expected_count: int,
        ) -> bool:
            if expected_count > len(rows):
                return False
            return all(
                (review_dir / row.get(path_field, "")).is_file()
                for row in rows
                if row.get(path_field)
            )

        try:
            expected_tables = max(0, int(existing.get("table_count") or 0))
            expected_figures = max(0, int(existing.get("figure_count") or 0))
        except (TypeError, ValueError):
            expected_tables = 0
            expected_figures = 0
        source_hash = sha256_file(source_path)
        if (
            not force
            and existing.get("status") == "success"
            and existing.get("source_sha256") == source_hash
            and markdown_path.is_file()
            and json_path.is_file()
            and cached_assets_exist(
                cached_tables,
                "extracted_table_path",
                expected_tables,
            )
            and cached_assets_exist(
                cached_figures,
                "extracted_asset_path",
                expected_figures,
            )
        ):
            processed += 1
            continue
        manifest_row, extracted_tables, extracted_figures = process_pdf(
            review_dir,
            source_path,
            doi,
            docling_version=version,
            force=force,
        )
        merged[doi] = manifest_row
        table_rows = [
            row for row in table_rows if normalize_doi(row.get("record_id", "")) != doi
        ]
        figure_rows = [
            row for row in figure_rows if normalize_doi(row.get("record_id", "")) != doi
        ]
        table_rows.extend(extracted_tables)
        figure_rows.extend(extracted_figures)
        processed += 1
        # Persist after every DOI so a timeout or restart resumes from the next
        # document instead of repeating hours of structured extraction.
        write_csv_rows(
            output_dir / "manifest.csv",
            DOCLING_MANIFEST_FIELDS,
            [merged[key] for key in sorted(merged)],
        )
        write_csv_rows(output_dir / "table-evidence.csv", TABLE_EVIDENCE_FIELDS, table_rows)
        write_csv_rows(output_dir / "figure-evidence.csv", FIGURE_EVIDENCE_FIELDS, figure_rows)

    write_csv_rows(
        output_dir / "manifest.csv",
        DOCLING_MANIFEST_FIELDS,
        [merged[key] for key in sorted(merged)],
    )
    write_csv_rows(output_dir / "table-evidence.csv", TABLE_EVIDENCE_FIELDS, table_rows)
    write_csv_rows(output_dir / "figure-evidence.csv", FIGURE_EVIDENCE_FIELDS, figure_rows)
    (output_dir / "status.json").write_text(
        json.dumps(
            {
                "status": "available",
                "docling_version": version,
                "documents_considered": processed,
                "tables_exported": len(table_rows),
                "figures_exported": len(figure_rows),
                "checked_at_epoch": int(time.time()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return table_rows, figure_rows


def parse_args() -> argparse.Namespace:
    """Parse the focused CLI used by tests and manual diagnostics."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    parser.add_argument("--pdf", type=pathlib.Path, required=True)
    parser.add_argument("--doi", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Convert one explicitly selected DOI/PDF pair."""

    args = parse_args()
    healthy, version = docling_health()
    if not healthy:
        print("Docling is unavailable; Poppler fallback remains active.")
        return 2
    manifest_row, table_rows, figure_rows = process_pdf(
        args.review_dir.resolve(),
        args.pdf.resolve(),
        args.doi,
        docling_version=version,
        force=args.force,
    )
    manifest_path = args.review_dir.resolve() / "fulltext" / "docling" / "manifest.csv"
    existing = {
        normalize_doi(row.get("doi", "")): row
        for row in read_csv_rows(manifest_path)
        if normalize_doi(row.get("doi", ""))
    }
    existing[manifest_row["doi"]] = manifest_row
    write_csv_rows(manifest_path, DOCLING_MANIFEST_FIELDS, existing.values())
    print(json.dumps({"manifest": manifest_row, "tables": table_rows, "figures": figure_rows}, ensure_ascii=False))
    return 0 if manifest_row["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
