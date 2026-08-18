# 投影绑定类缺口修复方案（TDD）

## 0. 范围与状态

外部缺口清单把这批问题归成一条"缺口⑨ CTE/子查询引用别名未绑定"。**实测不成立：这是 5 个互相独立的能力缺口**，共 178 个 gap、6 个任务。按一个根因去修，会出现"合成用例通过、真实任务不动"。

按定位状态分成两组：

| 子缺口 | gap 数 | 涉及任务 | 状态 |
| --- | --- | --- | --- |
| A. UNION 分支映射在合成 scope 命名空间中解析 | 32 | `batch_strategy_tools`、`01_perform_analysis_task` | **根因已确认，可开发** |
| B. PIVOT 未建模 | 32 | `lyn_deducted_channel` | **根因已确认，可开发** |
| E. 正则通配投影后未重试裸列归属 | 6 | `lxs_jhy_batch_adjcrdt_regular` | **根因已确认，可开发** |
| C. CTE 投影与下游引用 | ~27 | `pjl_bi_mxg_session_kelianlv_daily_d_di` 等 | 症状确认，**根因未定位** |
| D. 裸列上的 struct 成员访问 | 18 | `mapp_iceberg_tbls_df` | 症状确认，**根因未定位** |

A + B + E = **70 个 gap，占 39%**，三条都有合成复现，可以直接进入开发。C、D 见第 5 节，里面记了已经被排除的假设，避免重复试错。

---

## A. UNION 分支映射在合成 scope 命名空间中解析（32）

### 证据（`batch_strategy_tools`）

```text
scope union:main        输入边=0   outputs=16
scope union:main:b01    输入边=2   a -> cte:cust_details, b -> cte:rcs_send_details
scope union:main:b02    输入边=2   a -> cte:cust_details_no_round, b -> cte:rcs_send_details
```

```json
{"scope_id": "union:main", "object_name": "send_dt@union:main:b01",
 "object_type": "output.union_branch_mapping", "expression_sql": "`a`.`dt`",
 "missing_reasons": ["no_physical_source_fields"], "candidate_source_ids": null}
```

### 根因

分支映射表达式写在**分支的别名命名空间**里（`a` 绑在 `union:main:b01` 上），却在**合成 UNION scope** 的命名空间里解析。合成 scope 是集合运算节点，按设计输入边为 0，`a` 在那里永远解析不了。

分支 scope id 现成可得：既在 `object_name` 的 `@` 之后，也在分支映射记录里。

### 方案

解析 `output.union_branch_mapping` 事实时，用**该映射所属分支 scope** 的输入边与别名绑定作为上下文，而不是事实所在 scope 的。表达式解析入口需要接受一个"解析上下文 scope"参数，默认仍是事实所在 scope。父 output 的 `union_branch_mapping_unresolved` 在所有分支映射解析成功后自然消失。

### TDD case（合成）

| # | 用例 | 断言 |
| --- | --- | --- |
| A1 | 两分支 UNION，各自 `FROM` 一张物理表并起别名 `a`，投影 `a.col` | 两条分支映射解析到各自物理表列，无 gap |
| A2 | 两分支别名同为 `a` 但指向不同表 | 各自解析到**各自**的表，不串味 |
| A3 | 分支内是 JOIN，投影引用 join 侧别名 | 解析到 join 侧表列 |
| A4 | 某分支确实无法解析 | 只有该分支的映射产生 gap，父 output 仍标 `union_branch_mapping_unresolved`，另一分支不受牵连 |
| A5 | 三层嵌套 UNION | 按最内层分支的命名空间解析 |

### 验收

`batch_strategy_tools` 44 → ≤ 26；`01_perform_analysis_task` 64 → ≤ 50。两份逐字节基线零差异。

---

## B. PIVOT 未建模（32）

### 证据

代码库中对 `exp.Pivot` **零处理**（`grep -rn "Pivot" scope_lineage/` 无结果）。

合成复现：

