[English](../en/table-semantics.md) | 中文

# 表语义（`table-semantics/1`）：材料包、校验、确认

表语义针对一张目标表，用业务读者的话回答：这张表是什么、一行是什么、怎么更新、怎么取一天和一段时间、
收哪些记录、数据从哪来给谁用、每个字段什么意思怎么算、字段有哪些码值、要注意什么。

文档由模型写、由机器对照事实校验。Core 只做前后两段确定性的工作，从不调用模型：

- `scope-lineage semantic packet` 把写一张表所需的全部事实收成一份**材料包**——表的元数据、每个生产任务
  及其 SQL、输入表、语义画像已经推出的血缘事实；
- `scope-lineage semantic validate` 用 JSON Schema 和材料包（九项交叉校验）检查写好的
  `table-semantics/1` 文档，逐条列出要重写的地方；
- `scope-lineage semantic confirm` 把人的回答写回文档。

写文档（提示词、重写循环）属于 Agent 技能。把文档渲染成页面（`semantic render`）是下一步，不在这一版里。

[`examples/table-semantics/`](../../examples/table-semantics/) 里有一份为演示表手写的示例文档和一份
配套的确认文件；两者和它们描述的演示语料一样，都是虚构的。

## 位置

| 步骤 | 谁来做 | 命令 | 产出 |
| --- | --- | --- | --- |
| 1. 材料包 | 机器 | `semantic packet` | `<out>/<db.table>/packet.md` 与 `packet.json` |
| 2. 写作 | 模型，经 Agent 技能 | — | 每表一份 `table-semantics/1` JSON |
| 3. 校验 | 机器 | `semantic validate` | 文字摘要，或 `--json` 报告（其中的失败清单就是重写提示） |
| 4. 渲染 | 机器 | `semantic render`（下一步） | 每表一页 |
| 5. 确认 | 人回答，机器套用 | `semantic confirm` | 带 `confirmed` 标记的文档 |

## 五分钟跑通演示

所有输入都是仓库自带的虚构样例：

```bash
scope-lineage parse --input-dir examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/lineage
scope-lineage semantic packet --lineage out/lineage \
  --tasks examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/packets
scope-lineage semantic validate examples/table-semantics --packets out/packets
scope-lineage semantic confirm examples/table-semantics \
  --confirmations examples/table-semantics/confirmations.json --out out/confirmed
```

`validate` 每份文档打印一行（`demo_dwd.dwd_party_customer_info_df: 52/52 checks passed
(100.0%)`），最后是合计。示例的 `packet_digest` 对应当前安装的 SQLGlot 渲染出的材料包；换一个 SQLGlot
版本，摘要检查可能把示例报为过期，其余检查照样通过。

## `semantic packet`

### 输入

| 选项 | 必填 | 含义 |
| --- | --- | --- |
| `--lineage` | 是 | 一个 `lineage.json` 或一棵目录——与 `describe` 同一套遍历，连同每份文档旁的 `diagnostics.json` |
| `--tasks` | 是 | 解析血缘所用的任务 JSON 目录；用 `parse` 自己的任务读取器读，取每个任务的 SQL |
| `--schema` / `--schema-fallback` | 否 | 元数据，与 `parse` 同一套参数和加载器；不给时列和注释取自血缘 |
| `--tables` | 否 | `scope-lineage tables` 写出的 `tables.json`；不给时先从 `--lineage` 建表卡 |
| `--only` | 否 | 一张或多张目标表（`db.table`，忽略目录前缀）；名字不存在时退出码 1 |
| `--out` | 是 | 输出目录：每张目标表一个 `<db.table>/` |

语料里每张被任务最终写入的表都会生成材料包（会话视图和临时表不算目标表）。`--tasks` 里找不到任务 JSON 的
任务照样打包、只是没有 SQL；摘要行以 `tasks_without_sql` 计数。

### 材料包里有什么

`packet.json`（`table-semantics-packet/1`）与 `packet.md` 装的是同一批事实；校验读 JSON，模型读 markdown。

