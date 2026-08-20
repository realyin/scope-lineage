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

产出会话级关系的语句额外带 `is_session_scoped_relation: true`——`TEMP VIEW`、`GLOBAL TEMP VIEW`、
`CACHE [LAZY] TABLE` 建出的关系只存活于会话。`final_table_states` 会为脚本产出的**每个**关系建条目，
包括这些；按 catalog 对账前必须先用该字段排除，否则会认为仓库里新增了并不存在的表。
字段血缘本身不受影响：`mart.t.v ← tmp_v.v` 与 `tmp_v.v ← ods.real.v` 两跳仍各自作为事实保留，
是否折叠成一跳由消费方决定。
脚本里只要出现这类关系，`diagnostics.warnings[]` 会有一条 `session_scoped_relations_present` 列出全部关系名——标记在 `statement_sequence[]` 上、误导人的条目却在 `final_table_states` 里，不交叉比对就会漏掉，所以另发一条整脚本级别的提醒。

## 两种不能混淆的血缘

- value_sources[]：字段值本身来自哪里；
- row_membership_sources[]：哪些字段决定该目标行是否存在；
- value_condition_sources[]：哪些条件决定 UPDATE/MERGE 分支是否改变字段值。

DELETE 不会把 WHERE 字段伪装成目标字段值来源。未删除行的字段值从目标表前一状态透传，
而谓词字段进入 row_membership_sources，影响所有目标字段所在行的存在性。
MERGE 的 ON 和 WHEN 条件同样进入行成员/值条件来源；真正的 UPDATE/INSERT 表达式才进入
value_sources。

row_membership_sources[].table 始终是物理表，不是查询块。MERGE 条件里的目标别名解析为目标表，
USING 别名则沿已解析的 USING scope 一路追踪到物理根字段：USING 是 CTE 或子查询时记录其背后的
物理表而不是 CTE 名，USING 是 UNION 时保留每个分支的物理根字段。追踪无法完成时不补位任何名字，
改为记录 merge_condition_source_unresolved fact gap（见下一节）。

## value_sources[].source_kind：三种来源，以及怎么折叠前态边

每条 `value_sources[]` 都带 `source_kind`，取值只有三种：

| source_kind | 含义 | 典型场景 |
| --- | --- | --- |
| `physical_field` | 值来自某张物理表的某一列 | 绝大多数血缘 |
| `generated` | 值由常量或不引用任何输入列的表达式产生 | `'rcs' AS send_type` |
| `prior_table_state` | 值从**目标表自身的前一个状态**透传而来 | `INSERT OVERWRITE ... PARTITION` 未被覆盖的分区、`UPDATE` 未赋值的字段、`DELETE` 后存活行 |

### 前态边为什么存在，以及什么时候该折叠

`prior_table_state` 记录的是"这个字段的值这次没被改写，沿用上一状态"。它对**追溯最终物理来源**没有增量价值，
但对**解释一次写入到底改了什么**是必要的——所以 Core 如实记录，由消费方按用途取舍。

它的量不小：实测中它可占单个任务 `value_sources` 边的 40%–50%。只关心"字段最终来自哪些物理表"的消费方
（例如与只输出物理源的平台做对比）应当折叠掉它们：

```python
physical_only = [
    source
    for source in item["value_sources"]
    if source["source_kind"] != "prior_table_state"
]
```

### 不要用"表名相等"来过滤

一个看起来等价的写法是筛掉 `source_table == target_table` 的行。**这个口径是错的。**

实测 10 个任务：`prior_table_state` 边共 4508 条，其中指向**别的**表的有 **0** 条——所以按 `source_kind`
过滤精确、无误伤。但反过来，同表却**不是**前态边的行确实存在（实测 2 条）：那是任务把自己的表当作真实输入读取
（`INSERT INTO t SELECT ... FROM t`），是**真实血缘**。按表名相等过滤会把它一并删掉。

**判据是来源的种类，不是表名是否相同。**

## value_sources[].transform：`WINDOW` 的来源不都是值来源

