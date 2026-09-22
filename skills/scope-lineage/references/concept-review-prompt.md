# 把概念层的候选变成业务方认得出的概念

读 `ontology.md` 的「概念层」之后用这份提示词。它和 `ontology-review-prompt.md` 是同一份
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

## 先读什么

1. `ontology.md` 的「概念层」：一屏看完这份语料被读成了哪几个概念、谁连谁。框里是概念名与
   种类，底色按种类分；边上的 `?` 是「基数只是作者假设」。
2. 「概念」表：每个概念一行——名字、种类与它的层级、表数（按角色拆开）、前三个命名候选、
   `疑似重复`。**这是这一轮的工作台。**
3. 「概念关系」表：类型、两端、参与身份、基数与层级、证据条数。
4. 「未归入概念的表」：多少张表没有落到任何概念上，以及最常见的原因。逐表清单在
   `ontology.json` 的 `unassigned_tables[]`。紧跟着的「被挡下的键词根」（只在有的时候出现）
   说哪些词根被通用键规则挡下了——**它们仍然可以被点名**，逐条在 `retired_stems[]`。
5. 每张表卡片第 7 节开头那一行：「本表是〈概念〉的〈角色〉视图（〈依据〉）」，或者
   「未归入任何概念（〈原因〉）」。**核对折叠对不对，看这一行最快。**
6. 完整字段（`kind_evidence[]` 的逐条投票、`name_candidates[]` 的来源与出现次数、
   `tables[].membership_basis`）在 `ontology.json` 的 `concepts[]` 里。

## 按这个顺序问：种类 → 名字 → 合并 → 拆分 → 角色

顺序是有理由的，不要打乱：**种类错了，名字和关系都会跟着错**（把「消息发送」读成实体，
它与「客户」的关系就从 `participation` 掉成 `association`，`roles[]` 整段消失）；名字定了，
才谈得上两个概念是不是同一个；合并与拆分会改变成员表，所以角色放在最后校。

### 1. 种类（entity / event / summary）

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

### 2. 名字

`name` **永远**是 `hypothesis`：它是 `name_candidates[]` 里排第一的那个，来源可能是
`key_column_comment`（键列的注释）、`table_comment`（表注释）或 `key_stem`（键词根本身）。
词根来源的名字是英文缩写，业务方看不懂——**候选里只有 `key_stem` 一种来源时，这个概念一定
要问人**。给业务方看候选清单，让他挑一个或者自己写一个，并记下**凭什么**。

### 3. 合并（同一件东西被写成了两个概念）

`possible_duplicate_of` 是 K2 发现两个概念提出了**同一个名字**时打的标，它**没有**替你合并——
一个词被两件事共用，和一件事有两个词根，这一层分不出来。除它之外，下面两种也值得怀疑，
但都要拿证据，不许凭名字像：

| 线索 | 证据在哪 | 还需要什么 |
| --- | --- | --- |
| 两个概念的 `name` 相同 | `possible_duplicate_of` | 问业务方这两组表是不是一件东西 |
| 两个词根之间有 `association`，基数 `one_to_one_assumed` | 「概念关系」表 | 一对一不等于同一件事，仍要问 |
| 两个概念的 `attributes[].stem` 大面积重合 | `concepts[].attributes[]` | 重合的是通用字段（`dt`、`create_time`）时不算数 |

合并是**有方向**的：`merge_into` 写"留下来的那个"的 id，被合掉的那个的表、属性与词根都并过去，
它的 id 记在留下来那个的 `merged_from[]` 里。**概念关系在合并之后才折**，所以原本指向被合掉
那个概念的边，会自动改指到留下来的那个。

### 4. 拆分（一个概念其实是两件事）

反过来的情形：一个词根把两件事收到了一起（`cust` 同时收了签约客户与潜在客户）。线索是
`kind_evidence[]` 内部打架、或者成员表里有两组 `role` 都是 `primary` 而 grain 明显不同。
拆分要**逐表点名**：`into[]` 里每一项写一个名字和它带走的表，新概念的 id 是
`concept:<词根>-1`、`concept:<词根>-2`，按文件里的顺序编号。没被点名的表留在原概念上；
全被点走了，原概念就不再发布。

