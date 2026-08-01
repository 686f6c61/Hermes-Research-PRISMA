import csv
import hashlib
import json
import pathlib
import sys
import zipfile

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import bootstrap_topic_review
import build_evidence_ledger
import build_review_contracts
import delivery_portal
import evaluate_golden
import package_publication_bundle
import pipeline_state
import validate_artifact_schemas

ROOT = pathlib.Path(__file__).resolve().parents[6]


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def materialize_contract_review(tmp_path: pathlib.Path) -> pathlib.Path:
    review = tmp_path / "systematic-review-example"
    (review / "protocol").mkdir(parents=True)
    (review / "protocol/intake.md").write_text(
        """# Intake

- Tema: IA y docencia universitaria
- Pregunta de investigación (opcional): ¿Cómo cambia la calidad docente?
- Año o años: 2024-2026
- Criterios de inclusión: texto completo y evidencia empírica
- Criterios de exclusión: sin DOI
- Modo autónomo: sí
- Modo metodológico (opcional): educación
- Límite final N ultraquality: 23-63
- Revista o medio objetivo (opcional; si se omite, o si solo indicas una familia temática amplia, Hermes usa `generic-common-core`): generic-common-core
- Modo de validación (opcional): autonomous
""",
        encoding="utf-8",
    )
    (review / "protocol/review-mode.json").write_text(
        json.dumps(
            {
                "mode": "education",
                "mode_label": "Modo educación",
                "primary_mode": "education",
                "primary_unit": "actividad educativa-sistema-contexto-resultado",
                "confidence": "declarado",
            }
        ),
        encoding="utf-8",
    )
    return review


def test_review_contracts_freeze_range_method_and_synthesis(tmp_path):
    review = materialize_contract_review(tmp_path)

    paths = build_review_contracts.build_contracts(review)

    assert paths
    intake = json.loads((review / "protocol/intake.json").read_text(encoding="utf-8"))
    method = json.loads((review / "protocol/method-contract.json").read_text(encoding="utf-8"))
    synthesis = json.loads((review / "protocol/synthesis-plan.json").read_text(encoding="utf-8"))
    assert intake["target_n"] == {
        "minimum": 23,
        "maximum": 63,
        "exact": None,
        "policy": "desired range, never an inclusion quota",
    }
    assert method["review_mode"] == "education"
    assert method["unit_of_comparison"] == "actividad educativa-sistema-contexto-resultado"
    assert any(rule["method"] == "meta-analysis" for rule in synthesis["decision_rules"])


def test_topic_pack_adds_auditable_education_stage():
    decomposition = {"search_stages": [], "question_axes": {}}

    enriched = bootstrap_topic_review.apply_topic_packs(
        decomposition,
        topic="Inteligencia artificial y docentes universitarios",
        question="¿La IA mejora la calidad y reduce la carga de trabajo en educación superior?",
        inclusion="estudios empíricos con faculty",
        mode_decision={"mode": "education", "primary_mode": "education"},
    )

    assert enriched["topic_packs"] == ["ai-higher-education"]
    assert enriched["search_stages"][0]["stage_id"] == "TP1"
    assert "carga de trabajo" in enriched["search_stages"][0]["axis_covered"]


def test_claim_evidence_ledger_links_author_year_to_doi_and_page(tmp_path):
    review = tmp_path / "systematic-review-ledger"
    (review / "paper/manuscript").mkdir(parents=True)
    (review / "paper/manuscript/publication-ready.md").write_text(
        """# Full title

# Resultados

La evidencia indica que la intervención mejoró el resultado principal en 120 participantes (Smith, 2025).
""",
        encoding="utf-8",
    )
    write_csv(
        review / "extraction/extraction-table.csv",
        [
            "record_id",
            "assigned_doi",
            "authors",
            "year",
            "evidence_snippet",
            "evidence_location",
        ],
        [
            {
                "record_id": "RID-hidden",
                "assigned_doi": "10.1234/example",
                "authors": "Smith, Jane",
                "year": "2025",
                "evidence_snippet": "The intervention improved the primary outcome.",
                "evidence_location": "p. 7",
            }
        ],
    )

    ledger, summary = build_evidence_ledger.build_ledger(review)

    assert summary["status"] == "pass"
    assert summary["critical_located"] == 1
    assert ledger[0]["dois"] == "10.1234/example"
    assert "RID-hidden" not in json.dumps(ledger)


