---
doc_format: "warnings-md/1"
schema_version: "1.0"
task_name: "golden_star_without_schema"
target_table: "mart.raw_copy"
---

# 解析警告 mart.raw_copy

共 1 条。这些是解析过程的提示与降级说明，不改变 lineage.json 已证明的事实；影响血缘结论的信息在 mapping.md 的「不确定性与缺口」一节。

## star_not_expanded（1 条）

SELECT * 未能展开（缺少 schema 元数据）。

- @ ROOT：`SELECT * could not be expanded: no schema and no resolved source columns; missing_schema_sources=ods.raw_events; sources=ods.raw_events`
