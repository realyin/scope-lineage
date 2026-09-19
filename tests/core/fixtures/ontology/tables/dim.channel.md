---
doc_format: "ontology-md/1"
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
- 本语料用到 1/2 个字段（元数据事实）

## 2. 一行代表什么

- 本语料内没有生产任务，无法证明一行代表什么。（结构推断）

## 3. 字段

共 2 列，用到 1 列；注释覆盖 0.0（元数据事实）。

| 列 | 类型 | 注释 | 生产侧语义（结构推断） | 消费侧用法（SQL事实） |
| --- | --- | --- | --- | --- |
| `channel_code` | 未知 | 未知 | — | 连接键 ×2 |
| `channel_name` | 未知 | 未知 | — | — |

## 4. 谁生产

- 本语料内没有任务写这张表。（SQL事实）

## 5. 谁消费

| 任务 | 语句 | 角色 | 用到的列 | 怎么用 |
| --- | --- | --- | --- | --- |
| `golden_commented_insert` | `stmt:001` | 聚合来源（aggregate_source） | `channel_code` | 连接键 |
| `golden_commented_task` | `stmt:001` | 聚合来源（aggregate_source） | `channel_code` | 连接键 |

## 6. 治理线索

- never_produced_in_corpus：本语料内没有任务写这张表；它的一行代表什么无法从本语料证明。（SQL事实；证据 golden_commented_insert/stmt:001, golden_commented_task/stmt:001）

## 7. 身份（本体）

- 属性 2（语料用到 1）

**候选键**

- `channel_code` — 作者假设（`hypothesis`）；证据 `golden_commented_insert/stmt:001/logic:ROOT:join:001`、`golden_commented_task/stmt:001/logic:ROOT:join:001`

**元数据键线索**

- 元数据注释没有把任何列称作主键或唯一键。

**多行性**

- 语料内没有任务按某个键对这张表去重或聚合。

**分区列**

- 语料内没有观察到分区列。

## 8. 关系

**出边（本表在左）**

- 无。

**入边（本表在右）**

| 对端 | 键 | JOIN 类型 | 基数 | 层级 | 依据 | 任务数 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [`ods.channel_event`](ods.channel_event.md) | `channel_code` = `channel_code` | LEFT_OUTER | 多对一，作者假设（many_to_one_assumed） | 作者假设（`hypothesis`） | 直接关联未去重，作者假设对端按该键唯一 | 2 | `golden_commented_insert/stmt:001/ROOT/logic:ROOT:join:001`、`golden_commented_task/stmt:001/ROOT/logic:ROOT:join:001` |

## 9. 约束

- 语料内没有可发布的约束。

## 10. 属性同义

- 语料内没有证明本表任何列与别处同名异写。

## 11. 待人工判定

- [待确认] 候选键 `channel_code`：只有任务直接关联时的假设，语料没有证明它唯一。回写 `键:dim.channel=channel_code`。（清单 `open:key:dim.channel=channel_code`）
- [待确认] 关系 `ods.channel_event` → `dim.channel` 的基数写作「多对一，作者假设」，依据只是直接关联未去重，作者假设对端按该键唯一。回写 `关系:ods.channel_event.channel_code->dim.channel.channel_code`。（清单 `open:rel:ods.channel_event.channel_code->dim.channel.channel_code`）
