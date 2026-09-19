[English](../en/glossary-doc.md) | 中文

# glossary.json / glossary.md 术语与值域字典（glossary-json/1）

`scope-lineage glossary` 扫描**一整份语料**（一棵 `lineage.json` 目录树），把它聚合成一本
按列名组织的字典：每个列名有哪些注释、被哪些常量比较过、哪些取值集合已被 SQL 证明封闭。
它回答的是单个任务回答不了的问题——`describe` 只能说"这个字段按 `pay_status = 'PAID'`
过滤"，字典能说"`pay_status` 在 9 张表里出现，注释是这三种说法，语料里一共见过 4 个取值"。

## 定位：语料级派生视图，不是业务词表

- 字典只有**两个**内容来源：契约里的注释（列注释、表注释、SQL 注释）与契约里的常量。
  Core 不从值的拼写猜含义，不翻译，不同义扩写。
- `meaning` 只有人工确认能填（`glossary.overrides.json`），填上后标 `source: "override"`；
  `meaning_candidates` 是"某条注释的文字里**字面出现**了这个值，或该列自己的注释把这个值
  **枚举**了出来"，是线索不是结论。
- **观察到的值集合是下限，不是上限。** 只有两种情况写 `closed_set`：`IN` 列表，
  以及带 ELSE 且每个 THEN 与 ELSE 都是常量的 CASE。其余一律 `null`——
  "语料里只见过这 3 个值"不等于"这个列只有 3 个值"。
- 它是阶段二本体（`ontology-json/1`）的 `value_domains` + `synonyms` 切片提前交付，
  槽位与后者的 `in_set` 约束对齐：同样是（列、值、证据、任务数、完备性）五元组。

## 用法

```bash
# 一份语料 → 一本字典
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict

# 带上人工确认过的含义
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict \
  --overrides /path/to/glossary.overrides.json

# 顺带生成一份「取值含义待填模板」（.md 给人填，同名 .json 回头当 --overrides 用）
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict \
  --template /path/to/dict/glossary.overrides.template.md --template-top 20

# 只要 JSON
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict --format json

# 把字典交给 describe，字段语义里就带上取值含义
scope-lineage describe --lineage /path/to/task --glossary /path/to/dict/glossary.json
```

Python API（消费契约文档 dict，与文件写出同一条路径）：

```python
from scope_lineage import build_glossary, render_glossary_markdown

glossary = build_glossary(lineage_documents, artifact_root="corpus", overrides=overrides)
markdown = render_glossary_markdown(glossary)
```

- `--lineage` 与 `render` / `describe` / `tables` 完全一致：一个 `lineage.json` 或一棵递归查找
  它的目录树；两种契约形状都接受（语句文档 `1.0` 与任务文档 `2.0`）；其他版本在目录模式下
  跳过并计数，单文件模式报错退出（1）。
- `--out` 必填，写入 `glossary.json` 与 `glossary.md`；`--format` 取 `json`、`md` 或两者。
- `--overrides` 指向的文件不存在、不是合法 JSON、或顶层不是对象时退出码为 2——
  一份被人工确认过的文件被静默忽略，比报错更危险。
- `corpus.artifact_root` **原样记录** `--lineage` 的取值。要求产物字节可复现时传相对路径。

## 增量运行：`--incremental` / `--no-cache`

一份语料只改了一两个任务，重跑却要把每个任务重新读一遍、重新算一遍。`--incremental` 让这一遍
只落在指纹变了的任务上：

```bash
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict --incremental
```

- 它在 `--out` 下写两样可丢弃的东西：`.scope-lineage-corpus-index.json`（每个任务
  `lineage.json` / `diagnostics.json` 的 sha256，加一份「影响推导的选项」的 sha256）与
  `.cache/`（每个任务在语料级合并之前贡献的那份事实）。
- **语料级合并照样跑全量**：复用的只是每个任务自己贡献的那一半，所以增量跑出来的
  产物与全量跑逐字节一致。
- 选项变了就整份作废、全部重算：`--overrides` 文件的**内容**、`--format`、读回来的
  `glossary.json` / `tables.json`、以及工具版本，任何一项对不上，索引就当没有。
  由别的子命令写下的索引或缓存（`command`、`doc_format` 对不上）同样当没有。
