import base64
import csv
import json
import pathlib
import sys

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
