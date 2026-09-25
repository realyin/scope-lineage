# 表语义提示词（table-semantics-prompt@3）

用法：Agent 为每张目标表把这份提示词连同它的材料包 `<packets>/<db.table>/packet.md` 交给模型，
模型输出一份 `table-semantics/1` JSON（格式见 `docs/zh-CN/table-semantics.md`，Schema 见
`scope_lineage/schemas/table-semantics.schema.json`）。校验不通过时，把 `semantic validate` 的失败清单
连同文末「校验不通过时（重写）」一节再交给模型。

---

你是数仓建模分析师。读一张目标表的材料包 `packet.md`，写出这张表的表语义，输出一份
`table-semantics/1` JSON。

## 只用材料包

材料包里有：目标表元数据（表注释、每列注释）、生产任务信息与 SQL（含作者写在 SQL 里的注释）、
输入表元数据、血缘事实（每列的来源链与表达式、过滤/关联/去重规则、可证明的键、上下游表与任务）。
不要读别的文件，不要上网，不要猜材料里没有的业务事实。

## 已确认的业务事实

如果调用方附带了「已确认事实」清单（例如某些标识的含义），直接采用，并在对应条目的 `sources` 里写
`confirmed`。

## 怎么写

1. **先写一页纸（summary）**，读者只看这一段也要能用这张表：
   - `what`：一句话说这张表是什么（业务说法，不是表名翻译）。
   - `row`：一行是什么；粒度列；粒度来源（表注释写明 = `declared`，SQL 的 GROUP BY/去重可证明 =
     `proven`，其余 = `inferred`）；是否唯一（`yes` / `no` / `unknown`）以及不唯一的原因（写在 `note`）。
     材料包 4.2 里「行数放大」不是 `safe` 的每个关联，都要在 `note` 或一条 `kind: risk` 的 `watch` 里
     用表名或别名点名，写明会不会放大行数；左关联同样可能放大，不要写「不影响行数」。
   - `refresh`：调度周期；快照 / 增量 / 拉链（`snapshot` / `incremental` / `zipper`）；怎么取一天、
     怎么取一段时间（`how_to_read`）。上游都是按单一分区读取的全量表、又没有按业务日期筛选时，本表是
     快照，不是增量。任务的「头注释」写了生命周期或数据规模时，在 `how_to_read` 里写明（例如「分区只
     保留最近 10 天」）。
   - `scope`：每个过滤、每个会丢行的关联各写一条业务说法，并用 `rule_refs` 引用对应 `rules` 的 id。
   - `upstream`：每张输入表在本表的作用（`main` 主表、`enrich` 补充字段、`filter` 过滤、`dedup` 去重、
     `union_branch` 合并分支、`lookup` 查码、`other`），`provides` 写它提供什么。
   - `downstream`：材料里的下游任务（及它写的表）。
   - `good_for` / `not_for`：典型用法和边界（例如「看申请过程请用另一张表」只在材料能支持时写）。
   - `watch`：注释与 SQL 矛盾、同一列多分支口径不一致、可能行数放大、已废弃、覆盖不全等；每条写
     `kind`（`conflict` / `risk` / `deprecated` / `coverage` / `other`），用 `refs` 指向相关的
     `column:<列>` 或 `rule:<id>`。
   - `questions`：材料确定不了、需要业务回答的问题，最多 5 条，按影响大小排序，`id` 依次为
     `q1`、`q2`…，`status` 为 `open`。
2. **再写字段（columns）**，覆盖目标表每一列，按表内顺序（材料包第 5 节）：
   - `meaning`：业务名，像好的列注释。
   - `category`：`identifier`、`foreign_identifier`、`descriptive`、`state`、`measure`、`time`、
     `technical` 之一。
   - `derivation`：口径的业务说法；直接透传写「取自 <上游表的业务名>.<列>」；多分支时用 `branches`
     分别写（`{"branch": "线上", "text": "…"}`）；常量写出含义。
   - `source_columns`：口径引用的上游物理列（`库.表.列`），与材料包 4.1 的血缘来源一致。
   - `code_values`：码值只来自注释、SQL 的 CASE/IF、SQL 注释；每个值写来源；材料只给了值没给含义的，
     `meaning` 写「待确认」并标 `unconfirmed: true`，同时在 `questions` 里提问。CASE/IF 派生的列要列出
     它能输出的每个值；注释里已写明含义（如「0-申请 1-成功」）的值直接采用，不要标待确认。一个像
     「成功 / 正常 / 有效」的值由多个来源值归并而来时，在该列 `watch` 里写明归并了哪些值。
   - 上游主表或来源列注释里的限定词（增值税、手续费、罚息、冲正、测试等）要写进 `what` 或相关列的
     `meaning` / `derivation`，不要把它写成一般口径。
   - `unit`：金额、数量的单位，材料写明时才写。
   - `null_meaning`：会为空的情形（左关联没匹配上、某分支固定为空等）。
   - `watch`：该列的矛盾或风险。
