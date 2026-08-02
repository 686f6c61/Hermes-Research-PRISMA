import base64
import csv
import json
import pathlib
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import docling_extract
import publication_audit


def sample_response() -> dict:
    image_bytes = b"\x89PNG\r\n\x1a\n" + (b"x" * 5000)
    image_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    document = {
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
        "tables": [
            {
                "prov": [{"page_no": 2}],
                "data": {
                    "grid": [
                        [{"text": "Method"}, {"text": "Result"}],
                        [{"text": "Experiment"}, {"text": "Improved"}],
                    ]
                },
            }
        ],
        "pictures": [
            {
                "prov": [{"page_no": 3}],
                "image": {"uri": image_uri},
            }
        ],
    }
    return {
        "document": {
            "md_content": "# Paper\n\nEvidence.",
            "json_content": json.dumps(document),
        }
    }


def test_doi_file_stem_is_doi_only():
    assert docling_extract.normalize_doi("https://doi.org/10.1234/ABC.5") == "10.1234/abc.5"
    assert (
        docling_extract.normalize_doi("https://doi.org/10.48550/arXiv.2512.06716v2")
        == "10.48550/arxiv.2512.06716"
    )
    assert docling_extract.doi_file_stem("10.1234/ABC.5") == "10.1234__abc.5"


def test_process_pdf_exports_structured_assets(tmp_path, monkeypatch):
    review_dir = tmp_path / "review"
    pdf_path = review_dir / "fulltext" / "pdf" / "source.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.7\nfixture")
    monkeypatch.setattr(docling_extract, "convert_pdf", lambda _path, _timeout: sample_response())

    manifest, tables, figures = docling_extract.process_pdf(
        review_dir,
        pdf_path,
        "10.1234/ABC.5",
        docling_version="1.29.0",
    )

    assert manifest["status"] == "success"
    assert manifest["doi"] == "10.1234/abc.5"
    assert manifest["table_count"] == "1"
    assert manifest["figure_count"] == "1"
    assert tables[0]["record_id"] == "10.1234/abc.5"
    assert tables[0]["page_or_location"] == "Página 2"
    assert figures[0]["page_or_location"] == "Página 3"

    table_path = review_dir / tables[0]["extracted_table_path"]
    with table_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [["Method", "Result"], ["Experiment", "Improved"]]
    assert "..." not in table_path.read_text(encoding="utf-8")


def test_process_pdf_falls_back_without_leaking_api_key(tmp_path, monkeypatch):
    review_dir = tmp_path / "review"
    pdf_path = review_dir / "fulltext" / "pdf" / "source.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.7\nfixture")
    stale_table = review_dir / "tables" / "source" / "10.1234__failure-table-01.csv"
    stale_figure = review_dir / "figures" / "source" / "10.1234__failure-figure-01.png"
    stale_markdown = review_dir / "fulltext" / "docling" / "10.1234__failure.md"
    stale_json = review_dir / "fulltext" / "docling" / "10.1234__failure.json"
    for stale_path in (stale_table, stale_figure, stale_markdown, stale_json):
        stale_path.parent.mkdir(parents=True, exist_ok=True)
        stale_path.write_text("stale", encoding="utf-8")
    monkeypatch.setenv("HERMES_DOCLING_API_KEY", "private-docling-key")

    def fail_conversion(_path, _timeout):
        raise RuntimeError("private-docling-key failed at http://docling:5001")

    monkeypatch.setattr(docling_extract, "convert_pdf", fail_conversion)
    manifest, tables, figures = docling_extract.process_pdf(
        review_dir,
        pdf_path,
        "10.1234/failure",
    )

    assert manifest["status"] == "failed_fallback_poppler"
    assert "private-docling-key" not in manifest["error"]
    assert "http://docling:5001" not in manifest["error"]
    assert tables == []
    assert figures == []
    assert not stale_table.exists()
    assert not stale_figure.exists()
    assert not stale_markdown.exists()
    assert not stale_json.exists()


