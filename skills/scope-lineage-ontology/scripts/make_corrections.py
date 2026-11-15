#!/usr/bin/env python3
"""Build the corrections list a writer gets when a table is rewritten whole.

A table whose packet changed is rewritten from the new packet alone. Its old review and
its fix log say which findings were confirmed and fixed last time; without them the
writer repeats the same mistakes and the next review and fix have to catch them again.
This script reads those files and writes a short list for the writer (runbook S4,
template T1 ``{CORRECTIONS}``):

  A 段  high and medium findings the fix log says were fixed ("已改") -- the writer
        must follow them once they check out against the new packet;
  B 段  everything else worth a look: low findings, high and medium findings with no
        fix-log line, and older items the old review's table marks "已避免" -- the
        writer adopts them only when the packet supports them.

With the old document (``--prior-doc``, ``reviews/<db.table>.prior.json``) two more things
are added. Every B 段 item marked 未核 gets a 上一版写法 line: the old document's text at each
document path the item names (its 位置 line, or the paths quoted in a table row), so the
writer sees what the last version wrote there. And a C 段 lists the old document's
``summary.watch`` and ``summary.questions`` items whose quoted evidence -- backquoted
text, quoted literals, names with ``_`` or ``.`` -- is all still in the new packet: points
the last version got right, to keep once they check out. An item with no such evidence, or
with a piece the new packet no longer has, is left out.

Dropped: table rows the old review judged "不适用", findings the fix log judged
"不成立", and findings whose quoted packet text is not in the new packet. Skipped:
table rows "又犯了" (the finding section of the same review covers them). A finding the
script cannot read (no 材料包事实 or 应改成 line) is printed as ``未解析：<编号>`` on
stderr, never dropped silently. A finding with nothing to check against the packet is
marked 未核: the writer has to find its own evidence before adopting it. A finding whose
fix says "不放大" is tagged, not rewritten: the writer writes the conditional sentence.

When the table had a re-review (runbook S8), the old review is the re-review and the
first review was kept aside. Pass it with ``--round1``: its high and medium findings that
the fix log marks fixed go to A 段, matched by that review's own ``reviewed_doc_digest``.

The fix log is the fixer's reply kept as it came (T4), one section per review, each
opened by ``来源：reviews/<db.table>.md reviewed_doc_digest=<digest>``; under it every
finding sits on its own line, number first (``H1 已改：…``, ``M2 不成立：…``).

  make_corrections.py PRIOR_MD NEW_PACKET_DIR [--round1 FILE] [--fixlog FILE]
                      [--prior-doc FILE] [--writer-prompt FILE] [--out FILE] [--report FILE]

Exit 0 with the list written (stdout without ``--out``) and a one-line count on stderr;
exit 1 when an input file is missing. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITY = {"H": "高", "M": "中", "L": "低", "高": "高", "中": "中", "低": "低"}
# A finding heading: ### or #### then H1. / M1（ / L1 … or 中-1 / 低-1 (an older review's style).
HEADING = re.compile(r"^#{3,4}\s*(?:([HML])(\d+)|(高|中|低)-(\d+))(?=[\s.．（(]|$)(.*)$")
FIELD = re.compile(r"^-\s*(位置|文档位置|文档原话|材料包事实[^：:]*|应改成|后果|问题)[：:]\s*(.*)$")
OLD_ID = re.compile(r"([HML])\d+|(高|中|低)-\d+")
OLD_ROW = re.compile(r"^\|\s*o\d+\s*\|")
# Quoted text that names a place in the document, not text of the packet.
DOC_PATH = re.compile(
    r"^(columns|summary|rules|questions|steps|row|scope|watch|how_to_read|good_for|not_for|"
    r"code_values|refresh|upstream|task|generator)\b|\[[a-z0-9_]+\]|^r\d+$|^q\d+$"
)
VERDICT = re.compile(r"「([^」]*(?:risk|safe|unknown)[：:][^」]*)」")
HEX16 = re.compile(r"^[0-9a-f]{16}$")
NAME = re.compile(r"^[A-Za-z_][\w.]*$")
NO_FAN_OUT = re.compile(r"不放大|不影响行数|不会放大")
SOURCE_LINE = re.compile(r"^来源[：:].*?reviewed_doc_digest\s*=\s*([0-9a-f]{16})")
FIX_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:逐条处理[：:]\s*)?([HML]\d+|(?:高|中|低)-\d+)\s*[：:]?\s*(已改|不成立|未改)"
)
SENTENCE_TAG = (
    "（句式：写到「不放大」时带上条件和反面情形，例如「<条件> 成立时不放大；不成立时 … 会放大行数」，"
    "否则校验第 10 项（fan_out）报 WARN；不照抄本条措辞）"
)
USAGE = [
    "用法：",
    "- 这些不是 owner 确认的业务事实。`sources` 照材料包实际来源写，不写 `confirmed`；原来是推断的仍标推断。",
    "- 每条先按本材料包核对。下面三种情况一律丢弃，在回复里列出编号和理由：引用的材料包位置在新材料包里找不到；"
    "说法已变（例如判定从 risk 变成 unknown）；与写作提示词的现行规则冲突（例如列的 category、「不放大」的写法、注明据兄弟表）。",
    "- 标「未核」的条目，脚本在材料包里找不到可核对的原文：你自己在材料包里找到依据才采纳，找不到就不采纳。",
    "- 条目里凡写「不放大 / 不影响行数」的，按写作提示词的条件句式重写，不照抄。",
    "- 一条涉及多个字段时，全页相关字段都要一致。",
    "- A 段（修订已改的高、中级）：核对通过就必须照做。B 段（没经修订核实的审读意见、更早轮次上一版已写对的要点）：核对成立才采纳。",
    "- B 段「上一版写法」是上一版文档在该位置的原句：更早轮次已写对的条目，按材料包核对成立就照它的意思写；"
    "审读发现的条目，它可能正是被指出的错写法，对照「应改成」用，不照抄。",
    "- C 段（上一版要点，核对后保留）：上一版 watch / questions 里引用的材料原文都还在新材料包里的条目。"
    "逐条按新材料包核对，成立就在新文档的 watch / questions（或对应字段）里保留这个要点；不成立的丢弃并在回复里列出。",
]


def front_matter(text: str) -> dict:
    found = re.match(r"---\n(.*?)\n---", text, re.S)
    keys = {}
    if found:
        for line in found.group(1).splitlines():
            key, _, value = line.partition(":")
            keys[key.strip()] = value.strip()
    version = re.search(r"table-semantics-review@(\d+)", text)
    keys["review_prompt"] = f"table-semantics-review@{version.group(1)}" if version else "未写"
    return keys


def _norm(text: str) -> str:
    return re.sub(r"[\s`]+", "", text).lower()


def snippets(text: str) -> list[str]:
    """What of a 材料包事实 line can be looked up in the packet: backquoted text (split at
    ellipses; ``db.table.column`` reduced to its last part; single words, document paths
    and 16-hex digests left out) and quoted risk / safe / unknown verdicts."""
    found = []
    for double, single in re.findall(r"``\s*(.+?)\s*``|`([^`]+)`", text):
        quoted = double or single
        if DOC_PATH.search(quoted):
            continue
        for piece in re.split(r"…|\.\.\.", quoted):
            piece = piece.strip()
            if HEX16.match(piece):
                continue
            if ":" in piece and " " in piece and NAME.match(piece.split(":", 1)[0]):
                continue  # a document key and its value (`sources: comment`), not packet text
            if NAME.match(piece):
                if "." not in piece and "_" not in piece:
                    continue
                piece = piece.rsplit(".", 1)[-1]
            if len(_norm(piece)) >= 6:
                found.append(piece)
    return found + VERDICT.findall(text)


def check(text: str, packet: str) -> tuple[list[str], list[str]]:
    quoted = snippets(text)
    return quoted, [piece for piece in quoted if _norm(piece) not in packet]


# A document path a review quotes: `columns[x].derivation`, `summary.watch[2]`, `questions[q1]`.
PATH = re.compile(r"^[a-z_]+(?:\[[^\]\s]+\])*(?:\.[a-z0-9_]+(?:\[[^\]\s]+\])*)*$")
PATH_PART = re.compile(r"([a-z0-9_]+)((?:\[[^\]]+\])*)")
LIST_KEYS = ("column", "id", "branch", "name")
WORDING_CAP = 400
LITERAL = re.compile(r"(?<![\w'])'([^'\s][^'\n]{0,58}[^'\s]|[^'\s])'(?![\w'])")
IDENT = re.compile(r"(?<![\w.])[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?![\w])")


def doc_paths(text: str) -> list[str]:
    """The document paths quoted (backquoted) in ``text``, in order, once each."""
    found = []
    for quoted in re.findall(r"`([^`]+)`", text):
        quoted = quoted.strip()
        if PATH.match(quoted) and DOC_PATH.search(quoted) and quoted not in found:
            found.append(quoted)
    return found


def _step(node, key: str):
    """One ``[key]`` step: a list index, or the list item whose column / id / branch /
    name is ``key``."""
    if not isinstance(node, list):
        return None
    if key.isdigit():
        return node[int(key)] if int(key) < len(node) else None
    for item in node:
        if isinstance(item, dict) and any(item.get(name) == key for name in LIST_KEYS):
            return item
    return None


def resolve(doc: dict, path: str):
    """The value at a review's document path, or None. A path whose first part is not a
    top-level key is tried under ``summary`` and ``summary.refresh`` (`how_to_read`,
    `not_for[1]`); ``.q1`` after a list picks the item with that id."""
    parts = PATH_PART.findall(path)
    summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    roots = [doc, summary, summary.get("refresh") if isinstance(summary.get("refresh"), dict) else {}]
    for root in roots:
        if parts and parts[0][0] not in root:
            continue
        node = root
        for name, keys in parts:
            node = node.get(name) if isinstance(node, dict) else _step(node, name)
            for key in re.findall(r"\[([^\]]+)\]", keys):
                node = _step(node, key)
            if node is None:
                break
        if node is not None:
            return node
    return None


def render(value) -> str:
    """A resolved value as one line: a string as it is, an item by its text, a list or
    an object by its string fields."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict):
        text = value["text"] if isinstance(value.get("text"), str) else "；".join(
            f"{key}：{item}" for key, item in value.items() if isinstance(item, str))
    elif isinstance(value, list):
        text = "；".join(render(item) for item in value)
    else:
        text = json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= WORDING_CAP else text[:WORDING_CAP] + "…"


