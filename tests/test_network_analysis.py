from __future__ import annotations

import csv
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = (
    ROOT
    / "seed"
    / "hermes-home"
    / "skills"
    / "research"
    / "research-network-analysis"
    / "scripts"
)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
PRISMA_SCRIPT_DIR = (
    ROOT
    / "seed"
    / "hermes-home"
    / "skills"
    / "research"
    / "prisma-systematic-review"
    / "scripts"
)
if str(PRISMA_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PRISMA_SCRIPT_DIR))

from network_analysis import build_analysis
from network_analysis.graph_builder import resolved_keywords
from network_analysis.io import normalize_label
from network_analysis.metrics import normalized_mutual_information


def test_keyword_resolution_removes_unrelated_ontology_disambiguators() -> None:
    work = {
        "keywords": [
            "Context (archaeology)",
            "Vulnerability (computing)",
            "Threat model",
        ],
        "concepts": [],
    }

    labels = resolved_keywords({"keywords_raw": ""}, work)

    assert "Context" not in labels
    assert "Vulnerability" in labels
    assert "Threat model" in labels
from package_publication_bundle import build_bundle
from review_audit import check_structural_analysis
from sync_review_to_obsidian import build_structural_atlas_note


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_fixture(tmp_path: pathlib.Path, *, with_openalex: bool = True) -> pathlib.Path:
    review = tmp_path / "systematic-review-test"
    dois = [f"10.1000/test{i:02d}" for i in range(1, 13)]
    authors = {
        1: "Alice Alpha; Bob Bridge",
        2: "Alice Alpha; Bob Bridge",
        3: "Alice Alpha; Bob Bridge",
        4: "Bob Bridge; Carol Cluster",
        5: "Carol Cluster; Dan Delta",
        6: "Carol Cluster; Dan Delta",
        7: "Eva Echo; Fran Field",
        8: "Eva Echo; Fran Field",
        9: "Eva Echo; Gina Grove",
        10: "Bob Bridge; Gina Grove",
        11: "Hugo Hill",
        12: "Iris Island",
    }
    keywords = {
        index: ("memory; agents; planning" if index <= 6 else "education; teachers; adoption")
        for index in range(1, 13)
    }
    master = [
        {
            "record_id": f"RID-{index}",
            "assigned_doi": doi,
            "authors": authors[index],
            "title_original": f"Study {index}",
            "year": str(2020 + index % 6),
            "source": "Fixture Journal",
            "keywords_normalized": keywords[index],
        }
        for index, doi in enumerate(dois, 1)
    ]
    write_csv(
        review / "records" / "master-records.csv",
        [
            "record_id",
            "assigned_doi",
            "authors",
            "title_original",
            "year",
            "source",
            "keywords_normalized",
        ],
        master,
    )
    title_rows = [
        {
            **row,
            "decision": "exclude" if index == 12 else "include",
        }
        for index, row in enumerate(master, 1)
    ]
    write_csv(
        review / "screening" / "title-abstract.csv",
        [*master[0], "decision"],
        title_rows,
    )
    full_text = [
        {
            **row,
            "decision": "exclude" if index in {11, 12} else "include_ft",
        }
        for index, row in enumerate(master, 1)
        if index != 12
    ]
    write_csv(
        review / "screening" / "full-text.csv",
        [*master[0], "decision"],
        full_text,
    )
    extraction = [
        {
            **row,
            "work_type": "Empirical",
            "method_used": "Experiment" if index <= 6 else "Survey",
            "theory_framework": "Distributed cognition" if index <= 6 else "Technology acceptance",
            "variables_independent": "System configuration",
            "variables_dependent": "Observed performance",
            "countries": "Spain" if index <= 6 else "Malta",
            "key_findings": "A structured finding",
        }
        for index, row in enumerate(master[:10], 1)
    ]
    write_csv(
        review / "extraction" / "extraction-table.csv",
        [
            *master[0],
            "work_type",
            "method_used",
            "theory_framework",
            "variables_independent",
            "variables_dependent",
            "countries",
            "key_findings",
        ],
        extraction,
    )
    shortlist = [
        {
            "assigned_doi": doi,
            "authors": authors[index],
            "title_original": f"Study {index}",
            "decision_before_cap": "include_ft",
            "ultraquality_rank": str(index),
            "selected_for_final_n": "yes" if index <= 6 else "no",
        }
        for index, doi in enumerate(dois[:10], 1)
    ]
    write_csv(
        review / "selection" / "ultraquality-shortlist.csv",
        list(shortlist[0]),
        shortlist,
    )
    (review / "protocol").mkdir(parents=True, exist_ok=True)
    (review / "protocol" / "research-question.md").write_text(
        "# Structural test review\n\nWhat is connected?\n",
        encoding="utf-8",
    )
    if with_openalex:
        raw = review / "searches" / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        works = []
        for index, doi in enumerate(dois, 1):
            author_names = authors[index].split("; ")
            works.append(
                {
                    "id": f"https://openalex.org/W{index}",
                    "doi": f"https://doi.org/{doi}",
                    "display_name": f"Study {index}",
                    "publication_year": 2020 + index % 6,
                    "cited_by_count": index,
                    "primary_location": {"source": None} if index == 1 else None,
                    "authorships": [
                        {
                            "author": {
                                "id": f"https://openalex.org/A{name.replace(' ', '')}",
                                "display_name": name,
                            },
                            "institutions": [{"display_name": "Fixture University"}],
                        }
                        for name in author_names
                    ],
                    "referenced_works": [
                        f"https://openalex.org/W{target}"
                        for target in range(max(1, index - 2), index)
                    ],
                    "concepts": [
                        {
                            "display_name": "Artificial intelligence" if index <= 6 else "Higher education"
                        }
                    ],
                    "keywords": [{"display_name": value} for value in keywords[index].split("; ")],
                }
            )
        (raw / "openalex-fixture.json").write_text(
            json.dumps({"results": works}),
            encoding="utf-8",
        )
        author_cache = review / "analysis" / "cache" / "openalex" / "authors"
        author_cache.mkdir(parents=True, exist_ok=True)
        (author_cache / "ABobBridge.json").write_text(
            json.dumps(
                {
                    "id": "https://openalex.org/ABobBridge",
                    "display_name": "Bob Bridge",
                    "works_count": 42,
                    "cited_by_count": 314,
                    "last_known_institutions": [{"display_name": "Fixture University"}],
                }
            ),
            encoding="utf-8",
        )
    return review


