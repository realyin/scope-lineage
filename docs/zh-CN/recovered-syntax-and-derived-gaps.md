# 被修补的解析，以及它派生出来的"假缺口"

> 面向读取 `lineage.json` / `diagnostics.json` 的人，以及统计缺口数量的人。

## 一句话

`syntax_status = "recovered"` 意味着**这条 SQL 没有按原样解析成功**，解析器丢掉了它放不下的 token。此时同一份产物里的字段级缺口（`lineage_fact_gaps`）**不是能力缺口**——它们是"语句被截断"这一个问题的下游影子。把它们计入能力缺口统计，会得到一个放大几百倍的错误结论。

## 为什么会有 recovered 这档

Core 用宽松的错误级别解析（`ErrorLevel.IGNORE`）。这是一个有意的取舍：一个语料里的一条坏 SQL 不应该让整批解析停摆。代价是解析器会**静默修补**——放不下的 token 直接丢弃，返回一棵残缺的 AST，而基于残缺 AST 生成的血缘，和基于合法 SQL 生成的血缘长得一模一样。

所以 Core 会**再严格解析一遍**，只为回答一个宽松解析答不了的问题：这次解析被修补过吗？答案写在 `lineage.json` 的 `syntax_status`，v2 产物里则表现为 `analysis_status.blocking_reasons` 含 `syntax_recovered`。严格解析只做分类，实际使用的仍是宽松 AST，不会因此丢失血缘。

## 最小复现

```sql
INSERT INTO mart.t SELECT a, CAST(NOT AS DOUBLE) AS not, b FROM ods.src
```

这里 `not` 是一个**列名**。sqlglot 的 Spark 方言把 `NOT` 当运算符解析，发现它没有操作数，于是从该处开始丢弃剩余 token。实际保留下来的等价于：

```sql
INSERT INTO mart.t SELECT a, CAST(NOT AS DOUBLE)
```

`FROM ods.src` 整个消失了。后果是连锁的：

| 观察项 | 值 |
| --- | --- |
| `syntax_status` | `recovered` |
| ROOT scope 的输入边 | **0**（源表没了） |
| 输出字段 | `a`、`_col_1` |
| `lineage_fact_gaps` | 1 条，`no_physical_source_fields` |

那条缺口说的是"字段 `a` 找不到物理来源"。这句话在字面上没错，但它描述的不是这条 SQL——这条 SQL 明明写了 `FROM ods.src`。真正的事实只有一条：**语句没解析成功**。

放大到真实规模就是问题所在：某个 1755 任务语料里，一个 153 KB 的任务因为同样的原因只保留了 41% 的文本，随之产出 **1298 条字段级缺口**。如果按缺口数排能力缺口优先级，这一个语法问题会排到榜首，并被描述成"投影展开能力不足"。

## 语料里真实出现的三种形态

在一个 1755 个任务的真实语料上，走 Core 自身管线的统计是 **1750 `strict_ok` / 5 `recovered`**。这 5 个分成三类：

### 1. 保留字被当作列名（3 个任务）

列名是 `not`、`like`、`using`。这是**合法的表列名**——Spark 允许，平台导出的表里也确实存在——但在 SQL 里未加反引号引用时，解析器会按关键字去理解。

正确写法是加反引号：

```sql
SELECT `not`, `like`, `using` FROM ods.src   -- 解析正常
```

同一个成因也曾出现在**元数据 DDL** 那一侧，且后果更严重：`CREATE TABLE db.t (a DOUBLE, not DOUBLE)` 会让 sqlglot **永不返回**（30.0.0 / 30.16.0 / 30.17.0 均复现）。这一侧已由 Core 在解析前给保留字列名加引号解决，见
[元数据 DDL 解析不终止修复方案](metadata-ddl-parse-hang-fix-plan.md)。语句这一侧没有采用同样的做法，原因见下一节。

### 2. SQL 本身就是错的（2 个任务）

```sql
FROM hw_jhy_iceberg.report_csc_ana.pjl_mxg_xma_id_question_log_di
WHERE
GROUP BY 1, 2, 3
```

`WHERE` 后面是空的。这不是工具的能力缺口，是任务 SQL 写错了。这种情况下 `recovered` 就是**正确且完整的输出**，不存在"修好它"这回事。

### 3. Spark 特有写法（已处理，不再出现）

`INSERT OVERWRITE DIRECTORY '...' USING parquet SELECT ...` 是合法 Spark 语法但 sqlglot 不支持。Core 在解析前会把它规范化成 sqlglot 能保住 SELECT 的形式，因此这类任务现在都是 `strict_ok`。

> 提醒：如果绕过 Core 直接调 `sqlglot.parse()` 做统计，这一类会重新变成 `recovered`，从而把 5 个虚报成 29 个。任何关于语法状态的统计都应当走 Core 自身的管线。

## 为什么不去自动修补语句 SQL

保留字列名这一类，理论上可以"给出错位置的那个词加引号再重解析一遍"。我们做了原型并在真实任务上验证，结论是**不做**，理由是实测的：

- **5 个任务里 3 个够不着**。有两个的解析错误信息里没有表达式类和位置，无从定位。
- **唯一修成功的那个没有收益**。文本保留率 92% → 92%，源表数 2 → 2，血缘没有实质恢复。
- **最危险的一个差点被误修**。空 `WHERE` 那条 SQL，给 `WHERE` 加引号后**能干净地解析**——因为它变成了一个列名。严格解析这道闸门完全分辨不出来，产出的会是**另一个查询的血缘**。挡住它只能靠一份手工维护的子句关键字黑名单，而黑名单漏一个词，代价就是一份自信的错误答案。

这正是本仓库"事实与猜测分开"约定要防的事：**宁可报缺口，不给自信的错误答案。**

## 读取产物时的正确顺序

1. **先看 `syntax_status`**（v1）或 `analysis_status.blocking_reasons` 是否含 `syntax_recovered`（v2）。
2. 若为 `recovered`，**先不要读字段级血缘和缺口**。此时唯一可靠的结论是"这条语句没解析成功"，应当回到 SQL 本身。
3. 统计能力缺口时，**排除 `syntax_status = recovered` 的任务**，否则一条语法问题会被计成上千条能力缺口。
4. 只有 `strict_ok` 的产物，其 `lineage_fact_gaps` 才是关于工具能力或元数据完整性的事实。

为降低第 3 步被遗漏的概率，来自被修补解析的字段级缺口会带一个可选标记，消费方可以直接过滤，无需回头查 `syntax_status`：

```json
{
  "gap_id": "lineage_gap:0001",
  "object_name": "a",
  "gap_type": "expression_source_unresolved",
  "missing_reasons": ["no_physical_source_fields"],
  "derived_from_recovered_syntax": true
}
```

该字段只在 `syntax_status = "recovered"` 时出现，属契约 v1 允许的可选追加字段；`strict_ok` 的产物逐字节不变。

## 相关文档

- [`lineage.json` 输出契约](lineage-json.md) — `syntax_status` 字段定义
- [`diagnostics.json` 输出契约](diagnostics-json.md) — `lineage_fact_gaps` 结构
- [元数据 DDL 解析不终止修复方案](metadata-ddl-parse-hang-fix-plan.md) — 同一成因在元数据侧的形态与修复
