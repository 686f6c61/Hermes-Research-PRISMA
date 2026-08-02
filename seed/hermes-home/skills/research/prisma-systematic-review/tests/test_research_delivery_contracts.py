import csv
import hashlib
import json
import pathlib
import sys
import time
import zipfile

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import bootstrap_topic_review
import build_evidence_ledger
import build_research_memory
import build_review_contracts
import build_scientific_intelligence
import delivery_portal
import evaluate_golden
import export_publication_latex
import package_publication_bundle
import pipeline_state
import prepare_paper_figures
import publication_gate
import render_review_figures
import validate_artifact_schemas

ROOT = pathlib.Path(__file__).resolve().parents[6]


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_public_sanitizer_handles_large_cells_without_regex_backtracking(tmp_path):
    review = tmp_path / "systematic-review-large-cell"
    other_machine_path = (
        f"/Users/researcher/Research Archive/{review.name}/paper/manuscript"
    )
    large_value = ("evidence without a local path " * 80_000) + other_machine_path

    started = time.monotonic()
    sanitized = package_publication_bundle.replace_private_runtime_values(
        large_value,
        review_dir=review,
        id_to_doi={},
    )
    elapsed = time.monotonic() - started

    assert other_machine_path not in sanitized
    assert "./paper/manuscript" in sanitized
    assert elapsed < 1.0


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


def test_claim_evidence_ledger_resolves_multi_author_parenthetical_citations(tmp_path):
    review = tmp_path / "systematic-review-multi-author-ledger"
    (review / "paper/manuscript").mkdir(parents=True)
    (review / "paper/manuscript/publication-ready.md").write_text(
        """# Resultados

La evidencia compara dos defensas bajo amenazas equivalentes (Lin, Niu, et al., 2026; Zhao, Bhaskar, & Dobriban, 2026).
""",
        encoding="utf-8",
    )
    write_csv(
        review / "extraction/extraction-table.csv",
        [
            "assigned_doi",
            "authors",
            "year",
            "evidence_snippet",
            "evidence_location",
        ],
        [
            {
                "assigned_doi": "10.1234/lin",
                "authors": "Lin, Zoe; Niu, Zed",
                "year": "2026",
                "evidence_snippet": "Defense A reduced attack success.",
                "evidence_location": "p. 5",
            },
            {
                "assigned_doi": "10.1234/zhao",
                "authors": "Zhao, Lin; Bhaskar, Arun; Dobriban, Edgar",
                "year": "2026",
                "evidence_snippet": "Defense B preserved utility.",
                "evidence_location": "p. 9",
            },
        ],
    )

    ledger, summary = build_evidence_ledger.build_ledger(review)

    assert summary["status"] == "pass"
    assert ledger[0]["dois"] == "10.1234/lin; 10.1234/zhao"


def test_claim_evidence_ledger_links_aggregate_to_doi_matrix(tmp_path):
    review = tmp_path / "systematic-review-aggregate-ledger"
    (review / "paper/manuscript").mkdir(parents=True)
    (review / "paper/manuscript/publication-ready.md").write_text(
        """# Resultados

Solo 1/2 estudios reportan falsos positivos, por lo que la evidencia comparativa sigue incompleta.
""",
        encoding="utf-8",
    )
    write_csv(
        review / "extraction/extraction-table.csv",
        [
            "assigned_doi",
            "authors",
            "year",
            "evidence_snippet",
            "evidence_location",
        ],
        [
            {
                "assigned_doi": "10.1234/one",
                "authors": "One, Ada",
                "year": "2025",
                "evidence_snippet": "False-positive rate was measured.",
                "evidence_location": "p. 4",
            },
            {
                "assigned_doi": "10.1234/two",
                "authors": "Two, Ben",
                "year": "2025",
                "evidence_snippet": "No false-positive metric was reported.",
                "evidence_location": "p. 7",
            },
        ],
    )

    ledger, summary = build_evidence_ledger.build_ledger(review)

    assert summary["status"] == "pass"
    assert ledger[0]["coverage_status"] == "located"
    assert "extraction/extraction-table.csv" in ledger[0]["evidence_locations"]
    assert ledger[0]["dois"] == "10.1234/one; 10.1234/two"


