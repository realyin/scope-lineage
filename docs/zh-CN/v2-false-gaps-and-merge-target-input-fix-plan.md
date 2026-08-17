# v2 假事实缺口与 MERGE 目标输入修复方案

## 1. 文档目的与范围

`#18`、`#19`、`#20` 之后，v1 契约在 645 个外部任务上已经没有任何 root-impact 事实缺口，
但 v2 契约仍有 **31 个 partial 任务、296 条缺口**。逐条查证后：**这 296 条全部是假缺口**，
且都由 v2 自身的两处缺陷产生，与被解析的 SQL 无关。

本文把三个问题细化到开发级：复现 case、根因（含代码位置与实测证据）、开发方案、TDD 顺序、
验证方法。

方案状态：**Ready for implementation**。三个问题均有实测证据，两个已验证修复方向可行。

优先级：

- **P0-F**：v2 把每条语句往返 SQL 文本再解析，sqlglot 不能正确往返 UNION 分支各自携带的
  WITH，导致整条语句 qualify 失败并降级 —— 5 个任务、260 条假缺口；
- **P0-G**：任务层把 `COUNT(*)` 的整行依赖判成「投影通配符未展开」—— 26 个任务、36 条假缺口；
- **P1-H**：MERGE 的 ROOT 仍未声明目标关系。`#20` 因两条约束搁置，其中一条经试验已证明
  不成立。

完成标准是产出可信血缘。F 与 G 修复后，v2 的 root-impact 缺口任务应为 **0**；若仍有残留，
必须逐条查明而不是调低门槛。

所有 case 使用合成表名与字段名。真实任务、业务元数据和解析产物一律留在仓库外。

### 1.1 案例验证状态

F、G 的全部复现 case 均已实测通过，观测值直接写在 §2.1 与 §3.1。两个 case 各有一个
「看起来对、实际不复现」的陷阱写法，也一并记录，避免开发者照抄后得到永远通过的空测试。

### 1.2 本轮分析纠正的说法

上一轮我把 v2 的 296 条缺口描述为「前后数字一致，是既有问题，不在范围内」。这个说法回避了
真正该问的问题：**同一份语料、同一份元数据，为什么 v1 是 0 而 v2 是 296？**
追这个不对称，才找到了 F 和 G。数字稳定不等于数字正确。

---

## 2. 问题 F：v2 往返 SQL 文本导致整条语句解析降级

### 2.1 复现 case（已验证）

schema 为
`{"ods.left_events": ["id","day_idx"], "ods.right_events": ["id","day_span"],
"mart.summary": ["side","day_idx","day_span"]}`：

```sql
INSERT OVERWRITE TABLE mart.summary
WITH staged AS (SELECT id, day_idx FROM ods.left_events)
SELECT 'left' AS side, staged.day_idx AS day_idx, NULL AS day_span FROM staged
UNION ALL
WITH staged AS (SELECT id, day_span FROM ods.right_events)
SELECT 'right' AS side, NULL AS day_idx, staged.day_span AS day_span FROM staged
```

实测结果：

```text
原始 AST    : With(parent=Union), With(parent=Select)
往返后 AST  : With(parent=Insert)，CTE = ['staged', 'staged']
qualify 原始 : 成功
qualify 往返 : OptimizeError: Unknown column: day_idx
v1           : 0 gaps, fallback_used=False
v2           : 4 × expression_source_unresolved, analysis_status=partial
```

**两个分支必须引用各自 CTE 里不同名的列**。先前一版把两边都别名成同一个 `metric`，
AST 层的合并照样发生，但遮蔽后仍能解析，下游不报错——那样的 case 会让开发者以为
问题不存在。列名相同是这个 case 唯一的陷阱。

### 2.2 根因

`_apply_projection_write()`（`task_lineage.py`）对每条语句执行：

```python
result = parse_scope_lineage(
    tree.sql(dialect=DIALECT),   # <- AST 重新序列化成文本，再从文本重新解析
    ...
)
```

而 **sqlglot 的生成器不能往返「UNION 分支各自携带的 WITH」**。实测同一条真实语句：

```text
原始 AST   : With(parent=Select) × 2，各 3 个 CTE（同名、定义不同）
重序列化后 : With(parent=Insert) × 1，6 个 CTE，label_cust 等各出现两次
```

两个 WITH 被提升到 Insert 层并合并，后一个同名 CTE 遮蔽前一个。于是 qualify 抛出

```text
OptimizeError: Unknown column: day_inx
```

`_qualify_ast()` 捕获异常后降级为「未 qualify 解析」（`fallback_used=True`），该语句的所有
表达式解析随之失效，产出 88 条 `expression_source_unresolved`（`no_physical_source_fields`）。

逐层隔离实测，确认变量只有一个：

