"""Structural parity between the Chinese and English documentation trees.

`docs/zh-CN/` and `docs/en/` are two renderings of the same reference material. Prose
differs by language, but structure must not: the two trees hold the same files, each pair
has the same heading skeleton, the same tables with the same shape, the same fenced code
blocks in the same order (JSON payloads byte-identical, since a contract example has no
prose to translate), and the same link targets once `zh-CN`/`en` naming is normalized.

That structure is what catches the failure mode this guard exists for: one language gets a
new section, a new table row, or a corrected code sample, and the other silently keeps the
old story. A green run does not prove the translation is good -- it proves nothing was
dropped.

Run it directly for a report::

    python tests/architecture/docs_parity.py

Exit code 0 means the trees agree; 1 means a difference is reported; 2 means the tool
could not run (a missing tree).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ZH_DIR = REPO_ROOT / "docs" / "zh-CN"
EN_DIR = REPO_ROOT / "docs" / "en"

# Language pairs outside docs/ that the docs link into, checked with the same rules.
EXTRA_PAIRS = (("examples/README.zh-CN.md", "examples/README.md"),)

_FENCE_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})(?P<info>[^\s`]*)\s*$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*$")
_LINK_RE = re.compile(r"(?<!!)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
# A table row: starts and ends with a pipe that is not escaped.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
# JSON payloads are contract examples with no prose, so the two languages must match byte
# for byte; every other language may carry translated comments or node labels.
_BYTE_IDENTICAL_LANGUAGES = frozenset({"json", "yaml", "csv"})


@dataclass(frozen=True)
class CodeBlock:
    language: str
    body: str


@dataclass(frozen=True)
class Table:
    heading: str
    columns: int
    rows: int


@dataclass(frozen=True)
class DocStructure:
    path: Path
    headings: list[tuple[int, str]]
    code_blocks: list[CodeBlock]
    tables: list[Table]
    links: list[str]


def _normalize_link(target: str) -> str:
    """Map a link target onto its language-neutral form.

    `../en/x.md` and `../zh-CN/x.md` are the same edge; so are `README.md` and
    `README.zh-CN.md` in the examples pair. Anchors are dropped: heading text is
    translated, so anchors legitimately differ between the trees.
    """
    target = target.split("#", 1)[0]
    if not target:
        return ""
    target = target.replace("/zh-CN/", "/en/")
    target = target.replace("README.zh-CN.md", "README.md")
    return target


def parse_document(path: Path) -> DocStructure:
    headings: list[tuple[int, str]] = []
    code_blocks: list[CodeBlock] = []
    tables: list[Table] = []
    links: list[str] = []

    lines = path.read_text(encoding="utf-8").splitlines()
    fence: str | None = None
    language = ""
    body: list[str] = []
    current_heading = ""
    table_rows = 0
    table_columns = 0

    def close_table() -> None:
        nonlocal table_rows, table_columns
        if table_rows:
            # `rows` counts content: the header and the |---| delimiter are structure.
            tables.append(
                Table(
                    heading=current_heading,
                    columns=table_columns,
                    rows=max(table_rows - 2, 0),
                )
            )
        table_rows = 0
        table_columns = 0

    for line in lines:
        fence_match = _FENCE_RE.match(line)
        if fence is not None:
            if fence_match and line.startswith(fence) and not fence_match.group("info"):
                code_blocks.append(CodeBlock(language=language, body="\n".join(body)))
                fence = None
                body = []
            else:
                body.append(line)
            continue
        if fence_match:
            close_table()
            fence = fence_match.group("fence")
            language = fence_match.group("info")
            body = []
            continue

        if _TABLE_ROW_RE.match(line):
            columns = len(line.strip().strip("|").split("|"))
            if table_rows == 0:
                table_columns = columns
            table_rows += 1
        else:
            close_table()

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group("hashes"))
            text = heading_match.group("text")
            headings.append((level, text))
            current_heading = text

        for link_match in _LINK_RE.finditer(line):
            links.append(_normalize_link(link_match.group("target")))

    close_table()
    if fence is not None:
        raise ValueError(f"{path}: unterminated code fence")
    return DocStructure(
        path=path,
        headings=headings,
        code_blocks=code_blocks,
        tables=tables,
        links=links,
    )


def _compare_documents(zh: DocStructure, en: DocStructure) -> list[str]:
    name = zh.path.relative_to(REPO_ROOT)
    problems: list[str] = []

    zh_levels = [level for level, _ in zh.headings]
    en_levels = [level for level, _ in en.headings]
    if zh_levels != en_levels:
        problems.append(
            f"{name}: heading skeleton differs -- zh has {len(zh_levels)} headings "
            f"{zh_levels}, en has {len(en_levels)} {en_levels}"
        )

    if len(zh.code_blocks) != len(en.code_blocks):
        problems.append(
            f"{name}: {len(zh.code_blocks)} code block(s) in zh vs "
            f"{len(en.code_blocks)} in en"
        )
    else:
        for index, (zh_block, en_block) in enumerate(zip(zh.code_blocks, en.code_blocks)):
            if zh_block.language != en_block.language:
                problems.append(
                    f"{name}: code block {index + 1} is "
                    f"`{zh_block.language or 'plain'}` in zh but "
                    f"`{en_block.language or 'plain'}` in en"
                )
            elif (
                zh_block.language in _BYTE_IDENTICAL_LANGUAGES
                and zh_block.body != en_block.body
            ):
                problems.append(
                    f"{name}: {zh_block.language} block {index + 1} differs between "
                    f"the languages; contract examples carry no prose and must match"
                )

    if len(zh.tables) != len(en.tables):
        problems.append(f"{name}: {len(zh.tables)} table(s) in zh vs {len(en.tables)} in en")
    else:
        for index, (zh_table, en_table) in enumerate(zip(zh.tables, en.tables)):
            if (zh_table.columns, zh_table.rows) != (en_table.columns, en_table.rows):
                problems.append(
                    f"{name}: table {index + 1} (near zh heading "
                    f"{zh_table.heading!r}) is {zh_table.columns}x{zh_table.rows} in zh "
                    f"but {en_table.columns}x{en_table.rows} in en"
                )

    if zh.links != en.links:
        only_zh = [link for link in zh.links if link not in en.links]
        only_en = [link for link in en.links if link not in zh.links]
        if only_zh or only_en:
            problems.append(
                f"{name}: link targets differ -- only in zh: {sorted(set(only_zh))}; "
                f"only in en: {sorted(set(only_en))}"
            )
        elif len(zh.links) != len(en.links):
            problems.append(
                f"{name}: {len(zh.links)} link(s) in zh vs {len(en.links)} in en"
            )

    return problems


def _check_link_targets(structure: DocStructure, raw_path: Path) -> list[str]:
    """Every relative link must resolve to a file that exists."""
    problems: list[str] = []
    text = raw_path.read_text(encoding="utf-8")
    for link_match in _LINK_RE.finditer(text):
        target = link_match.group("target")
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = (raw_path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            problems.append(
                f"{raw_path.relative_to(REPO_ROOT)}: dead link {target!r}"
            )
    return problems


def compare_trees() -> list[str]:
    if not ZH_DIR.is_dir() or not EN_DIR.is_dir():
        raise FileNotFoundError(f"expected both {ZH_DIR} and {EN_DIR} to exist")

    problems: list[str] = []
    zh_names = {path.name for path in ZH_DIR.glob("*.md")}
    en_names = {path.name for path in EN_DIR.glob("*.md")}
    for missing in sorted(zh_names - en_names):
        problems.append(f"docs/en/{missing} is missing (docs/zh-CN has it)")
    for missing in sorted(en_names - zh_names):
        problems.append(f"docs/zh-CN/{missing} is missing (docs/en has it)")

    pairs = [(ZH_DIR / name, EN_DIR / name) for name in sorted(zh_names & en_names)]
    pairs.extend(
        (REPO_ROOT / zh_rel, REPO_ROOT / en_rel) for zh_rel, en_rel in EXTRA_PAIRS
    )

    for zh_path, en_path in pairs:
        if not zh_path.is_file() or not en_path.is_file():
            problems.append(f"missing counterpart for {zh_path.name} / {en_path.name}")
            continue
        zh = parse_document(zh_path)
        en = parse_document(en_path)
        problems.extend(_compare_documents(zh, en))
        problems.extend(_check_link_targets(zh, zh_path))
        problems.extend(_check_link_targets(en, en_path))

    return problems


def main() -> int:
    try:
        problems = compare_trees()
    except FileNotFoundError as error:
        print(f"docs parity: {error}", file=sys.stderr)
        return 2
    if problems:
        print(f"docs parity: {len(problems)} difference(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("docs parity: zh-CN and en agree on structure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