def test_publication_gate_accepts_material_and_page_evidence_locations():
    assert publication_gate.is_full_text_evidence_location("full text")
    assert publication_gate.is_full_text_evidence_location("texto completo")
    assert publication_gate.is_full_text_evidence_location("pp. 1, 8-9")
    assert publication_gate.is_full_text_evidence_location(
        "p. 12 (full text; fragmento localizado)"
    )
    assert not publication_gate.is_full_text_evidence_location("abstract metadata")


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
    lineage = json.loads((review / "notes/artifact-lineage.json").read_text(encoding="utf-8"))
    assert lineage["schema_version"] == "hermes.artifact-lineage/v1"
    assert {node["path"] for node in lineage["nodes"]} == {
        "paper/output.md",
        "protocol/input.md",
    }
    assert lineage["edges"] == [
        {
            "source": "protocol/input.md",
            "target": "paper/output.md",
            "step": "example",
        }
    ]
    assert str(tmp_path) not in json.dumps(lineage)
    lineage_before_running = (review / "notes/artifact-lineage.json").read_bytes()
    pipeline_state.record_step(
        review,
        "package",
        status="running",
        inputs=["paper/output.md"],
        outputs=["paper/package/publication-package.zip"],
    )
    assert (review / "notes/artifact-lineage.json").read_bytes() == lineage_before_running
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


