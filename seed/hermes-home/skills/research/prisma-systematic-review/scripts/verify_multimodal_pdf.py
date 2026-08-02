#!/usr/bin/env python3
"""Verify configured vision-capable models against a rendered scientific PDF page."""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import subprocess
import tempfile

from cloud_inference import (
    MODEL_ROLE_CAPABILITIES,
    configured_research_model_roles,
    post_openai_compatible_chat,
    resolve_inference_runtime,
)
from model_capability_probe import resolve_private_env_values

SELF_TEST_TEX = r"""
\documentclass[11pt]{article}
\usepackage[a4paper,margin=18mm]{geometry}
\usepackage[table]{xcolor}
\usepackage{array}
\pagestyle{empty}
\begin{document}
\begin{center}
{\LARGE\bfseries EVIDENCIA MULTIMODAL}\\[4mm]
{\large CÓDIGO VISUAL: H7 \quad MUESTRA TOTAL: 42}
\end{center}

\vspace{5mm}
\noindent
\colorbox{cyan!35}{\parbox{0.28\linewidth}{\centering\bfseries ENTRADA}}
\hfill$\longrightarrow$\hfill
\colorbox{yellow!55}{\parbox{0.28\linewidth}{\centering\bfseries ANÁLISIS}}
\hfill$\longrightarrow$\hfill
\colorbox{green!35}{\parbox{0.28\linewidth}{\centering\bfseries RESULTADO}}

\vspace{9mm}
\begin{center}
\renewcommand{\arraystretch}{1.5}
\begin{tabular}{|>{\bfseries}l|r|}
\hline
\rowcolor{black!12} Condición & Media observada \\
\hline
A & 18.2 \\
B & 37.4 \\
\hline
\end{tabular}
\end{center}

\vfill
\noindent\textbf{Regla de lectura:} responde usando el código visual, el tamaño
de la muestra y la media de la condición B.
\end{document}
"""

MAX_RESPONSE_TOKENS = 1024


def run_checked(command: list[str], *, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run one document command and expose useful diagnostics on failure."""
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"Command failed: {' '.join(command)}")
    return completed


def extract_message_content(response: dict[str, object]) -> str:
    """Return text from a standard OpenAI-compatible chat response."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Inference response did not contain choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    raise RuntimeError("Inference response did not contain message text")


def answer_contains_expected_values(answer: str) -> bool:
    """Accept formatting differences while requiring every visual fact."""
    normalized = re.sub(r"\s+", " ", answer).upper()
    return all(token in normalized for token in ("H7", "42", "37.4"))


def normalized_anchor_tokens(value: str) -> set[str]:
    """Return meaningful comparable tokens from OCR or model output."""
    dehyphenated = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    tokens = {
        token
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9-]{2,}", dehyphenated.lower())
    }
    stopwords = {
        "and",
        "con",
        "del",
        "entre",
        "para",
        "por",
        "the",
        "una",
    }
    return tokens - stopwords


def first_page_title_anchor(extracted_text: str) -> str:
    """Read the first visible text block as the expected document title."""
    blocks = [
        re.sub(r"(?<=\w)-\s+(?=\w)", "", " ".join(block.split()))
        for block in re.split(r"\n\s*\n", extracted_text)
        if len(" ".join(block.split())) >= 20
    ]
    if not blocks:
        raise RuntimeError("The PDF first page did not expose a usable title block")
    return blocks[0]


def answer_matches_title_anchor(answer: str, expected_anchor: str) -> bool:
    """Require substantial title-token agreement for a real scientific PDF."""
    expected = normalized_anchor_tokens(expected_anchor)
    observed = normalized_anchor_tokens(answer)
    if len(expected) < 4:
        return False
    required = max(4, int(len(expected) * 0.55 + 0.999))
    return len(expected & observed) >= required


def infer_review_dir(pdf_path: pathlib.Path | None) -> pathlib.Path | None:
    """Find the owning review from a manuscript PDF path."""
    if pdf_path is None:
        return None
    for candidate in [pdf_path.parent, *pdf_path.parents]:
        if (candidate / "protocol" / "intake.json").is_file():
            return candidate
    return None


def build_self_test_pdf(workdir: pathlib.Path) -> pathlib.Path:
    """Create a deterministic one-page PDF with text, a diagram, and a table."""
    tex_path = workdir / "multimodal-probe.tex"
    tex_path.write_text(SELF_TEST_TEX.strip() + "\n", encoding="utf-8")
    run_checked(
        [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex_path.name,
        ],
        cwd=workdir,
    )
    return workdir / "multimodal-probe.pdf"


