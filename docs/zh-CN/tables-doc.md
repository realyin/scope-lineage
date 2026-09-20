[English](../en/tables-doc.md) | 中文

# tables.json / tables.md 语料级表卡（tables-json/1、tables-md/1）

`scope-lineage tables` 扫描一棵语料目录下的所有 `lineage.json`，对每个任务构建一次
[semantic profile](semantic-doc.md)，再把**同一张表**在语料内的生产侧与消费侧合并成一张表卡：
谁写它、它的一行代表什么、有哪些字段、谁读它、读了哪些列、怎么用。

单个任务的 `semantic.json` 回答"这个任务在做什么"；表卡回答一个单任务永远回答不了的问题——
**"这张表是什么"**。上游任务已经证明了它输出表的粒度与键，下游任务不必再猜。

## 定位：语料级派生视图，不是业务定义

- 表卡是版本化契约的**派生视图**，与 [mapping.md](mapping-doc.md)、[semantic.json](semantic-doc.md) 同级：
  每一条内容都来自某个任务的 `lineage.json`，可按任务名、`statement_id`、列名回链。
- 表卡里的每一行都能追到语料内某个具体语句。Core 在这里只做三件事：**归并、计数、用结构词复述**。
  它不给表起中文名、不判断表类型（宽表／维表／指标表）、不猜列的业务含义——这些缺席是设计。
- 稳定性分级与 semantic 文档一致：契约 ID 与表名列名可作连接键；`tables.json` 的键名在
  `tables-json/1` 内稳定；中文措辞与排版可能微调，机器应读 JSON 而不是 Markdown。

## 用法

```bash
# 语料目录：递归查找 lineage.json，产物写到 --out
scope-lineage tables --lineage /path/to/corpus --out /path/to/tables

# 只要机器读的 JSON
scope-lineage tables --lineage /path/to/corpus --out /path/to/tables --format json

# 带上导出的样例值（CSV / CSV 目录 / samples/1 JSON）
scope-lineage tables --lineage /path/to/corpus --out /path/to/tables \
  --samples /path/to/samples.csv --samples-top 5

# 跨语料：把别的语料已经算好的 tables.json 合进来（可重复）
scope-lineage tables --merge /path/to/a/tables.json --merge /path/to/b/tables.json \
  --out /path/to/tables
```

产物三件：

| 文件 | 给谁读 | 内容 |
| --- | --- | --- |
| `tables.json` | 机器 / RAG | 主产物，`doc_format: "tables-json/1"` |
| `tables.md` | 人 | 索引：表 / 生产任务数 / 消费任务数 / 注释有无 / 业务域 / 键置信 |
| `tables/<db.table>.md` | 人 / RAG 按表切块 | 每表一张卡，六个固定小节 |

Python API（消费 semantic profile，与文件写出同一条路径）：

```python
from scope_lineage import build_semantic_profile, build_table_cards
from scope_lineage import render_table_card_markdown, render_table_index_markdown

profiles = [build_semantic_profile(document, diagnostics) for document, diagnostics in corpus]
cards = build_table_cards(profiles, artifact_root="/path/to/corpus")
index = render_table_index_markdown(cards)
card = render_table_card_markdown(cards["tables"][0])
```

- `--lineage` 与 `render` / `describe` 完全一致：一个 `lineage.json` 或一棵递归查找它的目录树，
  同目录的 `diagnostics.json` 自动配对；版本不认识的文档在目录模式下跳过并计数。给了 `--merge`
  时它可以不给（纯合并模式）；两个都不给是参数错误（退出码 2）。
- `--merge` 接一份**别的语料**已经写出的 `tables.json`，可重复；见下文「跨语料合并」。
- `--out` 必填：表卡是语料级产物，没有"写在 lineage.json 旁边"的位置。
- `--format` 取 `json`、`md` 或两者（默认 `json,md`）；其他值直接报参数错误（退出码 2）。
- `--samples` 接一份**别人导出的**样例值文件（见下文「样例值」）；`--samples-top` 是每列最多
  发布几个不同的值（默认 5）。没传 `--samples` 时产物与该功能上线之前逐字节一致。
