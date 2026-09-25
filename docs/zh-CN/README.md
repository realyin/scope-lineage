[English](../en/README.md) | 中文

# Scope Lineage 文档导航

Scope Lineage 把 Spark/Hive SQL 转换成两类机器可消费的事实：

- `lineage.json`：SQL 已经证明的结构、逻辑和字段来源；
- `diagnostics.json`：解析过程中发现的不确定性、降级和事实缺口。

如果你第一次接触项目，建议按下面顺序阅读：

1. [项目 README](../../README.zh-CN.md)：先了解工具解决什么问题、产物有什么价值；
2. [端到端工作流：从任务 JSON 到画像与本体](workflow.md)：先看清全流程——`parse` 之后 `glossary` / `tables` / `describe` / `ontology` 按什么顺序跑、每一步要上一步的什么、人和 Agent 在哪里介入、确认过的答案怎么写回来；不确定下一条命令敲什么时先读这篇；
3. [安装与使用指南](getting-started.md)：完成安装、第一次解析，并了解常用 CLI 和 Python API；
4. [Scope Lineage：把复杂 SQL 还原成可验证的字段加工链](value-and-use-cases.md)：通过完整案例了解加工血缘、可验证血缘和实际使用价值；
5. [输入格式](input-formats.md)：了解 SQL、任务 JSON、Schema 和目标表元数据怎么传入；
6. [读语句级还是任务级？按业务场景选层次](contract-selection.md)：字段血缘、加工步骤分析读内嵌的语句文档；审计、事故排查、最终表状态读任务级字段——先选对层次再读细节；
7. [`lineage.json` 输出契约](lineage-json.md)：逐层理解顶层字段、scope、逻辑块、字段映射链和端到端血缘；
8. [`diagnostics.json` 输出契约](diagnostics-json.md)：理解 warning、事实缺口以及什么结果不能当成已证明事实。
9. [Task Lineage 2.0](task-lineage-v2.md)：理解 DELETE/TRUNCATE/UPDATE、行集合影响和多语句最终表状态。
10. [mapping.md 字段映射文档](mapping-doc.md)：用 `scope-lineage render` 把契约渲染成对人和机器都可读的映射文档。
11. [semantic.json / semantic.md 任务语义描述](semantic-doc.md)：用 `scope-lineage describe` 把契约派生成确定性的任务语义骨架——输出表形态与粒度、加工链路、规则清单、字段语义，每条都带来源标签与证据 id；业务命名不在其中。
12. [tables.json / tables.md 语料级表卡](tables-doc.md)：用 `scope-lineage tables` 把一整份语料聚合成每张表一张卡——谁写它、一行代表什么、谁读它读了哪些列；`describe --tables` 让任务画像直接引用上游表卡。
13. [glossary.json / glossary.md 术语与值域字典](glossary-doc.md)：用 `scope-lineage glossary` 把一整份语料聚合成一本按列名组织的字典——注释跨表归并、常量取值观察、已被 SQL 证明封闭的枚举；含义只来自人工确认与注释字面命中，`describe --glossary` 把它接到 `fields[].value_domain`。
14. [ontology.json / ontology.md 语料级本体候选](ontology-doc.md)：用 `scope-lineage ontology` 在表卡与值词典之上把一整份语料整理成一份带置信分层的本体候选——业务概念与概念之间的关系，以及表现它们的表与底下的 JOIN 证据、身份键、约束、跨任务矛盾；索引开头是本体总览、随后每个概念一行链到它自己那份 `concepts/<文件>.md`（表一级的东西在 `appendix.md`），每张表卡追加身份 / 关系 / 约束 / 同义 / 待人工判定五节，人工确认经 `--overrides` 回写为第五级 `confirmed`；业务命名与类层次留给人或 Agent 确认。
15. [本体目录（`catalog-yaml/1`）与 `ontology-json/3`](ontology-catalog.md)：由人维护、概念先行的事实来源——业务域、标识符、实体、事件、角色、状态、关系、约束、术语，以及表与列到它们的映射；`scope-lineage catalog validate` 校验，`scope-lineage catalog build` 规范化成 `ontology-json/3`。上面的 `ontology` 命令再保留一个版本。
16. [AI agent 技能](agent-skill.md)：让 Claude Code、Codex 等 AI 编码 agent 直接用上血缘解析、字段加工链和 mapping 文档能力。

## 从问题找到字段

| 你要回答的问题 | 优先读取的位置 |
| --- | --- |
| 任务写入哪张表、使用什么写入方式？ | `target_table`、`stmt_kind`、`target_partition_*` |
| 任务读取了哪些物理表？ | `source_tables` |
| CTE、子查询和 UNION 如何连接？ | `scope_graph`、`scopes.<scope_id>.depends_on` |
| 某个查询块做了什么？ | `scopes.<scope_id>.logic_blocks[]`、`scope_profile.steps[]` |
| 某个输出字段的 SQL 表达式是什么？ | `scopes.ROOT.outputs[]` |
| 目标字段最终来自哪些物理字段？ | `end_to_end_lineage[]` |
| 字段经过了哪些查询块和变换步骤？ | `field_mapping_chains[].ordered_steps[]` |
| JOIN 的 key 和附加过滤是什么？ | `logic_blocks[].join_relation_detail` |
| 聚合的 group by、指标表达式是什么？ | `logic_blocks[].aggregation_detail` |
| 窗口函数如何分区、排序？ | `logic_blocks[].window_specification` |
| `SELECT *` 是否真正展开？ | `scopes.*.outputs[]`、`diagnostics.json.warnings[]` |
| 某条血缘是否完整可信？ | `trace_complete` / `trace_status`、`missing_reasons`、`ambiguities` |
| 为什么无法确定字段来源？ | `diagnostics.json.lineage_fact_gaps[]` |
| DELETE/TRUNCATE 如何影响最终表？ | v2 `statement_sequence[]`、`table_state_graph`、`final_table_states` |

## 事实层与上层知识的边界

Core 输出的是可追溯事实，不直接生成业务结论。例如：

- Core 可以证明 `paid_amount_30d` 使用 `SUM(CASE WHEN ...)`，来自 `dwd.order_detail.pay_amount`；
- 上层 Agent 可以基于该事实解释“近 30 天已支付金额”；
- Core 不会仅凭字段名猜测这是收入、风险或客户价值指标。

这种边界让 AI 的回答可以回到 SQL 表达式、scope、字段和诊断证据，而不是依赖一次不可复核的自然语言猜测。
