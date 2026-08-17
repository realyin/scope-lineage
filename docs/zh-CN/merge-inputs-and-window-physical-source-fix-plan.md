# MERGE 输入声明与混合别名表达式物理来源修复方案

## 1. 文档目的与范围

`#18`、`#19` 之后，645 个外部任务里仍有 2 个任务携带 root-impact 事实缺口。本文把这两个
问题细化到开发级：复现 case、根因（含代码位置与实测证据）、开发方案、TDD 顺序、验证方法。

方案状态：**Ready for implementation**。两个问题都有合成复现，根因均经隔离实验确证。

优先级：

- P0-D：MERGE 的 ROOT 作用域没有输入边，导致 `target` / `source` 别名在表达式解析层无法绑定；
- P0-E：表达式同时引用作用域别名与物理表别名时，物理表引用被整体跳过。

两者都会改变 golden 可见的输出，必须逐字节审查差异并在 PR 中逐条解释。这是它们没有并入
`#19` 的原因。

完成标准是产出可信血缘。让这两个任务的缺口计数归零但引入未经解释的 golden 变化，
不算修复完成。

所有 case 使用合成表名与字段名。真实任务、业务元数据和解析产物一律留在仓库外。

### 1.1 分析过程中被推翻的三个判断

记录在案，避免后续 Agent 重走弯路：

1. **「E 是同一物理表被引用两次的 occurrence 问题」——错。** 那个 `_1` 后缀是**真实表名**，
   两张表都在 `source_tables` 里，与 occurrence 去重无关。
2. **「真实产物里 `expansion_status: None` 说明主通路没跑」——错。** 那只是序列化省略了
   默认值，插桩显示实际是 `full`。不要用产物里字段的缺席推断执行路径。
3. **「D 的事实推断不出来」——错。** 列级来源**早就正确**，缺的只是表达式解析层查的那张表。

---

## 2. 问题 D：MERGE 的 ROOT 没有输入边

### 2.1 复现 case

两种形态都稳定复现，schema 为
`{"ods.source": ["id", "attribution_id"], "mart.target": ["id", "attr_id"]}`：

**D1 — USING 比目标多一层查询块**

```sql
WITH tmp AS (SELECT id, attribution_id FROM ods.source)
MERGE INTO mart.target target
USING (SELECT a_.id, a_.attribution_id FROM (SELECT id, attribution_id FROM tmp) a_) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET
  target.attr_id = COALESCE(target.attr_id, source.attribution_id)
```

**D2 — USING 的表没有 schema**

```sql
MERGE INTO mart.target target
USING (SELECT id, attribution_id FROM tmp_external) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET
  target.attr_id = COALESCE(target.attr_id, source.attribution_id)
```

当前实测（两者一致）：

```text
ROOT.alias_source_bindings : []
ROOT.attr_id 列级来源       : [('mart.target','attr_id'), ('subq:source','attribution_id')]   ← 已经是对的
ROOT.attr_id 表达式解析     : fields=[('mart.target','attr_id')]
                              missing=['alias_not_bound_to_input_source:source']
lineage_fact_gaps          : [alias_binding_missing, root_impact=true]
```

**注意第二行**：`source` 别名在列级解析里已经正确绑到 `subq:source`。这条缺口不是「推断不
出来」，是表达式解析层去查了一张从未填过的表，而没有用它已经握有的事实。

对照：把 `COALESCE(...)` 换成裸的 `source.attribution_id` 时不产生缺口——列级解析走另一条
路径，只有需要按别名解析限定引用的表达式才会暴露这个洞。

### 2.2 根因

两段独立的事实，缺一不可：

**(a) MERGE 的 ROOT 从来没有输入边。** 实测：

```text
subq:source.input_edges = [('ods.source', 'physical_table', 'source')]
ROOT.input_edges        = []
```

链路 `input_edges → _populate_scope_input_source_refs()` (`scope_facts.py:241`)
`→ _populate_scope_alias_source_bindings()` (`scope_facts.py:442`) 断在最上游，所以
`alias_source_bindings` 为空。契约层面同样为空——现有 `merge` golden 里 ROOT 的 `inputs`
和 `alias_source_bindings` 都是 `null`。**一条 MERGE 的 ROOT 在契约里看上去没有任何输入**，
目标表和 USING 关系双双缺席。这本身就是契约的完整性缺口，与本缺口是否修复无关。

