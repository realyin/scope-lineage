[English](../en/table-semantics.md) | 中文

# 表语义（`table-semantics/1`）：材料包、校验、确认、渲染

表语义针对一张目标表，用业务读者的话回答：这张表是什么、一行是什么、怎么更新、怎么取一天和一段时间、
收哪些记录、数据从哪来给谁用、每个字段什么意思怎么算、字段有哪些码值、要注意什么。

文档由模型写、由机器对照事实校验。Core 只做确定性的工作，从不调用模型：

- `scope-lineage semantic packet` 把写一张表所需的全部事实收成一份**材料包**——表的元数据、每个生产任务
  及其 SQL、输入表、语义画像已经推出的血缘事实；
- `scope-lineage semantic validate` 用 JSON Schema 和材料包（十三项交叉校验）检查写好的
  `table-semantics/1` 文档，逐条列出要重写的地方；
- `scope-lineage semantic confirm` 把人的回答写回文档；
- `scope-lineage semantic render` 把文档渲染成每表一页和一页索引，并与本体目录的概念页互相链接。

写文档（提示词、重写循环）属于 Agent 技能：提示词在 `skills/scope-lineage/references/table-semantics-prompt.md`，
编排步骤见技能的 `SKILL.md`。

[`examples/table-semantics/`](../../examples/table-semantics/) 里有一份为演示表手写的示例文档和一份
配套的确认文件；两者和它们描述的演示语料一样，都是虚构的。

## 位置

| 步骤 | 谁来做 | 命令 | 产出 |
| --- | --- | --- | --- |
| 1. 材料包 | 机器 | `semantic packet` | `<out>/<db.table>/packet.md` 与 `packet.json` |
| 2. 写作 | 模型，经 Agent 技能 | — | 每表一份 `table-semantics/1` JSON |
| 3. 校验 | 机器 | `semantic validate` | 文字摘要，或 `--json` 报告（其中的失败清单就是重写提示） |
| 4. 渲染 | 机器 | `semantic render` | 每表一页 `<db.table>.md` 与 `index.md` |
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
scope-lineage semantic validate out/confirmed --packets out/packets --json > out/validation.json
scope-lineage catalog build examples/catalog-demo --out out/catalog
scope-lineage semantic render out/confirmed --out out/pages/semantics \
  --validation out/validation.json --ontology out/catalog/ontology.json
scope-lineage catalog render out/catalog/ontology.json --out out/pages \
  --semantics out/pages/semantics
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

给了 `--only` 时不再为整个语料建画像。写或读一张表的文档一定写着它的名字，所以只解析字节里含有所请求表名的
血缘文档：有 `--tables` 时只留写这张表的文档；没有时再加上它各输入表的生产文档，用这些文档建表卡。材料包与
全量运行完全一致；摘要行的任务数就是读了多少份文档。

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

过滤是否在取分区，逐个合取项判断，因为血缘自己的标记是对整个 `WHERE` 子句的列名规则（`dt = x AND status = 0`
两半都不会被标记）。每条过滤规则带 `partition_filter` 与它依据的 `partition_basis`：

| `partition_basis` | 条件 |
| --- | --- |
| `metadata` | 过滤涉及的每一列在元数据里都有分区事实（列上的 `isPartition`，或 DDL 的 `PARTITIONED BY`）；在那里被标为分区的列，不论叫什么都算分区列 |
| `partition_name` | 元数据标明表是分区表（`is_partition`）但没有指出哪一列，且过滤把 `dt` / `ds` / `pt` / `p_date` 列与常量或 `${...}` 参数比较 |
| `lineage` | 两者都没有：沿用血缘的标记 |

目标表和输入表各列的 `partition` 也按同样的事实标注。