```sql
INSERT INTO mart.t SELECT p.A AS a_val, p.B AS b_val
FROM (SELECT k, v, amt FROM ods.src) PIVOT (max(amt) FOR k IN ('A', 'B')) p
```

```text
scope subq:_0: 输入边=[('ods.src', 'src')]   k / v / amt 均 resolved
scope ROOT:    输入边=[('subq:_0', '_0')]     a_val | `p`.`a` | unresolved
                                              b_val | `p`.`b` | unresolved
```

真实任务 `lyn_deducted_channel` 的 32 个 gap 形态完全一致：`AVG(t1.dpmaf034score)` 解析不到源，而同一 scope 内其它 `t1.*` 列正常——不是 scope 或别名的普遍问题，只是 PIVOT 这一种形态没有输出列。

### 根因（两个子问题）

1. **PIVOT 的别名没有注册成输入源**。ROOT 的输入边是内层子查询 `('subq:_0', '_0')`，别名 `p` 根本不在输入边里，所以 `p.a` 连别名都绑不上。
2. **PIVOT 的输出列没有推导**。输出列名来自 `IN` 列表的字面量（sqlglot 里在 `Pivot.args['fields']`），值来自聚合表达式（`Pivot.expressions`）。

### 方案

把 PIVOT 建模成一个产出列的关系节点：

- 输入边用 PIVOT 的别名（`p`），指向被 pivot 的子查询；
- `IN` 列表中每个字面量成为一个输出列，其血缘指向聚合函数内部引用的列，并保留 `FOR` 键列的来源；
- 带别名的 `IN` 项（`'x' AS y`）以别名为列名；
- `IN` 列表非字面量（子查询、`ANY`）时不推导，记一条事实缺口而不是猜——符合"不确定就报缺口"的约定。

### TDD case（合成）

| # | 用例 | 断言 |
| --- | --- | --- |
| B1 | 单聚合 PIVOT，`IN` 三个字面量 | 产出三个输出列，列名等于字面量 |
| B2 | 下游 `SELECT p.<literal>` 引用 | 解析到聚合表达式内部的源列，无 gap |
| B3 | PIVOT 别名出现在输入边 | ROOT 的输入边包含 `p`，而不是内层子查询别名 |
| B4 | `IN ('x' AS y)` 带别名 | 输出列名为 `y` |
| B5 | `IN (SELECT ...)` 动态列表 | 不推导，产生 `lineage_fact_gap` 而非错误绑定 |

### 验收

`lyn_deducted_channel` 32 → 0。两份基线零差异（现有夹具无 PIVOT）。

---

## E. 正则通配投影后未重试裸列归属（6）

### 证据（合成复现）

```sql
INSERT INTO mart.t
SELECT t1.a, b, t2.c
FROM (SELECT `(rk)?+.+` FROM ods.src) t1
JOIN (SELECT id, c FROM ods.other) t2 ON t1.a = t2.id
```

```text
subq:t1 正则展开后输出: ['a', 'b']
ROOT:  a | 't1.a' | resolved
       b | 'b'    | unresolved     <- 缺口
       c | 't2.c' | resolved
```

把正则通配换成普通的 `SELECT a, b`，同一条语句 **0 缺口**——`b` 会被 qualify 补成 `` `t1`.`b` ``。

真实任务 `lxs_jhy_batch_adjcrdt_regular` 一致：`temp_lim`、`last_cash_refuse_date` 只存在于 `subq:t1` 的输出中（`subq:t2` 只有 3 个输出列且都不匹配），归属其实唯一，却报 `no_physical_source_fields`。

### 根因

正则通配列选择的展开发生在 **qualify 之后**。qualify 运行时 `t1` 的列集还不可知，无法给裸列补限定符；等我们展开出列集之后，**没有重新尝试裸列的归属**。信息在展开后就已具备，只是没人再看一眼。

### 方案

在正则展开使上游列集变为已知之后，对仍未解析的裸列重试归属：按名在各输入 scope 的已知输出列中查找，命中唯一则绑定，命中多个仍报 `root_bare_no_unique_input`（那是正确的模糊性报告）。这与仓库既有的"重复到不动点"若干遍解析是同一模式。

