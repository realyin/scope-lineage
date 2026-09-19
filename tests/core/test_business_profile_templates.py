"""The profile templates must split the reader's document from the writer's QA record.

The business profile used to carry its whole generation record -- input verification,
source tags, inferred items, self-consistency, the 14-item self-check -- as appendix
A1-A6 of the document the business owner reads, and that appendix grew to the size of the
body. The record is the quality gate and must survive; it simply moved into a second file,
``business_profile.check.md``.

These tests pin that split: the document template keeps only appendices A/B/C, carries no
self-check, and the two templates together still hold every check item (1-14 plus the
lettered 12a/12c/12d) that the prompt and its prose refer to by number.
"""

from __future__ import annotations

import re
from pathlib import Path

REFERENCES = Path(__file__).resolve().parents[2] / "skills" / "scope-lineage" / "references"
DOCUMENT = REFERENCES / "business-profile-template.md"
CHECK = REFERENCES / "business-profile-check-template.md"
PROMPT = REFERENCES / "semantic-profile-prompt.md"

# `| 12a. 每条…` / `| 3. semantic.json…` -- the number is the item's identity, because
# other text refers to "自检第 N 项".
_CHECK_ITEM_RE = re.compile(r"^\|\s*(\d{1,2}[a-d]?)\.\s", re.MULTILINE)
_HEADING_RE = re.compile(r"^#{2,4}\s+(.*)$", re.MULTILINE)

EXPECTED_ITEMS = {str(n) for n in range(1, 15)} | {"12a", "12c", "12d"}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_both_templates_exist() -> None:
    assert DOCUMENT.is_file()
    assert CHECK.is_file()


def test_check_items_survive_the_split() -> None:
    """Every numbered item the old appendix A6 held is still written down somewhere."""
    items = set(_CHECK_ITEM_RE.findall(_text(DOCUMENT))) | set(_CHECK_ITEM_RE.findall(_text(CHECK)))
    assert EXPECTED_ITEMS <= items, EXPECTED_ITEMS - items


def test_document_template_has_no_self_check() -> None:
    """The QA record left the reader's document -- headings and items both."""
    document = _text(DOCUMENT)
    assert "A6" not in document
    assert "自检" not in "".join(_HEADING_RE.findall(document))
    assert not _CHECK_ITEM_RE.search(document)
    for gone in ("输入文件校验", "来源标签与证据", "结构推断项", "自洽性检查", "生成自检"):
        assert gone not in _HEADING_RE.findall(document), gone


def test_document_appendix_is_exactly_three_sections() -> None:
    headings = _HEADING_RE.findall(_text(DOCUMENT))
    appendix = [h for h in headings if h.startswith("附录 ")]
    assert appendix == ["附录 A 已确认项", "附录 B 备查项与待填取值", "附录 C 风险边界"]


def test_no_reference_dangles_on_the_old_appendix_numbering() -> None:
    """A1-A6 / A2a / A2b / A3a are gone; nothing may point at a section that moved."""
    stale = re.compile(r"A2a|A2b|A3a|附录 A[1-6]")
    for path in (DOCUMENT, CHECK, PROMPT):
        assert not stale.search(_text(path)), path.name


def test_writer_numbers_and_cross_check_are_not_in_the_reader_document() -> None:
    """The confirmations tally and the cross-check result are QA, not reader material."""
    document, check = _text(DOCUMENT), _text(CHECK)
    for writer_only in ("confidence.confirmations", "交叉校验"):
        assert writer_only not in document, writer_only
        assert writer_only in check, writer_only


# ------------------------------------------- where each finding lands (B4, B5, B7, B11)


def _rule_paragraph(marker: str) -> str:
    """The prompt paragraph a rule is written in, found by its own bold heading."""
    return next(
        block for block in _text(PROMPT).split("\n\n") if block.lstrip().startswith(marker)
    )


def test_the_risk_appendix_has_a_fixed_row_for_the_write_method() -> None:
    """B5: `target_binding` had nowhere to go, so it was written as prose or dropped."""
    row = next(
        line
        for line in _text(DOCUMENT).splitlines()
        if line.startswith("| 写入方式 |")
    )
    assert "target_binding" in row
    assert "按位置" in row and "按名" in row
    assert "DDL 列序" in row


def test_the_prompt_sends_the_binding_finding_to_that_row() -> None:
    prompt = _text(PROMPT)
    paragraph = next(
        block for block in prompt.split("\n\n") if "附录 C 的「写入方式" in block
    )
    assert "target_binding" in paragraph
    assert "alias_position_mismatch" in paragraph
    assert "使用注意" in paragraph


def test_the_prompt_reads_the_severity_off_each_finding() -> None:
    """B11: severity is decided per finding now, not by its kind."""
    paragraph = next(
        block for block in _text(PROMPT).split("\n\n") if "治理线索分两档" in block
    )
    assert "kept_authoritative" in paragraph
    assert "审计列" in paragraph
    assert "按 `severity` 读" in paragraph


def test_the_prompt_fixes_the_wording_for_how_an_input_is_read() -> None:
    """B7: the distinction used to live in a self-check item and in no sentence."""
    paragraph = _rule_paragraph("**数据从哪来、到哪去**")
    assert "read_by_scopes" in paragraph
    assert "直接读取" in paragraph
    assert "经 <scope> 读取" in paragraph


def test_the_prompt_names_both_downstream_sources() -> None:
    """B4: the scheduler's registration and the corpus's proof are two facts."""
    paragraph = _rule_paragraph("**数据从哪来、到哪去**")
    assert "task.meta.downstream_tasks" in paragraph
    assert "task.downstream_consumers" in paragraph
    assert "调度登记" in paragraph and "语料证明" in paragraph


def test_self_check_item_nine_checks_the_wording_rather_than_a_slot() -> None:
    item = next(
        line for line in _text(CHECK).splitlines() if line.startswith("| 9. ")
    )
    assert "直接读取" in item and "经" in item
