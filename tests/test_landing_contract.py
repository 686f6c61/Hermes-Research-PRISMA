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
        _read("confianza.html"),
        _read("faq.html"),
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
    assert 'href="/confianza.html"' in page
    assert 'href="/faq.html"' in page
    assert ">Bajar de GitHub</a>" in page


def test_public_pages_link_to_the_versioned_public_release() -> None:
    release_url = "https://github.com/686f6c61/Hermes-Research-PRISMA/releases/tag/v0.5.1"
    assert release_url in _read("index.html")
    assert release_url in _read("instalacion.html")
    assert release_url in _read("entregables.html")
    assert release_url in _read("confianza.html")


def test_every_public_page_displays_the_current_version_in_header_and_footer() -> None:
    for name in (
        "index.html",
        "instalacion.html",
        "metodologia.html",
        "entregables.html",
        "atlas-estructural.html",
        "confianza.html",
        "faq.html",
    ):
        page = _read(name)
        header = page.split('<header class="site-header">', 1)[1].split("</header>", 1)[0]
        footer = page.split('<footer class="site-footer">', 1)[1].split("</footer>", 1)[0]
        assert "0.5.1" in header
        assert "0.5.1" in footer


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
        "confianza.html",
        "faq.html",
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
        "confianza.html": "hermes-trust-og.png",
    }

    for page_name, image_name in cards.items():
        page = _read(page_name)
        expected_cache_key = "20260801-051"
        assert f"/assets/images/{image_name}?v={expected_cache_key}" in page
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
        "MÁS PROBADO",
        "Técnico + biomédico",
        "VALIDACIÓN ACTIVA",
    ):
        assert expected in page


def test_home_distinguishes_scientific_stages_runtime_phases_and_deliverables() -> None:
    page = _read("index.html")
    assert "Doce etapas científicas. Siete macrofases reanudables." in page
    assert len(re.findall(r'class="process-number">\d{2}</div>', page)) == 12
    assert "doce bloques navegables" in page


def test_installation_maps_third_party_services_without_making_nan_mandatory() -> None:
    page = _read("instalacion.html")
    for expected in (
        "NaN.builders",
        "millones de tokens",
        "Sin cobro por token",
        "modelos del clúster sin tope de uso",
        "no es un requisito del producto",
        "OpenAlex, Crossref, OpenAIRE, Europe PMC y arXiv",
        "Scopus, Web of Science, Embase e IEEE Xplore",
        "PsycINFO, CINAHL, Cochrane, ACM Digital Library, ERIC",
        "Docling + Poppler",
    ):
        assert expected in page
    assert "https://analytics.686f6c61.dev/q/imevwWq8X" in page
    assert 'rel="sponsored noopener noreferrer"' in page


def test_faq_covers_cost_local_multimodal_models_and_scientific_boundaries() -> None:
    page = _read("faq.html")
    for expected in (
        "¿Cuántos millones de tokens va a consumir una revisión?",
        "Su tarifa es plana",
        "no factura por token",
        "¿Puedo ejecutar modelos multimodales en local?",
        "Un modelo multimodal local",
        "¿Necesito tres modelos y tres proveedores?",
        "¿Por qué se menciona NaN.builders?",
        "¿Qué ocurre si los dos juicios no coinciden?",
        "¿Qué recibo al final?",
        "¿Hermes garantiza que una revista aceptará el artículo?",
    ):
        assert expected in page
    assert "https://analytics.686f6c61.dev/q/imevwWq8X" in page
    assert 'rel="sponsored noopener noreferrer"' in page
    assert page.count("https://analytics.686f6c61.dev/q/imevwWq8X") >= 6
    assert page.count('rel="sponsored noopener noreferrer"') >= 6
    assert "afiliado" not in page.lower()
    assert "Crear cuenta en NaN.builders" in page


def test_trust_page_explains_every_v050_control_boundary() -> None:
    page = _read("confianza.html")
    for expected in (
        "waiting_for_researcher",
        "Un desacuerdo no puede convertirse en un KO automático.",
        "PDF seguro",
        "Watchdog estricto",
        "Gold operacional",
        "Procedencia de modelos",
        "Scopus, Web of Science, Embase e IEEE Xplore",
        "QUÉ SIGUE SIENDO HUMANO",
        "no envía el artículo a la revista",
    ):
        assert expected in page


def test_contact_requires_four_interactions_and_is_not_static_plaintext() -> None:
    public_pages = (
        "index.html",
        "instalacion.html",
        "metodologia.html",
        "entregables.html",
        "atlas-estructural.html",
        "confianza.html",
        "faq.html",
    )
    script = _read("script.js")
    assert "hermes@" not in script
    assert "contactPayload" in script
    assert "step < 3" in script
    assert "Paso 4 de 4" in script

    for name in public_pages:
        page = _read(name)
        assert "hermes@" not in page
        assert "data-contact-gate" in page
        assert "data-contact-trigger" in page
        assert "<small>4 pasos</small>" in page
        assert "/script.js?v=20260801-051" in page

    styles = _read("styles.css")
    assert ".contact-gate {" in styles
    assert "width: 220px;" in styles
    assert "min-height: 88px;" in styles
    assert "height: 56px;" in styles
    assert "height: 28px;" in styles


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
