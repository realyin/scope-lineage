# 把概念层的候选变成业务方认得出的概念

读 `ontology.md` 的「本体总览」与「概念」两部分之后用这份提示词。它和 `ontology-review-prompt.md` 是同一份
语料的两轮：那一轮问的是**表**（这张表按这组列唯一吗、这条边是几对几），这一轮问的是
**概念**（这是一件什么东西、它叫什么、这两个是不是同一个）。表那一轮答完不会让概念层变准，
概念这一轮答完也不会让键变准——两轮互不替代，先跑哪一轮都行。

证据纪律与那一轮完全一致：凭证据自答必须写 `basis`，`confirmed_by` 写 `agent:<名字>`
不冒充人，去问人一次最多 **8 条**，凭证据自答**不限条数**。

**产出两份文件，缺一不可**：

| 文件 | 内容 | 谁读 |
| --- | --- | --- |
| `concepts.overrides.json` | Agent 凭证据自答的条目，以及业务方答完之后合并进来的条目 | `ontology --concept-overrides` |
| `open-questions.md` | 去问人的那 ≤ 8 条，每条五行加一行留白；超出的进末尾「备查项」，一行一条 | 业务方 |

业务方在 `open-questions.md` 的 `- 答案：` 行上落笔，答案按回写目标合并进
`concepts.overrides.json`（`doc_format: "concept-overrides/1"`），再跑：

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --concept-overrides <dir>/concepts.overrides.json
```

## 分批工作

语料一宽，临时概念就是几十上百个，而一轮只许问人 8 条。**别在一个文件里从头做到尾**：
先把它们切成批，一次做一批。

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --review-batches <review> --review-batches-by family --review-batch-size 30
```

这会在 `<review>/batches/` 下写三种文件：

| 文件 | 内容 | 怎么用 |
| --- | --- | --- |
| `index.md` | 批次清单：顺序、概念数、分组、关系条数、待判定分组数 | **从上往下做**。越靠前的批次，答案解开的边越多 |
| `batch-NN.md` | 这一批的工作表：概念表（名字、种类、类别依据、疑似重复、表、已是成员、关系、命名候选、回写键）、候选归并目标（按匹配分：名字 3 / 共同键词根 2 / 关系 1，通用词根不算，0 分不列）、判断依据（表注释与键列注释；两样都没有时给「属性线索」——这张表带注释的前 8 个列）、本批的待判定分组 | 这是**这一批的工作台**，代替「概念」表通读一遍 |
| `batch-NN.overrides.json` | 骨架：这一批每个临时概念一条 `merge_into: ""`，加一段 `comments`（本批的待判定分组） | 就地填答案，填不了的整条删掉 |

`--review-batches-by` 三种切法，按语料的元数据挑一种：

| 取值 | 怎么分 | 什么时候用 |
| --- | --- | --- |
| `family`（默认） | 按表族（`table_family`）分组，再按 `--review-batch-size` 装箱，**同一族绝不拆开** | 一张逻辑表被写成 `_di` / `_df` / `_tmp` 好几份——它们是同一个问题，分到两批就是问两遍 |
| `domain` | 按表的 `naming_hints.domain`，没有就退到 `project`，再没有就进「未标注领域」一组 | 元数据标了域，而每个域背后是不同的业务方——一批正好对应一个人 |
| `size` | 不分组，按影响（概念身上的关系条数）从大到小平铺切块 | 元数据两样都没说 |

一族或一个域大过 `--review-batch-size` 时，它**整个留在自己那一批**里，不会被切成两半。

**规矩**（这一段是这一节的全部意义）：

- **一批一份 overrides 文件**，文件名就用 `batch-NN.overrides.json`。
- **绝不改别的批次的文件**。你只对手上这一批负责。
- **每批最多 8 条去问人的问题**，凭证据自答仍然不限条数。8 条是**每批**的额度，不是整轮的。
- 只输出这一批的 overrides 文件；别把几批合并成一份，合并是下一步的事。
- 写 `merge_into` 之前先看工作表的「已是成员」：这张表已经被哪个概念按什么角色收下了。  并到同一个概念上时撞的就是那一条（`add_tables` 报 `already_a_member` 的也是它），  留下来的是两个角色里**较强**的那个——这一点在批次里就能看见，不用回 `ontology.json` 翻。
- 「匹配分」只是排序，不是建议：名字对上 3 分、共同键词根 2 分、关系 1 分，分高的先读，  读完两边的表再决定。
- 骨架里 `merge_into` **留空表示「本轮没答」**：原样应用什么也不会发生，`unmatched` 与
  `ignored_fields` 都是空的，`sources[].applied` 是 0。留空**不占目标键**，既不算冲突，也盖不掉
  别的文件给出的真答案。答不出来就留着或删掉，不要为了填满而乱填。

