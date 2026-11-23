"""A measure repeated within its table's grain is recorded in ``notes``, not in ``additivity``.

A value brought in through a JOIN on keys that do not cover the table's grain is still
additive at its own grain; what is wrong is summing it over this table's rows. So the
drafting prompts that handle measures (T5, T6 and the fragment prompt) tell the drafter to
read the digest's ``joined in through … on <keys>`` line, write in ``notes`` which keys to
take one row per in which table, keep the ``additivity`` the definitions give, and close
``measure_repeats_within_grain`` with a skip line when the SQL shows the value does not
repeat. None of them tells the drafter to change ``additivity`` for this reason.
"""

from __future__ import annotations

import re
from pathlib import Path

REFS = Path(__file__).resolve().parents[2] / "skills" / "scope-lineage-ontology" / "references"
PROMPTS = ("templates/T5.md", "templates/T6.md", "catalog-fragment-prompt.md")
LINE = "joined in through"
NOTE = "按 <键> 每组取一行后再加"


def _paragraph(text: str) -> str:
    """The lines from the first mention of the digest line to the next list item or blank."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if LINE in line)
    end = start + 1
    while end < len(lines) and lines[end].strip() and not re.match(r"\s*(- |\d+\.|[a-z]\. )", lines[end]):
        end += 1
    return "\n".join(lines[start:end])


def test_each_prompt_reads_the_digest_line_and_records_the_repeat_in_notes() -> None:
    for place in PROMPTS:
        text = (REFS / place).read_text(encoding="utf-8")
        assert LINE in text, place
        paragraph = _paragraph(text)
        assert NOTE in paragraph and "notes" in paragraph, place
        assert "repeats skip" in paragraph, place


def test_no_prompt_changes_additivity_for_a_repeat() -> None:
    for place in PROMPTS:
        paragraph = _paragraph((REFS / place).read_text(encoding="utf-8"))
        assert "non_additive`" not in paragraph.replace("不写 `non_additive`", ""), place
        assert "semi_additive`" not in paragraph.replace("不写 `semi_additive`", ""), place
        assert "不写 `additive`" not in paragraph, place
    t5 = (REFS / "templates/T5.md").read_text(encoding="utf-8")
    assert "一般写 `non_additive`" not in t5


def test_t5_keeps_reading_the_derivation_when_the_line_is_absent_or_covers_the_grain() -> None:
    paragraph = _paragraph((REFS / "templates/T5.md").read_text(encoding="utf-8"))
    assert "派生" in paragraph and "盖住" in paragraph
