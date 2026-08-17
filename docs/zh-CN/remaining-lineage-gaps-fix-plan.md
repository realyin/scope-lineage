# 残留血缘事实缺口修复方案

## 1. 文档目的与范围

`#18` 修复了 MERGE target 引用按位置配对导致的字段错位。在 645 个外部任务（932 条语句）
上复核后，仍有三类问题。本文把它们细化到开发级：每类给出复现 case、根因、开发方案、
TDD 顺序和验证方法。

方案状态：**Ready for implementation**。

优先级：

- P0-A：限定列引用不校验 schema，把不存在的列当作已证实的物理字段发布；
- P0-B：脚本内创建的临时表 schema 不向后续语句传递，占残留 root-impact 缺口的 93%；
- P1-C：UDTF 表达式展开未达不动点，丢失一个物理字段并产生 root-impact 缺口。

完成标准是**产出可信血缘**。仅让缺口计数下降、让命令返回成功，不算修复完成——
特别是 A 类，正确的修复会让诊断**变多**而不是变少。

所有 case 必须使用合成表名和字段名。真实任务、业务元数据和解析产物一律留在仓库外。

---

## 2. 问题 A：限定列引用不校验 schema

### 2.1 复现 case

四条语句，schema 为 `{"ods.s": ["id", "v"], "mart.t": ["id", "v"]}`：

```sql
-- A1 投影
INSERT INTO mart.t SELECT s.no_such_col AS id, s.v FROM ods.s s;
-- A2 过滤
INSERT INTO mart.t SELECT s.id, s.v FROM ods.s s WHERE s.no_such_col = 1;
-- A3 JOIN ON
INSERT INTO mart.t SELECT a.id, a.v FROM ods.s a JOIN ods.s b ON a.no_such_col = b.id;
-- A4 对照：未限定
INSERT INTO mart.t SELECT id, v FROM ods.s WHERE no_such_col = 1;
```

当前实测结果：

| case | warnings | fact gaps | 血缘 |
| --- | --- | --- | --- |
| A1 投影 | **无** | 无 | `mart.t.id <- ods.s.no_such_col` |
| A2 过滤 | **无** | 无 | filter 引用 `ods.s.no_such_col` |
| A3 JOIN ON | **无** | 无 | join 引用 `ods.s.no_such_col` |
| A4 未限定 | `column_not_found` ×2 | 无 | 归到 `UNKNOWN` |

MERGE 的 `USING (... WHERE id = target.id)` 是同一问题的一个触发形态：越界的 `target.id`
被 sqlglot 改写成 `s.target.id`，最终落成 `ods.s.target` 这个不存在的列，同样静默。

### 2.2 根因

`scope_lineage/scope/column_ref_resolver.py` 里，`column_not_found` 只在**未限定列**
找不到唯一来源时发出。限定列走另一条路径：限定符解析到某张表后直接绑定，
**从不检查该列是否在这张表的 schema 里**。

这与契约的核心主张直接冲突：「证明不了就显式标注，不把猜测伪装成事实」。
`ods.s.no_such_col` 不是猜测，是**可证伪的错误**——schema 就在手里，一查便知。

### 2.3 开发方案

在限定引用绑定成功后增加一次校验，**仅在该表 schema 已知时**判定：

- schema 已知且不含该列 → 发 `column_not_in_table_schema` warning；
- schema 未知 → 不发（那是元数据覆盖问题，已由 `metadata_coverage` 报告）。

**保留绑定，只加诊断。** 不改成 `UNKNOWN`：作者写明了限定符，绑定反映其意图；
而元数据不完整在真实仓库里是常态，改绑定会在 schema 缺列时大面积破坏正确血缘。
用 warning 而非 fact gap，与未限定路径的 `column_not_found` 对称，也不改变 strict 门禁口径。

修改文件：

- `scope_lineage/scope/column_ref_resolver.py`
- `tests/core/test_qualified_column_schema_audit.py`（新增）

### 2.4 风险与必测项

**这是本方案唯一可能大面积改变产物的改动。** 必须在 645 任务语料上先测量再定稿：

- 若新 warning 数量在可解释范围内（每条都能对应一个 schema 确实缺失的列），保留；
- 若出现大量误报（说明元数据本身按分区/版本不全），则收紧为「仅当该表 schema 来源为
  权威 JSON 且列数 > 0 时判定」，并在方案中记录实测数字。

不允许为了让计数好看而放宽判定；也不允许因为数量多就放弃——数量本身就是结论。

---

## 3. 问题 B：跨语句临时表 schema 不前向传递

### 3.1 复现 case

```sql
CREATE TABLE staging_tmp AS SELECT id, code FROM ods.source;
MERGE INTO mart.target target
USING (SELECT id, code FROM staging_tmp) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET target.code = source.code
```

schema 为 `{"ods.source": ["id", "code"], "mart.target": ["id", "code"]}`（`staging_tmp`
是运行时创建的，元数据里不可能有）。

