"""Static checks for the public landing and installation guide."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
pytestmark = pytest.mark.skipif(
    not LANDING.is_dir(),
    reason="The runtime release bundle intentionally excludes the standalone landing.",
)


def _read(name: str) -> str:
    return (LANDING / name).read_text(encoding="utf-8")


def test_public_pages_have_unique_metadata_and_valid_structured_data() -> None:
    pages = [
        _read("index.html"),
        _read("instalacion.html"),
        _read("metodologia.html"),
        _read("entregables.html"),
        _read("atlas-estructural.html"),
    ]
    titles = set()
    canonicals = set()

    for page in pages:
        title = re.search(r"<title>(.*?)</title>", page, flags=re.DOTALL)
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page)
        json_ld = re.search(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            page,
            flags=re.DOTALL,
        )
        assert title and title.group(1).strip()
        assert canonical and canonical.group(1).startswith("https://")
        assert json_ld
        json.loads(json_ld.group(1))
        titles.add(title.group(1).strip())
        canonicals.add(canonical.group(1))

    assert len(titles) == len(pages)
    assert len(canonicals) == len(pages)


def test_landing_links_to_the_installation_guide() -> None:
    page = _read("index.html")
    assert 'href="/instalacion.html"' in page
    assert 'href="/metodologia.html"' in page
    assert 'href="/entregables.html"' in page
    assert ">Bajar de GitHub</a>" in page


def test_public_pages_link_to_the_versioned_public_release() -> None:
    release_url = "https://github.com/686f6c61/Hermes-Research-PRISMA/releases/tag/v0.4.1"
    assert release_url in _read("index.html")
    assert release_url in _read("instalacion.html")
    assert release_url in _read("entregables.html")


def test_every_public_page_displays_the_current_version_in_header_and_footer() -> None:
    for name in (
        "index.html",
        "instalacion.html",
        "metodologia.html",
        "entregables.html",
        "atlas-estructural.html",
    ):
        page = _read(name)
        header = page.split('<header class="site-header">', 1)[1].split("</header>", 1)[0]
        footer = page.split('<footer class="site-footer">', 1)[1].split("</footer>", 1)[0]
        assert "0.4.1" in header
        assert "0.4.1" in footer


def test_methodology_and_delivery_pages_explain_the_new_contracts() -> None:
    methodology = _read("metodologia.html")
    delivery = _read("entregables.html")

    for expected in (
        "Cinco contratos",
        "Seis perfiles",
        "Una cita no basta",
        "Autonomous",
        "Adjudicated",
    ):
        assert expected in methodology

    for expected in (
        "Doce bloques",
        "index.html",
        "deliverables-manifest.json",
        "claim-evidence-ledger.csv",
        "Un manuscrito no es un PASS",
    ):
        assert expected in delivery


def test_public_footers_only_link_the_requested_social_profile() -> None:
    for name in (
        "index.html",
        "instalacion.html",
        "metodologia.html",
        "entregables.html",
        "atlas-estructural.html",
    ):
        footer = _read(name).split('<footer class="site-footer">', 1)[1]
        assert "x.com/686f6c61" in footer
        assert "github.com/686f6c61" not in footer


def test_social_cards_are_current_page_specific_and_release_ready() -> None:
    cards = {
        "index.html": "hermes-prisma-og.png",
        "instalacion.html": "hermes-prisma-og.png",
        "metodologia.html": "hermes-methodology-og.png",
        "entregables.html": "hermes-deliverables-og.png",
    }

    for page_name, image_name in cards.items():
        page = _read(page_name)
        assert f"/assets/images/{image_name}?v=20260731-5" in page
        image = LANDING / "assets" / "images" / image_name
        payload = image.read_bytes()
        assert payload[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", payload[16:24])
        assert (width, height) == (1200, 630)


def test_landing_declares_methodological_scope_and_limits() -> None:
    page = _read("index.html")
    for expected in (
        "DÓNDE TRABAJA BIEN",
        "PICO · PICOS",
        "SISTEMA · BENCHMARK",
        "SPIDER · PEO · PICo",
        "CIMO · TCCM",
        "DELIMITACIÓN ACTUAL",
        "requieren acceso propio",
    ):
        assert expected in page


def test_process_timeline_does_not_cross_the_section_heading() -> None:
    styles = _read("styles.css")
    assert ".process-list::before" in styles
    assert ".process::before" not in styles
    assert "--ruler: clamp(0.55rem, 2vw, 2.2rem);" in styles


def test_installation_guide_closes_with_product_value() -> None:
    page = _read("instalacion.html")
    for expected in (
        "DECIDE CON EVIDENCIA",
        "Descubre qué sabe realmente la literatura sobre tu pregunta.",
        "consensos, las contradicciones",
        "publicar con una base verificable",
        "Descargar Research Pack",
        'href="/#entregables"',
    ):
        assert expected in page


def test_landing_explains_how_hermes_guides_the_installation() -> None:
    home = _read("index.html")
    installation = _read("instalacion.html")
    for expected in (
        "Deja que Hermes te ayude a instalar Hermes.",
        "Setup_Hermes.txt",
        "Instalar con Hermes",
    ):
        assert expected in home
    for expected in (
        "Que Hermes te ayude a instalarlo todo.",
        "Setup_Hermes.txt",
        "todas las pruebas de aceptación",
        "nunca deben pegarse en la conversación",
    ):
        assert expected in installation
