import pathlib
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from verify_multimodal_pdf import (
    answer_contains_expected_values,
    answer_matches_title_anchor,
    extract_message_content,
    first_page_title_anchor,
    infer_review_dir,
)


def test_extract_message_content_accepts_string_content():
    response = {"choices": [{"message": {"content": "H7 | 42 | 37.4"}}]}

    assert extract_message_content(response) == "H7 | 42 | 37.4"


def test_extract_message_content_accepts_typed_text_parts():
    response = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "H7 | 42"},
                        {"type": "text", "text": "| 37.4"},
                    ]
                }
            }
        ]
    }

    assert extract_message_content(response) == "H7 | 42 | 37.4"


def test_extract_message_content_rejects_reasoning_without_final_answer():
    response = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "content": None,
                    "reasoning_content": "I can see H7, 42, and 37.4.",
                },
            }
        ]
    }

    with pytest.raises(RuntimeError, match="did not contain message text"):
        extract_message_content(response)


def test_answer_requires_every_visual_fact():
    assert answer_contains_expected_values("H7 | 42 | 37.4")
    assert not answer_contains_expected_values("H7 | 42")


def test_real_pdf_title_anchor_tolerates_line_break_hyphenation():
    extracted = (
        "Harnesses de seguridad para modelos generativos y sistemas agén-\n"
        "ticos entre 2023 y 2026\n\nResumen\n"
    )

    anchor = first_page_title_anchor(extracted)

    assert answer_matches_title_anchor(
        "Harnesses de seguridad para modelos generativos y sistemas agénticos entre 2023 y 2026",
        anchor,
    )
    assert not answer_matches_title_anchor("Resumen de seguridad", anchor)


def test_review_dir_is_inferred_from_manuscript_pdf(tmp_path):
    review = tmp_path / "review"
    pdf = review / "paper" / "manuscript" / "publication-ready.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.touch()
    intake = review / "protocol" / "intake.json"
    intake.parent.mkdir(parents=True)
    intake.write_text("{}\n", encoding="utf-8")

    assert infer_review_dir(pdf) == review
