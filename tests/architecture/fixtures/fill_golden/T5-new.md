你负责本体目录起草的第 2 步：在目录里补齐**概念、标识符、已有标识符的新拼写、关系、跨组属性和跨组共用的码值集**，
并写出分组方案。后面每组会各派一个子代理写片段；片段不能新增概念、不能改已有标识符，所以这些都要你在这一步写好。
独立完成，不许派子代理。

**已知**

- 运行目录：`/RUN`；每条 Bash 命令都以 `. /RUN/env.sh && ` 开头。
- 本轮的表：`/RUN/tables.txt`（一行一张）。
- 小样还是扩表：小样：只分 1 组，组名 main
- 模式：新建（新建：目录里没有本轮的表；增量：本轮的表是重写后接回已有目录的，旧目录里这些表的表现已经去掉）
- owner 已拍板的决定（编排者从 `/RUN/owner_decisions.md` 原样贴来；写「无」就是没有。用法见下面「写什么」第 8 条）：

```text
无
```

- 读长文件：任何文件一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完。
- 写入被拦截：Write 写 `/RUN` 下的文件被钩子拦截时，先写 `/SCRATCH/catalog-draft/` 下同名文件，再用 Bash `cp` 拷过去（已获调用方授权）；
  `cp` 也被拒绝就在回复里写明文件在哪，调用方会代拷。

**只读这些**

1. 起草材料 `/RUN/digest/digest.md`（结构化的同一份是 `digest.json`）：这是起草概念的**全部输入**。只在你要用的某个
   digest 字段**缺失**时（例如某列没有 meaning、某张表没有 Rules、某列没有码值而你要写 `states`），才读那张表文档
   `/RUN/docs/<表>.json` 里对应的那个字段；读了就在用到它的条目 `notes` 里写明「digest 缺 <表>.<字段>，取自表语义」。
   digest 里有、只是你觉得写得不够细的，不算缺失，不读文档；不要通读整份表语义。
2. 当前目录（起点）`/RUN/catalog/`：全部文件都读，先弄清已有的概念、标识符、关系和码值集。
3. 形状参考（只看形状，不抄内容）：`/SKILL/references/catalog-demo/` 里的 `identifiers.yaml`、`relations.yaml`、
   `code_sets.yaml`、`concepts/lending.yaml`。
4. 规则说不清时才查 `/SKILL/references/catalog-elements.md`（本体目录文档的「元素」一节）。

**增量模式**（新建模式跳过这一节，下面的清单写「无」）：下面是旧目录里提到本轮表的条目（文件、id、提到的表）：

```text
无
```

只核对其中的**标识符和概念**：标识符的 `scope`（照下面第 3 条「最窄范围」重写）、`name`；概念的 `definition`、`kind`。
digest 的说法与它矛盾的，就地改这一条，`status` 保持 `drafted`；每一处改动在 `/RUN/catalog_changes.md` 记一行（文件、id、改前、改后、
依据：digest 哪张表哪一段），没有改动就写一行「无改动」。属性只在 digest 明说矛盾时才改（同样记一行）。不删任何条目（别的表可能还在
用它）；不改清单以外的条目；没有矛盾就不动。片段会复用这些属性，所以属性要在这一步就改对，片段里不能用同一个 id 写别的内容。
之后照常做下面「写什么」的各条，补齐本轮表新带来的概念、标识符和拼写。

**不许读**：任何题集或判分文件；任何别的运行目录；`/RUN/reviews/`。不要上网。不改 `/RUN/docs/` 和 `/RUN/packets/`。

**写什么**（直接改 `/RUN/catalog/` 里的文件；目录是 JSON 的就写 JSON，是 YAML 的就写 YAML，新建的文件与 `catalog.*` 同格式。
文件名只能是 `catalog`、`domains`、`identifiers`、`code_sets`、`concepts/<域>`、`relations`、`constraints`、`metrics`、`terms`，别的文件会报 `unknown_file`；
`mapping/` 不归你写）

每个文件是一个对象，唯一的顶层键与文件名主干相同，值是条目列表（`catalog.json` 是清单，不改）：