**(b) 表达式解析的别名回退链没有覆盖作用域来源。**
`column_expression_resolution.py:50-56` 已经有两级尝试：

```python
physical_table = _physical_source_for_qualifier(scope_data, qualifier)      # 查 alias_source_bindings（空）
if not physical_table:
    physical_table = _physical_source_for_unbound_qualifier(physical_fields, field)  # 查已收集的物理字段
if not physical_table:
    unresolved_qualifiers.append(qualifier)                                 # 放弃
```

第二级只看**已经收集到的物理字段**，此时只有 `mart.target.attr_id`，不含 `attribution_id`，
所以回退失败。而 `column.sources` 里的 `('subq:source','attribution_id')` 没有被任何一级使用。

设计上已经预期了「别名可能绑不上」，缺的是把列级来源接进这条回退链。

### 2.3 开发方案

**推荐 D-fix-1：补齐 MERGE ROOT 的输入边**，修的是 (a) 这个源头，同时关闭契约完整性缺口。

1. 目标关系：别名取 `MERGE INTO ... AS <alias>` 的别名（无别名时取表名），
   `source_type` 为 `physical_table`，`source_id` 为目标表限定名，`position` 标为 `merge_target`；
2. USING 关系：别名取 USING 的别名（缺省 `source`），`source_id` 取
   `result.merge_using_scope_id`，`source_type` 为 `scope`，`position` 标为 `merge_using`；
3. 两条边顺序固定为「目标、USING」，与 SQL 书写顺序一致，保证输出确定性；
4. `merge_using_scope_id` 为空时**不补 USING 边**，也不伪造——`#18` 已保证正常 MERGE 一定有
   USING 作用域，缺失属于内部不变量被破坏，交由既有失败路径处理。

**备选 D-fix-2：给回退链加第三级，用 `column.sources` 追踪物理来源。** 影响面小得多
（不新增 `inputs`），但把 (a) 留在原地：MERGE 产物继续声明自己没有输入。

选择 D-fix-1 的理由是它修因不修果；若 Checkpoint 4 的 golden 审查发现既有事实被改动
且无法解释，退回 D-fix-2 并把 (a) 单独立项。

修改文件：

- `scope_lineage/scope/scope_facts.py`（输入边构建处，`scope_facts.py:216` 附近）
- `tests/core/test_merge_root_inputs.py`（新增）
- `tests/core/fixtures/lineage_contract/merge/`（golden 更新，逐字节解释）
- `tests/core/fixtures/task_lineage_contract/merge_cte_source/`（同上）
- `docs/zh-CN/lineage-json.md`（`inputs` 字段对 MERGE 的含义）

### 2.4 golden 影响与风险

**这是本方案风险最高的一处。** 每一份 MERGE 产物都会新增 ROOT 的 `inputs` 与
`alias_source_bindings`。要求：

- 变化必须**只有新增**：`columns`、`outputs`、`field_mapping_chains`、`end_to_end_lineage`
  的既有值不得改变；
- 若发现既有事实被改动，先停下来查清原因，不得直接重生成 golden；
- `position` 取值 `merge_target` / `merge_using` 是新增枚举值，需逐项核对
  `lineage.schema.json` 未对该字段做闭集约束。

---

## 3. 问题 E：混合别名表达式跳过物理表来源

### 3.1 复现 case

合成归约**已完成**，8 行 SQL 稳定复现，schema 为
`{"ods.s": ["id","a"], "ods.f": ["id","b"], "mart.t": ["x"]}`：

```sql
INSERT INTO mart.t
WITH c AS (SELECT id, a FROM ods.s)
SELECT ROW_NUMBER() OVER (
  PARTITION BY CASE WHEN p.a IS NULL THEN 1 WHEN NOT f.b IS NULL THEN 2 ELSE 3 END
  ORDER BY p.id
) AS x
FROM c p LEFT JOIN ods.f f ON p.id = f.id
```

当前实测：

```text
expanded : ROW_NUMBER() OVER (PARTITION BY CASE WHEN `ods.s`.`a` IS NULL THEN 1
           WHEN NOT `f`.`b` IS NULL THEN 2 ELSE 3 END ORDER BY `ods.s`.`id`)
fields   : [('ods.s','a'), ('ods.s','id')]          ← 缺 ('ods.f','b')
missing  : ['expanded_expression_contains_unexpanded_alias:f']
gaps     : [expression_resolution_incomplete, root_impact=true]
```