- 确定性：同一份语料无论以什么顺序被扫描，产出字节一致。

## 增量运行：`--incremental` / `--no-cache` / `--cache-from`

一份语料只改了一两个任务，重跑却要把每个任务重新读一遍、重新算一遍。`--incremental` 让这一遍
只落在指纹变了的任务上：

```bash
scope-lineage tables --lineage /path/to/corpus --out /path/to/tables --incremental
```

- 它在 `--out` 下写两样可丢弃的东西：`.scope-lineage-corpus-index.json`（每个任务
  `lineage.json` / `diagnostics.json` 的 sha256，加一份「影响推导的选项」的 sha256）与
  `.cache/`（每个任务在语料级合并之前贡献的那份事实）。
- 缓存里**只存语料级合并真正读的那些字段**：语义画像里给人看的那一半（`stages`、
  `confidence`、每个字段逐步的 `derivation` 等）合并从不读，也就不进缓存。哪些字段算数，
  由合并方自己那份清单说了算（`PROFILE_FIELDS_READ`，就写在读它的代码旁边）；清单改了，
  索引整份作废、全部重算。
- 存下来的那份事实**带版本号**：`payload_version`（当前 `corpus-cache/3`）。版本对不上的
  缓存文件与索引一律当没有、重算——旧版本里存的是另一种东西，不是少了几个字段。
- **语料级合并照样跑全量**：复用的只是每个任务自己贡献的那一半，所以增量跑出来的
  产物与全量跑逐字节一致。
- **换一份语料也能复用**（Q7）：`--cache-from <目录>` 再指一处事实缓存——另一次运行的
  `--out`，或它下面的 `.cache/`。同一个任务被解析到另一个目录下（重新解析、或是被一份更大的
  语料再走一遍），`lineage.json` / `diagnostics.json` 字节相同、选项摘要也相同时，就直接借用
  那份事实而不是重算；借来的文件会抄进本次运行自己的 `.cache/`，下次即本地命中，借出的那份
  目录可以删掉。可重复，按给出的顺序、在本地缓存之后依次尝试；它本身即蕴含 `--incremental`，
  `--no-cache` 仍然优先。语料路径**不进**选项摘要：同一个任务在哪个目录下解析，都该算出同一份事实。
- 事实文件按任务名存放，两份语料完全可能各有一个同名而内容不同的任务。能不能借用由文件里记着的
  指纹与选项摘要说了算，不由文件名说了算——同名不同内容的任务照样重算。
- 选项变了就整份作废、全部重算：`--overrides` 文件的**内容**、`--format`、读回来的
  `glossary.json` / `tables.json`、以及工具版本，任何一项对不上，索引就当没有。
  由别的子命令写下的索引或缓存（`command`、`doc_format` 对不上）同样当没有。
- 摘要行末尾多出 `reused=N, recomputed=M, removed=K`：复用了几个、重算了几个、语料里少了几个。
  给了 `--cache-from` 时第一项写成 `reused=N (borrowed=B)`，B 是从别处借来的那几个。
- 不给 `--incremental` 就是原来的全量跑，既不读也不写索引与缓存；`--no-cache` 先把这两样
  删掉再全量跑。

## 跨语料合并：`--merge`

一份语料只能证明它自己的任务写下的东西。证明某张表按某个键唯一的，往往是另一批任务里的某个
写语句；两份 `tables.json` 不合成一份，下游就只能拿到「这个 JOIN 可能扇出」。合并不是省事，
它是一张卡、一个 `safe` 判定、一条本体关系得以站在**不止一份语料**的证据上的唯一办法。

```bash
# 纯合并：没有语料要走，只有卡要折叠
scope-lineage tables --merge /path/to/a/tables.json --merge /path/to/b/tables.json \
  --out /path/to/merged

# 走一遍语料，再把别人的卡折进来（先文件、后本次语料）
scope-lineage tables --lineage /path/to/corpus --merge /path/to/a/tables.json \
  --out /path/to/merged
```

- **归并规则不变**：还是表卡自己的后缀规则，`aliases` 取并集，限定级别最高的写法作主名。
  同一张表在两份文档里各有半张卡（A 里有生产者、B 里有消费者），合出来是一张完整的卡。
