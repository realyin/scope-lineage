---
doc_format: "concept-md/1"
id: "concept:channel"
name: "渠道"
kind: "entity"
tier: "hypothesis"
name_tier: "hypothesis"
table_count: 2
relation_count: 1
---

# 渠道（实体）

`concept:channel` · 名字 `hypothesis` · 种类 `implied` · 概念 `hypothesis` · 表现表 2 张 · 属性 2 个

概念是**候选**：名字永远是作者假设，种类由 `kind_evidence[]` 的投票决定。索引见 [`ontology.md`](../ontology.md)，表一级的证据见 [`appendix.md`](../appendix.md)。

## 表现

| 表 | 角色 | 依据 | 粒度 |
| --- | --- | --- | --- |
| [`dim.channel`](../tables/dim.channel.md) | 主表 | `key:hypothesis` | — |
| [`ods.channel_event`](../tables/ods.channel_event.md) | 引用 | `reference` | — |

## 属性

共 2 个属性（按词根折叠），逐条如下：

| 词根 | 类型 | 注释 | 来源列 |
| --- | --- | --- | --- |
| `channel` | — | — | `dim.channel`.`channel_code` |
| `channel_name` | — | — | `dim.channel`.`channel_name` |

## 约束

- 本概念的表现表上没有可发布的约束。

## 关系

| 方向 | 对端 | 类型 | 角色 | 基数 | 层级 | 证据数 | 关系 id |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 入 | 渠道事件 | 关联 | — | 多对一，作者假设 | `hypothesis` | 1 | `crel:001` |

**证据：表级 JOIN**

| 表级关系 | 折入 | 从 | 到 | 基数 | 层级 | 依据 | 任务数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `rel:001` | `crel:001` | `ods.channel_event`.`channel_code` | `dim.channel`.`channel_code` | 多对一，作者假设 | `hypothesis` | 直接关联未去重，作者假设对端按该键唯一 | 2 |

## 待人工判定

1 个**概念级**问题。一个问题答一次，工具按下面的「展开」逐表写回 `ontology.overrides.json`；表一级的逐条清单在 `open_items[]` 里，仍然完整。

- 候选键（`open:concept:concept:channel:key=channel`，折了 1 条，影响 1，层级 `hypothesis`）：概念「渠道」是否按 `channel_code` 唯一？（1 张表现表）
  - 覆盖表现表 1 张：`dim.channel`
  - 概念级回写 `概念键:concept:channel=channel`——写在 `ontology.overrides.json` 的 `concepts` 下，展开成 1 条表级确认：`键:dim.channel=channel_code`
  - 表级条目：`open:key:dim.channel=channel_code`

## 命名与类别依据

**命名候选**

| 名字 | 来源 | 次数 | 证据表 |
| --- | --- | --- | --- |
| 渠道 | `table_comment` | 1 | `dim.channel` |
| channel | `key_stem` | 1 | — |

**种类证据**

| 信号 | 投票 | 表 | 细节 |
| --- | --- | --- | --- |
| `all_members_full_snapshot` | 实体 | — | — |
| `word_hint` | 实体 | `dim.channel` | dim.channel 渠道维表（合成） |

## 评审回写键

- 在 `concepts.overrides.json` 的 `concepts` 下写 `concept:channel`——这一串与索引的概念表、本文件的标题行、以及每张表卡第 7 节印的逐字一致。
- 可确认的槽位：`name`（业务名）、`kind`（`entity` / `event` / `summary`）、`roles`（改某张成员表的角色）、`add_tables`（加一张成员表），连同 `confirmed_by` / `date` / `basis` 一起写。