```json
{"domains": [ … ]}            // domains.json
{"identifiers": [ … ]}        // identifiers.json
{"code_sets": [ … ]}          // code_sets.json
{"concepts": [ … ]}           // concepts/<域>.json，例如 concepts/lending.json
{"relations": [ … ]}          // relations.json
{"constraints": [ … ]}        // constraints.json（下面「义务清单」b）
{"metrics": [ … ]}            // metrics.json（下面「义务清单」c）
```

（上面的 `//` 只是说明，文件里不能写注释。）

1. **业务域**：每个概念要有 `domain`。没有合适的域就建一个：`{"id": "domain:<slug>", "name": "中文名", "description": "一句话"}`。
2. **概念**：读 digest 每张表一段的 What / Row / Grain，判断这张表的一行是哪个业务对象。
   - 目录里已有概念能承载的，不新建。一个业务含义一个概念；同一对象的不同表（宽表、历史表、映射表）是同一个概念的不同表现，不是几个概念。
   - **每个新建的概念都在 `notes` 里写理由**：哪张表的一行就是它，或哪张表的哪一列指向它、为什么已有概念承载不了。
   - 只存「码 + 含义」、按类型列区分多套码的字典表**不是概念**，不建；它在分组方案里列为「码值来源表」。
   - `kind` 只有三种：`entity`（有稳定身份、能被反复引用）；`event`（在某个时点发生、有参与者、发生后不改）；
     `role`（实体在某个业务上下文里的身份，写 `player`、`context`、`condition`）。
   - 各类型必填 / 禁写的键（目录 schema 强制，写错 `catalog validate` 报 `schema`）：

     | kind | 必须写 | 不能写 |
     | --- | --- | --- |
     | `entity` | `identifiers`、`primary_identifier` | `occurred_at`、`participants`、`player`、`context`、`condition` |
     | `event` | `occurred_at`、`participants`（**至少一个**） | `primary_identifier`、`states`、`player`、`context`、`condition` |
     | `role` | `player`、`context`、`condition` | `identifiers`、`primary_identifier`、`states`、`occurred_at`、`participants` |

     所有概念都必须有 `id`、`kind`、`name`、`domain`；每个属性必须有 `id`、`name`、`definition`、`category`、`type`。
   - `event` 的 `occurred_at` **必须指向事件自己的时间属性**，所以同时在 `attributes` 里建这个属性（`category: time`）。
     `participants` 每项是 `{"role_name": <小写英文 slug，同一事件里不重复>, "concept": <entity 或 role>, "cardinality": "one" 或 "many"}`。
   - 事件的参与者按这个顺序定，第一条成立就停：
     1. 目录里已有、或本步因别的表新建的 entity / role 能当参与者：引用它。**事件表里每一个指向这类概念的外部标识列，
        都把那个概念列为参与者**（一列一个 `role_name`）；确实不该列的，在事件的 `notes` 写明哪一列、为什么不列。
     2. 都没有：只为**事件发生在谁身上**的那一个对象（例如被联系的客户、被处理的账户；表里要有指向它的标识列）新建一个最小的
        entity（`identifiers` 与 `primary_identifier` 用那一列建的标识符，`notes` 写理由并加「待 owner 确认：是否另建概念」），
        引用它当唯一的参与者。其余只凭外键列出现的对象（操作人、机器人、任务之类）不建概念，在事件的 `notes` 里写
        「待 owner 确认：<列> 指向的 <对象> 是否建概念」。
     3. 连这样的对象也找不到：这张表的概念按 `entity` 建（不是 `event`），时间列建成普通 `time` 属性，`notes` 写
        「待 owner 确认：本是事件，缺可引用的参与者，暂按 entity 建」，并在回复「没把握」里列出。
     **不要**写空的 `participants: []`，也不要省略它——`event` 至少要有一个参与者，否则 `catalog validate` 报错。
   - 每个概念写 `name`（中文）、`definition`（一句话）、`status: drafted`、`source`（`comment` / `sql` / `mixed` / `llm`）、
     `evidence`（表名或 `库.表.列`）。
   - 本轮没有自己的表的概念（只因别的表有指向它的外部标识列、或 owner 决定要建而建的），本轮也没有属于它的名称、描述列时，
     它会没有任何属性：在 `/RUN/catalog_changes.md` 写一行 `<概念 id> empty skip: <理由>`（例如「本批没有它的表，只作参与者 /
     关系一端」），S10g 的漏做检查读它。有名称、描述列的，按第 5 条在它上面建属性，不写这一行。
   - 形状：

     ```json
     {"id": "concept:repayment", "kind": "event", "name": "还款", "definition": "客户按借据还钱。",
      "domain": "domain:lending", "identifiers": ["id:repayment_txn_no"],
      "occurred_at": "attr:repayment.repaid_at",
      "participants": [{"role_name": "payer", "concept": "concept:customer", "cardinality": "one"},
                       {"role_name": "loan", "concept": "concept:loan", "cardinality": "many"}],
      "attributes": [{"id": "attr:repayment.repaid_at", "name": "还款时间", "definition": "收到还款的时间。",
                      "category": "time", "type": "timestamp"}],
      "status": "drafted", "source": "mixed", "evidence": ["demo_dwd.dwd_lending_repayment_di"]}
     ```