def test_delivery_portal_builds_academic_downloadable_figure_gallery(tmp_path):
    review = materialize_contract_review(tmp_path)
    build_review_contracts.build_contracts(review)
    (review / "figures/png").mkdir(parents=True)
    (review / "figures/svg").mkdir(parents=True)
    (review / "figures/png/fig-evidence-maturity.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (review / "figures/svg/fig-evidence-maturity.svg").write_text("<svg/>", encoding="utf-8")
    write_csv(
        review / "figures/manifest.csv",
        render_review_figures.MANIFEST_FIELDS,
        [
            {
                "figure_id": "fig-evidence-maturity",
                "title": "Madurez comparativa de la evidencia",
                "apa_caption": "Figura adicional. Madurez comparativa.",
                "png_path": "figures/png/fig-evidence-maturity.png",
                "svg_path": "figures/svg/fig-evidence-maturity.svg",
            }
        ],
    )
    write_csv(
        review / "figures/figure-ranking.csv",
        ["figure_id", "recommendation", "rationale"],
        [
            {
                "figure_id": "fig-evidence-maturity",
                "recommendation": "main_body",
                "rationale": "Separa certeza, señal y vacío.",
            }
        ],
    )

    html_path, _manifest_path, manifest = delivery_portal.build_delivery_assets(review)

    gallery = (review / "figures/gallery.html").read_text(encoding="utf-8")
    rendered = html_path.read_text(encoding="utf-8")
    visual_category = next(row for row in manifest["categories"] if row["id"] == "visuals")
    assert visual_category["start_path"] == "figures/gallery.html"
    assert "Cuerpo propuesto" in gallery
    assert 'href="png/fig-evidence-maturity.png" download' in gallery
    assert 'href="svg/fig-evidence-maturity.svg" download' in gallery
    assert "font-family:Georgia" in gallery
    assert "box-shadow" not in gallery
    assert "--shadow" not in rendered


def test_review_figures_default_to_high_resolution_png():
    assert render_review_figures.DEFAULT_PNG_WIDTH == 2400


def test_latex_figures_stay_with_their_interpretive_text():
    source = "\\usepackage{graphicx}\n\\begin{figure}\n\\caption{Figura 2. Ejemplo.}\n\\end{figure}\n"

    rendered = export_publication_latex.clean_caption_labels(source)

    assert "\\usepackage{float}" in rendered
    assert "\\begin{figure}[H]" in rendered
    assert "\\caption{Ejemplo.}" in rendered


def test_latex_wide_tables_keep_native_centering_and_security_column_balance():
    specs = "\n".join(
        r"  >{\raggedright\arraybackslash}p{(\linewidth - 12\tabcolsep) * \real{0.1429}}"
        + ("@{}}" if index == 6 else "")
        for index in range(7)
    )
    source = "\n".join(
        [
            r"\begin{longtable}[]{@{}",
            specs,
            r"\caption*{Tabla 8A. Fronteras de dominancia condicionada entre familias de harnesses.}\tabularnewline",
            "Amenaza & Familia de control & N & Eficacia & Adaptativa & Coste & Lectura \\\\",
            r"\end{longtable}",
        ]
    )

    rebalanced = export_publication_latex.rebalance_full_title_tables(source)
    rendered = export_publication_latex.tighten_wide_longtables(rebalanced)

    assert r"\real{0.1800}" in rendered
    assert r"\real{0.2300}" in rendered
    assert r"\real{0.0500}" in rendered
    assert r"\setlength{\tabcolsep}{4pt}" in rendered
    assert r"\setlength{\LTleft}{0pt}" not in rendered
    assert r"\setlength{\LTright}{0pt}" not in rendered


def test_latex_export_normalizes_extracted_math_and_defines_unicode_fallback():
    markdown = "Delta ASR-R ≈ 0; U = ∅; |C| ≥ 2; p records d(p) and tau(p)."
    unicode_markdown = "Una etiqueta científica: Δοκιμή."

    normalized = export_publication_latex.normalize_markdown_for_pandoc(markdown)
    rendered = export_publication_latex.add_unicode_font_fallbacks(
        "\\usepackage{graphicx}\n" + unicode_markdown
    )

    assert "≈" not in normalized
    assert "∅" not in normalized
    assert "≥" not in normalized
    assert "Delta ASR-R aprox. 0" in normalized
    assert "\\newfontfamily\\hermesunicodefont{DejaVu Sans}" in rendered
    assert "Delta{\\hermesunicodefont οκιμή}" in rendered
    assert "Δ" not in rendered


def test_evidence_maturity_figure_is_derived_from_position_summary(tmp_path):
    review = tmp_path / "systematic-review-evidence-figure"
    summary_path = review / "analysis/evidence/evidence-position-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "studies": 25,
                "comparisons": 23,
                "status_counts": {
                    "descriptive_alignment": 4,
                    "insufficient_evidence": 7,
                    "open_question": 12,
                },
                "outcome_domains": [
                    {"outcome_label": "Calidad", "studies": 11},
                    {"outcome_label": "Riesgo", "studies": 5},
                ],
            }
        ),
        encoding="utf-8",
    )

    svg = prepare_paper_figures.render_evidence_maturity(
        review,
        [],
        "generic",
        "analytic-grayscale",
    )

    assert "Madurez comparativa de la evidencia" in svg
    assert "ALINEACIÓN DESCRIPTIVA" in svg
    assert ">12<" in svg
    assert "23 unidades de comparación" in svg


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


