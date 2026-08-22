# mapping.md 字段映射文档（mapping-md/1）

`scope-lineage render` 把一条写语句的 `lineage.json`（以及同目录的 `diagnostics.json`）
渲染成一份对人和机器都可读的字段映射文档 `mapping.md`。

## 定位：派生视图，不是契约

- mapping.md 是版本化契约的**派生视图**：其中每一条事实都来自 `lineage.json` /
  `diagnostics.json`，文档本身不携带契约之外的"孤儿事实"。
- **事实本体永远在 `lineage.json`**。长期的机器集成应当直接消费 JSON 契约；
  mapping.md 面向阅读、检索切块（RAG chunk）和轻量解析。
- 稳定性分级：
  1. 文档中引用的契约 ID（`mapping_chain_id`、`chain_id`、`logic_block_id`、
     scope_id）与 `lineage.json` 同级稳定，可作连接键 join 回 JSON；
  2. 行语法只保证在同一 `doc_format` 主版本内稳定（当前 `mapping-md/1`）；
     行语法变更会递增该版本号；
  3. 章节的措辞与排版可能在不递增版本号的情况下微调，机器不应依赖任何
     未在本文档"行语法"一节列出的文本形态。

## 用法

```bash
# 单条语句：mapping.md 写在 lineage.json 旁
scope-lineage render --lineage /path/to/task/lineage.json

# 语料目录：递归查找 lineage.json；--out 镜像输入目录结构
scope-lineage render --lineage /path/to/corpus --out /path/to/docs

# 只看某个字段的加工步骤；只输出部分章节；附加完全展开表达式
scope-lineage render --lineage lineage.json \
  --field paid_amount --sections overview,steps --expanded
```

Python API（消费契约文档 dict，与文件渲染同一条路径）：

```python
from scope_lineage import render_mapping_markdown

markdown = render_mapping_markdown(lineage_document, diagnostics_document)
```

- 仅支持 `schema_version: "1.0"` 的文档。目录模式遇到 2.0 文档会跳过并计数；
  单文件模式直接报错。
- 同目录没有 `diagnostics.json` 时照常渲染，但第 9 节会明确标注
  "无 diagnostics 文档"，而不是沉默。

## 文档结构与 lineage.json 字段对照

| 节 | `--sections` 名 | 内容 | 事实来源 |
| --- | --- | --- | --- |
| 1. 概览 | overview | 任务、目标表、语句类型、分区、解析状态、目标绑定摘要 | 顶层字段、`target_field_binding`；无绑定时按 `target_binding_absent_reason` 给出中文原因，仅 `target_table_not_found`（唯一有落错列风险的情形）标 ⚠ |
| 2. 来源表 | sources | 物理来源表与元数据完整性 | `source_tables`、`related_metadata.input_tables` |
| 3. 来源表关系 | relations | 物理表关系总览 + UNION 合并（scope 级连接明细在第 6 节） | `logic_blocks[].join_relation_detail`、`union_branch_alignment` |
| 4. 字段映射总表 | mapping | 每目标字段一行的端到端映射（"生成来源"列仅当有常量字段时出现） | `end_to_end_lineage[]` |
| 5. 加工步骤明细 | steps | 逐字段的逐步加工链 | `field_mapping_chains[].ordered_steps[]` |
| 6. 加工逻辑汇总 | logic | 每个 scope 做了什么：概要、过滤条件、该 scope 的连接明细 | `scope_profile.steps[]` + `logic_blocks[].join_relation_detail` |
| 7. scope 结构图 | graph | mermaid 数据流图 | `scope_graph` |
| 8. 任务依赖 | deps | 声明的上下游任务 | `task_dependencies` |
| 9. 不确定性与缺口 | gaps | 只保留影响血缘结论的信息：未完全追溯字段、事实缺口、警告条数指针 | `end_to_end_lineage[].trace_complete`、`diagnostics.json` |

章节编号固定（过滤 `--sections` 不会重新编号），便于引用。

## 行语法（mapping-md/1）

机器可读性由文档自身的稳定语法提供，不是第二份 JSON。

### front matter

文档头是一个**扁平**的 YAML front matter 块：每行 `key: value`，value 一律是
JSON 标量（可直接 `json.loads`）。不含时间戳、不含渲染器版本，保证同输入渲染
字节一致。键固定为：

```yaml
---
doc_format: "mapping-md/1"
schema_version: "1.0"
task_name: "..."
target_table: "..."
stmt_kind: "..."
---
```

`task_name` 的取值来自 `lineage.json` 顶层的 `task_id` 键——该契约键实际承载的是
基于任务名的语句标识（批量/多语句输入会派生 `_1` 等后缀），并非调度器的数字
task_id，因此文档按其真实含义标注为任务名。

### 步骤行

第 5 节中每个加工步骤一行，语法（Python 正则，与
`scope_lineage.render.mapping_markdown.STEP_LINE_PATTERN` 同源）：

