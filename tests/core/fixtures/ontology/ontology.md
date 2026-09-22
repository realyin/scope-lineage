---
doc_format: "ontology-index-md/2"
task_count: 5
concept_count: 9
relation_count: 4
table_count: 9
table_relation_count: 4
open_item_count: 2
open_item_group_count: 2
concept_open_item_count: 2
---

# 语料本体候选索引

## 本体总览

1 个概念（实体 1、事件 0、汇总 0）、4 条概念关系，另有 8 个**临时概念**（M1：语料没能把它归到任何业务键上的表，暂时各自成一个概念，其中 4 条概念关系至少有一端是临时的）。概念是**候选**：名字永远是作者假设，种类由 `kind_evidence[]` 的投票决定，两个词根是不是同一件事留给评审那一轮判（见 `concepts.overrides.json`）。

底下是 5 个任务、9 张表、4 条表级关系、6 条约束、0 条矛盾发现，逐条见 [`appendix.md`](appendix.md)；待人工判定 2 条 / 2 组 / 2 个概念级问题（已确认 0 条）。N3：概念级那一列才是这一轮要做的决定数——同一个概念的几张表现表问的是同一件事，答一次工具逐表展开，每个概念的问题印在它自己的 `concepts/` 文件里。

每条断言都带置信层级：`proven`（已证明，SQL 直接写着）、`implied`（可推得，由结构证明的推论）、`hypothesis`（作者假设，未被证明）、`conflict`（矛盾，跨任务证据打架）、`confirmed`（已确认，只来自人工回写的 `ontology.overrides.json`）。

另有 8 个临时概念未画，逐个见下面的「临时概念」表。

```mermaid
flowchart LR
    concept_channel["渠道（实体）"]:::entity
    classDef entity fill:#e8f0fe,stroke:#3367d6,color:#102a43
    classDef event fill:#fdf0e6,stroke:#c2660a,color:#43260f
    classDef summary fill:#eaf6ed,stroke:#2e7d46,color:#10331d
```

框里是概念名与它的种类，底色按种类分；边上的 `?` 表示这条基数只是作者假设、未被证明，括号里是实体在事件里的身份。同一个概念的两张表之间那条 JOIN 是 K1 折叠的接缝、不是业务关系，它在 `representation_links[]` 里，图上不画。

### 概念

| 概念 | 种类 | 表数 | 命名候选 | 疑似重复 |
| --- | --- | --- | --- | --- |
| [渠道](concepts/channel.md)（`hypothesis`） | 实体（`implied`） | 2（主表 1、引用 1） | 渠道 / channel | — |

### 关系

| 类型 | 从 | 到 | 角色 | 基数 | 层级 | 证据数 |
| --- | --- | --- | --- | --- | --- | --- |
| 关联（临时） | 渠道事件 | 渠道 | — | 多对一，作者假设 | `hypothesis` | 1 |
| 关联（临时） | events_a | segment_dim | — | 一对多 | `implied` | 1 |
| 关联（临时） | events_a | events_b | — | 未知 | `implied` | 1 |
| 关联（临时） | events_b | segment_dim | — | 一对多 | `implied` | 1 |

## 概念

1 个概念各有一份自己的文件，在 `concepts/` 下——哪些表在表现它、它由什么组成、对它成立什么、它和谁有关系、还有什么要人来判，全在那一份里。上面「概念」表里的名字就链到它。

### 临时概念（每表一个，待归并）

8 个临时概念：每一个都是一张语料没能归到任何业务键上的表，暂时自成一个概念（`tier: "provisional"`）。评审这一轮的**第一步**就是把它们归并掉：在 `concepts.overrides.json` 里按回写键写一条 `merge_into`，或者用 `new_concepts` 把几张一起收成一个新概念；确实自成一件事的，改名并确认。

完整清单见 [`appendix.md`](appendix.md) 的「临时概念（每表一个，待归并）」；用 `ontology --review-batches <目录>` 把它们切成一批批能做完的评审。

下面是影响最大的 8 个（按它带的概念关系数、任务数排序，与评审批次同一个顺序）：

| 概念 | 种类 | 表 | 影响 | 回写 |
| --- | --- | --- | --- | --- |
| segment_dim（`stem_only`） | 实体 | `dim.segment_dim` | 2 关系 / 2 任务 | `concept:table:dim_segment_dim` 的 `merge_into` |
| events_a（`stem_only`） | 实体 | `ods.events_a` | 2 关系 / 2 任务 | `concept:table:ods_events_a` 的 `merge_into` |
| events_b（`stem_only`） | 实体 | `ods.events_b` | 2 关系 / 2 任务 | `concept:table:ods_events_b` 的 `merge_into` |
| 渠道事件（`hypothesis`） | 实体 | `ods.channel_event` | 1 关系 / 2 任务 | `concept:table:ods_channel_event` 的 `merge_into` |
| channel_summary（`stem_only`） | 实体 | `mart.channel_summary` | 0 关系 / 0 任务 | `concept:table:mart_channel_summary` 的 `merge_into` |
| metric_by_segment（`stem_only`） | 实体 | `mart.metric_by_segment` | 0 关系 / 0 任务 | `concept:table:mart_metric_by_segment` 的 `merge_into` |
| user_names（`stem_only`） | 实体 | `mart.user_names` | 0 关系 / 0 任务 | `concept:table:mart_user_names` 的 `merge_into` |
| users（`stem_only`） | 实体 | `ods.users` | 0 关系 / 0 任务 | `concept:table:ods_users` 的 `merge_into` |

## 附录索引

表一级的事实全部在 [`appendix.md`](appendix.md) 里，每节一行：

- **表** 9 张 — [`appendix.md`](appendix.md) 的「表」；每张表一份卡片在 [`tables/`](tables/)。
- **表级关系** 4 条 — [`appendix.md`](appendix.md) 的「表级关系」与「表级关系（证据）」，每条都标明折进了哪条概念关系。
- **约束** 6 条 — [`appendix.md`](appendix.md) 的「约束」；按概念读的话，每条也在它所属概念的文件里。
- **表族** 9 族 — [`appendix.md`](appendix.md) 的「表族」。
- **临时概念（每表一个，待归并）** 8 个 — [`appendix.md`](appendix.md) 的「临时概念（每表一个，待归并）」；影响最大的前 20 个已经印在上面。
- **退役键词根** 0 个 — [`appendix.md`](appendix.md) 的「退役键词根」。
- **矛盾发现** 0 条 / 0 组 — [`appendix.md`](appendix.md) 的「矛盾发现」。
- **待人工判定清单** 2 条 / 2 组 — [`appendix.md`](appendix.md) 的「待人工判定清单」。影响最大的 2 组：`open:group:rel:dim.channel=channel_code`（1 条，影响 3）、`open:group:key:dim.channel=channel_code`（1 条，影响 1）。