另有三类事实供含义检查（第 10–13 项）使用。每条关联规则带 `right`（右侧：`库.表`，或画像的 scope 编号，
如 `subq:p`）、`right_aliases`（ON 子句与 scope 给它的别名）、`right_tables`（它背后的物理表）和
`fan_out`——画像对右侧是否按关联键唯一的判定（`{status, reason, path}`，`status` 为 `safe` / `risk` /
`unknown`；画像没有走到的关联为 `null`）；`packet.md` 在规则表的「行数放大」一列里给出。每个列的生产语句带
`case_outputs`：该列最后一步计算是一个输出全为字符串或数字字面量（NULL 与 `''` 除外）的 CASE 或 IF 时，每个值一条，写明分支条件
（`when`）、这些条件比较的来源值（`source_values`；条件不是等值或 `IN` 列表时为 `null`）以及是否由 ELSE 返回
（`catch_all`）。每个任务带 `header_facts`：头注释写明的生命周期（`生命周期` / `保留` / `lifecycle` 后跟天数
或 `永久`）与数据规模（`数据规模` / `数据量` 后跟数字），从血缘发布的头注释和脚本开头的注释行里读取；
`packet.md` 以「头注释」一行列出。

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
  "packet_digest": "04439862460b03d6",
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
| 10 | `fan_out` | `fan_out.status` 不是 `safe` 的关联，其右侧既没有在 `summary.row.note` 里、也没有在任何 kind 为 `risk` 的 `summary.watch` 里被点名（表名 `库.表` 或不带库名，或别名；同一右侧不论关联几次只算一项） | 行说明或某条 watch 的某句话把这样的左关联写成不影响行数（无影响、不影响行数、不会放大……）；每处一条警告 |
| 11 | `derived_codes` | 列的 CASE / IF 返回的字面量（`case_outputs`）不在它的 `code_values` 里（每缺一个值一条失败；NULL、`''` 和 TRUE / FALSE 不算码值） | 含义像「成功」的码值（成功 / 正常 / 通过 / 有效）来自归并多个来源值的分支或 ELSE，而该列的 `watch` 和 `refs` 含 `column:<列>` 的 `summary.watch` 都没有说明 |
| 12 | `documented_meaning` | 标了 `unconfirmed` 或含义写「待确认」的码值，其含义在该列注释或来源列注释里已写明（`0-申请 1-成功` 式的值-含义对，或 SQL 里引用了其标签的 `正常、锁定、删除` 式列表）；注释写明的含义本身就是「待确认」的状态可以照写 | 主输入表注释或来源列注释里有限定词（`增值税`、`税`、`手续费`、`罚息`、`冲正`、`测试`）而目标表注释里没有，`summary.what`（主输入表）或所有受影响列的 meaning / derivation 里也没写（每个词一条警告） |
| 13 | `header_facts` | — | SQL 头注释写明了生命周期（`header_facts.lifecycle`）或数据规模（`header_facts.volume`），而 `summary.refresh.how_to_read` 和 watch 都没有提到 |

第 9 项存在的原因：把每日全量快照写成增量，读者就会把多个分区相加，每一行按天数重复计数。

第 1–9 项核对文档的形式：每一列都覆盖、每个来源都有出处、每段引用都找得到。第 10–13 项核对含义，因为一页
文档可以通过前九项却依然误导读者：会重复行的关联没有提、派生出来的码值漏了、注释已经解释的值被当成问题、
增值税或测试这样的限定被丢掉、十天的生命周期没有传达。它们读取「材料包里有什么」一节所述的事实（`fan_out`、
`case_outputs`、`header_facts`）和注释；在这些事实出现之前生成的材料包里没有它们，相应检查就无事可查。
限定词清单是 `scope_lineage/semantics/checks_documented.py` 里的 `QUALIFIER_TERMS`；同一条注释里被更长的词
包含的词（增值税里的税）只按更长的词报一次。

第 5 项的规范化会转小写、去掉标识符引号、表限定、空白以及开头的 `WHERE` / `AND` / `ON`，所以血缘里的
`` `latest`.`rn` = 1 ``、文档引用的 `WHERE rn = 1` 和脚本里的 `latest.rn=1` 视为相同。

