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

from dataclasses import dataclass, replace
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
    "R-VALUES-DISTINCT": Rule(SOUND, "内联 VALUES 的字面量行在连接键上互不相同（等值钉住过滤后）"),
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
    "R-DRIVING-KEYS": Rule(HEURISTIC, "驱动表粒度下写出的全部连接键作为候选键"),
    "R-COMMENT-HINT": Rule(HEURISTIC, "列注释称某列为主键/唯一键"),
    "R-FILTER-HINT": Rule(HEURISTIC, "某个任务的过滤条件（取值、非空）暗示物理列的取值特征"),
    "R-COMMENT-RELATION": Rule(HEURISTIC, "列注释指向另一张表的列"),
    "R-HINT-AGREEMENT": Rule(HEURISTIC, "两条独立线索说同一件事，比任一条强一级"),
    "R-KIND-VOTES": Rule(HEURISTIC, "概念种类由各信号投票，一致为 implied，打架为 hypothesis"),
    "R-CONCEPT-NAME": Rule(HEURISTIC, "概念名来自候选名，只有键词干时算无人命名"),
    "R-HUMAN-CONFIRM": Rule(HEURISTIC, "评审者给出的回答"),
    # -- evidence against a conclusion
    "R-CONFLICT": Rule(CONFLICT, "两条结论互相矛盾，发布为发现，不发布为事实"),
}


# ------------------------------------------------------------------ premises

# What SQL text can never prove and a conclusion may still rest on, named so a claim can
# say which of them it needs instead of leaving them implicit.
ASSUMPTIONS: dict[str, str] = {
    "A-WRITERS-CLOSED": "语料包含了这张表的全部写入任务",
    "A-METADATA-AUTHORITATIVE": "元数据（DDL、分区、覆盖模式声明）与线上一致",
    "A-RUN-SUCCEEDED": "脚本按顺序完整执行成功",
    "A-NO-CONCURRENT-WRITE": "读取时刻没有并发写入",
    "A-DIALECT-SEMANTICS": "Spark/Hive 按默认配置的语义（排序稳定性、NULL 语义）",
}

# The premises a `proven` claim may rest on. Owner decision A (2026-09-28): all of them.
# A claim needing any other premise is at most `conditional`.
STANDARD_ASSUMPTIONS: tuple[str, ...] = tuple(ASSUMPTIONS)


# ------------------------------------------------------------------ the claim record

# What a claim is about. The order is the only direction a claim may be carried, and only
# by a named rule: a query's rows, the batch a write stores, one partition of a table,
# the whole table, and what one read of it sees.
SUBJECT_QUERY_ROWS = "query_rows"
SUBJECT_WRITE_BATCH = "write_batch"
SUBJECT_PARTITION_STATE = "partition_state"
SUBJECT_TABLE_STATE = "table_state"
SUBJECT_READ_VIEW = "read_view"
SUBJECT_PHYSICAL_COLUMN = "physical_column"
SUBJECT_KINDS = (
    SUBJECT_QUERY_ROWS,
    SUBJECT_WRITE_BATCH,
    SUBJECT_PARTITION_STATE,
    SUBJECT_TABLE_STATE,
    SUBJECT_READ_VIEW,
    SUBJECT_PHYSICAL_COLUMN,
)

# Strongest first. `conditional` is a sound rule with a condition this subject does not
# discharge itself; `conflicted` has evidence against it; `unknown` is no conclusion.
PROVEN = "proven"
CONFIRMED = "confirmed"
CONDITIONAL = "conditional"
HYPOTHESIS = "hypothesis"
CONFLICTED = "conflicted"
UNKNOWN = "unknown"
STATUSES = (PROVEN, CONFIRMED, CONDITIONAL, HYPOTHESIS, CONFLICTED, UNKNOWN)


class Subject(NamedTuple):
    kind: str
    ref: tuple


@dataclass(frozen=True)
class Claim:
    """One conclusion about one subject, by one rule.

    ``defeaters`` are ``(code, text)`` pairs: evidence the corpus holds against carrying
    the conclusion to this subject. A claim with any defeater is never ``proven`` -- the
    card that reports a producer conflict used to show it and prove the key anyway.
    """

    kind: str
    subject: Subject
    content: tuple
    status: str
    rule: str
    evidence: tuple = ()
    conditions: tuple = ()
    assumptions: tuple = ()
    defeaters: tuple = ()

    def __post_init__(self) -> None:
        if self.rule not in RULES:
            raise ValueError(f"undeclared rule {self.rule!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.subject.kind not in SUBJECT_KINDS:
            raise ValueError(f"unknown subject kind {self.subject.kind!r}")
        if self.status == PROVEN and RULES[self.rule].kind != SOUND:
            raise ValueError(f"{self.rule} is a heuristic rule and cannot prove")
        if self.status == PROVEN and self.defeaters:
            raise ValueError("a claim with a defeater cannot be proven")
        for assumption in self.assumptions:
            if assumption not in ASSUMPTIONS:
                raise ValueError(f"unregistered premise {assumption!r}")
            if self.status == PROVEN and assumption not in STANDARD_ASSUMPTIONS:
                raise ValueError(f"a proven claim cannot rest on {assumption}")

    def weakened_to(self, status: str) -> "Claim":
        """This claim at ``status`` or weaker -- never stronger than it already is."""
        weaker = max(STATUSES.index(self.status), STATUSES.index(status))
        return replace(self, status=STATUSES[weaker])

    def defeated_by(self, code: str, text: str) -> "Claim":
        """This claim with one more piece of evidence against it, no longer a proof."""
        weakened = self.weakened_to(UNKNOWN) if self.status == PROVEN else self
        return replace(weakened, defeaters=(*self.defeaters, (code, text)))


def claim_json(claim: Claim | None) -> dict | None:
    """A claim as the plain JSON the documents publish: tuples become lists."""
    if claim is None:
        return None
    return {
        "kind": claim.kind,
        "subject": {"kind": claim.subject.kind, "ref": _plain(claim.subject.ref)},
        "content": _plain(claim.content),
        "status": claim.status,
        "rule": claim.rule,
        "evidence": _plain(claim.evidence),
        "conditions": _plain(claim.conditions),
        "assumptions": _plain(claim.assumptions),
        "defeaters": _plain(claim.defeaters),
    }


def _plain(value):
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value
