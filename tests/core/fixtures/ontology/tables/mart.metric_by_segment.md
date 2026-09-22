---
doc_format: "ontology-md/2"
table: "mart.metric_by_segment"
producers: 1
consumers: 0
---

# 表卡 `mart.metric_by_segment`

## 1. 这张表是什么

- 表注释：未知（元数据事实）
- 别名写法：无（SQL事实）
- 语料内：1 个生产语句、0 个消费语句（SQL事实）
- 本语料用到 6/7 个字段（元数据事实）

## 2. 一行代表什么

- `golden_grouped_dedup_join` / `stmt:001`：分组聚合后的一行；逻辑键 segment、band；目标表候选键 segment、band；键置信 proven（结构推断；证据 stmt:001）

## 3. 字段

共 7 列，用到 6 列；注释覆盖 1.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `segment` | string | Segment code | Segment code：直接取自 ods.events_a.segment（注释未知）、ods.events_b.seg_code（注释未知） | — |
| `band` | string | Amount band | Amount band：amount >= 100 → 'HIGH'；否则 'LOW'；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知） | — |
| `total` | decimal(18,2) | Summed amount | Summed amount：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知） | — |
| `cnt` | bigint | Row count | Row count：按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：COUNT(1) | — |
| `band_total` | decimal(18,2) | Band level total | Band level total：amount >= 100 → 'HIGH'；否则 'LOW'，再按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 聚合：SUM(amount)，再窗口函数 SUM(total)；按 band 分组；来源 ods.events_a.amount（注释未知）、ods.events_b.amount（注释未知） | — |
| `segment_name` | string | Segment display name | Segment display name：直接取自 dim.segment_dim.segment_name（注释未知）（关联未命中时为空） | — |
| `dt` | string | Partition date | — | — |

## 4. 谁生产

| 任务 | 语句 | 写入方式 | 分区 | 更新频率 |
| --- | --- | --- | --- | --- |
| `golden_grouped_dedup_join` | `stmt:001` | INSERT_OVERWRITE | dt（static） | 未知 |

## 5. 谁消费

- 本语料内没有任务读这张表。（SQL事实）

## 6. 治理线索

- never_consumed_in_corpus：本语料内没有任务读这张表；可能是对外出口，也可能是无人消费的产出。（SQL事实；证据 golden_grouped_dedup_join/stmt:001）

## 7. 身份（本体）

- 本表暂自成概念「metric_by_segment」（provisional），待评审归并（`concept:table:mart_metric_by_segment`）。

- 属性 7（语料用到 6）

**候选键**

- `segment`、`band` — 已证明（`proven`）；证据 `golden_grouped_dedup_join/stmt:001`

**元数据键线索**

- 元数据注释没有把任何列称作主键或唯一键。

**多行性**

- 语料内没有任务按某个键对这张表去重或聚合。

**分区列**

- `dt` — 已证明（`proven`）

## 8. 关系

**概念关系**

- 本表所属概念没有可发布的概念关系。

**表级 JOIN（证据）**

*出边（本表在左）*

- 无。

*入边（本表在右）*

- 无。

## 9. 约束

以下都是「metric_by_segment」（`concept:table:mart_metric_by_segment`）这一份表现上的事实。

| 约束 | 目标 | 值集 / 完整性 | 层级 | 证据 |
| --- | --- | --- | --- | --- |
| 每键唯一（unique_per） | 整表 | `segment`、`band`、`dt` | 已证明（`proven`） | `golden_grouped_dedup_join/stmt:001` |
| 分区列（partition） | `dt` | — | 已证明（`proven`） | `golden_grouped_dedup_join/stmt:001` |

## 10. 属性同义

以下都是「metric_by_segment」（`concept:table:mart_metric_by_segment`）这一份表现上的事实。

- 语料内没有证明本表任何列与别处同名异写。

## 11. 待人工判定

以下都是「metric_by_segment」（`concept:table:mart_metric_by_segment`）这一份表现上的事实。

- 本表没有待人工判定的项。
