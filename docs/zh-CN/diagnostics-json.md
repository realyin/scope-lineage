# `diagnostics.json` 输出契约与字段说明

## 1. 它解决什么问题

静态 SQL 解析不可能在所有输入上都得到唯一、完整的答案。常见原因包括：

- `SELECT *` 缺少 Schema，无法知道实际字段集合；
- 同名字段来自多个 JOIN 输入，SQL 又没有 qualifier；
- alias 没有绑定到唯一输入；
- 上游 scope 没有输出被引用字段；
- 平台 SQL 使用了恢复解析或自定义语法；
- 表达式只解析到逻辑 scope，还没有证明最终物理来源。

`diagnostics.json` 用于保存这些边界。它让下游区分：

- **已证明事实**：可以进入知识图谱和自动影响分析；
- **可用但有提醒**：血缘存在，但值得治理或人工关注；
- **事实缺口**：不能生成确定结论，需要补 SQL、Schema、alias 或解析能力。

它与同目录 `lineage.json` 来自同一次 parse，必须配对消费。

权威 Schema：

```text
lineage_parser/schemas/diagnostics.schema.json
```

## 2. 顶层 key/value

| Key | Value 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `schema_version` | string | 是 | Diagnostics 契约版本，当前固定为 `1.0`。 |
| `fallback_used` | boolean | 否 | 是否使用了解析降级路径；缺省等价于 `false`。它不是“结果一定错误”，但要求进一步检查 warning 和 Lineage 状态。 |
| `warnings` | array<object> | 否 | 完整警告清单；缺省或空数组表示没有 warning。 |
| `stats` | object | 否 | SQL 结构统计，用于复杂度索引和质量观测。 |
| `lineage_fact_gaps` | array<object> | 否 | 无法形成确定血缘事实的完整缺口清单。 |

成功且无 warning/缺口的最小文件可以只有：

```json
{
  "schema_version": "1.0",
  "stats": {
    "scope_count": 2,
    "physical_table_count": 1
  }
}
```

可选 key 不出现与值为空语义相同。例如没有 `warnings` 不表示文件生成失败。

## 3. `warnings[]`：提醒和治理信号

每个 warning 至少包含：

| Key | Value | 含义 |
| --- | --- | --- |
| `type` | string | 稳定的机器可分组类型。 |
| `scope` | string | 发生 warning 的 scope ID；全局问题可能使用特殊标识。 |
| `msg` | string | 面向人的证据说明，通常包含相关字段或表达式片段。 |

示例：

```json
{
  "type": "star_not_expanded",
  "scope": "ROOT",
  "msg": "SELECT * could not be expanded: no schema; missing_schema_sources=ods.raw_events"
}
```

### 3.1 Warning 与事实缺口的区别

- warning 表示“需要注意”，不一定阻断字段血缘；
- fact gap 表示某项来源事实没有被证明，必须限制下游自动化；
- 同一个任务可以既有 warning，又没有 fact gap。例如 magic number 不会阻止追溯字段来源；
- `star_not_expanded` 会降低字段完整性，但表级来源仍可能有效。

### 3.2 常见 warning 类型

实际类型会随 1.x 增加，消费者应按字符串容忍新类型。常见类型包括：

| Type | 说明 | 建议动作 |
| --- | --- | --- |
| `star_not_expanded` | 缺少 Schema 或无法确定来源列，`SELECT *` 没有展开。 | 补源表 Schema；字段级覆盖率不要按完整计算。 |
| `unresolved_alias` | 表达式 qualifier 没有绑定到输入。 | 检查 SQL alias、自定义语法或解析支持。 |
| `duplicate_alias` | 同一 scope 重复使用 alias，字段来源可能歧义。 | 修正 SQL，或结合字段/Schema 证据消歧。 |
| `column_not_found` | 字段不在任何已知来源中。 | 检查字段名和 Schema 完整性。 |
| `ambiguous_unqualified` | 未限定字段匹配多个输入。 | 给 SQL 字段增加 qualifier；不得任选来源。 |
| `filter_in_join_on_clause` | JOIN ON 中包含常量比较等行过滤。 | 影响逻辑解释时区分 join key 与 condition filter。 |
| `magic_number` | 表达式包含缺少解释的数值常量。 | 上层业务知识生成时请求口径说明。 |
| `complex_aggregate_with_case` | 聚合中嵌套 CASE。 | 指标解释应保留 CASE 分支，不只记录 SUM/COUNT。 |
| `target_field_binding_fallback` | 目标字段权威绑定没有完整应用。 | 查看 `lineage.json.target_field_binding.issues[]`。 |

