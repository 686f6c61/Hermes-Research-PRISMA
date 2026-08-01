"""Network safety helpers for retrieving scientific full text.

The review pipeline consumes URLs returned by external metadata providers. A
record is therefore untrusted input even when it came from a scholarly API.
This module keeps PDF retrieval bounded and prevents requests to local,
link-local, reserved, or otherwise non-public network destinations.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import BinaryIO, Callable, Iterable

DEFAULT_MAX_PDF_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 3
CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class UnsafeDownloadError(RuntimeError):
    """Raised when a full-text request violates the network policy."""


@dataclass(frozen=True)
class DownloadedPDF:
    """A validated PDF response and its credential-free provenance."""

    body: bytes
    content_type: str
    final_url: str
    license_hint: str


def env_truthy(name: str, default: bool = False) -> bool:
    """Read a conservative boolean environment option."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def max_pdf_bytes() -> int:
    """Return the response limit, capped to a defensible upper bound."""

    raw = os.environ.get("HERMES_FULLTEXT_MAX_BYTES", "").strip()
    try:
        configured = int(raw) if raw else DEFAULT_MAX_PDF_BYTES
    except ValueError:
        configured = DEFAULT_MAX_PDF_BYTES
    return max(1024, min(configured, 200 * 1024 * 1024))


def is_public_address(address: str) -> bool:
    """Return True only for globally routable IP addresses."""

    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip in CGNAT_NETWORK or ip in BENCHMARK_NETWORK:
        return False
    return bool(ip.is_global)


def resolve_public_addresses(
    hostname: str,
    *,
    resolver: Callable[..., Iterable[tuple]] = socket.getaddrinfo,
) -> tuple[str, ...]:
    """Resolve a host and reject it when any answer is not public.

    Rejecting mixed public/private DNS answers prevents a provider-controlled
    hostname from selecting an internal destination during connection retries.
    """

    try:
        answers = resolver(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeDownloadError(f"Unable to resolve full-text host: {hostname}") from exc
    addresses = tuple(sorted({str(answer[4][0]) for answer in answers if answer[4]}))
    if not addresses:
        raise UnsafeDownloadError(f"Full-text host has no usable address: {hostname}")
    unsafe = [address for address in addresses if not is_public_address(address)]
    if unsafe:
        raise UnsafeDownloadError(f"Full-text host resolves to a non-public address: {hostname}")
    return addresses


def validate_public_url(
    url: str,
    *,
    resolver: Callable[..., Iterable[tuple]] = socket.getaddrinfo,
) -> urllib.parse.SplitResult:
    """Validate scheme, authority, port, credentials, and DNS destination."""

    try:
        parsed = urllib.parse.urlsplit((url or "").strip())
    except ValueError as exc:
        raise UnsafeDownloadError("Full-text URL is malformed") from exc
    allowed_schemes = {"https"}
    if env_truthy("HERMES_FULLTEXT_ALLOW_HTTP", False):
        allowed_schemes.add("http")
    if parsed.scheme.lower() not in allowed_schemes:
        raise UnsafeDownloadError("Full-text URL must use HTTPS")
    if not parsed.hostname:
        raise UnsafeDownloadError("Full-text URL has no hostname")
    if parsed.username or parsed.password:
        raise UnsafeDownloadError("Credentials are not allowed in full-text URLs")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeDownloadError("Full-text URL contains an invalid port") from exc
    expected_port = 443 if parsed.scheme.lower() == "https" else 80
    if port not in {None, expected_port} and not env_truthy("HERMES_FULLTEXT_ALLOW_CUSTOM_PORTS", False):
        raise UnsafeDownloadError("Full-text URL uses a non-standard port")
    resolve_public_addresses(parsed.hostname, resolver=resolver)
    return parsed


def read_bounded(stream: BinaryIO, limit: int) -> bytes:
    """Read a response without allowing unbounded memory consumption."""

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UnsafeDownloadError(f"Full-text response exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Revalidate every redirect and stop redirect loops."""

    def __init__(self, max_redirects: int = DEFAULT_MAX_REDIRECTS) -> None:
        super().__init__()
        self.max_redirects = max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirects = int(getattr(req, "_hermes_redirects", 0)) + 1
        if redirects > self.max_redirects:
            raise UnsafeDownloadError("Full-text request exceeded the redirect limit")
        validate_public_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            setattr(redirected, "_hermes_redirects", redirects)
        return redirected


def _license_hint(headers) -> str:  # noqa: ANN001
    """Extract a bounded rights hint without interpreting legal meaning."""

    value = str(headers.get("License") or headers.get("Link") or "").strip()
    return " ".join(value.split())[:1000]


def download_pdf(
    url: str,
    *,
    opener=None,  # noqa: ANN001
    limit: int | None = None,
) -> DownloadedPDF:
    """Download one public PDF with redirect, type, and size enforcement."""

    validate_public_url(url)
    response_limit = limit or max_pdf_bytes()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HermesResearchFullText/0.5",
            "Accept": "application/pdf,application/octet-stream;q=0.8",
        },
    )
    client = opener or urllib.request.build_opener(SafeRedirectHandler())
    with client.open(request, timeout=20) as response:
        final_url = str(response.geturl() or url)
        # Re-resolve after redirects and immediately before consuming the body.
        validate_public_url(final_url)
        content_length = str(response.headers.get("Content-Length") or "").strip()
        if content_length.isdigit() and int(content_length) > response_limit:
            raise UnsafeDownloadError(f"Full-text response exceeds {response_limit} bytes")
        body = read_bounded(response, response_limit)
        content_type = str(response.headers.get("Content-Type") or "").strip()
        license_hint = _license_hint(response.headers)
    if not body.startswith(b"%PDF"):
        raise UnsafeDownloadError("Full-text response is not a PDF")
    return DownloadedPDF(
        body=body,
        content_type=content_type,
        final_url=final_url,
        license_hint=license_hint,
    )