3. **标识符**：新概念的标识符；已有标识符在新表里的新拼写（在 `spellings` 里加 `{"column": "<列>", "table": "<库.表>"}`；
   列名到处都一样的写 `{"column": "<列>"}` 即可）。
   - `scope` 写**表语义能证明的最窄范围**，不要比表语义页说得更强：
     - 表语义（digest 的 Grain / Watch）说它全局唯一，才写 `"global"`；
     - 只在另一个概念的每个实例内唯一：写 `{"per": ["concept:<id>"]}`；
     - 只证明了在某个判别列（来源系统、环境这类不是业务概念的列）的每个取值内唯一，跨这一列是否唯一没有证明：写
       `{"by": [{"column": "<列>"}]}`，并在 `notes` 写「待 owner 确认：跨 <列> 是否唯一」。**不要写 `global`**，否则目录页会写成「全局唯一」，与表语义页的「未证明」矛盾；
     - 什么范围都证明不了：写 `"global"`，`notes` 写「待 owner 确认：唯一性未证明（见表语义 <表>）」，并在回复「没把握」里列出。
   - 两套编号没有证据证明是同一套（例如两个系统各自的人员编号），不写 `maps_to`，也不建它们之间的关系，在 `notes` 里写明。
   - 一个概念可以有几个标识符：同一张表里有两列都标识同一个对象（例如注册即有的编号和后来才有的编号），各建一个标识符，都列进
     这个概念的 `identifiers`，`primary_identifier` 选表语义 Grain 用的那一列，两者之间的对应写进 `maps_to`（有证据时）或 `notes`。
     digest 把一个编码列（`_cd`、`_id`）列在 Descriptive 下、而它旁边有同对象的名称列时，照编码列处理（标识符或外部标识符），
     不按描述列处理。
   - 形状：`{"id": "id:loan_no", "name": "借据号", "identifies": "concept:loan", "scope": "global", "spellings": [{"column": "loan_no"}], "status": "drafted", "source": "sql"}`
4. **关系**：新概念与已有概念之间的业务联系（参与关系由事件的 `participants` 自动派生，不手写）。
   - 每条关系都写 `definition`：一句话说两端在业务上是什么联系、凭哪张表哪一列连上（例如「一份借据属于一个客户：借据表的客户号指向客户」）。
   - `name` / `inverse_name` **只写动词短语**，不带另一端的概念：页面读成「<name> <另一端概念名>」。写 `"name": "持有"`、
     `"inverse_name": "持有人为"`，不写 `"name": "持有借据"`。
   - `cardinality` 两端各取 `"1"`、`"0..1"`、`"0..*"`、`"1..*"`，按 digest 的粒度与关联判断，拿不准写宽的一侧并在 `notes` 说明。
   - 一个概念有几条自关联（隔不同层数的同类实例，例如上级、上上级）：每条单独一个关系；同一张表按分区日自关联时，
     在关系的 `notes` 写清按哪一天对齐。
   - 形状：`{"id": "rel:loan_renews_loan", "kind": "association", "from": "concept:loan", "to": "concept:loan", "name": "续借", "inverse_name": "被续借为", "cardinality": {"from": "0..1", "to": "0..1"}, "definition": "一笔借据可以续借出另一笔借据：借据表的原借据号指向被续借的借据。", "status": "drafted", "source": "sql", "evidence": ["demo_dwd.dwd_lending_loan_df.orig_loan_no"]}`