### 5. 角色（这张表是这个概念的哪一份）

`tables[].role` 说这张表是概念的哪一份副本：`primary` 主表、`snapshot` 快照、`detail` 明细、
`summary` 汇总、`intermediate` 中间步骤、`reference` 引用（**这张表只是带着这个键，不是这个
概念的一份**——事件表参与客户就是这样）。`membership_basis` 说它凭什么进来：`key:<层级>`
是它自己的候选键，`declared_hint` 是元数据声明的主键注释，`reference` 是一条 JOIN。

只在**卡片第 7 节那一行明显读错了**的时候改它，例如一张 `_tmp` 中间表被读成了 `primary`。
角色不是业务判断，**不要为它去占那 8 条问人的额度**——能改就自己改，写清 `basis`。

漏掉的成员用 `add_tables` 补：`roles` 只能移动已经在册的成员，`add_tables` 把一张
`unassigned_tables[]` 里的表（或任何一张本语料的表）放进这个概念，值写它的角色。
语料读不出它的键、元数据也没说话，而你在卡片里看得出它是这个概念的一份——这是唯一能说出口
的地方。加进来的成员 `membership_basis` 是 `override`、`role_tier` 是 `confirmed`，它的列
并进概念的属性，它也从 `unassigned_tables[]` 里消失。一张表可以加进好几个概念（一张明细
表同时带着两个键），但**身份只有一个**：这张表如果已经被自己的键放在某个概念上，再加到别的
概念只是「带着这个键」，不会把身份抢过去。

### 补：新建概念（语料一个也没发芽，你却看得出来）

`add_tables` 需要先有一个概念可加。**一个都没有**的时候用 `new_concepts`：这一件东西的每张表
都只有代理键（`id`、`rowkey`），谁也没发芽，而卡片里看得出它们说的是同一件事。写 `id`
（`concept:<小写词根>`，没人用过）、`name`、`kind`、`tables`（表 → 角色），可选 `key_columns`。
建出来的概念三个层级全是 `confirmed`、`origin` 是 `override`，成员也从 `unassigned_tables[]`
里消失。已经被自己的键放在别的概念上的表只能给 `reference` 角色，否则报 `already_a_member`。

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
| 4 | 合并 | 两个概念的**词根经 O5 同义证明同值**（`entities[].attributes[].synonyms[]` 里有一条把两个键列连起来），不是名字像 | `O5 已证明 <表A>.<列A> 与 <表B>.<列B> 同值` |
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
- 只有 `key_stem` 一种来源的名字**不许自答**：把英文缩写确认成业务名，等于把"我们不知道"
  写成了"已确认"。

自答不限条数；去问人的问题**一次最多 8 条**，自答的不占这个额度。

## 只问四类

| 类 | 什么时候问 | 为什么值得问 |
| --- | --- | --- |
| 1. 种类打架 | `kind_tier` 为 `hypothesis`——两个结构信号投了不同的票，或只有词汇线索而几处词提示互相打架 | 种类错了，名字、关系类型与参与身份会一起错 |
| 2. 名字没有中文来源 | `name_candidates[]` 只有 `key_stem` | 业务方看不懂英文缩写，这个概念等于没命名 |
| 3. 疑似重复 | `possible_duplicate_of` 非空 | 一个词被两件事共用，还是一件事有两个词根，只有业务方知道 |
| 4. 一个概念像两件事 | 成员表里两组 `primary` 的 grain 明显不同 | 合在一起会让下游按错误的口径统计 |

**不问的事**：成员角色（自己改，见上）、`kind_tier` 已是 `implied` 的种类（证据一致，
再问等于不信任证据——**只有词汇线索时也一样**，按证据 5 自答，别把同一件事既写进自答表
又写成问题）、某一列的中文含义（走 `glossary.overrides.template.md`）、
表的候选键与基数（那是 `ontology-review-prompt.md` 那一轮的事）、
`unassigned_tables[]` 里的表（它们没有概念可问；你自己看得出它属于哪个概念的，用
`add_tables` 加上去，看得出它们自成一个概念而语料一个也没发芽的用 `new_concepts`，
两样都看不出的先补元数据或补语料）。

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

