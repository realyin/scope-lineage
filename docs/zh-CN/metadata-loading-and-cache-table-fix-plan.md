# 元数据加载与 `cache lazy table` 修复方案

## 1. 文档目的与范围

本文针对一份外部能力缺口清单（1756 个任务、3438 份表元数据、82889 条缺口）的复核结果。
复核用**报告点名的真实任务**逐条实测，结论与原清单有重大出入：**7 项里 4 项是工具缺陷，
3 项是元数据加载问题伪装成的解析缺陷**。

方案状态：**Ready for implementation**（P0/P1 部分）。P2 两项需先完成合成归约。

优先级：

- **P0-I**：元数据加载器一个文件不合格即中止整体加载 —— 这是原清单缺口①③ 的真正根源；
- **P0-J**：`cache lazy table ... as select` 未被识别为任务内产出 —— 占全部缺口约 1/3，
  原清单缺口② 也归并于此；
- **P1-K**：元数据无法按需加载，全量 3438 份耗时 >2 分钟，是使用者自建绕行方案的动因；
- **P1-L**：Spark 引号正则列选择 `` `(dt)?+.+` `` 未展开（原清单缺口④）；
- **P2-M/N**：UDTF 输出列的 struct 成员访问、union 分支内子查询表引用（原清单缺口⑤⑥），
  真实任务上现象成立，但**尚无合成复现**。

完成标准是产出可信血缘。P0 两项修复后，原清单中 ①②③⑦ 四类缺口应全部消失。

所有 case 使用合成表名与字段名。真实任务、业务元数据和解析产物一律留在仓库外。

### 1.1 对原清单的三处更正

复核推翻了原清单的三条归因。记录在案，因为**照原归因去修，方向是错的**。

| 原判定 | 实测 | 更正 |
| --- | --- | --- |
| ① 输入表 schema 列注入失败（疑似工具 bug） | 按文件加载元数据后 **0 缺口** | 不是工具缺陷；是「合并单文件绕过校验」这一绕行方案造成的 |
| ② `col alias` 隐式别名语法未解析 | sqlglot 解析结果就是 `Alias(alias=p)` | 语法解析无缺口；源表由 `cache lazy table` 产出，**与 ⑦ 同因** |
| ③ 聚合表达式内部字段追溯不全 | 补入该表元数据后 **0 缺口** | 不是工具缺陷；是该表元数据未进入 schema |

原清单缺口① 自己列了两个待验证方向，其中第 1 个（合并单文件是诱因）是对的。它被削弱的
理由是「同路径另一张表成功」——但那只说明绕行方案的失败不是全局性的，不足以排除它。

原清单缺口④ 的现象成立，归因需改：`(dt)?+.+` 不是「子查询投影推断失败的通配占位符」，
而是 SQL 里真实写着的 Spark 引号正则列选择语法。

---

## 2. 问题 I：一个元数据文件不合格，整个加载中止

### 2.1 复现 case（已验证）

一份表元数据 JSON，DDL 中 `PARTITIONED BY (dt)`，而 `schema` 数组不含 `dt`
（也没有 `isPartition=1` 的列）：

```json
{
  "table_name": "risk.demo_table",
  "schema": [{"columnName": "id", "columnType": "string", "columnIndex": 0, "isPartition": 0}],
  "ddl": "CREATE TABLE risk.demo_table (id string) USING iceberg PARTITIONED BY (dt)"
}
```

把它和**一份完全正常**的元数据放进同一目录，实测：

```text
load_schema_sources([目录])
  -> MetadataFileError: 源表权威 JSON 元数据无效: …demo_table_metadata.json
     问题: schema_ddl_column_set_mismatch
  >>> 同目录那张正常表也一并拿不到
```

真实语料中这种形态 **2 / 3434** 份 —— **2 份文件让 3434 份全部加载不了**。

### 2.2 根因

`_append_loaded_table_schema()`（`metadata/schema_metadata.py`）在权威 JSON 元数据的
`schema` 列集合与 `ddl` 列集合不一致时 `raise MetadataFileError`，异常穿透
`load_schema()` → `load_schema_sources()`，终止整批加载。

两层问题：

1. **失败粒度错了。** 一份表的元数据有问题，只应影响那一张表。让它中止整批，等于把
   「一张表缺元数据」放大成「所有表都没有元数据」；