- 摘要行末尾多出 `reused=N, recomputed=M, removed=K`：复用了几个、重算了几个、语料里少了几个。
- 不给 `--incremental` 就是原来的全量跑，既不读也不写索引与缓存；`--no-cache` 先把这两样
  删掉再全量跑。

## glossary.json 结构（glossary-json/1）

```jsonc
{
  "doc_format": "glossary-json/1",
  "corpus": {"artifact_root": "…", "task_count": 12, "statement_count": 17,
             "lineage_digests": {"<task_id>": "8c292a40a47f1439"}},
  "terms": [
    {"column": "pay_status",
     "comments": [{"text": "支付状态", "tables": ["ods.app_order", "ods.web_order"], "count": 2}],
     "tables_total": 3, "tables_without_comment": ["ods.pos_order"], "conflict": false,
     "meaning": null}
  ],
  "values": [
    {"column_ref": "ods.app_order.pay_status", "column": "pay_status",
     "value": "PAID", "sql_literal": "'PAID'", "kind": "literal",
     "observations": [{"task": "order_daily", "statement_id": "stmt:001",
                       "context": "filter_eq", "evidence": "rule:003",
                       "expression": "pay_status = 'PAID'"}],
     "task_count": 2,
     "closed_set": {"values": ["PAID", "REFUND"], "basis": "in_list"},
     "meaning_candidates": [{"text": "支付状态，PAID 表示已结算", "source": "column_comment",
                             "evidence": "column:ods.app_order.pay_status"}],
     "meaning": {"text": "已支付", "source": "override",
                 "confirmed_by": "owner", "date": "2026-09-18"}},
    {"column_ref": "cte:latest_dim.rn", "logical": true, "column": "rn",
     "value": "1", "sql_literal": "1", "kind": "literal",
     "observations": [{"task": "…", "statement_id": "stmt:001",
                       "context": "join_condition", "evidence": "rule:002",
                       "expression": "rn = 1"}],
     "task_count": 1, "closed_set": null, "meaning_candidates": [], "meaning": null}
  ],
  "parameters": [{"column_ref": "ods.app_order.dt", "expression": "dt = '${bizdate}'",
                  "kind": "parameterized", "task_count": 6}],
  "overrides_applied": {"terms": 1, "values": 2, "blank": 0,
                        "unmatched": ["pay_status='GONE'"]}
}
```

| 键 | 内容 |
| --- | --- |
| `corpus` | 扫了什么：`artifact_root` 原样记录、任务数、写语句数、每个任务的契约摘要（与 mapping.md / semantic.md 用的是同一个 digest 函数，可据此确认字典与画像来自同一快照） |
| `terms[]` | 按**列名**跨表归并的注释；一个列名一条，按列名排序 |
| `values[]` | 一条 =（列引用，取值，`kind`）；按（列名、列引用、取值、`kind`）排序。`value` 是去引号的规范形式，`sql_literal` 是作者写的字面量 |
| `parameters[]` | `${…}` 变量与函数调用钉住的列：它们钉住这个列，但不是这个列的取值 |
| `overrides_applied` | 本次人工确认生效了多少条（`terms` / `values`）、多少条还空着没填（`blank`），以及哪些键在语料里没有对应项（`unmatched`） |

### 术语（terms[]）

| 键 | 含义 |
| --- | --- |
| `comments[]` | 同一段注释文本合并成一条，`tables[]` 是写了这段注释的表（去重后按名排序），`count` 是表数；按（表数降序、文本）排序 |
| `tables_total` | 语料里有这个列的表数（输入表与目标表都算，同一张表的不同 catalog 写法算一张） |
| `tables_without_comment[]` | 有这个列、但没写列注释的表——这是"待补注释"的清单 |
| `conflict` | 同一个列名有 ≥ 2 种不同注释文本时为 `true`；字典**并列保留两种说法**，不替作者裁决 |
| `meaning` | 人工确认的列含义；没人确认过时为 `null` |

### 值域观察（values[]）

