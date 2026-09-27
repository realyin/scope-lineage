"""The answerer's sheet, the answers file it comes back as, and the grader's sheet.

The answerer sees only each question's id, table (or concept) and text. Answers come back
as markdown with one ``## <id>`` heading per question (the rest of the heading line is
ignored; ``###`` and deeper headings and fenced code stay inside the answer). The grader
sees the question, its type, reference answer, evidence, owner check and that answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import GRADES_FORMAT
from .select import type_of

DEFAULT_SCORING = {
    "2": "正确且完整，落到具体的列、码值或条件",
    "1": "方向对但不完整，或推理里有与材料矛盾的说法",
    "0": "错误，或没找到",
}
GAPS = (
    "page_missing", "page_wrong", "page_contradiction", "answerer", "key_wrong",
    "owner_only", "none",
)
NO_ANSWER = "（未作答）"

_HEADING = re.compile(r"^##[ \t]+(\S+)")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass
class Answers:
    """Answer text by question id, in file order; ids whose heading came twice."""

    answers: dict[str, str] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)


def parse_answers(text: str) -> Answers:
    """Split an answers file on its ``## <id>`` headings; text before the first is ignored."""
    parsed = Answers()
    current: str | None = None
    lines: list[str] = []
    fence: str | None = None

    def close() -> None:
        if current is not None and current not in parsed.answers:
            parsed.answers[current] = "\n".join(lines).strip()

    for line in text.splitlines():
        marker = _FENCE.match(line)
        if marker:
            fence = None if fence and marker.group(1).startswith(fence) else (fence or marker.group(1))
        heading = None if fence or marker else _HEADING.match(line)
        if heading is None:
            lines.append(line)
            continue
        close()
        current, lines = heading.group(1), []
        if current in parsed.answers:
            parsed.duplicates.append(current)
    close()
    return parsed


def render_answer_sheet(document: dict, questions: list[dict], *, pages: str | None) -> str:
    where = f"（页面目录：`{pages}`）" if pages else ""
    out = [
        f"# 作答题单：{_subject(document)}",
        "",
        f"只读给你的页面作答{where}，不要读 SQL、材料包、血缘文件、问题集或其他来源。",
        "",
        "- 每个结论注明依据的页面和小节，例如「`<库.表>.md` · 一页纸」。",
        "- 页面确实定不了的事实：答出能确定的部分，其余写明「待 owner 确认」。"
        "页面已经写清楚的，直接答，不要写成待确认。",
        "- 页面里找不到的，照实说没找到，不要猜。",
        "- 作答文件每题一节，以 `## <id>` 开头（与下面的题号相同），节内可以再分段或用 `###` 小标题。",
        "",
        f"共 {len(questions)} 题。",
    ]
    for question in questions:
        out += ["", f"## {question['id']}", "", *_place_lines(question), "", question["text"].strip()]
    return "\n".join(out) + "\n"


def render_grading_sheet(
    document: dict, questions: list[dict], answers: dict[str, str], *, set_label: str
) -> str:
    scoring = {**DEFAULT_SCORING, **document.get("scoring", {})}
    out = [
        f"# 判分材料：{_subject(document)}",
        "",
        "对照参考答案、证据和材料，给每题的作答判分。评分标准：",
        "",
        *(f"- {score}：{scoring[score]}" for score in ("2", "1", "0")),
        "",
        "另外三条：",
        "",
        "- 材料确实定不了的事实，作答答出已知部分、其余标明待 owner 确认，算满分（gap: owner_only）；"
        "材料能定的却写成待确认，扣一分。",
        "- 推理里有与材料矛盾的说法，最多 1 分。",
        "- 参考答案本身错了：按材料判作答，gap 记 key_wrong，reason 写正确答案，不因参考答案扣作答的分。",
        "",
        f"输出一份 `{GRADES_FORMAT}` YAML，每题一条：",
        "",
        "```yaml",
        f"doc_format: {GRADES_FORMAT}",
        f"set: {set_label}",
        "round: <轮次>",
        "grades:",
        "  - id: <题号>",
        "    score: <2|1|0>",
        f"    gap: <{'|'.join(GAPS)}>",
        "    reason: <一句话：对在哪、差在哪>",
        "```",
        "",
        f"共 {len(questions)} 题。",
    ]
    for question in questions:
        out += _grading_block(question, answers.get(question["id"]))
    return "\n".join(out) + "\n"


def _grading_block(question: dict, answer: str | None) -> list[str]:
    out = ["", f"## {question['id']}", "", *_place_lines(question), f"- 题型：{type_of(question)}"]
    out += ["", "### 题目", "", question["text"].strip()]
    out += ["", "### 参考答案", "", question["answer_key"].strip()]
    evidence = question.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    out += ["", "### 证据", "", *([f"- {item}" for item in evidence] or ["（无）"])]
    if question.get("owner_check"):
        out += ["", "### 需 owner 确认", "", question["owner_check"].strip()]
    body = answer if answer else NO_ANSWER
    out += ["", "### 作答", "", *(f"> {line}".rstrip() for line in body.splitlines())]
    return out


def _place_lines(question: dict) -> list[str]:
    lines = [f"- 表：`{question['table']}`"] if question.get("table") else []
    if question.get("concept"):
        lines.append(f"- 概念：`{question['concept']}`")
    return lines


def _subject(document: dict) -> str:
    return document.get("subject") or "（未命名问题集）"