5. **跨组属性**（也管同组）：表里有指向**另一个概念**的外部标识列，旁边有这个对象的名称、描述或属性列（如 `xx_id` + `xx_name`、
   `xx_cd` + `xx_desc`）时，不论那个概念和这张表同组还是别组，现在就在**那个概念**的 `attributes` 里建这个属性，片段才能把那一列绑成
   `foreign_attribute`。分工别写反：**编码列**（`xx_id`、`xx_cd`）绑 `foreign_identifier`；**名称、描述列**才绑 `foreign_attribute`，
   它的 `via` 必须是同表里那个已绑 `foreign_identifier` 的编码列。表里只有编码列、没有名称列时，分组方案只写 `foreign_identifier`。那个概念在别组时，再在分组方案「跨组属性」表里登记「属性 id → 引用它的组」。只有一组的小样也照做。
6. **跨组共用的码值集**：只看 digest 列下「Joined inputs read (from the lineage)」那一行。
   - 为每个**有列读取**的「码表 + 常量条件」组合建一个码值集：`lookups` 里出现的，或 `key_of` 里 `read_by` 不为空的。
     写 `read by no column`（`read_by` 为空）的是死关联或只用来过滤行，不建码值集，记进分组方案的说明。
   - 只建**两个及以上组**都会用到的；只有一组用到的留给那一组的片段写。目录里已有同样 `lookup` 的直接复用，不重建。
   - `lookup.table` 是码表 `库.表`；`lookup.filter` 就是 `where`，**键和值原样照抄，大小写不改**；`lookup.code_column` 是
     `key`（码表一侧的关联列）；`meaning_columns` 是 `reads` 读的含义列（加 `lang`，中文写 `zh`）；`reads` 读的是代理键列时
     写 `key_column`。`values` 写 `[]`。
   - 带 `keyed_by: "row_identifier"`（md 写 `keyed by this table's row identifier`）的读取读的是同一条记录的属性行，不是码值翻译：
     不建码值集。带 `code_set_mismatch`（md 写 `reverse lookup?`）的是按含义反查回码，不建码值集。
   - SQL 内联的字典（`VALUES`、`CASE` 映射）不在这一行里，留给片段写 `values`。
   - 形状：`{"id": "code:waiver_reason", "name": "豁免原因", "values": [], "lookup": {"table": "demo_dim.dim_code_dict", "code_column": "code_val", "meaning_columns": [{"column": "code_desc", "lang": "zh"}], "filter": {"code_type": "WaiverReason"}}, "status": "drafted", "source": "sql", "evidence": ["<任务名>"]}`
7. 不写表现和绑定（`mapping/`），不写人名、邮箱。
8. 每个对象（概念、属性、标识符、关系、码值集、约束、指标）的 `notes` 是**一段文字（字符串），不是列表**：几件事写在同一段里，用分号隔开。
   写给 owner 的内容都以「待 owner 确认：」开头。只有上面「owner 已拍板的决定」里写明的决定，才能写 `status: confirmed`、
   `source: owner`，`notes` 写「依据 owner 决定：…」，并把这条决定推到底（例如「某列就是某编号」，那张表的事件就要把它指向的概念列为参与者）。
   其余一律 `drafted`；不要自己写「owner 确认：…」。

**义务清单**（从 digest 逐条派生，每一条都要有落点，不能因为「拿不准」跳过；拿不准就照写并在 `notes` 写「待 owner 确认：…」。
做完在回复里逐项报数）

a. **状态**：digest 里 `category` 是 `state`、列下列出了码值的每一列：在它描述的 entity 概念上建这个状态属性（`category: state`，
   有共用码值集就写 `code_set`；片段会复用它）。`states` 是**一个对象，不是列表**，每个 entity 至多一个：从这些状态属性里挑描述
   这个对象生命周期的那一个（「状态」「阶段」一类），写
   `"states": {"attribute": "<属性 id>", "values": [{"value": "<码>", "name": "<含义>"}, …], "transitions": []}`，取值照 digest
   原样抄，不补 digest 没有的码。结果、标志、类型一类的状态列只建属性和码值集，不写 `states`；一个 entity 的状态列都不是生命周期
   状态时，在 `/RUN/catalog_changes.md` 写一行 `<概念 id> states skip: <理由>`（S10g 的漏做检查读它）。在回复里列出你挑了哪一列、
   哪些列没写及理由。
   digest 写明了某个事件把状态从一个值改成另一个值时，才写 `transitions`（`{"event": "<事件概念 id>", "from": …, "to": …}`）。
   `event`、`role` 概念不能写 `states`：状态列在事件表上时，写在事件发生在其身上的那个 entity 上；找不到这样的 entity，
   在回复「没把握」里列出这一列。
