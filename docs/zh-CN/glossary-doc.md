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
  `meaning_candidates` 是"某条注释的文字里**字面出现**了这个值"，是线索不是结论。
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
     "value": "'PAID'", "kind": "literal",
     "observations": [{"task": "order_daily", "statement_id": "stmt:001",
                       "context": "filter_eq", "evidence": "rule:003",
                       "expression": "pay_status = 'PAID'"}],
     "task_count": 2,
     "closed_set": {"values": ["'PAID'", "'REFUND'"], "basis": "in_list"},
     "meaning_candidates": [{"text": "支付状态，PAID 表示已结算", "source": "column_comment",
                             "evidence": "column:ods.app_order.pay_status"}],
     "meaning": {"text": "已支付", "source": "override",
                 "confirmed_by": "owner", "date": "2026-09-18"}},
    {"column_ref": "cte:latest_dim.rn", "logical": true, "column": "rn",
     "value": "1", "kind": "literal",
     "observations": [{"task": "…", "statement_id": "stmt:001",
                       "context": "join_condition", "evidence": "rule:002",
                       "expression": "rn = 1"}],
     "task_count": 1, "closed_set": null, "meaning_candidates": [], "meaning": null}
  ],
  "parameters": [{"column_ref": "ods.app_order.dt", "expression": "dt = '${bizdate}'",
                  "kind": "parameterized", "task_count": 6}],
  "overrides_applied": {"terms": 1, "values": 2, "unmatched": ["pay_status='GONE'"]}
}
```

| 键 | 内容 |
| --- | --- |
| `corpus` | 扫了什么：`artifact_root` 原样记录、任务数、写语句数、每个任务的契约摘要（与 mapping.md / semantic.md 用的是同一个 digest 函数，可据此确认字典与画像来自同一快照） |
| `terms[]` | 按**列名**跨表归并的注释；一个列名一条，按列名排序 |
| `values[]` | 一条 =（列引用，取值，`kind`）；按（列名、列引用、取值、`kind`）排序 |
| `parameters[]` | `${…}` 变量与函数调用钉住的列：它们钉住这个列，但不是这个列的取值 |
| `overrides_applied` | 本次人工确认生效了多少条，以及哪些键在语料里没有对应项 |

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

`context` 词表（`observations[].context`）：

| 取值 | 来自哪里 |
| --- | --- |
| `filter_eq` / `filter_neq` | WHERE / HAVING 合取项 `col = 常量` / `col <> 常量` |
| `filter_in` | `col IN (…)`，列表里每个值一条，并互为 `closed_set` |
| `filter_rlike` | `col LIKE '模式'` / `col RLIKE '模式'`——**整个模式记成一条观察**，不拆 `|` 分支：拆开等于发明两个 SQL 从未比较过的值；这条观察的 `kind` 是 `pattern` 而不是 `literal` |
| `case_condition` | CASE 分支的 WHEN 条件里的 `col = 常量` |
| `case_then` | CASE 的 THEN / ELSE 常量，归到该 CASE **产出的那个列** |
| `union_constant` | UNION 某个分支里写死的投影常量，归到目标列 |
| `constant_projection` | 不在 UNION 分支里的投影常量，归到目标列 |
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
- `NULL` 不作为取值发布（它是缺失，不是编码），但参与 CASE 的穷尽性判定：
  `ELSE NULL` 同样把分支集合闭上。
- `closed_set` 只在**整个语料对这一列的封闭断言唯一**时发布：两个任务给出不同的 `IN` 列表
  时写 `null`，因为互相矛盾的证据不构成封闭集。
- `meaning_candidates[]` 只做**字面匹配**：把值去掉引号后（不区分大小写）在注释文本里能找到
  才算。候选注释来自三处：该列的列注释（`column_comment`）、该表的表注释（`table_comment`）、
  写在该条件/字段上的 SQL 注释（`sql_comment`）。**长度小于 2 的值一律不匹配**——
  `0` 会出现在几乎任何一句话里，一个错误候选比十个漏掉的候选代价更大。

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
| 值匹配 | 去引号后比较，`'PAID'` 与 `PAID` 是同一个值 |
| 合并优先级 | overrides 永远赢过候选：命中后 `meaning.source` 为 `override`，`meaning_candidates` 原样保留 |
| 没命中的键 | 进 `overrides_applied.unmatched`（排序后），**不静默丢弃**——一份被人工确认过的文件里的拼写错误，正是审阅者看不见的那一类 |

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

```jsonc
"value_domain": [
  {"value": "'PAID'", "kind": "literal", "seen_in": ["rule:003", "mc:004"],
   "closed_set": true, "meaning": {"text": "已支付", "status": "confirmed"}},
  {"value": "'REFUND'", "kind": "literal", "seen_in": ["rule:003"],
   "closed_set": true, "meaning": {"text": "支付状态，REFUND 表示已退款", "status": "candidate"}},
  {"value": "'%UNIT_OUT_%'", "kind": "pattern", "seen_in": ["rule:007"],
   "closed_set": null, "meaning": null}
]
```

| 规则 | 说明 |
| --- | --- |
| 何时出现 | 只在非空时出现；这个字段没有任何取值观察时不写该键 |
| 一个值一条 | 按（`value`、`kind`）去重：同一个值被多条观察证明（两个 CASE 分支、两个分支 scope）只写一条，证据合并进 `seen_in`（去重保序）。字段的取值是一个**集合**，出现次数属于 `seen_in` |
| 条目顺序 | 按**首次出现顺序**，不重排 |
| `kind` | `literal`（枚举值）或 `pattern`（`LIKE` / `RLIKE` 的匹配模式）；`pattern` 的 `closed_set` 恒为 `null`，且不参与封闭集判定，也不进 `summary` 追加 |
| 按来源列匹配 | 只在字段的末步变换是 `DIRECT` / `UNION`（值原样传到目标）时，才继承来源物理列的取值——`CASE WHEN pay_status = 'PAID' THEN 'Y' ELSE 'N' END` 读了 `pay_status`，但 `'PAID'` 绝不是 `paid_flag` 的取值 |
| 按目标列名匹配 | `case_then` / `union_constant` / `constant_projection` 三种观察按**列名**匹配，CASE 产出的枚举因此能落到同名目标字段上 |
| `closed_set` | `true` 表示这个取值属于一个已被证明封闭的集合；`null` 表示**未证明封闭**，不表示"证明了不封闭" |
| `meaning.status` | `confirmed`（人工确认）或 `candidate`（注释字面命中） |
| `summary` 追加 | 只有**已确认**含义才会追加到那句话尾部（`；取值：'PAID'（已支付）`，最多 3 个）：候选是"某条注释里恰好出现了这个值"，写进读者会停下来读的那一句等于把它当成定义 |
| `confidence.metadata_coverage.glossary` | `{values_total, confirmed, candidate}`；这条语句一个取值观察都没有时不写该键 |

`semantic.md` 第 5 节的字段小节里多一行 `- 取值：`，已确认写含义、候选写 `? `、都没有写
「待确认」；整列**枚举值**都封闭时追加「（该列取值已被 SQL 证明封闭）」。行尾的 `SQL事实`
标签只为取值本身背书——含义不是 SQL 事实，所以它的三态标记写在值里面。

这一行还有两条 WI-2.4b 的约束：

- 最多列 12 个枚举值，超过时写「等 N 个，完整见 semantic.json value_domain」——这一行是
  摘要，`semantic.json` 才是记录；
- `pattern` 不与枚举值并列，单独排在行尾的「匹配模式：…」里，且不带「待确认」标记
  （一个匹配形状不是等着谁去确认业务含义的编码）。

## glossary.md 的章节

一个列名一节（`## <列名>`），节内依次是：术语行（注释集合、`⚠` 冲突提示、缺注释的表、
列含义）、值域表（值 / 列引用 / 种类 / 出现任务数 / 上下文 / 封闭集 / 含义）、参数化值行。
既没有列注释也没有被任何常量比较过的列名，只在末尾的「其余列」里记一次名字。

同输入同字节：文档不含时间戳，所有列表与表格都按稳定键排序，语料读入顺序不影响结果。

## 不做的事

- 不给字段起中文名，不猜 code 的含义，不把观察到的值集合说成完整枚举；
- 不接数据库取样例值；
- 不替作者裁决注释冲突——两种说法并列，由人回答。