2. **问题定性错了。** 现有实现把「schema 数组与 DDL 的列集合不同」当成需要校验的
   *不一致*。但两者本就是同一张表的两种描述，强弱有别 —— 这是**优先级问题，不是校验
   问题**。`PARTITIONED BY` 里的分区列不出现在列数组中，是完全正常的导出形态。

后果不止于加载失败：使用者为绕开它会把元数据合并成字典形态的单文件、绕过校验，
而那个绕行方案正是原清单缺口① 的成因。**工具的缺陷在加载器，不在列注入。**

### 2.3 开发方案

把「schema 数组与 DDL 是否一致」这个**校验问题**，换成「谁说了算」这个**优先级问题**。
现有实现先尝试用 DDL 对齐列，对齐失败就判 `schema_ddl_column_set_mismatch`；
本方案改为 DDL 直接为准，于是「不一致」这个概念不再存在。

**三级优先：**

1. **DDL 可解析 → 以 DDL 的列为准**（含 `PARTITIONED BY` 声明的分区列）。
   列数组只用来补 type / comment 等细节，不参与「列集合是否一致」的判定；
2. **DDL 缺失或不可解析 → 退回列数组**，并记录一条说明「本表列来自 Schema 导出而非 DDL」
   的诊断，让消费者知道这张表的列不是最强来源给出的；
3. **两者都不可用 → 报错**。

**报错粒度：只废弃该表。** 记录诊断、跳过这一张表，其余表照常加载。一份元数据有问题
只应影响它描述的那张表；让它中止整批，等于把「一张表缺元数据」放大成「所有表都没有
元数据」——那正是把使用者逼去自建绕行方案的行为，也正是原清单缺口①③ 的成因。

采用优先级规则后第 3 级会变得罕见：只有 DDL 与列数组同时不可用才触发，那确实该报错。

**配套：**

- 被跳过的表汇总进 `metadata_conflicts`，使 `metadata_coverage` 能如实反映
  「这张表的元数据被拒绝了」，而不是表现为「这张表没被引用」；
- 诊断须给出文件名与具体原因，让使用者能修数据而不是绕过工具；
- `schema_ddl_column_set_mismatch` 这一 issue 类型随之退役；
  `schema_ddl_table_name_mismatch`（表名对不上）仍然保留——那是另一类问题。

修改文件：

- `scope_lineage/metadata/schema_metadata.py`
- `tests/core/test_metadata_loading_faults.py`（新增）
- `docs/zh-CN/` 中 schema 优先级/元数据相关文档

---

## 3. 问题 J：`cache lazy table ... as select` 未识别为任务内产出

### 3.1 复现 case（已验证）

```sql
cache lazy table tmp_part1 OPTIONS ('storageLevel' 'DISK_ONLY') as select id, v from ods.s;
INSERT INTO mart.t SELECT t.id, t.v FROM tmp_part1 t
```

schema 为 `{"ods.s": ["id","v"], "mart.t": ["id","v"]}`。实测：

```text
语句: [('CACHE', 'unsupported'), ('INSERT', 'modeled')]
missing_tables: ['tmp_part1']
```

真实任务上后果放大：一个任务 1205 条缺口，全部是
`bare_unqualified_field / root_bare_no_unique_input`，`missing_tables` 就是那几张
cache 产出的表。

### 3.2 根因

sqlglot 把该语法解析为 `exp.Cache`，其结构与 CTAS **完全同构**：

```text
exp.Cache  args = ['this', 'lazy', 'options', 'expression']
           this       = tmp_part1        （产出表）
           expression = SELECT id, v …   （产出投影）
```

但 `_is_ctas()` 只认 `isinstance(tree, exp.Create)`，于是 `_collect_insert_trees()`
把它归入 `not_a_table_write_from_select` 跳过。产出表因此：

- 进不了 `script_local_schema`（该机制只登记 CTAS）；
- 进不了 `table_state_graph` 的 producer；
- 下游读取时当作无元数据的外部物理表 —— 字段全部成缺口，级联放大。

该语法的语义就是「把查询结果缓存成本任务内可读的表」，与 CTAS 在血缘上等价。

### 3.3 开发方案

