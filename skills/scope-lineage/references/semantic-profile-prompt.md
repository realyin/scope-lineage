# 业务画像生成 Prompt v2（business_profile.md + business_profile.check.md）

由 SKILL.md 的「这个任务在做什么 / 生成业务画像」工作流引用。前置条件：已对目标任务跑过
`scope-lineage describe`，任务目录里有 `semantic.json` / `semantic.md`。

本文件的职责是把**确定性语义骨架**（Core 产出，只含 SQL 事实、元数据事实、结构推断）翻译成
业务方读得懂的交付物。骨架已经回答了「怎么算」，画像必须回答读者真正关心的四个问题：
**这个任务干什么 / 输出表一行是什么 / 每个字段什么意思 / 用它的时候要注意什么。**

产出**两个文件**，都与 `semantic.md` 同目录：

- `business_profile.md` —— 给读者的交付物：三件 + 一个短附录（A 已确认项 / B 备查项与待填取值 /
  C 风险边界）。
- `business_profile.check.md` —— 给写作方与复核者的生成记录：输入文件校验、来源标签与证据、
  结构推断项、自洽性检查、生成自检。它是质量门，一项都不能省，但**一个字都不进读者的文档**。

| 章 | 标题 | 写给谁 | 篇幅上限 |
| --- | --- | --- | --- |
| 一 | 任务语义卡 | 不看 SQL 的业务方 | ≤ 1 页，≤ 600 字 |
| 二 | 字段字典 | 用这张表的人与 Agent | 覆盖全部输出字段，一个不漏 |
| 三 | 待确认清单 | 要答问题的业务方 | ≤ **5 条**，几分钟答完 |
| 附录 A / B / C | 已确认项 / 备查项与待填取值 / 风险边界 | 用这张表的人 | 三节合计 ≤ 正文（一、二、三）字数的 **1/3** |
| 另一个文件 | 生成记录 `business_profile.check.md` | 复核的人、下一次生成的你 | 不限长 |

v1 的 L1–L9 不再作正文。风险边界表留在读者文档的附录 C；输入文件校验表、来源标签与证据表、
结构推断项清单、自洽性检查与生成自检表是写作方的质检记录，整体搬进 `business_profile.check.md`
——两个文件的正文里都不要重建它们。

空白骨架见 `references/business-profile-template.md` 与
`references/business-profile-check-template.md`，照它们的占位符填。

## 输入与读取方式

| 文件 | 必读 | 读法 | 用途 |
| --- | --- | --- | --- |
| `semantic.md` | 是 | 整读（它已是压缩视图） | 任务概览、输出形态与粒度、加工链路、规则、字段语义、可信度 |
| `semantic.json` | 是 | **按路径定向取**，不整读 | `task` / `inputs` / `output_shape` / `stages` / `rules` / `fields` / `confidence` |
| `diagnostics.json` | 是 | 整读；**警告数以 `statement_diagnostics.<stmt>.warnings` 与顶层 `warnings[]` 的并集为准**，骨架的 `confidence.warning_counts` 已是这个并集。顶层 `warnings[]` 只装任务级警告，语句级的都在 `statement_diagnostics` 里——**顶层是空数组不等于「无警告」**。另按 `lineage_fact_gaps[]` / `analysis_status` 取 | 风险边界、断链、metadata 缺失，并与 `semantic.json.confidence` 交叉校验 |
| `mapping.md` | 否 | 只读第 5/6 节 | 需要逐 scope 的技术细节或完整表达式时补充 |
| `lineage.json` | 否 | **只通过 `scripts/query.py chain` / `summary` 定向取** | 单字段完整推导链、任务级统计。**永远不要整读** |
| 原始任务 JSON（若可得） | 否 | **仅当骨架缺下列键时**（旧版产物）才读 `meta.sql` 的注释与 `meta` | SQL 注释与任务元信息的后备来源。骨架已含 `task.header_comments`、`task.meta`、`fields[].sql_comments`、`rules[].sql_comments`、`stages[].actions[].sql_comments`——**优先从骨架取**，不要为拿注释去翻原始 SQL |

**治理线索分两档**：`confidence.findings[]` 每条带 `severity`。`warn` 是要人处理的线索
（`alias_position_mismatch`、`nondeterministic_function`、`metadata_conflicts`、`target_binding`），
`info` 是"真但不用处理"的事实（`hardcoded_date_literal`、`partition_literal_mismatch`、
`table_comment_missing`）。**`info` 级的不进正文**，不写进「使用注意」，也不生成 `Q`——
任务实例本来就对应某一天，分区日期写死是设计而不是缺陷。要提它就写进附录 C。

**取数日**取 `task.instance_dates[]`（本实例的日期过滤钉住的那一天或几天，`[]` 表示由变量替换）。
语义卡「口径要点」里写成一句事实：「本实例取数日 20260814（每次运行按实例日期替换，不是 SQL 固定日期）」；
有两天时写「本实例主表取 20260814，另一侧取前 1 日」。**不要**写成「都取这一天的数据」——
那是本次实例的日期，SQL 每次运行取当次实例的日期。
这是**口径**，不是问题。`metric_spec.time_range[].kind` 为 `instance_date` 的条目照此措辞，
不要写成「硬编码日期」。

