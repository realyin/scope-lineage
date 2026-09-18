---
doc_format: "tables-md/1"
table: "ods.users"
producers: 0
consumers: 2
---

# 表卡 `ods.users`

## 1. 这张表是什么

- 表注释：未知（元数据事实）
- 别名写法：无（SQL事实）
- 语料内：0 个生产语句、2 个消费语句（SQL事实）

## 2. 一行代表什么

- 本语料内没有生产任务，无法证明一行代表什么。（结构推断）

## 3. 字段

共 3 列；注释覆盖 0.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `user_id` | 未知 | 未知 | — | 输出 ×2 |
| `user_name` | 未知 | 未知 | — | 输出 ×2 |
| `is_active` | 未知 | 未知 | — | 过滤 ×1 |

## 4. 谁生产

- 本语料内没有任务写这张表。（SQL事实）

## 5. 谁消费

| 任务 | 语句 | 角色 | 用到的列 | 怎么用 |
| --- | --- | --- | --- | --- |
| `golden_directory_target` | `stmt:001` | 主表（driving） | `user_id`、`user_name` | 输出 |
| `golden_simple_insert` | `stmt:001` | 主表（driving） | `user_id`、`user_name`、`is_active` | 输出、过滤 |

## 6. 治理线索

- never_produced_in_corpus：本语料内没有任务写这张表；它的一行代表什么无法从本语料证明。（SQL事实；证据 golden_directory_target/stmt:001, golden_simple_insert/stmt:001）