```
^- 步骤 (?P<no>\d+)/(?P<total>\d+)：
  (?P<inputs>`[^`]*`(?:、`[^`]*`)*) → (?P<output>`[^`]*`)；
  (?P<step_type>[a-z_]+)(?:；粒度=(?P<grain>[a-z_]+))?；表达式：(?P<expression>.*)$
```

（实际为单行；此处换行仅为排版。）

- 每个输入/输出字段 id 各自包在单反引号 code span 里，用 `、` 连接；
  从 span 中提取字段 id 用 `FIELD_ID_SPAN_PATTERN`（`` `([^`]*)` ``）。
- `表达式：`标签后**贪婪取到行尾**，内容包在 code span 中（表达式含反引号时
  使用更长的反引号围栏，即标准 markdown 规则）。因此 SQL 字面量里出现
  `；`、`→`、`|` 都不会破坏语法。
- 渲染值中的真实换行一律归一化为字面量 `\n`，保证"一行一个事实"。
- `粒度=changed` 仅在该步聚合改变了行粒度时出现。
- 表达式优先取契约的 `display_expression`（FROM 别名已解析为真实表名），
  取不到时回落 `expression_sql` 原文。

### 证据行与关系行

- 每个字段小节以证据行收尾：
  `- 证据：mapping_chain_id=<id>；chain=<chain_id>`。
- 第 3 节回答"**物理表**之间怎么关联"：join 键穿透到物理字段后按（左表，右表）聚合，
  键列用短字段名（表名已在行首两列）；同一模式在多个 scope 重复出现时合并为一行并计
  "N 处"；CTE 之间、键穿透不出新信息的连接**不进该节**（中间结果的管道，明细在第 6
  节）；两张物理表间等值键未能拆分时保留 `⚠ 未拆分` 行。UNION 合并关系同在该节。
- scope 级连接明细挂在**第 6 节对应 scope 名下**，以
  `- <JOIN 类型> JOIN：\`左\` ⋈ \`右\`（@ <scope_id>；logic_block_id=<id>）` 开头；
  左右是 SQL 里实际连接的对象（物理表或 CTE/子查询 scope），不强行穿透——两个同源
  CTE 相连时穿透会退化成无意义的同表自等对。scope_profile 折叠掉的 union 分支，
  其连接明细回落到父 union scope 的小节（行内 `@ <scope_id>` 保留真实归属）；
  两者都不在时列入"其他连接"兜底小节，任何连接事实不会丢失。
- 等值键行首选 scope 级短形式（两侧同名列缩写为单个列名，异名用
  `别名.列 = 别名.列`）；物理穿透只在能提供新信息（两侧物理字段不同）时以
  `（物理：表.字段 = 表.字段）`附注。
- ON 原文仅在等值键**未能拆分**（自连接、`ON TRUE` 等，⚠ 标注）时保留；正常拆分时
  键与附加条件已完整覆盖 ON，原文可回 `lineage.json` 查看。
- 关系总览表格的单元格**不放任意表达式**；单元格内的 `|` 转义为 `\|`。

### warnings.md（warnings-md/1）

解析过程的**提示类警告不进 mapping.md**——它们描述解析过程，不改变已证明的事实，
混在映射文档里会淹没真正影响结论的信息。有警告的语句会在同目录额外生成
`warnings.md`：

- front matter：`doc_format: "warnings-md/1"`、`schema_version`、`task_id`、
  `target_table`；
- 按警告类型分组，每组标题 `## <type>（N 条）`，组内首行是该类型的一句中文说明
  （已知类型内置词表，未知类型只显示类型名），逐条为 `- @ <scope>：` + 原文
  code span；
- 没有任何警告时不生成该文件。

mapping.md 第 9 节保留一行计数指针（`- 解析警告：N 条（提示类信息，见同目录
warnings.md）`），并只保留影响血缘结论的内容：未完全追溯字段、`lineage_fact_gaps`。

### 不确定性记号

固定用 `⚠` 前缀标注，绝不把猜测渲染成事实：

- 第 4 节状态列：`⚠ trace_incomplete`；
- 第 5 节链级：`- ⚠ trace_status=<status>: <原因>`；
- 第 3 节自连接等场景：连接键列 `⚠ 未拆分`，明细中的条件用中性标签
  "连接条件（未拆分）"（此时等值键与过滤条件未区分，不应当作"非等值附加条件"）；
- 第 9 节：无 diagnostics 文档、追溯不完整字段清单。

### chunk 自包含

每个字段一个 `###` 小节，标题携带完整身份：

- 普通写入：`### 字段 <目标表>.<字段>`；
- MERGE 同名字段多分支：`### 字段 <目标表>.<字段>（merge:<分支> 分支 <序号>）`；
- 目录写入（`target_table` 为 `directory:` 前缀）：
  `### 字段 <字段>（写入目录 <路径>）`，不拼造伪表名。

按 `###` 切块后，任一小节单独检索仍能自我定位。

## 确定性

同一对输入文档渲染两次字节一致：字段按 `target_column_ordinal`（缺失时回退
`output_ordinal`）排序，关系按 `logic_block_id` 排序，图节点按名称排序。
该性质由 golden 基线测试（`tests/core/fixtures/lineage_contract/<case>/mapping.md`）
锁定。
