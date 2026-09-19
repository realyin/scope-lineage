[English](../en/ontology-doc.md) | 中文

# ontology.json / ontology.md 语料级本体候选（ontology-json/1）

`scope-lineage ontology` 扫描一棵语料目录下的所有 `lineage.json`，在
[表卡](tables-doc.md) 与[值词典](glossary-doc.md)之上再回答一个单表回答不了的问题——
**这些表之间是什么关系**：实体（表 + 身份键）、属性（列 + 注释 + 观察到的角色 + 同义列）、
关系（JOIN 键对 + 可证明的基数）、约束（非空 / 枚举 / 每键唯一 / 分区）、以及跨任务的矛盾。

语料里每一个 JOIN 都是一句关于两个实体及其键的断言；每一次「先按 k 去重再关联」都是一句
关于那张表按 k 有多行的断言；每一个封闭 `IN` 列表都是一句关于列值域的断言。本产物把这些
断言收集起来，逐条标注置信层级与证据。

## 定位：本体**候选**，不是业务本体

- 每条断言都带 `tier` 与 `evidence`，可按任务名、`statement_id`、`logic_block_id` 回链到
  某个具体语句；没有证据的断言根本不会被发布。
- Core 不给实体起业务名、不判断类型、不推断父子类。`naming_hints` 只放元数据事实
  （表注释、业务域、项目、负责人），命名与建模交给懂业务的人或 Agent 确认。
- 槽位刻意对齐常见本体语言（entity ~ owl:Class、attribute ~ owl:DatatypeProperty、
  relation ~ owl:ObjectProperty、constraint ~ sh:NodeShape），一期不产 OWL/SHACL/LinkML 文件。
- 稳定性分级与其他派生文档一致：`ontology-json/1` 内键名稳定，中文措辞可能微调，
  机器应读 JSON 而不是 Markdown。

## 用法

```bash
# 语料目录：递归查找 lineage.json，产物写到 --out
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology

# 复用已经算好的表卡与值词典（不给就在内存里按同一份语料现场构建）
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology \
  --tables /path/to/tables/tables.json --glossary /path/to/glossary/glossary.json
```

产物两件：

| 文件 | 给谁读 | 内容 |
| --- | --- | --- |
| `ontology.json` | 机器 / RAG / 知识图谱入库 | 主产物，`doc_format: "ontology-json/1"` |
| `ontology.md` | 人 | 索引：实体数 / 关系数 / 约束数 / 发现数 + 关系表 + 待人工判定清单 |

Python API（消费契约文档，与文件写出同一条路径）：

```python
from scope_lineage import build_ontology, build_semantic_profile
from scope_lineage import render_ontology_index_markdown

profiles = [build_semantic_profile(document) for document in documents]
ontology = build_ontology(documents, profiles, artifact_root="/path/to/corpus")
index = render_ontology_index_markdown(ontology)
```

- `--lineage` 与 `tables` / `glossary` 完全一致：一个 `lineage.json` 或一棵递归查找它的目录树；
  版本不认识的文档在目录模式下跳过并计数。
- `--tables` / `--glossary` 只是省一次重算：给与不给产出字节一致。
- `--format` 取 `json`、`md` 或两者（默认 `json,md`）；其他值直接报参数错误（退出码 2）。
- 确定性：同一份语料无论以什么顺序被扫描，产出字节一致。

## 置信四级

| 层级 | 定义 | 例 |
| --- | --- | --- |
| `proven` | SQL 里直接写着 | 连接键对存在；分区列；生产任务已证明的键；DIRECT 重命名 |
| `implied` | 由结构可证明的推论 | 任务在 JOIN 前按 k 去重 → 那张表按 k 有多行（否则作者不会去重）；UNION 列对齐 |
| `hypothesis` | 作者假设，未被 SQL 证明 | 直接以 k 关联物理表 → 假设它按 k 唯一；过滤里出现过的取值集合是否完整 |
| `conflict` | 跨任务证据矛盾 | T1 按 k 去重、T2 直接按 k 关联同一张表——这是治理发现，不是本体事实 |

## ontology.json 结构

