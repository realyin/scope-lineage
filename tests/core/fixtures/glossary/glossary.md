# 术语与值域字典

- 语料根目录：`tests/core/fixtures/lineage_contract`；任务 13 个，写语句 13 条。
- 术语 29 个（注释冲突 0 个）；值域观察 11 条（封闭集 4 条，含义候选 2 条）；参数化值 0 条。
- 人工确认（overrides）：术语 0 条、值 0 条生效；未命中键 0 个。
- 含义只有两个来源：人工确认（✓）与语料自己写下的候选（?：注释里字面出现或枚举该值，或 CASE 把它标成某个标签）；其余一律写「待确认」，Core 不猜。

## band

- 术语（1 张表）：Amount band（1 张表：`mart.metric_by_segment`）
- 列含义：待确认

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `'HIGH'` | `cte:agg.band`（scope 级） | literal | 1 | case_then | case_exhaustive：`HIGH`、`LOW` | 待确认 |
| `'LOW'` | `cte:agg.band`（scope 级） | literal | 1 | case_then | case_exhaustive：`HIGH`、`LOW` | 待确认 |

## band_total

- 术语（1 张表）：Band level total（1 张表：`mart.metric_by_segment`）
- 列含义：待确认

## channel_code

- 术语：2 张表有这个列，没有一张写了列注释。
- 缺列注释的表（2/2）：`dim.channel`、`ods.channel_event`
- 列含义：待确认

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `'A'` | `ods.channel_event.channel_code` | literal | 1 | case_condition | — | ? ONLINE（case_label） |

## channel_name

- 术语：1 张表有这个列，没有一张写了列注释。
- 缺列注释的表（1/1）：`mart.channel_summary`
- 列含义：待确认

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `'OFFLINE'` | `mart.channel_summary.channel_name` | literal | 1 | case_then | case_exhaustive：`ONLINE`、`OFFLINE` | 待确认 |
| `'ONLINE'` | `mart.channel_summary.channel_name` | literal | 1 | case_then | case_exhaustive：`ONLINE`、`OFFLINE` | 待确认 |

## cnt

- 术语（1 张表）：Row count（1 张表：`mart.metric_by_segment`）
- 列含义：待确认

## flagged

- 术语：1 张表有这个列，没有一张写了列注释。
- 缺列注释的表（1/1）：`mart.flags`
- 列含义：待确认

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `'a\nb'` | `mart.flags.flagged` | literal | 1 | case_then | — | 待确认 |

## is_active

- 术语：1 张表有这个列，没有一张写了列注释。
- 缺列注释的表（1/1）：`ods.users`
- 列含义：待确认

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `1` | `ods.users.is_active` | literal | 1 | filter_eq | — | 待确认 |

## name

- 术语：1 张表有这个列，没有一张写了列注释。
- 缺列注释的表（1/1）：`ods.users`
- 列含义：待确认

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `'x；y → z\|w'` | `ods.users.name` | literal | 1 | case_condition | — | ? a\nb（case_label） |

## rn

- 术语：本语料的元数据里没有这个列。

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `1` | `cte:latest_dim.rn`（scope 级） | literal | 1 | join_condition | — | 待确认 |
| `1` | `cte:ranked.rn`（scope 级） | literal | 1 | filter_eq | — | 待确认 |

## segment

- 术语（3 张表）：Segment code（1 张表：`mart.metric_by_segment`）
- 缺列注释的表（2/3）：`dim.segment_dim`、`ods.events_a`
- 列含义：待确认

## segment_name

- 术语（2 张表）：Segment display name（1 张表：`mart.metric_by_segment`）
- 缺列注释的表（1/2）：`dim.segment_dim`
- 列含义：待确认

## status

- 术语：1 张表有这个列，没有一张写了列注释。
- 缺列注释的表（1/1）：`ods.channel_event`
- 列含义：待确认

| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `'ACTIVE'` | `ods.channel_event.status` | literal | 1 | filter_eq | — | 待确认 |

## total

- 术语（1 张表）：Summed amount（1 张表：`mart.metric_by_segment`）
- 列含义：待确认

## 其余列

- 另有 17 个列名在本语料里既没有列注释，也没有被任何常量比较过，本字典只记录它们的存在：`account_id`、`account_key`、`amount`、`balance`、`balance_value`、`batch_id`、`customer_id`、`customer_name`、`entry_id`、`id`、`parent_id`、`seg_code`、`total_amount`、`updated_at`、`user_id`、`user_name`、`v`