血缘里的每个谓词都经 SQLGlot 渲染，`rules[].sql` 却照抄脚本原文，所以第 5 项在同一个空间里比较两者。一段
片段有两种形式：宽松文本，以及 SQLGlot 按血缘所用方言能解析时渲染出的文本。任务 SQL 有宽松文本、渲染文本，
以及每个 `WHERE`、`HAVING`、`ON` 谓词和其中每个合取项各一个单元——按原样渲染一次，再把子查询或 CTE 算出的
列替换成它背后的表达式渲染一次。引用的片段只要有一种形式出现在脚本里或等于某个单元，就算找到；过滤只要有
一种形式与某条引用、或与该引用相等的单元的某种形式相合，就算被引用。因此脚本里的 `nvl(x, 0) = 1`、
`substr(n, 1, 2) = 'AB'`、`x is not null` 分别引用了血缘的 `COALESCE(x, 0) = 1`、`SUBSTRING(n, 1, 2) = 'AB'`、
`NOT x IS NULL`；子查询 `a` 这样算出 `dt` 时，引用 `a.dt = '${bizdate}'` 也就引用了
`DATE_FORMAT(time_inst, 'yyyyMMdd') = '${bizdate}'`。SQLGlot 解析不了的片段或脚本，仍按宽松文本比较。

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

## 独立审读与修订

`semantic validate` 保证的是形式：每列都写了、出处在血缘里、规则照抄了原文、时间语义与分区一致、行数放大被点名。它保证不了含义——一个派生列在什么情况下为空、页面写的是目标码还是原码、回填的 0 是「真的为 0」还是「没有值」、取数说明和适用说明是否互相矛盾，这些在真实验收里都出现过「校验全过、内容却错」的页面。

所以写作之后加两步，都在 Agent 技能里：

1. **独立审读**（`skills/scope-lineage/references/table-semantics-review-prompt.md`）：另起一次调用，只读材料包、文档和已确认事实，按十五项清单找事实错误，按严重程度列出「文档原话 / 材料原文 / 应改成」。审读员可以读兄弟表的材料包，核实文档对其他表的说法。
2. **修订**（`skills/scope-lineage/references/table-semantics-fix-prompt.md`）：逐条核实后修改，改完通读全页消除前后矛盾，推断与事实分开，再跑一次 `semantic validate`。

两条经验：审读必须是独立的调用，写作者自查找不出自己的盲点；修订容易在一处改对、另一处留下旧说法，所以修订后通读全页那一步不能省。验收问题集不要交给写作、审读或修订的调用。

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

## `semantic render`

```bash
scope-lineage semantic render <documents> --out <dir> \
  [--validation <report.json>] [--ontology <ontology.json>]
```

把 `<documents>` 下每份合法的 `table-semantics/1` 文档渲染成一页 `<dir>/<db.table>.md`，再写一页
`<dir>/index.md`。工具链自己的其他文档（确认文件、材料包、报告）跳过；不合 Schema 的文档在 stderr 报出、
不渲染，退出码为 1。

| 选项 | 必填 | 含义 |
| --- | --- | --- |
| `<documents>` | 是 | `table-semantics/1` 文档目录 |
| `--out` | 是 | 输出目录 |
| `--validation` | 否 | `semantic validate --json` 写出的 `table-semantics-validation/1` 报告：页面标出未通过的条目，文末加「校验」一节，索引写通过率 |
| `--ontology` | 否 | `catalog build` 写出的 `ontology.json`：每张表的域与概念取自目录，概念链到 `../concepts/<slug>.md` |

### 表语义页

页面顺序照一页样例排：

