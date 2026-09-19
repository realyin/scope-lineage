---
doc_format: "ontology-md/1"
table: "ods.events_a"
producers: 0
consumers: 1
---

# 表卡 `ods.events_a`

## 1. 这张表是什么

- 表注释：未知（元数据事实）
- 别名写法：无（SQL事实）
- 语料内：0 个生产语句、1 个消费语句（SQL事实）
- 本语料用到 2/2 个字段（元数据事实）

## 2. 一行代表什么

- 本语料内没有生产任务，无法证明一行代表什么。（结构推断）

## 3. 字段

共 2 列；注释覆盖 0.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `segment` | 未知 | 未知 | — | 连接键 ×1、分组键 ×1、输出 ×1 |
| `amount` | 未知 | 未知 | — | 分组键 ×1、窗口分组 ×1、输出 ×1 |

## 4. 谁生产

- 本语料内没有任务写这张表。（SQL事实）

## 5. 谁消费

| 任务 | 语句 | 角色 | 用到的列 | 怎么用 |
| --- | --- | --- | --- | --- |
| `golden_grouped_dedup_join` | `stmt:001` | 主表（driving） | `segment`、`amount` | 分组键、窗口分组、输出、连接键 |

## 6. 治理线索

- never_produced_in_corpus：本语料内没有任务写这张表；它的一行代表什么无法从本语料证明。（SQL事实；证据 golden_grouped_dedup_join/stmt:001）

## 7. 身份（本体）

- 属性 2（语料用到 2）

**候选键**

- 语料内没有可发布的候选键证据。

**多行性**

- 语料内没有任务按某个键对这张表去重或聚合。

**分区列**

- 语料内没有观察到分区列。

## 8. 关系

**出边（本表在左）**

| 对端 | 键 | JOIN 类型 | 基数 | 层级 | 依据 | 任务数 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [`dim.segment_dim`](dim.segment_dim.md) | `segment` = `segment` | LEFT_OUTER | 一对多（one_to_many） | 可推得（`implied`） | 关联前已按连接键排名去重 | 1 | `golden_grouped_dedup_join/stmt:001/cte:joined/logic:cte:joined:join:001` |
| [`ods.events_b`](ods.events_b.md) | `segment` = `seg_code`、`amount` = `amount` | — | 未知（unknown） | 可推得（`implied`） | 同一 UNION 的分支按列位置对齐 | 1 | `golden_grouped_dedup_join/stmt:001/union:events_norm` |

**入边（本表在右）**

- 无。

## 9. 约束

- 语料内没有可发布的约束。

## 10. 属性同义

| 本表列 | 同义列 | 依据 | 层级 | 证据 |
| --- | --- | --- | --- | --- |
| `segment` | `ods.events_b`.`seg_code` | UNION 同一位置（union_alignment） | 可推得（`implied`） | `golden_grouped_dedup_join/stmt:001` |

## 11. 待人工判定

- 本表没有待人工判定的项。
