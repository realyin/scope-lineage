# 怎样正确统计血缘缺口

> 面向要产出"工具能力缺口清单"的人。**一次配错的元数据，会把 0 个能力缺口放大成上万个。**

## 为什么需要这篇

`lineage_fact_gaps` 记录的是"没能形成确定血缘事实"的地方。它诚实，但它**不区分原因**：

- 工具确实解析不了某种 SQL 形态 —— 这是能力缺口；
- 这次运行根本没拿到源表的列 —— 这不是能力缺口，是输入没配好。

两者在产物里长得**一模一样**：`missing_reasons: ["no_physical_source_fields"]`。按缺口数排优先级时，第二种会淹没第一种。

真实发生过的情况：一份缺口清单把某任务列为最大单点，`16,122` 条缺口，结论是"投影展开能力不足，优先级最高"。同一份代码、同一个任务，把该表的元数据正确加载后，缺口是 **0**。

## 判定方法：三个探针

### 探针 1（最快）：加载器到底返回了多少列

```python
from scope_lineage import load_schema_sources

schema = load_schema_sources(metadata_paths)     # 你的管线实际传进去的那份
print(len(schema.get("<db>.<source_table>") or []))   # 期望：该表的真实列数
print(schema.metadata_conflicts)                      # 期望：[]
```

- 返回 `0` 或 `None` → 列没进来，**这批缺口不是能力缺口**，先修输入。
- `metadata_conflicts` 非空 → 有文件被拒绝，里面写了原因和文件名。

注意表名要用工具归一化后的形式：

```python
from scope_lineage import normalize_table_name
normalize_table_name("catalog.db.table")
```

三段式和两段式键都能命中，**catalog 前缀不是差异来源**，不用为此排查。

### 探针 2：做一次「不传 schema」的对照

```python
from scope_lineage import parse_task_lineage

with_schema = parse_task_lineage(sql, task_name=name, schema=schema)
without     = parse_task_lineage(sql, task_name=name, schema=None)
```

如果你报告里的数字**等于** `without` 那一侧，那这份报告测的是"没有元数据"，不是工具能力。

这个对照非常灵敏：缺口数往往能逐位相同，连 `gap_sub_bucket` 的分布都一致。见下节的特征。

### 探针 3：看分布形状

缺元数据时，缺口分布会**塌缩成两三类**，且几乎全部带同一个原因：

```
{'physical_table_qualified_ref_missing': 10748, 'non_actionable_no_source_ref': 5374}
missing_reasons 全部是 no_physical_source_fields
```

真实的能力缺口分布是**散的**：`alias_binding_unresolved`、`upstream_output_unresolved`、
`root_bare_no_unique_input`、`aggregation_detail_expression_refs_missing` 等混在一起，每类几条到几十条。

**一个任务贡献四位数缺口，且只有一两个 sub_bucket** —— 这个形状本身就是元数据没进来的信号，先跑探针 1。

## 推荐的加载方式：按需，而不是一次性全加载

一次性加载整个元数据目录有两个问题：

1. **慢**：几千张表里只要有几张超宽表，加载时间就会失控。
2. **脆**：任何一份文件出问题都可能让整批失败。如果调用方用 `try/except` 兜底继续跑，
   结果是**所有任务都没有 schema** —— 而每个任务仍然照常出结果，只是全是假缺口。

按需加载：先从 SQL 里取出引用到的表，只加载这些表的元数据文件。

```python
import sqlglot
from sqlglot import exp
from scope_lineage import load_schema_sources, normalize_table_name

trees = sqlglot.parse(sql, dialect="spark")
tables = set()
for tree in trees:
    if tree is None:
        continue
    for node in tree.find_all(exp.Table):
        parts = [x for x in (node.catalog, node.db, node.name) if x]
        if len(parts) >= 2:
            tables.add(normalize_table_name(".".join(parts)))

paths = [path_of[t] for t in sorted(tables) if t in path_of]
schema = load_schema_sources(paths)
```

`load_schema_sources` 对单份文件的失败是**容忍**的：坏文件只损失那一张表，并在
`metadata_conflicts` 里留下记录，其余表照常可用。所以**不要**在外层再包一个吞掉一切的
`try/except`。

## 另外两个会让统计失真的坑

### 坑 1：用裸 `sqlglot.parse()` 统计语法状态

Core 在解析前会做规范化（例如 Spark 的 `INSERT OVERWRITE DIRECTORY ... USING <fmt>`）。
绕过它直接调 sqlglot，会把本来正常的任务算成解析失败。实测同一语料：走 Core 自身管线是
**5** 个 `recovered`，裸调 sqlglot 是 **29** 个。

统计语法状态请用 Core 的结果（`lineage.json` 的 `syntax_status`，或 v2 的
`analysis_status.blocking_reasons`）。

### 坑 2：把"被修补的解析"派生出的缺口计入能力缺口

`syntax_status = "recovered"` 表示解析器丢弃了它放不下的 token，此时的字段级缺口描述的是
截断本身。这些缺口带有 `derived_from_recovered_syntax: true`，统计时应排除。详见
[被修补的解析，以及它派生出来的"假缺口"](recovered-syntax-and-derived-gaps.md)。

## 一份缺口报告应该附带的信息

要让结论可复核，每条缺口至少记录：

| 项 | 为什么需要 |
| --- | --- |
| 该任务引用的表数 / 元数据命中数 | 命中数小于引用数，就要先解释差额 |
| 关键源表实际加载到的列数 | 探针 1，一个数就能定性 |
| `metadata_conflicts` | 有没有文件被拒绝，拒绝原因是什么 |
| `syntax_status` | `recovered` 的任务不参与能力缺口统计 |
| 「不传 schema」对照的缺口数 | 与报告数字相同即说明测的是输入问题 |
| `gap_sub_bucket` 分布 | 塌缩成一两类是元数据缺失的特征 |

## 结论怎么写才站得住

- **以真实任务的缺口数为验收标准，不以合成用例通过为准。** 合成用例可以复现症状却不复现成因。
- **归因要落到代码或 AST 层面**，而不是从 `object_name` 的字面形态推测。真实发生过的误判：
  把一个源表里真实存在的长列名，读成了"两个列名被粘连成一个 token"。
- **一个成因不要写成一条缺口。** 同一批 `alias_binding_unresolved` 背后可能是好几个互不相干
  的原因，按一个根因去修，会出现"合成用例全绿、真实任务纹丝不动"。

## 相关文档

- [`diagnostics.json` 输出契约](diagnostics-json.md) — `lineage_fact_gaps` 字段含义
- [被修补的解析，以及它派生出来的"假缺口"](recovered-syntax-and-derived-gaps.md)
- [输入格式](input-formats.md) — schema 与目标表元数据怎么传入
