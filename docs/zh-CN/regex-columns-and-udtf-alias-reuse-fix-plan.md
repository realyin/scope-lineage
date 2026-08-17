# 正则列选择与 UDTF 别名复用修复方案

## 1. 文档目的与范围

外部能力缺口清单的 7 项中，`cache lazy table`（⑦）与元数据加载（①③，②归并入⑦）已在
前一轮修复。本文覆盖剩余两项：

- **P0-L**：Spark 引号正则列选择 `` `(dt)?+.+` `` 未展开（原清单缺口④）；
- **P0-M**：同一查询块内 LATERAL VIEW **别名复用**，导致 UDTF 输出列引用绑不上
  （原清单缺口⑤）。

两项均有**已验证的合成复现**与代码层根因，具备开工条件。

原清单缺口⑥（子查询内表引用别名扩展）仍**无合成复现**，不在本文范围，见 §6。

方案状态：**Ready for implementation**。

所有 case 使用合成表名与字段名。真实任务、业务元数据和解析产物一律留在仓库外。

### 1.1 对原清单归因的两处更正

| 原判定 | 实测 | 更正 |
| --- | --- | --- |
| ④ 子查询投影列静态推断不全，`(dt)?+.+` 是通配占位符 | 该字符串是 SQL 里真实写着的内容 | 是 **Spark 引号正则列选择语法**未展开 |
| ⑤ UDTF 输出别名未建模 | 单独的链式 LATERAL VIEW、struct 成员访问、跨 CTE 同名别名**均正常** | 触发条件是**同一查询块内两个 LATERAL VIEW 复用同一别名** |

⑤ 的归因改过两次：原清单说「UDTF 别名未建模」，中途我判为「UDTF 输出列的 struct 成员
访问」，两者都不成立 —— 逐条排除后才落到「别名复用」。**照前两种归因去改都会改错地方。**

---

## 2. 问题 L：Spark 引号正则列选择未展开

### 2.1 复现 case（已验证）

schema 为 `{"ods.s": ["id","v","dt"], "mart.t": ["id","v"]}`：

```sql
INSERT INTO mart.t
SELECT a.id, a.v FROM (SELECT `(dt)?+.+` FROM ods.s) a
```

实测：

```text
status=partial gaps=3
  object='(dt)?+.+' scope='subq:a'  reasons=['no_physical_source_fields']
  object='id'       scope='ROOT'    reasons=['no_physical_source_fields']
  object='v'        scope='ROOT'    reasons=['no_physical_source_fields']
```