warning 不是固定封闭枚举；机器处理应对已知类型设策略，对未知类型保留并展示。

## 4. `stats`：解析结构统计

公开 Core 当前常见统计：

| Key | Value | 含义与价值 |
| --- | --- | --- |
| `scope_count` | integer | 逻辑 scope 与物理来源节点总规模。 |
| `physical_table_count` | integer | 物理输入表数量。 |
| `cte_count` | integer | CTE 数量。 |
| `subquery_count` | integer | 子查询数量。 |
| `union_count` | integer | UNION scope 数量。 |
| `union_branch_count` | integer | UNION 分支数量。 |
| `max_depth` | integer | scope 依赖最大深度。 |
| `case_when_count` | integer | CASE WHEN 数量。 |
| `window_function_count` | integer | 窗口函数数量。 |
| `join_count` | integer | JOIN 数量。 |
| `aggregate_function_count` | integer | 聚合函数数量。 |

这些值可以用于检索排序和复杂度分桶，例如优先让 Agent 分析 `max_depth` 高、JOIN/UNION 多的任务；它们不能单独证明 SQL 风险或业务重要性。

## 5. `lineage_fact_gaps[]`：未证明事实

Schema 对 gap value 保持可扩展，因为不同解析缺口需要携带不同证据。Core 当前生成的公共字段如下：

| Key | Value | 含义 |
| --- | --- | --- |
| `gap_id` | string | 文档内唯一 ID，如 `lineage_gap:0001`。 |
| `gap_type` | string | 缺口大类。 |
| `gap_bucket` | string | 按表达式形态或绑定阶段划分的处理桶。 |
| `gap_sub_bucket` | string | 更具体的缺口子类。 |
| `scope_id` | string | 问题所在 scope。 |
| `object_type` | string | 受影响对象，如 `output`、`output.union_branch_mapping` 或 `aggregation_detail.aggregate_items`。 |
| `object_name` | string | 受影响字段或表达式名称。 |
| `expression_sql` | string/null | 无法完整解析来源的表达式。 |
| `expression_resolution_status` | string | 表达式解析状态，如 unresolved/partially resolved。 |
| `source_kind` | string | 当前来源类别，未确定时通常为 `unresolved`。 |
| `missing_reasons[]` | array<string> | 解析器观察到的直接原因。 |
| `needed_fact` | string | 要关闭缺口需要补充的事实。 |
| `root_impact` | boolean | 是否影响最终目标字段。 |
| `owner_hint` | string | 建议由 parser fact backfill、内部补全或 review 处理。 |
| `evidence_path` | string | 指向 `lineage.json` 中对应事实的路径。 |
| `evidence_summary` | object | scope 输入数、候选来源、目标影响等摘要。 |
| `downstream_impact` | object | 受影响的 scope 输出和最终目标字段。 |

示例：

```json
{
  "gap_id": "lineage_gap:0001",
  "gap_type": "alias_binding_missing",
  "gap_bucket": "alias_binding",
  "gap_sub_bucket": "alias_binding_unresolved",
  "scope_id": "ROOT",
  "object_type": "output",
  "object_name": "customer_id",
  "expression_sql": "x.customer_id",
  "expression_resolution_status": "unresolved",
  "source_kind": "unresolved",
  "missing_reasons": ["alias_not_bound_to_input_source:x"],
  "needed_fact": "input alias to source binding",
  "root_impact": true,
  "owner_hint": "parser_fact_backfill",
  "evidence_path": "lineage.scopes.ROOT.outputs[0]",
  "evidence_summary": {
    "has_target_impact": true,
    "scope_input_count": 2,
    "candidate_source_ids": ["ods.customer", "ods.order"],
    "candidate_output_fields": [],
    "expression_ref_count": 1
  },
  "downstream_impact": {
    "output_fields": ["customer_id"],
    "target_columns": ["mart.customer_summary.customer_id"]
  }
}
```

