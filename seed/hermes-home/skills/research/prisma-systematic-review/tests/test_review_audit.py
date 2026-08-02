import csv
import pathlib
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from review_audit import check_prisma_counts, parse_ultraquality_limit


def write_csv(path: pathlib.Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_parse_ultraquality_limit_uses_range_upper_bound(tmp_path: pathlib.Path) -> None:
    intake = tmp_path / "intake.md"
    intake.write_text("- Límite final N ultraquality: 25-50\n", encoding="utf-8")

    assert parse_ultraquality_limit(intake) == 50


def test_prisma_sought_count_uses_material_fulltext_candidate_set(tmp_path: pathlib.Path) -> None:
    review_dir = tmp_path / "review"
    write_csv(
        review_dir / "screening" / "title-abstract.csv",
        ["decision"],
        [{"decision": "include"}, {"decision": "maybe"}, {"decision": "maybe"}],
    )
    write_csv(
        review_dir / "screening" / "full-text.csv",
        ["decision", "full_text_path"],
        [
            {"decision": "include_ft", "full_text_path": "fulltext/pdf/a.pdf"},
            {"decision": "", "full_text_path": ""},
        ],
    )
    write_csv(
        review_dir / "prisma" / "flow-counts.csv",
        ["stage", "count"],
        [
            {"stage": "screened_title_abstract", "count": "3"},
            {"stage": "excluded_title_abstract", "count": "0"},
            {"stage": "full_text_sought", "count": "2"},
            {"stage": "full_text_retrieved", "count": "1"},
            {"stage": "full_text_not_retrieved", "count": "1"},
            {"stage": "full_text_assessed", "count": "1"},
            {"stage": "full_text_excluded", "count": "0"},
            {"stage": "included_in_review", "count": "1"},
        ],
    )

    result = check_prisma_counts(review_dir / "prisma" / "flow-counts.csv")

    assert result.status == "PASS"
