"""The two documentation trees must not drift apart.

`docs/zh-CN/` and `docs/en/` say the same thing in two languages. The failure mode is
never a loud one: someone corrects a contract detail, a table row, or a code sample in the
language they happen to be editing, and the other tree keeps telling the old story until a
reader trusts it. The parity check below is the guard; the unit tests around it pin what
"a difference" means, since a guard nobody has watched fail is not a guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .docs_parity import compare_trees, parse_document

REPO = Path(__file__).resolve().parents[2]


def test_zh_and_en_documentation_agree_on_structure() -> None:
    problems = compare_trees()

    assert problems == [], "docs parity differences:\n" + "\n".join(problems)


def test_every_zh_document_has_an_en_counterpart() -> None:
    zh = {path.name for path in (REPO / "docs" / "zh-CN").glob("*.md")}
    en = {path.name for path in (REPO / "docs" / "en").glob("*.md")}

    assert zh == en


@pytest.fixture()
def doc(tmp_path: Path):
    def _write(name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return path

    return _write


def test_parse_document_counts_headings_code_blocks_tables_and_links(doc) -> None:
    path = doc(
        "sample.md",
        "# Title\n\n"
        "See [guide](getting-started.md) and [site](https://example.com).\n\n"
        "## Section\n\n"
        "| Key | Value |\n| --- | --- |\n| a | b |\n| c | d |\n\n"
        "```json\n{\"a\": 1}\n```\n",
    )

    structure = parse_document(path)

    assert structure.headings == [(1, "Title"), (2, "Section")]
    assert [block.language for block in structure.code_blocks] == ["json"]
    assert structure.code_blocks[0].body == '{"a": 1}'
    assert [(table.columns, table.rows) for table in structure.tables] == [(2, 2)]
    assert structure.links == ["getting-started.md", "https://example.com"]


def test_language_specific_link_targets_normalize_to_the_same_edge(doc) -> None:
    zh = doc("zh.md", "[x](../zh-CN/lineage-json.md) [y](../../examples/README.zh-CN.md)\n")
    en = doc("en.md", "[x](../en/lineage-json.md) [y](../../examples/README.md)\n")

    assert parse_document(zh).links == parse_document(en).links


def test_anchors_are_dropped_because_heading_text_is_translated(doc) -> None:
    zh = doc("zh.md", "[x](input-formats.md#目标表-ddlschema-元数据)\n")
    en = doc("en.md", "[x](input-formats.md#target-table-ddlschema-metadata)\n")

    assert parse_document(zh).links == parse_document(en).links


def test_a_table_inside_a_fenced_block_is_not_counted_as_a_table(doc) -> None:
    path = doc("sample.md", "```text\n| not | a | table |\n| --- | --- | --- |\n```\n")

    assert parse_document(path).tables == []


def test_unterminated_fence_is_an_error_not_a_silent_truncation(doc) -> None:
    path = doc("sample.md", "# Title\n\n```bash\nscope-lineage parse\n")

    with pytest.raises(ValueError, match="unterminated code fence"):
        parse_document(path)