当前实测：

```
analysis_status : partial (lineage_fact_gap)
gaps            : 2 × expression_resolution_incomplete
                  missing_reasons=['expanded_expression_contains_unexpanded_alias:staging_tmp']
missing_tables  : ['staging_tmp']
```

真实语料中有 3 个任务是这个形态（`CREATE ... _tmp` → `DELETE` → `MERGE USING _tmp`），
贡献 38 条 root-impact 缺口，占残留总量的 93%。

### 3.2 根因

每条写语句独立调用 `parse_scope_lineage`，语句 N 建的表对语句 N+1 不可见。
v2 已经按顺序建模语句并维护表状态图，但**没有把前序语句产出的列传给后续语句的作用域解析**。
v1 的多语句路径同样如此。

`staging_tmp` 因此既进不了 schema（列无法展开），又被算作「引用了但没有元数据的表」，
在 `metadata_coverage.missing_tables` 里变成一个永远补不上的伪缺失表。

### 3.3 开发方案

在多语句解析的循环中维护一份**脚本内产出 schema**：

1. 每条语句解析完成后，若它创建或写入一张不在输入 schema 中的表，把它的目标字段名
   记入该表的列集合；
2. 后续语句解析时，把这份 schema 作为**补充**并入传入的 schema；
3. **输入元数据始终优先**：脚本内推导只填补输入 schema 没有的表，不覆盖已有定义；
4. 只登记能确定列名的语句（CTAS、带显式列的 CREATE、能解析出目标字段的写入），
   列名不确定时不登记，也不猜；
5. `metadata_coverage` 因此不再把脚本内建的表算作缺失表——不需要为表名加过滤特例，
   它本来就有了 schema。

修改文件：

- `scope_lineage/scope/scope_builder.py`（`parse_all_scope_lineage` 的语句循环）
- `scope_lineage/scope/task_lineage.py`（`parse_task_lineage` 的语句循环）
- `tests/core/test_script_local_table_schema.py`（新增）
- `tests/core/test_task_state_lineage.py`

### 3.4 边界

- 同名表在脚本内被重复创建时，以**最近一次**产出为准（顺序语义）；
- 脚本内表与真实仓库表同名时，输入 schema 优先（避免用临时定义污染真实表）；
- 不引入新的契约字段，不改 schema major version。

---

## 4. 问题 C：UDTF 表达式展开未达不动点

### 4.1 复现 case

```sql
INSERT INTO mart.target
WITH base AS (SELECT id, session_id, created_at, items FROM ods.source)
SELECT id, last_code FROM (
  SELECT t.id,
    FIRST_VALUE(item.code) OVER (PARTITION BY t.session_id ORDER BY t.created_at DESC) AS last_code
  FROM base t LATERAL VIEW EXPLODE(t.items) x AS item
) q
```

schema 为 `{"ods.source": ["id","session_id","created_at","items"], "mart.target": ["id","last_code"]}`。

当前实测：列级来源**全部正确解析**（`cte:base.session_id`、`udtf:x.item`、
`cte:base.created_at`），但 `subq:q.last_code` 报 root-impact 缺口：

```
missing_reasons        : ['expanded_expression_contains_unexpanded_alias:t']
physical_source_fields : [ods.source.session_id, ods.source.created_at]   ← 缺 items
```

关键：UDTF 上游是**物理表**时不复现，是 **CTE** 时复现。

### 4.2 根因

这**不是误报**。展开轨迹显示：

```
x.item        -> EXPLODE(`t`.`items`)          status=resolved   ← 重新引入了消费方别名 t
t.session_id  -> `ods.source`.`session_id`     status=resolved
```

`x.item` 被替换成 UDTF 自己的表达式后，替换结果里**又出现了 `t`**——UDTF 的表达式是用
消费方作用域的别名写的。展开只跑一遍，不对替换结果再展开，于是 `t.items` 停在原地，
`ods.source.items` 没能进入 `physical_source_fields`。

`expanded_expression_contains_unexpanded_alias:t` 因此是**正确的信号**，指向真实的
事实缺失。修复方向不是放宽判定，而是**把展开做完**。

上游是物理表时不复现，是因为 `t` 直接绑定到物理表，替换后的 `t.items` 能被同一遍的
物理限定符解析吃掉；上游是 CTE 时需要再走一层，而这一层没有被执行。

### 4.3 开发方案

让表达式展开迭代到不动点，与本模块中其它已有的重复解析遍保持一致：

1. 展开后检测替换结果是否引入了本作用域仍可解析的限定符；
2. 若是则再展开一轮，直到不再变化或达到轮次上限；
3. 上限用固定小常数并在耗尽时保留 `missing_reasons`——**耗尽必须留下缺口，
   不能因为跑满轮次就宣布解析完成**；
