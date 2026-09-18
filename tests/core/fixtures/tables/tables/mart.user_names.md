---
doc_format: "tables-md/1"
table: "mart.user_names"
producers: 1
consumers: 0
---

# 表卡 `mart.user_names`

## 1. 这张表是什么

- 表注释：未知（元数据事实）
- 别名写法：无（SQL事实）
- 语料内：1 个生产语句、0 个消费语句（SQL事实）

## 2. 一行代表什么

- `golden_simple_insert` / `stmt:001`：主表的一行；目标表无可证明的键；键置信 none（结构推断；证据 stmt:001）

## 3. 字段

共 2 列；注释覆盖 0.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `user_id` | 未知 | 未知 | （注释未知）：直接取自 ods.users.user_id（注释未知） | — |
| `user_name` | 未知 | 未知 | （注释未知）：直接取自 ods.users.user_name（注释未知） | — |

## 4. 谁生产

| 任务 | 语句 | 写入方式 | 分区 | 更新频率 |
| --- | --- | --- | --- | --- |
| `golden_simple_insert` | `stmt:001` | INSERT_OVERWRITE | 无分区 | 未知 |

## 5. 谁消费

- 本语料内没有任务读这张表。（SQL事实）

## 6. 治理线索

- never_consumed_in_corpus：本语料内没有任务读这张表；可能是对外出口，也可能是无人消费的产出。（SQL事实；证据 golden_simple_insert/stmt:001）