- `produced_by[]` / `consumed_by[]` 取并集，按 `(task, statement_id, corpus)` 去重——
  **同名任务在两份语料里算两个**：那是两棵树的两次扫描，这里不假定它们是同一段代码。
  每条 entry 因此多一个 `corpus`（来源文档的 `corpus.artifact_root`，文档没记就是 `corpus:N`），
  借来的证据永远说得出该去哪棵树里找那个任务。
- `columns[]` 取并集：**顺序取第一份声明它们的文档**（那是某个 catalog 的声明顺序），
  只有后面的文档知道的列追加在末尾；`used_in_corpus` 取或，`consumer_usage_counts` 相加，
  `samples` 取并集、按首次出现排序，上限取各文档中最宽的那一份——卡上只有值没有 count，
  合并无从重排频次，也就不该发布比任何一份文档都宽的一列。
- `coverage` 全部重算，`findings` 在**合并后的证据**上重判：A 里没人读的表，一旦 B 里有人读，
  就不再是 `never_consumed_in_corpus`；两份语料的生产者候选键不一致，照样报
  `producer_key_conflict`，`evidence[]` 上带各自的 `corpus`。
- 顶层多一个 `merged_from[]`，每个原始语料一条（`corpus` 与 `task_count`）；`corpus.artifact_root`
  为 `null`（没有一棵树可以重走，`merged_from` 才是那份名单），`corpus.lineage_digests` 的键
  改成 `<corpus>/<task>`——两份语料可能各有一个同名任务、指纹不同，悄悄留一个是撒谎。
- **合并一份文档就是恒等**：没有跟任何东西合并过的文档不多出 `corpus`、也不多出 `merged_from`，
  与本功能上线之前逐字节一致。分两步合与一步合给出同一份 `merged_from`。
- 确定性：结果按表名排序，与 `--merge` 的先后无关；先后只决定「第一份文档」是谁——
  表注释、业务归属、列序取它的。
- 表卡 Markdown 第 4、5 节在合并后各多一列「语料」；没合并过的卡不多这一列。

Python API：

```python
from scope_lineage.render.table_cards import merge_table_cards

merged = merge_table_cards(first_tables_json, second_tables_json)
```

## tables.json 结构（tables-json/1）

```jsonc
{
  "doc_format": "tables-json/1",
  "corpus": {"artifact_root": "…", "task_count": 5, "lineage_digests": {"<task>": "…"}},
  "merged_from": [{"corpus": "…", "task_count": 5}],   // 只有 --merge 合并过才出现
  "samples_applied": {"sources": ["…/samples.csv"], "columns_sampled": 1,
                      "unmatched": ["mart.t.no_such_column"]},   // 只有传了 --samples 才出现
  "tables": [
    {
      "table": "spark_catalog.mart.customer_daily",   // 归一后的主名（最长写法）
      "aliases": ["mart.customer_daily"],             // 语料内见过的其它写法
      "comment": null,                                 // 元数据事实；没有就是 null
      "domain": null, "project": null, "owner": null, "layer": null,  // 表级元数据事实
      "kind": "physical",
      "produced_by": [
        {"task": "…", "statement_id": "stmt:001",
         "corpus": "…",                                 // 只有合并过才出现
         "stmt_kind": "INSERT_OVERWRITE",
         "partition": {"columns": ["dt"], "mode": "static", "spec": {"dt": "'20250101'"}},
         "grain": {"basis": "group_by", "keys": ["customer_id"]},
         "candidate_keys": ["customer_id"], "key_confidence": "proven",
         "fields": [{"column": "…", "comment": null, "summary": "…", "structural_role": "measure"}],
         "refresh": {"cycle": "day", "cron": "…", "source": "task_meta"},
         "header_comments": ["…"], "lineage_digest": "…"}
      ],
      "consumed_by": [
        {"task": "…", "statement_id": "stmt:001", "role_in_task": "driving", "roles": ["driving"],
         "columns": [{"name": "customer_id", "usages": ["join_key"]}],
         "read_by_scopes": ["ROOT"]}
      ],
      "columns": [
        {"name": "customer_id", "type": "string", "comment": null,
         "produced_summary": "…", "consumer_usage_counts": {"join_key": 2, "filter": 1},
         "used_in_corpus": true,
         "samples": ["C-001", "C-002"]}             // 只有传了 --samples 且这一列有值时才出现
      ],
      "coverage": {"column_comment_ratio": 0.0, "table_comment": false, "producers": 1, "consumers": 2,
                   "columns_used": 2, "columns_declared": 3, "columns_sampled": 1},
      "findings": [{"kind": "never_consumed_in_corpus", "text": "…",
                    "evidence": [{"task": "…", "statement_id": "stmt:001"}]}]
    }
  ]
}
```

