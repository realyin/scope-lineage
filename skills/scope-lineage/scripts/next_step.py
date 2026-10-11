#!/usr/bin/env python3
"""Say where a runbook run stands and what to do next.

An orchestrator working through ``references/runbook.md`` has to keep fourteen steps, a
per-table decision table (appendix A) and a dozen file conventions (appendix B) in its
head. One that loses track skips a step, redoes a finished one, or stops at the key-fold
``ontology`` and calls it done. This script reads only the files a run directory already
holds and prints:

  - the S0–S13 checklist, each step ``[x]`` done, ``[ ]`` not yet, or ``[-]`` skipped;
  - the current step, why it is current, and the runbook section to follow;
  - while table semantics is in progress (S4–S9), each table's next action and template,
    taken from appendix A.

It never recomputes a table's stage. It reads ``$RUN/status.json`` as ``semantic status
--json`` wrote it, and when that file is missing or older than anything under ``docs/``,
``reviews/``, ``reviews_prev/``, ``packets/`` or the table pages (rendering moves a table to
``rendered``) it says so and prints the command that refreshes it. A step counts as done only when the files that step writes are there; the
script cannot tell whether their content is right -- each step's completion test in the
runbook still decides that.

  next_step.py RUN

Exit 0 with the report on stdout; exit 2 when RUN is not a directory. Read-only; standard
library only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

STEPS = [
    ("S0", "环境、版本与运行目录"),
    ("S1", "血缘解析"),
    ("S2", "表卡与术语"),
    ("S3", "选表与材料包"),
    ("S4", "写作"),
    ("S5", "校验与 blocked"),
    ("S6", "审读"),
    ("S7", "修订"),
    ("S8", "状态推进与复审"),
    ("S9", "全量校验与渲染表语义页"),
    ("S10a", "起点目录"),
    ("S10b", "起草材料 digest"),
    ("S10c", "起草概念与分组方案"),
    ("S10d", "片段"),
    ("S10e", "合并"),
    ("S10f", "合并后的手工修正"),
    ("S10g", "构建与渲染"),
    ("S11", "回归验收"),
    ("S12", "确认回写（可选）"),
    ("S13", "交付"),
]
ORDER = {step: index for index, (step, _) in enumerate(STEPS)}
TITLE = dict(STEPS)
STATUS_COMMAND = (
    'load_tables && sl semantic status "$RUN" --pages "$SEMPAGES" --json "$RUN/status.json" '
    '--only "${TABLES[@]}"'
)
GROUP = re.compile(r"^##\s+组\s+(\S+)\s*$", re.M)
# Table semantics is under way but status.json cannot say where: S4–S9 are all unknown.
REFRESH = "刷新状态"
TABLE_STEPS = {"S4", "S5", "S6", "S7", "S8", "S9"}


def _lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _question_set(run: Path) -> str:
    """The value of ``export Q=`` in env.sh, without a trailing comment."""
    for line in _lines(run / "env.sh"):
        if line.startswith("export Q="):
            return line.removeprefix("export Q=").split("#", 1)[0].strip().strip("'\"")
    return ""


def _newest(run: Path, pages: Path) -> float:
    newest = 0.0
    for directory in [run / name for name in ("docs", "reviews", "reviews_prev", "packets")] + [pages]:
        for path in directory.rglob("*"):
            if path.is_file():
                newest = max(newest, path.stat().st_mtime)
    return newest


def _table_action(run: Path, row: dict) -> tuple[str, str]:
    """Appendix A: (step, action) for one table's stage and flags."""
    table, stage, flags = row["table"], row["stage"], set(row.get("flags") or [])
    review = row.get("review") or {}
    if "doc_misfiled" in flags:
        return "S4", "停：doc_misfiled，按附录 A 最后一行把 docs/ 里的文件改回 docs/<table>.json"
    if stage == "no_packet":
        return "S3", "建材料包（核对 tables.txt 拼写，不带 catalog 前缀）"
    if stage == "packet":
        return "S4", "S4 新写（T1）"
    if stage == "drafted" and "packet_stale" in flags:
        return "S4", "S4 重写准备 → 修正点清单 → 新写（T1，带清单）"
    if stage == "drafted":
        return "S5", "S5：写作第 1 轮补失败（T1 补失败）；第 2 轮或修订两轮后标 blocked"
    if stage == "valid" and "review_packet_stale" in flags:
        return "S6", "旧审读移到 reviews_prev/ → S6 首审（T2）"
    if stage == "valid" and "review_stale" in flags:
        return "S6", "刚做过确认回写：sl semantic fixed；否则旧审读移到 reviews_prev/ → S6 首审（T2）"
    if stage == "valid":
        if (run / "reviews" / f"{table}.prior.md").is_file():
            return "S6", "S6 重写后首审（T2，带旧审读）"
        return "S6", "S6 首审（T2）"
    if stage == "reviewed" and "review_unparsed" in flags:
        return "S6", "审读移到 reviews_prev/<table>.unparsed.md → S6 首审（T2）"
    if stage == "reviewed" and "fix_unconfirmed" in flags:
        return "S7", "刚做过确认回写：sl semantic fixed；否则 S7 核对模式（T4 核对）"
    if stage == "reviewed":
        return "S7", "S7 首修（T4），回报后存修订记录"
    if stage == "fixed":
        round1 = run / "reviews_prev" / f"{table}.round1.md"
        if (review.get("high") or 0) >= 1 and not round1.is_file():
            return "S8", "S8 复审（T3）：先备份首轮审读到 reviews_prev/<table>.round1.md"
        if "render_stale" in flags:
            return "S9", "S9 重新渲染"
        return "S9", "等其余表；全部 fixed 后 S9 渲染"
    if stage == "rendered":
        return "S10a", "完成"
    return "S4", f"未知阶段 {stage}：照附录 A 判断"