与真实任务的症状逐项一致：CTE 别名被改写成限定表名，物理表别名原样留下，其字段不在
物理字段表中。

### 3.2 触发条件（隔离实验确证）

直接调用 `_resolved_scope_alias_expression_fact()` 三种输入：

| 表达式中的别名 | 返回 | 结果 |
| --- | --- | --- |
| 全部绑到作用域 | 结果 | 改写正确，字段完整 ✓ |
| 全部绑到物理表 | **None** | 交给下一个候选处理，正常 ✓ |
| **作用域 + 物理表混合** | 结果 | **物理别名原样留下，其字段丢失** ✗ |

**只有混合才出问题。** 这解释了为什么早先多个合成用例（窗口里单独一个物理别名、UNION CTE
与物理表 JOIN、物理列不在 schema 中）都不复现——它们的单个明细表达式没有混合。
真实任务里那个 `CASE WHEN` 同时引用了 CTE 别名和物理表别名，正是混合。

### 3.3 根因

`_resolved_scope_alias_expression_fact()`（`scope_facts.py:2115`，调用点
`scope_facts.py:1881` / `scope_facts.py:1929`）：

```python
for qualifier, field in qualified_refs:
    source_id = alias_to_source.get(qualifier)
    if not source_id or not _is_internal_scope_id(source_id):
        continue          # <- 物理表来源在这里被整体跳过
```

物理表来源既不做文本替换，也不向 `physical_fields` 追加字段；函数末尾又执行

```python
physical_fields = _ordered_physical_fields_in_expression(expanded_expression, ...)
```

按文本过滤，于是字段即便在别处被收集也会被丢弃。

函数的隐含契约是「一个引用都没解析就返回 None」（`resolved_internal_ref` 为 False 时返回
None）。缺陷在于：**解析了一部分就返回结果，把部分答案当成完整答案交出去**。

已在真实任务上插桩确认该函数就是写入者（命中，返回 11 个物理字段，其中没有那张物理表的）。

`expanded_expression_contains_unexpanded_alias:f` 因此是**正确信号**，指向真实缺失的物理
字段，不是误报。修复方向是补齐物理来源处理，**不是放宽判定**。

### 3.4 开发方案

**E-fix-1（采用）：让该函数按主通路的方式处理物理表来源。**

1. `source_id` 不是内部作用域 ID 时不再 `continue`，按物理来源处理；
2. 把 `<别名>.<字段>` 改写为限定表名形式（复用 `_qualified_physical_field_sql` /
   `_replace_qualified_ref_with_expression`）；
3. 向 `physical_fields` 追加 `{"table": <限定表名>, "field": <字段>}`；
4. 该别名绑定状态不是 resolved 时不改写、不追加，保留原有 `missing_reasons`——不确定就留缺口；
5. 不改动函数末尾按文本过滤物理字段的行为：改写做对了，过滤自然留下正确字段。

**E-fix-2（实验后否决，记录理由）：** 让函数在「没能处理全部引用」时返回 `None`，交给下一个
候选。实测结果：

```text
fields  : [('ods.s','a'), ('ods.s','id'), ('ods.f','b')]   ← 物理字段补回来了
missing : ['expanded_expression_contains_unexpanded_alias:f']  ← 缺口仍在
```

字段能补回，但**缺口判定看的是文本**，下一个候选同样不改写文本，所以缺口不消。
**任何只补字段不改写文本的修法都无效**，这条必须写进实现者的注意事项。

修改文件：

- `scope_lineage/scope/scope_facts.py`
- `tests/core/test_mixed_alias_expression_expansion.py`（新增）

### 3.5 风险

该函数是多处刷新逻辑的公共出口，改动会影响所有由它写入解析的输出。必须：

- 在 645 语料上比对**每个任务**的完整链路数与物理字段数，任何一项下降都按回归处理；
- 既有 golden 若变化，逐字节解释；预期是**物理字段只增不减**，不应出现字段被替换或重排。

---

## 4. TDD 实施顺序

每个 checkpoint 先写失败测试、确认失败原因正确，再改生产代码。

### Checkpoint 1：D 的失败测试

`tests/core/test_merge_root_inputs.py` 写入 D1、D2，断言：

