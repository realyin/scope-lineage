[English](../en/semantic-doc.md) | 中文

# semantic.json / semantic.md 任务语义描述（semantic-json/1、semantic-md/1）

`scope-lineage describe` 把一条写语句的 `lineage.json`（以及同目录的 `diagnostics.json`）
派生成一份**确定性的任务语义骨架**：`semantic.json`（主产物）与它的渲染 `semantic.md`。
它回答的问题与 [mapping.md](mapping-doc.md) 不同——mapping.md 回答"这一列从哪来"，
semantic 回答"这个任务在做什么、输出表的一行代表什么、每个字段是什么含义"。

## 定位：派生视图，不是业务定义

- semantic.json / semantic.md 是版本化契约的**派生视图**（与 mapping.md 同级）：
  其中每一条内容都来自 `lineage.json` / `diagnostics.json`，可按 `scope_id`、
  `logic_block_id`、`mapping_chain_id` 回链，文档本身不携带契约之外的"孤儿事实"。
- **事实本体永远在 `lineage.json`**。semantic.json 是给 Agent / RAG 按路径取片段用的压缩视图，
  semantic.md 是给人整读的渲染；两者由同一个 dict 产生，不会各自漂移。
- 文档里的每一条内容都打了来源标签，一共四种：

| 标签 | 含义 | 典型出处 |
| --- | --- | --- |
| `SQL事实` | SQL 里直接写着的：过滤条件、连接键、分组键、窗口定义、表达式、来源字段 | 第 3/4/5 节的动作行、规则表、加工步骤行 |
| `元数据事实` | 表/字段注释、字段类型、分区列——来自 `related_metadata` | 第 1 节目标表行、第 5 节目标注释与类型、第 6 节元数据覆盖 |
| `SQL事实+元数据事实` | 一行里既有 SQL 来源又有该来源的注释 | 第 5 节的"来源"行 |
| `结构推断` | 从 SQL 结构**可证明**的结论：输出形态、粒度、候选键、放大风险、窗口意图、结构角色 | 第 2 节全部、第 3 节窗口意图、第 5 节结构角色 |

- **`结构推断` 不是业务定义。** "按 `customer_id` 分组、按 `event_time` 降序、只保留第 1 行"
  是可证明的结构事实；"取客户最新状态"是业务归纳，不在本产物内。Core 刻意不输出业务实体命名、
  表类型的业务称呼（宽表/名单表/指标表）、模块命名、"这个任务的业务目标是…"，也不从字段名后缀
  猜角色——这些缺席是设计，不是缺口。业务画像由 Agent 按
  [`skills/scope-lineage/references/semantic-profile-prompt.md`](../../skills/scope-lineage/references/semantic-profile-prompt.md)
  生成，并另标 `LLM推断` / `待业务确认`。
- 稳定性分级：
  1. 文档中引用的契约 ID（`scope_id`、`logic_block_id`、`mapping_chain_id`、表名列名）与
     `lineage.json` 同级稳定，可作连接键 join 回 JSON；
  2. `semantic.json` 的键名与 `semantic.md` 的行语法只保证在同一 `doc_format` 主版本内稳定
     （当前 `semantic-json/1`、`semantic-md/1`）；结构变更会递增该版本号；
  3. 中文措辞与排版可能在不递增版本号的情况下微调，机器不应依赖任何未在本文档"行语法"一节
     列出的文本形态——要机器读就读 `semantic.json`。

## 用法

```bash
# 单条语句：semantic.json 与 semantic.md 写在 lineage.json 旁
scope-lineage describe --lineage /path/to/task/lineage.json

# 语料目录：递归查找 lineage.json；--out 镜像输入目录结构
scope-lineage describe --lineage /path/to/corpus --out /path/to/docs

# 只要 JSON；或只渲染部分章节（112 字段的大任务只保留第 5 节的紧凑清单）
scope-lineage describe --lineage lineage.json --format json
scope-lineage describe --lineage lineage.json \
  --sections overview,shape,fields_table,confidence
```

Python API（消费契约文档 dict，与文件写出同一条路径）：

```python
from scope_lineage import build_semantic_profile, render_semantic_markdown

profile = build_semantic_profile(lineage_document, diagnostics_document)
markdown = render_semantic_markdown(profile)                       # 全部七节
short = render_semantic_markdown(profile, sections=["overview", "fields_table"])
```

- 输入与 `render` 完全一致：`--lineage` 接受一个 `lineage.json` 或一棵递归查找它的目录树，
  同目录的 `diagnostics.json` 自动配对，`--out` 镜像输入目录结构。
- 两种契约形状都接受：**语句文档**（`schema_version: "1.0"`）与**任务文档**
  （`schema_version: "2.0"` 且 `artifact_kind: "task_lineage"`）。其他版本在目录模式下跳过并计数
  （运行摘要里的 `skipped_unknown_version=N`），单文件模式直接报错（退出码 1）。
- 读不出来的文档只丢它自己：`lineage.json` 或同目录 `diagnostics.json` 不是合法 JSON、或顶层
  不是对象时，目录模式在 stderr 各写一行并计入 `skipped_unreadable=N`，其余任务照常描述；
  单文件模式一行报错、退出码 2。
- `--format` 取 `json`、`md` 或两者（默认 `json,md`）；其他值直接报参数错误。
  `--sections` 只影响 `semantic.md`，`semantic.json` 永远是完整的；给了未知节名时报错退出（1）。
- 同目录没有 `diagnostics.json` 时照常渲染，但第 6 节会明确写"无 diagnostics 文档"，
  并计入运行摘要的 `missing_diagnostics=N`，而不是沉默。

## semantic.json 结构（semantic-json/1）

语句文档的 profile 是一个扁平的七块结构，键序固定：