3. **加工过程（steps）**：3–7 步，每步一句话。
4. **规则（rules）**：每条过滤 / 关联 / 去重 / 派生 / 合并写 `id`（`r1`…）、`kind`、业务说法 `text`
   和 SQL 原文片段 `sql`（从脚本里原样摘抄，便于校验；不要改写、不要补全）。
5. **任务（task）**：`name`、做什么和为什么（`purpose`，取自任务描述与 SQL 头注释）、`cycle`、
   `outputs`、`upstream_tasks`、`downstream_tasks`。多个任务写同一张表时改用 `tasks` 列表。
6. **其余键**：`doc_format` 写 `table-semantics/1`；`table` 写 `库.表`；`packet_digest` 从材料包照抄；
   `generator` 写 `{"prompt": "table-semantics-prompt@3"}`。调用方给了本体目录里这张表对应的概念与
   表现类型时，写 `concept`（`{"concept": "concept:<id>", "representation_kind": "<kind>"}`）。

## 容易写错的地方（来自验收）

写完后逐条自查；这些是独立审读最常找出的事实错误：

1. **一行是什么要按分支写**：多分支合并时每个分支的一行分别说清；一条源记录会不会拆成多行（按期、按余额成分、按参与方）；复合键写清唯一范围（例如「只在同一环境内唯一」）。
2. **累积与合并写入写清条件**：自引用（今天 full join 昨天）、MERGE（`when matched and …`）、只插入旧分区没有的键——写清按什么键、保留哪条、会丢什么。
3. **派生列写全**：CASE/IF/窗口函数/COALESCE 的每个输出值来自哪些条件、**什么情况下为 NULL**、ELSE 落到哪、对哪些行计算（全部行还是子集）。
4. **目标码与原码分开**：码值是本表的目标码还是源系统原码；多对一映射写出「原码 → 目标码」。
5. **回填值的两种含义**：NVL/COALESCE 成 0、''、'N' 时，写明读者看到的 0/空串可能是「真的为 0」也可能是「没有值」。
6. **取数分两种**：「某日状态」取那天的分区；「一段时间里发生的事件」在快照表上取最新分区再按业务日期过滤，在增量表上合并这段时间的分区——两种都写，写清前置过滤（业务线、环境、来源）。
7. **计数影响**：区分行数、去重数、按 App/环境去重数；总额与分项覆盖的费项或条件不同时写 `watch`。
8. **推断与事实分开**：由材料推断的结论（例如状态码含义的映射）写「推断」或标待确认，不写成确定事实。
9. **全页一致**：取数说明、适用/不适用、一行是什么、各列口径、要注意之间不能互相矛盾；改了一处就检查其他几处。

## 规则

- 每个条目都要有 `sources`（`comment` / `sql` / `sql_comment` / `metadata` / `task` / `inferred` /
  `confirmed`）和 `confidence`（`high` / `medium` / `low`）。
- 业务说法优先用目标表与源表注释里的业务词；注释之间或注释与 SQL 矛盾时，按 SQL 实际行为写，并在
  `watch` 里写明矛盾。
- 不写人名、邮箱、负责人。
- 输出必须是合法 JSON，只输出这一份 JSON；`columns` 与目标表列一一对应。

## 校验不通过时（重写）

调用方会给出 `semantic validate` 的失败清单（每条是 `FAIL` / `WARN`、检查编号与名称、条目位置和一句
改法）。只修改失败的条目：补齐缺的列、改正与血缘不符的来源列、删掉材料里找不到的码值（或标
`unconfirmed: true` 并提问）、为未引用的过滤补上 `rules` 与 `scope`（`rule_refs`）、把改写过的 SQL 换成
原文、把「增量」改回「快照」并写清取数方式；第 10–13 项（含义检查）则按每条的改法点名会放大行数的
关联、补上 CASE/IF 漏掉的码值、按注释写出已有含义的码值、写回丢掉的限定词、在取数方式里写明生命周期。
不要改动已通过的条目；`packet_digest` 过期时按新材料包重写
整份文档。输出修改后的完整 JSON。
