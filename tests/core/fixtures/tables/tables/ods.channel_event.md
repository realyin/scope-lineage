---
doc_format: "tables-md/1"
table: "ods.channel_event"
producers: 0
consumers: 2
---

# 表卡 `ods.channel_event`

## 1. 这张表是什么

- 表注释：渠道事件明细（合成）（元数据事实）
- 业务归属：业务域 渠道域；项目 渠道分析（合成）；负责人 demo_owner；分层 ODS（元数据事实）
- 别名写法：无（SQL事实）
- 语料内：0 个生产语句、2 个消费语句（SQL事实）
- 本语料用到 4/4 个字段（元数据事实）

## 2. 一行代表什么

- 本语料内没有生产任务，无法证明一行代表什么。（结构推断）

## 3. 字段

共 4 列；注释覆盖 0.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `customer_id` | 未知 | 未知 | — | 分组键 ×2、输出 ×2 |
| `channel_code` | 未知 | 未知 | — | 连接键 ×2、分组键 ×2、输出 ×2 |
| `amount` | 未知 | 未知 | — | 输出 ×2 |
| `status` | 未知 | 未知 | — | 过滤 ×2 |

## 4. 谁生产

- 本语料内没有任务写这张表。（SQL事实）

## 5. 谁消费

| 任务 | 语句 | 角色 | 用到的列 | 怎么用 |
| --- | --- | --- | --- | --- |
| `golden_commented_insert` | `stmt:001` | 聚合来源（aggregate_source） | `customer_id`、`channel_code`、`amount`、`status` | 分组键、输出、过滤、连接键 |
| `golden_commented_task` | `stmt:001` | 聚合来源（aggregate_source） | `customer_id`、`channel_code`、`amount`、`status` | 分组键、输出、过滤、连接键 |

## 6. 治理线索

- never_produced_in_corpus：本语料内没有任务写这张表；它的一行代表什么无法从本语料证明。（SQL事实；证据 golden_commented_insert/stmt:001, golden_commented_task/stmt:001）
