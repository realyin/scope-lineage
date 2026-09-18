---
doc_format: "tables-md/1"
table: "mart.channel_summary"
producers: 2
consumers: 0
---

# 表卡 `mart.channel_summary`

## 1. 这张表是什么

- 表注释：未知（元数据事实）
- 别名写法：无（SQL事实）
- 语料内：2 个生产语句、0 个消费语句（SQL事实）

生产任务 `golden_commented_insert` 的语句头注释（SQL注释）：

> 任务：客户渠道汇总（合成示例）
> 口径：仅统计生效状态的客户
> 口径问题联系 <email>（合成地址）

生产任务 `golden_commented_task` 的语句头注释（SQL注释）：

> 任务：客户渠道汇总（合成示例）
> 口径：仅统计生效状态的客户

## 2. 一行代表什么

- `golden_commented_insert` / `stmt:001`：分组聚合后的一行；逻辑键 customer_id、channel_name；目标表无可证明的键；键置信 none（结构推断；证据 stmt:001）
- `golden_commented_task` / `stmt:001`：分组聚合后的一行；逻辑键 customer_id、channel_name；目标表无可证明的键；键置信 none（结构推断；证据 stmt:001）

## 3. 字段

共 3 列；注释覆盖 0.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `customer_id` | 未知 | 未知 | （注释未知）：直接取自 ods.channel_event.customer_id（表：渠道事件明细（合成））；注释：客户号 | — |
| `channel_name` | 未知 | 未知 | （注释未知）：channel_code = 'A' → 'ONLINE'；否则 'OFFLINE'；来源 ods.channel_event.channel_code（表：渠道事件明细（合成））；注释：渠道编码（合成值域） | — |
| `total_amount` | 未知 | 未知 | （注释未知）：按 customer_id、CASE WHEN channel_code = 'A' THEN 'ONLINE' ELSE 'OFFLINE' END 聚合：SUM(amount)；来源 ods.channel_event.amount（表：渠道事件明细（合成））；注释：金额合计（元） | — |

## 4. 谁生产

| 任务 | 语句 | 写入方式 | 分区 | 更新频率 |
| --- | --- | --- | --- | --- |
| `golden_commented_insert` | `stmt:001` | INSERT_OVERWRITE | dt（static） | 未知 |
| `golden_commented_task` | `stmt:001` | INSERT_OVERWRITE | dt（static） | DAY |

## 5. 谁消费

- 本语料内没有任务读这张表。（SQL事实）

## 6. 治理线索

- multiple_producers：2 条写语句写同一张表；下游读到的是哪一条的结果取决于调度顺序。（SQL事实；证据 golden_commented_insert/stmt:001, golden_commented_task/stmt:001）
- never_consumed_in_corpus：本语料内没有任务读这张表；可能是对外出口，也可能是无人消费的产出。（SQL事实；证据 golden_commented_insert/stmt:001, golden_commented_task/stmt:001）