4. 不放宽 `_unexpanded_bound_aliases_in_expression` 的判定条件。放宽会把这条真实信号
   静音，正是方案要避免的做法。

修改文件：

- `scope_lineage/scope/scope_facts.py`
- `tests/core/test_expression_expansion_fixpoint.py`（新增）

---

## 5. TDD 实施顺序

每个 checkpoint 先写失败测试、确认失败原因正确，再改生产代码。

### Checkpoint 1：A 类失败测试

`tests/core/test_qualified_column_schema_audit.py` 写入 A1–A4，断言 A1/A2/A3 各产生
`column_not_in_table_schema`，A4 维持现有 `column_not_found`。确认前三条在改代码前失败。

```bash
python -m pytest tests/core/test_qualified_column_schema_audit.py -q
```

### Checkpoint 2：A 类实现 + 语料测量

实现后**先在 645 任务语料上测量新 warning 的数量和分布**，逐类判断是真缺列还是元数据
不全，再决定是否收紧判定。测量结果写进 PR 说明。

```bash
python -m pytest tests/core -q
```

### Checkpoint 3：B 类失败测试

`tests/core/test_script_local_table_schema.py` 写入 3.1 的 case，断言：

- 两条语句均 `modeled`；
- 无 `expanded_expression_contains_unexpanded_alias:staging_tmp`；
- `missing_tables` 不含 `staging_tmp`；
- `analysis_status.status == "complete"`；
- MERGE 的 `membership_sources` 追踪到 `ods.source.id`。

再补两条边界断言：脚本内表与输入 schema 同名时输入优先；同名表重复创建时以最近一次为准。

### Checkpoint 4：B 类实现

v1 与 v2 两条多语句路径都要覆盖，两边各有测试。

```bash
python -m pytest tests/core/test_script_local_table_schema.py tests/core/test_task_state_lineage.py -q
```

### Checkpoint 5：C 类失败测试

`tests/core/test_expression_expansion_fixpoint.py` 写入 4.1 的 case，断言
`physical_source_fields` 含 `ods.source.items`、`missing_reasons` 为空、`lineage_fact_gaps`
为空。同时写一条「轮次耗尽仍保留缺口」的测试，防止实现用「跑满就算完成」蒙混。

### Checkpoint 6：C 类实现

```bash
python -m pytest tests/core/test_expression_expansion_fixpoint.py -q
```

### Checkpoint 7：契约与确定性

```bash
python -m pytest tests/core/test_lineage_contract_baseline.py tests/core/test_task_lineage_contract_baseline.py -q
python -m pytest tests/core/test_contract_versioning.py -q
```

既有 golden 的任何变化都要逐字节解释。B 和 C 会让部分 golden 的事实**变得更完整**——
这类变化是预期的，但必须在 PR 中逐条说明改了什么、为什么更正确；A 只加诊断，
不应改变任何既有 golden 的血缘部分。

### Checkpoint 8：跨版本与仓库完整验证

```bash
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py   # ×30.0.0/30.16.0/30.17.0
python -m ruff check scope_lineage tests
python -m build && python tests/architecture/verify_distribution.py dist/*
```

### Checkpoint 9：外部语料验收

645 任务修复前后对比，要求：

- 无任何任务的链路完整度下降；
- root-impact 缺口从 5 个任务降到 0（B、C 覆盖全部 5 个）；
- A 类新增 warning 逐类可解释；
- 无新增 parse 失败、无新增 recovered syntax。

外部路径经环境变量传入，不写进测试或文档。

---

## 6. 验收清单

- [ ] A1–A3 产生 `column_not_in_table_schema`，A4 行为不变；
- [ ] A 类只加诊断，不改变任何既有 golden 的血缘事实；
- [ ] A 类语料 warning 增量已逐类解释并记录在 PR 中；
- [ ] 脚本内 CTAS 产出的列对后续语句可见；
- [ ] 输入 schema 始终优先于脚本内推导；
- [ ] 脚本内表不再出现在 `metadata_coverage.missing_tables`；
- [ ] UDTF 表达式展开到不动点，物理字段补齐；
- [ ] 展开轮次耗尽时仍保留 `missing_reasons`；
- [ ] 既有 golden 的每处变化都有逐字节说明；
- [ ] SQLGlot 30.0.0 / 30.16.0 / 30.17.0 均通过；
- [ ] 645 任务无任何回退，root-impact 缺口任务降至 0；
- [ ] 提交中无真实任务、业务元数据、本地路径或生成产物。

---

## 7. 明确不做的事

- 不改公开 API 和 `PUBLIC_CORE_API`；
- 不改契约 major version 和既有字段含义；
- 不扩大 SQLGlot 依赖范围；
- 不通过放宽 `_unexpanded_bound_aliases_in_expression` 的判定来消除 C 类缺口；
- 不通过过滤表名来消除 B 类的伪缺失表；
- 不为了让计数好看而抑制 A 类新增的诊断。