| 输入 | 结果 |
| --- | --- |
| 原始文本 + SchemaMap | 0 gaps |
| 原始文本 + `dict(schema)` | 0 gaps（schema 转换**不是**原因）|
| 重序列化 + SchemaMap | **88 gaps** |
| 重序列化 + `dict(schema)` | 88 gaps |

再直接对比构建函数，排除其余因素：

```text
_build_insert_scope(原始 AST)        -> fallback_used=False, gaps=0
_build_insert_scope(文本往返后 AST)  -> fallback_used=True,  gaps=88
```

**影响面精确匹配**：全语料 120 个含 UNION+WITH 的任务中，5 个属于「分支各带同名 CTE」形态，
正是产生那 260 条缺口的同 5 个任务。

### 2.3 开发方案

**不要再让 v2 把语句往返 SQL 文本。** 语句的 AST 已经在手上，且是从原始脚本解析出来的。

1. 给 `parse_scope_lineage()` 增加可选参数 `tree: exp.Expression | None = None`；
   传入时跳过 `_collect_insert_trees()`，直接使用该 AST；
2. `_apply_projection_write()` 传入它已持有的 `tree`；
3. `statement_identity_sql` 与 v2 记录里的 `normalized_sql` 仍由 `tree.sql()` 产生 ——
   它们是展示与身份用途，不参与血缘解析。但 **`normalized_sql` 对这 5 个任务是不可执行的
   SQL**（重复 CTE 名），必须在 §2.4 决定如何处理；
4. 不改 `parse_all_scope_lineage()`：它本来就解析原始文本，没有这个问题。

修改文件：

- `scope_lineage/scope/scope_builder.py`（`parse_scope_lineage` 增加可选 tree 参数）
- `scope_lineage/scope/task_lineage.py`（传入 tree）
- `tests/core/test_statement_ast_is_not_round_tripped.py`（新增）

### 2.4 必须一并决定的事：`normalized_sql`

同一个 sqlglot 缺陷会让这 5 个任务的 `normalized_sql` 变成含重复 CTE 名、无法执行的 SQL。
本次修复让血缘正确，但不会自动修好这个字段。两个选项：

- **A（推荐）**：保留现状并在契约文档中说明 `normalized_sql` 是「解析器视角的规范化文本」，
  不保证可执行；同时新增一条诊断，标记该语句的规范化文本与原始语义不等价；
- **B**：为这类形态改用原始语句文本切片。需要语句级文本偏移，`sqlglot.parse` 不直接提供，
  改动面明显更大。

**Checkpoint 3 必须显式做出选择并写进 PR**，不允许默默保留 A 而不加诊断——那等于继续发布
一段看起来可执行、实际不可执行的 SQL。

---

## 3. 问题 G：`COUNT(*)` 被判成投影通配符未展开

### 3.1 复现 case（已验证）

**G1 — 聚合星号**，schema 为
`{"ods.events": ["app_code"], "mart.summary": ["app_code","call_cnt"]}`：

```sql
INSERT INTO mart.summary
SELECT app_code, COUNT(*) AS call_cnt FROM ods.events GROUP BY app_code
```

**G2 — 窗口星号**，同 schema：

```sql
INSERT INTO mart.summary
SELECT app_code, COUNT(*) OVER () AS call_cnt FROM ods.events
```

**G3 — 对照，真通配符**，schema 只含 `{"mart.summary": ["app_code","call_cnt"]}`：

```sql
INSERT INTO mart.summary SELECT * FROM ods.undocumented
```

实测：

| case | 星号来源 | written 键 | v2 结果 | 期望 |
| --- | --- | --- | --- | --- |
| G1 | `('call_cnt','AGGREGATE')` | `app_code, call_cnt` | partial + 缺口 | **complete，无缺口** |
| G2 | `('call_cnt','WINDOW')` | `app_code, call_cnt` | partial + 缺口 | **complete，无缺口** |
| G3 | `('*','EXPAND_ALL')` | `*` | partial + 缺口 | **保持不变** |

v1 对 G1、G2 均为 **0 缺口**，ROOT 列完全展开。

**G2 必须写成 `COUNT(*) OVER ()`。** 先前一版写的是
`COUNT(*) OVER (PARTITION BY app_code)`，那种形态解析到分区列、根本不产生星号来源，
因此不复现——照抄会得到一条永远通过的空测试。

注意 G3 的 written 键就是 `*`，说明判据的**第一个条件已经能捕获真通配符**，
这正是收紧第二个条件安全的直接证据。

### 3.2 根因

`_projection_state_missing_reasons()`（`task_lineage.py:787`）：

```python
if "*" in written_values or any(
    source.get("column") == "*"
    for sources in written_values.values()
    for source in sources
):
    return ["projection_wildcard_unexpanded"]
```