def test_nmi_is_one_for_equivalent_partitions() -> None:
    left = [{"a", "b"}, {"c", "d"}]
    right = [{"c", "d"}, {"a", "b"}]
    assert normalized_mutual_information(left, right) == pytest.approx(1.0)


def test_label_normalization_removes_invisible_formatting_controls() -> None:
    assert normalize_label("Ciaran Grafton\u2060‐Clarke") == "Ciaran Grafton‐Clarke"


def test_build_analysis_creates_offline_auditable_outputs(tmp_path: pathlib.Path, monkeypatch) -> None:
    review = build_fixture(tmp_path)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785456000")
    manifest = build_analysis(review, offline=True)

    required = [
        "manifest.json",
        "atlas/network-atlas.html",
        "data/nodes.csv",
        "data/edges.csv",
        "data/graph.graphml",
        "metrics/network-summary.json",
        "metrics/centrality.csv",
        "metrics/communities.csv",
        "metrics/author-production.csv",
        "metrics/selection-drift.csv",
        "audit/coverage.json",
        "audit/parameters.json",
        "audit/provenance.csv",
    ]
    for relative in required:
        assert (review / "analysis" / relative).is_file(), relative

    assert manifest["included_study_count"] == 10
    assert manifest["focal_study_count"] == 6
    assert manifest["title"] == "Structural test review"
    html = (review / "analysis" / "atlas" / "network-atlas.html").read_text(encoding="utf-8")
    assert "OFFLINE · SIN CDN" in html
    assert "default-src 'none'" in html
    assert 'src="http' not in html
    assert 'href="http' not in html
    assert "GEXF · Gephi" in html
    assert "downloadPng" in html
    assert "downloadSvg" in html
    assert "downloadGexf" in html
    assert 'href="../data/graph.graphml"' in html

    centrality = list(
        csv.DictReader((review / "analysis" / "metrics" / "centrality.csv").open(encoding="utf-8"))
    )
    author_rows = [row for row in centrality if row["layer"] == "coauthorship"]
    bridge = next(row for row in author_rows if row["label"] == "Bob Bridge")
    alice = next(row for row in author_rows if row["label"] == "Alice Alpha")
    assert float(bridge["betweenness"]) > float(alice["betweenness"])

    nodes = list(csv.DictReader((review / "analysis" / "data" / "nodes.csv").open(encoding="utf-8")))
    study_nodes = [row for row in nodes if row["node_type"] == "study"]
    assert study_nodes
    assert all(row["node_id"].startswith("study:10.") for row in study_nodes)
    assert all("RID-" not in row["node_id"] for row in study_nodes)
    author_production = list(
        csv.DictReader(
            (review / "analysis" / "metrics" / "author-production.csv").open(encoding="utf-8")
        )
    )
    bob = next(row for row in author_production if row["author"] == "Bob Bridge")
    assert bob["openalex_works_count"] == "42"
    assert bob["included_studies"] == "5"
    assert check_structural_analysis(review / "analysis").status == "PASS"