真实任务（`lxs_jhy_cash_basic`、`lxs_jhy_credit_basic`）的缺口形态与此逐项一致，
SQL 里写的就是 ``(select `(dt)?+.+` ...``。

### 2.2 根因

`` `(dt)?+.+` `` 是 Spark 的引号正则列选择（`spark.sql.parser.quotedRegexColumnNames`），
语义为「选出列名匹配该正则的所有列」。工具把它当成字面列名，于是子查询输出一个不存在的
列，所有引用该子查询的下游表达式随之落空 —— 一个语法未识别放大成整棵子树的缺口。

### 2.3 开发方案

1. 识别投影中的**引号列名**是否为正则模式：含正则元字符，**且** schema 中不存在同名列；
2. schema 已知时按正则展开为匹配的列集合，与 `SELECT *` 的展开走同一条路；
3. **schema 未知时不猜**：保留该投影并记录 fact gap，说明需要源表 schema 才能展开 ——
   与 `projection_wildcard_unexpanded` 的口径一致；
4. 普通引号列名行为不变：`` `dt` `` 这种确实存在的列照旧按字面处理。

**判据顺序不能颠倒**：必须先查 schema 再判正则。反过来会把一个真实存在、名字含元字符的
列误当成正则展开掉。

修改文件：

- 投影解析所在模块（`scope_lineage/scope/` 下的星号展开路径）
- `tests/core/test_regex_column_selection.py`（新增）

---

## 3. 问题 M：LATERAL VIEW 别名复用

### 3.1 复现 case（已验证）

schema 为 `{"lods.rule_detail": ["data","id"], "mart.t": ["unit_code"]}`：

```sql
INSERT INTO mart.t
SELECT DISTINCT arr.unitCode AS unit_code
FROM lods.rule_detail
LATERAL VIEW EXPLODE(from_json(data, 'array<struct<unitCode:string,detail:array<struct<subType:string>>>>')) t AS arr
LATERAL VIEW EXPLODE(arr.detail) t AS d          -- 别名 t 复用
WHERE d.subType = 'abTest'
```

把第二个别名改成 `t2` 即恢复正常。实测对照：

| | 展开后的表达式 | 结果 |
| --- | --- | --- |
| 别名不同（`t` / `t2`） | `` `t`.`arr`.`unitcode` `` | resolved，物理字段 `lods.rule_detail.data` |
| 别名复用（`t` / `t`） | `arr.unitcode` | unresolved，`alias_not_bound_to_input_source:arr` |

真实任务 `dwd_ma_res_adp_user_creative_rel_di` 有 6 个 LATERAL VIEW、别名复用，缺口形态
与合成用例逐字一致。

### 3.2 根因

作用域与列级血缘**两种情况下都是对的**：

```text
udtf:t    列 arr ← lods.rule_detail.data
udtf:t_2  列 d   ← udtf:t.arr
```

差别只在 qualify：两个 LATERAL VIEW 同名时，sqlglot 无法判定哪个 `t` 拥有输出列 `arr`，
于是把 `arr.unitCode` 原样留下；别名不同时它会改写成 `` `t`.`arr`.`unitcode` ``。

随后表达式解析拿 `arr` 去查别名绑定表，那里只有 `t`，于是判为
`alias_not_bound_to_input_source:arr`。

**解析所需的信息是齐的** —— `udtf:t` 明明暴露了名为 `arr` 的输出列。缺的是一条回退：
限定符不是已绑定别名时，去看它是不是本作用域某个 UDTF 输入的输出列。

这与仓库已有的 `_resolve_duplicate_alias_ref`（处理同一 SELECT 里重复的**表**别名）
是同一类问题，只是 UDTF 这条路径没有对应处理。

### 3.3 开发方案

给限定符解析增加一级回退，位置在「别名绑定查不到」之后、「放弃并记缺口」之前：

1. 限定符不是本作用域的已绑定别名时，检查它是否为某个 UDTF 输入作用域的**输出列名**；
2. **恰好一个** UDTF 暴露该列名 → 绑定到那个作用域；
3. **多个都暴露** → 这是真歧义，保留缺口，不挑一个 —— 挑选会让结果取决于书写顺序；
4. 一个都没有 → 保留现有 `alias_not_bound_to_input_source` 行为不变。

修改文件：

- `scope_lineage/scope/column_expression_resolution.py`
- `tests/core/test_udtf_alias_reuse.py`（新增）

---

## 4. TDD 实施顺序

先 M 后 L：M 的根因链条更长，先做能尽早暴露对作用域模型的误解。
每个 checkpoint 先写失败测试、确认失败原因正确，再改生产代码。

### Checkpoint 1：M 的失败测试

`tests/core/test_udtf_alias_reuse.py`：

- §3.1 的 case：`lineage_fact_gaps == []`，`unit_code` 追溯到
  `lods.rule_detail.data`；
- **对照**：别名不同的同形态 SQL 行为不变（防止修复顺手改坏了本来正常的路径）；
- **反向保护**：两个 UDTF 都暴露同名输出列时**仍然**保留缺口，不得任选其一。
  这条最重要 —— 它把「不确定就留缺口」钉死，否则实现很容易退化成「取第一个」。

### Checkpoint 2：M 的实现

```bash
python -m pytest tests/core/test_udtf_alias_reuse.py -q
python -m pytest tests/core -q -k "udtf or lateral"
```

### Checkpoint 3：L 的失败测试

`tests/core/test_regex_column_selection.py`：

- §2.1 的 case：0 缺口，子查询输出展开为 `id, v, dt`；
- schema 未知时保留缺口，说明需要源表 schema；
- **反向保护**：schema 中确实存在、名字含正则元字符的列按字面处理，不被展开。

### Checkpoint 4：L 的实现

```bash
python -m pytest tests/core/test_regex_column_selection.py -q
python -m pytest tests/core -q -k "star or wildcard"
```

### Checkpoint 5：契约、确定性与跨版本

```bash
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py   # ×30.0.0/30.16.0/30.17.0
python -m ruff check scope_lineage tests
python -m build && python tests/architecture/verify_distribution.py dist/*
```

既有 golden 若变化，逐键比对后再重生成，PR 中逐条说明。

### Checkpoint 6：外部语料验收

用原清单点名的任务验证：

- ④ 的两个任务（`lxs_jhy_cash_basic`、`lxs_jhy_credit_basic`）缺口 3 → 0；
- ⑤ 的任务（`dwd_ma_res_adp_user_creative_rel_di`）缺口 4 → 0；
- 已修复的 ①②③⑦ 相关任务保持 0 缺口；
- 无任何任务的完整链路数或物理来源数下降。

外部路径经环境变量传入，产物不入库。

---

## 5. 验收清单

- [ ] 引号正则列选择按 schema 展开，下游引用可解析；
- [ ] schema 未知时保留缺口，不猜列名；
- [ ] 真实存在、名字含元字符的列不被误展开；
- [ ] LATERAL VIEW 别名复用时 UDTF 输出列引用可解析；
- [ ] 别名不同的同形态行为不变；
- [ ] 多个 UDTF 暴露同名输出列时仍保留缺口，不任选其一；
- [ ] 既有 golden 变化逐键解释；
- [ ] SQLGlot 30.0.0 / 30.16.0 / 30.17.0 均通过；
- [ ] 点名任务缺口归零，无回退；
- [ ] 提交中无真实任务、业务元数据、本地路径或生成产物。

---

## 6. 明确不做的事

- 不修改公开 API 和 `PUBLIC_CORE_API`；
- 不修改契约 major version；
- 不扩大 SQLGlot 依赖范围；
- 不按原清单对 ④⑤ 的归因去改「子查询投影推断」或「UDTF 别名建模」——
  §1.1 已说明两者都不成立；
- 不在多个 UDTF 暴露同名列时任选其一：那会让结果取决于书写顺序；
- **不动缺口⑥**：真实任务上现象成立（7 条 `expanded_expression_contains_unexpanded_alias`），
  但已排除表别名、列限定、CTE 包裹、union 分支等因素后仍无合成复现。
  归约成功前不改生产代码 —— 改一个没有测试能证明存在的问题，既无法验证也无法防回归。
