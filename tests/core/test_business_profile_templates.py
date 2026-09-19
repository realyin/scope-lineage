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
