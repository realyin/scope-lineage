# 目录片段提示词：为一组概念补属性、码值、表现与列绑定

给「表语义 → 目录」流程里**每组一个**的子代理用（流程见 `SKILL.md` 的
「"从表语义起草本体目录" — drafting procedure (digest → fragments → merge)」一节）。
编排者把下面的 `<…>` 换成实际路径和组名后，连同分配一起交给子代理。

你负责一个 group：`<group>`。只处理这个 group 的概念和分配给它的表。**自己完成，不许分派或等待其他代理。**

## 读什么

- 目录格式：`docs/zh-CN/ontology-catalog.md`（「元素」「表现与绑定」「起草」三节），示例
  `examples/catalog-demo/`（`mapping/party.yaml`、`concepts/*.yaml`、`code_sets.yaml` 的形状照抄）与
  `examples/catalog-fragments/disbursement.json`（片段的形状照抄）。示例目录用 YAML 写；目录文件也可以是
  `.json`（可以全是 JSON），条目形状不变，下文只写文件名主干（`identifiers`、`code_sets`、`mapping/<group>`）。
- 当前目录（只读）：`<catalog-dir>`。概念、标识符、关系已经起草好；不要改它，只写片段。片段不能新增概念，
  也不能改已有标识符（包括给它加拼写）：缺概念、缺事件的时间属性、已有标识符缺拼写时，写进 `notes` 并告诉
  编排者，不要绕开。
- 分配（编排者给出）：本组的概念 id 列表；分给本组的表，以及每张表初拟的概念、表现类型、粒度、时间语义。
  只有一组、分配没写这些时，由你来定，并在 `notes` 里说明。
- 起草材料：`<digest-dir>/digest.md`（`catalog digest` 的输出）里本组的表。
- 每张表的语义：`<docs-dir>/<db.table>.json`（`table-semantics/1`）。列的含义、码值、加工口径以它为准；
  只有它说不清时才看材料包 `<packets-dir>/<db.table>/packet.md`。

## 写什么

只写一个文件：`<fragments-dir>/<group>.json`，格式 `catalog-fragment/1`：

```json
{
  "doc_format": "catalog-fragment/1",
  "group": "<group>",
  "attributes": {
    "concept:<id>": [
      {"id": "attr:<concept slug>.<slug>", "name": "中文名", "definition": "一句话",
       "category": "descriptive|state|measure|time", "type": "string|decimal(18,2)|...",
       "unit": "可选", "code_set": "可选 code:<slug>", "derivation": "可选，跨表一致的口径",
       "status": "drafted", "source": "comment|sql|mixed|llm", "evidence": ["库.表.列"]}
    ]
  },
  "code_sets": [
    {"id": "code:<slug>", "name": "中文名", "values": [{"value": "...", "meaning": "..."}],
     "status": "drafted", "source": "comment|sql", "evidence": ["库.表.列"]},
    {"id": "code:<slug>", "name": "码值在码值表里的码值集", "values": [],
     "lookup": {"table": "库.码值表", "code_column": "码列",
                "meaning_columns": [{"column": "中文含义列", "lang": "zh"}],
                "key_column": "可选，代理键列", "filter": {"类型列": "区分本码值集的字面量"},
                "valid_from": "可选，与 valid_to 成对", "valid_to": "可选"},
     "status": "drafted", "source": "sql", "evidence": ["任务名或 SQL 线索"]}
  ],
  "identifiers": [],
  "constraints": [],
  "terms": [{"term": "...", "refers_to": "attr:...|concept:...", "preferred": false}],
  "representations": [
    {"table": "库.表", "concept": "concept:<id>",
     "kind": "core|extension|dependent|event_detail|state_history|identifier_map|role_view|summary|intermediate",
     "grain": {"identifiers": ["id:..."], "extra": ["文字"], "source": "declared|inferred|proven"},
     "time": "snapshot|incremental|zipper|unknown", "refresh": "daily",
     "scope": ["记录范围的业务说法"], "table_status": "active|deprecated",
     "bindings": [
       {"column": "列", "to": "attribute|identifier|foreign_identifier|foreign_attribute|technical|unmapped",
        "ref": "attr:...|id:...", "derivation": "可选，本表特有口径", "code_map": {"值": "含义"},
        "code_sets": ["可选，按查找顺序 code:a", "code:b"]}
     ],
     "status": "drafted", "source": "mixed", "evidence": ["任务名或 SQL 线索"]}
  ],
  "notes": ["给 owner 的问题或冲突，最多 8 条"]
}
```