`source_kind` 回答"值来自哪一类地方"，`transform` 回答"经过了什么变换"。两者要一起读——
只按 `source_kind == "physical_field"` 统计，会把窗口的**分组上下文**也算成值依赖。

一个窗口字段的来源里混着三种角色，但 `transform` 一律是 `WINDOW`：

| 角色 | `SUM(amt) OVER (PARTITION BY id ORDER BY dt)` 中 | 是否决定数值 |
| --- | --- | --- |
| 值参数 | `amt` | 是 |
| 分区键 | `id` | 否，只决定分到哪一组 |
| 排序键 | `dt` | 否，只决定组内次序 |

三列都会以 `physical_field` + `transform: "WINDOW"` 出现。

### 为什么这里最容易误判

`end_to_end_lineage` 是**压平**视图：它把整条 scope 链一路展开到物理叶子，
只保留 `{table, column, transform}`，**不保留是哪一跳、也不带回指**。
于是一个按 15 列分区的窗口，会让这 15 列全部出现在某个下游字段的 `value_sources` 里，
看上去像"来源被铺成整张表"。

在 `lineage.json` 的 scope 视图里则不会有这个错觉——那里每一跳通常只有一两个直接来源，
上下文列只挂在定义窗口的那一列上。

### 怎么只取值来源

角色信息在 `lineage.json` 一侧：`scopes[].columns[].window` 给出 `partition_by[]` 与
`order_by[]`，且只有 `transform` 为 `WINDOW` 的那一列才有。做法是沿 `sources[]` 往上走到
带 `window` 的那一列，把它的 `partition_by` / `order_by` 从来源里剔除。

`row_number()`、`rank()` 这类窗口没有值参数，剔除后为空是正确结果：它们的值完全由分区与排序决定。
这类字段真正的值来源在窗口之外的表达式里，会以 `DIRECT` / `EXPRESSION` 而不是 `WINDOW` 出现。

**判断某列是不是值来源，看它的 `transform`，以及它是否出现在对应窗口的 `partition_by` / `order_by` 里——
不要只数 `value_sources` 的条数。**

## value_sources[] 是"参与路径"的列表，不是"依赖列"的集合

同一个物理列可以在一个字段的 `value_sources` 里出现**多次**，每次带不同的 `transform`。
去重键是 `(table, column, transform)`，`transform` 是刻意计入的：每条记录的是一种**参与方式**，
不是同一事实记了多遍。

一个真实的拉链表派生列：

```
etl_begin_date: 条目 17 → 按 (table, column) 去重后 16 列
etl_end_date:   条目 33 → 按 (table, column) 去重后 16 列（与上面是同一批列）
```

`etl_end_date` 的 33 条不是膨胀：同一批 16 列经**两条路径**到达——一条经窗口派生的列
（`transform=WINDOW`），一条经读取该窗口输出的聚合（`transform=AGGREGATE`），
再加 1 条真正的取值路径（`transform=CONDITIONAL`）。

要"这个字段依赖哪些物理列"，按 `(table, column)` 去重：

```python
columns = {
    (source["table"], source["column"])
    for source in item["value_sources"]
    if source["source_kind"] == "physical_field"
}
```

要"值是从哪来的"，那是另一个问题——见上一节，不能只按 `transform` 白名单过滤。

### 一条会清空血缘的过滤写法

有人会想"只保留 `DIRECT`/`EXPRESSION`/`CONDITIONAL` 就是取值来源"。**这条规则是错的**：

| 字段写法 | 真实物理来源 | 按该规则过滤后 |
| --- | --- | --- |
| `SUM(amt)` | `amt` | **空** |
| `COUNT(DISTINCT amt)` | `amt` | **空** |
| `SUM(amt) OVER (PARTITION BY id ORDER BY dt)` | `amt`、`id`、`dt` | **空** |

聚合与窗口指标的**值参数本身**就带 `AGGREGATE` / `WINDOW`，滤掉它们等于滤掉真正的来源。
数仓里绝大多数指标列都是这个形态。这条规则在 `row_number()` 这类**没有值参数**的窗口上
看起来有效，那是巧合，不能推广。

## value_sources[].source_state：这一跳读的是哪个状态

