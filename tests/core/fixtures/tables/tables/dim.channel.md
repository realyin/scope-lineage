---
doc_format: "tables-md/1"
table: "dim.channel"
producers: 0
consumers: 2
---

# 表卡 `dim.channel`

## 1. 这张表是什么

- 表注释：渠道维表（合成）（元数据事实）
- 业务归属：业务域 渠道域；分层 DIM（元数据事实）
- 别名写法：无（SQL事实）
- 语料内：0 个生产语句、2 个消费语句（SQL事实）

## 2. 一行代表什么

- 本语料内没有生产任务，无法证明一行代表什么。（结构推断）

## 3. 字段

共 1 列；注释覆盖 0.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `channel_code` | 未知 | 未知 | — | 连接键 ×2 |

## 4. 谁生产

- 本语料内没有任务写这张表。（SQL事实）

## 5. 谁消费

| 任务 | 语句 | 角色 | 用到的列 | 怎么用 |
| --- | --- | --- | --- | --- |
| `golden_commented_insert` | `stmt:001` | 聚合来源（aggregate_source） | `channel_code` | 连接键 |
| `golden_commented_task` | `stmt:001` | 聚合来源（aggregate_source） | `channel_code` | 连接键 |

## 6. 治理线索

- never_produced_in_corpus：本语料内没有任务写这张表；它的一行代表什么无法从本语料证明。（SQL事实；证据 golden_commented_insert/stmt:001, golden_commented_task/stmt:001）