b. **规则 → 约束**：digest 每张表 Rules 里 `kind` 是 `filter`、`dedup`、`derive` 的每一条（记作 `<库.表>#rN`），二选一：
   - 在 `constraints` 文件写一条约束：`id` 用 `cons:<slug>`；`kind` 按含义选（去重 → `unique`，过滤 → `business_rule` 或
     `value_domain`，派生 → `derivation`）；`on` 写它约束的概念、属性或标识符；`expression` 用一句业务话写清规则；
     `strength` 写 `soft`（材料证明强制时才写 `hard`）；`rules: ["<库.表>#rN"]` 指回规则（同一条业务规则在几张表里出现，
     一条约束列出全部编号）；规则能写成单列比较时加 `predicate: {"column": "<列>", "op": "<= / = / in …>", "value": …}`。
     形状：`{"id": "cons:loan_latest_version", "kind": "unique", "on": "concept:loan", "expression": "同一借据号只保留最新一版。",
     "strength": "soft", "rules": ["demo_dwd.dwd_lending_loan_df#r2"], "status": "drafted", "source": "sql",
     "evidence": ["demo_dwd.dwd_lending_loan_df"]}`
   - 或在 `/RUN/catalog_changes.md` 写一行 `<库.表>#rN skip: <理由>`（例如「只限定读哪个分区，不是业务约束」「技术性去重，
     不改变业务含义」）。
   漏一条，S10g 的漏做检查就报 `unabsorbed_rule`。
c. **度量**：你建的每个 `category: measure` 属性都写 `unit`（金额写币种单位、计数写「个 / 次」等，digest 没写单位就写
   `notes`「待 owner 确认：单位」并按列注释暂填）和 `additivity`（`additive` 可跨任意维度相加；`semi_additive` 不能跨时间相加，
   例如余额、快照计数；`non_additive` 不能相加，例如比率、单价）。digest 里表现类型像汇总表（Row 是「每 X 每天一行的汇总」、
   Rules 有聚合）或列的派生是 sum / count / avg 时，为每个这样的度量在 `metrics` 文件写一条指标：
   `{"id": "metric:<slug>", "name": "中文名", "on": "concept:<id>", "aggregation": "sum / count / count_distinct / avg / min / max / ratio / other",
   "measure": "attr:<id>", "definition": "一句话口径", "filter": "<口径里的过滤，没有就省略>", "constraints": ["cons:<id>", …],
   "time_window": "<按日 / 累计等>", "dimensions": ["attr:<id>" 或 "concept:<id>", …], "additivity": "…", "unit": "…",
   "status": "drafted", "source": "sql", "evidence": ["<库.表>.<列>"]}`。逐键这样定：
   - `on` 是表的一行所对应的概念；`aggregation` 是**跨行**怎么汇总（加总、计数……）。列的派生里的 sum / count 是这张表在写入时
     已经做过的行内汇总（例如把一行之下的多条明细加成一个数），它说明这一列是度量，不决定 `aggregation`；可加的度量跨行一般是 `sum`。
     `additivity` 也按跨行判断。
   - `measure`：`sum`、`avg`、`min`、`max` 必须写，指向 `on` 概念上的度量属性。这个属性**由你在这一步建好**（带 `unit`、`additivity`），
     片段再把列绑上去；不要留空等片段补。只数实例个数的 `count` / `count_distinct` 不写 `measure`。
   - `dimensions`：业务会按什么拆开看这个数。`on` 自己的属性写 `attr:` id（例如发生时间、状态）；按另一个对象拆（例如按事件的
     参与者、按关系另一端的概念）写那个概念的 `concept:` id——它必须是 `on` 事件的参与者，或与 `on` 之间有一条关系，否则
     `catalog validate` 报 `metric_dimension`。不要为了能拆而把外部标识列建成 `on` 的属性。
   - `constraints`：本步写的约束里，限定「哪些实例计入」的（这张表的过滤、去重规则承接成的约束）列在这里；`filter` 用一句话
     重复口径。只限定这次运行读哪个分区、哪个批次日的规则说的是装载窗口，不是口径，不列（时间范围写进 `time_window`）。
     表由几条语句从不同来源写入、各自的过滤不同时，`filter` 按来源分开写（「来源 A：…；来源 B：…」）。没有就写 `[]`。
   - `unit`、`additivity` 与 `measure` 指向的属性一致；`count` 的单位写「个 / 次」一类。