一张表在一个脚本里可以有多个状态（被写两次、或临时关系被 `CREATE OR REPLACE` 重定义）。
来源只写表名时，这些读取彼此无法区分。

来源表在本脚本中被写过时，该来源额外带 `source_state`，值是 `table_state_graph.nodes[].state_id`：

```json
{"source_kind": "physical_field", "table": "v", "column": "id",
 "transform": "DIRECT", "source_state": "state:v:001"}
```

从没被本脚本写过的表不带这个字段——它就是脚本开始前的那个状态，没有第二个候选可混淆。

`CREATE GLOBAL TEMPORARY VIEW gv` 产出的关系记为 **`global_temp.gv`**，不是 `gv`——Spark 把这类视图
放在 `global_temp` 库里，声明时的裸名并不可解析，读它的语句必然写成 `global_temp.gv`。
按产出名与读取名对齐，这一跳才能被识别为会话级关系；否则它看起来就是一张普通物理表。

### 边上直接带标记

读会话级关系的那条边，自己带 `session_scoped: true`：

```json
{"source_kind": "physical_field", "table": "tmp_v", "column": "amt",
 "transform": "DIRECT", "source_state": "state:tmp_v:001", "session_scoped": true}
```

**不必回 `statement_sequence` 做关联**。只取落盘来源就是一次过滤：

```python
[s for s in item["value_sources"]
 if s.get("source_kind") == "physical_field" and not s.get("session_scoped")]
```

这**不是 `source_kind` 的取值**——`source_kind` 保持原义，按 `source_kind == "physical_field"`
过滤的既有代码行为完全不变，只是仍会包含这些边。

标记由工具在解析时按它实际解析到的关系判定，所以**拼写不一致也不会漏**：
全局临时视图声明时是裸名、读的时候是 `global_temp.` 限定名，按名字比对会漏，边上的标记不会。

### 只想排除、不想折叠

按 catalog 对账时通常只需要把这些关系从表清单里去掉，不需要动字段血缘：

```bash
jq -r '
  ([.statement_sequence[] | select(.is_session_scoped_relation==true) | .target_table]) as $scoped
  | .final_table_states | keys | map(select(. as $t | $scoped | index($t) | not))
' lineage.json
```

`["mart.daily", "tmp_v"]` → `["mart.daily"]`。

**但不要把这个当成字段血缘的过滤方式。** 只删掉会话级来源、不做替换，会让那些列不再指向任何
上游表——它们的上游只有这一条路。要字段血缘干净，用 `fold_session_scoped`。

### 两个反模式

**不要按名字或后缀判断。** 形如 `tmp_*`、`*_20260101` 的**真实表**是存在的，按名字过滤会误杀；
反过来，临时视图也常常不带任何可识别前缀。全局临时视图更是声明时用裸名、读的时候用
`global_temp.` 限定名，按名字比对必漏。判据只有 `session_scoped` / `is_session_scoped_relation`。

**不要用「来源计数变了没有」判断工具是否处理了这件事。** 标记是加法、不删边，所以默认产物的
来源计数**本来就不会变**。要验证的是折叠之后：`value_sources_folded` 是否为 `true`，以及
折叠后每个落盘列是否仍有来源。

### 想要「干净」的产物：用 fold_session_scoped

不必自己写折叠。Core 导出了一份实现：

```python
from scope_lineage import fold_session_scoped

folded = fold_session_scoped(document)     # 输入不会被修改
```

它把 `最终表.v ← 临时视图.v ← 真实表.v` 解析成 `最终表.v ← 真实表.v`，
并把那些临时关系自己的行、以及它们在 `final_table_states` 里的条目一并去掉。

**折不动的地方不会被悄悄丢掉。** 该行保留原边，并给出：

| 字段 | 含义 |
| --- | --- |
| `value_sources_folded` | `true` = 这一行全部折叠成功；`false` = 有折不动的跳 |
| `fold_incomplete_reasons` | 折不动的原因，仅在 `false` 时出现 |

原因有四种，都对应一个真实存在的情况：

- `source_state_not_in_document` —— 读的是该关系被重定义**之前**的状态。
  `end_to_end_lineage` 是最终状态视图，那个状态没有行；用现存的定义替换会**指错出处**。