```jsonc
{
  "doc_format": "semantic-json/1",
  "schema_version": "1.0",          // 源契约版本
  "statement_id": "stmt:001",       // 源文档没有脚本位置时省略该键
  "lineage_digest": "8c292a40a47f1439",
  "task": { "task_name": "…", "target_table": "…", "target_table_comment": null,
            "target_table_domain": null, "target_table_project": null,
            "target_table_owner": null,
            "stmt_kind": "INSERT_OVERWRITE",
            "partition": {"columns": ["dt"], "mode": "static", "spec": {"dt": "${bizdate}"}},
            "instance_dates": ["20260814"],
            "structural_summary": "…", "target_metadata_source": "target_ddl",
            "header_comments": ["任务：客户画像快照", "口径：只计已支付订单"],
            "meta": {"task_name": "…", "task_id": "…", "project": "…", "owner": "…",
                     "schedule": "0 30 2 * * ?", "schedule_cycle": "DAY",
                     "description": "…", "expect_date": "…", "source_file": "…"} },
  "inputs": [ { "table": "…", "comment": null, "comment_source": "metadata",
                "domain": null, "project": null,
                "owner": null, "layer": null,
                "role_in_task": "driving", "roles": ["driving"],
                "used_columns": [{"name": "…", "type": "…", "comment": "…", "usages": ["join_key"]}],
                "metadata_complete": true, "table_column_count": 5, "read_by_scopes": ["ROOT"] } ],
  "output_shape": { "shape": "enriched_projection", "shape_evidence": ["logic:ROOT:join:001"],
                    "grain": {"keys": [{"scope_id": "cte:agg", "name": "org_code",
                                         "expression": "CASE WHEN … END",
                                         "physical_sources": [{"table": "…", "column": "…"}]}],
                              "basis": "group_by", "via_scopes": [],
                              "confidence": "structural", "evidence": ["…"]},
                    "candidate_keys": ["org_code"], "unexposed_keys": [],
                    "key_evidence": [], "key_confidence": "proven",
                    "partition_columns": ["dt"],
                    "fan_out_risks": [{"logic_block_id": "…", "scope_id": "ROOT",
                                       "join_type": "LEFT_OUTER",
                                       "right": "…", "status": "safe", "reason": "…",
                                       "path": "grain"}],
                    // describe --tables 改判过的风险多一个 basis: "table_card"
                    "tag": "结构推断" },
  "stages": [ { "scope_id": "cte:latest_status", "name": "latest_status", "kind": "cte",
                "role": "dedup", "direct_inputs": ["…"], "direct_source_tables": ["…"],
                "upstream_physical_tables": ["…"],
                "actions": [{"type": "derive", "column": "gap_h", "text": "日期差（天）：a − b",
                             "expression": "…", "fields": [], "evidence": "cte:agg"},
                            {"type": "window", "intent": "keep_latest_per_group", "text": "…",
                             "expression": "…", "fields": [{"table": "…", "column": "…", "comment": "…"}],
                             "consumed_by": "logic:ROOT:join:001",
                             "evidence": "logic:cte:latest_status:window:001", "tag": "结构推断"}],
                "outputs": ["…"], "output_count": 3,
                "pattern_signature": "role=dedup|kind=cte|inputs=tables:1,scopes:0,union:no|…" } ],
  "rules": [ { "rule_id": "rule:001", "kind": "filter", "scope_id": "…", "expression": "…",
               "is_partition_filter": true, "fields": [], "scope_fields": [],
               "sql_comments": ["仅生效状态"],   // 仅当该逻辑块上写了注释
               "value_meanings": [{"column_ref": "ods.a.queue_code", "value": "01",
                                   "sql_literal": "'01'",
                                   "meaning": {"text": "人工队列", "status": "confirmed"}}],
               "evidence": "logic:…", "tag": "SQL事实" },
             { "rule_id": "rule:002", "kind": "join_condition", "scope_id": "ROOT",
               "join_type": "LEFT_OUTER",
               "null_semantics": "右侧无匹配时保留左行，右侧字段为空",
               "key_pairs": [{"left": "a.segment", "right": "d.segment"}],
               "physical_key_pairs": [{"left": "ods.a.segment", "right": "dim.d.segment"}],
               "extra_conditions": [], "extra_condition_fields": [],
               "fields": [], "scope_fields": [], "evidence": "logic:…", "tag": "SQL事实" } ],
  "fields": [ { "column": "paid_amount_30d", "column_label": "mart.t.paid_amount_30d",
                "summary": "近 30 天已支付金额：按 customer_id 聚合：SUM(pay_amount)，仅计 pay_status = 'PAID'，再空值回填为 0；来源 dwd.order_detail.pay_amount（Paid amount）",
                "target_comment": "…", "target_comment_source": "patch",
                "sql_comments": ["近 30 天已支付金额（元）"],
                "type": "decimal(18,2)", "transform": "EXPRESSION",
                "structural_role": "measure", "nullable_by_join": true,
                "metric_spec": {"subject": {"scope_id": "cte:agg", "tables": ["dwd.order_detail"],
                                           "text": "dwd.order_detail 的记录"},
                                "time_range": [{"column": "dwd.order_detail.stat_date",
                                                "expression": "stat_date = ${bizdate}",
                                                "kind": "parameter", "scope_id": "cte:agg",
                                                "path": "grain"}],
                                "time_dependent": true,
                                "inclusion": [{"expression": "pay_status = 'PAID'",
                                               "text": "仅计 pay_status = 'PAID'",
                                               "scope_id": "cte:agg", "where": "aggregate_case",
                                               "path": "grain"}],
                                "aggregation": {"function": "SUM", "argument": "pay_amount",
                                                "argument_comment": "Paid amount",
                                                "group_keys": [{"name": "customer_id",
                                                                "target_column": "customer_id"}],
                                                "text": "按 customer_id 汇总 SUM(pay_amount)"},
                                "unit": {"type": "decimal(18,2)", "hint": null, "hint_source": null},
                                "null_handling": {"nullable_by_join": true, "default": "0",
                                                  "default_source": "COALESCE"},
                                "refresh": {"cycle": "DAY", "cron": "0 30 2 * * ?",
                                            "source": "task_meta"},
                                "post_aggregation": ["空值回填为 0"],
                                "evidence": ["logic:cte:agg:group_by:001", "mc:007"]},
                "value_domain": [{"value": "PAID", "sql_literal": "'PAID'",
                                  "kind": "literal",
                                  "seen_in": ["rule:003"], "closed_set": true,
                                  "meaning": {"text": "已支付", "status": "confirmed"}}],
                "sources": [], "generated_sources": [],
                "derivation": [{"step_no": 1, "scope_id": "union:u:b01", "step_type": "expression",
                                "branch": {"index": 1, "label": "ods.a"},
                                "grain": "preserved", "text": "…", "expression": "…"}],
                "expression": "…", "trace_complete": true, "ambiguous": false,
                "mapping_chain_id": "mc:007", "tag": "SQL事实+元数据事实" } ],
  "confidence": { "metadata_coverage": {"sql_comment_counts": {"header": 2, "output": 1, "logic": 1},
                                        "patch": {"tables": 1, "columns": 3}},
                  "confirmations": {"values_confirmed": 2, "rule_values_confirmed": 4,
                                    "terms_confirmed": 1,
                                    "columns_patched": 3, "tables_patched": 1},
                  "trace_incomplete_fields": [], "ambiguous_fields": [],
                  "diagnostics_available": true, "fact_gap_count": 0, "fact_gap_types": {},
                  "warning_counts": {},
                  "findings": [{"kind": "nondeterministic_function", "severity": "warn",
                                "text": "…", "evidence": ["mc:007"]},
                               {"kind": "hardcoded_date_literal", "severity": "info",
                                "text": "…", "evidence": ["rule:001"]}],
                  "inferred_items": {"fields[].structural_role": 52, "output_shape.shape": 1} }
}
```

### 任务文档的外层 wrapper

任务文档（`schema_version: "2.0"`）不把七块摊平在顶层，而是包一层任务级信息，每条写语句一个
完整的语句 profile：