`column_ref` 优先是物理列 `<db.table>.<column>`；**穿不透物理列时**写
`<scope_id>.<column>` 并带 `logical: true`——CTE id 不是表名，把它写在 `table` 位置等于
凭空造一张表。归属规则：该规则的 `fields[]` 里**恰好一个**同名列时才认物理表，
否则退到 scope 级（两张表都有 `status` 时，认哪一张都是猜）。

`sql_alias`（WI-B）只在**按 DDL 位置写入**且这条观察落在目标列上、而作者写的别名与该位置
列名不同、且那个别名是人写的（不是 `_col_N` 占位名）时出现，值为作者写的别名原文；判定与
`semantic.json` 的 `fields[].sql_alias`、`alias_position_mismatch` 是同一套。`glossary.md`
的列小节标题与待填模板的列小节标题都会跟着写「（SQL 别名 `<别名>`，按 DDL 位置写入）」——
否则读者在自己的 SQL 里搜不到这个列名。

`context` 词表（`observations[].context`）：

| 取值 | 来自哪里 |
| --- | --- |
| `filter_eq` / `filter_neq` | WHERE / HAVING 合取项 `col = 常量` / `col <> 常量` |
| `filter_in` | `col IN (…)`，列表里每个值一条，并互为 `closed_set` |
| `filter_rlike` | `col LIKE '模式'` / `col RLIKE '模式'`——**整个模式记成一条观察**，不拆 `|` 分支：拆开等于发明两个 SQL 从未比较过的值；这条观察的 `kind` 是 `pattern` 而不是 `literal` |
| `case_condition` | CASE 分支的 WHEN 条件里的 `col = 常量` |
| `case_then` | CASE 的 THEN / ELSE 常量，归到该 CASE **产出的那个列**。WI-C：各结果分支**不全是**标量常量时（`CASE WHEN gap > 0 THEN 0 ELSE gap END` 这类封顶），**数值**字面量分支是计算兜底而不是业务码，不记观察；同样情形下的**字符串**分支照记（`closed_set` 仍为 `null`）。分支全是常量时不受影响 |
| `union_constant` | UNION 某个分支里写死的投影常量，归到**该分支把它投影成的那一列**（见下） |
| `constant_projection` | 不在 UNION 分支里的投影常量，同样归到产生它的那一步的输出列 |
| `join_condition` | JOIN 的附加条件（`ON … AND d.rn = 1`） |

其余规则：

- `kind` 词表共四个：`literal`、`pattern`、`parameterized`、`function`。进 `values[]` 的
  只有前两个；`${…}` 变量（`parameterized`）与函数调用（`function`）不是取值，它们进
  `parameters[]`；列对列的比较（`a.x = b.y`）两边都不是常量，既不进 `values[]` 也不进
  `parameters[]`。
- `pattern`（WI-2.4b）是 `LIKE` / `RLIKE` 右边的匹配模式：`col LIKE '%UNIT_OUT_%'` 说的是
  这一列取值的**形状**，不是它取过的某个值。它仍然是一条关于该列的观察，所以留在
  `values[]` 里，但 `closed_set` 恒为 `null`，也不参与任何封闭集判定——把它跟枚举值并排
  列出来，等于替 SQL 说了它没说过的话。`LIKE '${prefix}%'` 仍然算 `parameterized`：
  「这是个替换」是关于它更要紧的那个事实。
- 取值以**去掉 SQL 引号的规范形式**入库：`value` 是 `PAID`，作者写的 `'PAID'` 留在
  `sql_literal` 里，谓词原文留在 `observations[].expression` 里。数值原样（`0` 就是 `0`）。
  一处写 `'0'`、另一处写 `0` 的同一个值因此归并成一条，`sql_literal` 取排序后的第一种写法。
  markdown 与 overrides 的键都跟着这条规则走：**展示用 `sql_literal`，键用 `value`**。