- `produced_by[]` 每条来自该任务 semantic profile 的 `task` / `output_shape` / `fields` 块，
  `refresh` 来自任务 JSON 的 `meta`（`schedule_cycle` / `schedule`），没有就是 `null`——
  绝不从分区列或表名猜调度周期。
- `consumed_by[].columns` 只列**确实被逻辑块读到**的列；`columns[]` 则是元数据声明的全部
  字段（`related_metadata.*.declared_columns[]`，按 DDL 顺序）与生产侧字段、消费侧列的并集，
  因此一张只被读的表也有完整字段清单，一张八十列的表不会因为本语料只读了四列就只剩四列。
- `columns[].used_in_corpus` 说明本语料有没有写过或读过这一列：`false` 的列
  `consumer_usage_counts` 为空、`produced_summary` 为 `null`，它是「元数据声明了、语料没碰过」，
  不是「无人使用」。`coverage.columns_used` / `coverage.columns_declared` 是同一件事的两个计数，
  没有任何文档声明过这张表时 `columns_declared` 为 `null`（不是 0）。
- `consumer_usage_counts` 的取值来自 `filter`、`partition_filter`、`join_key`、`group_by`、
  `window_partition`、`window_order`、`output`，按这个顺序输出，计数为 0 的键不出现。

### 表名归一

一份语料常把同一张表记成几种限定级别（读的地方写 `mart.t`，写的地方写 `catalog.mart.t`）。
表卡按**点号后缀**规则把它们归为一张表（与 `skills/scope-lineage/scripts/query.py` 的
`_same_table` 同语义），**限定级别最高的写法作主名**，其余写法进 `aliases`，不丢弃。

后缀合并只发生在**带库名的写法之间**。不带点的裸表名不作为合并的桥梁：`ods.t` 与 `dwd.t`
是两张表，一段写了裸 `t` 的脚本不能把它们并成一张卡。裸名只在语料里**恰好只有一张**带点的
表与它后缀匹配时并入那张卡；有多张时它自成一张卡，并在该卡的 `findings` 里记
`ambiguous_bare_name`，由人来确认脚本实际读写的是哪一张。

### 样例值（`--samples`）

Core 不连数据库，所以「这一列的值长什么样」只能由**别人导出**再传进来。`--samples` 接三种写法：
一份表头为 `table,column,value[,count]` 的 CSV、一个装着这种 CSV 的目录（递归查找 `.csv`/`.json`），
或一份 `samples/1` JSON。

```csv
table,column,value,count
mart.customer_daily,country_code,US,30
mart.customer_daily,country_code,JP,20
mart.customer_daily,country_code,CN,10
```

```json
{
  "doc_format": "samples/1",
  "samples": [
    {"table": "mart.customer_daily", "column": "country_code", "values": ["US", "JP", "CN"]}
  ]
}
```

- **表名按表卡的规则匹配**：取最后两段、忽略大小写，所以 `spark_catalog.MART.t` 与卡上的
  `mart.t` 是同一张表；列名也忽略大小写。
- **每列最多 N 个不同的值**（默认 5，`--samples-top` 可改）：文件给了 `count` 就按 `count`
  从大到小排，没给就按文件里的先后顺序；重复的值只占一个位置。
- **永远脱敏，没有关掉它的开关**：样例值是本工具见过的最容易带个人信息的输入，每个值都先去掉
  首尾空白，再过一遍与 SQL 注释同一套的形状脱敏（邮箱→`<email>`、手机/国际号码→`<phone>`、
  身份证号→`<id>`），超过 64 个字符的值截断并加 `…`。它是**形状**匹配，既不穷尽也不保证准确——
  真正敏感的列不要导出来。