d. **关系**：每条关系都有 `definition`（见上面第 4 条）。
e. **拉链表**：时间语义是 `zipper` 的表，在分组方案的「说明」里写出它的有效期开始列和结束列，片段会把它们绑成
   `time_role: valid_from` / `valid_to`。

**自检**（改到 0 error 为止）

```bash
. /RUN/env.sh && sl catalog validate "$RUN/catalog"; echo "exit=$?"
```

通过 = `exit=0` 且 `0 error(s)`。`drafted_ratio` 警告是正常的。`catalog validate` 的 warning 里有 `state_attribute_without_states`、
`measure_without_unit`、`relation_without_definition` 的，回到上面义务清单 a / c / d 补上。

**分组方案**：写 `/RUN/catalog_plan.md`，照下面的格式。每张表只进一组；表格的每一行都写成 `| <库.表> | … |`（表名两边各一个空格），
编排者用它核对覆盖。小样只写一组；扩表时按概念分组，每组的表不超过十张左右。

```markdown
# 片段分组方案

起点目录：<catalog validate 计数行原样>

## 通用约定（各组都适用）

- 片段不新增概念、不改已有标识符；确实缺的写进 notes。
- <本轮特有的约定：哪些编号体系不能互相关联、哪个概念的属性只由哪一组新增、事件参与者怎么选 relation 等>

## 码值来源表（不进任何组，只写码值集的 lookup）

| 表 | 说明 |
| --- | --- |
| <库.表> | <它装哪几类码> |

## 组 <组名>

本组概念：`concept:<id>`、…

| 表 | 概念 | 表现类型 | 粒度标识符 | 时间语义 |
| --- | --- | --- | --- | --- |
| <库.表> | concept:<id> | core | id:<a> + id:<b>（extra: <不是标识符的粒度列>） | snapshot |

说明：<本组特殊的列、码值、自关联、按来源分支的写法>

## 跨组属性

| 属性 id | 所属概念 | 引用它的组 | 列 |
| --- | --- | --- | --- |

## 已建在目录里的共用码值集

| 码值集 id | lookup.table | filter | 用到它的组 |
| --- | --- | --- | --- |
```

表现类型只能是 `core` / `extension` / `dependent` / `event_detail` / `state_history` / `identifier_map` / `role_view` /
`summary` / `intermediate`；时间语义只能是 `snapshot` / `incremental` / `zipper` / `unknown`，按 digest 的 Time 一行定。
组名用小写英文、数字、`_`、`-`。

**返工**：无

（返工时以上面贴的这次报错为准；改完重跑 `catalog validate`，以**最新一次**输出为准——文件改过之后，同一个问题的报错文字
可能变，例如「'participants' is a required property」改完一半后会变成「[] should be non-empty」。）

**回复**（中文，只写这些行）

```text
新增：域 <n>、概念 <n>（entity <n> / event <n> / role <n>）、标识符 <n>、新拼写 <n>、关系 <n>、跨组属性 <n>、共用码值集 <n>
catalog validate：exit=<n>；<计数行原样>
分组：组名 → 表数（逐组一行）
码值来源表：…（没有写「无」）
没把握、需要 owner 判断的：…（没有写「无」）
增量模式改动：<n> 处（标识符 <n> / 概念 <n> / 属性 <n>）；新建模式写「不适用」
义务清单：a 状态属性 <n>、写了 states <n>；b 规则（filter / dedup / derive）共 <n> 条 = 约束承接 <n> + skip <n>；c 度量 <n>（有 unit <n>、有 additivity <n>）、指标 <n>（有 measure <n>、有 dimensions <n>、有 constraints <n>）；d 关系 <n>（有 definition <n>）；e 拉链表 <n>
工具 / 文档问题：每条一句（没有写「无」）
```
