"""``score.md``: the ``question-score/1`` report as tables a person reads."""

from __future__ import annotations


def render_score_markdown(report: dict) -> str:
    total = report["total"]
    previous = [r["round"] for r in report["rounds"][:-1]]
    out = [
        f"# 验收评分：{report['subject']}（{report['round']}）",
        "",
        f"- 问题集：`{report['set']}`",
        f"- 得分 {total['points']} / {total['max']}（{_pct(total['percent'])}），"
        f"已判 {total['graded']} / {total['questions']} 题",
    ]
    if report["ungraded"]:
        out.append(f"- 未判分（不计入总分）：{', '.join(report['ungraded'])}")
    out += ["", "## 总分", "", _line(["轮次", "已判", "得分", "满分", "得分率"]), _line(["---"] * 5)]
    for row in report["rounds"]:
        t = row["total"]
        out.append(_line([row["round"], t["graded"], t["points"], t["max"], _pct(t["percent"])]))
    out += _breakdown("按题型", "题型", report["by_type"], previous)
    out += _breakdown("按表", "表 / 概念", report["by_table"], previous)
    out += ["", "## 按缺口", "", "| 缺口 | 题数 | 失分 |", "| --- | --- | --- |"]
    out += [f"| {r['gap']} | {r['count']} | {r['lost']} |" for r in report["by_gap"]]
    out += _rows("失分清单", report["lost"])
    out += _rows("参考答案待修正（key_wrong）", report["key_wrong"])
    out += _changes(report["changes"], [r["round"] for r in report["rounds"]])
    return "\n".join(out) + "\n"


def _breakdown(title: str, name: str, rows: list[dict], previous: list[str]) -> list[str]:
    head = ["题数", "已判", "得分", "满分", "得分率", *previous]
    out = ["", f"## {title}", "", _line([name, *head]), _line(["---"] * (len(head) + 1))]
    for row in rows:
        cells = [row["key"], row["questions"], row["graded"], row["points"], row["max"]]
        cells += [_pct(row["percent"]), *(_pct(row["rounds"][label]) for label in previous)]
        out.append(_line(cells))
    return out


def _rows(title: str, rows: list[dict]) -> list[str]:
    out = ["", f"## {title}", ""]
    if not rows:
        return [*out, "无。"]
    out += [_line(["题", "表 / 概念", "题型", "得分", "缺口", "理由"]), _line(["---"] * 6)]
    for row in rows:
        cells = [row["id"], row["table"], row["type"], row["score"], row["gap"], row["reason"]]
        out.append(_line(cells))
    return out


def _changes(changes: list[dict], labels: list[str]) -> list[str]:
    if len(labels) < 2:
        return []
    out = ["", "## 与前几轮相比变化的题", ""]
    if not changes:
        return [*out, "无。"]
    out += [_line(["题", *labels]), _line(["---"] * (len(labels) + 1))]
    for row in changes:
        scores = [row["scores"][label] for label in labels]
        out.append(_line([row["id"], *("—" if s is None else s for s in scores)]))
    return out


def _line(cells: list) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _cell(value) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value}%"