```python
assert [(b["alias"], b["source_id"], b["source_type"]) for b in root.alias_source_bindings] == [
    ("target", "mart.target", "physical_table"),
    ("source", "subq:source", "scope"),
]
assert result.diagnostics.lineage_fact_gaps == []
```

再补三条边界断言：目标无别名时取表名；USING 无别名时为 `source`；同一 SQL 连续解析两次
`inputs` 顺序一致。

确认测试失败，且失败原因是绑定为空而非其它。

### Checkpoint 2：D 的实现

```bash
python -m pytest tests/core/test_merge_root_inputs.py -q
python -m pytest tests/core/test_merge_scope_compat.py -q
```

### Checkpoint 3：D 的 golden 审查

```bash
python -m pytest tests/core/test_lineage_contract_baseline.py -q
python -m pytest tests/core/test_task_lineage_contract_baseline.py -q
```

预期失败。**逐字节 diff 后**再重生成，并在 PR 中说明新增了哪些字段、为什么是新增而非修改、
既有事实是否有任何一处改变。出现 `columns` / `outputs` / `end_to_end_lineage` 变化就停下
查清原因，必要时退回 D-fix-2。

### Checkpoint 4：E 的失败测试

`tests/core/test_mixed_alias_expression_expansion.py` 写入 §3.1 的合成 SQL，断言
`physical_source_fields` 含 `('ods.f','b')`、`missing_reasons` 为空、`lineage_fact_gaps` 为空。

同时写两条保护测试：

- **反向保护**：物理别名绑定未解析时仍保留 `missing_reasons`，防止实现用「一律改写」
  把真实缺口抹掉；
- **单元级三态**：直接调用 `_resolved_scope_alias_expression_fact()`，断言全作用域、
  全物理、混合三种输入的行为，把 §3.2 的表格固化成测试。

### Checkpoint 5：E 的实现

```bash
python -m pytest tests/core/test_mixed_alias_expression_expansion.py -q
python -m pytest tests/core/test_parser_capability_matrix.py -q -k window
```

### Checkpoint 6：契约、确定性与跨版本

```bash
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py   # ×30.0.0/30.16.0/30.17.0
python -m pytest tests/core/test_contract_versioning.py -q
python -m ruff check scope_lineage tests
python -m build && python tests/architecture/verify_distribution.py dist/*
```

要求相同输入连续解析两次字节一致。

### Checkpoint 7：外部语料验收

645 任务，修复前后 v1 与 v2 双版本对比。**v2 必须单独跑**——`#19` 的教训是 v1 的结论不能
代表 v2。要求：

- root-impact 缺口任务 **2 → 0**；
- 无任何任务的完整链路数下降；
- 无任何任务的物理字段数下降；
- 已建模语句数不变；
- 无新增 parse 失败、无新增 recovered syntax；
- warning 的每一处增量都能逐类解释。

外部路径经环境变量传入，产物不入库。

---

## 5. 验收清单

- [ ] MERGE 的 ROOT 声明目标关系与 USING 关系两条输入；
- [ ] 目标/USING 无别名时的别名回退正确；
- [ ] `merge_using_scope_id` 缺失时不伪造 USING 边；
- [ ] 混合别名表达式中物理表引用被改写且计入物理字段；
- [ ] `_resolved_scope_alias_expression_fact()` 的三态行为有单元测试固化；
- [ ] 绑定未解析时仍保留 `missing_reasons`；
- [ ] 所有 golden 变化逐字节解释，且只有新增、没有既有事实被改动；
- [ ] 相同输入两次解析字节一致；
- [ ] SQLGlot 30.0.0 / 30.16.0 / 30.17.0 均通过；
- [ ] 645 任务 v1 与 v2 双版本零回退，root-impact 缺口任务降至 0；
- [ ] 提交中无真实任务、业务元数据、本地路径或生成产物。

---

## 6. 明确不做的事

- 不修改公开 API 和 `PUBLIC_CORE_API`；
- 不修改契约 major version；
- 不扩大 SQLGlot 依赖范围；
- 不通过放宽 `_unexpanded_bound_aliases_in_expression` 消除 E 的缺口；
- 不采用「只补物理字段、不改写表达式文本」的修法（§3.4 已实测无效）；
- 不在未逐字节审查的情况下重生成任何 golden；
- 不顺带重构该函数的其它分支或窗口刷新通路。
