"""Tests for optional institutional scholarly-source adapters."""

from __future__ import annotations

import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from institutional_sources import (  # noqa: E402
    SOURCE_CONFIG,
    active_source_plan,
    build_request,
    normalize_doi,
    search_sources,
)


def test_missing_credentials_skip_sources_without_breaking_open_search() -> None:
    plan = active_source_plan(["agent systems"], {})

    raw, logs, normalized = search_sources(
        plan,
        "2024-01-01",
        "2026-12-31",
        "agent systems",
        {},
        lambda *_args, **_kwargs: {},
    )

    assert normalized == []
    assert all(raw[source] == [] for source in SOURCE_CONFIG)
    assert len(logs) == len(SOURCE_CONFIG)
    assert all("optional source skipped" in row["notes"] for row in logs)


def test_request_secrets_never_enter_search_logs() -> None:
    secret = "institutional-secret-value"
    env = {
        config["key"]: secret
        for config in SOURCE_CONFIG.values()
    }
    plan = active_source_plan(["agent systems"], env, limit=1)

    def failing_fetch(url, *, headers, timeout):
        del headers, timeout
        raise RuntimeError(f"Provider rejected {url}")

    _raw, logs, _normalized = search_sources(
        plan,
        "2024-01-01",
        "2026-12-31",
        "agent systems",
        env,
        failing_fetch,
    )

    assert logs
    assert secret not in str(logs)
    assert all(row["notes"] == "error: RuntimeError" for row in logs)


def test_each_request_uses_the_official_authentication_shape() -> None:
    env = {
        "HERMES_SCOPUS_API_KEY": "scopus-key",
        "HERMES_WOS_API_KEY": "wos-key",
        "HERMES_EMBASE_API_KEY": "embase-key",
        "HERMES_IEEE_API_KEY": "ieee-key",
        "HERMES_ELSEVIER_INST_TOKEN": "institution-token",
    }

    scopus_url, scopus_headers = build_request(
        "scopus",
        "agent systems",
        "2024-01-01",
        "2026-12-31",
        env,
    )
    wos_url, wos_headers = build_request(
        "wos",
        "agent systems",
        "2024-01-01",
        "2026-12-31",
        env,
    )
    ieee_url, ieee_headers = build_request(
        "ieee",
        "agent systems",
        "2024-01-01",
        "2026-12-31",
        env,
    )

    assert "api.elsevier.com/content/search/scopus" in scopus_url
    assert scopus_headers["X-ELS-APIKey"] == "scopus-key"
    assert scopus_headers["X-ELS-Insttoken"] == "institution-token"
    assert "api.clarivate.com/apis/wos-starter/v1/documents" in wos_url
    assert wos_headers["X-ApiKey"] == "wos-key"
    assert "ieeexploreapi.ieee.org/api/v1/search/articles" in ieee_url
    assert "apikey=ieee-key" in ieee_url
    assert ieee_headers["Accept"] == "application/json"


def test_only_real_dois_survive_provider_identifier_normalization() -> None:
    assert normalize_doi("https://doi.org/10.1000/example") == "10.1000/example"
    assert normalize_doi("SCOPUS_ID:85123456789") == ""