- **投影常量归属于「这一步把它投影成的那一列」**（WI-2.10 A）：字段链
  （`field_mapping_chains[].ordered_steps[]`）里的每个 `constant` 步都带一个 `output_field`
  （形如 `union:xxx:b01.data_source` 或 `<目标表>.<列>`），观察就记在这个列上。从这个输出列
  往下游走，**沿途每一步都是透传（`DIRECT` / `UNION`）**时，这个常量仍然就是目标列的取值，
  于是记成 `<目标表>.<列>`；中间只要有一步把它**消费**掉（聚合、算术、读它的 CASE），观察就
  停在产生它的那个 scope 级列上（`logical: true`）。
  反例是真实语料给的：`x = SUM(CASE WHEN data_source = 'contract' THEN amt END)` 的链里
  合法地含有 `'contract' AS data_source` 这一步——按链的**目标列**归属，会把
  `contract` / `inner` 发布成一个 `decimal` 金额列的取值。它们是 `data_source` 的取值。
- **声明类型守卫**（WI-2.10 A）：带引号的字面量只有在引号里的文本本身也是该类型时，才会落到
  声明为数值 / 日期的物理列上——`'Y'` 不是任何 `decimal(15,2)` 列取过的值。元数据没给类型的
  列一律放行：这一层不猜。同一条规则 describe 侧（`value_domain`）与字典采集侧共用。
- `NULL` 不作为取值发布（它是缺失，不是编码），但参与 CASE 的穷尽性判定：
  `ELSE NULL` 同样把分支集合闭上。
- `closed_set` 只在**整个语料对这一列的封闭断言唯一**时发布：两个任务给出不同的 `IN` 列表
  时写 `null`，因为互相矛盾的证据不构成封闭集。
- `meaning_candidates[]` 有两条路，一条注释按先命中的那条作答。候选注释来自三处：该列的列注释
  （`column_comment`，`column_details[]` 没有该列时退到 `declared_columns[]`）、该表的表注释
  （`table_comment`）、写在该条件/字段上的 SQL 注释（`sql_comment`）。
  1. **该列自己的注释把取值枚举出来了**（B6）：`0-未生效，1-生效` 这种写法是有人把码表写进了
     注释，属于这个取值的那一半就是候选，`text` 写这一半（`生效`），`source` 为
     `column_comment`，模板的「注释线索」列照写。分隔符认 `，,;；|/、` 与空格，码与含义之间认
     `-`、`:`、`=`、`：` 或一个空格；只读**该列自己的**注释（源表或目标表都算），与观察语境
     （`filter_eq` / `filter_in` / `case_condition` / `case_then` / `constant_projection` /
     `union_constant`）无关。只靠空格分隔的写法要**至少两对**才算码表——`队列编码，99 表示无效`
     是一句话，不是一张表。
  2. **注释文字里字面出现了这个值**：把值去掉引号后（不区分大小写）在注释文本里能找到才算。
     **长度小于 2 的值一律不匹配**——`0` 会出现在几乎任何一句话里，一个错误候选比十个漏掉的
     候选代价更大。
  两条都只产出**候选**：`glossary --template` 照样把这个取值列进待填表，候选不是确认。

### 参数化值（parameters[]）

`{column_ref, expression, kind, task_count}`，`kind` 取 `parameterized`（`${…}` 变量，
写在引号里的 `'${bizdate}'` 同样算）或 `function`（`date_sub(current_date(), 1)` 这类调用）。
`expression` 是去掉限定符与反引号后的谓词原文。

## overrides：人工确认怎么写回来

```json
{
  "terms": {
    "pay_status": {"meaning": "支付状态", "confirmed_by": "owner", "date": "2026-09-18"}
  },
  "values": {
    "ods.app_order.pay_status='PAID'": {"meaning": "已支付", "confirmed_by": "owner", "date": "2026-09-18"},
    "pay_status='REFUND'": {"meaning": "已退款"}
  }
}
```

| 规则 | 说明 |
| --- | --- |
| 键的两种写法 | 带表名（`ods.app_order.pay_status='PAID'`）只命中那一列；只带列名（`pay_status='PAID'`）命中语料里**所有**同名列 |
| 表名匹配 | 与字典内部一致：后缀匹配，`ods.t` 与 `catalog.ods.t` 是同一张表 |
| 值匹配 | 两边都做去引号后比较，`'PAID'` 与 `PAID` 是同一个值；**推荐写去引号的 `pay_status=PAID`**，与 `values[].value` 一致 |
| 合并优先级 | overrides 永远赢过候选：命中后 `meaning.source` 为 `override`，`meaning_candidates` 原样保留 |
| 没命中的键 | 进 `overrides_applied.unmatched`（排序后），**不静默丢弃**——一份被人工确认过的文件里的拼写错误，正是审阅者看不见的那一类 |