def _assess(run: Path) -> tuple[str, str, list[str], set[str]]:
    """(current step, reason, per-table lines, skipped steps)."""
    skipped = {"S12"}
    if not _question_set(run):
        skipped.add("S11")

    missing = [name for name in ("env.sh", "TOOL_VERSION", "ledger.md") if not (run / name).is_file()]
    if missing:
        return "S0", "缺 " + "、".join(missing), [], skipped
    if not list((run / "artifacts").glob("*/lineage.json")):
        return "S1", "artifacts/ 里还没有 lineage.json", [], skipped
    missing = [f"corpus/{name}" for name in ("tables.json", "glossary.json") if not (run / "corpus" / name).is_file()]
    if missing:
        return "S2", "缺 " + "、".join(missing), [], skipped

    blocked = set(_lines(run / "blocked.txt"))
    tables = [table for table in _lines(run / "tables.txt") if table not in blocked]
    if not tables:
        return "S3", "tables.txt 不存在或是空的", [], skipped
    no_packet = [table for table in tables if not (run / "packets" / table / "packet.json").is_file()]
    if no_packet:
        return "S3", "这些表还没有材料包：" + "、".join(no_packet), [], skipped

    status = run / "status.json"
    if not status.is_file():
        return REFRESH, "没有 status.json，不知道每张表在 S4–S9 的哪一步", [], skipped
    report = json.loads(status.read_text(encoding="utf-8"))
    pages = Path((report.get("directories") or {}).get("pages") or run / "site" / "semantics")
    if status.stat().st_mtime < _newest(run, pages):
        return REFRESH, "status.json 比 docs/ reviews/ packets/ 或表语义页旧，不能信", [], skipped
    rows = {row["table"]: row for row in report.get("tables", [])}
    actions = []
    for table in tables:
        row = rows.get(table, {"table": table, "stage": "no_packet"})
        actions.append((table, row["stage"], *_table_action(run, row)))
    lines = [f"  {table}  {stage}  → {action}" for table, stage, _, action in actions]
    earliest = min((step for *_, step, _ in actions), key=ORDER.__getitem__)
    if ORDER[earliest] <= ORDER["S9"]:
        return earliest, "表语义还没全部 rendered，每张表的下一步见下", lines, skipped

    if not any((run / "catalog" / name).is_file() for name in ("catalog.json", "catalog.yaml", "catalog.yml")):
        return "S10a", "catalog/ 里还没有 catalog.json 或 catalog.yaml", [], skipped
    if not (run / "digest" / "digest.md").is_file():
        return "S10b", "缺 digest/digest.md", [], skipped
    plan = run / "catalog_plan.md"
    if not plan.is_file():
        return "S10c", "缺 catalog_plan.md", [], skipped
    groups = GROUP.findall(plan.read_text(encoding="utf-8"))
    no_fragment = [group for group in groups if not (run / "fragments" / f"{group}.json").is_file()]
    if not groups or no_fragment:
        return "S10d", "这些组还没有片段：" + ("、".join(no_fragment) or "catalog_plan.md 里没有「## 组 …」"), [], skipped
    if not (run / "merged").is_dir() or not (run / "merge_report.txt").is_file():
        return "S10e", "缺 merged/ 或 merge_report.txt", [], skipped
    if not (run / "catalog_changes.md").is_file():
        return "S10f", "缺 catalog_changes.md（没有要改的也写一行「无改动」）", [], skipped
    if not (run / "onto" / "ontology.json").is_file() or not (run / "site" / "concepts").is_dir():
        return "S10g", "缺 onto/ontology.json 或 site/concepts/", [], skipped
    if "S11" not in skipped and not any((run / "round1" / "score").glob("*")):
        return "S11", "env.sh 里 Q 不为空，round1/score/ 还是空的", [], skipped
    if not (run / "RESULT.md").is_file():
        return "S13", "缺 RESULT.md", [], skipped
    return "完成", "S13 的 RESULT.md 已写", [], skipped


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：next_step.py RUN", file=sys.stderr)
        return 2
    run = Path(argv[1])
    if not run.is_dir():
        print(f"运行目录不存在：{run}", file=sys.stderr)
        return 2
    current, reason, lines, skipped = _assess(run)
    position = ORDER["S4"] if current == REFRESH else ORDER.get(current, len(STEPS))

    out = [f"运行目录：{run}", "进度："]
    for step, title in STEPS:
        if step in skipped:
            mark = "[-]"
        elif current == REFRESH and step in TABLE_STEPS:
            mark = "[?]"
        elif ORDER[step] < position:
            mark = "[x]"
        else:
            mark = "[ ]"
        out.append(f"  {mark} {step} {title}" + ("  ← 当前" if step == current else ""))
    out.append("")
    if current == "完成":
        out.append("当前：完成")
        out.append(f"原因：{reason}")
    elif current == REFRESH:
        out.append(f"当前：{REFRESH}")
        out.append(f"原因：{reason}")
        out.append(f"做法：先 . \"$RUN/env.sh\"，再跑 {STATUS_COMMAND}；然后再跑一次本脚本。")
    else:
        out.append(f"当前：{current} {TITLE[current]}")
        out.append(f"原因：{reason}")
        section = "S10" if current.startswith("S10") else current
        out.append(f"做法：读 references/runbook.md 的「{section}」一节，照前提检查、命令、完成判据做；做完再跑一次本脚本。")
    if lines:
        out.append("每张表的下一步（附录 A）：")
        out.extend(lines)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