def test_analysis_is_packaged_and_ready_for_obsidian(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    review = build_fixture(tmp_path)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785456000")
    build_analysis(review, offline=True)

    bundle = build_bundle(review)
    archive_root = f"{review.name}-publication-package"
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
    assert f"{archive_root}/analysis/atlas/network-atlas.html" in names
    assert f"{archive_root}/analysis/data/graph.graphml" in names
    assert f"{archive_root}/analysis/audit/coverage.json" in names
    assert not any("/analysis/cache/" in name for name in names)

    note = build_structural_atlas_note(review)
    assert "[Abrir atlas HTML offline]" in note
    assert "### Estructura relacional del corpus" in note
    assert "### Metodología del atlas estructural" in note


def test_focal_selection_is_constrained_to_included_studies(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    review = build_fixture(tmp_path)
    shortlist_path = review / "selection" / "ultraquality-shortlist.csv"
    rows = list(csv.DictReader(shortlist_path.open(encoding="utf-8")))
    rows.append(
        {
            "assigned_doi": "10.1000/test11",
            "authors": "Hugo Hill",
            "title_original": "Study 11",
            "decision_before_cap": "include_ft",
            "ultraquality_rank": "11",
            "selected_for_final_n": "yes",
        }
    )
    write_csv(shortlist_path, list(rows[0]), rows)

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785456000")
    manifest = build_analysis(review, offline=True)
    coverage = json.loads(
        (review / "analysis" / "audit" / "coverage.json").read_text(encoding="utf-8")
    )
    assert manifest["included_study_count"] == 10
    assert manifest["focal_study_count"] == 6
    assert coverage["raw_focal_shortlist_count"] == 7
    assert coverage["focal_outside_included_count"] == 1
    assert coverage["focal_outside_included_dois"] == ["10.1000/test11"]


def test_explicit_non_selection_is_not_treated_as_focal(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    review = build_fixture(tmp_path)
    shortlist_path = review / "selection" / "ultraquality-shortlist.csv"
    rows = list(csv.DictReader(shortlist_path.open(encoding="utf-8")))
    rows[0]["selected_for_final_n"] = "no"
    rows[0]["decision_before_cap"] = "include"
    rows[0]["ultraquality_rank"] = "1"
    write_csv(shortlist_path, list(rows[0]), rows)

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785456000")
    manifest = build_analysis(review, offline=True)
    coverage = json.loads(
        (review / "analysis" / "audit" / "coverage.json").read_text(encoding="utf-8")
    )

    assert manifest["focal_study_count"] == 5
    assert coverage["raw_focal_shortlist_count"] == 5
    assert coverage["focal_outside_included_count"] == 0


def test_build_analysis_is_reproducible_with_fixed_epoch(tmp_path: pathlib.Path, monkeypatch) -> None:
    review = build_fixture(tmp_path)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785456000")
    build_analysis(review, offline=True)
    first = {
        relative: (review / "analysis" / relative).read_bytes()
        for relative in (
            "data/nodes.csv",
            "data/edges.csv",
            "metrics/centrality.csv",
            "atlas/network-atlas.html",
        )
    }
    build_analysis(review, offline=True)
    second = {
        relative: (review / "analysis" / relative).read_bytes()
        for relative in first
    }
    assert first == second


def test_cli_is_reproducible_across_hash_seeds(tmp_path: pathlib.Path) -> None:
    review = build_fixture(tmp_path)
    command = [
        sys.executable,
        str(SCRIPT_DIR / "build_network_analysis.py"),
        str(review),
        "--offline",
    ]
    outputs = []
    for hash_seed in ("1", "947"):
        environment = {
            **os.environ,
            "PYTHONHASHSEED": hash_seed,
            "SOURCE_DATE_EPOCH": "1785456000",
        }
        subprocess.run(command, check=True, capture_output=True, text=True, env=environment)
        outputs.append(
            {
                relative: (review / "analysis" / relative).read_bytes()
                for relative in (
                    "data/nodes.csv",
                    "data/edges.csv",
                    "metrics/centrality.csv",
                    "metrics/communities.csv",
                    "metrics/network-summary.json",
                    "atlas/network-atlas.html",
                )
            }
        )
    assert outputs[0] == outputs[1]


def test_missing_openalex_stays_partial_without_inventing_references(
    tmp_path: pathlib.Path,
    monkeypatch,
) -> None:
    review = build_fixture(tmp_path, with_openalex=False)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785456000")
    build_analysis(review, offline=True)
    coverage = json.loads(
        (review / "analysis" / "audit" / "coverage.json").read_text(encoding="utf-8")
    )
    assert coverage["authors"]["coverage"] == pytest.approx(1.0)
    assert coverage["references"]["coverage"] == 0.0
    summary = json.loads(
        (review / "analysis" / "metrics" / "network-summary.json").read_text(encoding="utf-8")
    )
    assert summary["layers"]["bibliographic_coupling"]["claim_status"] == "exploratory"


def test_cli_module_can_be_imported_without_side_effects() -> None:
    spec = importlib.util.spec_from_file_location(
        "build_network_analysis",
        SCRIPT_DIR / "build_network_analysis.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert callable(module.main)