**指标口径卡**取 `semantic.json` 的 `fields[].metric_spec`，槽位固定：`subject`（统计对象）、
`time_range`（时间范围）、`inclusion`（纳入条件）、`aggregation`（聚合方式与粒度）、`unit`
（单位/类型）、`null_handling`（空值处理）、`refresh`（更新频率），另有可选的
`post_aggregation`（聚合后加工：排名、环比、封顶等）。它只出现在指标类字段上，槽位证不出来时
为 `null`——**照写「未知」，不要补一个合理的值**。骨架版本较旧、`fields[]` 里没有 `metric_spec`
键时降级：自己从 `rules[]`（纳入条件、时间过滤）、`fields[].derivation[]`（聚合函数与粒度）、
`fields[].type` / `target_comment`（单位）、`nullable_by_join` 与 COALESCE（空值）、任务元信息
（更新频率）拼出同样 7 行，并把整张卡标 `[推断]`。

**SQL 注释与任务元信息现在在骨架里**，按路径取：

| 要的东西 | 骨架路径 |
| --- | --- |
| 语句头部注释（任务目的、口径说明、变更史） | `semantic.json` → `task.header_comments[]` |
| 任务元信息（项目、owner、调度周期、调度表达式、description、期望日期） | `task.meta`（`.sql` 输入或无元信息时为 `null`） |
| 某个字段上的注释 | `fields[].sql_comments[]`；该字段自己的别名注释也已追加在 `fields[].summary` 末尾 |
| 某条过滤/连接/CASE 上的注释 | `rules[].sql_comments[]` |
| 某个加工动作上的注释 | `stages[].actions[].sql_comments[]` |
| 指标的更新频率 | `fields[].metric_spec.refresh`（`{cycle, cron, source: "task_meta"}`，无调度时 `null`） |
| 本任务一共有多少注释可用 | `confidence.metadata_coverage.sql_comment_counts` |

**注意 `owner_email` 不在骨架里，也不在任何产物里**——契约按名排除个人联系方式，不要去原始
JSON 里捞它，也不要写进画像。

原始任务 JSON 只在骨架**缺**上面这些键时（旧版产物，或用 `--strip-comments` 跑的）作为后备：
它是喂给 `scope-lineage parse` 的那份输入文件，不是产物目录里的任何一个文件。拿不到它不是缺陷。

注释可能过时、可能与 SQL 不符——它是作者的说法，不是 SQL 事实；与骨架的结构事实冲突时正文写
「注释称 X，实际按 Y 计算」，标 `[待确认]`，并进第三件清单，**任何时候都不得用注释覆盖骨架**。

注释体本身是一段 SQL（`cast(null as string) as x` 这类被作者注释掉的旧写法）时，按「作者留下的
旧写法」处理：写进使用注意，不要当成字段含义。`fields[].sql_comments` 已经过滤掉判得出的这类
条目（契约的 `comments` 里仍保留原文），漏网的按这条自己判。

`semantic.md` 或 `diagnostics.json` 缺失读不了：在生成记录的输入文件校验表里写「未读取/缺失」，
不得假装已校验。`semantic.*` 不存在时先让用户跑 `describe`，不要改用整读 `lineage.json` 兜底。

## 通用写作规则

### 正文不挂来源标签

v1 每句挂 `SQL事实` / `LLM推断` 让语义说明读起来像审计日志。v2 的正文（第一、二、三件）
**不出现任何来源标签**，可信度只用三档极简标记：

| 标记 | 含义 | 何时写 |
| --- | --- | --- |
| `[事实]` | SQL 或元数据里直接写着 | **不写**。正文里没有标记的句子默认就是事实 |
| `[推断]` | 你从结构与命名归纳出来的 | 只标在这类句子的句末 |
| `[待确认]` | 有证据但含义要业务方定义 | 只标在这类句子的句末，并在第三件里有对应 `Q<n>` |

所以正文里实际只会出现 `[推断]` 与 `[待确认]` 两种记号；`[事实]` 这一档只在第二件字段字典的
「可信度」列里作为取值出现。一句话里同时含事实与推断时，拆成两句，只在推断那句标记。
七档来源标签（`SQL事实` / `元数据事实` / `结构推断` / `SQL注释` / `任务元信息` / `LLM推断` /
`待业务确认`）与证据 id 全部搬到生成记录，逐条给出，读者的文档里一个都不留。

### 结构词一律译成人话

骨架的词表是给机器用的。正文出现下列任何原词都算写坏了（生成记录里保留原词以便回查）：