def test_review_extraction_checkpoints_each_completed_doi(tmp_path, monkeypatch):
    review_dir = tmp_path / "review"
    first_pdf = review_dir / "fulltext/pdf/first.pdf"
    second_pdf = review_dir / "fulltext/pdf/second.pdf"
    first_pdf.parent.mkdir(parents=True)
    first_pdf.write_bytes(b"%PDF-1.7\nfirst")
    second_pdf.write_bytes(b"%PDF-1.7\nsecond")
    monkeypatch.setattr(docling_extract, "docling_health", lambda: (True, "test"))
    calls = 0

    def interrupted_process(_review, source_path, doi, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated interruption")
        return (
            {
                "doi": doi,
                "source_path": str(source_path),
                "source_sha256": docling_extract.sha256_file(source_path),
                "status": "success",
                "duration_seconds": "1.00",
                "page_count": "1",
                "table_count": "0",
                "figure_count": "0",
                "markdown_path": f"fulltext/docling/{docling_extract.doi_file_stem(doi)}.md",
                "json_path": f"fulltext/docling/{docling_extract.doi_file_stem(doi)}.json",
                "docling_version": "test",
                "confidence_grade": "test",
                "error": "",
            },
            [],
            [],
        )

    monkeypatch.setattr(docling_extract, "process_pdf", interrupted_process)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        docling_extract.extract_review_documents(
            review_dir,
            [
                {"assigned_doi": "10.1000/first", "full_text_path": str(first_pdf)},
                {"assigned_doi": "10.1000/second", "full_text_path": str(second_pdf)},
            ],
        )

    manifest = docling_extract.read_csv_rows(review_dir / "fulltext/docling/manifest.csv")
    assert [row["doi"] for row in manifest] == ["10.1000/first"]


def test_review_extraction_reuses_complete_material_cache(tmp_path, monkeypatch):
    review_dir = tmp_path / "review"
    pdf_path = review_dir / "fulltext/pdf/source.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.7\ncached")
    doi = "10.1000/cached"
    stem = docling_extract.doi_file_stem(doi)
    output_dir = review_dir / "fulltext/docling"
    output_dir.mkdir(parents=True)
    (output_dir / f"{stem}.md").write_text("# Cached\n", encoding="utf-8")
    (output_dir / f"{stem}.json").write_text("{}\n", encoding="utf-8")
    table_path = review_dir / "tables/source" / f"{stem}-table-01.csv"
    figure_path = review_dir / "figures/source" / f"{stem}-figure-01.png"
    table_path.parent.mkdir(parents=True)
    figure_path.parent.mkdir(parents=True)
    table_path.write_text("Metric,Value\nASR,2%\n", encoding="utf-8")
    figure_path.write_bytes(b"\x89PNG\r\n\x1a\ncached")
    docling_extract.write_csv_rows(
        output_dir / "manifest.csv",
        docling_extract.DOCLING_MANIFEST_FIELDS,
        [
            {
                "doi": doi,
                "source_path": str(pdf_path),
                "source_sha256": docling_extract.sha256_file(pdf_path),
                "status": "success",
                "duration_seconds": "1.00",
                "page_count": "4",
                "table_count": "1",
                "figure_count": "1",
                "markdown_path": f"fulltext/docling/{stem}.md",
                "json_path": f"fulltext/docling/{stem}.json",
                "docling_version": "test",
                "confidence_grade": "excellent",
                "error": "",
            }
        ],
    )
    docling_extract.write_csv_rows(
        output_dir / "table-evidence.csv",
        docling_extract.TABLE_EVIDENCE_FIELDS,
        [
            {
                "record_id": doi,
                "table_id": f"{doi}-table-01",
                "source_path": str(pdf_path),
                "page_or_location": "Página 2",
                "extracted_table_path": table_path.relative_to(review_dir).as_posix(),
                "vision_model": "",
                "status": "extracted_from_pdf_by_docling",
            }
        ],
    )
    docling_extract.write_csv_rows(
        output_dir / "figure-evidence.csv",
        docling_extract.FIGURE_EVIDENCE_FIELDS,
        [
            {
                "record_id": doi,
                "asset_id": f"{doi}-figure-01",
                "source_path": str(pdf_path),
                "page_or_location": "Página 3",
                "extracted_asset_path": figure_path.relative_to(review_dir).as_posix(),
                "vision_model": "",
                "status": "extracted_from_pdf_by_docling",
            }
        ],
    )
    monkeypatch.setattr(docling_extract, "docling_health", lambda: (True, "test"))

    def unexpected_process(*_args, **_kwargs):
        raise AssertionError("A complete material cache must not be regenerated")

    monkeypatch.setattr(docling_extract, "process_pdf", unexpected_process)

    tables, figures = docling_extract.extract_review_documents(
        review_dir,
        [{"assigned_doi": doi, "full_text_path": str(pdf_path)}],
    )

    assert len(tables) == 1
    assert len(figures) == 1
    assert json.loads((output_dir / "status.json").read_text(encoding="utf-8"))[
        "documents_considered"
    ] == 1