## 待填模板：`glossary --template`

画像的待确认清单从 15 条压到 **5 条**（WI-2.9）之后，"这个 code 是什么意思"不再逐条提问——
它本来也不是问题，是一张**表格**。`--template` 就生成这张表格：

```bash
scope-lineage glossary --lineage corpus --out dict \
  --template dict/glossary.overrides.template.md --template-top 20
# 业务方把含义写进 .md 与同名 .json，然后
scope-lineage glossary --lineage corpus --out dict --overrides dict/glossary.overrides.template.json
```

一个 `--template` 路径写两个文件：`.md` 是给人填的（一列一节，一取值一行），同名 `.json` 是
`--overrides` 直接读得回去的（`doc_format: "glossary-overrides-template/1"`，`values` 的键是
`<表.列>=<去引号取值>`，`meaning` 为空串，`date` 取当天）。两个文件问的是同一批取值。

`--template` 仍然需要 `--out`：模板是**对字典的一次排名**，不是字典的替代品。少给 `--out`
时命令以退出码 2 停下，并把这句理由一起打出来。

**哪些取值进模板**（其余一律不问，WI-2.10 B）：

| 规则 | 说明 |
| --- | --- |
| 只要 `kind = literal` | `pattern` 是 `LIKE` / `RLIKE` 的匹配形状，不是某个取值，没人能给它一个业务含义 |
| 只要物理列 | `logical: true`、或 `column_ref` 里带 `:` 的是 scope 级引用，写成 overrides 的键命不中任何列 |
| 排除开关 | `Y` / `N` / `yes` / `no` / `true` / `false`（不区分大小写）答的是「是或否」，读者本来就知道 |
| 排除裸数字 | `rn = 1`、`flag = 0` 是位置与开关；**即使落在已证明封闭的集合里也不问**（`IN (0, 1, 2)` 只是把位置钉在一个集合里） |
| 排除日期形字面量 | `'20260814'` 是实例日期，不是编码（见 semantic 文档的 `instance_date`） |
| 排除只剩一个取值的整列 | 一个取值不成编码体系，答完也说不出一个集合——这是「值不值得排进表单」而不是「不许问」，所以 `--template-top 0` 的不限量表单会把它们收回来（WI-D） |
| 排除已确认的取值 | `meaning` 已有文本的不再问第二遍 |

**排序与条数**：上一版按 `closed_set` 优先 + 观察数排，真实语料的第一页于是被 `Y`/`N`、`1`/`0`
与 scope 级列占满——上面那几条排除就是这个发现。现在按**列**排，列得分为

```
不同取值数 × 2 + Σ出现任务数 + 3×(有 filter_in) + 2×(有 case_then) + 2×(列注释含线索词)
```

线索词是 `编码`/`代码`/`类型`/`状态`/`标记`/`code`/`type`/`status`/`flag`。它只是**排序线索**，
永远不会变成某个取值的含义——「这列大概值得问」和「知道这列的某个值是什么意思」是两回事。
同分按列名定序，列内按出现任务数、观察数、取值拼写定序，所以同一份语料两次生成字节一致。
`--template-top` 仍然是**取值条数**上限（默认 20），截断可能落在一列中间，它前面的列是完整的；写 `0` 表示**不设上限**，把全部可问取值都问一遍——包括只剩一个取值的列。

**它没问什么也写在表头**：`generated.excluded_values` / `generated.excluded_scope_columns` 两个
计数，md 里是一行 `> 排除了 N 个开关/数字/日期型取值与 M 个 scope 级列。`——一张只问三列的表，
要让人分得清「语料里没别的」和「别的都被跳过了」。

**空着的条目不算答案**：整张表初始全空，填了一半就交回来是常态。`--overrides` 读到 `meaning`
为空串的键时**跳过并计入 `overrides_applied.blank`**，不会把它写成一条"含义是空字符串"的已确认
事实——"没人说过"和"有人说了空话"是两回事。

## 回写闭环：答案怎么回到字典与元数据