| `packet.md` 小节 | `packet.json` 键 | 内容 |
| --- | --- | --- |
| 1. 目标表 | `target` | 表注释、层、域、元数据来源（`schema` / `lineage` / `fields`），按表内顺序的每一列及其类型、注释、是否分区列 |
| 2. 生产任务 | `tasks[]` | 每个生产任务：编号、调度、周期、描述、登记的上下游任务、脚本头注释、写本表的语句，以及 SQL |
| 3. 输入表 | `inputs[]` | 每张输入表：注释、层、在本表语句里的角色、生产它的任务、每一列及用法，以及下面的时间事实 |
| 4. 血缘事实 | `lineage` | `columns[]`（每个目标列：每条生产语句的加工方式、物理来源列、表达式与推导步骤）、`rules[]`（过滤、关联、去重、合并与 CASE 分支，编号 `p1…`）、`keys[]`（形态、粒度依据、候选键、`key_confidence`、`proven`）、`partition[]`、`upstream_tables`、`upstream_tasks`、`downstream[]`（下游任务、它写的表、依据是血缘还是任务登记） |
| 5. 目标列顺序 | — | 文档必须遵守的列顺序 |

血缘事实来自语义画像（`describe` 的构建器），并带上表卡一起读，因此知道下游消费者、也知道别的任务证明唯一
的关联。画像在这里是输入，不再是交付物。

每张输入表带上第 9 项检查要用的事实：`partition_read`（只取一个分区为 `equality`，否则 `range`，不过滤为
`none`）及其依据 `partition_filters`；`date_filters`（落在日期、时间类列上的非分区过滤）；`name_convention`
（`_df` / `_da` 一类表名为 `full`，`_di` / `_hi` 为 `incremental`，其余 `unknown`）——这是命名约定，公开出来
让读者看到检查的前提。`full_snapshot` 即以 `equality` 方式读取的 `full` 表。

### 负责人与邮箱

材料包要交给模型，所以从不带人：任何负责人键（`owner`、`owner_email`、`target_table_owner` 等）出现在哪
都删掉；每条注释按 `parse` 默认的方式脱敏（邮箱、电话、证件号）；SQL 里的注释同样脱敏；最后再扫一遍，
材料包里任何位置（包括 SQL）剩下的邮箱地址都会被遮盖。

### 摘要

`packet_digest` 是对材料包全部事实计算的十六位十六进制摘要。输入相同摘要就相同；元数据、SQL 或任何血缘事实
变了，摘要就变。文档照抄它所依据的材料包的摘要，第 8 项检查拿它与当前材料包比较。

## `table-semantics/1` 格式

每张目标表一份 JSON。Schema 随包发布在 `scope_lineage/schemas/table-semantics.schema.json`，不认识的键一律拒绝。

```json
{
  "doc_format": "table-semantics/1",
  "table": "demo_dwd.dwd_party_customer_info_df",
  "packet_digest": "e21d636c4c7a990f",
  "generator": {"prompt": "table-semantics-prompt@0", "model": "hand-written example"},
  "summary": {"what": "...", "row": {}, "refresh": {}, "scope": [], "upstream": [],
              "downstream": [], "good_for": [], "not_for": [], "watch": [], "questions": []},
  "columns": [],
  "steps": ["..."],
  "rules": [],
  "task": {"name": "dwd_party_customer_info_daily", "purpose": "...", "outputs": ["demo_dwd.dwd_party_customer_info_df"]},
  "concept": {"concept": "concept:customer", "representation_kind": "core"}
}
```

| 键 | 内容 |
| --- | --- |
| `table` | `db.table`，不带目录前缀 |
| `packet_digest` | 从材料包照抄 |
| `generator` | 写它的提示词（可选再加模型） |
| `summary` | 一页纸，十个键都必填（数组可以为空） |
| `columns[]` | 目标表每一列，按表内顺序 |
| `steps[]` | 加工过程，一到七句话 |
| `rules[]` | 过滤、关联、去重、派生、合并：业务说法加上照抄的 SQL 原文 |
| `task` 或 `tasks[]` | 生产任务：`name`、`purpose`、`outputs`，可选 `cycle`、`upstream_tasks`、`downstream_tasks`——两个键只能出现一个 |
| `concept` | 可选，链接本体目录：`concept:<id>` 与本表的表现类型 |
| `confirmed[]` | 由 `semantic confirm` 写入：每条已套用的确认（`target`、`by`、`date`） |

### 来源与置信

每个陈述性条目都带 `sources`，取值 `comment`、`sql`、`sql_comment`、`metadata`、`task`、`inferred`、
`confirmed`；可以带 `confidence`（`high` / `medium` / `low`），以及写矛盾或风险的 `watch`。带来源的条目是
`summary.row`、`summary.refresh`、每条 `summary.scope[]` 与 `summary.upstream[]`、每一列、每个码值、每条规则。

### 一页纸

