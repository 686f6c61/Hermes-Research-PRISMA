"""Regression tests for topic-independent manuscript synthesis."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "publication_audit.py"


def load_publication_module():
    """Load the standalone publication generator without installing the bundle."""
    spec = importlib.util.spec_from_file_location("publication_audit_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generic_synthesis_uses_topic_without_topic_specific_state() -> None:
    publication = load_publication_module()

    lines = publication.domain_substantive_synthesis_lines(
        "generic",
        "adopción de tecnología en organizaciones",
        [{"title_original": "A comparative organizational study"}],
        ["10.1000/example"],
    )

    rendered = "\n".join(lines)
    assert "Síntesis sustantiva de resultados" in rendered
    assert "adopción de tecnología en organizaciones" in rendered


def test_management_workload_synthesis_uses_complete_work_accounting() -> None:
    publication = load_publication_module()
    workload_row = {
        "title_original": "Artificial intelligence and workload productivity",
        "key_findings": "AI reduces execution time but increases supervision effort.",
        "method_used": "Longitudinal field study",
    }

    lines = publication.domain_substantive_synthesis_lines(
        "management",
        "impacto de la IA en la carga de trabajo",
        [workload_row],
        ["10.1000/workload"],
    )

    rendered = "\n".join(lines)
    assert "desplazamiento del esfuerzo" in rendered
    assert "reducción neta y general del trabajo humano" in rendered