画像的第三件（待确认清单）每条都有一行「回写目标」，它就是分流依据。业务方答完之后：

```bash
# 1. 业务方在 business_profile.md 的每条待确认项里填 `- 答案：…`
# 2. 把答案分流成两份回写文件（--dry-run 只打印）
python3 skills/scope-lineage/scripts/confirmations.py apply <画像>/business_profile.md \
  --by owner --overrides dict/glossary.overrides.json --patch dict/metadata-patch.json

# 3. 重跑字典与画像，已确认项就不再是问题
scope-lineage glossary --lineage corpus --out dict --overrides dict/glossary.overrides.json
scope-lineage describe --lineage corpus --glossary dict/glossary.json \
  --metadata-patch dict/metadata-patch.json
```

| 回写目标 | 去哪个文件 | 写成什么 |
| --- | --- | --- |
| `术语:<词>` | `glossary.overrides.json` | `terms["<词>"] = {meaning, confirmed_by, date}` |
| `值域:<列>=<值>` | `glossary.overrides.json` | `values["<列>=<值>"] = {meaning, confirmed_by, date}` |
| `字段注释:<表.列>` | `metadata-patch.json` | `columns["<表.列>"] = {comment, confirmed_by, date}` |
| `表注释:<表>` | `metadata-patch.json` | `tables["<表>"] = {table_name_cn, confirmed_by, date}` |

脚本的规则：

- **合并不覆盖**：目标文件里已经有的键原样保留并计入 `kept_existing`——两个人各答一轮，谁都
  不会把对方的答案抹掉；
- **没填的跳过并计数**：`- 答案：（待填）`、空答案、或整条没有答案行时计入 `unanswered`，
  一个没人答的问题不是一个空答案；
- **回写目标没填成四选一的跳过并计数**（`no_target`）：模板里四种并列的那一行原样留着等于没填，
  猜一种等于把答案写进错误的文件；
- `--by` 记在每条的 `confirmed_by`，`date` 默认取当天，可用 `--date` 指定；
- 没有任何条目要写时**不创建空文件**——一个空文件读起来像"所有确认都被清空了"。

下一轮的画像里，这些项在骨架里就是已确认的事实，prompt 要求**不再为它们生成 `Q`**：

| 骨架键 | 由谁填 | 含义 |
| --- | --- | --- |
| `fields[].value_domain[].meaning.status = "confirmed"` | `glossary --overrides` | 这个取值的含义已确认 |
| `fields[].target_comment_source = "patch"` | `describe --metadata-patch` | 目标字段注释来自确认回写 |
| `inputs[].comment_source = "patch"` | 同上 | 输入表中文名来自确认回写 |
| `confidence.confirmations` | 两者 | `{values_confirmed, terms_confirmed, columns_patched, tables_patched}` 四类已确认项的计数 |

补丁文件本身的格式、匹配规则与 `parse --metadata-patch`，见
[Core 输入格式](input-formats.md)。

## describe 消费：fields[].value_domain

`describe` 永远发布 `fields[].value_domain`，**不传 `--glossary` 也发**——那时它只含
这一条语句自己证明的取值，每条 `meaning` 都是 `null`（一条语句不可能知道一个值的含义）。
传了 `--glossary` 才会换成语料级的观察，并带上人工确认的含义。

`--glossary` 指向的文件不存在或不是合法 JSON（退出码 2）、或没有声明 `doc_format:
"glossary-json/1"`（退出码 1）时直接报错，与 `--tables` 同一口径：两者都是 JSON 对象，
把 `glossary.overrides.json` 误传成 `--glossary` 过去会被静默接受，结果是一份取值全空的
文档——它读起来和"语料里什么都没观察到"一模一样。

```jsonc
"value_domain": [
  {"value": "PAID", "sql_literal": "'PAID'", "kind": "literal",
   "seen_in": ["rule:003", "mc:004"], "closed_set": true, "meaning": {"text": "已支付", "status": "confirmed"}},
  {"value": "REFUND", "sql_literal": "'REFUND'", "kind": "literal",
   "seen_in": ["rule:003"], "closed_set": true, "meaning": {"text": "支付状态，REFUND 表示已退款", "status": "candidate"}},
  {"value": "%UNIT_OUT_%", "sql_literal": "'%UNIT_OUT_%'", "kind": "pattern",
   "seen_in": ["rule:007"], "closed_set": null, "meaning": null}
]
```