第二个条件把**任何**列名为 `*` 的来源都判成通配符未展开。但 `*` 在这份契约里有两种含义：

| 形态 | 目标列名 | 来源 transform | 含义 |
| --- | --- | --- | --- |
| `SELECT *` 无法展开 | `*` | `EXPAND_ALL` | 真缺口：不知道有哪些列 |
| `COUNT(*)` | 具名列 | `AGGREGATE` | **已解析的事实**：依赖整行 |
| `COUNT(*) OVER (...)` | 具名列 | `WINDOW` | 同上 |

实测 26 个受影响任务的全部 142 处星号来源：**AGGREGATE 140、WINDOW 2、EXPAND_ALL 0**。
没有一处是真的未展开通配符。

第一个条件 `"*" in written_values` 是对的——真通配符的目标列名就是 `*`。错的是第二个条件。

值得一提：`COUNT(*) → table.*` 正是这个工具在整行依赖上比同类更准确的地方，却被自己的
判定当成了缺陷。

### 3.3 开发方案

把判据从「来源列名是 `*`」收紧为「来源确实是未展开的通配符」：

1. 第一个条件保留不变；
2. 第二个条件加上 `source.get("transform") == "EXPAND_ALL"` 约束；
3. 不删除第二个条件——目标列名不是 `*` 但来源仍是 `EXPAND_ALL` 的形态需要继续被捕获。

修改文件：

- `scope_lineage/scope/task_lineage.py`
- `tests/core/test_projection_wildcard_detection.py`（新增）

---

## 4. 问题 H：MERGE 的 ROOT 未声明目标关系

### 4.1 现状与 `#20` 的搁置理由

`#20` 只声明了 USING 关系，目标关系仍缺席。当时给出两条搁置理由：

1. 绑定 `target` 别名会让 MERGE 动作子查询里刻意保留的相关引用 `target.id` 被判成
   「未展开的别名」；
2. 声明目标需要新的 `position` 枚举值，而契约把该字段约束为 `from|join|lateral_view`。

### 4.2 试验推翻了第一条

`_populate_scope_alias_source_bindings()`（`scope_facts.py:493-495`）对**没有别名的输入边
直接跳过**：

```python
alias = ref.get("alias")
if not alias:
    continue
```

因此用 `alias=None` 声明目标关系时**不会产生别名绑定**，也就不会与相关引用冲突。已实测：
两条守卫测试（`test_a_correlated_target_reference_is_not_reported_as_an_unexpanded_alias`、
`test_cte_projection_and_correlated_target_ref_do_not_contaminate_each_other`）均通过，
只有 golden 与「恰好一条输入边」的断言需要更新。

第二条约束也不成立：`position` 用既有的 `from` 即可，**不需要改 schema**。

### 4.3 开发方案与其代价

在 `_populate_merge_root_input_edges()` 中补一条目标关系输入边：
`source_id=result.target_table`、`source_type="physical_table"`、`alias=None`、
`position="from"`，排在 USING 边之前。

**代价必须写进 PR**：输入被声明了，但别名没有记录，消费者无法把 `target.x` 映射回这条边。
这是**部分答案**——比现在「声明自己没有任何输入」严格更好，但不完整。要做到完整需要一个
能表达「已声明但不参与别名展开」的输入模型，那是契约演进，不在本次范围。

修改文件：

- `scope_lineage/scope/scope_facts.py`
- `tests/core/test_merge_root_inputs.py`
- `tests/core/fixtures/lineage_contract/merge/`、
  `tests/core/fixtures/task_lineage_contract/merge_cte_source/`（golden，逐字节解释）
- `docs/zh-CN/lineage-json.md`

---

## 5. TDD 实施顺序

按 G → F → H 执行：G 最简单且影响面最大，F 价值最高，H 涉及 golden。
每个 checkpoint 先写失败测试、确认失败原因正确，再改生产代码。

### Checkpoint 1：G 的失败测试

`tests/core/test_projection_wildcard_detection.py`，用 `parse_task_lineage` 断言：

- G1、G2：`analysis_status.status == "complete"`、`lineage_fact_gaps == []`；
- G3 对照：**仍然**产出 `projection_wildcard_unexpanded` 且 `root_impact=true`；
- 单元级：直接调用 `_projection_state_missing_reasons()`，用三组构造的
  `written_values`（键为 `*`、来源 `EXPAND_ALL`、来源 `AGGREGATE`）固化 §3.2 的表格。

### Checkpoint 2：G 的实现

```bash
python -m pytest tests/core/test_projection_wildcard_detection.py -q
python -m pytest tests/core/test_task_state_lineage.py -q
```

### Checkpoint 3：F 的失败测试

`tests/core/test_statement_ast_is_not_round_tripped.py`：

1. 用 §2.1 的合成 SQL（已验证复现：v2 产生 4 条 `expression_source_unresolved`，
   v1 同一 SQL 0 缺口）；