| 骨架词 | 正文说法 |
| --- | --- |
| `enriched_projection` / `filtered_projection` | 以某张主表为准再挂上补充信息 / 从一张表里筛出部分行与列 |
| `aggregated` / `deduplicated` / `union_merge` | 按某几个维度汇总 / 同一对象只留一条 / 几路来源拼成一张表 |
| `driving` / `filter_partner` / `enrich` / `dedup_source` / `aggregate_source` / `union_branch` / `merge_source` / `rowset_only` | 决定输出哪些行的主表 / 既补列又会把连不上的主表行丢掉 / 补充信息用 / 去重后取一条的来源 / 被汇总的明细来源 / 拼接的其中一路 / 更新时的来源 / 只借它的行集 |
| `candidate_key` / `key_confidence=proven` / `proven_unexposed` / `candidate` / `none` | 能唯一标识一行的列 / 确实唯一 / **唯一性依赖的列没写进表，现有列不能唯一标识一行** / 只是候选，是否唯一未证明 / 没有能唯一标识一行的列 |
| `keep_latest_per_group` / `keep_first_per_group` / `rank_within_group` | 每个对象只留最新一条 / 只留最早一条 / 组内排名（不筛第一名） |
| `pick_first_in_group` / `pick_last_in_group` / `adjacent_row_offset` / `running_aggregate` | 取组内第一条的值 / 最后一条的值 / 相邻一行的值 / 累计值 |
| `fan_out_risks[].status=risk` / `nullable_by_join` | 这次关联可能让一行变成多行 / 关联不上时这列为空 |
| `measure` / `event_time` / `conditional_label` / `attribute` / `constant` / `derived` / `partition` | 指标 / 时间 / 按条件打的标签 / 属性 / 固定值 / 算出来的 / 分区列 |

### 硬性要求（一条都不放宽）

1. 不得编造表、字段、规则、下游任务或业务结论。文档里每个表名和列名都必须能在骨架里找到。
2. 只能推断时写「推断」「可能」并标 `[推断]`，不得写成肯定句。
3. 缺中文表名/字段注释时写「未知」，不要把英文名翻译成事实。
4. 风险必须优先来自 `diagnostics.json`，不能只根据 `semantic.json.confidence` 猜；两者不一致时
   在生成记录的「四、自洽性检查」写「存在交叉校验不一致」并分别列出两个来源的值。数警告时取
   `statement_diagnostics[].warnings` 与顶层 `warnings[]` 的并集——顶层常常是空的，照字面把它
   当成「0 条警告」会与骨架的 `confidence.warning_counts` 直接矛盾。
5. 「直接读取物理表」（`stages[].direct_source_tables`）与「上游可追溯到物理表」
   （`upstream_physical_tables`）分开写，不要合并。
6. 骨架的 `结构推断` 不是业务定义。「按 `customer_id` 分组、`event_time` 降序取第 1 行」是结构
   事实；「取客户最新状态」是你的推断，标 `[推断]`。

## 第一件：任务语义卡

固定五个小节，顺序不变，合计 ≤ **基础 600 字 + 每多于 3 张的输入表 40 字，最多 900 字**
（中文字符，不含表格；`600 + 40 × max(0, len(inputs) − 3)`，封顶 900）。输入表越多，「数据从
哪来」与「使用注意」按硬性覆盖要求必须写的句子就越多，一刀切的 600 字会逼着写作方违反覆盖面。
业务语言，短句，不出现结构词。

**这个任务做什么** — 2–4 句。它解决什么业务问题、产出什么、给谁用。来源：`task`、任务元信息与
SQL 头部注释；纯业务归纳的那句标 `[推断]`。

**一行代表什么** — 一句话粒度 + 一句键。粒度来自 `output_shape.grain`（按**逻辑键**计数，一个
GROUP BY 项就是一个键，哪怕它穿透到好几个物理列），键用 `output_shape.candidate_keys`（已是目标
表列名），措辞按 `key_confidence` 分四种：`proven` 写「这几列确实唯一」；`proven_unexposed`
**必须写成一句使用注意**——「唯一性依赖的列没有写进这张表，用现有列去关联会重复」；`candidate`
写「候选，是否唯一未证明 `[待确认]`」；`none` 不声称任何键唯一。分区列单说，不当业务主键。
`grain.basis` 为 `unknown` 时写「无法判定一行代表什么」，不要补一个粒度当事实——但 `grain.candidate` 存在时**照抄它**（`row_source` 是行的来源表、`keys` 是展开前的粒度键加上展开出的列），写成「无法判定；推测一行 = …，因为 <candidate.reason>」并标 `[推断]`，不得把它写成肯定句、也不得自己另编一个；`grain.basis` 为 `single_row` 时写「整张输出一行（全表汇总）」并说明键那句不适用（一行不需要键），带 `pinned` 的粒度键照写业务含义，但要说清它被等值过滤钉死成一个值（通常是数据日期），不是区分行的维度。

**数据从哪来、到哪去** — 每张输入表一句：**是什么、在这里起什么作用**。有
`inputs[].card` 时**优先用它**——那是写这张表的上游任务自己证明的粒度与键（`grain_text`、
`candidate_keys`、`key_confidence`、`refresh`），比表名和注释都硬；`card` 为 `null` 或没传
`--tables` 时才退回 `inputs[].comment` + `role_in_task` 译成人话，并写「上游未知」。**主表按 `task.driving_tables[]` 认**——它是行的来源表，`structural_summary` 的「行来源 …」说的就是它；不要拿「ROOT 直接读取」或第一张出现的表当主表，那常常是挂在主表上的维表。输入表
> 6 张时按作用归成三四组，每组一句并列出表名。下游优先取 `task.downstream_consumers`（谁读本表、
读了哪些列、起什么作用），其次才是任务元信息（下游任务、`description`），两者都拿不到就写
「下游未知」，不要从表名猜。

