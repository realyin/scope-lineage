# `lineage.json` 输出契约

## 1. 定位

`lineage.json` 是 Scope Lineage 的主事实契约。它保存 SQL 解析状态、scope 图、字段来源、
端到端血缘和确定性的 scope 投影。完整告警与缺口明细放在同目录的 `diagnostics.json`。

权威 JSON Schema：

```text
lineage_parser/schemas/lineage.schema.json
```

## 2. 版本规则

顶层 `schema_version` 必填，当前固定为 `1.0`。

- 1.x 可以增加可选字段；消费者必须忽略未知可选字段。
- 删除、改名、改变字段类型或语义必须升级 major。
- 缺失版本或未知 major 会在写盘前被拒绝。

## 3. 顶层核心字段

Schema 是字段完整性的最终权威；以下是消费时最常用的分组：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 契约版本，当前为 `1.0`。 |
| `task_id` / `task_name` | 本次解析结果的稳定标识和显示名称。 |
| `statement_type` | 解析到的 SQL 语句类型。 |
| `parse_status` | `ok` 或 `failed`；消费 scope 前必须先检查。 |
| `syntax_status` / `syntax_errors` | 语法检查状态与错误证据。 |
| `target_table` | INSERT/MERGE 的目标表观察结果。 |
| `scopes` | 以 scope ID 为键的查询块事实。 |
| `scope_graph` | scope 节点之间的有向依赖边。 |
| `end_to_end_lineage` | 从 scope 图确定性推导的目标字段到物理来源链路。 |
| `scope_profile` | scope 图的确定性摘要，不是业务画像。 |
| `diagnostics` | 告警和缺口的轻量摘要。 |
| `related_metadata` | 调用方提供的通用元数据观察结果。 |

## 4. Scope 与字段引用

每个 scope 表示一个独立查询块，例如 ROOT、CTE、子查询或 UNION 分支。字段来源中的 `scope`
引用必须指向：

- 当前文档中存在的 scope ID；
- 已识别的物理表；
- 契约定义的特殊来源，例如常量、系统值、UNKNOWN 或 AMBIGUOUS。

`write_lineage()` 在写盘前同时执行 JSON Schema 校验和交叉引用校验。悬空 scope、字段或图边会
导致写盘失败，不能形成“结构合法但引用损坏”的成功产物。

## 5. 降级与失败

- `parse_status=failed` 时，`scopes` 可能为空；这表示没有解析成功，不表示 SQL 没有血缘。
- `syntax_status` 为 recovered/failed 时，必须结合 `syntax_errors` 与 `diagnostics.json` 判断。
- 缺少 Schema 时，`SELECT *` 可以保留 `*` 占位，并通过 warning 明确降级。
- 无法证明来源的字段必须保留 UNKNOWN/AMBIGUOUS 证据，不能静默删除。

## 6. 推荐消费顺序

1. 校验 `schema_version` 和 JSON Schema；
2. 检查 `parse_status`、`syntax_status`；
3. 查看 `diagnostics` 摘要，必要时读取 `diagnostics.json`；
4. 按 `scope_graph` 消费 scopes，或读取可复算的 `end_to_end_lineage`；
5. 对 UNKNOWN、AMBIGUOUS 和 fact gaps 保留人工或下游处理状态。

Python 消费方可以直接调用：

```python
from lineage_parser import validate_lineage_document

validate_lineage_document(document)
```