| 键 | 内容 |
| --- | --- |
| `what` | 一句话：这张表是什么 |
| `row` | 一行是什么：`text`、`grain_columns`、`grain_source`（`declared` / `inferred` / `proven`）、`unique`（`yes` / `no` / `unknown`），不唯一时在 `note` 写风险 |
| `refresh` | `cycle`、`time`（`snapshot` / `incremental` / `zipper` / `unknown`）与 `how_to_read`：怎么取一天、怎么取一段 |
| `scope[]` | 收哪些记录，业务说法，用 `rule_refs` 引用规则 |
| `upstream[]` | 每张输入表的 `role`（`main` / `enrich` / `filter` / `dedup` / `union_branch` / `lookup` / `other`）与它 `provides` 什么 |
| `downstream[]` | 下游 `task`，可选它写的 `table` |
| `good_for[]` / `not_for[]` | 典型用法与边界 |
| `watch[]` | 矛盾、风险、废弃与覆盖缺口，每条带 `kind`，可选 `refs`（如 `column:x`、`rule:r2`） |
| `questions[]` | 给负责人的待确认问题，最多五个：`id`（`q1`…）、`text`、`about`、`status`（`open` / `answered`），回答后有 `answer`、`answered_by`、`answered_on` |

### 字段与规则

字段包括 `column`、`meaning`（业务名）、`category`（`identifier`、`foreign_identifier`、`descriptive`、
`state`、`measure`、`time`、`technical`）、`derivation`（业务说法的口径；多分支时用 `branches[]`）、
`source_columns`（口径读到的 `db.table.column`）、`code_values[]`（`value`、`meaning`、`sources`，猜测的
标 `unconfirmed: true`），可选 `unit`、`null_meaning`、`watch`，以及 `sources` 与 `confidence`。

规则包括 `id`（`r1`…）、`kind`（`filter`、`join`、`dedup`、`derive`、`union`、`other`）、`text`、`sql`
（脚本里的 SQL 原文片段）与 `sources`。

### Schema 留给交叉检查的部分

Schema 只查结构。模型常出错的两个数量故意留给第 7 项检查，让它们进入重写清单、而不是让整份文档失败：
`sources` 为空，以及问题超过五个。

## `semantic validate`

```bash
scope-lineage semantic validate <documents> --packets <packet dir> [--json]
```

读取 `<documents>` 下每个 `*.json`；工具链自己的其他文档（`semantic-confirmations/1`、材料包、报告）跳过，
其他一律检查。Schema 不通过的文档报出错误、不做交叉检查。合法的文档与 `<packet dir>/<table>/packet.json`
对照：

| # | 检查 | 失败条件 | 警告条件 |
| --- | --- | --- | --- |
| 1 | `coverage` | 缺目标表的列、多出或重复的列、顺序与表内不一致 | — |
| 2 | `source_columns` | 来源列既不在该列的血缘里，也不在任何输入表里 | 只在输入表元数据里，不在该列的血缘里 |
| 3 | `code_values` | 未标 `unconfirmed` 的码值在相关注释和 SQL 里都找不到 | — |
| 4 | `grain` | 粒度列不是目标表的列，或写了 `grain_source: proven` 而材料包里没有证明的键 | 声称的粒度列与证明的键不同 |
| 5 | `rules` | 非分区过滤没有被任何 `rules[].sql` 引用；引用的 `sql` 规范化后在任务 SQL 里找不到；`rule_refs` 指向不存在的规则 | 材料包里没有 SQL，无法核对原文 |
| 6 | `neighbours` | 上游表不是血缘里的输入表；下游任务（或声称它写的表）不认识 | 下游任务认识，但不知道它写哪些表 |
| 7 | `sources` | 带来源的条目 `sources` 为空，或问题超过五个 | — |
| 8 | `digest` | `packet_digest` 与材料包不一致（过期），或没有这张表的材料包 | — |
| 9 | `time` | `refresh.time` 写 `incremental`，而所有输入都是按单一分区读取的全量快照、且没有按业务日期过滤 | `refresh.time` 写 `snapshot`，而写入按业务日期筛选 |

第 9 项存在的原因：把每日全量快照写成增量，读者就会把多个分区相加，每一行按天数重复计数。

第 5 项的规范化会转小写、去掉标识符引号、表限定、空白以及开头的 `WHERE` / `AND` / `ON`，所以血缘里的
`` `latest`.`rn` = 1 ``、文档引用的 `WHERE rn = 1` 和脚本里的 `latest.rn=1` 视为相同。

### 报告