**口径要点** — 3–6 条，每条一句。**第一条固定是取数日**：`task.instance_dates` 非空时写
「本实例取数日 20260814（每次运行按实例日期替换，不是 SQL 固定日期）」，两天时写
「本实例取数日 20260814；<另一侧> 取前 1 日」（差几天照
`metric_spec.time_range[].mismatch` 那条的措辞写），`[]` 时写「取数日由调度变量替换」。
其余各条：统计的时间口径（当天/T-1/近 N 天）、核心指标的分子分母、更新方式（覆盖写/追加、
调度频率）。有 `metric_spec` 时直接压缩它的 `time_range` 与 `aggregation`；`kind` 为
`instance_date` 的写「实例日期 20260814」，**不要**写成「硬编码」「写死」「应该参数化」，
也**不要**写成「都按这一天取」——日期是本次实例的，不是 SQL 的。

**口径里出现 code 时优先读 `rules[].value_meanings[]`**（WI-2.12，`describe --glossary`
接入后就有）：它是这条规则把列钉住的每个取值与人工确认的含义，`{column_ref, value,
sql_literal, meaning}`。「只保留人工队列（`queue_code = '01'`）」这类句子的出处就在这里——
`meaning.status = "confirmed"` 时直接当事实写（标 `SQL事实`，含义部分的证据写 `rule:0NN`），
`candidate` 写成「…（含义待确认）」，`meaning` 为 `null` 的 code **不要猜**：句子里保留原始取值，
该取值进附录 B 的待填清单。规则解释（第一件的「口径要点」「使用注意」与第三件的问题正文）
一律先看这个键，再退回 `rules[].expression` 自己读。

**使用注意** — `severity = warn` 的治理线索里读者**必须**知道的，每条一句，没有就写「无」。
至少覆盖：`alias_position_mismatch`（列错位，正文只写「这张表的列名与实际写入值可能整体错位，
核对列序前不要按注释解读数值」）、关联不上时为空的字段、UDF 与黑盒表达式、
`trace_complete=false` 的字段。**`severity = info` 的一条都不写进这里**——实例日期、
两侧取不同天、缺表注释都不是使用注意；实例日期与跨天口径属于上面的「口径要点」。

## 第二件：字段字典

一张表覆盖**全部**输出字段，来源 `semantic.json.fields[]`（已按 `target_column_ordinal` 排序），
一个不漏。列固定为七列：

| # | 字段 | 中文名 | 一句含义 | 口径 | 取值含义 | 可信度 |
| --- | --- | --- | --- | --- | --- | --- |

- **中文名**：`target_comment` 原文；没有注释时先看 `fields[].term_meaning`（WI-2.12：语料字典里
  这个列名**已人工确认**的含义，形如 `{text, status: "confirmed"}`，只在没有目标注释时出现）——
  有就照写、**不加 `?`**、按 `[事实]` 处理并在附录 A 列一行「术语」，因为它是人答过的；两者都没有
  才给一个推断名并后缀 `?`（如 `订单金额?`）。`target_comment_source` 为 `patch` 时这个名字来自
  人工确认的回写，同样照写、不加 `?`、不再提问。
- **一句含义**：**是什么，不是怎么算**。「这个客户当天下的订单总金额」是含义，「`SUM(pay_amount)`」不是。`fields[].summary` 是复述，只能作起点，不能直接抄进这一列。
- **口径**：指标字段把 `metric_spec` 压成一行 `对象 · 时间范围 · 纳入条件 · 聚合`（槽位为 `null`
  写「未知」）；非指标字段写来源，形如 `取自 <表>.<列>` 或 `按 <条件> 打标` 或 `固定值 'X'`。
- **取值含义**：枚举值、code、常量的业务含义。**优先读 `fields[].value_domain[]`**（WI-2.4 字典层，
  `describe --glossary` 接入后就有）：每条是 `{value, kind, seen_in, closed_set, meaning}`。
  `meaning.status = "confirmed"` 是人工确认过的事实，直接写；`candidate` 是"某条注释里字面出现了
  这个值"，写成 `值 = 含义?`；没有 `meaning` 的值只写值本身 +「含义待确认」。`value` 是去掉 SQL
  引号的规范形式（`PAID`），`sql_literal` 是作者写的字面量（`'PAID'`）——**展示与举例写
  `sql_literal`，写进 `glossary.overrides.json` 的键用 `value`**（`列=PAID`；带引号的写法同样
  命中，两边都会 `strip_quotes`）。`closed_set` 是**整列**的结论，同一字段的每条取值要么都是
  `true`、要么都是 `null`；为 `true` 时补一句「该列取值已被 SQL 证明封闭」，否则默认还有没见过的
  取值。`value_domain` 只收该列**自己输出**的值（CASE 的 THEN/ELSE、UNION 常量、常量投影）与
  **透传来源列**被 `=`/`IN` 钉住的值；CASE **条件**里比较的常量属于被判断的那一列，不会出现在
  这里。`kind = "pattern"` 的条目
  是 `LIKE` / `RLIKE` 的匹配模式（WI-2.4b），**不是枚举值**：写成「匹配 `'%UNIT_OUT_%'`」，不要
  当成该列取过的值，也不参与封闭判断。`value_domain` 之外，**这个字段的来源列在规则里被钉住的
  code 读 `rules[].value_meanings[]`**（WI-2.12）：仓库的业务码多数只出现在 `WHERE` / 连接附加
  条件 / CASE 条件里，永远到不了 `value_domain`，而那里的 `meaning.status = "confirmed"` 同样是
  人工确认过的事实。没有这两个键时才退回自己从 `rules[].expression` 的 `IN` / `=`、CASE 分支、
  常量投影里读取值集合。
  **不要猜 code 代表什么，也不要为它生成 `Q`**（WI-2.9）：没有含义的取值统一写
  「含义待确认，见附录 B」，答案由 `glossary.overrides.template.md` 收。无枚举的字段写 `—`。
