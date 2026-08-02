#!/usr/bin/env python3
"""Audit optional paper-to-code consistency without executing external code.

The default mode only inventories repository declarations found in local review
artifacts. ``--inspect-remote`` adds read-only GitHub metadata and tree checks.
No repository is cloned, installed, imported, or executed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Iterable

AUDIT_FIELDS = [
    "doi",
    "title",
    "repository_url",
    "repository_host",
    "audit_mode",
    "status",
    "default_branch",
    "resolved_commit",
    "license",
    "readme",
    "dependency_manifest",
    "container_definition",
    "tests",
    "continuous_integration",
    "configuration",
    "data_or_dataset",
    "notebook",
    "reported_method",
    "reported_dataset",
    "reported_comparator",
    "structural_consistency",
    "gaps",
    "code_executed",
]

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
REPO_RE = re.compile(
    r"^https?://(?P<host>github\.com|gitlab\.com|codeberg\.org)/"
    r"(?P<owner>[^/#?]+)/(?P<repo>[^/#?]+)",
    re.IGNORECASE,
)


def now_iso() -> str:
    """Return a timezone-aware generation timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def clean_doi(value: object) -> str:
    """Normalize a public DOI."""
    doi = " ".join(str(value or "").split()).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi if doi.startswith("10.") and "/" in doi else ""


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    """Read one optional CSV."""
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: pathlib.Path, rows: Iterable[dict[str, object]]) -> pathlib.Path:
    """Write the stable audit table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in AUDIT_FIELDS})
    return path


def normalize_repository_url(url: str) -> str:
    """Strip punctuation, deep links, and a trailing .git suffix."""
    candidate = url.rstrip(".,;:!?)]}").replace("\\", "")
    match = REPO_RE.match(candidate)
    if not match:
        return ""
    repo = match.group("repo").removesuffix(".git")
    return f"https://{match.group('host').lower()}/{match.group('owner')}/{repo}"


def selected_dois(review_dir: pathlib.Path) -> set[str]:
    """Return focal DOI values, falling back to the included extraction set."""
    selected = {
        doi
        for row in read_csv(review_dir / "selection" / "ultraquality-shortlist.csv")
        if str(row.get("selected_for_final_n") or "").strip().lower() in {"yes", "si", "sí", "true", "1"}
        if (doi := clean_doi(row.get("assigned_doi") or row.get("doi")))
    }
    if selected:
        return selected
    return {
        doi
        for row in read_csv(review_dir / "extraction" / "extraction-table.csv")
        if (doi := clean_doi(row.get("assigned_doi") or row.get("doi")))
    }


def local_text_by_doi(review_dir: pathlib.Path) -> dict[str, str]:
    """Collect local full-text derivatives without exposing their paths."""
    texts: dict[str, list[str]] = {}
    candidates = [
        review_dir / "fulltext" / "docling",
        review_dir / "fulltext" / "txt",
        review_dir / "fulltext" / "html",
    ]
    doi_pattern = re.compile(r"10\.\d{4,9}[/_][A-Za-z0-9._;()/:+-]+", re.IGNORECASE)
    for root in candidates:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".html", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            matches = doi_pattern.findall(path.name + "\n" + text[:4000])
            for raw in matches:
                doi = clean_doi(raw.replace("__", "/").replace("_", "/", 1))
                if doi:
                    texts.setdefault(doi, []).append(text)
    return {doi: "\n".join(parts) for doi, parts in texts.items()}


def repository_urls(text: str) -> list[str]:
    """Extract unique supported repository roots."""
    found = {normalized for url in URL_RE.findall(text) if (normalized := normalize_repository_url(url))}
    return sorted(found)


def github_request(path: str) -> dict[str, object] | list[object]:
    """Call the read-only GitHub API with an optional token for rate limits."""
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "HermesResearchPaperCodeAudit/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def github_coordinates(url: str) -> tuple[str, str] | None:
    """Return the owner and repository for a canonical GitHub URL."""
    match = REPO_RE.match(url)
    if not match or match.group("host").lower() != "github.com":
        return None
    return match.group("owner"), match.group("repo").removesuffix(".git")


def tree_signals(paths: list[str]) -> dict[str, str]:
    """Translate a repository tree into reproducibility signals."""
    lowered = [path.lower() for path in paths]

    def has_name(*patterns: str) -> str:
        return "yes" if any(any(re.search(pattern, path) for pattern in patterns) for path in lowered) else "no"

    return {
        "readme": has_name(r"(^|/)readme(?:\.|$)"),
        "dependency_manifest": has_name(
            r"(^|/)requirements[^/]*\.txt$",
            r"(^|/)pyproject\.toml$",
            r"(^|/)environment\.ya?ml$",
            r"(^|/)package\.json$",
            r"(^|/)renv\.lock$",
        ),
        "container_definition": has_name(r"(^|/)dockerfile", r"(^|/)docker-compose", r"(^|/)compose\.ya?ml$"),
        "tests": has_name(r"(^|/)tests?/", r"(^|/)test_[^/]+\.py$", r"\.(spec|test)\.[jt]sx?$"),
        "continuous_integration": has_name(r"^\.github/workflows/", r"^\.gitlab-ci\.ya?ml$"),
        "configuration": has_name(r"(^|/)configs?/", r"\.(toml|ya?ml|json)$"),
        "data_or_dataset": has_name(r"(^|/)(data|datasets?)/", r"dataset"),
        "notebook": has_name(r"\.ipynb$"),
    }


def inspect_github(url: str) -> dict[str, str]:
    """Inspect public metadata and file names without downloading or running code."""
    coordinates = github_coordinates(url)
    if not coordinates:
        return {"status": "unsupported_host"}
    owner, repo = coordinates
    encoded = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
    try:
        metadata = github_request(encoded)
        if not isinstance(metadata, dict):
            return {"status": "remote_error", "gaps": "Unexpected GitHub metadata response."}
        branch = str(metadata.get("default_branch") or "")
        tree = github_request(f"{encoded}/git/trees/{urllib.parse.quote(branch)}?recursive=1") if branch else {}
        tree_rows = tree.get("tree") if isinstance(tree, dict) else []
        paths = [
            str(item.get("path") or "")
            for item in tree_rows
            if isinstance(item, dict) and item.get("type") == "blob"
        ]
        signals = tree_signals(paths)
        license_payload = metadata.get("license")
        license_name = (
            str(license_payload.get("spdx_id") or license_payload.get("name") or "")
            if isinstance(license_payload, dict)
            else ""
        )
        return {
            "status": "inspected",
            "default_branch": branch,
            "resolved_commit": str(tree.get("sha") or "") if isinstance(tree, dict) else "",
            "license": license_name,
            **signals,
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"status": "remote_error", "gaps": type(exc).__name__}


def structural_consistency(row: dict[str, str]) -> tuple[str, str]:
    """Describe visible reproducibility structure without claiming replication."""
    if row["status"] != "inspected":
        return "not_assessed", "Remote repository structure was not inspected."
    expected = {
        "readme": "README",
        "dependency_manifest": "dependency manifest",
        "configuration": "configuration",
        "tests": "tests",
    }
    missing = [label for field, label in expected.items() if row.get(field) != "yes"]
    if row.get("reported_dataset") and row.get("data_or_dataset") != "yes":
        missing.append("visible data or dataset path")
    if not missing:
        return "structurally_supported", ""
    return "gaps_detected", "; ".join(missing)


def build_rows(review_dir: pathlib.Path, *, inspect_remote: bool, max_papers: int) -> list[dict[str, str]]:
    """Build optional audit rows for focal studies with locally declared code."""
    focus = selected_dois(review_dir)
    fulltext = local_text_by_doi(review_dir)
    extraction = [
        row
        for row in read_csv(review_dir / "extraction" / "extraction-table.csv")
        if clean_doi(row.get("assigned_doi") or row.get("doi")) in focus
    ]
    if max_papers > 0:
        extraction = extraction[:max_papers]
    output: list[dict[str, str]] = []
    for source in extraction:
        doi = clean_doi(source.get("assigned_doi") or source.get("doi"))
        source_blob = "\n".join(
            [
                fulltext.get(doi, ""),
                str(source.get("notes") or ""),
                str(source.get("key_findings") or ""),
                str(source.get("evidence_snippet") or ""),
            ]
        )
        urls = repository_urls(source_blob)
        if not urls:
            output.append(
                {
                    "doi": doi,
                    "title": " ".join(str(source.get("title_original") or "").split()),
                    "audit_mode": "remote_metadata" if inspect_remote else "inventory",
                    "status": "no_repository_declared",
                    "reported_method": " ".join(str(source.get("method_used") or "").split()),
                    "reported_dataset": " ".join(str(source.get("benchmark_dataset_or_corpus") or "").split()),
                    "reported_comparator": " ".join(str(source.get("baselines_or_comparators") or "").split()),
                    "structural_consistency": "not_assessed",
                    "gaps": "No supported public repository URL was recovered from local evidence.",
                    "code_executed": "no",
                }
            )
            continue
        for url in urls:
            match = REPO_RE.match(url)
            base = {
                "doi": doi,
                "title": " ".join(str(source.get("title_original") or "").split()),
                "repository_url": url,
                "repository_host": match.group("host").lower() if match else "",
                "audit_mode": "remote_metadata" if inspect_remote else "inventory",
                "status": "declared_not_inspected",
                "reported_method": " ".join(str(source.get("method_used") or "").split()),
                "reported_dataset": " ".join(str(source.get("benchmark_dataset_or_corpus") or "").split()),
                "reported_comparator": " ".join(str(source.get("baselines_or_comparators") or "").split()),
                "code_executed": "no",
            }
            if inspect_remote:
                base.update(inspect_github(url))
            consistency, gaps = structural_consistency(base)
            base["structural_consistency"] = consistency
            base["gaps"] = "; ".join(filter(None, [base.get("gaps", ""), gaps]))
            output.append(base)
    return output


def write_report(path: pathlib.Path, rows: list[dict[str, str]], inspect_remote: bool) -> pathlib.Path:
    """Write a reader-facing report that states the audit boundary."""
    inspected = sum(1 for row in rows if row.get("status") == "inspected")
    repositories = sum(1 for row in rows if row.get("repository_url"))
    lines = [
        "# Auditoría opcional artículo-código",
        "",
        f"- Fecha: {now_iso()}",
        f"- Modo: {'metadatos remotos de solo lectura' if inspect_remote else 'inventario local'}",
        f"- Repositorios declarados: {repositories}",
        f"- Repositorios inspeccionados: {inspected}",
        "",
        "Esta comprobación no ejecuta, importa ni instala código externo. Una estructura completa puede "
        "mejorar la capacidad de reproducción, pero no demuestra que los resultados hayan sido replicados.",
        "",
        "| DOI | Repositorio | Estado | Consistencia estructural |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('doi', '')} | {row.get('repository_url') or 'no declarado'} | "
            f"{row.get('status', '')} | {row.get('structural_consistency', '')} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(review_dir: pathlib.Path, *, inspect_remote: bool, max_papers: int = 0) -> dict[str, object]:
    """Run the bounded optional audit and return its manifest."""
    rows = build_rows(review_dir, inspect_remote=inspect_remote, max_papers=max_papers)
    output_dir = review_dir / "analysis" / "reproducibility"
    csv_path = write_csv(output_dir / "paper-code-consistency.csv", rows)
    report_path = write_report(output_dir / "paper-code-audit.md", rows, inspect_remote)
    manifest = {
        "schema_version": "hermes.paper-code-audit/v1",
        "generated_at": now_iso(),
        "optional": True,
        "mode": "remote_metadata" if inspect_remote else "inventory",
        "code_executed": False,
        "studies": len({row.get("doi") for row in rows}),
        "repositories": sum(1 for row in rows if row.get("repository_url")),
        "inspected": sum(1 for row in rows if row.get("status") == "inspected"),
        "artifacts": [
            str(csv_path.relative_to(review_dir)),
            str(report_path.relative_to(review_dir)),
        ],
    }
    (output_dir / "paper-code-audit.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    parser.add_argument(
        "--inspect-remote",
        action="store_true",
        help="Inspect public GitHub metadata and file names without cloning or executing code.",
    )
    parser.add_argument("--max-papers", type=int, default=0, help="Optional cap; zero audits every focal study.")
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    if not review_dir.is_dir():
        raise SystemExit(f"Review directory not found: {review_dir}")
    print(json.dumps(run(review_dir, inspect_remote=args.inspect_remote, max_papers=max(args.max_papers, 0)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