1. 增加 `_is_cache_table()` 判据：`isinstance(tree, exp.Cache) and tree.expression is not None`；
2. `_collect_insert_trees()` 把它收进写语句集合；
3. 语句种类标为 `CACHE_TABLE`（不复用 `CTAS`：产物是缓存不是建表，契约消费者应能区分）；
4. `script_local_schema()` 放宽为「CTAS 或 CACHE_TABLE」，产出列照旧取自已解析的投影；
5. 与 CTAS 一致：投影仍是 `*` 且无法展开时不登记，不猜列名。

修改文件：

- `scope_lineage/scope/scope_builder.py`
- `scope_lineage/scope/task_lineage.py`（语句归类）
- `tests/core/test_cache_table_as_select.py`（新增）
- `docs/zh-CN/lineage-json.md`、`docs/zh-CN/task-lineage-v2.md`（新增语句种类）

### 3.4 契约影响

`stmt_kind` 新增取值 `CACHE_TABLE`。需逐项核对 `lineage.schema.json` /
`lineage-v2.schema.json` 是否对该字段做闭集约束 —— **`position` 字段就有过闭集约束、
在实施中才被发现**，这次必须先查。若是闭集，新增取值属于契约决策，需单独评审。

---

## 4. 问题 K：元数据无法按需加载

### 4.1 实测

| 加载方式 | 文件数 | 耗时 |
| --- | --- | --- |
| 目录全量 | 3434 | **分钟级**（CLI 单任务解析直接超时）|
| 只加载任务引用到的表 | 59 | **5.8s** |

**成本不来自文件数量，来自少数超宽表。** 分批实测：

```text
200 份小文件       0.4s
最大的 5 份        每份 1.09 ~ 2.78s（3.4MB / 2.8MB / 2.4MB / 2.0MB / 1.8MB）
文件大小中位数      6.2 KB
98 份 >100KB 的文件占 88MB 总量中的 59MB
```

3300 多份普通文件加起来还没这几十份贵 —— 瓶颈是对列数上千的宽表做完整 `CREATE TABLE`
SQL 解析。**「文件多所以慢」是错误表述**，先前一版方案据此写的按需加载理由不完整。

### 4.2 根因与方案

`load_schema_sources()` 对传入目录一律全量读取。CLI 在解析前已能拿到任务 SQL，
因此可以先扫出引用的表名，只加载对应文件。

1. CLI 增加按需加载：先解析任务 SQL 取表名集合，再按表名匹配元数据文件；
2. 匹配需大小写不敏感、并考虑 catalog 前缀（SQL 常写
   `catalog.db.table`，元数据文件名常为 `db.table`）—— 真实语料两种差异都出现过；
3. 匹配不到的表照旧进入 `metadata_coverage.missing_tables`，行为不变；
4. 保留全量加载作为显式选项，供需要一次性预热的场景使用；
5. **超宽表 DDL 走轻量列提取**：列集合本可以不做完整 SQL 解析就得到。按需加载只是让宽表
   在不被引用时不付代价，被引用时那 1~3 秒仍然要付 —— 这一条才是根治。
   前提是轻量提取与 sqlglot 解析给出相同结果，需用真实语料逐表比对后才可启用。

**这一项的价值不只是性能**：它直接消除使用者自建元数据绕行方案的动机，而那类绕行正是
原清单缺口①③ 的成因。

修改文件：

- `scope_lineage/cli.py`
- `scope_lineage/metadata/schema_metadata.py`
- `tests/core/test_selective_metadata_loading.py`（新增）

---

## 5. 问题 L：Spark 引号正则列选择未展开

### 5.1 复现 case（已验证）

```sql
INSERT INTO mart.t
SELECT a.id, a.v FROM (SELECT `(dt)?+.+` FROM ods.s) a
```

schema 为 `{"ods.s": ["id","v","dt"], "mart.t": ["id","v"]}`。实测：

```text
status=partial gaps=3
  object='(dt)?+.+' scope='subq:a'  reasons=['no_physical_source_fields']
  object='id'       scope='ROOT'    reasons=['no_physical_source_fields']
  object='v'        scope='ROOT'    reasons=['no_physical_source_fields']
```

与真实任务的缺口形态逐项一致。

### 5.2 根因

`` `(dt)?+.+` `` 是 Spark 的引号正则列选择（`spark.sql.parser.quotedRegexColumnNames`），
语义为「选出列名匹配该正则的所有列」。工具把它当成字面列名，于是子查询输出一个不存在的
列，下游引用全部落空。