- **可信度**：`事实` / `推断` / `待确认` 三档之一，一个字段一档（取该行最弱的一档）。写 `待确认`
  的字段，若其待确认点属于第三件那四类，必须有对应 `Q<n>`；若只是取值含义未填，则**不生成 `Q`**，
  在附录 B 的待填取值清单里有一行即可。该行的事实里含**已确认回写**（`target_comment_source =
  "patch"`，或取值含义 `meaning.status = "confirmed"`）时写 `事实（已确认）`，并在附录 A
  「已确认项」里列一行。

**超过 40 个字段**时按结构角色拆成多张表，顺序固定：**键 / 时间 / 指标 / 标签 / 属性**（分别对应
`candidate_key` + `partition`、`event_time`、`measure`、`conditional_label`、`attribute` +
`constant` + `derived`）。每张表前一句说明这组字段是什么，表后写「本组 N 个字段」；各组之和必须
等于目标表列数，在生成记录的自检第 6 项核对。**分组不是省略的借口**，仍然一个不漏。名称成系列的字段（`x_9` …
`x_20` 这种）可以合并成一行并在「#」列写区间，但要写清区间覆盖几个字段。

### 指标字段的口径卡

每个 `structural_role = measure`（或 `metric_spec` 非空）的字段，在所属表之后各附一张 7 行卡：

| 槽位 | 值 |
| --- | --- |
| 统计对象 | `metric_spec.subject`｜未知 |
| 时间范围 | `metric_spec.time_range`｜未知 |
| 纳入条件 | `metric_spec.inclusion`｜未知 |
| 聚合方式与粒度 | `metric_spec.aggregation`｜未知 |
| 单位/类型 | `metric_spec.unit`｜未知 |
| 空值处理 | `metric_spec.null_handling`｜未知 |
| 更新频率 | `metric_spec.refresh`｜未知 |

`post_aggregation` 非空时附第 8 行「聚合后加工」。直接转写，不要改写成业务口号；哪一行是你降级
拼出来的，就在那一行末尾标 `[推断]`。同口径的系列字段（只差一个小时数、一个档位）共用一张卡，
写明它覆盖哪些字段。

## 第三件：待确认清单

给业务方逐条答的问题，**≤ 5 条**。上一版的 15 条上限在真实任务上产出了 14 条，owner 的原话是
「太多了，很难处理」——所以这一件现在只问**答错会改变数值或含义**的事，别的都不问。

**只有四类可以进清单**（其余一律不问）：

| # | 类别 | 判定 | 合并方式 |
| --- | --- | --- | --- |
| 1 | 列错位 | `confidence.findings[].kind = alias_position_mismatch` | 整个任务合成一条 |
| 2 | 注释与推导链语义冲突 | 注释称近 30 天而过滤是 `>= 7`；注释称已支付而聚合不带支付条件；注释称最新状态而窗口只做排名 | 一处冲突一条，最多 2 条，多的进附录 B |
| 3 | 关联可能放大且键未证明 | `output_shape.fan_out_risks[].status = risk` 且该侧 `key_confidence` 不是 `proven` | **合成一条**：一次问「这几个关联里，右侧一行对应左侧几行」，并列出涉及哪些关联 |
| 4 | 名不副实字段 | 列名或注释与 `value_domain` 的实际取值、或与 `derivation` 的实际来源明显不符 | 同一类命名合成一条 |

**不再问的事**（问了也答不出增量，或已有别的落点）：

| 旧问题 | 现在怎么办 |
| --- | --- |
| 硬编码日期是否由调度平台替换 | 不问。任务实例对应某一天，写死是设计；日期写在「口径要点」的「本实例取数日」一句里，措辞说明它随实例变化 |
| code / 枚举值 / 常量的业务含义 | 不问。正文写固定一句：「取值含义请填 `glossary.overrides.template.md`，见附录 B 的待填取值清单」 |
| 候选键在业务上是否真的唯一 | 只在该键参与了 `fan_out_risks[].status = risk` 的关联时问，且并进第 3 类那一条 |
| 连接键是否真实外键 | 同上 |
| 「这样是否符合业务期望」「请核对整张表」类 | 不问。它不是一句话能答的问题 |

**超出 5 条的候选进附录 B「备查项」**，一行一条，不用六行格式，也不计入清单。

每条固定六行，最后一行是留给业务方填的空位：

```
Q<n>. <一句问题，业务方不看 SQL 也能懂>
- 证据：<骨架路径或注释原文>
- 候选答案：<A / B / C，或「无候选」>
- 回写目标：字段注释:<表.列> | 术语:<词> | 值域:<列>=<值> | 表注释:<表>
- 影响：<答错会怎样>
- 答案：（待填）
```