- `concepts` 的键是概念 id，逐字照抄「概念」表或卡片第 7 节印的那一串。
- `name` / `kind` / `roles` 被确认的那一项会升到 `confirmed`（分别写在 `name_tier` /
  `kind_tier` / 该成员的 `role_tier` 上），`confirmed_by` / `date` / `basis`（发布成
  `confirmed_basis`）/ `note` 一起记在概念的 `confirmation` 里。
- `kind` 只能是 `entity` / `event` / `summary`；`roles` 与 `add_tables` 的取值只能是
  `primary` / `snapshot` / `detail` / `summary` / `intermediate` / `reference`。写别的会被
  报成 `unknown_kind:` / `unknown_role:`，那一项不生效。
- `add_tables` 的键是**表名**，必须是本语料 `entities[]` 里有的一张表，否则报
  `unknown_table: <表>`；已经是这个概念成员的表报 `already_a_member: <表>`，
  用 `roles` 改它的角色，不要用 `add_tables` 加第二遍。
- `merge_into` 写留下来的那个概念的 id。合并在**概念关系折叠之前**生效，所以原本指向被合掉
  那个概念的边会自动改指过来。
- `splits[].into[]` 逐表点名，新概念是 `concept:<词根>-1`、`-2`，按文件顺序编号；
  没被点名的表留在原概念上。
- `new_concepts[]` 新建一个语料没发芽的概念（见上面「补：新建概念」）。`id` 要没人用过、且形如
  `concept:<小写词根>`，否则报 `already_a_concept:` / `invalid_concept_id:`；一张表都没点
  报 `no_tables`。**新建在合并与拆分之前生效**，所以后面几步点得到它。
- `concepts` 的键若是 `retired_stems[]` 里的某个词根，那一条按记下的表与角色把概念建回来，
  报在 `created[]` 里带 `revived: true`。

跑完检查三件事：`concept_overrides_applied.concepts` / `created` / `tables_added` /
`merges` / `splits` 的条数与你合并的条数相等；`concept_overrides_applied.unmatched` 为空——非空说明某个 id 或表名抄错了，`reason`
直接说错在哪（`unknown_concept` / `unknown_concept: <id>` / `unknown_table: <表>` /
`unknown_kind: <值>` / `unknown_role: <值>` / `already_a_member: <表>` /
`merge_into_self`）；
`concept_overrides_applied.ignored_fields` 为空——非空说明某个字段名拼错了，那一项没生效。

## 自检

| # | 检查项 | 通过 |
| --- | --- | --- |
| 1 | 按种类 → 名字 → 合并 → 拆分 → 角色的顺序走过一遍 | |
| 2 | 每条问题业务方不看 SQL 也能懂，正文没有结构词（`- 证据：` 行除外） | |
| 3 | 每条只有一个回写目标，id 逐字抄自「概念」表或卡片第 7 节 | |
| 4 | 正文没有把 `hypothesis` 的候选写成事实 | |
| 5 | 去问人的总数 ≤ 8 条，超出的进「备查项」 | |
| 6 | 每条都有 `- 答案：（待填）` 行 | |
| 7 | 凭证据自答只用了表里那六类证据（含证据 6：表注释命名了概念与粒度），且每条都写了 `basis` | |
| 8 | 没有自答任何一个拆分，也没有把只有 `key_stem` 来源的名字自答掉 | |
| 9 | 没有问成员角色、没有问 `implied` 的种类、没有问键与基数（那是另一轮） | |
| 10 | 跑完 `--concept-overrides` 后 `unmatched` 与 `ignored_fields` 都是空的 | |
| 11 | 只有 `word_hint` 的种类：一致且 `implied` 的已按「仅词汇线索一致」自答，只有打架的或 `hypothesis` 的才去问人 | |
| 12 | 新建的概念 id 都是没人用过的 `concept:<小写词根>`，成员表里没有一张是别的概念**按身份**收下的（那种只能给 `reference`） | |
| 13 | `retired_stems[]` 里的词根若有上一轮的答案，已经照原 id 写进 `concepts`，没有当成 `unknown_concept` 丢掉 | |
