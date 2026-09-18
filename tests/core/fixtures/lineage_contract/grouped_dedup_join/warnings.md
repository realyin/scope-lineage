---
doc_format: "warnings-md/1"
schema_version: "1.0"
task_name: "golden_grouped_dedup_join"
target_table: "mart.metric_by_segment"
---

# 解析警告 mart.metric_by_segment

共 1 条。这些是解析过程的提示与降级说明，不改变 lineage.json 已证明的事实；影响血缘结论的信息在 mapping.md 的「不确定性与缺口」一节。

## filter_in_join_on_clause（1 条）

JOIN ON 中混有过滤条件（非连接键），注意连接语义。

- @ cte:joined：`` JOIN ON clause contains a row filter (constant comparison). Expression: `a`.`segment` = `d`.`segment` AND `d`.`rn` = 1 ``