`- 证据：` 这一行**豁免「正文不得出现结构词」**：它是写给复核者的指针，写的就是骨架路径
（`candidate_keys`、`key_confidence`、`nullable_by_join`、`value_domain[].closed_set` 这类原词
照写），不要为了躲结构词把它译成人话。自检第 4 项只扫语义卡与字段字典的**正文单元格**，
不扫 `- 证据：` 行。

**「回写目标」必须写成四种形式之一、且只写一种**（`术语:` / `值域:` / `字段注释:` / `表注释:`，
冒号中英文皆可），因为业务方答完之后由 `scripts/confirmations.py apply` 按这一行分流：
`术语` 与 `值域` 进 `glossary.overrides.json`，`字段注释` 与 `表注释` 进 `metadata-patch.json`。
把四种并列写在一行（模板原样）等于没填，脚本会跳过并计数。`- 答案：（待填）` 这一行**必须写出来**，
不写业务方就没有落笔的地方。

### 已确认的项不再提问

骨架里已经带着答案的项**不许再生成 `Q`**——重复问一遍会让业务方觉得上一轮白答了。三处判断：

| 骨架证据 | 含义 | 处理 |
| --- | --- | --- |
| `fields[].value_domain[].meaning.status = "confirmed"` | 这个取值的含义已被人工确认 | 正文直接当事实写，不标 `[待确认]`，不进第三件 |
| `fields[].target_comment_source = "patch"` | 这个字段的目标注释来自确认回写 | 同上；中文名与一句含义直接用它，不加 `?` |
| `inputs[].comment_source = "patch"` | 这张输入表的中文名来自确认回写 | 同上 |

这些项改在**附录 A「已确认项」小表**里列出（值/字段/表、确认后的含义、来源），让复核的人看到
上一轮的答案落在哪儿了。字段字典的「可信度」列相应升档：该行的证据全部是事实或已确认项时写
`事实（已确认）`，它与 `事实` 同档，只是多说明一句这份事实来自人工确认。
`confidence.confirmations`（`{values_confirmed, rule_values_confirmed, terms_confirmed,
columns_patched, tables_patched}`）是这几类已确认项的计数，附录 A 直接转写它。
`rule_values_confirmed`（WI-2.12）是**规则里**被确认的取值数，与字段层的 `values_confirmed`
分开计——同一个 code 写在输出列上和写在 `WHERE` 里，是读者在两个地方各问一次的问题。

来源只扫上面那四类。**不再标「（优先）」**：清单只剩 5 条，条条都是优先，标记不再区分任何东西。
顺序仍按影响排：影响数值正确性 > 影响口径理解 > 影响命名。业务方应能几分钟答完——问题要能用
一句话回答，不要把「请核对整张表」写成一条。

正文里出现 `[待确认]` 但不属于这四类的句子（典型就是没有含义的 code），**不生成 `Q`**：句末照标
`[待确认]`，取值本身进附录 B 的待填取值清单，由 `glossary.overrides.template.md` 统一收答案。

## 自洽性检查（生成后必做）

写完三件之后，逐字段收集它在**语义卡、字段字典、口径卡、待确认清单**里的所有表述，两两比对四
件事：统计对象、时间范围、聚合方式、含义。发现冲突时**只保留一个说法**（保留证据更硬的那个：
SQL 事实 > 元数据注释 > 你的推断），把被丢弃的另一种写成一条 `Q` 条目而不是留在正文里。

在生成记录的「自洽性检查」一节输出一行结论：`自洽性检查：N 字段、0 冲突`；有冲突则逐条列出「字段、两处说法、保留了哪个、
对应 Q 编号」。这一步不能只在心里做，没写出来视为没做。

## 篇幅分档

不再用总字数公式，三件各自设限：

| 件 | 上限 | 超出说明 |
| --- | --- | --- |
| 任务语义卡 | `600 + 40 × max(0, 输入表数 − 3)`，封顶 900 字 | 在写模板或在复述 SQL，删结构细节 |
| 字段字典 | 按字段数：≤ 40 字段一张表；> 40 分组；每字段「一句含义」≤ 30 字 | 含义写成了推导过程 |
| 待确认清单 | 5 条 | 同类没合并，或问了四类之外的事 |
| 附录 A/B/C | 三节合计 ≤ 正文（一、二、三）字数的 1/3 | 把证据、校验、自检写进了读者的文档，搬回 `business_profile.check.md` |
| 生成记录 | 不限 | — |

**小任务**（`fields[]` ≤ 10 且 `stages[]` ≤ 5）：语义卡压到 300 字，字段字典一张表，待确认
清单常见 0–2 条（四类都不成立时写「本轮无需确认」），生成记录的自检表只保留下表前 8 项。章节一件都不能少，压缩的是篇幅不是覆盖面；
硬性要求、`alias_position_mismatch` 单独成段、注释与推导链冲突检查，小任务同样不豁免。

**大任务**（字段 > 40 或阶段 > 12）：语义卡的上限只随**输入表数**放宽，不随字段数或阶段数放宽
——它是给业务方的一页纸，字段多不是把它写长的理由；变大的是字段字典与生成记录；读者文档的附录仍受 1/3 上限约束。

## 附录（读者文档）：A / B / C 三节

读者文档的附录只留读者用得上的三节，**合计字数 ≤ 正文（一、二、三）字数的 1/3**。写多了就是
把质检记录塞给了读者——搬进 `business_profile.check.md`，那里不限长。