一张表的通过率是检查项中未失败的比例；警告会列出，但不计入失败。文字摘要先打印每张表一行，再逐行列出失败项，
格式可直接作为重写提示：

```text
demo_dwd.dwd_party_customer_info_df: 46/51 checks passed (90.2%), 5 fail, 1 warn
  FAIL [1 coverage] columns: 缺少目标表的列 verified_customer_no（表内第 2 列）；补上这一列
  WARN [2 source_columns] columns[0].source_columns[1]: ...
  FAIL [9 time] summary.refresh.time: 写了 incremental，但上游 demo_ods.ods_core_customer_df 都按单一分区取全量快照，...
Validated 1 document(s): 0 clean, 1 with failures, 0 with warnings only, 0 with schema errors
```

`--json` 把同样的内容输出为 `table-semantics-validation/1` 文档：

```json
{
  "doc_format": "table-semantics-validation/1",
  "tables": [
    {
      "table": "demo_dwd.dwd_party_customer_info_df",
      "file": "demo_dwd.dwd_party_customer_info_df.json",
      "schema_errors": [],
      "counts": {"pass": 45, "warn": 1, "fail": 5},
      "pass_rate": 0.902,
      "checks": {"coverage": {"pass": 5, "warn": 0, "fail": 1}},
      "failures": [
        {"check": "coverage", "status": "fail", "at": "columns", "message": "..."}
      ]
    }
  ],
  "summary": {"documents": 1, "clean": 0, "tables_with_failures": 1,
              "tables_with_warnings_only": 0, "tables_with_schema_errors": 0, "pass_rate": 0.902}
}
```

### 退出码

| 退出码 | 条件 |
| --- | --- |
| 0 | 所有文档都通过 Schema（交叉检查的失败只报告，不致命） |
| 1 | 至少一份文档有 Schema 错误，或目录里没有 JSON |
| 2 | 文档目录或 `--packets` 不存在 |

## `semantic confirm`

```bash
scope-lineage semantic confirm <documents> --confirmations <file> [--out <dir>]
```

确认文件是 `semantic-confirmations/1` 文档（Schema：`scope_lineage/schemas/semantic-confirmations.schema.json`）。
每条写明一张表、一个目标、回答（`value`）、回答人（`by`）和日期（`date`，`YYYY-MM-DD`）：

```json
{
  "doc_format": "semantic-confirmations/1",
  "confirmations": [
    {
      "table": "demo_dwd.dwd_party_customer_info_df",
      "target": "question:q1",
      "value": "不会。注册系统只允许 F、M、U 三个值。",
      "by": "demo-reviewer",
      "date": "2026-09-26"
    }
  ]
}
```

| 目标 | `value` | 效果 |
| --- | --- | --- |
| `question:<id>` | 回答文字 | `status: answered`，写入 `answer`、`answered_by`、`answered_on` |
| `column:<c>.meaning` | 含义文字 | 替换 `meaning`；该列 `sources` 加 `confirmed` |
| `column:<c>.code_values` | `{value, meaning}` 列表，或单个这样的对象 | 列表整体替换码值，单个对象合并进去；每个被确认的码值加 `confirmed` 并置 `unconfirmed: false` |
| `summary.row` | 行字段组成的对象，或行描述文字 | 合并进 `summary.row`；其 `sources` 加 `confirmed` |

每条已套用的确认记入 `confirmed[]`，同一文件套用两次，第二次不改变任何东西。表、问题或列不存在、值的形状不对、
或套用后文档会违反 Schema 的确认，**不套用、也不丢弃**：摘要行计入 `unmatched`，并逐条列出原因。不给 `--out`
时就地改写有变化的文档；给了 `--out` 时所有文档写到那里，原文件不动。确认文件本身格式不对时退出码 2。

## 与本体目录、与 `describe` 的关系

两层回答不同的问题。表语义针对一张表、一列、一段 SQL；[本体目录](ontology-catalog.md)针对跨很多张表的业务
概念。表语义是本体的原料：它的 `concept` 键写明本表表现的概念（`concept:<id>`）与表现类型（本体目录里表现的
`kind`，如 `core`），让表语义页与概念页可以互相链接；本体发现的跨表问题（例如某列实际存的是另一个标识）以
`watch` 的形式回写到这张表的文档。

[任务语义描述](semantic-doc.md)（`describe`，旧的语义卡）不再作为给读者的交付物：它的构建器是材料包血缘事实的
来源，读者拿到的是依据材料包写成的表语义文档。