| 键 | 内容 |
| --- | --- |
| `doc_format` | 固定 `semantic-json/1` |
| `artifact_kind` | 固定 `task_semantic`，用于与语句 profile 区分 |
| `task_id` | 任务标识（来自契约顶层 `task_id`） |
| `lineage_digest` | 源任务文档的内容摘要 |
| `produced_tables` | 最终产出表清单，来自 `final_table_states`，已排除会话内关系与 `directory:` 写入 |
| `warning_counts` | 全脚本警告的按类型计数：顶层（脚本级）与每条语句 `statement_diagnostics` 的**并集**去重后计数；没有 diagnostics 文档时为 `null` |
| `statements` | 每条写语句一个语句 profile，键与上面的七块结构完全相同 |

### 每块写什么、词表是什么

| 块 | 关键子键 | 取值词表（以实现为准） |
| --- | --- | --- |
| `task` | `target_table_comment`、`target_table_domain` / `target_table_project` / `target_table_owner`（目标表的业务归属，取自元数据的表级事实，`null` 表示元数据没说）、`partition`、`instance_dates[]`、`structural_summary`、`target_metadata_source`、`header_comments[]`、`meta` | `partition.mode`：`static` / `dynamic`；`target_metadata_source`：`schema` / `target_ddl` / `null`（两侧都没描述该表）；`header_comments[]` 是契约 `statement_comments` 的原样副本（语句头部注释，作者原话，恒存在、可为空）；`meta` 是契约 2.0 顶层 `task_meta` 的原样副本，`.sql` 输入或无任务元信息时为 `null`——`null` 表示没有输入提供，不表示这个任务没有负责人或调度。两者都是**引用**而不是本视图的断言：注释与元数据里的列注释可能互相矛盾，产物不替作者裁决；`instance_dates[]`（WI-2.9）是本实例的等值日期过滤钉住的**日期形字面量**去引号去重升序后的集合（`['20260814']`），`[]` 表示没有任何过滤钉住一天——由 `${…}` 变量替换，或根本没有日期过滤，**不表示读取全部日期**；判定只看常量的写法（`yyyyMMdd` / `yyyy-MM-dd` / `yyyy/MM/dd` 前缀），与 `hardcoded_date_literal` 读的是同一批比较，两者不会指向不同的天 |
| `inputs[]` | `comment`（表注释，按 `table_name_cn` → `table_desc` → `comment` → `table_comment` 取第一个有值的）、`domain` / `project` / `owner` / `layer`（表级元数据事实，恒存在、缺则 `null`）、`role_in_task`（最具体的一个）、`roles`（全部）、`used_columns[].usages`、`metadata_complete`、`table_column_count` | 角色（R7）：`driving`、`merge_source`、`aggregate_source`、`dedup_source`、`union_branch`、`enrich`、`rowset_only`；`driving` 除 ROOT 直读的主表外，还包含**下层 scope 的 FROM 项**：某个非 ROOT scope 的 FROM 项（按 `_scope_from_item` 规则，只做 JOIN 右侧的输入不算）所属物理表，只要该 scope 在 ROOT 的驱动路径上（UNION 取全部分支），或它的输出列正是 ROOT 的 GROUP BY 键，就同样是 `driving`——GROUP BY 键全来自某张表却因 ROOT 不直读而被标成 `enrich`，会把读者引到查找表上；MERGE 语句不适用（R2 判不出形态，其来源仍是 `merge_source`）；用途：`filter`、`partition_filter`、`join_key`、`group_by`、`window_partition`、`window_order`、`output`；`used_columns[].term_meaning`（WI-2.12）是语料字典里**已人工确认**的该列名含义 `{text, status}`，与该列自己的 `comment` 并排而不替换它，没有确认过就整键缺席 |
| `output_shape` | `shape`、`grain`、`candidate_keys`、`unexposed_keys`、`key_evidence`、`key_confidence`、`partition_columns`、`fan_out_risks[]` | 形态（R2）：`aggregated`、`deduplicated`、`union_merge`、`enriched_projection`、`filtered_projection`、`unknown`；`grain.basis`（R3）：`group_by`、`distinct`、`window_partition`、`driving_table_rows`、`unknown`；`grain.via_scopes`：从 ROOT 递归下探时**穿透过**的 scope_id 列表（不含 ROOT、不含终止的那一层），空列表表示 ROOT 直读；`grain.keys[]` 是**逻辑键**对象（见下表），`candidate_keys[]` 是**目标表列名**；`key_confidence`：`proven`（GROUP BY / DISTINCT / 窗口 `= 1` 的键，链路上每个 JOIN 都 `safe`，且每个键都直投到目标列）/ `proven_unexposed`（键本身成立，但至少一个键没写进目标表——**目标表列无法唯一标识一行**，治理发现）/ `candidate`（主表行粒度，连接键候选且都已输出）/ `none`（此时 `candidate_keys` 为空）；`fan_out_risks[]`：粒度链路上**每个** scope 的 JOIN，带 `scope_id`；`status`：`safe` / `risk` / `unknown`——判定发生在**右侧 scope 的逻辑层**：右侧 GROUP BY 项（或排名窗口的 PARTITION BY 项）在该 scope 的输出列名（未投影时用其表达式原文）被 `join_key_pairs[].right.column` 的集合覆盖才是 `safe`，否则 `risk`；键的物理穿透列只作为 reason 末尾的附注（`（键的物理来源 …）`），**不参与判定**——一个 CASE 键穿到 4 列、另一个穿到其中 2 列时，物理集合会把「右侧按 3 个键唯一」误读成「被 2 个连接键覆盖」；`path`：`grain`（粒度链路，影响输出行数）/ `argument`（某个指标的**参数路径**上的 JOIN——不改变输出行数，但会重复指标读到的行，把数值放大）/ `anchor`（指标锚定到自己的聚合 scope 后，该 scope **输入子树**里既不在驱动路径也不在参数路径上的 JOIN——它同样会放大被聚合的行；这三条路径都不沾的旁路 JOIN 仍然不列）；**只有 `path = grain` 的风险参与 `candidate_keys` / `key_confidence` 的判定**：参数路径与锚定子树上的放大改的是指标取值而不是行身份，让它压低键置信等于用另一个问题撤销这条语句能给出的最强结论，风险本身照发；`basis` 只在 `describe --tables` 用表卡改判过这条风险时出现，取 `table_card`（见 [tables-doc.md](tables-doc.md)「表卡参与 fan_out 判定」），此时 `candidate_keys` / `key_confidence` 也按新的风险集合一并算出 |
| `output_shape.grain.keys[]` / `unexposed_keys[]` | `scope_id`、`name`、`expression`、`physical_sources[]` | 一个 GROUP BY 项 / 窗口 `PARTITION BY` 项 / DISTINCT 输出列 = **一个**逻辑键，无论它的表达式穿透到几个物理列：`scope_id` 是产生该键的 scope，`name` 是该 scope 的输出列名（GROUP BY 项不是投影列时为 `null`），`expression` 是原表达式，`physical_sources[]` 是穿透到的 `{table, column}` 列表。`unexposed_keys[]` 是其中没有直投到任何目标列的那些键 |
| `stages[]` | 拓扑序，每 scope 一项：`role`、三种来源清单、`actions[]`、`pattern_signature` | 动作类型按 SQL 生效顺序排列：`join`、`filter`、`aggregate`、`having`、`window`、`distinct`、`union`、`lateral_view`、`derive`、`case_when`；`derive` 是该 scope 输出列里 `transform` 为 `EXPRESSION` 的普通表达式派生（算术、函数调用），每列一条并带 `column`，`evidence` 取该列的 `source_logic_blocks[0]`、契约没给时取 `scope_id`；`actions[].sql_comments[]` 是该动作对应逻辑块上的注释原文（`derive` 动作取该输出列的注释，别名注释不在块表达式内），无注释时不写该键；窗口意图（R6）：`keep_latest_per_group`、`keep_first_per_group`、`rank_within_group`、`pick_first_in_group`、`pick_last_in_group`、`adjacent_row_offset`、`running_aggregate`；聚合动作的分组键与关联动作的连接键都按**逻辑名**书写（GROUP BY 项的 `expression_sql` 去限定符、连接键的 scope 级 `qualifier.column`），物理穿透结果只在 `actions[].fields[]`；`pattern_signature` 含直接输入的种类（`inputs=tables:N,scopes:M,union:yes\|no`）与 `derive=N`，不含任何名字 |
| `rules[]` | 扁平规则清单：`kind`、`expression`（SQL 原文）、`fields[]`（带注释）、`is_partition_filter`、`sql_comments[]`、`evidence` | `kind`：`filter`、`having`、`join_condition`、`case_branch`；连接规则另有 `key_pairs[]`（**scope 级短形式**，与 mapping.md 第 6 节一致：`{left, right}` 为 ON 原文写法的 `qualifier.column`）/ `physical_key_pairs[]`（穿透到物理列后的结果，UNION 下一个逻辑键对会展开成多对）/ `extra_conditions[]` / `extra_condition_fields[]` / `null_semantics`（该连接类型对未命中行的固定说法：`LEFT_OUTER` / `INNER` / `RIGHT_OUTER` / `FULL_OUTER` / `CROSS` 各一句，其余类型为 `null`）；CASE 规则另有 `branches[]` / `else`；`value_meanings[]`（WI-2.12，只在 `describe --glossary` 命中时出现，命中不到一条就整键缺席）是这条规则把列钉住的每个 code：`{column_ref, value, sql_literal, meaning}`，按 `(column_ref, value)` 去重、按规则写出的顺序排列，`meaning` 在没人回答时为 `null`。只收 `=` / `IN` / `<>` 与 CASE **条件**里的常量——`LIKE` / `RLIKE` 的匹配模式不是业务码，连接键比较的是两列而不是常量；`column_ref` 的归属与字典同一套规则（规则字段里恰好一列同名才写表名，否则写 scope 级引用，scope 级引用只认本任务观察到的条目） |
| `fields[]` | 每目标字段一项，按 `target_column_ordinal` 排序：`summary`、`target_comment`、`sources[]`、`derivation[]`、`structural_role`、`nullable_by_join`、`trace_complete` | 结构角色（R5）：`candidate_key`、`partition`、`measure`、`event_time`、`conditional_label`、`constant`、`attribute`、`derived`；`conditional_label` 只看**该字段自身最后一个** CASE/IF 步（链路会把分组键与度量两条线交织在一起，「任一步是常量 CASE」会让别的线的标签给这个字段命名），且要求它每个 THEN 与 ELSE 都是字面常量（或 NULL、带符号的数字字面量）——`CASE WHEN x > 0 THEN 0 ELSE x END` 这类封顶有一个分支返回列，算 `measure`（链含聚合）或 `derived`；`derivation[].grain`：`changed` / `preserved` / `unknown`；`derivation[].branch` 仅在该步发生在某个 UNION 分支里时出现，值为 `{index, label}`（分支序号与该分支的来源表）；`summary` 是**一句无标签的人话**，模板 `<目标注释｜（注释未知）>：<各 derivation 步骤用"，再"连接｜全链路仅投影时"直接取自 <表>.<列>（<注释>）">；来源 <表>.<列>（<注释>）…`。含 UNION 分支加工时，分支是**并列**关系而不是顺序步骤，改写成 `分支 1（来自 <表>）：…；分支 2（来自 <表>）：…；合并后 …`（最多 3 个分支，其余计数）；`generated_sources[]` 在句子里写成 `常量 'F_00'` / `系统值 current_date()`，JSON 里保持 `{source_type, value, transform}` 结构，它只复述本条目其它键已有的事实，且**不加反引号**（自由文本不是 catalog 断言）；`nullable_by_join` 仅在**能严格证明**该字段全部取值都经某个 OUTER JOIN 的可空侧到达、且其后每一步都原样传递时出现并恒为 `true`，证不出来就不写；`sql_comments[]` 是沿推导链各步输出列上的 SQL 注释原文（去重保序，上游在前），无注释时不写该键；注释体本身是一段被注释掉的 SQL（`cast(null as string) as x` 这类旧写法）时**不进这个键**，也不进 `summary` 的 `；注释：` 后缀——判定保守：解析不出 SQL 形态、或没有一个 ASCII SQL 关键词时一律当成说明文字，原文仍留在契约的 `comments` 里；`summary` 末尾在**该字段自己的别名注释**存在时追加 `；注释：<原文>`——只追加别名注释而不是整条链，且这段是**引用**：它是句子里唯一不由契约推导出来的部分，反编造属性检查在扫描前先把它切掉；`value_domain[]`（WI-2.4）是这个字段观察到的取值，每条为 `{value, kind, seen_in[], closed_set, meaning}`——只在非空时出现，不传 `--glossary` 时只含本语句自己证明的取值且 `meaning` 恒为 `null`；按（`value`、`kind`）去重、按首次出现顺序排列，`kind` 取 `literal`（枚举值）或 `pattern`（`LIKE` / `RLIKE` 的匹配模式，`closed_set` 恒 `null` 且不参与封闭集判定）；`value` 去掉 SQL 引号、`sql_literal` 保留作者写的字面量；`closed_set` 是**整列**的结论（同一字段要么全 `true` 要么全 `null`）；只收该列自己输出的常量与**全链路透传**来源列被 `=` / `IN` 钉住的值，CASE 条件里的常量属于被判断的那一列，且数值/日期型目标列只接受同类型字面量。详见 [glossary-doc.md](glossary-doc.md)。`semantic.md` 的 `- 取值：` 行最多列 12 个枚举值（超过写「等 N 个，完整见 semantic.json value_domain」），匹配模式单独排在行尾的「匹配模式：…」里；`term_meaning`（WI-2.12）只在该字段 `target_comment` 为空、而字典里这个列名有人工确认含义时出现，形如 `{text, status: "confirmed"}`——它是术语不是注释，`semantic.md` 里写成独立的 `- 术语：…（人工确认）` 行，`- 目标注释：` 行照旧写「注释未知」；`sql_alias`（WI-B）只在三个条件同时成立时出现：`target_field_binding.method = ddl_position`、该投影的 SQL 别名与 DDL 同位置列名不同、且这个别名是作者写的（不是 `_col_N` / `_cN` 占位名，判定与 `alias_position_mismatch` 同一套），值为作者写的别名原文；`semantic.md` 的字段清单行与字段小节标题都会在列名后追加「（SQL 别名 `<别名>`，按 DDL 位置写入）」——否则一行顶着 DDL 列名展示作者按别名写的表达式，读者只会以为文档写错了 |
| `fields[].metric_spec` | 仅指标字段有：`subject`、`time_range[]`、`time_dependent`（仅为真时出现）、`inclusion[]`、`aggregation`、`unit`、`null_handling`、`refresh`、`post_aggregation[]`、`evidence[]` | 出现条件：`structural_role` 为 `measure` / `event_time`，或加工链里有 **AGGREGATE 步**（末步变换看不出的聚合也算；被标量函数包住的聚合同样算——`DATE_FORMAT(MAX(t), 'yyyy-MM-dd')` 的步类型是标量调用，`aggregation` 取表达式内**最外层**的聚合调用，窗口帧里的聚合不算，它不改变行数）。**聚合 scope** = 链上最后一个 aggregate 步所在 scope。口径读**两条路径**：**粒度路径（`path: "grain"`）** = 聚合 scope 加上它逐层 FROM 项下探到的 scope（JOIN 右侧永不算 FROM 项，UNION 取全部分支），决定统计对象与粒度；**参数路径（`path: "argument"`）** = 该聚合步 `expression_resolution` 指认的上游 scope（`source_scope_id` / `scope_output_trace[].to_scope_id`；无聚合步时取链末步）再逐层下探得到的 scope，去掉粒度路径已走过的部分——指标参数取自 JOIN 右侧时，**那一侧自己的日期过滤才是这个指标的时间口径**。两条路径都不沾的旁路 JOIN 右侧仍然排除，它的过滤进不了口径。`time_range[]` 取两条路径上**判定为日期列**的过滤合取项（判定依据三选一：元数据声明 date/timestamp、契约的 `is_partition_filter` 或列属 `target_partition_columns`、常量写成日期字面量或 `${…}`），`kind` 取 `literal` / `instance_date` / `parameter` / `expression` / `range`（带引号的 `'${bizdate}'` 也算 `parameter`；**`instance_date`**（WI-2.9）是等值钉住一个**日期形字面量**的 `literal`——一个任务实例本来就对应某一天，md 写成「实例日期 20260814」而不是「字面量」，写成别的形状的字面量仍是 `literal`）；`inclusion[]` 取两条路径上**其余**过滤合取项（`where: filter`）、这些路径上 JOIN 的附加条件（`join_condition`）与聚合调用内 CASE 的 WHEN 条件（`aggregate_case`，复述成「仅计 …」），HAVING 不算（它过滤的是已成形的组）；`aggregation.group_keys[].target_column` 复用 WI-1e 的「逻辑键落目标列」判定，落不到写 `null`；`unit.hint` 取自封闭词表 `金额` / `笔数` / `天数` / `时间` / `天` / `月` / `秒`，`hint_source` 为 `comment`（注释字面含 金额/元/笔数/次数/天/时间）/ `function`（COUNT；**日期差表达式**——`DATEDIFF` 给 `天`、`MONTHS_BETWEEN` 给 `月`、`UNIX_TIMESTAMP(a) - UNIX_TIMESTAMP(b)` 给 `秒`，外层套 MAX/MIN/AVG/SUM 时递归识别，`DATE_ADD(x, DATEDIFF(…))` 这类「差值再造日期」不算；或声明为时间类型的列上的 MAX/MIN）/ `type`（目标列本身是 date/timestamp）/ `null`；`time_dependent`：字段推导链或聚合参数里出现 `CURRENT_TIMESTAMP` / `CURRENT_DATE` / `NOW()` / 无参 `UNIX_TIMESTAMP()`（sqlglot 规范化后即 `CURRENT_TIMESTAMP()`）/ `RAND` / `UUID` 时为 `true`，口径卡「时间范围」行末追加「（含运行时刻函数，结果随跑批时间漂移）」；为假时**不写这个键**（写 `false` 会读成「查过且干净」）；`time_range[].mismatch`：同一列名在 grain 与 argument 两侧被钉到**不同字面量**时，两条都标 `true`，md 该行末写「（<另一条> 另一侧取前 N 日）」——方向与 N 只在两侧都写成 `yyyyMMdd` / `yyyy-MM-dd` 时算得出，否则只写「另一侧取另一天」；WI-2.9 起这句是**口径事实**而不是告警，对应的 `partition_literal_mismatch` finding 也降为 `info`；同一条路径上的两个合取项不算不一致（同一个关系被过滤两次）；`subject.argument_tables[]` 只在指标参数**全部**来自粒度路径以外的表时出现，统计对象仍是主表的记录，只是取值来自别处（md 写「<主表> 的记录，指标值取自 <参数来源表>」）；`null_handling.nullable_by_join` 除字段自身链路的判定外，还认**参数来源**：聚合参数由某个 OUTER JOIN 的可空侧（LEFT 的右侧 / RIGHT 的左侧 / FULL 两侧）进来、且聚合步及其之后没有 COALESCE / CASE ELSE 回填时为 `true`（COUNT 除外，空组答 0 而不是 NULL），此时 `null_handling.nullable_argument` = `{scope_id, join_type, side}` 指认那个 JOIN，`fields[].nullable_by_join` 同步为 `true`；`null_handling.default` 只读**两条能确认属于这个字段**的表达式：该字段自身的末段表达式与它自己的聚合调用（加工链是多条线交织的一个有序表——度量的步骤与分组键的步骤混在一起——整条扫一遍会把邻列的兜底写成这个指标的默认值）；其中 COALESCE 家族调用的末位参数在这两条表达式里不限层级，CASE 的 ELSE 只认**末段表达式顶层**且 ELSE 是标量常量的那一种；ELSE 是列或表达式、CASE 嵌在别的调用里（那是那个调用的参数）都写 `null`；`refresh` 取自 `task.meta`：`schedule_cycle` 或 `schedule` 有一个非空就发 `{cycle, cron, source: "task_meta"}`，两者都没有时为 `null`——周期绝不从分区列或表名推断；`post_aggregation[]` 是聚合步之后那些非透传步骤的 R4 复述原话；聚合调用被标量函数包住时，外层那一层写成 `外层 DATE_FORMAT(…, 'yyyy-MM-dd')` 排在最前——它发生在同一个表达式里而不是后续步骤里，否则读者看到的就是个裸 `MAX` |
| `confidence` | `metadata_coverage`（含 `sql_comment_counts`）、`trace_incomplete_fields`、`ambiguous_fields`、`diagnostics_available`、`fact_gap_count` / `fact_gap_types`、`warning_counts`、`findings[]`、`inferred_items` | `fact_gap_count` / `fact_gap_types` / `warning_counts` 取**顶层 + 本语句 `statement_diagnostics.<statement_id>`** 的并集（v2 诊断文档把语句自己的警告放在后者，只读顶层会把有警告的语句写成"无"）；`findings[]` 每条为 `{kind, severity, text, evidence[]}`，`severity` 取 `warn`（要人处理）或 `info`（真但不用处理，WI-2.9：`hardcoded_date_literal` / `partition_literal_mismatch` / `table_comment_missing` 三个恒为 `info`，其余恒为 `warn`；一个任务实例本来就对应某一天，分区日期写死是设计而不是缺陷），`kind` 取 `alias_position_mismatch`（`target_field_binding.method = ddl_position` 且至少一个投影的 SQL 别名与 DDL 同位置列名不同——写错列或元数据列序过期，`evidence[]` 是这些字段的 `mapping_chain_id`；作者没写别名的投影不算错位：`SELECT a, 0, current_date()` 的后两列拿到的是 sqlglot 生成的占位名，判定先看契约的 `end_to_end_lineage[].name_is_generated`，位置绑定已把名字绑掉、该键缺席时再看占位形态 `_col_N` / `_cN`）、`partition_literal_mismatch`（多张输入表同名列的等值字面量不一致；`evidence[]` 还带上 `metric_spec.time_range` 里因此被标 `mismatch` 的字段的 `mapping_chain_id`）、`nondeterministic_function`（字段推导链、过滤条件或聚合参数里出现 `CURRENT_TIMESTAMP` / `CURRENT_DATE` / `NOW()` / 无参 `UNIX_TIMESTAMP()` / `RAND` / `UUID`——依赖作业运行时刻或随机值而非数据日期，补跑历史会得到不同结果；整条语句一条 finding，text 里按「字段 <目标列>」「规则 <rule_id>」列出，`evidence[]` 为对应的 `mapping_chain_id` 与 logic block id）、`hardcoded_date_literal`（分区/日期过滤用字面量而非 `${…}` 变量或函数）、`metadata_conflicts`（来自 2.0 诊断的 `metadata_coverage.metadata_conflicts`）、`target_binding`（`target_field_binding.status` / `method`，或 `target_binding_absent_reason`）、`table_comment_missing`（缺表注释的输入表与目标表）；`inferred_items` 是本文档结构推断项**按路径模式聚合后的计数**（`{"fields[].structural_role": 52, "output_shape.grain": 1, …}`），用于"哪些是推断"的自查——逐下标列出 52 条同类路径只是把一个计数写长；`metadata_coverage.sql_comment_counts` 是 `{header, output, logic}` 三个计数，说明本文档能用到多少作者批注，**只计数不判断**：没有注释的语句不是治理问题，因此它不进 `findings[]` |