**附录 A 已确认项**（有则必须写）：上一轮答完、这一轮已经落进骨架的项，一行一条，不再作为问题出现。

| 类型 | 对象 | 确认后的含义 | 证据 |
| --- | --- | --- | --- |
| 取值 | `<列>='<值>'` | {meaning.text} | `fields[].value_domain[].meaning.status=confirmed` |
| 规则取值 | `<列>='<值>'`（写在哪条规则上） | {meaning.text} | `rules[].value_meanings[].meaning.status=confirmed` |
| 术语 | `<列名>` | {term_meaning.text} | `fields[].term_meaning` / `inputs[].used_columns[].term_meaning` |
| 字段注释 | `<表.列>` | {target_comment} | `fields[].target_comment_source=patch` |
| 表注释 | `<表>` | {inputs[].comment} | `inputs[].comment_source=patch` |

表里只写项，不写计数：`confidence.confirmations` 的计数与取值含义覆盖率都是写作方的数字，
写在生成记录的「来源标签与证据」一节，不占读者附录的篇幅。

**附录 B 备查项与待填取值**（WI-2.9，有则必须写）：第三件装不下的候选与所有没有含义的取值都落在
这里。两段，都不用六行格式：

- **备查项**：一行一条，格式 `- <一句话> —— 证据 <骨架路径>`。它们是真的线索，只是这一轮不占
  业务方的五条额度；下一轮清单空出来时再提上去。
- **待填取值清单**：本任务 `fields[].value_domain[]` **与 `rules[].value_meanings[]`** 里
  `meaning` 为空（或 `status = candidate`）的取值，**按列聚合**，一列一行：
  `- <表.列>：'A'、'B'、'C'（N 个，封闭/未证明封闭）`。两个来源合成一份清单并按
  `(列, 取值)` 去重；只出现在规则里的取值同样要列出来——它们正是最该问的那一批，行末标
  「（出现在 rule:0NN）」，`value_domain` 里也有的不必重复标。表头前写
  一句固定话：「取值含义请填 `glossary.overrides.template.md`，生成命令：
  `scope-lineage glossary --lineage <语料> --out <目录> --template <目录>/glossary.overrides.template.md`」。
  这一段**取代**了旧版逐个 code 提问的那些 `Q`。

**附录 C 风险边界**

| 风险项 | 来源 | 状态 | 说明 |
| --- | --- | --- | --- |
| trace_complete=false 字段 | semantic.json.confidence | | |
| diagnostics warning | diagnostics.json | | |
| metadata 缺失 | confidence / diagnostics | | |
| 结构推断项（形态/粒度/窗口意图/放大风险） | semantic.json | | 非业务定义 |
| SELECT * / JSON / UDF 黑盒 | diagnostics / stages | | |

warning 类型的解读见 `references/diagnostics.md`。这张表只收**真实风险**：`diagnostics.json` 与
`semantic.json.confidence` 的交叉校验是你做过没做过的问题，不是读者的风险，结论写在生成记录的
「四、自洽性检查」。

**附录 C 的「列错位（`alias_position_mismatch`）」子段**（有则必须写，不得混进上表）：它的含义是
「这个任务按 DDL 列位置写入，且 N/M 个投影的 SQL 别名与目标表同位置列名不同」。这是疑似生产事故
级别的发现——要么数据正写进错误的列，要么目标表元数据列序已过期。照实写出 N/M、骨架给的前 3 个
例子（`目标 a ← 别名 b`）与 `evidence[]` 里的 `mapping_chain_id`，给出「请 DESC 目标表核对列序」
的动作建议。不要自己判定是哪一种，也不要因为字段最终有注释就淡化它；正文「使用注意」里必须有
对应的一句，第三件里必须有对应的 `Q`。

## 生成记录 `business_profile.check.md`（写作方的质检，必须写）

正文不挂标签的代价由这个文件承担：这里要能让复核的人把正文每一句追回契约 id。**它与
`business_profile.md` 同目录、同时生成，允许长**，也不计入读者附录的 1/3 上限。空白骨架见
`references/business-profile-check-template.md`。五节，顺序固定。

**一、输入文件校验**

| 文件 | 是否读取 | 用途 | 关键校验结果 |
| --- | --- | --- | --- |
| semantic.md | 是/否 | 事实骨架 | 字段数 / 阶段数 / 规则数 |
| semantic.json | 是/否/定向取 | 结构化字段 | 取了哪些路径；`metric_spec` 是否存在；`sql_comment_counts` 三个计数 |
| diagnostics.json | 是/否 | warning、断链、风险 | `analysis_status`、警告条数 |
| mapping.md | 是/否/未必要 | 技术细节补充 | |
| lineage.json | 是/否/未必要 | query.py 定向取 | 取了哪些字段 |
| 原始任务 JSON | 是/否/未必要 | 仅在骨架缺注释键时作后备 | 为何需要后备（骨架缺哪个键） |

**二、来源标签与证据**

正文的每一条关键结论在这里落一行，七档标签逐条给证据 id：

