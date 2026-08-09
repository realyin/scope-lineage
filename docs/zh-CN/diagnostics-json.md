# diagnostics.json 输出契约

## 1. 定位

`diagnostics.json` 是 `lineage.json` 的详细诊断伴随产物，和 Lineage 一起由最底层 Core
生成。它保存完整 warnings、统计和血缘事实缺口；`lineage.json.diagnostics` 只保留计数、类型
和少量样本，方便普通消费者快速判断质量。

两者必须来自同一次 parse，不能把不同任务或不同运行的文件配对。

## 2. 版本与 Schema

权威 Schema：

```text
lineage_parser/schemas/diagnostics.schema.json
```

顶层 `schema_version` 必填，当前固定为 `1.0`。Core 写盘前调用
`validate_diagnostics_document(document)` 校验最终文档；缺失版本、未知 major 或稳定字段类型错误
都属于生成器错误，不得发布为成功产物。1.x 内允许增加可选诊断字段。

## 3. 顶层字段

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `schema_version` | 是 | Diagnostics 对外契约版本，当前为 `1.0`。 |
| `fallback_used` | 否 | 是否使用了解析降级路径。缺省等价于 `false`。 |
| `warnings[]` | 否 | 完整警告；每项至少包含 `type`、`scope`、`msg`。 |
| `stats` | 否 | 解析器生成的统计事实。 |
| `lineage_fact_gaps[]` | 否 | 无法形成确定血缘事实的完整缺口记录。 |

## 4. 消费规则

1. 先校验 `schema_version`，再读取诊断内容。
2. `warnings` 缺省表示没有警告，不能解释为文件未生成。
3. 判断 Lineage 是否可用时同时读取 `lineage.json` 的 `parse_status`、`syntax_status` 和诊断摘要。
4. 需要定位证据或列出全部缺口时读取本文件，不要只依赖 Lineage 中的样本。
5. `lineage_fact_gaps[].evidence_path` 指向 Lineage 事实位置；修改路径或语义时必须同步更新对应契约和消费者。