两条贯穿全文的诚实规则：缺失的注释一律写 `null`（md 里渲染成"注释未知"），**绝不翻译、不同义扩写、
不按字段名猜**；连接键穿透到生成列时，该生成列的上游字段进 `rules[].extra_condition_fields`
（带 `via_generated_column: true`）而不是 `fields[]`——否则等于声称 `event_time` 是连接键。

### 语料表卡：`describe --tables`

传了 [`tables.json`](tables-doc.md) 之后，profile 再多三处，**都按归一表名匹配**：

- `inputs[].card`：这张输入表的**生产任务**证明的东西——`produced_by_task`、`grain_text`
  （一句结构化的"一行代表什么"）、`candidate_keys`、`key_confidence`、`comment`、`refresh`；
  语料内没有任务写它时为 `null`。
- `task.downstream_consumers[]`：谁读本语句的目标表，每条给 `task` / `role_in_task` / `columns`；
  本语句自己不算在内。
- `confidence.metadata_coverage.table_cards`：`inputs_with_card` / `inputs_total` / `consumers`
  三个计数，说明表卡回答了输入侧的多少。

没有传 `--tables` 时这三个键**根本不出现**，`semantic.json` 与 `semantic.md` 与表卡功能上线之前
逐字节一致——"没给语料"和"语料证明没人写"是两个答案，不会渲染成同一句。