- `source_column_not_in_document` —— 该关系自身的列没解析出来（通常是未展开的 `SELECT *`，
  只有一行 `*`）。
- `source_column_has_no_sources` —— 该列在文档里没有任何来源。
- `fold_depth_exceeded` —— 关系间构成环。

**折叠后来源为空 ≠ 这列没有血缘**，所以这个实现从不返回空——折不动就保留原边并说明。
自己写折叠最容易错的也正是这一点。

### 已知边界：解析不了的建表语法

`CREATE TEMPORARY VIEW tv (...) USING csv OPTIONS (...)` 这类**不带 `AS SELECT`** 的写法，
解析器无法结构化，语句退化为 `stmt_kind: COMMAND` / `model_status: unsupported`，
因此**不会**被标为会话级关系。

工具不对它做猜测：判据只取自 AST 事实，而这里没有可用的 AST。从未解析的文本里正则出关系名，
与按 `tmp_` 前缀猜表是同一类做法，本工具不采用。

实际影响有限，但要知道边界在哪：

- **不会**登记幽灵表——`final_table_states` 里不会出现 `tv`；
- 脚本会被标 `analysis_status: partial`，阻塞原因含 `unsupported_data_change`，
  并伴随 `unsupported_statement` 与 `metadata_incomplete` 两条 warning；
- **但**读了 `tv` 的字段其 `trace_complete` 仍为 `true`——那一跳的来源是工具没能建模的关系。
  **含 `unsupported` 语句的脚本，其逐行 `trace_complete` 不应单独采信**，要先看
  `analysis_status`。

### 折叠前必须检查它

`end_to_end_lineage` 是**最终状态视图**（每张表在脚本结束时的状态），所以**中间状态的行不在文档里**。
折叠某一跳之前，先确认 `source_state` 能在 `end_to_end_lineage[].target_state` 里找到：

```python
available = {item["target_state"] for item in doc["end_to_end_lineage"]}
foldable = source.get("source_state") in available   # 无 source_state 的来源无需折叠
```

**找不到就保留原边，不要替换。** 找不到意味着这次读到的是一个中间状态，而文档里那张表的行
描述的是另一个状态——按表名替换会得到「最后一个定义」，那是一个关于该列出处的错误论断。

例：

```sql
create or replace temp view v as select id from ods.a;
insert overwrite table mart.x select id from v;      -- 读 state:v:001
create or replace temp view v as select id from ods.b;
insert overwrite table mart.y select id from v;      -- 读 state:v:002
```

`mart.x.id` 的来源是 `state:v:001`，而文档里 `v` 只有 `state:v:002` 那一行。按名字折叠会得出
`mart.x.id ← ods.b.id`——它其实来自 `ods.a`。带上 `source_state` 后，这种情况**可以被发现**，
消费方知道这一跳在本文档里折不了。

工具在这里给的是「读到的是哪个状态」这个事实，不承诺每个状态都能在文档里取到。

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

不完整会**跨脚本内的一跳传播**。读一个自身列未解析的脚本内关系（例如它由未展开的
`SELECT *` 建成，只有一行 `*`），读到的字段会记录 source_state_columns_unknown，
`trace_complete` 为 false。此前这类字段声称 `trace_complete: true`——它建立在一个没人能描述的
关系上；同时消费方去折叠这一跳时找不到该列的行，得到空结果、读起来像「这列没有血缘」，
而旁边那个 `true` 不会与之矛盾。缺口同名记入 `lineage_fact_gaps`，`needed_fact` 列出是哪些状态。

目标表**前态**的不完整本来就会传播；这一条是同一个问题问在另一条边上：被**读**的关系。

MERGE 条件字段无法追踪到物理根字段时记录 merge_condition_source_unresolved，字段为
statement_id、source_alias、column、root_impact=true 和 needed_fact。触发场景包括条件引用了
USING 关系并未输出的列，以及条件使用了既非目标别名也非 USING 别名的限定符。该缺口
root_impact=true，因此会令 analysis_status=partial 并使 strict 门禁返回非零。

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