def render_pdf(
    pdf_path: pathlib.Path,
    workdir: pathlib.Path,
    *,
    require_self_test_values: bool,
) -> tuple[str, pathlib.Path]:
    """Extract the text layer and render the first PDF page to PNG."""
    text_path = workdir / "multimodal-probe.txt"
    image_prefix = workdir / "multimodal-probe-page"
    run_checked(["pdftotext", "-layout", str(pdf_path), str(text_path)], cwd=workdir)
    run_checked(
        ["pdftoppm", "-f", "1", "-singlefile", "-r", "180", "-png", str(pdf_path), str(image_prefix)],
        cwd=workdir,
    )
    extracted_text = text_path.read_text(encoding="utf-8", errors="replace")
    image_path = image_prefix.with_suffix(".png")
    if require_self_test_values and not answer_contains_expected_values(extracted_text):
        raise RuntimeError("The PDF text layer did not preserve H7, 42, and 37.4")
    if not require_self_test_values:
        first_page_title_anchor(extracted_text)
    if not image_path.exists() or image_path.stat().st_size < 10_000:
        raise RuntimeError("The rendered PDF page is missing or unexpectedly small")
    return extracted_text, image_path


def verify_models(
    image_path: pathlib.Path,
    env_values: dict[str, str],
    *,
    expected_title: str = "",
    review_dir: pathlib.Path | None = None,
) -> list[dict[str, object]]:
    """Ask only roles that require vision to read facts from the page image."""
    base_url, api_key = resolve_inference_runtime(env_values)
    if not api_key:
        raise RuntimeError("HERMES_INFERENCE_API_KEY is required")
    role_models = configured_research_model_roles(env_values)
    if not role_models:
        raise RuntimeError("At least one HERMES_MODEL_* value is required")
    vision_roles = {
        role: model
        for role, model in role_models.items()
        if "vision" in MODEL_ROLE_CAPABILITIES.get(role, ())
    }
    if not vision_roles:
        raise RuntimeError("HERMES_MODEL_VISION is required for the multimodal probe")

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"
    results: list[dict[str, object]] = []
    if expected_title:
        prompt = (
            "Lee únicamente la primera página mostrada y transcribe el título principal "
            "del documento. No lo resumas ni añadas comentarios."
        )
    else:
        prompt = (
            "Lee únicamente la página mostrada. Responde con el código visual, "
            "el tamaño total de la muestra y la media de la condición B. "
            "Formato recomendado: H7 | 42 | 37.4."
        )
    for role, model in vision_roles.items():
        response = post_openai_compatible_chat(
            base_url=base_url,
            api_key=api_key,
            payload={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                "temperature": 0,
                # Reasoning models may spend part of this budget before emitting
                # the final answer. A short cap can therefore create false
                # negatives even when the image was read correctly.
                "max_tokens": MAX_RESPONSE_TOKENS,
            },
            timeout_seconds=120,
            user_agent="HermesResearchMultimodalProbe/1.0",
            role=role,
            capability="vision",
            review_dir=review_dir,
        )
        answer = extract_message_content(response)
        passed = (
            answer_matches_title_anchor(answer, expected_title)
            if expected_title
            else answer_contains_expected_values(answer)
        )
        results.append(
            {
                "role": role,
                "model": model,
                "required_capability": "vision",
                "passed": passed,
                "answer": answer.strip(),
            }
        )
        if not passed:
            expectation = "the visible title" if expected_title else "every expected visual value"
            raise RuntimeError(f"{model} did not recover {expectation}: {answer}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        type=pathlib.Path,
        help="Optional PDF to render. Omit it to use the deterministic self-test PDF.",
    )
    parser.add_argument("--output", type=pathlib.Path, help="Optional JSON evidence path.")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="hermes-multimodal-") as temp_dir:
        workdir = pathlib.Path(temp_dir)
        external_pdf = args.pdf is not None
        pdf_path = args.pdf.resolve() if external_pdf else build_self_test_pdf(workdir)
        review_dir = infer_review_dir(pdf_path) if external_pdf else None
        env_values = resolve_private_env_values(review_dir)
        extracted_text, image_path = render_pdf(
            pdf_path,
            workdir,
            require_self_test_values=not external_pdf,
        )
        expected_title = first_page_title_anchor(extracted_text) if external_pdf else ""
        results = verify_models(
            image_path,
            env_values,
            expected_title=expected_title,
            review_dir=review_dir,
        )
        evidence = {
            "schema_version": "hermes.multimodal-probe/v1",
            "status": "pass",
            "probe_mode": "scientific_pdf" if external_pdf else "deterministic_self_test",
            "pdf_text_layer": "pass",
            "pdf_page_render": "pass",
            "expected_title": expected_title,
            "models": results,
        }
        if args.output:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