```jsonc
{
  "doc_format": "ontology-json/1",
  "corpus": {"artifact_root": "…", "task_count": 12, "lineage_digests": {"task_a": "…"}},
  "entities": [
    {"id": "ods.customer", "kind": "physical_table",
     "comment": null,
     "identity": {
       "candidate_keys": [{"columns": ["id"], "tier": "hypothesis",
                           "evidence": [{"task": "task_a", "statement_id": "stmt:001",
                                         "kind": "joined_as_right_without_dedup",
                                         "logic_block_id": "logic:ROOT:join:001"}]}],
       "multiplicity": [{"columns": ["driver_id"], "tier": "implied",
                         "claim": "multiple_rows_per_key", "evidence": [{"kind": "group_by"}]}],
       "partition_columns": ["dt"]},
     "attributes": [
       {"column": "state", "type": "string", "comment": null,
        "observed_roles": ["filter", "output"], "not_null_observed": false,
        "synonyms": [{"entity": "mart.t", "column": "order_state", "tier": "proven",
                      "via": "direct_rename", "evidence": [{"task": "task_a"}]}]}],
     "naming_hints": {"table_comment": null, "domain": null, "project": null, "owner": null}}
  ],
  "relations": [
    {"id": "rel:001",
     "from": {"entity": "ods.driver", "columns": ["id"]},
     "to": {"entity": "ods.pay", "columns": ["driver_id"]},
     "kind": "join_association",
     "cardinality": {"claim": "one_to_many", "tier": "implied", "basis": "group_by"},
     "join_types": ["LEFT_OUTER"], "task_count": 1,
     "evidence": [{"task": "task_a", "statement_id": "stmt:001",
                   "scope_id": "ROOT", "logic_block_id": "logic:ROOT:join:001"}]}
  ],
  "constraints": [
    {"target": {"entity": "ods.orders", "column": "state"}, "kind": "in_set",
     "tier": "proven", "values": ["NEW", "PAID"], "completeness": "complete",
     "evidence": [{"task": "task_a", "statement_id": "stmt:001", "context": "filter_in"}]}
  ],
  "findings": [
    {"kind": "cardinality_conflict", "entity": "ods.pay", "columns": ["driver_id"],
     "tasks": {"multiple_rows_per_key": ["task_a"], "assumed_unique": ["task_b"]},
     "text": "…"}
  ]
}
```

槽位说明：

| 槽位 | 取值 | 含义 |
| --- | --- | --- |
| `entities[].kind` | `physical_table` / `produced_table` | 语料内有生产任务的是 `produced_table` |
| `entities[].identity.candidate_keys[]` | `columns` + `tier` + `evidence` | 生产任务证明的键（`producer_key_confidence`）与消费任务假设的键（`joined_as_right_without_dedup`）并列，不合并成「主键」 |
| `entities[].identity.multiplicity[]` | `claim: multiple_rows_per_key` | O3：某任务按这组键对该表做过 GROUP BY 或窗口 partition |
| `entities[].attributes[].observed_roles` | `filter`、`partition_filter`、`join_key`、`group_by`、`window_partition`、`window_order`、`output` | 表卡记录的消费用法，没人读过的列是空列表 |
| `entities[].attributes[].synonyms[].via` | `direct_rename` / `union_alignment` | O5：同一个值的两个列名 |
| `relations[].kind` | `join_association` / `union_sibling` | JOIN 键对，或同一 UNION 的兄弟分支 |
| `relations[].cardinality.claim` | `one_to_many` / `many_to_one` / `many_to_one_assumed` / `unknown` | O2，方向为 `from` → `to` |
| `relations[].cardinality.basis` | `group_by` / `ranking_window` / `producer_key_confidence` / `right_side_not_deduplicated` / `union_branch_alignment` / `no_uniqueness_evidence` | 该基数断言的依据 |
| `relations[].evidence[].left_via_scopes` | scope id 列表 | JOIN 某一侧是 CTE 时，穿透到物理表所经过的 scope（右侧为 `right_via_scopes`） |
| `constraints[].kind` | `not_null` / `in_set` / `unique_per` / `partition` | O6 |
| `constraints[].completeness` | `complete` / `unknown` | 仅 `in_set`：只有封闭 `IN` 列表或穷尽 CASE 才是 `complete` |
| `findings[].kind` | `cardinality_conflict` / `producer_key_conflict` / `ambiguous_bare_name` | O7，后两者由表卡透传 |

## 推断规则

| 规则 | 内容 |
| --- | --- |
| O1 关系边 | JOIN 的 `join_key_pairs` 按（左表, 右表）归组成边；CTE 侧用 R3 的驱动路径穿透到物理表并记录穿透路径；UNION 分支两两成 `union_sibling`，列按位置对齐 |
| O2 基数 | 右侧在 JOIN 前按连接键 GROUP BY / 排名窗口去重 → `one_to_many`（`implied`）；右侧物理表且某生产任务已证明该键唯一 → `many_to_one`（`proven`）；直接关联物理表 → `many_to_one_assumed`（`hypothesis`）；其余 `unknown` |
| O3 多行性 | 任一任务对表 T 按键集 K 做 GROUP BY 或窗口 partition → T 按 K 有多行（`implied`）；键集跨两张表时不做任何断言 |
| O5 同义 | `end_to_end_lineage` 的 DIRECT 且列名不同 → `direct_rename`（`proven`）；UNION 同位置列名不同 → `union_alignment`（`implied`）；两端互相登记 |
| O6 约束 | `NOT x IS NULL` 过滤 → `not_null`（`hypothesis`，附注「任务丢弃了 NULL，源表可能仍含 NULL」）；可枚举 code → `in_set`；分区列 → `partition`（`proven`）；产出表候选键 + 分区列 → `unique_per`（键置信 `proven` → `proven`，`candidate` → `hypothesis`） |
| O7 冲突 | 同一（表, 键集）上「去重」与「直接关联」并存 → `cardinality_conflict`；表卡的 `producer_key_conflict` 与 `ambiguous_bare_name` 原样透传 |

## 边界与后续

- 本轮只出 `ontology.json` 与最小 `ontology.md` 索引；每表一张本体卡片与 Mermaid ER 总览是下一轮。
- 不产 OWL / SHACL / LinkML 文件；JSON 已带全部信息，导出器是后续的薄层。
- 不做向量化、不入库、不调 LLM、不含业务词表——那些属于下游项目。