def prior_wording(text: str, doc: dict | None) -> tuple[str, int, list[str]]:
    """The 上一版写法 line for the paths quoted in ``text``, how many resolved, and the
    paths that did not."""
    if doc is None:
        return "", 0, []
    shown, unresolved = [], []
    for path in doc_paths(text):
        value = resolve(doc, path)
        if value is None or not render(value):
            unresolved.append(path)
        else:
            shown.append(f"`{path}`「{render(value)}」")
    line = f"\n  上一版写法：{'；'.join(shown)}" if shown else ""
    return line, len(shown), unresolved


def evidence(text: str) -> list[str]:
    """What a watch or question item cites from the material: backquoted text, quoted
    literals, and names with ``_`` or ``.`` (pN numbers are the packet's own and left out)."""
    found = [piece.strip() for piece in re.findall(r"`([^`]+)`", text)]
    found += [f"'{literal}'" for literal in LITERAL.findall(text)]
    found += [name for name in IDENT.findall(text) if "_" in name or "." in name.strip(".")]
    unique = []
    for piece in found:
        if piece and piece not in unique and not re.fullmatch(r"[pr]\d+", piece):
            unique.append(piece)
    return unique


def _in_packet(piece: str, packet: str) -> bool:
    if _norm(piece) in packet:
        return True
    return bool(NAME.match(piece)) and "." in piece and _norm(piece.rsplit(".", 1)[-1]) in packet