| 规则 | 说明 |
| --- | --- |
| 何时出现 | 只在非空时出现；这个字段没有任何取值观察时不写该键 |
| 一个值一条 | 按（`value`、`kind`）去重：同一个值被多条观察证明（两个 CASE 分支、两个分支 scope）只写一条，证据合并进 `seen_in`（去重保序）。字段的取值是一个**集合**，出现次数属于 `seen_in` |
| 条目顺序 | 按**首次出现顺序**，不重排 |
| `kind` | `literal`（枚举值）或 `pattern`（`LIKE` / `RLIKE` 的匹配模式）；`pattern` 的 `closed_set` 恒为 `null`，且不参与封闭集判定，也不进 `summary` 追加 |
| 按来源列匹配 | 只在**整条链每一步**都是 `DIRECT` / `UNION` 时（字段自己的 `transform` 与该来源的 `sources[].transform` 都要是，任一步非透传即断），才继承来源物理列的取值；继承的也只有该列被 `=` / `IN` 钉住的观察与 `LIKE` / `RLIKE` 的匹配形状。`CASE WHEN pay_status = 'PAID' THEN 'Y' ELSE 'N' END` 读了 `pay_status`，但 `'PAID'` 绝不是 `paid_flag` 的取值 |
| 按目标表 + 列名匹配 | `case_then` / `union_constant` / `constant_projection` 三种观察按**目标表（点号后缀归一）+ 列名**匹配，CASE 产出的枚举因此能落到同名目标字段上；只按列名匹配会让任何任务写进 `status` 的标签变成所有 `status` 的取值，而 `mart.orders.status` 的枚举与 `mart.tickets.status` 无关。落在某个 scope 上、没有进到具名目标列的观察（CTE 里的 CASE）不属于任何表，仍然只对本语句自己的同名字段说话 |
| 类型护栏 | 目标列声明为数值（`decimal` / `int` / `bigint` / `double` …）或日期（`date` / `timestamp`）时，只接受同类型字面量：引号里的 `'Y'` 不会挂到金额列，引号里的 `'0'` / `'2026-01-01'` 仍然算 |
| `closed_set` | `true` 表示这个取值属于一个已被证明封闭的集合；`null` 表示**未证明封闭**，不表示"证明了不封闭"。这是**整列**的结论：同一字段的每条取值要么都是 `true`、要么都是 `null`。为 `true` 的两种证明——该列自己的末步 CASE 穷尽（带 ELSE 且各分支全是常量），或透传来源列存在封闭的 `IN` 列表 |
| `sql_literal` | 作者写的字面量。`semantic.md` 的 `- 取值：` 行显示它，`value_domain[].value` 与 overrides 的键用去引号形式 |
| `meaning.status` | `confirmed`（人工确认）或 `candidate`（注释字面命中） |
| `summary` 追加 | 只有**已确认**含义才会追加到那句话尾部（`；取值：'PAID'（已支付）`，最多 3 个）：候选是"某条注释里恰好出现了这个值"，写进读者会停下来读的那一句等于把它当成定义 |
| `confidence.metadata_coverage.glossary` | `{values_total, confirmed, candidate, rule_values_total, rule_values_confirmed, field_values_total, field_values_confirmed, enumerable_total, enumerable_confirmed}`；这条语句一个取值观察都没有时不写该键。`values_total` 是**字段取值 ∪ 规则引用取值**去重后的总数，按 `(列名, 取值, kind)` 归一——同一个 code 被 `WHERE` 钉住又原样带进同名输出列，是读者要答的**一个**问题而不是两个；`confirmed` / `candidate` 是同一并集上的计数。`enumerable_total` 把这个并集收窄到**能被人认领含义的 code**，画像生成记录「来源标签与证据」一节的覆盖率按它算（`enumerable_confirmed / enumerable_total`）：物理列上的 literal、上下文含 `filter_eq` / `filter_in` / `case_then` / `union_constant` / `constant_projection`、不是日期形，且纯数字还要额外出现在 `IN` 列表、CASE 标签或常量投影里而不是只被 `=` 钉过一次。跑批日期与 `= 0` 这类守卫是观察到的取值，但没有人会去确认它们，把它们计入分母会让这个覆盖率永远像不及格 |