def test_pipeline_state_skips_only_when_hash_and_outputs_match(tmp_path):
    review = tmp_path / "review"
    (review / "protocol").mkdir(parents=True)
    (review / "protocol/input.md").write_text("v1", encoding="utf-8")
    (review / "paper").mkdir()
    (review / "paper/output.md").write_text("ready", encoding="utf-8")

    pipeline_state.record_step(
        review,
        "example",
        status="completed",
        inputs=["protocol/*.md"],
        outputs=["paper/output.md"],
    )

    dirty, _ = pipeline_state.should_run(
        review,
        "example",
        inputs=["protocol/*.md"],
        outputs=["paper/output.md"],
    )
    assert dirty is False
    (review / "protocol/input.md").write_text("v2", encoding="utf-8")
    dirty, _ = pipeline_state.should_run(
        review,
        "example",
        inputs=["protocol/*.md"],
        outputs=["paper/output.md"],
    )
    assert dirty is True


def test_delivery_portal_explains_package_instead_of_listing_a_folder(tmp_path):
    review = materialize_contract_review(tmp_path)
    build_review_contracts.build_contracts(review)
    (review / "paper/manuscript").mkdir(parents=True)
    (review / "paper/manuscript/publication-ready.md").write_text(
        "# Título completo de la revisión\n",
        encoding="utf-8",
    )

    html_path, manifest_path, manifest = delivery_portal.build_delivery_assets(review)

    rendered = html_path.read_text(encoding="utf-8")
    assert manifest_path.exists()
    assert manifest["schema_version"] == "hermes.deliverables-manifest/v1"
    assert len(manifest["categories"]) == 12
    assert "12 paquetes, una revisión" in rendered
    assert "Título completo de la revisión" in rendered
    assert "../../protocol/method-contract.json" in rendered
    assert "RID-" not in rendered


def test_golden_fixture_proves_evaluator_and_png_output(tmp_path):
    fixture = ROOT / "evals/fixtures/common"
    output = tmp_path / "golden"

    metrics = evaluate_golden.evaluate(
        fixture,
        fixture / "predictions.jsonl",
        output,
        recall_threshold=0.95,
        precision_threshold=0.80,
        extraction_threshold=0.85,
        evidence_threshold=0.95,
    )

    assert metrics["status"] == "pass"
    assert (output / "screening-confusion-matrix.png").read_bytes().startswith(b"\x89PNG")
    assert (output / "error-analysis.csv").exists()


def test_schema_validator_reports_missing_contracts_instead_of_guessing(tmp_path):
    review = materialize_contract_review(tmp_path)
    build_review_contracts.build_contracts(review)

    result = validate_artifact_schemas.validate(review)

    assert result["status"] == "fail"
    assert result["checks_failed"] > 0