### 确认回写：`describe --metadata-patch`

传了一份 [`metadata-patch/1`](input-formats.md) 之后，本视图再多四处，回答的是同一个问题——
**这句话是仓库的元数据说的，还是人答出来的**：

- `inputs[].comment_source`：`metadata` / `patch`；该输入表**没有**表注释时该键不出现
  （一个"来源是元数据"的空注释在回答文档回答不了的问题）；
- `fields[].target_comment_source`：同样两个取值，同样只在该字段有目标注释时出现；
- `confidence.metadata_coverage.patch`：`{tables, columns}`，本语句里被补丁写过的表数与列数；
  一条补丁都没命中时该键不出现；
- `confidence.confirmations`：`{values_confirmed, rule_values_confirmed, terms_confirmed,
  columns_patched, tables_patched}`，**恒存在**——全 0 也是事实，"这个任务还没有人确认过任何
  东西"正是回写闭环要改变的那个状态。前三个计数由 `--glossary` 填（字段取值含义、规则取值含义、
  列名术语），后两个由补丁填。`rule_values_confirmed`（WI-2.12）单独计数而不并进
  `values_confirmed`：同一个 code 写在输出字段上与写在 `WHERE` 里是读者在两个地方各问一次的
  问题，而仓库里的业务码多数只出现在后者。

