---
doc_format: "warnings-md/1"
schema_version: "1.0"
task_name: "golden_fact_gap"
target_table: "mart.amounts"
---

# 解析警告 mart.amounts

共 1 条。这些是解析过程的提示与降级说明，不改变 lineage.json 已证明的事实；影响血缘结论的信息在 mapping.md 的「不确定性与缺口」一节。

## ambiguous_unqualified（1 条）

未限定列有多个可行来源，保持歧义未归属。

- @ ROOT：`Unqualified column 'amount' found in multiple viable sources (ods.ledger_a, ods.ledger_b); left ambiguous rather than attributed to one`