答完几批之后，`--concept-overrides` **可以重复**，按你做批次的顺序给：

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --concept-overrides <review>/batches/batch-01.overrides.json \
  --concept-overrides <review>/batches/batch-02.overrides.json
```

- 不冲突的条目**累加**：两份文件点的是不同的键，两边都生效。
- 同一个目标键（概念 id + 字段、`add_tables` 的某张表、`new_concepts` 的某个 id、
  `merge_into` 的来源）被两份文件都点到时，**后给的那份生效**，并报一条
  `concept_overrides_applied.conflicts[] = {key, field, earlier, later}`。
  **冲突由人来定**：看到它就回头确认两批里哪一条才是对的，不要靠调换命令行顺序蒙混过去。
- `concept_overrides_applied.sources[]` 逐个文件写着它赢下了几条，拿它核对
  「我刚写的那一批真的落进去了吗」。
- 同一份文件给两遍等于给一遍，输出逐字节不变。

## 先读什么

1. `ontology.md` 的「本体总览」：一屏看完这份语料被读成了哪几个概念、按种类各几个、谁连谁。
   框里是概念名与种类，底色按种类分；边上的 `?` 是「基数只是作者假设」。
2. 「概念」表：每个概念一行——名字、种类与它的层级、表数（按角色拆开）、前三个命名候选、
   `疑似重复`。**这是这一轮的工作台。**
3. 「关系」表：概念之间的关系——类型、两端、参与身份、基数与层级、证据条数。M2 起
   `ontology.json` 里这一层就叫 `relations[]`；表与表之间的 JOIN 是它的**证据**，在
   `table_relations[]`，每条写着自己折进了哪条概念关系（`concept_relation`）。
4. 「临时概念（每表一个，待归并）」：语料没能把它归到任何业务键上的表，每张各自成了一个
   概念（`tier: "provisional"`、`origin: "provisional"`，id 形如 `concept:table:<表名>`，
   点号换成 `_`）。**这是这一轮的第一步**，见下面第 1 节。N2 起这份清单**分两处**：
   `ontology.md` 里只有计数、去处，以及**影响最大的 20 个**（按它带的概念关系数排序——
   那就是答完能解开多少东西）；**完整一行一个的清单在 `appendix.md` 的同名小节里**，与
   `--review-batches` 切出来的队列同一个顺序。行里写着名字、种类、是哪张表、影响，以及
   回写时要用的那个 id。`appendix.md` 里紧跟着的「退役键词根」（只在有的时候出现）说哪些
   词根被通用键规则挡下了——**它们仍然可以被点名**，逐条在 `retired_stems[]`。（M2 删掉了
   `unassigned_tables[]`：每张表都有概念了，只是临时概念不是答案，是问题。）
5. **每个概念自己那一份文件**（N2）：`ontology.md` 概念表里的名字就链到 `concepts/<文件>.md`
   （`concept:cust` → `concepts/cust.md`），里面是表现（表 / 角色 / 依据 / 粒度）、全部属性、
   约束、关系（连同折出它的表级 JOIN）、待人工判定、命名与类别依据，以及这个概念的回写键。
   判断一个概念折得对不对，读它这一份最快。临时概念没有文件：它是一个问题，答案从
   `appendix.md` 的清单或 `--review-batches` 的队列里做。
6. 每张表卡片第 7 节开头那一行：「本表是〈概念〉的〈角色〉视图（〈依据〉）」，或者
   「本表暂自成概念〈名字〉（provisional），待评审归并」；紧接着的「概念中的其他表现」列出
   同一概念的别的表。**核对某一张表归得对不对，看这两块最快。**
7. 完整字段（`kind_evidence[]` 的逐条投票、`name_candidates[]` 的来源与出现次数、
   `tables[].membership_basis`）在 `ontology.json` 的 `concepts[]` 里；反过来，
   `tables[].concepts[]` 说一张表表现了哪些概念。

## 按这个顺序问：临时概念归并 → 种类 → 名字 → 合并 → 拆分 → 角色

顺序是有理由的，不要打乱：**临时概念先归并掉**，否则后面每一步都在对着一堆「其实是别人的一部分」
的伪概念做判断（种类、名字、关系全白算一遍）；**种类错了，名字和关系都会跟着错**（把「消息发送」
读成实体，它与「客户」的关系就从 `participation` 掉成 `association`，`roles[]` 整段消失）；
名字定了，才谈得上两个概念是不是同一个；合并与拆分会改变成员表，所以角色放在最后校。

### 1. 临时概念归并（这一轮的第一件事）

「临时概念」表里的每一行都是同一个问题：**这张表是什么**。语料答不出来——它的键要么是代理键，
要么跨了两个词根，要么压根没有——所以这一版让它自成一个概念，好让它身上的每条边都能折下去。
这不是一个判断，是一张待办。逐个看，三条出路选一条：

| 出路 | 什么时候选 | 怎么写 |
| --- | --- | --- |
| **归进一个已有概念** | 卡片第 2、3 节看得出它是某个概念的一份副本（主表 / 快照 / 明细 / 汇总 / 中间步骤） | `concepts` 里以这个临时概念的 id 为键写 `merge_into: "<留下来的概念 id>"`，带 `basis`。成员会连同属性一起并过去，成员的 `membership_basis` 发布成 `override`、`role_tier` 为 `confirmed` |
| **和别的临时概念一起自成一个新概念** | 好几张临时概念说的是同一件事，而语料一个词根也没发芽 | `new_concepts` 里写一条，`tables` 里把这几张表逐个点名到角色上；它们的临时概念随之解散，报在 `concept_overrides_applied.dissolved[]` |
| **它确实自成一件事** | 业务方认得出这一张表就是一件东西（一份独立的台账、一条独立的事件流） | 以这个临时概念的 id 为键写 `name` / `kind`（必要时还有 `roles`），跟别的概念一模一样地确认 |

- 也可以反过来写：`concepts` 里对**已有概念**写 `add_tables: {"<那张表>": "<角色>"}`，效果与
  `merge_into` 相同，那张表的临时概念同样解散，报在 `dissolved[]` 里。两种写法选顺手的一种，
  **不要对同一张表同时写两种**。
- 一个例外：`add_tables` 里写 `reference` 的**不算归并**。`reference` 的意思正是「这张表只是
  带着这个键」，它没有回答「这张表是什么」，所以那个临时概念**留着**，问题也留着。
- `merge_into` 的方向、`primary` 副本的取舍，与下面第 4 节的规则完全一致。
- **临时概念不占去问人的额度**：它们的归并绝大多数看卡片就能自答（证据 6 正为此存在）。真的
  看不出来的，再按「只问四类」的第 5 类去问，**8 条的上限是留给剩下的问题的**。

### 2. 种类（entity / event / summary）

`kind` 有三种：`entity` 业务留着的一件东西（客户、门店）、`event` 发生过的一件事
（消息发送、回款）、`summary` 有人聚合出来的数（客户日汇总）。`kind_evidence[]` 里每条都写了
**哪个信号投了哪一票**：`key_event_column`（键里有事件列）、`increment_with_event_time`
（增量表带事件时间）、`driving_rows_over_log_source`（主表行来自日志源）、
`all_members_summary`（成员全是聚合产出）、`word_hint`（表名或注释里的词）。

- `kind_tier` 为 `implied`：投票一致，**别问人**，除非你能指出证据本身错了。
- `kind_tier` 为 `hypothesis`：两个信号投了不同的票，`kind_evidence[]` 里看得见是哪两个。
  这是**值得问的第一类问题**。
- 只有词汇线索（`signal` 全是 `word_hint` 或 `no_signal`）：**分两种，别混**。词提示彼此
  一致、`kind_tier` 已是 `implied` → **自答**，`basis` 写「仅词汇线索一致」，那句话本身就
  告诉复核者这一条比结构信号弱（见下面「凭证据自答」的证据 5）。词提示互相打架，或
  `kind_tier` 为 `hypothesis` → **这才是去问人的那一类**。表名里有 `log` 不代表它是事件，
  但几处措辞都说是日志、又没有任何结构信号反对时，为它占掉一条问人的额度并不值得。

### 3. 名字

`name` 是 `name_candidates[]` 里排第一的那个，来源可能是 `key_column_comment`（键列的
注释）、`table_comment`（表注释）或 `key_stem`（键词根本身）。语料自己给的名字最高只到
`hypothesis`，而排第一的那条来源是 `key_stem` 时 `name_tier` 写的是 **`stem_only`**（K2c）：
词根是仓库的写法，`queue` / `key` 这种英文缩写业务方看不懂，那不是一个猜测，是「没有任何
东西给它起过名」。**`name_tier` 为 `stem_only` 的概念一定要问人**——这一条比数候选来源可靠，
因为一条 junk 候选（周期 / 度量 / 筛选，见 `junk_reason`）也不是名字。给业务方看候选清单，
让他挑一个或者自己写一个，并记下**凭什么**。

### 4. 合并（同一件东西被写成了两个概念）

`possible_duplicate_of` 是 K2 发现两个概念提出了**同一个名字**时打的标，它**没有**替你合并——
一个词被两件事共用，和一件事有两个词根，这一层分不出来。除它之外，下面两种也值得怀疑，
但都要拿证据，不许凭名字像：

| 线索 | 证据在哪 | 还需要什么 |
| --- | --- | --- |
| 两个概念的 `name` 相同 | `possible_duplicate_of` | 问业务方这两组表是不是一件东西 |
| 两个词根之间有 `association`，基数 `one_to_one_assumed` | 「关系」表 | 一对一不等于同一件事，仍要问 |
| 两个概念的 `attributes[].stem` 大面积重合 | `concepts[].attributes[]` | 重合的是通用字段（`dt`、`create_time`）时不算数 |

合并是**有方向**的：`merge_into` 写"留下来的那个"的 id，被合掉的那个的表、属性与词根都并过去，
它的 id 记在留下来那个的 `merged_from[]` 里。**概念关系在合并之后才折**，所以原本指向被合掉
那个概念的边，会自动改指到留下来的那个。

**方向怎么选**：把 `primary` 成员**少**的那一边合进多的那一边。两边各有自己的 `primary`
副本时，两条成员都会留下来（谁才是「这个概念的那一份」只有业务方答得了，这一层不替你删），
同时报一条 `concept_overrides_applied.warnings[] = {key, warning: "merge_kept_two_primaries: <表1>, <表2>"}`。
看到这条就回头看一眼：要么方向写反了，要么这两组表本来就是两件东西，合并这一问应该原样去问业务方。
同一张表在两边都是成员时，它按**较强**的那个角色留下（`primary` > `snapshot` > `detail` >
`summary` > `intermediate` > `reference`）——被合掉那一边读出来的东西不该因为合并而丢掉。

**被合掉的是一个临时概念时，这条警告不适用**：它只有一张表，那张表按 M1 的构造必然是它自己的
`primary`。它那条成员在并进来时**重新定角色**——留下来的概念已经有 `primary` 了，就按它自己的
表名后缀与产出粒度降成 `snapshot` / `summary` / `intermediate` / `detail`；没有，它就是
`primary`——并发布成 `membership_basis: "override"`、`role_tier: "confirmed"`。所以把一个
临时概念并进真概念**永远不会**报 `merge_kept_two_primaries`，看见这条一定是两个真概念的合并。

### 5. 拆分（一个概念其实是两件事）

反过来的情形：一个词根把两件事收到了一起（`cust` 同时收了签约客户与潜在客户）。线索是
`kind_evidence[]` 内部打架、或者成员表里有两组 `role` 都是 `primary` 而 grain 明显不同。
拆分要**逐表点名**：`into[]` 里每一项写一个名字和它带走的表，新概念的 id 是
`concept:<词根>-1`、`concept:<词根>-2`，按文件里的顺序编号。没被点名的表留在原概念上；
全被点走了，原概念就不再发布。

### 6. 角色（这张表是这个概念的哪一份）

`tables[].role` 说这张表是概念的哪一份副本：`primary` 主表、`snapshot` 快照、`detail` 明细、
`summary` 汇总、`intermediate` 中间步骤、`reference` 引用（**这张表只是带着这个键，不是这个
概念的一份**——事件表参与客户就是这样）。`membership_basis` 说它凭什么进来：`key:<层级>`
是它自己的候选键，`declared_hint` 是元数据声明的主键注释，`reference` 是一条 JOIN。

只在**卡片第 7 节那一行明显读错了**的时候改它，例如一张 `_tmp` 中间表被读成了 `primary`。
角色不是业务判断，**不要为它去占那 8 条问人的额度**——能改就自己改，写清 `basis`。

漏掉的成员用 `add_tables` 补：`roles` 只能移动已经在册的成员，`add_tables` 把任何一张本语料的
表放进这个概念，值写它的角色。语料读不出它的键、元数据也没说话，而你在卡片里看得出它是这个概念
的一份——这是唯一能说出口的地方。加进来的成员 `membership_basis` 是 `override`、`role_tier`
是 `confirmed`，它的列并进概念的属性；那张表原本的**临时概念随之解散**，报在
`concept_overrides_applied.dissolved[]` 里（`reference` 角色除外，见第 1 节：它既不解散那个
临时概念，**列也不并进属性**——只是带着这个键，不被这个键描述）。一张表可以加进
好几个概念（一张明细表同时带着两个键），但**身份只有一个**：这张表如果已经被自己的键放在某个
概念上，再加到别的概念只是「带着这个键」，不会把身份抢过去。

### 补：新建概念（语料一个也没发芽，你却看得出来）

`add_tables` 需要先有一个**语料发芽出来的**概念可加。**一个都没有**的时候用 `new_concepts`：
这一件东西的每张表都只有代理键（`id`、`rowkey`），谁也没发芽，而卡片里看得出它们说的是同一件
事——也就是第 1 节里「好几个临时概念其实是一件事」的那一条出路。写 `id`
（`concept:<小写词根>`，没人用过）、`name`、`kind`、`tables`（表 → 角色），可选 `key_columns`。
建出来的概念三个层级全是 `confirmed`、`origin` 是 `override`，被点名的那几张表的临时概念随之
解散，报在 `dissolved[]` 里。已经被自己的键放在别的概念上的表只能给 `reference` 角色，否则报
`already_a_member`——**临时概念不算**「别的概念」，它本来就是等着被这一条答掉的。

`ontology.md` 的「被挡下的键词根」/ `retired_stems[]` 是同一件事的另一半：某个词根这一版被
通用键规则挡下了，**上一轮你对 `concept:<那个词根>` 写的答案照写不误**——`concepts` 里直接用
那个 id，它会按 `retired_stems[]` 记下的表与角色把概念建回来，报在 `created[]` 里带
`revived: true`，而不是报 `unknown_concept`。判定规则会改，评审的答案不该跟着作废。

## 凭证据自答：Agent 先答，剩下的才去问人

只有下面六类证据可以自答，别的都不行：

| # | 可自答 | 证据 | 写进 `basis` 的话术 |
| --- | --- | --- | --- |
| 1 | 名字 | 某个成员表的**表注释**或**键列注释**给出了一个中文业务词，且 `name_candidates[]` 里它的 `source` 是 `table_comment` / `key_column_comment` | `<表>.<列> 的注释 <原注释> 称它为 <名字>` |
| 2 | 种类 | `kind_tier` 已是 `implied`，且要写的 `kind` 与它一致（把已推得的结论显式确认下来） | `kind_evidence 中 <N> 个信号一致投 <种类>` |
| 3 | 角色 | 该表在 `tables[]` 里的 `membership_basis` 与卡片第 2 节的 grain 直接矛盾（例如 grain 证明它是按天聚合的，却被读成 `primary`） | `生产任务 <任务名> 的 grain 为 <basis>，本表是汇总而非主表` |
| 4 | 合并 | 两个概念的**词根经 O5 同义证明同值**（`tables[].attributes[].synonyms[]` 里有一条把两个键列连起来），不是名字像 | `O5 已证明 <表A>.<列A> 与 <表B>.<列B> 同值` |
| 5 | 种类（只有词汇线索） | `kind_evidence[]` 里 `signal` 全是 `word_hint` 或 `no_signal`，几条 `word_hint` **投的是同一票**，且 `kind_tier` 为 `implied` | `仅词汇线索一致：<N> 处词汇都投 <种类>，没有结构信号反对` |
| 6 | 角色 / 成员 | 某张表的**表注释**同时命名了**概念**与**粒度**（「客户日快照」＝客户的快照，「客户还款明细」＝客户的明细）——那正是 `role` 与 `add_tables` 读的东西 | `表注释命名了概念与粒度：<表> 的注释 <原注释> 说它是 <概念> 的 <角色>` |

- 自答一律写进 `concepts.overrides.json`，**每条都必须带 `basis`**；`confirmed_by` 写
  `agent:concept-review` 之类的 Agent 标识。
- 证据 1 只能确认**名字**，不能顺手把种类也确认了；证据 2 与证据 5 只能确认**种类**；
  证据 6 只能确认**角色或成员**（`roles` / `add_tables` / `new_concepts` 的一条成员），
  不能顺手把名字或种类也确认了——注释里的「客户」是命名候选，不是被确认的名字。
- 证据 5 比证据 2 弱，所以它多一条限制：`kind_tier` 是 `hypothesis`（几处词提示投了不同的
  票）时**一条都不许自答**，那是下面「只问四类」的第 1 类。
- **拆分永远不许自答。** 把一个概念拆成两件事是业务判断，语料里没有任何东西能证明它。
- 两条证据互相矛盾（表注释说 A、键列注释说 B）时一条都不许自答，原样留着去问人。
- `name_tier` 为 `stem_only` 的名字**不许自答**：把英文缩写确认成业务名，等于把"我们不知道"
  写成了"已确认"。

自答不限条数；去问人的问题**一次最多 8 条**，自答的不占这个额度。

## 只问五类

| 类 | 什么时候问 | 为什么值得问 |
| --- | --- | --- |
| 1. 种类打架 | `kind_tier` 为 `hypothesis`——两个结构信号投了不同的票，或只有词汇线索而几处词提示互相打架 | 种类错了，名字、关系类型与参与身份会一起错 |
| 2. 名字没有中文来源 | `name_tier` 为 `stem_only`（K2c）——排第一的候选来源是 `key_stem`：要么没有别的候选，要么剩下的都带 `junk_reason` | 业务方看不懂英文缩写，这个概念等于没命名 |
| 3. 疑似重复 | `possible_duplicate_of` 非空 | 一个词被两件事共用，还是一件事有两个词根，只有业务方知道 |
| 4. 一个概念像两件事 | 成员表里两组 `primary` 的 grain 明显不同 | 合在一起会让下游按错误的口径统计 |
| 5. 临时概念归不下去 | 一个临时概念的表注释与列注释都说不出它是什么，卡片里也看不出它是谁的一份（M1） | 归错了会把一张无关的表并进某个概念，从此它的每条边都算在那个概念头上 |

第 5 类**最后排队**：先把看得出来的临时概念自答掉，8 条的额度留给真的看不出来的那几张。
临时概念动辄几十个，把它们原样倒给业务方是把这一层的工作推给别人。

**不问的事**：成员角色（自己改，见上）、`kind_tier` 已是 `implied` 的种类（证据一致，
再问等于不信任证据——**只有词汇线索时也一样**，按证据 5 自答，别把同一件事既写进自答表
又写成问题）、某一列的中文含义（走 `glossary.overrides.template.md`）、
表的候选键与基数（那是 `ontology-review-prompt.md` 那一轮的事）、
**看得出归属的临时概念**（自己 `merge_into` / `add_tables` / `new_concepts` 写掉，见第 1 节；
真的两样都看不出的才按上面第 5 类去问，或者先补元数据、补语料）。

## 每条固定五行加一行留白

```
Q<n>. <一句问题，业务方不看 SQL 也能懂>
- 证据：<ontology.json 路径或卡片小节，允许写结构词>；概念 id <concept:…>，涉及 <N> 张表
- 候选答案：<A / B / C，或「无候选」>
- 回写目标：概念:<concept id>.<name|kind|merge_into|split>
- 影响：<答错会怎样，写具体的数字后果>
- 答案：（待填）
```

- `- 证据：` 这一行**豁免「正文不得出现结构词」**：`kind_evidence`、`name_candidates`、
  `possible_duplicate_of`、`hypothesis` 这类原词照写，它是给复核者的指针。
- `- 回写目标：` 只写一种，且写全 `concept:` 开头的 id；拆分写 `概念:<id>.split`。
- `- 答案：（待填）` 必须写出来。

### 措辞底线

- 不许把候选写成事实。不写「`concept:cust` 就是客户，对吗」；写「这组表的键列注释写的是
  『客户编号』，所以候选名字是『客户』。业务上这批表说的是同一件东西吗，它叫什么？」
- 种类的问题要把两票都摆出来：「表名里有 `log`，但生产任务是按客户号聚合的——这批数据是
  『发生过的一件事』还是『客户的一个属性』？」不要替业务方选。
- 合并的问题不要替业务方合：把两个概念各自的表列出来，问是不是一件东西。
- 一条问题只能有一个回写目标。

## 答案回来之后

业务方把答案写在 `- 答案：` 行，按回写目标合并进 `concepts.overrides.json`：

```json
{
  "doc_format": "concept-overrides/1",
  "concepts": {
    "concept:cust": {
      "name": "客户",
      "kind": "entity",
      "roles": {"tmp.cust_step01": "intermediate"},
      "add_tables": {"ods.cust_wide": "detail"},
      "basis": "<凭什么，自由文本>",
      "note": "<补充说明，可省>",
      "confirmed_by": "<名字或 agent:…>",
      "date": "<YYYY-MM-DD>"
    },
    "concept:party": {
      "merge_into": "concept:cust",
      "basis": "<凭什么，自由文本>",
      "confirmed_by": "<名字>",
      "date": "<YYYY-MM-DD>"
    }
  },
  "new_concepts": [
    {
      "id": "concept:party",
      "name": "往来方",
      "kind": "entity",
      "tables": {"ods.party_base": "primary", "ods.cust_base": "reference"},
      "key_columns": ["party_no"],
      "basis": "<凭什么，自由文本>",
      "confirmed_by": "<名字或 agent:…>",
      "date": "<YYYY-MM-DD>"
    }
  ],
  "splits": [
    {
      "from": "concept:acct",
      "into": [
        {"name": "签约账户", "tables": ["ods.acct_base"]},
        {"name": "申请账户", "tables": ["ods.acct_apply"]}
      ]
    }
  ]
}
```

- `concepts` 的键是概念 id，逐字照抄「概念」表、「临时概念」表或卡片第 7 节印的那一串。
  临时概念的 id 形如 `concept:table:<表名，点号换成 _>`（表名里带大写时，后面还挂着一段 6 位的
  表名摘要——只大小写不同的两张表是两张表，各有各的 id），写法上与别的概念没有任何区别：
  `name` / `kind` / `roles` / `add_tables` / `merge_into` 都照常生效。
- `name` / `kind` / `roles` 被确认的那一项会升到 `confirmed`（分别写在 `name_tier` /
  `kind_tier` / 该成员的 `role_tier` 上），`confirmed_by` / `date` / `basis`（发布成
  `confirmed_basis`）/ `note` 一起记在概念的 `confirmation` 里。
- `kind` 只能是 `entity` / `event` / `summary`；`roles` 与 `add_tables` 的取值只能是
  `primary` / `snapshot` / `detail` / `summary` / `intermediate` / `reference`。写别的会被
  报成 `unknown_kind:` / `unknown_role:`，那一项不生效。
- `add_tables` 的键是**表名**，必须是本语料 `tables[]` 里有的一张表，否则报
  `unknown_table: <表>`；已经是这个概念成员的表报 `already_a_member: <表>`，
  用 `roles` 改它的角色，不要用 `add_tables` 加第二遍。
- `merge_into` 写留下来的那个概念的 id。合并在**概念关系折叠之前**生效，所以原本指向被合掉
  那个概念的边会自动改指过来。**把 `primary` 少的那一边合进多的那一边**；两边各有一个
  `primary` 时两条都留着，并报一条 `warnings[] = {"merge_kept_two_primaries: <表1>, <表2>"}`——  被合掉的是**临时概念**时不会有这一条，它那条成员是按留下来那个概念的角色规则重新定的。
  被合掉的是一个**临时概念**时，它那条成员发布成 `membership_basis: "override"`、
  `role_tier: "confirmed"`——是人把这张表放进来的，它不再自称「没人放过」。
- `splits[].into[]` 逐表点名，新概念是 `concept:<词根>-1`、`-2`，按文件顺序编号；
  没被点名的表留在原概念上。
- `new_concepts[]` 新建一个语料没发芽的概念（见上面「补：新建概念」）。`id` 要没人用过、且形如
  `concept:<小写词根>`，否则报 `already_a_concept:` / `invalid_concept_id:`；一张表都没点
  报 `no_tables`。**新建在合并与拆分之前生效**，所以后面几步点得到它。
- `concepts` 的键若是 `retired_stems[]` 里的某个词根，那一条按记下的表与角色把概念建回来，
  报在 `created[]` 里带 `revived: true`。

`add_tables` 与 `new_concepts` 顺手解散掉的临时概念逐条报在
`concept_overrides_applied.dissolved[]` 里（`{id, table, into}`），拿它核对「我以为归并掉的
那几张表，是不是真的归并掉了」。

跑完检查三件事：`concept_overrides_applied.concepts` / `created` / `tables_added` /
`merges` / `splits` / `dissolved` 的条数与你合并的条数相等；`concept_overrides_applied.unmatched` 为空——非空说明某个 id 或表名抄错了，`reason`
直接说错在哪（`unknown_concept` / `unknown_concept: <id>` / `unknown_table: <表>` /
`unknown_kind: <值>` / `unknown_role: <值>` / `already_a_member: <表>` /
`merge_into_self`）；`concept_overrides_applied.warnings` 为空——非空说明某次合并把两个
`primary` 副本折进了一个概念，回头确认方向，或者把这一问原样交给业务方；
`concept_overrides_applied.ignored_fields` 为空——非空说明某个字段名拼错了，那一项没生效。

## 自检

| # | 检查项 | 通过 |
| --- | --- | --- |
| 1 | 按临时概念归并 → 种类 → 名字 → 合并 → 拆分 → 角色的顺序走过一遍 | |
| 2 | 每条问题业务方不看 SQL 也能懂，正文没有结构词（`- 证据：` 行除外） | |
| 3 | 每条只有一个回写目标，id 逐字抄自「概念」表或卡片第 7 节 | |
| 4 | 正文没有把 `hypothesis` 的候选写成事实 | |
| 5 | 去问人的总数 ≤ 8 条，超出的进「备查项」 | |
| 6 | 每条都有 `- 答案：（待填）` 行 | |
| 7 | 凭证据自答只用了表里那六类证据（含证据 6：表注释命名了概念与粒度），且每条都写了 `basis` | |
| 8 | 没有自答任何一个拆分，也没有把 `name_tier` 为 `stem_only` 的名字自答掉 | |
| 9 | 没有问成员角色、没有问 `implied` 的种类、没有问键与基数（那是另一轮） | |
| 10 | 跑完 `--concept-overrides` 后 `unmatched` 与 `ignored_fields` 都是空的 | |
| 11 | 只有 `word_hint` 的种类：一致且 `implied` 的已按「仅词汇线索一致」自答，只有打架的或 `hypothesis` 的才去问人 | |
| 12 | 新建的概念 id 都是没人用过的 `concept:<小写词根>`，成员表里没有一张是别的概念**按身份**收下的（那种只能给 `reference`） | |
| 13 | `retired_stems[]` 里的词根若有上一轮的答案，已经照原 id 写进 `concepts`，没有当成 `unknown_concept` 丢掉 | |
| 14 | **两个真概念之间**的每次合并都把 `primary` 少的那一边合进多的那一边，`warnings` 里没有 `merge_kept_two_primaries`（把临时概念并进真概念不在此列：它那条成员会被重新定角色，本来就不会报） | |
| 15 | `add_tables` 里写 `reference` 的表，本意确实是「只是带着这个键」——那一条不会改变这张表本身是什么，它的列也不进这个概念的 `attributes[]`，它的临时概念也不会因此解散 | |
| 16 | 「临时概念」表逐行看过一遍，看得出归属的都已经写成 `merge_into` / `add_tables` / `new_concepts`，没有原样倒给业务方 | |
| 17 | 跑完 `--concept-overrides` 后 `provisional_count` 比上一轮少，`dissolved[]` 的条数与你写下的归并条数对得上 | |