`semantic.md` 里，来自补丁的注释在原文之后加一个后缀 `（人工确认）`——第 3 节输入表表格的
「表注释」列与第 5 节字段小节的 `- 目标注释：` 行各一处。行尾的 `元数据事实` 标签只为"确实有这条
注释"背书，谁说的写在注释里面。

`parse --metadata-patch` 与 `describe --metadata-patch` 走同一个函数，两条路径产出的
`semantic.json` 逐字节相同（含 `lineage_digest`）。不传补丁时前三个键都不出现。
业务方的答案怎么变成这份补丁，见 [术语与值域字典](glossary-doc.md) 的「回写闭环」。

## semantic.md 的七节与 `--sections` 名

| 节 | `--sections` 名 | 内容 | 事实来源 |
| --- | --- | --- | --- |
| 1. 任务概览 | overview | 目标表与表注释、语句类型与分区、目标表元数据来源、取数日一行（`task.instance_dates` 非空时才出现，多天时附「（相差 N 天）」）、结构摘要一句、任务元信息一行（项目 / 负责人 / 调度周期 / 调度表达式 / 期望日期 / 任务描述，缺哪项就不写哪项，全缺则整行不出现）、SQL 头部注释引用块（`> ` 逐行原文，标题「SQL 头部注释（原文，作者说法，非 SQL 事实）」，无注释时整块不出现）、输入表表格（注释、角色、使用列/全宽、元数据完整性、读取 scope） | `task`、`inputs` |
| 2. 输出表形态与粒度 | shape | 形态、粒度的逻辑键与依据（含穿透路径、物理来源）、键/候选键（**目标表列名**，按 `key_confidence` 措辞）、分区列、粒度链路上逐 JOIN 的行数放大风险；`path` 为 `argument` 的 JOIN 另起一行小标题「影响指标取值的关联：」单列——它不改变行数，改变的是指标数值 | `output_shape` |
| 3. 加工链路 | stages | 拓扑序逐阶段：角色、直接输入 / 直接读取物理表 / 上游物理表、动作行（有注释时行末追加 `（注释：…；SQL注释）`；WI-2.12：过滤 / HAVING / 关联的复述在注释之前追加 `（取值：'01'＝人工队列；…）`，只列字典已答的 code，超过 3 个写「等 N 个，见规则表」）、输出列 | `stages` |
| 4. 规则清单 | rules | 过滤 / HAVING / 连接条件 / CASE 分支，一条一行，带涉及字段的注释、`SQL注释` 列（作者写在该条件上的原话，无则 `—`）与证据 id；WI-2.12：本语句有被字典答过的 code 时，「条件」列之后多一列「取值含义」（已确认写 `'01'＝人工队列`，候选写 `'07'＝? 自动队列`，该条没有答案写 `—`），一条都没答过时整列不出现 | `rules` |
| 5. 字段语义 | fields（子开关 fields_table） | **先**出"完整字段清单"紧凑表（`#` / 字段 / 一句话语义 / 结构角色 / 口径 / 追溯，"口径"是聚合调用与时间范围的一句压缩，非指标字段写 `—`），**再**逐字段一个 `###` 小节：第一行 `- 语义：<summary>`（无标签），指标字段紧接一张固定七行的"口径"小卡（统计对象 / 时间范围 / 纳入条件 / 聚合 / 单位·类型 / 空值 / 更新频率；槽位为空时写明"未在聚合路径上发现日期过滤"这类原因，而不是省掉该行；来自参数路径的日期过滤在"时间范围"行末标"（参数来源侧）"，"空值"行在参数可空时写成"参数来自 LEFT JOIN 右侧（<scope>），关联不上时为空"；"更新频率"行在 `task.meta` 给出调度时写成"每日（cron …）"、否则写"未知（任务元信息未提供）"），随后 `- 注释：…（SQL注释）` 一行（该字段推导链上的作者原话，无则整行不出现）、目标注释、类型、来源、结构角色、逐步加工、最终表达式、追溯状态；有取值观察时在注释行后加一行 `- 取值：`（已确认写含义、候选写 `? `、都没有写「待确认」，整列封闭时行尾追加封闭说明）；WI-2.12：目标注释为空而字典有已确认术语时，`- 目标注释：` 之后多一行 `- 术语：<含义>（人工确认）`，「完整字段清单」也相应多一列「术语」（有术语的写 `<含义> ✓`，其余写 `—`），无术语时该列不出现 | `fields` |
| 6. 可信度与边界 | confidence | 元数据覆盖、追溯不完整字段、AMBIGUOUS、事实缺口、警告计数、目标列绑定一行、本文档的结构推断项统计，末尾"治理线索"小节**只逐条渲染 `severity = warn` 的 `findings[]`**（一条都没有时写"治理线索：无"），`info` 级的汇成一行"信息项：N（见 semantic.json findings）"（N 为 0 时不写这行）；有警告时指向 `scope-lineage render` 生成的 `warnings.md`（`describe` 自己不写这个文件） | `confidence`、`diagnostics.json` |
| 7. 给 Agent 的说明 | agent | 固定三行：本文档是事实骨架；业务画像另按 prompt 生成；未标 `元数据事实` 的中文含义都不是业务定义 | 固定文本 |