def test_review_extraction_reuses_versioned_arxiv_material_paths(tmp_path, monkeypatch):
    review_dir = tmp_path / "review"
    pdf_path = review_dir / "fulltext/pdf/source.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.7\ncached")
    versioned_doi = "10.48550/arxiv.2410.22770v3"
    canonical_doi = "10.48550/arxiv.2410.22770"
    stem = docling_extract.doi_file_stem(versioned_doi)
    output_dir = review_dir / "fulltext/docling"
    output_dir.mkdir(parents=True)
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.json"
    markdown_path.write_text("# Cached\n", encoding="utf-8")
    json_path.write_text("{}\n", encoding="utf-8")
    docling_extract.write_csv_rows(
        output_dir / "manifest.csv",
        docling_extract.DOCLING_MANIFEST_FIELDS,
        [
            {
                "doi": versioned_doi,
                "source_path": str(pdf_path),
                "source_sha256": docling_extract.sha256_file(pdf_path),
                "status": "success",
                "duration_seconds": "1.00",
                "page_count": "4",
                "table_count": "0",
                "figure_count": "0",
                "markdown_path": markdown_path.relative_to(review_dir).as_posix(),
                "json_path": json_path.relative_to(review_dir).as_posix(),
                "docling_version": "test",
                "confidence_grade": "excellent",
                "error": "",
            }
        ],
    )
    monkeypatch.setattr(docling_extract, "docling_health", lambda: (True, "test"))

    def unexpected_process(*_args, **_kwargs):
        raise AssertionError("A versioned arXiv cache must not be regenerated")

    monkeypatch.setattr(docling_extract, "process_pdf", unexpected_process)

    tables, figures = docling_extract.extract_review_documents(
        review_dir,
        [{"assigned_doi": canonical_doi, "full_text_path": str(pdf_path)}],
    )

    assert tables == []
    assert figures == []
    assert json.loads((output_dir / "status.json").read_text(encoding="utf-8"))[
        "documents_considered"
    ] == 1


def test_publication_evidence_prefers_docling_source_table(tmp_path, monkeypatch):
    review_dir = tmp_path / "review"
    pdf_path = review_dir / "fulltext" / "pdf" / "source.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.7\nfixture")
    source_table = review_dir / "tables" / "source" / "10.1234__source-table-01.csv"
    source_figure = review_dir / "figures" / "source" / "10.1234__source-figure-01.png"
    source_table.parent.mkdir(parents=True)
    source_figure.parent.mkdir(parents=True)
    source_table.write_text("Method,Result\nExperiment,Improved\n", encoding="utf-8")
    source_figure.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"x" * 5000))

    docling_tables = [
        {
            "record_id": "10.1234/source",
            "table_id": "10.1234/source-table-01",
            "source_path": str(pdf_path),
            "page_or_location": "Página 2",
            "extracted_table_path": source_table.relative_to(review_dir).as_posix(),
            "vision_model": "",
            "status": "extracted_from_pdf_by_docling",
        }
    ]
    docling_figures = [
        {
            "record_id": "10.1234/source",
            "asset_id": "10.1234/source-figure-01",
            "source_path": str(pdf_path),
            "page_or_location": "Página 3",
            "extracted_asset_path": source_figure.relative_to(review_dir).as_posix(),
            "vision_model": "",
            "status": "extracted_from_pdf_by_docling",
        }
    ]
    monkeypatch.setattr(
        publication_audit,
        "extract_review_documents",
        lambda _review_dir, _rows: (docling_tables, docling_figures),
    )
    monkeypatch.setenv("HERMES_ENABLE_SOURCE_VISUAL_EVIDENCE", "0")

    publication_audit.ensure_visual_evidence(
        review_dir,
        [
            {
                "record_id": "INTERNAL-PRIVATE",
                "assigned_doi": "10.1234/source",
                "full_text_path": str(pdf_path),
                "title_original": "Source evidence",
            }
        ],
    )

    table_manifest = (review_dir / "tables" / "evidence-manifest.csv").read_text(encoding="utf-8")
    figure_manifest = (review_dir / "figures" / "evidence-manifest.csv").read_text(encoding="utf-8")
    assert "extracted_from_pdf_by_docling" in table_manifest
    assert "derived_from_pdf_text_fallback" not in table_manifest
    assert "INTERNAL-PRIVATE" not in table_manifest
    assert "INTERNAL-PRIVATE" not in figure_manifest