### 5.3 开发方案

1. 识别投影中的引号列名是否为正则模式（含正则元字符、且在 schema 中不存在同名列）；
2. schema 已知时按正则展开为匹配的列集合，与 `SELECT *` 的展开走同一条路；
3. **schema 未知时不猜**：保留该投影并记录 fact gap，说明需要源表 schema 才能展开
   —— 与 `projection_wildcard_unexpanded` 的处理口径一致；
4. 不改变普通引号列名的行为：`` `dt` `` 这种确实存在的列名照旧按字面处理。

判据必须先查 schema 再判正则，否则一个真实存在、名字含元字符的列会被误展开。

修改文件：

- `scope_lineage/scope/scope_builder.py` 或投影解析所在模块
- `tests/core/test_regex_column_selection.py`（新增）

---

## 6. 问题 M / N：尚无合成复现，先归约再动手

两项在真实任务上现象成立，但**我的合成用例不复现**，因此不具备开工条件。

### 6.1 M：UDTF 输出列的 struct 成员访问

真实形态是链式 LATERAL VIEW，第二层引用第一层输出列的 struct 成员：

```sql
LATERAL VIEW EXPLODE(from_json(payload, 'array<struct<unitCode:string,detail:array<...>>>')) t AS arr
LATERAL VIEW EXPLODE(arr.detail) t2 AS d
SELECT DISTINCT arr.unitCode AS unit_code
```

真实任务报 `alias_not_bound_to_input_source:arr`。

**原清单把 `arr` 判为「UDTF 输出的表别名」，这不成立**：`arr` 是第一个 explode 的
**输出列**（`t AS arr`），`t` 才是表别名。所以问题不是「UDTF 别名未建模」，
而是对 UDTF 输出列做 struct 成员访问时的绑定。

等价合成用例实测 **0 缺口**，说明触发条件还包含未识别的因素（可能与 `from_json` 的
schema 字符串、或第二层 explode 的嵌套深度有关）。

### 6.2 N：union 分支内子查询的表引用

真实形态是 union 各分支里的标量子查询，表无别名、列未限定：

```sql
(SELECT COUNT(DISTINCT id_unqf) FROM lods_extds.some_table WHERE source = 'x') AS total_num
```

真实任务报 `expanded_expression_contains_unexpanded_alias:some_table`（表短名被当成
未扩展的别名）。等价合成用例实测 **0 缺口**。

### 6.3 处理方式

M、N 的 Checkpoint 第一步都是**从真实任务归约出合成 SQL**（外部路径经环境变量传入，
不入库）。**归约不成功就不要改生产代码** —— 改一个没有测试能证明存在的问题，
既无法验证也无法防回归。归约失败时把现状与已排除的因素记进 issue，先做 P0/P1。

---

## 7. TDD 实施顺序

按 J → I → K → L → M/N 执行：J 影响面最大且根因最清晰，I 解除使用者绕行的根源。
每个 checkpoint 先写失败测试、确认失败原因正确，再改生产代码。

### Checkpoint 1：J 的失败测试

`tests/core/test_cache_table_as_select.py`，用 §3.1 的 SQL 断言：

- 两条语句都 `modeled`，第一条 `stmt_kind == "CACHE_TABLE"`；
- `metadata_coverage.missing_tables` 不含 `tmp_part1`；
- 下游 INSERT 的字段追溯到 `ods.s.id` / `ods.s.v`；
- `lineage_fact_gaps == []`；
- 边界：cache 的投影是 `SELECT *` 且源表无 schema 时**不登记**、不猜列名。

先查 `stmt_kind` 是否为契约闭集（见 §3.4）；是闭集则本 checkpoint 暂停，先做契约评审。

### Checkpoint 2：J 的实现

```bash
python -m pytest tests/core/test_cache_table_as_select.py -q
python -m pytest tests/core/test_script_local_table_schema.py tests/core/test_task_state_lineage.py -q
```

### Checkpoint 3：I 的失败测试

`tests/core/test_metadata_loading_faults.py`：

- §2.1 的两文件目录：加载**成功**，两张表都可用 —— 问题文件按 DDL 优先取列，
  连诊断都不该有，因为它本就不是问题；
