[English](../en/contract-selection.md) | 中文

# 读语句级还是任务级？按业务场景选层次

自 0.2.0 起工具只产出一份产物：任务文档（schema_version 2.0，见
[Task Lineage 2.0](task-lineage-v2.md)）。原 1.0 的"语句文档"没有消失——它作为
`statement_lineage.<statement_id>` 的条目**完整内嵌**在任务文档里，形状仍由
[`lineage.json` 输出契约](lineage-json.md) 描述。本文不讲字段细节，只回答一个问题：
**你的场景该读哪一层。**

## 一句话判据

> **你的问题是"数据从哪来"，读语句文档；你的问题是"任务干了什么"，读任务级字段。**

再具体一点：如果你发现自己在问带时间顺序的问题——"它是**先**清空**再**插入的吗？"
"**跑完之后**昨天的数据还在吗？"——那就是任务级的问题。语句文档是给每条写入语句拍的
照片，照片回答不了"先后"；任务级字段是整个任务的录像。

## 场景对照表

| 你要做的事 | 读哪层 | 一句话原因 |
| --- | --- | --- |
| **字段血缘分析**（这个字段来自上游哪些表哪些列） | **语句文档** | 答案就在 `end_to_end_lineage[].physical_sources` 里，拿来就能用 |
| **字段加工步骤分析**（这个指标是怎么一步步算出来的） | **语句文档** | 加工链（`field_mapping_chains`）、表达式、JOIN/过滤逻辑都在语句文档的证据层，还能渲染成给人看的 `mapping.md` |
| **表级依赖 / 影响分析**（改了上游表，影响谁） | **语句文档** | `source_tables` / `target_table` 直接可读 |
| **给数据地图 / 数据资产平台建血缘图** | **语句文档** | 平台按"目标表"组织资产，每个条目一个 `target_table`，粒度正好对上 |
| **审计一个任务改了什么数据**（删了什么、清空了什么、更新了什么） | **任务级** | 语句文档不建模 DELETE / UPDATE / TRUNCATE，只把它们记在 `skipped_statements` 里 |
| **判断任务跑完后表是什么样**（空了？整表覆盖？只覆盖昨天分区？） | **任务级** | 这是"最终状态"问题，只有任务级的 `final_table_states` / `table_state_graph` 记录状态 |
| **排查数据丢失事故**（"表怎么空了 / 数据怎么少了"） | **任务级** | 要还原语句执行顺序和每一步对表的影响 |
| **数据质量归因**（这行数据为什么消失 / 为什么没更新） | **任务级** | "行还在不在"由 DELETE / MERGE 条件决定，只有任务级的 `row_membership_sources` 区分这个 |
| **合规 / 安全审查**（敏感字段流到哪里，包括中间被删被改的路径） | **任务级** | 需要完整的任务级事实，不能漏掉语句文档未建模的语句 |
| **CI 质量门禁** | 不用选 | `--quality-policy` / `--fail-on-*` 作用于整次任务解析，两层的事实都计入 |

## 两个典型场景的展开

**字段血缘分析 → 语句文档。** 你想知道 `mart.customer_summary.order_count` 来自哪——
打开写它的那个 `statement_lineage` 条目，`end_to_end_lineage` 里直接写着"来自
`dwd.order_detail.order_id`，经过聚合"。完事。用任务级 `end_to_end_lineage` 也能查到
同样的答案，但你必须先做对几件事：剔除"来自表自己上一状态"的 `prior_table_state` 边、
用 `fold_session_scoped` 折叠临时视图、检查 `source_state`——一步做错，结论就是错的。
**能用语句文档答的问题，别用任务级自找麻烦。**

**字段加工步骤分析 → 语句文档。** 你想向业务方解释"这个指标是先按客户分组、再算 30 天
支付金额、最后取排名第一的记录"——语句文档的 `field_mapping_chains[].ordered_steps[]`
按步骤记录每一层做了什么，每步带原始 SQL 表达式，`scope-lineage render` 还能输出人可读
的 `mapping.md`。这正是语句文档设计出来干的事。

## 两层之间怎么对号

任务级与语句级指同一条语句时，用 **`statement_id`**（形如 `stmt:002`）对上号——
`statement_sequence[]` 与 `statement_lineage` 的键就是它；**不要用 `task_id`**，条目内的
`task_id` 带另一套后缀口径，同名会静默指向不同的语句（详见
[lineage-json.md](lineage-json.md) 顶层字段表与 [task-lineage-v2.md](task-lineage-v2.md)
的"兼容与消费"）。

## 给新消费方的建议

语句级证据一样不少地嵌在每个 `statement_lineage` 条目里，所以消费程序只需要读这一份
产物：血缘、字段解释读条目，审计、状态判断读任务级字段。读任务级 `end_to_end_lineage`
时按 [task-lineage-v2.md](task-lineage-v2.md) 正确处理前态边折叠、会话级关系、窗口上下
文列这几个已知易错点——那份文档一半以上的篇幅就在讲怎么别读错。曾经独立输出的 v1 产物
已在 0.2.0 移除；迁移方法见项目 README 的"从已移除的契约 1.0 迁移"。
