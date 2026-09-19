---
doc_format: "ontology-index-md/1"
task_count: 5
entity_count: 9
relation_count: 4
---

# 语料本体候选索引

共 5 个任务、9 个实体、4 条关系、5 条约束、0 条待人工判定的发现。

每条断言都带置信层级：`proven`（SQL 直接写着）、`implied`（可由结构证明的推论）、`hypothesis`（作者假设，未被证明）、`conflict`（跨任务证据矛盾）。

## 关系

| 关系 | 从 | 到 | 类型 | 基数 | 层级 | 依据 | 任务数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rel:001 | `ods.channel_event`.`channel_code` | `dim.channel`.`channel_code` | join_association | many_to_one_assumed | hypothesis | right_side_not_deduplicated | 2 |
| rel:002 | `ods.events_a`.`segment` | `dim.segment_dim`.`segment` | join_association | one_to_many | implied | ranking_window | 1 |
| rel:003 | `ods.events_a`.`segment`、`amount` | `ods.events_b`.`seg_code`、`amount` | union_sibling | unknown | implied | union_branch_alignment | 1 |
| rel:004 | `ods.events_b`.`seg_code` | `dim.segment_dim`.`segment` | join_association | one_to_many | implied | ranking_window | 1 |

## 待人工判定

本语料没有发现矛盾证据。
