# Task Lineage 2.0：任务级表状态与行集合血缘

schema_version 2.0 是显式 opt-in 的任务级契约。它保留脚本中的语句顺序，在同一对
lineage.json / diagnostics.json 中描述字段值来源、行是否存在的依赖以及最终表状态。
默认 1.0 仍然为每条 INSERT、INSERT OVERWRITE、CTAS 或 MERGE 分别生成产物。

## 使用

~~~bash
scope-lineage parse \
  --task-file task.json \
  --contract-version 2.0 \
  --schema rich-table-metadata \
  --schema-fallback schema_info.csv \
  --target-ddl-metadata rich-table-metadata \
  --quality-policy strict \
  --compact-json \
  --out ./output
~~~

Python API：

~~~python
from scope_lineage import parse_task_lineage, write_task_lineage

result = parse_task_lineage(sql, task_name="daily_publish", schema=schema)
write_task_lineage(result, "./output/daily_publish")
~~~

## 顶层结构

| 字段 | 含义 |
| --- | --- |
| artifact_kind | 固定为 task_lineage。 |
| analysis_status | complete 或 partial，与语法/构图的 parse_status 分开。 |
| statement_sequence[] | 按脚本顺序排列的全部可识别语句。 |
| table_state_graph | 表在各语句执行前后的逻辑状态节点和转换边。 |
| final_table_states | 每张被修改表在脚本结束时对应的状态。 |
| statement_lineage | INSERT/CTAS/MERGE 复用 Core v1 scope 事实形成的语句级证据。 |
| end_to_end_lineage | 面向最终状态，分别保存值来源和行存在性来源。 |

每条语句都有稳定的 statement_id、零基 statement_index、stmt_kind、category 和
model_status。SET/空分号会保留在序列中但标为 ignored，不会被误算成数据变更失败。

## 两种不能混淆的血缘

- value_sources[]：字段值本身来自哪里；
- row_membership_sources[]：哪些字段决定该目标行是否存在；
- value_condition_sources[]：哪些条件决定 UPDATE/MERGE 分支是否改变字段值。

DELETE 不会把 WHERE 字段伪装成目标字段值来源。未删除行的字段值从目标表前一状态透传，
而谓词字段进入 row_membership_sources，影响所有目标字段所在行的存在性。
MERGE 的 ON 和 WHEN 条件同样进入行成员/值条件来源；真正的 UPDATE/INSERT 表达式才进入
value_sources。

## 状态转换语义

| 语句 | rowset operation | 字段值语义 |
| --- | --- | --- |
| INSERT INTO | APPEND | 旧状态值与新增投影值并存。 |
| INSERT OVERWRITE | REPLACE | 全表覆盖时新状态值来自本次投影。 |
| INSERT OVERWRITE PARTITION | REPLACE_PARTITION | 被覆盖分区来自本次投影，未受影响分区保留旧状态来源。 |
| CTAS | REPLACE | 创建没有旧目标分支的新状态。 |
| DELETE | DELETE_MATCHED_ROWS | 未删除行 PASSTHROUGH_SURVIVING_ROWS；无 WHERE 时为 DELETE_ALL_ROWS。 |
| TRUNCATE | RESET_ALL_ROWS | 行集合已知为空，字段集合保留，但字段 value_sources 为空。 |
| TRUNCATE PARTITION | RESET_PARTITION | 未受影响分区及其既有字段来源保留。 |
| UPDATE | PRESERVE_ROWS | 被赋值字段是条件更新，其他字段透传。 |
| MERGE | MERGE | 旧状态与已解析的 update/delete/insert 分支共同形成新状态。 |

例如 TRUNCATE; INSERT 会形成两个中间状态：TRUNCATE 后状态 known_empty=true，后续 INSERT
生成新的最终状态。因此消费者不能仅因脚本出现 TRUNCATE 就断言任务结束时表为空。

空状态也不是“无血缘”。全表 DELETE/TRUNCATE 后仍有目标表状态和字段条目；此时空的
value_sources 表示没有存活字段值，known_empty 和状态转换边则解释行集合为何为空。

## 元数据与事实缺口

缺少 DELETE/UPDATE 目标 schema 时，工具仍输出表级状态转换，但不会猜测全部字段，会记录
schema_missing_for_state_passthrough fact gap 并令 analysis_status=partial。
投影中的 `*` 无法根据 schema 展开时会保留通配来源，同时记录
projection_wildcard_unexpanded，并将对应最终字段的 trace_complete 设为 false。

diagnostics.json.metadata_coverage 记录引用表、已覆盖表、缺失表、schema 来源数以及元数据冲突。
--schema-fallback 只补 --schema 中缺失的表；同表定义不一致时保留权威来源并报告冲突。

## 质量门禁

--quality-policy permissive|balanced|strict 控制 CLI 退出码，不改变产物中的事实。

- permissive：保持 v1 的解析失败口径；
- balanced：未建模的数据变更也返回非零；
- strict：另外拒绝语法恢复、root-impact fact gap 和目标绑定 fallback。

也可以分别使用 --fail-on-root-gap、--fail-on-unsupported-mutation 和
--fail-on-binding-fallback。--allow-partial 不会覆盖显式质量门禁。

## 兼容与消费

1. v1 和 v2 必须输出到不同目录；
2. 消费者先检查 schema_version，未知 major version 必须拒绝；
3. v2 以整个任务为一个产物，不能再假设一个目录只代表一条写表语句；
4. --compact-json 只删除格式化空白，不改变 JSON 语义；
5. 每次运行仍然只写 lineage.json 和 diagnostics.json。