| 部分 | 内容 |
| --- | --- |
| 标题行 | 表名；下一行是域（有 `--ontology` 时是概念所属的域，否则是库名）、「本表是 <概念> 的 <表现类型>表」、本页已确认的条目数；有报告时再加通过率 |
| 一页纸 | 这张表是什么、一行是什么（粒度列、粒度来源、是否唯一）、更新与取数、收哪些数据（引用的规则）、数据从哪来（上游表及其作用）、谁在用、适合用来 / 不适合、要注意（每条带种类）、待确认问题（已回答的带回答、回答人与日期） |
| 字段 | 按五组列出：标识与关联、状态与码值（有码值的列都在这一组，多一列「码值」）、金额（含义后带单位）、时间，各一张「字段 / 含义 / 口径 / 来源」表；描述与技术列写成一行。口径依次写各分支（`线上：…；线下：…`）、总的说法、为空的情形 |
| 加工过程 | 产出任务（周期与用途），然后是加工步骤 |
| 规则（原文） | 每条规则的编号与种类、业务说法、SQL 原文 |
| 来源说明 | 来源词与各个标记的意思；写作所用的提示词与依据的材料包摘要 |
| 校验 | 只在给了 `--validation` 时出现：通过率，以及每个未通过项和警告的检查、位置与改法 |

页面上的标记：

| 标记 | 意思 |
| --- | --- |
| ✓ | 条目的 `sources` 含 `confirmed`（`semantic confirm` 写入），或问题已回答；标在它确认的内容旁（列的含义、码值、规则等） |
| ⚠ | 条目带 `watch`，后面跟着 `watch` 的文字；列或规则只被一页纸的「要注意」引用（`column:<列>`、`rule:<id>`）时写「⚠（见要注意）」 |
| ✗n | 报告里第 n 个未通过项落在这个条目上（按报告顺序编号）；指向整张表的未通过项（缺列、未引用的过滤、过期摘要）只列在「校验」一节 |
| `值（含义待确认）` | 标了 `unconfirmed: true`（或含义以「待确认」开头）的码值 |
| （中置信）（低置信） | 条目的 `confidence` 不是 `high` |

### 索引

`index.md` 先按域、再按概念列出每张表：表（链到它的页）、这张表是什么（`summary.what`）、校验通过率
（没有报告时写 —，报告里没有这张表时写「未校验」）、待确认问题数（仍为 `open` 的问题）；按概念的表多一列
表现类型。有 `--ontology` 时，域是表所表现概念的域、概念标题链到概念页；否则域用库名，概念取文档自己的
`concept`、只写编号不加链接。不属于任何概念的表列在最后的「未关联概念」下。不按任何公司的表名约定分组。

### 与概念页互链

概念归属以本体目录为准：目录把这张表登记为某个概念的表现时，用目录里的概念和表现类型；目录没有登记这张表
时才用文档自己的 `concept`。表语义页链到 `../concepts/<slug>.md`，也就是 `catalog render` 写的概念页，所以
`--out` 要放在 `catalog render` 输出目录下的一个子目录里，例如 `<pages>/semantics`。反方向由
`catalog render --semantics <pages>/semantics` 负责，见[本体目录](ontology-catalog.md)。两个选项都可不给；
不给时两边的输出与没有这个功能时逐字节相同。

### 退出码

| 退出码 | 条件 |
| --- | --- |
| 0 | 所有文档都已渲染 |
| 1 | 有文档不合 Schema（其余照常渲染），目录里没有可渲染的文档，或 `--validation` / `--ontology` 的 `doc_format` 不对 |
| 2 | 文档目录、`--validation` 或 `--ontology` 不存在或读不了 |

## 与本体目录、与 `describe` 的关系

两层回答不同的问题。表语义针对一张表、一列、一段 SQL；[本体目录](ontology-catalog.md)针对跨很多张表的业务
概念。表语义是本体的原料：它的 `concept` 键写明本表表现的概念（`concept:<id>`）与表现类型（本体目录里表现的
`kind`，如 `core`），让表语义页与概念页可以互相链接（`semantic render --ontology` 与 `catalog render --semantics`）；本体发现的跨表问题（例如某列实际存的是另一个标识）以
`watch` 的形式回写到这张表的文档。

[任务语义描述](semantic-doc.md)（`describe`，旧的语义卡）不再作为给读者的交付物：它的构建器是材料包血缘事实的
来源，读者拿到的是依据材料包写成的表语义文档。
