import pathlib
import sys

import pytest

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from verify_multimodal_pdf import (
    answer_contains_expected_values,
    extract_message_content,
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