`semantic.md` 第 5 节的字段小节里多一行 `- 取值：`，已确认写含义、候选写 `? `、都没有写
「待确认」；整列**枚举值**都封闭时追加「（该列取值已被 SQL 证明封闭）」——因为 `closed_set`
是整列的结论，这句话不会再出现「同一列有的值封闭、有的值不封闭」的情况。行尾的 `SQL事实`
标签只为取值本身背书——含义不是 SQL 事实，所以它的三态标记写在值里面。

这一行还有两条 WI-2.4b 的约束：

- 最多列 12 个枚举值，超过时写「等 N 个，完整见 semantic.json value_domain」——这一行是
  摘要，`semantic.json` 才是记录；
- `pattern` 不与枚举值并列，单独排在行尾的「匹配模式：…」里，且不带「待确认」标记
  （一个匹配形状不是等着谁去确认业务含义的编码）。

### 规则与术语层：`rules[].value_meanings` 与 `term_meaning`（WI-2.12）

仓库的业务码多数不在输出字段上，而在 `WHERE queue_code IN ('01','07')`、连接的附加条件、
CASE 的**条件**里。`value_domain` 只挂在输出列上，所以语料把十七个 code 全确认了，任务文档
仍然只有四个字段受益——含义没有被送到写着这个 code 的那一行。传了 `--glossary` 之后：

| 落点 | 内容 |
| --- | --- |
| `rules[].value_meanings[]` | 这条规则把列钉住的每个 code，`{column_ref, value, sql_literal, meaning}`。只收 `=` / `IN` / `<>` 与 CASE **条件**的常量；`LIKE` / `RLIKE` 的匹配模式不是业务码，连接键比较的是两列。按 `(column_ref, value)` 去重、按规则写出的顺序排列，没人回答时 `meaning` 为 `null`——被省略的不是问题，而是答案 |
| 归属怎么算 | 与字典收集端同一套规则：规则的 `fields[]` 里恰好一列同名才写物理表名（复用 `values[]` 的按列索引与点号后缀归一），否则写 scope 级引用。scope 级引用**只认本任务观察到的条目**：`cte.flag` 在另一个任务里是另一个 CTE，只是恰好同名 |
| `inputs[].used_columns[].term_meaning` | 字典 `terms[]` 里**已人工确认**的该列名含义 `{text, status}`，与该列自己的 `comment` 并排 |
| `fields[].term_meaning` | 同样的 `{text, status}`，但只在该字段 `target_comment` **为空**时出现：术语不是注释，填进注释槽位等于发布一条元数据里没有的注释 |
| `confidence.confirmations.rule_values_confirmed` | 规则层被确认的 code 数，与字段层的 `values_confirmed` 分开计 |

`semantic.md` 里三处相应变化：第 3 节过滤 / 关联的复述末尾追加「（取值：'01'＝人工队列）」
（只列已答的，超过 3 个写「等 N 个，见规则表」）；第 4 节规则表在「条件」后多一列「取值含义」
（一条都没答过时整列不出现）；第 5 节字段小节在 `- 目标注释：` 后多一行 `- 术语：…（人工确认）`，
「完整字段清单」相应多一列「术语」。

## glossary.md 的章节

一个列名一节（`## <列名>`），节内依次是：术语行（注释集合、`⚠` 冲突提示、缺注释的表、
列含义）、值域表（值 / 列引用 / 种类 / 出现任务数 / 上下文 / 封闭集 / 含义）、参数化值行。
既没有列注释也没有被任何常量比较过的列名，只在末尾的「其余列」里记一次名字。

同输入同字节：文档不含时间戳，所有列表与表格都按稳定键排序，语料读入顺序不影响结果。

## 不做的事

- 不给字段起中文名，不猜 code 的含义，不把观察到的值集合说成完整枚举；
- 不接数据库取样例值；
- 不替作者裁决注释冲突——两种说法并列，由人回答。
