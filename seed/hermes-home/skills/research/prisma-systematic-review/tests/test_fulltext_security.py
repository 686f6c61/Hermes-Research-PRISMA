"""Security regression tests for scholarly full-text retrieval."""

from __future__ import annotations

import io
import pathlib
import socket
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from fulltext_security import (
    UnsafeDownloadError,
    is_public_address,
    read_bounded,
    resolve_public_addresses,
    validate_public_url,
)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "172.16.0.1",
        "192.168.1.1",
        "100.64.0.1",
        "198.18.0.1",
        "::1",
        "fe80::1",
    ],
)
def test_internal_and_special_addresses_are_rejected(address: str) -> None:
    assert is_public_address(address) is False


def test_public_address_is_allowed() -> None:
    assert is_public_address("1.1.1.1") is True


def test_mixed_dns_answer_is_rejected() -> None:
    def resolver(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    with pytest.raises(UnsafeDownloadError, match="non-public"):
        resolve_public_addresses("papers.example", resolver=resolver)


def test_http_and_embedded_credentials_are_rejected(monkeypatch) -> None:
    monkeypatch.delenv("HERMES_FULLTEXT_ALLOW_HTTP", raising=False)
    with pytest.raises(UnsafeDownloadError, match="HTTPS"):
        validate_public_url("http://example.com/paper.pdf")
    with pytest.raises(UnsafeDownloadError, match="Credentials"):
        validate_public_url("https://user:password@example.com/paper.pdf")


def test_response_reader_stops_above_limit() -> None:
    with pytest.raises(UnsafeDownloadError, match="exceeds"):
        read_bounded(io.BytesIO(b"%PDF" + (b"x" * 20)), 10)