def old_points(doc: dict | None, packet: str, report: list) -> list[str]:
    """C 段: the old document's watch and question items whose evidence is all still in
    the new packet."""
    if doc is None:
        return []
    summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    entries = []
    labelled = [(f"watch[{n}]", item) for n, item in enumerate(summary.get("watch") or [])]
    labelled += [(f"questions[{item.get('id', n) if isinstance(item, dict) else n}]", item)
                 for n, item in enumerate(summary.get("questions") or [])]
    for label, item in labelled:
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        pieces = evidence(text)
        if not pieces:
            report.append({"id": label, "from": "prior_doc", "dest": "skipped", "reason": "没有可核对的引文"})
            continue
        missing = [piece for piece in pieces if not _in_packet(piece, packet)]
        if missing:
            report.append({"id": label, "from": "prior_doc", "dest": "dropped",
                           "reason": "引用的材料原文在新材料包里找不到", "missing": missing})
            continue
        kind = item.get("kind") if isinstance(item, dict) else None
        entries.append(f"[c{len(entries) + 1}（上一版 `summary.{label}`{'，' + kind if kind else ''}）] "
                       f"{re.sub(chr(10), ' ', text)}\n  引文都在新材料包里：{'、'.join(f'`{p}`' for p in pieces)}")
        report.append({"id": label, "from": "prior_doc", "dest": "C", "checked": len(pieces)})
    return entries