| 标签 | 含义 | 正文位置 | 证据 id |
| --- | --- | --- | --- |
| `SQL事实` | SQL 原文：条件、表达式、连接键、分组键、窗口定义 | 语义卡「口径要点」第 2 条 | `logic:…` |
| `元数据事实` | 表/字段注释、类型、分区列 | 字段字典「中文名」列 | 表名/列名 |
| `结构推断` | 骨架从结构证明的结论：形态、粒度、候选键、窗口意图、放大风险、结构角色 | 语义卡「一行代表什么」 | `scope_id` / `mc:…` |
| `SQL注释` | SQL 作者写在语句里的话（骨架已携带） | 语义卡「这个任务做什么」 | `task.header_comments[i]` / `fields[].sql_comments` / `rules[].sql_comments`；骨架缺键时才写「原始 SQL 第 N 行」 |
| `任务元信息` | 调度侧登记的 owner、周期、description、上下游 | 语义卡「到哪去」 | `task.meta.<键>` / `task_dependencies`；骨架缺键时才写原始 `meta` 键名 |
| `LLM推断` | 你的业务归纳（业务实体、表类型、模块名、业务目标） | 正文所有 `[推断]` 句 | — |
| `待业务确认` | 有证据但含义需业务方定义 | 正文所有 `[待确认]` 句 | 对应 `Q<n>` |

这一节末尾写两行数字。第一行直接转写 `confidence.confirmations`：
`已确认：字段取值 N1、规则取值 N2、术语 N3、字段注释 N4、表注释 N5`。第二行是取值含义覆盖率，按
`confidence.metadata_coverage.glossary`：
`已确认 confirmed / values_total`——其中 `values_total` 是**字段取值 ∪ 规则引用取值**去重后的
总数（按列名与取值归一，同一个 code 在 `WHERE` 与同名输出列上只算一次），`rule_values_*` /
`field_values_*` 是它的两半。

映射规则不变：骨架已标的三档**原样保留不升不降**；`SQL注释` / `任务元信息` 必须能引到原文（优先引骨架路径）；
业务实体、业务表类型（宽表/名单表/指标表/明细表/标签表/维表）、模块名、业务目标一律 `LLM推断`；
code 含义、外键真实性、候选键业务唯一性、常量集合是否完整枚举一律 `待业务确认`——但**标了
`待业务确认` 不等于要生成 `Q`**，第三件只收那四类，其余在附录 B 里备查。

**三、结构推断项**：转写 `confidence.inferred_items`（它是**按路径模式聚合的计数**，如
`{"fields[].structural_role": 52}`，按类写数量即可），再列出你自己加的 `LLM推断` 与
`待业务确认` 条数。

**四、自洽性检查**：见上一节的做法，一行结论或冲突清单。同一节里再写一行交叉校验结论——
`diagnostics.json` 与 `semantic.json.confidence` 一致与否；不一致时分别列出两个来源的值。它是
「你核对过了吗」的答案，读者的附录 C 只收真实风险，不收这一行。

**五、生成自检**（必须写出来，不能只在心里检查）。它检查的仍然是 `business_profile.md` 的正文，
只是记录写在这里：

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 1. 实际读取 semantic.md | ✅/⚠️/❌ | |
| 2. 实际读取 diagnostics.json，警告数按语句级与顶层的并集数（不是只看顶层 `warnings[]`） | | |
| 3. semantic.json 按路径定向取，未整读 lineage.json | | |
| 4. 语义卡 ≤ `600 + 40 ×（输入表数 − 3）`（封顶 900），且正文单元格未出现任何结构词与来源标签（只扫语义卡与字段字典的正文单元格，第三件的 `- 证据：` 行豁免） | | |
| 5. 语义卡只在推断与待确认的句子上标了记号，事实句无记号 | | |
| 6. 字段字典覆盖全部输出字段（N/M 核对） | | |
| 7. 每个指标字段都有 7 行口径卡；`metric_spec` 缺失时的降级已标 `[推断]` | | |
| 8. 「一行代表什么」按 `key_confidence` 正确措辞，`proven_unexposed` 进了使用注意 | | |
| 9. 区分了「直接读取物理表」与「上游可追溯」 | | |
| 10. 逐字段核对了目标注释与 `derivation[]` 是否语义冲突，冲突的进了清单 | | |
| 11. `alias_position_mismatch`（若有）在附录 C 单独成段，写了 N/M、例子与核对动作 | | |
| 12. 待确认清单 **≤ 5 条且只在四类之内**（列错位 / 注释与推导链冲突 / fan_out=risk 且键未证明 / 名不副实字段），六行格式齐全（含 `- 答案：（待填）`） | | |
| 12a. 每条的「回写目标」只写了四种形式中的一种，没留模板的四选一 | | |
| 12b. 已确认项（confirmed / patch）没有再生成 Q，且都进了附录 A | | |
| 12c. `severity = info` 的 findings（实例日期、两侧取不同天、缺表注释）**没有进正文**，也没有生成 Q | | |
| 12d. 超出 5 条的候选与所有没有含义的取值（含只出现在 `rules[].value_meanings[]` 里的）都进了附录 B，正文里写了那句「取值含义请填 `glossary.overrides.template.md`」 | | |
| 13. 自洽性检查已执行并写出结论 | | |
| 14. 没有编造骨架中不存在的表、字段、规则 | | |

表末再写一行占比核对：`附录占比：附录 A+B+C N 字 / 正文 M 字 = 比例`，**须 ≤ 1/3**；超了就把
证据、校验、自检类的文字搬回本文件，不要靠删正文来达标。
