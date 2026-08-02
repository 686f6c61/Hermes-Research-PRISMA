#!/usr/bin/env python3
"""Build a private cross-review catalog and advisory context for one review.

The catalog helps a new project discover prior DOI, queries, and constructs.
Prior inclusion or exclusion decisions are never imported automatically.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

from artifact_contracts import write_json_atomic

STOPWORDS = {
    "about",
    "after",
    "among",
    "and",
    "como",
    "con",
    "del",
    "desde",
    "entre",
    "estudio",
    "estudios",
    "para",
    "por",
    "que",
    "review",
    "sobre",
    "the",
    "una",
    "using",
}


def now_iso() -> str:
    """Return a timezone-aware generation timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def normalize(value: object) -> str:
    """Fold text for overlap checks."""
    folded = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in folded if not unicodedata.combining(char)).lower()


def clean_doi(value: object) -> str:
    """Normalize a public DOI."""
    doi = " ".join(str(value or "").split()).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi if doi.startswith("10.") and "/" in doi else ""


def tokens(value: object) -> set[str]:
    """Return material tokens for query and construct overlap."""
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", normalize(value))
        if token not in STOPWORDS and not token.isdigit()
    }


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    """Read an optional CSV."""
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: pathlib.Path) -> dict[str, object]:
    """Read a JSON object with a safe fallback."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def intake_topic(review_dir: pathlib.Path) -> str:
    """Read the machine contract first and retain Markdown compatibility."""
    intake = read_json(review_dir / "protocol" / "intake.json")
    if intake.get("topic"):
        return " ".join(str(intake["topic"]).split())
    path = review_dir / "protocol" / "intake.md"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
    match = re.search(r"(?im)^-\s*Tema:\s*(.+)$", text)
    return " ".join(match.group(1).split()) if match else review_dir.name


def review_mode(review_dir: pathlib.Path) -> str:
    """Read the declared or inferred methodological mode."""
    payload = read_json(review_dir / "protocol" / "review-mode.json")
    return str(payload.get("mode") or payload.get("primary_mode") or "")


def review_queries(review_dir: pathlib.Path) -> list[str]:
    """Collect exact prior search strings for discovery, not silent reuse."""
    values: set[str] = set()
    for row in read_csv(review_dir / "searches" / "search-log.csv"):
        query = " ".join(str(row.get("query_string") or row.get("query") or "").split())
        if query:
            values.add(query)
    return sorted(values)


def review_dois(review_dir: pathlib.Path) -> list[str]:
    """Collect DOI identities from the master corpus."""
    return sorted(
        {
            doi
            for row in read_csv(review_dir / "records" / "master-records.csv")
            if (doi := clean_doi(row.get("assigned_doi") or row.get("doi")))
        }
    )


def review_decisions(review_dir: pathlib.Path) -> dict[str, dict[str, str]]:
    """Preserve prior decisions as advisory evidence only."""
    decisions: dict[str, dict[str, str]] = {}
    for stage, path in (
        ("title_abstract", review_dir / "screening" / "title-abstract.csv"),
        ("full_text", review_dir / "screening" / "full-text.csv"),
    ):
        for row in read_csv(path):
            doi = clean_doi(row.get("assigned_doi") or row.get("doi"))
            if not doi:
                continue
            decisions[doi] = {
                "stage": stage,
                "decision": str(row.get("decision") or ""),
                "reason": str(row.get("reason") or ""),
                "reason_detail": str(row.get("reason_detail") or ""),
            }
    return decisions


def review_constructs(review_dir: pathlib.Path) -> list[str]:
    """Collect reusable concepts without copying prose or private notes."""
    counts: Counter[str] = Counter()
    fields = (
        "keywords_normalized",
        "theory_framework",
        "variables_dependent",
        "variables_independent",
        "tasks_or_domains",
        "method_used",
        "security_harness_name",
        "control_architecture",
        "enforcement_point",
        "threat_model",
        "attack_type",
        "attacker_adaptivity",
        "security_metrics",
        "failure_modes",
    )
    for row in read_csv(review_dir / "extraction" / "extraction-table.csv"):
        for field in fields:
            for part in re.split(r"[;|,]", str(row.get(field) or "")):
                value = " ".join(part.split())
                if len(value) >= 3:
                    counts[value] += 1
    return [value for value, _count in counts.most_common(80)]


def review_entry(review_dir: pathlib.Path) -> dict[str, object]:
    """Build one private, path-free catalog entry."""
    topic = intake_topic(review_dir)
    dois = review_dois(review_dir)
    queries = review_queries(review_dir)
    constructs = review_constructs(review_dir)
    fingerprint = hashlib.sha256(
        json.dumps(
            {"topic": topic, "dois": dois, "queries": queries, "constructs": constructs},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return {
        "review_id": review_dir.name,
        "topic": topic,
        "mode": review_mode(review_dir),
        "queries": queries,
        "dois": dois,
        "constructs": constructs,
        "decisions": review_decisions(review_dir),
        "content_fingerprint": fingerprint,
    }


def review_directories(workspace_root: pathlib.Path) -> list[pathlib.Path]:
    """Find review projects without descending into unrelated folders."""
    return sorted(
        child
        for child in workspace_root.iterdir()
        if child.is_dir()
        and child.name.startswith("systematic-review")
        and child.name != "systematic-review-template"
    )


def jaccard(left: set[str], right: set[str]) -> float:
    """Return token overlap with an explicit zero for empty sets."""
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def advisory_context(current: dict[str, object], catalog: list[dict[str, object]]) -> dict[str, object]:
    """Compare the current review with prior work without inheriting decisions."""
    current_dois = set(current.get("dois") or [])
    current_tokens = tokens(current.get("topic"))
    for query in current.get("queries") or []:
        current_tokens.update(tokens(query))
    current_constructs = {normalize(value) for value in current.get("constructs") or []}
    related: list[dict[str, object]] = []
    prior_decisions: list[dict[str, str]] = []
    for entry in catalog:
        if entry.get("review_id") == current.get("review_id"):
            continue
        entry_dois = set(entry.get("dois") or [])
        entry_tokens = tokens(entry.get("topic"))
        for query in entry.get("queries") or []:
            entry_tokens.update(tokens(query))
        entry_constructs = {normalize(value) for value in entry.get("constructs") or []}
        overlap_dois = sorted(current_dois & entry_dois)
        query_overlap = jaccard(current_tokens, entry_tokens)
        shared_constructs = sorted(current_constructs & entry_constructs)
        if overlap_dois or query_overlap >= 0.08 or shared_constructs:
            source_hash = hashlib.sha256(str(entry.get("review_id") or "").encode()).hexdigest()[:12]
            related.append(
                {
                    "source_review": f"review-{source_hash}",
                    "topic": entry.get("topic", ""),
                    "mode": entry.get("mode", ""),
                    "query_token_overlap": round(query_overlap, 4),
                    "overlapping_dois": overlap_dois,
                    "shared_constructs": shared_constructs[:20],
                    "prior_queries": list(entry.get("queries") or [])[:10],
                }
            )
            decisions = entry.get("decisions") if isinstance(entry.get("decisions"), dict) else {}
            for doi in overlap_dois:
                decision = decisions.get(doi)
                if not isinstance(decision, dict):
                    continue
                prior_decisions.append(
                    {
                        "doi": doi,
                        "source_review": f"review-{source_hash}",
                        "stage": str(decision.get("stage") or ""),
                        "prior_decision": str(decision.get("decision") or ""),
                        "prior_reason": str(decision.get("reason") or ""),
                        "reuse_policy": "advisory_only_reassess_under_current_protocol",
                    }
                )
    related.sort(
        key=lambda row: (
            -len(row["overlapping_dois"]),
            -float(row["query_token_overlap"]),
            str(row["source_review"]),
        )
    )
    return {
        "schema_version": "hermes.prior-research-context/v1",
        "generated_at": now_iso(),
        "current_review": current.get("review_id"),
        "related_reviews": related,
        "prior_decision_signals": prior_decisions,
        "decision_reuse": "forbidden",
        "instruction": (
            "Use prior queries, DOI, and constructs as discovery leads only. "
            "Reassess every record under the current frozen protocol."
        ),
    }


def write_context_markdown(path: pathlib.Path, context: dict[str, object]) -> pathlib.Path:
    """Write a human-readable private context note."""
    related = context.get("related_reviews") or []
    signals = context.get("prior_decision_signals") or []
    lines = [
        "# Contexto de investigaciones anteriores",
        "",
        "Este documento es privado y funciona como ayuda de descubrimiento. Ninguna decisión previa se "
        "hereda: cada DOI debe evaluarse otra vez con el protocolo actual.",
        "",
        f"- Revisiones relacionadas: {len(related)}",
        f"- DOI con señales de decisión previa: {len(signals)}",
        "",
        "## Revisiones relacionadas",
    ]
    for item in related:
        lines.append(
            f"- `{item['source_review']}`: solapamiento de consulta {item['query_token_overlap']}; "
            f"DOI compartidos {len(item['overlapping_dois'])}; constructos compartidos "
            f"{len(item['shared_constructs'])}."
        )
    if not related:
        lines.append("- No se detectó conocimiento previo suficientemente próximo.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build(review_dir: pathlib.Path, workspace_root: pathlib.Path) -> dict[str, object]:
    """Refresh the private catalog and write context for the active review."""
    catalog_entries = [review_entry(path) for path in review_directories(workspace_root)]
    catalog = {
        "schema_version": "hermes.research-memory/v1",
        "generated_at": now_iso(),
        "private": True,
        "decision_reuse": "forbidden",
        "reviews": catalog_entries,
    }
    catalog_path = workspace_root / ".hermes" / "research-memory.json"
    write_json_atomic(catalog_path, catalog)
    current = next(
        (entry for entry in catalog_entries if entry.get("review_id") == review_dir.name),
        review_entry(review_dir),
    )
    context = advisory_context(current, catalog_entries)
    context_path = write_json_atomic(review_dir / "notes" / "prior-research-context.json", context)
    markdown_path = write_context_markdown(review_dir / "notes" / "prior-research-context.md", context)
    return {
        "schema_version": "hermes.research-memory-build/v1",
        "reviews": len(catalog_entries),
        "related_reviews": len(context["related_reviews"]),
        "prior_decision_signals": len(context["prior_decision_signals"]),
        "private_catalog": str(catalog_path),
        "context": str(context_path),
        "context_markdown": str(markdown_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=pathlib.Path)
    parser.add_argument("--workspace-root", type=pathlib.Path)
    args = parser.parse_args()
    review_dir = args.review_dir.expanduser().resolve()
    workspace_root = (args.workspace_root or review_dir.parent).expanduser().resolve()
    if not review_dir.is_dir():
        raise SystemExit(f"Review directory not found: {review_dir}")
    if not workspace_root.is_dir():
        raise SystemExit(f"Workspace root not found: {workspace_root}")
    print(json.dumps(build(review_dir, workspace_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
