# 元数据 DDL 解析不终止修复方案（TDD）

## 1. 问题

加载某些表的元数据文档时，`load_schema` **永不返回**。调用方（CLI、按需加载、批量重跑）没有任何超时机制，表现为整个任务卡死，而不是报错。

实测：`load_schema` 读入一份 2948 列的元数据文档，90 秒未返回；另一次采样显示它在内部消耗了 7 分钟以上 CPU 仍未结束。

这是一个**可用性级别的缺陷**：任务不是结果变差，而是根本跑不出结果。批量重跑遇到这类表时，只能超时或退化成"不加载元数据"，后者会让该任务的所有字段落入 `no_physical_source_fields`，从而在缺口统计里表现为一场虚假的"能力缺口爆发"。

## 2. 根因

卡点在 [`_facts_from_ddl`](../../scope_lineage/metadata/target_table_metadata.py#L367)：

```python
tree = sqlglot.parse_one(ddl, dialect="spark", error_level=ErrorLevel.RAISE)
```

sqlglot 的 Spark 方言在解析**列名为未加引号的 `not`** 的 `CREATE TABLE` 时不终止。最小复现：

```sql
CREATE TABLE db.t (a DOUBLE, not DOUBLE COMMENT 'n')
```

`sqlglot.parse_one(..., dialect="spark")` 对这条 51 字符的语句永不返回。

已验证的边界条件：

| 变体 | 结果 |
| --- | --- |
| `not DOUBLE COMMENT 'n'`（列定义） | **挂死** |
| `NOT DOUBLE` / `Not DOUBLE`（大小写变体） | **挂死** |
| `not DOUBLE`（无 COMMENT） | **挂死** |
| `` `not` DOUBLE COMMENT 'n' ``（加反引号） | 0.006s 正常 |
| `PARTITIONED BY (not STRING)` | ParseError（走现有失败路径，不挂死） |
| `from` / `view` / `int` / `out` / `number` / `str` 作列名 | 全部正常 |
| `STRUCT<x: INT, y: STRING>`、`DECIMAL(10, 2)` | 全部正常 |
| 纯列数（合成 DDL 3000 列） | 0.07s，**无列数拐点** |

与 `error_level` 无关：`ErrorLevel.RAISE` 与默认级别都挂死。

**上游无可用修复**：CI 矩阵中的 sqlglot 30.0.0 / 30.6.0 / 30.17.0 三个版本全部复现。因此必须在本仓库这一侧防护。

### 影响面

按需加载的元数据目录中 3434 张表，DDL 含未加引号 `not` 列的有 **3 张**：

- `lods_rip_us.lods_rip_us_dlake_rip_us_cust_mx_sms_tfidf_var_3`（2958 列）
- `variables.mx_sms_vars_tfidf_p3_0428`（2948 列）
- `variables.mx_sms_vars_tfidf_p3`（2948 列）

引用到它们的任务 4 个，全部无法完成解析。任务 SQL 本身没有出现裸 `not` 列定义，所以问题只在元数据 DDL 这条路径上。

数量小，但性质是硬失败，且**无法通过重试或超时在调用方绕开**——纯 Python 的 `signal.alarm` 会被 sqlglot 内部的 `except Exception` 吞掉，实测无效。

## 3. 修复方案

在把 DDL 交给 sqlglot 之前，把列定义列表中**属于保留关键字的列名加上反引号**。

选择这个形状的理由：

- 加引号是 DDL 的等价改写，不改变我们要从中提取的任何事实（列名、分区名）。`column.name` 本来就会去掉引号。
- 比"给 `not` 打补丁"更耐用：命中条件是"列名是保留关键字"，而不是某一个词。语料里另有 6 个关键字列名（`int` / `number` / `out` / `str` / `from` / `view`），当前不触发，但一并规范化不增加风险。
- 不动"DDL 是权威结构来源"这条已定的原则，也不需要引入超时或子进程。

### 3.1 新增 `_quoted_keyword_column_names(ddl)`

位置：`scope_lineage/metadata/target_table_metadata.py`，`_facts_from_ddl` 之上。

```python
def _quoted_keyword_column_names(ddl: str) -> str:
    """给列定义中属于保留关键字的列名加反引号，再交给 sqlglot。

    sqlglot 的 Spark 方言解析列名为未加引号 `not` 的 CREATE TABLE 时不终止
    （30.0.0 / 30.6.0 / 30.17.0 均复现，加引号即恢复）。元数据 DDL 由平台导出，
    这类列名合法且真实存在，不能因此丢掉整张表；而纯 Python 无法给 sqlglot 加
    超时，所以只能在送进去之前消除触发条件（METADATA-002）。
    """
```

实现要点：

1. 定位列定义列表：`CREATE ... (` 之后与之配对的 `)`。用括号深度配对，不用正则匹配整体。
2. 在深度 0 处按逗号切分。深度同时计入 `(` `)` 与 `<` `>`，否则 `DECIMAL(10, 2)` 与 `STRUCT<x: INT, y: STRING>` 里的逗号会被误切。
3. 每段取首个 token；若它是未加引号的标识符且大写形式命中 `Spark.Tokenizer.KEYWORDS`，替换为反引号包裹形式。大小写不敏感。
4. 任何一步无法确信地定位（括号不配对、找不到列表），**原样返回**，把判断交给既有的解析失败路径。

### 3.2 `_facts_from_ddl` 接入

```python
    try:
        tree = sqlglot.parse_one(
            _quoted_keyword_column_names(ddl),
            dialect="spark",
            error_level=ErrorLevel.RAISE,
        )
```

其余逻辑不变。`ddl` 字段本身仍原样保存在 `TargetTableMetadata.ddl` 里——规范化只服务于解析，不改变对外呈现的 DDL 文本。

## 4. TDD case

新建 `tests/core/test_metadata_ddl_keyword_columns.py`。全部夹具为合成 SQL，不含任何真实表名。

| # | 用例 | 断言 |
| --- | --- | --- |
| T1 | `_quoted_keyword_column_names("CREATE TABLE db.t (a DOUBLE, not DOUBLE COMMENT 'n')")` | 返回值中 `not` 被反引号包裹，`a` 不变 |
| T2 | 大小写变体 `NOT` / `Not` | 同样被包裹（命中条件大小写不敏感） |
| T3 | `STRUCT<x: INT, y: STRING>` 与 `DECIMAL(10, 2)` 混合的列表 | 类型内部的逗号不被当作列分隔符，输出与输入等价 |
| T4 | 列名全部非关键字 | **返回值与输入逐字节相同**（不做无谓改写） |
| T5 | 括号不配对的残缺 DDL | 原样返回，不抛异常 |
| T6 | `_facts_from_ddl` 处理含 `not` 列的合成 DDL | 返回列名 `["a", "not"]`，`issues` 为空 |
| T7 | `_facts_from_ddl` 处理 `PARTITIONED BY (not STRING)` | 记 `ddl_parse_failed:ParseError`，不挂死（钉住现有行为） |
| T8 | 一份含 `not` 列的合成 rich metadata 文档经 `load_schema_sources` 加载 | 该表列数完整，`metadata_conflicts` 为空 |
| T9 | 同一批里另有一份正常文档 | 两张表都在，互不影响 |

**关于 T6 的取舍**：如果 3.1 的规范化被改坏，T6 会**挂起**而不是失败，这对 CI 不友好。缓解办法是让 T1–T5（纯字符串函数，毫秒级）先跑并覆盖全部规范化行为——规范化一旦回归，T1 就会先失败并指明原因。T6 在断言前先 `assert "`not`" in normalized`，把"没规范化就别去解析"变成显式前置条件。

## 5. 开发步骤

1. 先写 T1–T5，红。
2. 实现 `_quoted_keyword_column_names`，转绿。
3. 写 T6–T9，红（T6 此时会挂起——这正是缺陷本身，确认后再接入）。
4. `_facts_from_ddl` 接入规范化，转绿。
5. 跑 CI 闭包与两份逐字节基线。

## 6. 验证方法

| 项 | 判据 |
| --- | --- |
| 单测 | `python -m pytest -q tests/core tests/architecture/test_core_boundaries.py` 全绿 |
| 逐字节基线 | `lineage_contract/` 与 `task_lineage_contract/` **零差异**（本改动不影响任何已有夹具的输出） |
| sqlglot 矩阵 | 30.0.0 / 30.6.0 / 30.17.0 三档下 T1–T9 全绿 |
| ruff | `python -m ruff check scope_lineage tests` 干净 |
| 真实语料（仓库外） | 4 个受影响任务（`rt_variables_mx_sms_vars_tfidf_p3`、`prd_mx_mgt_bd016_bd017_model_var`、`prd_mx_mgt_c003_c005_01_model_var`、`prd_mx_mgt_bd020_model_var`）从"永不返回"变为**在秒级完成**，且 `analysis_status` 不是因本改动引入的新告警 |
| 回归面 | 随机抽取 100 个此前正常的任务，缺口数与状态与改动前**逐任务一致** |

真实任务、业务元数据与解析产物一律留在仓库外，路径通过环境变量传入。

## 7. 实施结果（已完成）

### 规范化的实际影响面

对按需加载目录中全部 3269 份带 DDL 的元数据文档跑规范化，并逐份对比「改写前后提取出的列」：

| 结果 | 数量 |
| --- | --- |
| 被改写 | 314 |
| 改写前后提取结果**逐条一致** | 308 |
| 原本挂死 → 现在解析出 2948–2958 列 | 3 |
| 原本 `ddl_parse_failed:ParseError`（整表被拒）→ 现在解析出 3005–3013 列 | 3 |
| 回归 | **0** |

后 3 项是意外收获：`like` 作列名不挂死但会 ParseError，三张表因此被整张丢弃、损失 3000+ 列。同一条规则把它们一起救回来了，已补测试 `test_keyword_column_that_only_failed_to_parse_is_also_recovered` 钉住。

### 受影响任务

| 任务 | 修复前 | 修复后 |
| --- | --- | --- |
| `prd_mx_mgt_bd016_bd017_model_var` | 永不返回 | `complete` gaps=0，3.2s |
| `prd_mx_mgt_c003_c005_01_model_var` | 永不返回 | `complete` gaps=0，14.7s |
| `prd_mx_mgt_bd020_model_var` | 永不返回 | `complete` gaps=0，13.7s |
| `rt_variables_mx_sms_vars_tfidf_p3` | 永不返回 | `partial` gaps=1298，1.7s（见下） |

### 验证记录

| 项 | 结果 |
| --- | --- |
| CI 闭包 | 174 passed（原 160 + 新增 14） |
| sqlglot 矩阵 | 30.0.0 / 30.16.0 / 30.17.0 三档均 174 passed |
| 两份逐字节基线 | 零差异 |
| ruff / build / 分发边界 | 全部通过 |

## 8. 验证中新发现：同一个关键字问题在**语句侧**也存在

`rt_variables_mx_sms_vars_tfidf_p3` 修复后能跑完，但残留 1298 个 gap，根因**不是** DDL：它的任务 SQL 自身写了

```sql
,CAST(NOT AS DOUBLE) AS NOT
```

即把 `NOT` 当列名引用。这里 sqlglot 不挂死，但会把语句解析歪——`FROM hw_jhy_iceberg.lods_rip_us....` 整个被吞掉，`find_all(exp.Table)` 只剩目标表，于是该语句的全部投影列都无源可绑。

**未纳入本次修复，理由**：

- 规模是 1755 个任务中的 **1 个**。
- 修法不能照搬。DDL 的列定义列表里，「首个 token 就是列名」是确定的；而在任意表达式位置，无法在不解析的前提下区分「关键字作标识符」与「关键字作语法」——而解析正是失败的那一步。为一个任务在语句路径上做正则改写，风险远大于收益。

已单独记录在此，供后续决定。若日后这类 SQL 变多，应作为独立缺口立项。

## 9. 已知边界

- `PARTITIONED BY (not STRING)` 仍是 ParseError。它不挂死，走既有的"该表不可用"路径，语料中未出现。若日后出现，同一规范化思路可扩展到分区列表，但那是另一处代码位置，不在本次范围内。
- 规范化只覆盖列定义列表。DDL 其它区域（TBLPROPERTIES、COMMENT）不改写。
- 这是绕开上游缺陷的防护。若 sqlglot 日后修掉，本函数仍然无害（对非关键字列名逐字节不变），可以保留。