- 章节编号固定：`--sections` 只是隐藏章节，**从不重编号**，所以"第 5 节"在任何一份文档里都指同一件事。
- `fields_table` 不是第八节，而是第 5 节的**子开关**：传它（而不是 `fields`）会保留"完整字段清单"
  表格、去掉逐字段小节——112 个字段的大任务给人读时正需要这个。传 `fields_table` 时 `fields`
  自动生效，不必同时写。

## 行语法（semantic-md/1）

机器可读性由 `semantic.json` 提供；md 的行语法只保证下面这几条。

### front matter

语句文档的文档头是一个**扁平**的 YAML front matter 块：每行 `key: value`，value 一律是 JSON
标量（可直接 `json.loads`）。不含时间戳、不含渲染器版本，保证同输入渲染字节一致。键固定为：

```yaml
---
doc_format: "semantic-md/1"
schema_version: "1.0"
task_name: "..."
target_table: "..."
stmt_kind: "..."
lineage_digest: "..."
---
```

`lineage_digest` 与 mapping.md 用的是同一个函数
（`scope_lineage.render.mapping_markdown.lineage_document_digest`，键排序紧凑 JSON 的 SHA-256
前 16 位），所以同一份 `lineage.json` 派生出的 mapping.md 与 semantic.md 摘要相同——可据此确认
两份派生文档来自同一快照。

任务文档的头不是 front matter：先一行 `# 任务语义描述：<task_id>`、一行"共 N 条写入语句；
最终产出表：…"，随后每条写语句一个 `## <statement_id>` 小节，节内是该语句的完整文档
（含它自己的 front matter）。

### 标签后缀与证据 id

每一行都以来源标签结尾，四个标签共用一套语法：

```
（<标签>[；证据 <id>[, <id>]]）
```

- `<标签>` 取 `SQL事实`、`元数据事实`、`SQL事实+元数据事实`、`结构推断`、`SQL注释` 之一。
- `SQL注释` 是唯一一个**不由本文档推导**的标签：它标记的文字是 SQL 作者写的原话，本文档只负责原样引用。带该标签的内容**从不放进 code span**——code span 在本文档里的语法含义是「逐字的 SQL 标识符或表达式」，把自由文本放进去会被人和反编造检查都读成一个真实标识符。
- `证据` 后是逗号分隔的契约 id：`logic_block_id`、`mapping_chain_id`、`scope_id`、
  或表名。没有可引的 id 时整个"；证据 …"部分省略，只留 `（<标签>）`。
- 动作行同时带 `evidence` 与 `consumed_by` 时两个 id 都列出（窗口意图要靠下游的 `= 1` 过滤
  才成立，证据链必须写全）。
- 表达式一律放在 code span 里，围栏长度随表达式内含的反引号增长；表格单元格内的 `|`
  转义为 `\|`；渲染值中的真实换行归一化为字面量 `\n`，保证"一行一个事实"。

### 不确定性记号

固定用 `⚠` 标注，绝不把猜不出来的东西写成事实：

- 第 2 节：`⚠ 有放大风险`（`risk`）/ `⚠ 未知`（`unknown`）；形态判不出时 `⚠ 粒度：未能判定（basis=unknown）`；键成立但没写进目标表时 `⚠ 键：…未输出到目标表；目标表列 … 不能唯一标识一行（key_confidence=proven_unexposed）`；
- 第 1 节输入表元数据列：`⚠ 不完整` / `⚠ 未知`；
- 第 5 节：步骤行 `⚠ 粒度=unknown`、追溯行 `⚠ 追溯：不完整——<原因>`、完整字段清单的追溯列 `⚠`；
- 第 6 节：`⚠ 追溯不完整字段`、`⚠ AMBIGUOUS 字段`、`⚠ 无 diagnostics 文档`、
  目标表列注释不可用时 `⚠ 不可用——字段语义退化为来源注释加加工复述`。