def test_schema_validator_blocks_character_split_selection_rows(tmp_path):
    review = materialize_contract_review(tmp_path)
    build_review_contracts.build_contracts(review)
    shortlist = review / "selection/ultraquality-shortlist.csv"
    shortlist.parent.mkdir(parents=True, exist_ok=True)
    shortlist.write_text(
        "record_id,assigned_doi,authors,title_original,decision_before_cap,n_limit,"
        "ultraquality_rank,ultraquality_score,representativeness_score,"
        "methodological_quality_score,relevance_score,selected_for_final_n,"
        "selection_reason,cap_exclusion_reason,reviewer,reviewed_at,notes,score_formula\n"
        + "\n".join("RID-BROKEN")
        + "\n",
        encoding="utf-8",
    )

    result = validate_artifact_schemas.validate(review)
    check = next(
        item
        for item in result["checks"]
        if item["path"] == "selection/ultraquality-shortlist.csv"
    )

    assert check["status"] == "fail"
    assert check["integrity_issues"] == ["malformed_rows:10/10"]


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
    manuscript_figures = review / "paper/manuscript/figures/png"
    manuscript_figures.mkdir(parents=True)
    (manuscript_figures / ".DS_Store").write_bytes(b"metadata")
    (manuscript_figures / "obsolete-figure.png").write_bytes(b"stale")
    current_figures = review / "figures/png"
    current_figures.mkdir(parents=True)
    (current_figures / "current-figure.png").write_bytes(b"current")
    (current_figures / ".keep").write_text("", encoding="utf-8")
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
    audit_dir = review / "paper/audit"
    (audit_dir / "extraction-provider-assessment.json").write_text(
        json.dumps({"decision": "not_used_for_remaining_deep_extraction"}) + "\n",
        encoding="utf-8",
    )
    write_csv(
        audit_dir / "model-provenance-discarded-beta.csv",
        ["requested_model", "discard_reason"],
        [{"requested_model": "beta-model", "discard_reason": "contract not closed"}],
    )
    write_csv(
        audit_dir / "provenance-corrections.csv",
        ["artifact", "reason"],
        [{"artifact": "model-provenance.csv", "reason": "metadata correction"}],
    )
    build_scientific_intelligence.build(review)
    build_research_memory.build(review, tmp_path)
    pipeline_state.record_step(
        review,
        "research_memory",
        status="completed",
        inputs=["protocol/intake.md"],
        outputs=[
            "notes/prior-research-context.json",
            "notes/prior-research-context.md",
        ],
    )
    pipeline_state.record_step(
        review,
        "scientific_intelligence",
        status="completed",
        inputs=["extraction/extraction-table.csv"],
        outputs=[
            "analysis/scientific-intelligence.json",
            "analysis/reading-priority.csv",
            "analysis/evidence/claim-position-matrix.csv",
        ],
    )

    bundle = package_publication_bundle.build_bundle(review)

    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert any(name.endswith("analysis/scientific-intelligence.json") for name in names)
        assert any(name.endswith("analysis/reading-priority.csv") for name in names)
        assert any(name.endswith("analysis/evidence/claim-position-matrix.csv") for name in names)
        assert any(name.endswith("notes/artifact-lineage.json") for name in names)
        assert any(name.endswith("paper/audit/extraction-provider-assessment.json") for name in names)
        assert any(name.endswith("paper/audit/model-provenance-discarded-beta.csv") for name in names)
        assert any(name.endswith("paper/audit/provenance-corrections.csv") for name in names)
        assert not any("prior-research-context" in name for name in names)
        assert not any("research-memory" in name for name in names)
        assert not any(".DS_Store" in name for name in names)
        assert not any(name.endswith("/.keep") for name in names)
        assert not any("obsolete-figure.png" in name for name in names)
        assert any(name.endswith("figures/png/current-figure.png") for name in names)
        public_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in names
            if pathlib.Path(name).suffix.lower()
            in {".csv", ".json", ".jsonl", ".md", ".txt"}
        )
        assert "prior-research-context" not in public_text
        assert "research_memory" not in public_text
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

    latex_bundle = package_publication_bundle.build_latex_editable_bundle(review)
    with zipfile.ZipFile(latex_bundle) as archive:
        names = archive.namelist()
        assert not any(name.endswith("/.keep") for name in names)
        assert not any("obsolete-figure.png" in name for name in names)
        assert any(name.endswith("figures/png/current-figure.png") for name in names)