def findings(text: str) -> list[dict]:
    """Every finding section of a review, with its 位置 / 材料包事实 / 应改成 lines."""
    items, current = [], None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            if current:
                items.append(current)
            letter, number, word, word_number, title = heading.groups()
            current = {
                "id": f"{letter}{number}" if letter else f"{word}-{word_number}",
                "severity": SEVERITY[letter or word],
                "title": title.strip(" .．"),
                "fields": {},
            }
            continue
        if current is None:
            continue
        if re.match(r"^#{1,4}\s", line):
            items.append(current)
            current = None
            continue
        field = FIELD.match(line)
        if field:
            name = field.group(1)
            key = "位置" if name in ("位置", "文档位置") else "材料包事实" if name.startswith("材料包事实") else name
            current["fields"][key] = (current["fields"].get(key, "") + " " + field.group(2)).strip()
    if current:
        items.append(current)
    return items


def table_rows(text: str) -> tuple[list[dict], list[str]]:
    """The rows of the old-review table (rewrite-after review), and the o-rows found
    under no recognised heading. A re-review's table of the previous round's findings is
    recognised and left alone: the first review itself is read with ``--round1``."""
    rows, stray, section = [], [], None
    for line in text.splitlines():
        if re.match(r"^#{2,3}\s", line):
            if "旧审读" in line and ("处理" in line or "结果" in line):
                section = "old"
            elif "上一轮" in line and ("处理" in line or "结果" in line):
                section = "previous"
            else:
                section = None
            continue
        if not line.startswith("|") or re.match(r"^\|\s*:?-", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if section == "old" and not (cells[0].startswith("旧") or cells[0] == "编号"):
            rows.append(cells)
        elif section is None and OLD_ROW.match(line):
            stray.append(cells[0])
    parsed = []
    for cells in rows:
        # The first column is the o number (review@10) or, in an older review, the old number.
        number, cells = (cells[0] + " ", cells[1:]) if re.fullmatch(r"o\d+", cells[0]) else ("", cells)
        if not cells:
            continue
        joined = " | ".join(cells)
        severity = OLD_ID.search(cells[0])
        rest = cells[1:]
        if any(cell.lstrip("*").startswith("不适用") for cell in rest):
            status = "不适用"
        elif "又犯" in joined:
            status = "又犯了"
        elif "已避免" in joined:
            status = "已避免"
        else:
            status = "未知"
        parsed.append({
            "id": f"{number}{cells[0]}",
            "severity": SEVERITY[severity.group(1) or severity.group(2)] if severity else "未标",
            "status": status,
            "cells": cells,
        })
    return parsed, stray


def fix_log(path: str | None, digest: str, warnings: list[str]) -> dict | None:
    """``编号 -> 已改 / 不成立 / 未改`` from the last fix-log section of the review whose
    ``reviewed_doc_digest`` is ``digest``; None when there is no such section."""
    if not path:
        return None
    sections, current = [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        source = SOURCE_LINE.match(line)
        if source:
            current = {"digest": source.group(1), "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line)
    matching = [section for section in sections if section["digest"] == digest]
    if not matching:
        warnings.append(f"警告：fixlog 里没有 reviewed_doc_digest={digest} 的段，这份审读的高、中级都按 B 段处理")
        return None
    verdicts = {}
    for line in matching[-1]["lines"]:
        found = FIX_LINE.match(line)
        if found:
            verdicts[found.group(1)] = found.group(2)
    return verdicts


def _entry(label: str, item: dict, checked: int, wording: str = "") -> str:
    fields = item["fields"]
    marks = item["severity"] + ("，未核" if not checked else "")
    tag = SENTENCE_TAG if NO_FAN_OUT.search(fields["应改成"]) else ""
    return (
        f"[{label}（{marks}）] {item['title']}\n"
        f"  位置：{fields.get('位置', '—')}\n"
        f"  材料包事实：{fields['材料包事实']}\n"
        f"  应改成：{fields['应改成']}{tag}{wording}"
    )


def collect(review: str, origin: str, prefix: str, verdicts: dict | None, packet: str,
            sections: dict, report: list, unparsed: list, only_fixed: bool = False,
            doc: dict | None = None) -> None:
    """Route the findings of one review into A 段 / B 段 / dropped.

    ``only_fixed`` (the first review behind a re-review): only its high and medium
    findings the fix log marks fixed are taken; the rest is the re-review's business.
    """
    for item in findings(review):
        label = prefix + item["id"]
        verdict = (verdicts or {}).get(item["id"])
        serious = item["severity"] in ("高", "中")
        if only_fixed and not (serious and verdict == "已改"):
            if verdict == "不成立":
                report.append({"id": label, "from": origin, "dest": "dropped", "reason": "修订者判不成立"})
            continue
        fields = item["fields"]
        if "应改成" not in fields or "材料包事实" not in fields:
            missing = "应改成" if "应改成" not in fields else "材料包事实"
            unparsed.append(f"未解析：{label}（缺「{missing}」）")
            report.append({"id": label, "from": origin, "dest": "unparsed", "reason": f"缺「{missing}」"})
            continue
        if verdict == "不成立":
            report.append({"id": label, "from": origin, "dest": "dropped", "reason": "修订者判不成立"})
            continue
        quoted, missing = check(fields["材料包事实"], packet)
        if missing:
            report.append({"id": label, "from": origin, "dest": "dropped",
                           "reason": "引用的材料包原文在新材料包里找不到", "missing": missing})
            continue
        dest = "A" if serious and verdict == "已改" else "B"
        entry = {"id": label, "from": origin, "severity": item["severity"], "dest": dest, "checked": len(quoted)}
        wording = ""
        if dest == "B" and not quoted and doc is not None:
            wording, entry["prior_wording"], entry["unresolved"] = prior_wording(fields.get("位置", ""), doc)
        sections[dest].append(_entry(label, item, len(quoted), wording))
        report.append(entry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("prior", help="the old review, reviews/<db.table>.prior.md")
    parser.add_argument("packet_dir", help="the rebuilt packet directory, packets/<db.table>")
    parser.add_argument("--round1", help="the first review behind a re-review, when there was one")
    parser.add_argument("--fixlog", help="the fix log kept beside the old review")
    parser.add_argument("--prior-doc", help="the old document, reviews/<db.table>.prior.json")
    parser.add_argument("--writer-prompt", help="table-semantics-prompt.md, for its version")
    parser.add_argument("--out", help="write the list here (default: stdout)")
    parser.add_argument("--report", help="write each item's destination here as JSON")
    args = parser.parse_args(argv)

    for path in (args.prior, args.round1, args.fixlog, Path(args.packet_dir) / "packet.md",
                 Path(args.packet_dir) / "packet.json", args.prior_doc, args.writer_prompt):
        if path and not Path(path).is_file():
            print(f"找不到文件：{path}", file=sys.stderr)
            return 1

    prior = Path(args.prior).read_text(encoding="utf-8")
    keys = front_matter(prior)
    packet = _norm(Path(args.packet_dir, "packet.md").read_text(encoding="utf-8"))
    digest = json.loads(Path(args.packet_dir, "packet.json").read_text(encoding="utf-8")).get("packet_digest")
    writer = "未给"
    if args.writer_prompt:
        version = re.search(r"table-semantics-prompt@(\d+)", Path(args.writer_prompt).read_text(encoding="utf-8"))
        writer = f"table-semantics-prompt@{version.group(1)}" if version else "未写"

    doc = json.loads(Path(args.prior_doc).read_text(encoding="utf-8")) if args.prior_doc else None
    if doc is not None and not isinstance(doc, dict):
        print(f"{args.prior_doc} 不是一份文档（JSON 对象）", file=sys.stderr)
        return 1
    warnings, unparsed, report = [], [], []
    sections: dict[str, list[str]] = {"A": [], "B": []}
    if args.round1:
        first = Path(args.round1).read_text(encoding="utf-8")
        first_digest = front_matter(first).get("reviewed_doc_digest", "")
        collect(first, "round1", "首审 ", fix_log(args.fixlog, first_digest, warnings), packet,
                sections, report, unparsed, only_fixed=True, doc=doc)
    collect(prior, "prior", "", fix_log(args.fixlog, keys.get("reviewed_doc_digest", ""), warnings),
            packet, sections, report, unparsed, doc=doc)

    rows, stray = table_rows(prior)
    if stray:
        unparsed.append(f"未解析：旧审读处理表格的 {'、'.join(stray)} 不在「旧审读各条的处理结果」小节下")
    for row in rows:
        if row["status"] == "不适用":
            report.append({"id": row["id"], "from": "table", "dest": "dropped", "reason": "旧审读已判不适用"})
            continue
        if row["status"] == "又犯了":
            report.append({"id": row["id"], "from": "table", "dest": "skipped", "reason": "又犯了：由发现小节覆盖"})
            continue
        if row["status"] != "已避免":
            unparsed.append(f"未解析：{row['id']}（看不出是不适用、已避免还是又犯了）")
            report.append({"id": row["id"], "from": "table", "dest": "unparsed", "reason": "状态不明"})
            continue
        joined = " | ".join(row["cells"][1:])
        quoted, missing = check(joined, packet)
        if missing:
            report.append({"id": row["id"], "from": "table", "dest": "dropped",
                           "reason": "引用的材料包原文在新材料包里找不到", "missing": missing})
            continue
        marks = row["severity"] + "，更早轮次，上一版已写对" + ("" if quoted else "，未核")
        tag = SENTENCE_TAG if NO_FAN_OUT.search(joined) else ""
        entry = {"id": row["id"], "from": "table", "severity": row["severity"], "dest": "B", "checked": len(quoted)}
        wording = ""
        if not quoted and doc is not None:
            wording, entry["prior_wording"], entry["unresolved"] = prior_wording(joined, doc)
        sections["B"].append(f"[{row['id']}（{marks}）] {joined}{tag}{wording}")
        report.append(entry)

    lines = [
        "# 修正点清单",
        "",
        "下面不是 owner 确认的业务事实，而是从旧审读和修订记录里抽出的「修正点」。",
        f"来源：旧审读 reviewed_doc_digest={keys.get('reviewed_doc_digest', '无')}、"
        f"reviewed_packet_digest={keys.get('reviewed_packet_digest', '无')}、"
        f"fixed_doc_digest={keys.get('fixed_doc_digest', '无')}、审读提示词 {keys['review_prompt']}；"
        f"新材料包 packet_digest={digest}；写作提示词 {writer}。",
        *USAGE,
        "",
        "## A 段",
        *(sections["A"] or ["无"]),
        "",
        "## B 段",
        *(sections["B"] or ["无"]),
        "",
        "## C 段（上一版要点，核对后保留）",
        *(old_points(doc, packet, report) or ["无"]),
    ]
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for line in warnings + unparsed:
        print(line, file=sys.stderr)
    counts: dict[str, int] = {}
    for item in report:
        counts[item["dest"]] = counts.get(item["dest"], 0) + 1
    unchecked = sum(1 for item in report if item["dest"] in ("A", "B") and not item.get("checked"))
    unchecked_b = [item for item in report if item["dest"] == "B" and not item.get("checked")]
    worded = sum(1 for item in unchecked_b if item.get("prior_wording"))
    print(f"{Path(args.prior).name}: A {counts.get('A', 0)}、B {counts.get('B', 0)}（未核 {unchecked}）、"
          f"丢弃 {counts.get('dropped', 0)}、跳过 {counts.get('skipped', 0)}、未解析 {counts.get('unparsed', 0)}"
          + (f"；上一版写法 {worded}/{len(unchecked_b)}、C {counts.get('C', 0)}" if doc is not None else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