- **没命中的行只报告不丢弃**：文件里写了、但语料里没有这张表或这一列的键，进
  `samples_applied.unmatched[]`（`表.列`，用文件里的原写法），CLI 末尾打印
  `samples_columns=N, samples_unmatched=N` 并列出它们。
- 文件不存在、目录里没有可读文件、CSV 表头不对、JSON 不是 `samples/1`、`count` 不是整数时
  退出码为 2，报一句话，不抛 traceback。
- 卡上多出三处：`columns[].samples[]`（这一列没有值时**不出现**）、
  `coverage.columns_sampled`、顶层 `samples_applied`；表卡 Markdown 第 3 节多一列「样例值」，
  渲染成 `` `'US'`、`'JP'`、`'CN'` ``。没传 `--samples` 时三处都不出现，那一列也不出现。

### 什么不会成为一张表

- **会话内关系**：`CREATE TEMPORARY VIEW` 之类只活在脚本里的关系，别的任务读不到，
  判据与任务文档的 `final_table_states` / `produced_tables` 一致；
- **`directory:` 目标**：写目录不是写表，没有任何 catalog 声明它。

两者既不会成为表卡，也不会出现在别的表的 `aliases` 里。

## 表卡 `tables/<db.table>.md` 的六节

| 节 | 回答的问题 | 事实来源 |
| --- | --- | --- |
| 1 这张表是什么 | 表注释、业务归属（业务域 / 项目 / 负责人 / 分层，元数据说了才出现）、别名写法、语料内的生产/消费语句数、「本语料用到 n/N 个字段」（`columns_declared` 已知时才有这一行） | 元数据事实 + 生产任务的语句头注释（`SQL注释`，原样引用） |
| 2 一行代表什么 | 每个生产语句的粒度、逻辑键、候选键、键置信 | 结构推断（证据为 `statement_id`） |
| 3 字段 | 列 / 类型 / 注释 / 样例值（传了 `--samples` 才有这一列）/ 生产侧一句语义 / 消费侧用法计数；语料没碰过的列用法一栏是 `—`，超过 20 列时它们移到用到的列之后、附一行说明 | 元数据事实 + SQL事实 + 结构推断 + 导出的样例值 |
| 4 谁生产 | 任务、语句、写入方式、分区、更新频率；合并过的卡多一列「语料」 | SQL事实 + 任务元信息 |
| 5 谁消费 | 任务、语句、角色（词表同 `inputs[].role_in_task`，含 B2 的 `filter_partner`，见 [semantic-doc.md](semantic-doc.md)）、用到哪些列、怎么用；合并过的卡多一列「语料」 | SQL事实 + 结构推断（角色） |
| 6 治理线索 | 多生产者、键冲突、无人读、无人写 | SQL事实（证据为 `<task>/<statement_id>`） |

行标签风格与 [semantic.md](semantic-doc.md) 一致：`（元数据事实）`、`（SQL事实）`、
`（结构推断；证据 …）`、`（SQL注释）`。文件名把 `/`、空格等文件系统不接受的字符换成 `_`。

`findings[].kind` 只有五种，含义都是"这是语料内可观察到的事实"，不是判决：

| kind | 含义 |
| --- | --- |
| `ambiguous_bare_name` | 这个表名没有库名限定，语料内有多张表可能是它；它们没有被合并，需人工确认 |
| `multiple_producers` | 语料内有多于一条写语句写这张表；下游读到谁的结果取决于调度顺序 |
| `producer_key_conflict` | 多个生产语句给出的候选键不一致，口径需要人来裁决 |
| `never_consumed_in_corpus` | 语料内没有任务读它；可能是对外出口，也可能是无人消费的产出 |
| `never_produced_in_corpus` | 语料内没有任务写它；它的一行代表什么无法从本语料证明 |

## describe 消费表卡：`describe --tables`

```bash
scope-lineage tables   --lineage /path/to/corpus --out /path/to/tables
scope-lineage describe --lineage /path/to/corpus/one_task/lineage.json \
  --tables /path/to/tables/tables.json
```