### 折叠与截断规则

长文档会折叠，但**折叠从不丢 id**：

| 规则 | 阈值 | 行为 |
| --- | --- | --- |
| 第 3 节阶段折叠 | 阶段数 > 12 | `pattern_signature` 相同的阶段合并成一张表（表里列出**全部**拓扑序号与 `scope_id`、角色、直接输入、动作摘要、输出列数，标题写"阶段 2、5、6 等 3 个同模式阶段"），并把其中第一个展开为 `####` 小节作代表；ROOT 永远单独展开 |
| 第 3 节来源边界行 | 恒定 | `上游物理表（来源边界）` 与本阶段的直接输入相同、或与上一阶段相同时省略该行（JSON 不动） |
| 第 3 节 `derive` 动作 | 同 scope 内 > 8 条 | 折叠为"派生 N 列：a、b、c…（前 3 条展开）"，其余动作行不再逐条列出 |
| 第 4 节同构规则族 | 同 `kind` / `scope`、把数字字面量替换成 `N` 后表达式相同的 ≥ 3 条 | 合并成一行"rule:021–032（12 条）：`<模板表达式>`（N 取 9…20）"；每条含多个数字时不猜哪个是 N，写"各条取值见 semantic.json rules[]" |
| 第 5 节连续透传步骤 | ≥ 2 步 | 连续的 `direct_projection` / 单分支 `union` 折叠为"第 k–m 步：直接透传（经 scopeA → scopeB → …）"；同属 UNION 分支的一段写成"各分支直接透传（经 A、B）"，**不用箭头**——各分支是并列关系，不是先后 |
| 折叠表的动作摘要 | 120 字符 | 超出部分截断为 `…`，完整动作在代表阶段或 `semantic.json` 里 |
| 阶段输出列 | 20 列 | 超出只写列数与前 20 个列名 |
| CASE 分支复述 | 6 个分支 | 超出折叠为"N 个分支，前 3 个：…"，完整分支在 `rules[].branches[]` |
| 结构推断项清单 | 恒定 | 第 6 节只按 `semantic.json` 路径分组计数，完整清单在 `confidence.inferred_items` |

`semantic.json` **从不折叠**：任何被 md 折叠或截断的内容都能在 JSON 里拿到全量。

### chunk 自包含

第 5 节每个字段一个 `###` 小节，标题用 `column_label` 携带完整身份
（`### 字段 <目标表>.<字段>`）；目标为 `directory:` 写入时按目录命名，不拼造伪表名；未绑定目标列
时不拼 `<目标表>.<字段>`——命名规则与 mapping.md 一致，按 `###` 切块后任一小节单独检索仍能自我定位。
第 3 节每个阶段一个 `###` 小节，标题带 `scope_id` 与角色，同样可单独切块。

## 节选：examples 实跑产物

下面是 `examples/tasks/customer/customer_profile_daily.json` 经 `parse` → `describe` 后
`semantic.md` 第 2 节的**原样输出**（非手写示例）：

```markdown
## 2. 输出表形态与粒度

- 形态：关联补充型投影（enriched_projection）（结构推断；证据 logic:ROOT:join:001, logic:ROOT:join:002）
- 粒度：一行对应 `ods.customer_base` 的一行（依据主表行，basis=driving_table_rows）（结构推断；证据 ods.customer_base）
- 候选键：目标表列 `customer_id`——仅为候选，输入中无主键声明（分区内）（key_confidence=candidate）（结构推断）
- 分区列：`dt`；分区列不计入候选键（元数据事实）
- 行数放大风险：
  - LEFT_OUTER JOIN `cte:latest_status`：安全（safe）——右侧 row_number 按 customer_id 分区并以 = 1 过滤（logic:ROOT:join:001）（结构推断；证据 logic:ROOT:join:001）
  - LEFT_OUTER JOIN `cte:order_summary`：安全（safe）——右侧按 dwd.order_detail.customer_id GROUP BY，键集被连接键覆盖（结构推断；证据 logic:ROOT:join:002）
```

读法：两条 JOIN 都判成 `safe`，是因为右侧分别被证明按连接键唯一（一个 `row_number() = 1`、
一个 `GROUP BY` 键集被连接键覆盖）；只承认这类可证明形态，右侧是物理表时一律 `unknown`
——物理表不声明主键，没有事实可依。

参数路径上的 JOIN 单独列在下面一组，因为它要的动作不同：粒度链路上的放大多出来的是**行**，
参数路径上的放大多出来的是**被求和的行**，输出行数一点不变、数值却偏大。

```markdown
- 行数放大风险：
  - LEFT_OUTER JOIN `subq:v`：⚠ 有放大风险（risk）——右侧未被证明按连接键唯一（结构推断；证据 logic:ROOT:join:001）
- 影响指标取值的关联：
  - `subq:v` 中的 INNER JOIN `subq:g`：⚠ 有放大风险（risk）——右侧未被证明按连接键唯一（结构推断；证据 logic:subq:v:join:001）
```

## 确定性与 golden

同一对输入文档 describe 两次字节一致：字段按 `target_column_ordinal`（缺失时回退
`output_ordinal`，再回退原序）排序，阶段按拓扑序，规则按"scope 拓扑序 + scope 内
`logic_block_id` 序"编号成 `rule:001`…，输入表按表名排序；文档里没有时间戳、没有渲染器版本、
没有 LLM 调用、没有网络请求、没有新依赖。该性质由 golden 基线测试
（`tests/core/fixtures/lineage_contract/<case>/semantic.json` 与 `semantic.md`）锁定，
另有属性测试保证文档中出现的每个表名/列名都能在源 `lineage.json` 里找到——反编造。

## 与 mapping.md 的分工

两份文档都由同一份契约渲染，不会互相漂移，但视角不同：

- [mapping.md](mapping-doc.md) 逐 scope 给技术细节：字段映射总表、逐步加工链、scope 逻辑汇总、
  mermaid 结构图。问"这一列到底从哪来、中间经过哪些 scope"读它。
- semantic.md 按拓扑序复述动作并拼上注释：输出形态与粒度、阶段动作、规则清单、字段语义。
  问"这个任务在做什么、输出表一行代表什么、这个字段什么含义"读它。
- 第 3/4 节与 mapping.md 第 6 节有事实重叠，这是两个视角看同一批 `logic_blocks`，不是两份事实源。
- 选层次的完整判据见[读语句级还是任务级？](contract-selection.md)；
  产物结构见 [`lineage.json` 输出契约](lineage-json.md) 与
  [`diagnostics.json` 输出契约](diagnostics-json.md)。