2. 断言修复后 v2 与 v1 对该 SQL 的物理来源集合一致；
3. 断言 `fallback_used` 为 False；
4. 加一条 **AST 判据**单元测试，直接断言 sqlglot 的往返缺陷存在：
   `With(parent=Select)` 在往返后变成 `With(parent=Insert)` 且出现重复 CTE 名。
   这条独立于本仓库的修复，用来在 sqlglot 日后修好该缺陷时立刻暴露——届时本方案的
   绕行可以撤除；
4. 加一条**跨契约一致性**测试：同一 SQL 在 v1 与 v2 下，每个最终字段的物理来源集合相同。
   这条是本问题的通用护栏——两个契约对同一语句给出不同事实，本身就是缺陷。

### Checkpoint 4：F 的实现

```bash
python -m pytest tests/core/test_statement_ast_is_not_round_tripped.py -q
python -m pytest tests/core/test_task_state_lineage.py tests/core/test_task_lineage_contract_baseline.py -q
```

并按 §2.4 就 `normalized_sql` 做出选择，写进 PR。

### Checkpoint 5：H 的失败测试与实现

更新 `test_merge_root_inputs.py`：ROOT 输入边为「目标（无别名）、USING（别名 source）」两条，
别名绑定仍只有 `source` 一条。两条守卫测试必须继续通过。

### Checkpoint 6：H 的 golden 审查

```bash
python -m pytest tests/core/test_lineage_contract_baseline.py -q
python -m pytest tests/core/test_task_lineage_contract_baseline.py -q
```

预期失败。**逐键结构比对后**再重生成，PR 中说明只有新增、没有既有值被改动。出现
`columns` / `outputs` / `end_to_end_lineage` 变化就停下查清原因。

### Checkpoint 7：契约、确定性与跨版本

```bash
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py   # ×30.0.0/30.16.0/30.17.0
python -m pytest tests/core/test_contract_versioning.py -q
python -m ruff check scope_lineage tests
python -m build && python tests/architecture/verify_distribution.py dist/*
```

相同输入连续解析两次必须字节一致。

### Checkpoint 8：外部语料验收

645 任务，修复前后 v1 与 v2 双版本对比。要求：

- **v2 的 root-impact 缺口任务 31 → 0**，`expression_source_unresolved` 260 → 0，
  `projection_wildcard_unexpanded` 36 → 0；
- v1 保持 0 缺口，无任何变化；
- 无任何任务的完整链路数或物理来源数下降；
- 已建模语句数不变；
- 无新增 parse 失败、无新增 recovered syntax；
- **新增一项**：逐任务比对 v1 与 v2 的最终字段物理来源集合，差异数应为 0。

外部路径经环境变量传入，产物不入库。

---

## 6. 验收清单

- [ ] G1（`COUNT(*)`）与 G2（`COUNT(*) OVER ()`）不再产生通配符缺口；
- [ ] 真正未展开的 `SELECT *` 仍然产生缺口且 `root_impact=true`；
- [ ] `_projection_state_missing_reasons()` 的三态行为有单元测试固化；
- [ ] v2 不再对语句做 SQL 文本往返；
- [ ] 分支各带同名 CTE 的 UNION 语句 `fallback_used=False`；
- [ ] AST 判据测试固化 sqlglot 的往返缺陷，便于其修复后撤除绕行；
- [ ] v1 与 v2 对同一 SQL 给出相同的物理来源集合（跨契约一致性测试）；
- [ ] `normalized_sql` 的处理方式已明确选择并写进 PR；
- [ ] MERGE 的 ROOT 声明目标关系，且不产生 `target` 别名绑定；
- [ ] 两条相关引用守卫测试继续通过；
- [ ] 所有 golden 变化逐键解释，只有新增、没有既有值被改动；
- [ ] 相同输入两次解析字节一致；
- [ ] SQLGlot 30.0.0 / 30.16.0 / 30.17.0 均通过；
- [ ] 645 任务 v2 root-impact 缺口任务降至 0，v1 无变化，零回退；
- [ ] 提交中无真实任务、业务元数据、本地路径或生成产物。

---

## 7. 明确不做的事

- 不修改公开 API 和 `PUBLIC_CORE_API`；
- 不修改契约 major version 和既有字段含义；
- 不扩大 SQLGlot 依赖范围，也不试图在本仓库内修 SQLGlot 的 WITH 往返缺陷；
- 不通过删除 `_projection_state_missing_reasons()` 的第二个条件来「修好」G——
  那会让目标列名不是 `*` 的真通配符漏报；
- 不为 H 新增 `position` 枚举值；
- 不在未逐键审查的情况下重生成任何 golden；
- 不因为 v2 的缺口数字「前后一致」就判定它们是既有的、可接受的。
