# 投影绑定类缺口修复方案（TDD）

## 0. 范围与结论先行

外部缺口清单把这批问题归成一条"缺口⑨ CTE/子查询引用别名未绑定"。**实测不成立：这是 5 个互相独立的能力缺口**，共 178 个 gap，分布在 6 个任务上。把它们当成一个根因去修，会出现"合成用例通过、真实任务不动"的结果。

按类型与 scope 归类（正确加载元数据后实测）：

| 子缺口 | gap 数 | 涉及任务 | 根因确信度 |
| --- | --- | --- | --- |
| A. UNION 分支映射在合成 scope 命名空间中解析 | 32 | `batch_strategy_tools`、`01_perform_analysis_task` | **高**（已定位到 scope 输入边） |
| B. PIVOT 输出列未建模 | 32 | `lyn_deducted_channel` | **高**（SQL 形态明确） |
| C. CTE `a.*` 投影未展开，下游引用无法绑定 | ~27 | `pjl_bi_mxg_session_kelianlv_daily_d_di`、`01_perform_analysis_task` | 中 |
| D. 裸列上的 struct 成员访问被当作表限定 | 18 | `mapp_iceberg_tbls_df` | 中 |
| E. 正则通配投影 + 多输入时裸列无法归属 | 6 | `lxs_jhy_batch_adjcrdt_regular` | 中 |

其余 gap 落在上述任务的下游传播上（父 output 因分支映射未解析而带 `union_branch_mapping_unresolved`）。

建议实施顺序 **A → B → C → D → E**：A 的根因已经定位到具体数据结构，改动面最小且能连带消掉父 output 的告警；B 是独立新增能力；C/D/E 需要各自再做一轮代码级定位。

---

## 子缺口 A：UNION 分支映射在合成 scope 命名空间中解析

### 问题

合成 UNION scope 的 `output.union_branch_mapping` 事实无法解析到物理源，父 output 随之带 `union_branch_mapping_unresolved`。

### 证据（`batch_strategy_tools`）

```
scope union:main        输入边=0   outputs=16
scope union:main:b01    输入边=2   a -> cte:cust_details, b -> cte:rcs_send_details
scope union:main:b02    输入边=2   a -> cte:cust_details_no_round, b -> cte:rcs_send_details
```

gap：

```json
{"scope_id": "union:main",
 "object_name": "send_dt@union:main:b01",
 "object_type": "output.union_branch_mapping",
 "expression_sql": "`a`.`dt`",
 "missing_reasons": ["no_physical_source_fields"],
 "candidate_source_ids": null}
```

### 根因

分支映射表达式写在**分支的别名命名空间**里（`a` 绑定在 `union:main:b01` 上），却在**合成 UNION scope** 的命名空间里解析。合成 scope 是集合运算节点，按设计输入边为 0，`a` 在那里永远无法解析。

分支 scope id 已经在事实里现成可得——既在 `object_name` 的 `@` 之后，也在分支映射记录本身。

### 开发方案

在解析 `output.union_branch_mapping` 事实时，用**该映射所属分支 scope** 的输入边与别名绑定作为解析上下文，而不是所在 scope 的。父 output 的 `union_branch_mapping_unresolved` 在所有分支映射解析成功后不再产生。

改动集中在 `scope_lineage/scope/scope_facts.py` 的表达式解析入口——需要它接受一个"解析上下文 scope"参数，默认仍是事实所在 scope。

### TDD case（合成）

| # | 用例 | 断言 |
| --- | --- | --- |
| A1 | 两分支 UNION，各自 `FROM` 一张物理表并起别名 `a`，投影 `a.col` | 两条分支映射均解析到各自物理表列，无 gap |
| A2 | 两分支别名相同（都叫 `a`）但指向不同表 | 各自解析到**各自**的表，不串味 |
| A3 | 分支内是 JOIN，投影引用 join 侧别名 | 解析到 join 侧表列 |
| A4 | 某分支确实无法解析 | 只有该分支的映射产生 gap，父 output 仍标 `union_branch_mapping_unresolved`；另一分支不受牵连 |
| A5 | 三层嵌套 UNION | 分支映射按最内层分支的命名空间解析 |

### 验证

`batch_strategy_tools` 从 44 降到 ≤ 26（消掉 union合成 的 9 + 9）；`01_perform_analysis_task` 从 64 降到 ≤ 50。两份逐字节基线零差异。

---

## 子缺口 B：PIVOT 输出列未建模

### 问题

`PIVOT` 产生的列在下游被引用时无法绑定到源列。

### 证据（`lyn_deducted_channel`，32 个 gap 全部由此产生）

```sql
select ... avg(t1.DPMAF034SCORE) as avg_034, ...
from ( ... ) a
left join (
  select * from ( ... ) 
  pivot( max(value_fixed) for score in ('DPMAF034SCORE','DPMAF035SCORE', ...) )
) t1 on ...
```

gap：`{"object_name": "avg_034", "expression_sql": "AVG(`t1`.`dpmaf034score`)", "missing_reasons": ["no_physical_source_fields"]}`

同一 scope 里其它 `t1.*` 列（`prod_cd`、`app_code` 等）解析正常——说明不是 scope 或别名的问题，只是 PIVOT 这一种投影形态没有输出列。

### 根因