- DDL 可解析时列集合以 DDL 为准，分区列包含在内，type/comment 由列数组补足；
- DDL 缺失 → 退回列数组，并带「列来自 Schema 导出而非 DDL」的诊断；
- DDL 不可解析 → 同上，诊断需能区分「缺失」与「解析失败」；
- **两者都不可用 → 只废弃该表**：加载不中止，其余表可用，该表进 `metadata_conflicts`；
- **反向保护**：DDL 与列数组给出的列不同时，取 DDL 的那份 —— 断言列数组独有的列
  不出现在结果里，防止实现偷懒做并集，那等于两个来源都不算数。

### Checkpoint 4：I 的实现

```bash
python -m pytest tests/core/test_metadata_loading_faults.py -q
python -m pytest tests/core -q -k schema
```

### Checkpoint 5：K 的测试与实现

- 按需加载只读取引用到的表对应文件（断言读取文件数）；
- 大小写与 catalog 前缀差异下仍能匹配；
- 匹配不到的表照旧进 `missing_tables`；
- 全量加载选项行为不变。

### Checkpoint 6：L 的测试与实现

`tests/core/test_regex_column_selection.py`：§5.1 的 case 断言 0 缺口且列展开为
`id, v, dt`；schema 未知时保留缺口；真实存在的引号列名行为不变。

### Checkpoint 7：契约、确定性与跨版本

```bash
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py   # ×30.0.0/30.16.0/30.17.0
python -m pytest tests/core/test_contract_versioning.py -q
python -m ruff check scope_lineage tests
python -m build && python tests/architecture/verify_distribution.py dist/*
```

golden 若变化，逐键结构比对后再重生成，PR 中说明每一处。

### Checkpoint 8：外部语料验收

1756 个任务，修复前后 v1 与 v2 双版本对比。**v2 必须单独跑**。要求：

- 原清单 ⑦ 涉及的 8 个任务缺口归零（约 27853 条）；
- 原清单 ①③ 涉及的 4 个任务在**按目录加载**下也归零（当前只在按文件加载下归零）；
- 元数据加载不再因个别文件中止；
- 无任何任务的完整链路数或物理来源数下降；
- 无新增 parse 失败、无新增 recovered syntax；
- 单任务解析耗时从 >120s 降到秒级。

外部路径经环境变量传入，产物不入库。

---

## 8. 验收清单

- [ ] `cache lazy table ... as select` 被识别为任务内产出，下游可解析；
- [ ] cache 投影无法展开时不登记、不猜列名；
- [ ] `stmt_kind` 新增值已确认不违反契约约束（或已单独评审）；
- [ ] DDL 可解析时以 DDL 的列为准，分区列包含在内；
- [ ] DDL 缺失或不可解析时退回列数组，并有可区分二者的诊断；
- [ ] 两者都不可用时只废弃该表，加载不中止，该表进 `metadata_conflicts`；
- [ ] 两个来源列不同时取 DDL，不做并集；
- [ ] 按需加载只读取引用到的元数据文件，大小写与 catalog 差异不影响匹配；
- [ ] 引号正则列选择按 schema 展开，schema 未知时保留缺口；
- [ ] M/N 或有合成复现后修复，或明确记录为未归约、未动代码；
- [ ] 既有 golden 变化逐键解释；
- [ ] SQLGlot 30.0.0 / 30.16.0 / 30.17.0 均通过；
- [ ] 1756 任务语料零回退，目标缺口归零；
- [ ] 提交中无真实任务、业务元数据、本地路径或生成产物。

---

## 9. 明确不做的事

- 不修改公开 API 和 `PUBLIC_CORE_API`；
- 不修改契约 major version；
- 不扩大 SQLGlot 依赖范围；
- 不按原清单的 ①②③ 归因去改列注入、别名语法解析或聚合追溯 —— 那三处经实测不是工具缺陷；
- 不把 `CACHE_TABLE` 直接复用 `CTAS`：产物语义不同，消费者应能区分；
- 不在没有合成复现的情况下修改 M/N 的生产代码；
- 不把两个来源的列做并集来「兼容」两边 —— 那等于谁都不算数，必须有唯一权威；
- 不因为放宽了校验就默认元数据都可用 —— DDL 与列数组同时不可用时仍然废弃该表。