给了 `--tables` 之后，`semantic.json` 多出三处（按归一表名匹配），第四处是被**改写**的
`output_shape`（见下文「表卡参与 fan_out 判定」）：

```jsonc
{
  "task": {
    "downstream_consumers": [{"task": "…", "role_in_task": "driving", "columns": ["customer_id"]}]
  },
  "inputs": [
    {"table": "mart.customer_daily",
     "card": {"produced_by_task": "…", "grain_text": "分组聚合后的一行；逻辑键 customer_id；…",
              "candidate_keys": ["customer_id"], "key_confidence": "proven",
              "comment": null, "refresh": {"cycle": "day", "cron": "…", "source": "task_meta"}}}
  ],
  "confidence": {
    "metadata_coverage": {"table_cards": {"inputs_with_card": 1, "inputs_total": 3, "consumers": 2}}
  }
}
```

`semantic.md` 相应多出两处：第 1 节输入表表格多一列"一行是什么（来自生产任务）"，
目标表那几行后多一行"下游消费：…"。

- 语料内没有任务写某张输入表时，该输入的 `card` 是 `null`，表格里写"⚠ 本语料内无生产任务"——
  **"没给语料"和"语料证明没人写"是两个答案，不会渲染成同一句**。
- 有生产任务、但那个任务自己也没能判定粒度时，`card.grain_text` 写成
  `生产任务 <task> 未能判定粒度（<上游 grain walk 停下来的原因>）`，而不是以"未知"开头——
  "没有上游"和"有上游但上游没证出来"同样是两个答案。

### 表卡参与 fan_out 判定

一条语句永远无法证明一张物理表按连接键唯一，所以 JOIN 到物理表的 `fan_out_risks[]` 只能停在
`unknown` / 「物理表无主键事实」。表卡里有另一个任务的证明，`describe --tables` 因此把表卡交给
**画像构建本身**（`build_semantic_profile(..., table_cards=...)`）：fan_out 判定只有一处，
表卡只是它的第四种证据来源。所以由 `output_shape` 派生的东西（字段的 `candidate_key` 角色、
`inferred_items` 计数）看到的也是同一个答案：

| 条件 | 结果 |
| --- | --- |
| JOIN 右侧是物理表，其表卡的 `key_confidence` 是 `proven`，且 `candidate_keys` ⊆ 该 JOIN 右侧连接键列名 | 该条风险改判 `safe`，`reason` 写「生产任务 `<task>` 已证明 `<keys>` 唯一（表卡）」，并加 `basis: "table_card"` |
| 同上但表卡的 `key_confidence` 是 `candidate` | 同样改判 `safe`，但 `reason` 注明「表卡候选键，未证唯一」，且整条语句的 `key_confidence` 上限压到 `candidate` |
| 表卡 `key_confidence` 是 `proven_unexposed` 或 `none`，或连接键没盖住候选键 | 不改判，仍是原来的结论 |

`candidate_keys`、`unexposed_keys`、`key_evidence`、`key_confidence` 都由最终的风险集合算出——
它们本来就是「粒度链路上每个 JOIN 都 `safe`」这个前提的函数。没有传 `--tables` 时，
`output_shape` 与表卡功能上线之前逐字节一致。
- 没有传 `--tables` 时，上面三个键**根本不出现**，`semantic.json` / `semantic.md` 与表卡功能
  上线之前逐字节一致。要"空值"语义就把 `--tables` 传上。
- `--tables` 指向的文件不存在（退出码 2）或不是 `tables-json/1`（退出码 1）时直接报错，
  不会静默退回"没有表卡"。

## 不做的事

- 不给表或列起中文名、不推断表类型、不猜 code 值的业务含义（值域与术语见字典层）；
- 不连数据库取样例值：`columns[].samples[]` 只可能来自 `--samples` 传进来的文件，Core 自己不会去查数；
- 不做跨语料的传递闭包分析——`--merge` 合的是几份语料各自陈述过的事实，不跨语料推演链路；
  血缘链路追踪见 [Agent 技能](agent-skill.md) 的 `query.py trace`。