每个条目的形状与目录文件里的完全相同（字段、枚举、必填项都一样）；不认识的键会让片段不合 schema。
`identifiers` 只在必须新增标识符时写，形状同目录 `identifiers` 文件里的条目；`constraints` 只写有证据的
属性级约束（值域、必填、派生、业务规则），形状同 `constraints` 文件里的条目；不需要的列表可以省略。合并时新表现
进 `mapping/<group>`，其余条目进同名的顶层文件：已有的文件保持原格式，新建的文件与 `catalog.*` 同格式。

## 规则

- **属性是业务属性，不是列。**同一业务含义在多张表、多个列名出现，只建一个属性，多列绑定到它。id 用英文
  slug，名称用中文。先查当前目录里这个概念已有的属性，有就复用，不要换个 id 重建。
- **每张表的每一列都要有 binding。**
  - `attribute`：ref 必须是本表概念的属性（`role_view` 可以用承担者的属性和标识符）；
  - `identifier`：必须是本概念的标识符；
  - `foreign_identifier`：必须是别的概念已有的标识符（在目录的 `identifiers` 文件里找，确实缺才在片段里新增）；
  - `foreign_attribute`：冗余存放的别的概念的属性，`via` 写本表里作为外部标识符绑定的那一列；
  - `dt`、`etl_time`、来源库标记等是 `technical`；
  - 实在判断不了才 `unmapped`，并在 `notes` 里说为什么。
- 本表特有的加工口径写在 binding 的 `derivation`；码值写成可复用的 `code_set`，或本表特有的 `code_map`。
  `code_map` 里含义没确认的值，含义以「待确认：」开头（页面原样显示这个前缀）。
- 一个码和它的描述列是**同一个属性**（描述是码的展示），两列都绑到它；同一角色的 id、登录名、姓名是三个属性。
- 员工、经办人、客户经理这类「某角色的人」的列，目录里没有人员概念时，按目录已有先例绑成本概念的属性，
  并在 `notes` 里列为候选概念。
- 状态类、代码类属性尽量挂 `code_set`。码值只来自注释、SQL 的 CASE 或表语义的 `code_values`，不要编；含义
  没确认的值写 `"unconfirmed": true`，或让 `meaning` 以「待确认」开头。
- **码值表（字典表）不写表现。**只存码与含义、按类型列区分多套码的表不是概念：为 SQL 里每个
  `JOIN 码值表 ON … AND 类型列 = '…'` 的类型写一个码值集，`values` 留空，写 `lookup`（`filter` 就是那个
  `类型列 = '…'` 的字面量，不要编）。本组的列查码值表时，在 binding 上写 `code_sets`；
  `coalesce(g1.含义, g2.含义)` 这样按顺序回退的，`code_sets` 的顺序与 SQL 一致；所绑属性的 `code_set` 要在其中。
  先 `substr(...)` 再查、或经映射表两步翻译的，`lookup` 表达不了，写进 binding 的 `derivation`。
  `lookup` 只指物理码表（`库.表`）：字典定义在任务内（`VALUES` CTE、`CASE` 映射、字面量列表）时，把码写成码值集的
  `values`，`evidence` 写生产它的任务名，不要给 CTE 起名当 `lookup.table`（会让 `catalog query table` 为不存在的表作答）。
- 表现的 `kind`、`grain`、`time` 以分配为起点，可以按表语义修正，修正要在 `notes` 里说明。
- 表语义里的 `watch`（冲突、弃用）与未回答的问题，挑与目录有关的写进 `notes`。
- 不写人名、邮箱；不把 SQL 原文整段抄进 `derivation`。

## 自检

```bash
scope-lineage catalog merge <catalog-dir> <fragments-dir>/<group>.json --out <scratch-dir>/check-<group>
```

`--out` 必须是新目录或空目录；再跑一次时先删掉它或换个名字。`merge` 自动对合并结果跑 `catalog validate`，
也可以单独再跑 `scope-lineage catalog validate <scratch-dir>/check-<group>`。改到退出码为 0：

- `conflict`：同一个 id（或同一张表）已经存在且内容不同。复用已有的条目，或换一个真正不同的 id；不要改已有的。
- `unknown_concept`：属性挂到了目录里没有的概念上。只用分配给本组的概念。
- 校验 `error`：按消息改片段里对应的条目。
- 覆盖报告里 `unmapped` 要尽量少；每张分配给你的表都要有表现。

完成后回复：属性数、码值集数、表现数、binding 数（按 `to` 分类）、unmapped 列数、notes。