### 5.1 `gap_type`

| Type | 缺少什么 |
| --- | --- |
| `alias_binding_missing` | alias 到输入 scope/表的绑定。 |
| `scope_output_mapping_missing` | 上游 scope 输出字段到当前引用的映射。 |
| `expression_source_unresolved` | 表达式的物理或生成来源。 |
| `expression_resolution_incomplete` | 部分来源已知，但表达式解析尚不完整。 |

### 5.2 `gap_bucket`

| Bucket | 典型问题 |
| --- | --- |
| `alias_binding` | qualifier 没有对应输入。 |
| `upstream_output_mapping` | 引用了上游 scope 未证明的输出。 |
| `bare_unqualified_field` | 裸字段在多个或零个输入中无法唯一绑定。 |
| `qualified_expression_unresolved` | 有限定名的表达式仍未解析到来源。 |
| `other_expression_unresolved` | 其他表达式来源缺口。 |

### 5.3 如何决定是否可用于自动化

建议至少采用以下门禁：

```text
parse_status == ok
AND syntax_status == strict_ok（或调用方明确接受 recovered）
AND 目标字段 trace_complete == true
AND 目标字段不存在 root_impact=true 的 lineage_fact_gap
```

不能只看 `warnings` 数量，也不能因为 `physical_sources` 非空就忽略 `trace_complete=false`。

## 6. 与 `lineage.json.diagnostics` 的关系

`lineage.json` 只保存摘要：

```json
{
  "diagnostics": {
    "fallback_used": false,
    "warning_count": 3,
    "warning_types": {"magic_number": 1},
    "lineage_fact_gap_count": 1,
    "lineage_fact_gap_types": {"alias_binding_missing": 1},
    "lineage_fact_gap_samples": [{"gap_id": "lineage_gap:0001"}],
    "stats": {"scope_count": 6},
    "full_diagnostics_file": "diagnostics.json"
  }
}
```

| 需求 | 读取位置 |
| --- | --- |
| 列表页显示质量徽标 | `lineage.json.diagnostics` |
| 按 warning/gap 类型做聚合 | 摘要即可；需要完整对象时读伴随文件 |
| 展示全部 warning 和证据 | `diagnostics.json` |
| 定位所有受影响字段 | `diagnostics.json.lineage_fact_gaps[]` |
| 自动门禁单个字段 | Lineage 的 trace 状态 + 完整 fact gaps |

## 7. 消费示例

列出所有 warning：

```bash
jq -r '.warnings[]? | [.type, .scope, .msg] | @tsv' diagnostics.json
```

列出影响最终目标的事实缺口：

```bash
jq -r '.lineage_fact_gaps[]? |
  select(.root_impact == true) |
  [.gap_id, .gap_type, .scope_id, .object_name, .needed_fact] |
  @tsv' diagnostics.json
```

Python 质量门禁：

```python
import json
from pathlib import Path

from lineage_parser import validate_diagnostics_document

diagnostics = json.loads(Path("diagnostics.json").read_text(encoding="utf-8"))
validate_diagnostics_document(diagnostics)

blocking_gaps = [
    gap
    for gap in diagnostics.get("lineage_fact_gaps", [])
    if gap.get("root_impact") is True
]
if blocking_gaps:
    raise RuntimeError(f"lineage has {len(blocking_gaps)} target-impacting fact gaps")
```

## 8. 安全解释规则

1. `fallback_used=true` 不等于失败，但必须显示降级状态；
2. warning 是提醒，不应全部升级成阻断；
3. fact gap 是未证明事实，不得由 AI 静默猜测补全；
4. `evidence_path` 用于回到 Lineage 定位，不是文件系统路径；
5. `owner_hint` 是处理建议，不是业务责任人的身份；
6. 未知 warning/gap 类型必须保留，不能因消费者不认识而丢弃；
7. `diagnostics.json` 与 `lineage.json` 必须来自同一输出目录和同一次解析；
8. 1.x 可以增加可选诊断字段，消费者应容忍未知 key。