`PIVOT(agg(v) FOR k IN (l1, l2, ...))` 的输出列名来自 `IN` 列表的字面量，值来自聚合表达式。工具没有为 PIVOT 节点产出投影列，于是下游对这些列名的引用没有可绑定的上游输出。

### 开发方案

为 PIVOT 增加输出列推导：`IN` 列表中每个字面量成为一个输出列，其表达式血缘指向聚合函数内部引用的列（本例 `value_fixed`），并保留 `FOR` 键列的来源。带别名的 `IN` 项（`'x' AS y`）以别名为列名。

`IN` 列表非字面量（子查询、`ANY`）时不推导，改为记录一条事实缺口——符合"不确定就报缺口，不给自信的错误答案"的约定。

### TDD case（合成）

| # | 用例 | 断言 |
| --- | --- | --- |
| B1 | 单聚合 PIVOT，`IN` 三个字面量 | 产出三个输出列，列名等于字面量 |
| B2 | 下游 `SELECT p.<literal>` 引用 | 解析到聚合表达式内部的源列，无 gap |
| B3 | `IN ('x' AS y)` 带别名 | 输出列名为 `y` |
| B4 | `IN (SELECT ...)` 动态列表 | 不推导，产生 `lineage_fact_gap` 而非错误绑定 |
| B5 | 多聚合 PIVOT | 输出列名按方言规则组合，或（若不支持）产生缺口而非静默丢列 |

### 验证

`lyn_deducted_channel` 从 32 降到 0。两份基线零差异（现有夹具无 PIVOT）。

---

## 子缺口 C：CTE `a.*` 投影未展开，下游引用无法绑定

### 证据（`pjl_bi_mxg_session_kelianlv_daily_d_di`）

```json
{"scope_id": "ROOT", "object_name": "brief_sum2_cn",
 "expression_sql": "`all_ming`.`brief_sum2_cn`",
 "missing_reasons": ["no_physical_source_fields"]}
```

`all_ming` 是一个 CTE，其投影是 `a.*` 加若干 `COALESCE` 列。下游按名引用 `all_ming.brief_sum2_cn`、`COUNT(DISTINCT all_ming.session_id)` 时无法绑定。

### 待确认

星号展开已有"迭代到稳定"的实现（`scope_resolver.resolve_all`）。需要先判定：是 CTE 这一层的展开没跑到，还是展开结果没有登记为 CTE 的对外输出。**这一步定位必须先做，再定改法**——本方案不预设结论。

### TDD case 方向（合成）

CTE 内 `a.*` + 计算列，下游按名引用其中一个星号来的列与一个计算列；再加一层"CTE 引用 CTE"的传递用例。

---

## 子缺口 D：裸列上的 struct 成员访问被当作表限定

### 证据（`mapp_iceberg_tbls_df`）

```sql
named_struct(
  'hide', sum(nvl(pt_lc_dfs_c_dis_file_on_flag.hide, 0)),
   'tmp', sum(nvl(pt_lc_dfs_c_dis_file_on_flag.tmp , 0)), ... )
```

`pt_lc_dfs_c_dis_file_on_flag` 是输入里的一个 **struct 类型列**，`.hide` 是成员访问。工具把它当成了表限定符去找表，找不到 → `no_physical_source_fields`。

仓库里已有 struct 成员访问的判定（`_has_qualified_struct_member_access`、`passthrough_resolution._expression_has_struct_member_access`），需要确认为何此形态未命中——很可能是因为限定符不带表前缀（裸列 + 成员），与既有判定假设的形态不同。

### TDD case 方向（合成）

输入表含一个 struct 列；分别测 `col.member`（裸列）与 `t.col.member`（带表别名）两种写法，断言二者都绑定到该 struct 列而不是被当作表。

---

## 子缺口 E：正则通配投影 + 多输入时裸列无法归属

### 证据（`lxs_jhy_batch_adjcrdt_regular`，6 个 gap）

```sql
select t1.a, ..., last_cash_refuse_date, temp_lim, temp_lim_beg_dt, ...
from (select `(rk)?+.+` from ...) t1
join ... t2
```

正则通配列选择（`(rk)?+.+`）的展开已在 0.1.6 实现，但 ROOT 有 `t1`/`t2` 两个输入，裸列 `temp_lim` 归属不唯一 → `root_bare_no_unique_input`。

### 待确认

需要判定展开出来的列名是否进入了裸列归属的候选集。若已进入且仍不唯一，则这是**正确的模糊性报告**，应归为良性、不修；若没进入，则是展开结果登记不完整的缺陷。

**这个判定要先做**，它决定 E 是缺陷还是良性标签。

---

## 统一验证口径

| 项 | 判据 |
| --- | --- |
| 单测 | CI 闭包全绿；每个子缺口配结构用例 + 诊断用例 |
| 逐字节基线 | 两份基线零差异；若某子缺口确实改变输出，须重新生成并**逐条复核 diff** |
| 真实语料（仓库外） | 6 个任务的 gap 数逐任务下降，且**不得有任何此前为 0 的任务出现新 gap** |
| 回归面 | 抽样 200 个任务，缺口数与状态逐任务对比 |

**验收标准以真实任务的 gap 数为准，不以合成用例通过为准。** 合成用例可以复现症状却不复现成因——这在本仓库已经发生过（缺口⑤的修复曾因为落在错误的分支里，合成用例全绿而真实任务纹丝不动）。