def test_publication_zip_uses_doi_and_removes_private_record_identity(tmp_path):
    review = materialize_contract_review(tmp_path)
    build_review_contracts.build_contracts(review)
    record_id = "RID-ABCDEF1234"
    doi = "10.1234/public-example"
    common_fields = ["record_id", "assigned_doi", "authors", "title_original"]
    common_row = {
        "record_id": record_id,
        "assigned_doi": doi,
        "authors": "Smith, Jane",
        "title_original": "Public study",
    }
    write_csv(review / "records/master-records.csv", common_fields, [common_row])
    write_csv(
        review / "selection/ultraquality-shortlist.csv",
        [*common_fields, "ultraquality_rank", "selected_for_final_n"],
        [{**common_row, "ultraquality_rank": "1", "selected_for_final_n": "yes"}],
    )
    write_csv(
        review / "extraction/extraction-table.csv",
        [*common_fields, "evidence_snippet", "evidence_location"],
        [{**common_row, "evidence_snippet": "Supported result", "evidence_location": "p. 4"}],
    )
    write_csv(review / "searches/search-log.csv", ["source", "query"], [{"source": "test", "query": "example"}])
    write_csv(
        review / "screening/title-abstract.csv",
        [*common_fields, "decision"],
        [{**common_row, "decision": "include"}],
    )
    write_csv(
        review / "screening/full-text.csv",
        [*common_fields, "decision"],
        [{**common_row, "decision": "include_ft"}],
    )
    (review / "paper/manuscript").mkdir(parents=True)
    (review / "paper/manuscript/publication-ready.md").write_text(
        f"# Public title\n\nSource {record_id} from {review}.\n",
        encoding="utf-8",
    )
    (review / "fulltext/pdf").mkdir(parents=True)
    (review / "fulltext/pdf/rid-abcdef1234.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    write_csv(
        review / "tables/extracted/rid-abcdef1234-summary.csv",
        ["field", "value"],
        [{"field": "record_id", "value": record_id}],
    )
    gold_dir = review / "paper/audit/gold"
    write_csv(
        gold_dir / "title-abstract-gold.csv",
        ["record_id", "assigned_doi", "decision"],
        [{"record_id": record_id, "assigned_doi": doi, "decision": "include"}],
    )
    write_csv(
        gold_dir / "full-text-gold.csv",
        ["record_id", "assigned_doi", "decision"],
        [{"record_id": record_id, "assigned_doi": doi, "decision": "include_ft"}],
    )
    (gold_dir / "extraction-gold.jsonl").write_text(
        json.dumps(
            {
                "record": {
                    "record_id": record_id,
                    "assigned_doi": doi,
                    "evidence": "Supported result",
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (gold_dir / "DATASET-CARD.md").write_text(
        "# Operational reference set\n",
        encoding="utf-8",
    )
    (gold_dir / "gold-manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "paper/audit/gold/extraction-gold.jsonl",
                        "bytes": 1,
                        "sha256": "private-placeholder",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    bundle = package_publication_bundle.build_bundle(review)

    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert any(name.endswith("fulltext/pdf/10.1234-public-example.pdf") for name in names)
        assert not any("rid-" in name.lower() for name in names)
        master_name = next(name for name in names if name.endswith("paper/appendices/data/master-records.csv"))
        master = archive.read(master_name).decode("utf-8")
        assert "record_id" not in master.splitlines()[0]
        assert "doi" in master.splitlines()[0]
        assert record_id not in master
        manuscript_name = next(name for name in names if name.endswith("paper/manuscript/publication-ready.md"))
        manuscript = archive.read(manuscript_name).decode("utf-8")
        assert record_id not in manuscript
        assert str(review) not in manuscript
        summary_name = next(name for name in names if name.endswith("tables/extracted/10.1234-public-example-summary.csv"))
        summary = archive.read(summary_name).decode("utf-8")
        assert "record_id" not in summary
        assert "doi,10.1234/public-example" in summary
        gold_name = next(
            name
            for name in names
            if name.endswith("paper/audit/gold/extraction-gold.jsonl")
        )
        public_gold = archive.read(gold_name).decode("utf-8")
        assert "record_id" not in public_gold
        assert '"doi": "10.1234/public-example"' in public_gold
        manifest_name = next(
            name
            for name in names
            if name.endswith("paper/audit/gold/gold-manifest.json")
        )
        public_manifest = json.loads(archive.read(manifest_name))
        item = public_manifest["files"][0]
        public_gold_bytes = archive.read(gold_name)
        assert item["bytes"] == len(public_gold_bytes)
        assert item["sha256"] == hashlib.sha256(public_gold_bytes).hexdigest()