### TDD case（合成）

| # | 用例 | 断言 |
| --- | --- | --- |
| E1 | 上文合成语句 | `b` 解析到 `ods.src.b`，0 缺口 |
| E2 | 裸列名在两个上游都存在 | 仍报 `root_bare_no_unique_input`（模糊性是事实，不该猜） |
| E3 | 裸列名在任一上游都不存在 | 仍报缺口，不做无中生有的绑定 |
| E4 | 普通 `SELECT a, b`（非正则）上游 | 行为逐字节不变（回归护栏） |

### 验收

`lxs_jhy_batch_adjcrdt_regular` 6 → 0。两份基线零差异。

---

## 5. 尚未定位的两条（C、D）

**这一节记录已经被证伪的假设，下一位不必重试。**

### C：CTE 投影与下游引用（~27，`pjl_bi_mxg_session_kelianlv_daily_d_di` 等）

症状：`` `all_ming`.`brief_sum2_cn` `` 解析不到源，`all_ming` 是一个 `a.*` + `COALESCE` 列的 CTE。

**已排除**：不是"CTE 的 `a.*` 展不开"。合成用例

```sql
WITH c AS (SELECT a.*, COALESCE(b.x, 0) AS x FROM ods.src a LEFT JOIN ods.other b ON a.id = b.id)
SELECT c.id, COUNT(DISTINCT c.name) FROM c GROUP BY c.id
```

**0 缺口**，CTE 星号正常展开、下游按名引用正常解析。

下一步：直接 dump 真实任务中 `all_ming` 这个 CTE scope 的输入边与已知列集，找出它与合成用例的结构差异，而不是继续构造合成用例。

### D：裸列上的 struct 成员访问（18，`mapp_iceberg_tbls_df`）

症状：表达式为 `NAMED_STRUCT('hide', SUM(COALESCE(pt_lc_dfs_c_dis_file_on_flag.hide, 0)), ...)`，
`missing_reasons` 为 `alias_not_bound_to_input_source:pt_lc_dfs_c_dis_file_on_flag`。同一 scope 内相邻的裸列 `pt_lc_dfs_c_cnt_file` 解析正常，差别只在多了 `.hide`。

**已排除两条**：

1. 不是"struct 成员访问一律被当作表限定"。合成用例中 `SUM(flags.hide)` 与 `SUM(s.flags.hide)`（`flags` 是物理表的 struct 列）**都能正确绑定到 `ods.src.flags`**。
2. 不是"限定符是上游 scope 的输出列而解析器没查上游输出"。实测该 scope 的两个上游（`subq:a` 52 列、`subq:b` 91 列）**都没有**名为 `pt_lc_dfs_c_dis_file_on_flag` 的输出列——连解析正常的 `pt_lc_dfs_c_cnt_file` 也不在其中。

也就是说 scope 的输入边与该表达式实际引用的来源对不上，问题可能出在更早的 scope 划分，而不是表达式解析。下一步应先核对该 SQL 片段究竟属于哪个 scope，再谈绑定。

---

## 统一验证口径

| 项 | 判据 |
| --- | --- |
| 单测 | CI 闭包全绿；每个子缺口配结构用例 + 诊断用例 |
| 逐字节基线 | 两份基线零差异；若确实改变输出，须重新生成并**逐条复核 diff** |
| 真实语料（仓库外） | 涉及任务的 gap 数逐任务下降，且**不得有任何此前为 0 的任务出现新 gap** |
| 回归面 | 抽样 200 个任务，缺口数与状态逐任务对比 |

**验收以真实任务的 gap 数为准，不以合成用例通过为准。** 合成用例可以复现症状却不复现成因——本仓库已经发生过：缺口⑤的修复曾落在错误的分支里，合成用例全绿而真实任务纹丝不动。反过来也发生过：本方案中 C、D 两条的假设，正是因为合成用例**跑不出症状**才被证伪。
