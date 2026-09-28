"""What a conclusion is about, what makes it hold, and which rule said so.

A conclusion this package publishes -- a key set is unique, a JOIN cannot duplicate rows,
a column takes only these values -- is true of one object and not of the next one up. A
GROUP BY makes one query's output unique; it says nothing about the table an append
writes that output into. The first round of the deep assessment (F1-F6) found the same
mistake six times in six modules: a conclusion carried, silently, to an object it does
not hold for.

This module is where that knowledge lives instead. ``RULES`` names every inference the
package makes and whether it is *sound* (the SQL guarantees the conclusion for the stated
subject) or a *heuristic* (it reads the author's intent, a name or a comment).
``tests/architecture/test_claim_producers.py`` makes every function that decides a
strength name the rules it applies.

See ``dev-notes/plans/2026-09-28-assertion-model-design.md``.
"""

from __future__ import annotations

from typing import NamedTuple

SOUND = "sound"
HEURISTIC = "heuristic"
CONFLICT = "conflict"


class Rule(NamedTuple):
    kind: str
    text: str


RULES: dict[str, Rule] = {
    # -- one query's output rows
    "R-GROUPBY-KEY": Rule(SOUND, "GROUP BY 使输出按分组键唯一"),
    "R-DISTINCT-KEY": Rule(SOUND, "DISTINCT 使输出按全部输出列唯一"),
    "R-ROWNUM-FIRST": Rule(SOUND, "row_number() = 1 使每个分区至多一行"),
    "R-RANK-FIRST": Rule(HEURISTIC, "rank()/dense_rank() = 1 表达去重意图，保留并列，不证明唯一"),
    "R-EMPTY-GROUPING": Rule(SOUND, "没有 GROUP BY 的聚合输出一行"),
    "R-PIN-DROP": Rule(SOUND, "AND 顶层的等值钉住使该列在 scope 内为常量，离开键集"),
    "R-JOIN-PRESERVE": Rule(SOUND, "右侧按连接键唯一时 JOIN 不放大左侧行"),
    "R-JOIN-BEFORE-GROUPING": Rule(SOUND, "分组之前的 JOIN 放大被聚合的行，不增加输出行"),
    "R-CANDIDATE-CAP": Rule(SOUND, "借用了候选键（未证明）的结论不强于候选"),
    # -- from one write to the table it writes
    "R-REPLACE-STATE": Rule(SOUND, "整表覆盖写入的批次结论成为该表状态的结论"),
    "R-PARTITION-STATE": Rule(SOUND, "分区覆盖写入只对分区成立；表级键集加上分区列"),
    "R-READ-PIN": Rule(SOUND, "读侧把分区列钉成常量时，分区内的键成为这次读取的键"),
    "R-PRODUCERS-AGREE": Rule(SOUND, "多个生产者都整表覆盖且键一致时结论成立，否则撤销"),
    "R-PARTITION-METADATA": Rule(SOUND, "分区列是写入的元数据事实"),
    # -- values
    "R-IN-FILTER": Rule(SOUND, "WHERE c IN (...) 限定本语句读到的行的 c，不限定物理列"),
    "R-CASE-OUTPUT": Rule(SOUND, "穷尽 CASE 的输出列只取分支常量"),
    "R-NOT-NULL-FILTER": Rule(SOUND, "x IS NOT NULL 过滤只约束本语句读到的行"),
    # -- structure between columns
    "R-UNION-ALIGN": Rule(SOUND, "UNION 同位置的列是同一输出列的来源"),
    "R-DIRECT-RENAME": Rule(SOUND, "DIRECT 透传且列名不同是改名"),
    # -- the author's intent, names and comments
    "R-INTENT-DEDUP": Rule(HEURISTIC, "关联前按 k 去重，推测那张表按 k 有多行"),
    "R-DIRECT-JOIN": Rule(HEURISTIC, "直接按 k 关联物理表，推测作者认为它按 k 唯一"),
    "R-COMMENT-HINT": Rule(HEURISTIC, "列注释称某列为主键/唯一键"),
    "R-COMMENT-RELATION": Rule(HEURISTIC, "列注释指向另一张表的列"),
    "R-HINT-AGREEMENT": Rule(HEURISTIC, "两条独立线索说同一件事，比任一条强一级"),
    "R-KIND-VOTES": Rule(HEURISTIC, "概念种类由各信号投票，一致为 implied，打架为 hypothesis"),
    "R-CONCEPT-NAME": Rule(HEURISTIC, "概念名来自候选名，只有键词干时算无人命名"),
    "R-HUMAN-CONFIRM": Rule(HEURISTIC, "评审者给出的回答"),
    # -- evidence against a conclusion
    "R-CONFLICT": Rule(CONFLICT, "两条结论互相矛盾，发布为发现，不发布为事实"),
}
