---
doc_format: "tables-index-md/1"
task_count: 5
table_count: 9
---

# 语料表卡索引

共 5 个任务、9 张表（会话内关系与目录写入已排除）。

| 表 | 生产任务数 | 消费任务数 | 表注释 | 业务域 | 键置信 |
| --- | --- | --- | --- | --- | --- |
| [`dim.channel`](tables/dim.channel.md) | 0 | 2 | 有 | 渠道域 | — |
| [`dim.segment_dim`](tables/dim.segment_dim.md) | 0 | 1 | 无 | — | — |
| [`mart.channel_summary`](tables/mart.channel_summary.md) | 2 | 0 | 无 | — | none |
| [`mart.metric_by_segment`](tables/mart.metric_by_segment.md) | 1 | 0 | 无 | — | proven |
| [`mart.user_names`](tables/mart.user_names.md) | 1 | 0 | 无 | — | none |
| [`ods.channel_event`](tables/ods.channel_event.md) | 0 | 2 | 有 | 渠道域 | — |
| [`ods.events_a`](tables/ods.events_a.md) | 0 | 1 | 无 | — | — |
| [`ods.events_b`](tables/ods.events_b.md) | 0 | 1 | 无 | — | — |
| [`ods.users`](tables/ods.users.md) | 0 | 2 | 无 | — | — |
