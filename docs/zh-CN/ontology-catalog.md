[English](../en/ontology-catalog.md) | 中文

# 本体目录（`catalog-yaml/1`）与 `ontology-json/3`

本体目录是一个由人维护的文件夹，里面是 YAML（或 JSON）文件。它**先**说清业务世界里有什么，
**再**说由哪些表承载：业务域，实体、事件与角色，它们的标识符、属性与状态，它们之间的关系与约束，
人们对它们的叫法——然后在单独的映射层里写明哪张表表现哪个概念、每一列绑定到什么。

**目录是本体新的、概念先行的唯一事实来源。**生成器（血缘、表卡、LLM）可以对它提出变更，但不拥有它。
`scope-lineage catalog validate` 校验目录，`scope-lineage catalog build` 把它规范化成一份给机器读的
`ontology-json/3` 文档（可同时带上血缘语料与表卡显示的证据），`scope-lineage catalog render` 把这份
文档写成每个概念一页，`scope-lineage catalog query` 从中回答一个问题；`catalog digest` 与
`catalog merge` 帮助从表语义起草目录（见[起草](#起草catalog-digest-与-catalog-merge)）。

> **过渡期。**从表语义起草的这份目录才是业务本体。现有的 [`scope-lineage ontology`](ontology-doc.md)
> 命令从血缘语料自下而上按共用键词根折出 `ontology-json/2` **键折叠候选**，只是结构扫描与起草证据，
> 不是业务本体；它**再保留一个版本**，行为不变。目录不读它，它也不读目录。血缘与表卡证据
> 用 `catalog build --lineage/--tables` 挂到目录上；值词典暂不读取。

一份完整的虚构目录——一家虚构的消费信贷公司——放在
[`examples/catalog-demo/`](../../examples/catalog-demo/)；下面每个例子都取自它。

## 布局

```text
catalog/
  catalog.yaml          # 清单：doc_format、name、description（必需）
  domains.yaml          # domains: [...]
  identifiers.yaml      # identifiers: [...]
  code_sets.yaml        # code_sets: [...]
  concepts/*.yaml       # concepts: [...]   实体、事件、角色；通常每个域一个文件
  relations.yaml        # relations: [...]
  constraints.yaml      # constraints: [...]
  terms.yaml            # terms: [...]
  mapping/*.yaml        # representations: [...]   通常每个域一个文件
```

- 任一文件都可以是 `.yaml`、`.yml` 或 `.json`，可以混用。读 YAML 需要可选依赖 PyYAML：
  `pip install 'scope-lineage[catalog]'`。全部用 JSON 写的目录不需要额外依赖。
- 只有 `catalog.yaml`（或 `catalog.yml` / `catalog.json`）是必需的。缺失的文件视为空列表。
  同类文件按路径顺序拼接；对象写在哪个文件里不影响构建结果。
- 布局里没有的文件（拼错的 `domain.yaml`、`concepts/` 里的一份笔记）会报 `unknown_file`
  警告，而不是悄悄跳过。

```yaml
doc_format: catalog-yaml/1
name: demo-lending
description: A fictional consumer-lending shop.
```

## 通用字段

每个对象除了自己的字段，还带这些字段。

| 字段 | 取值 | 默认 | 含义 |
| --- | --- | --- | --- |
| `id` | `<前缀>:<slug>`；小写字母、数字、`_` 和 `.` | —（必填；术语与表现没有 id） | 全局唯一；前缀必须与对象类型一致 |
| `status` | `drafted` / `confirmed` / `deprecated` | `drafted` | 只有 `confirmed` 经过 owner 确认 |
| `source` | `owner` / `comment` / `task` / `sql` / `llm` / `mixed` | 无 | 这条陈述从哪里来 |
| `evidence` | 字符串列表：表、`表.列`、血缘 id、任务名 | `[]` | 评审可以顺着查的指针 |
| `notes` | 文字 | — | 自由备注 |

属性若不自己写 `status` 与 `source`，就继承所属概念的；绑定继承所属表现的。

## 元素

### 业务域

一组相关概念的业务范围。`id: domain:<slug>`、`name`、`description`。

```yaml
domains:
  - id: domain:lending
    name: 贷款
    description: Loans from disbursement to settlement.
    status: confirmed
    source: owner
```

### 标识符

在**某个范围内**唯一识别一个实体或事件的业务编号。

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `id` | 是 | `id:<slug>` |
| `name` | 是 | 业务名称 |
| `identifies` | 是 | 它识别的实体或事件 |
| `scope` | 是 | `global`，或 `{per: [<概念 id>, ...]}`：只在这些概念的每个组合内唯一 |
| `arises_when` | 否 | 标识符在什么条件下产生：文字，或 `{condition, state: <概念 id>#<状态值>}` |
| `spellings` | 否 | 物理拼写：`[{column, table?}]`；不写 `table` 表示"这个列名，出现在哪里都算" |
| `maps_to` | 否 | 与其他标识符的对应：`[{identifier, cardinality, via?: [表]}]`，基数为 `one_to_one` / `one_to_many` / `many_to_one` / `many_to_many` |
| `format` | 否 | 取值长什么样 |

```yaml
identifiers:
  - id: id:verified_customer_no
    name: 认证客户号
    identifies: concept:customer
    scope: global
    arises_when:
      condition: assigned when the customer passes identity verification
      state: concept:customer#verified
    spellings:
      - column: verified_customer_no
  - id: id:app_account_id
    name: 应用账户号
    identifies: concept:app_account
    scope:
      per: [concept:channel]
```

### 码值集

有限取值及其业务含义，可被多个属性共用。`id: code:<slug>`、`name`、
`values: [{value, meaning, retired?, unconfirmed?}]`、`definition?`。取值是文字或整数；`0` 与 `"0"`
是同一个码。数据里见到、含义还没人确认的值写 `unconfirmed: true`，或让 `meaning` 留空、以「待确认」
开头（其后是目录的猜测）；页面与查询把它写成「值（含义待确认：猜测）」，`governance.md` 列出含这类值的码值集。

```yaml
code_sets:
  - id: code:loan_status
    name: 借据状态
    values:
      - {value: "1", meaning: normal}
      - {value: "2", meaning: overdue}
      - {value: "3", meaning: settled, retired: false}
      - {value: "9", meaning: 待确认，疑似核销}
      - {value: "0", meaning: "", unconfirmed: true}
```

值存在一张码值表（字典表）里、目录不逐个列出时，写 `lookup` 指明去哪里查——一个码值集一个来源。
这时 `values` 可以是 `[]`，不报 `empty_code_set`：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `table` | 是 | `库.表`；不分大小写，`build` 一律写成小写 |
| `code_column` | 是 | 码所在的列：被翻译的列里存的就是它 |
| `meaning_columns` | 是 | `[{column, lang?}]`：含义所在的列，可按语言列多个 |
| `key_column` | 否 | 码值表的代理键列：事实表存的可能是它而不是码 |
| `filter` | 否 | `{列: 字面量}`：一张码值表装着多个码值集时，挑出本码值集那些行的常量等值条件 |
| `valid_from` / `valid_to` | 否，须成对 | 每行有效期的起止列 |

```yaml
code_sets:
  - id: code:waiver_reason
    name: 豁免原因
    values: []
    lookup:
      table: demo_dim.dim_code_dict
      code_column: code_val
      meaning_columns: [{column: code_desc, lang: zh}, {column: code_desc_en, lang: en}]
      key_column: dict_key
      filter: {code_type: WaiverReason}
      valid_from: valid_begin
      valid_to: valid_end
```

`lookup` 只表达「按码等值去查一张表」。码侧表达式（先 `substr(...)` 再查）、经映射表的两步翻译（先把码换成
另一张表的码，再查码值表）不在范围内：写进绑定的 `derivation` 文字。

`lookup` 只指**物理码表**（`库.表`）。字典若定义在 SQL 里（`VALUES` CTE、`CASE` 映射、字面量列表），它不是一张表：
把码写成码值集的 `values`，`evidence` 写生产它的任务名；不要给 CTE 起个名字当 `lookup.table`。
指向不存在的表会让 `catalog query table` 为一张不存在的表给出答案。

### 概念：实体、事件、角色

`id: concept:<slug>`、`kind`、`name`、`definition`、`domain`、`synonyms?`、`attributes`，
再加上各类型自己的字段：

| 类型 | 是什么 | 类型专属字段 |
| --- | --- | --- |
| `entity` | 独立存在、有稳定身份、能被反复引用的事物 | `identifiers`（列表）、`primary_identifier`（其中之一）、`states?` |
| `event` | 在某时点发生、有参与者、发生后不改（只能被冲正类事件抵消）的事 | `identifiers?`、`occurred_at`（它自己的一个属性）、`participants: [{role_name, concept, cardinality: one/many}]` |
| `role` | 实体在某业务上下文里的身份，不改变实体本身 | `player`（一个实体）、`context`（一个业务域）、`condition`（文字） |

缺 `definition` 允许但会警告。`role_name` 是 slug（`[a-z0-9_]+`），因为它会成为 id 的一部分
（见构建一节）。

```yaml
concepts:
  - id: concept:repayment
    kind: event
    name: 还款
    definition: A customer pays money back against one or more loans.
    domain: domain:lending
    identifiers: [id:repayment_txn_no]
    occurred_at: attr:repayment.repaid_at
    participants:
      - {role_name: payer, concept: concept:customer, cardinality: one}
      - {role_name: loan, concept: concept:loan, cardinality: many}
    attributes:
      - id: attr:repayment.repaid_at
        name: 还款时间
        definition: When the payment was received.
        category: time
        type: timestamp
  - id: concept:borrower
    kind: role
    name: 借款人
    domain: domain:lending
    player: concept:customer
    context: domain:lending
    condition: holds at least one loan whose status is not settled
```

### 属性

概念的一项业务特征，写在概念内部。`id: attr:<概念 slug>.<slug>`（概念 slug 必须是所属概念的）、
`name`、`definition`、`category`（`descriptive` / `state` / `measure` / `time`）、`type`、`unit?`、
`code_set?`、`derivation?`（文字口径）。

属性的码值集是它自己的 `code_set`；没有时，是绑定它的各列（`attribute` / `foreign_attribute`）的 `code_sets`，
按出现顺序去重。所有「这个属性的码」的读者都用这一条规则：A4「码值」格、`catalog query attribute`、缺码值缺口、
`code_sets.md` 在码值集下列出的属性。属性写了 `code_set` 就只是那一个，不把列上别的码值集并进来。

### 状态

实体在生命周期中的阶段，由事件推动迁移。写在实体的 `states` 下：承载状态的 `attribute`
（实体自己的属性之一）、`values`，以及 `transitions`——每条是一个 `event` 把实体从 `from`
迁到 `to`。

```yaml
    states:
      attribute: attr:loan.loan_status
      values:
        - {value: normal, name: 正常}
        - {value: overdue, name: 逾期}
        - {value: settled, name: 结清}
      transitions:
        - {event: concept:repayment, from: overdue, to: normal}
        - {event: concept:fee_waiver, from: overdue, to: settled}
```

### 关系

两个概念之间的业务联系。`id: rel:<slug>`、`kind`、`from`、`to`、`name`（动词）、`inverse_name?`、
`cardinality: {from, to}`，每端取 `"1"`、`"0..1"`、`"0..*"`、`"1..*"` 之一（YAML 里请给 `"1"`
加引号；不加引号的 `1` 也接受）、`definition?`。

| 种类 | 含义 | 例子 |
| --- | --- | --- |
| `association` | 两个独立概念由一个动词联系 | 借款人 欠 借据 |
| `composition` | 一方从属于另一方，离开它不存在 | 客户 拥有 应用账户 |
| `participation` | 实体或角色参与事件 | 由事件的参与者自动派生——不必手写 |
| `generalization` | 一方是另一方的一种 | 分期借据 是一种 借据 |
| `derivation` | 一方由另一方派生（指标，二期） | — |

每端的基数表示"对另一端的一个实例，这一端有多少个"：
`customer holds app_account {from: "1", to: "0..*"}` 即一个账户属于一个客户，一个客户可有任意多个账户。

`name` 与 `inverse_name` 只写动词短语，不带另一端的概念：页面把关系读成「<name> <另一端概念名>」（概念页概览的
「拥有的 / 关联的」），附录里读成「<起点> <name> <终点>」；从终点一侧读时用 `inverse_name` 和起点的名称。
自关联（`from` 与 `to` 是同一个概念）从本概念读既是起点也是终点：有 `inverse_name` 时两个方向都给出，概览读成
「<name> / <inverse_name> <概念名>」，附录与 `catalog query related` 读成「<概念名> <name> <概念名> / <概念名> <inverse_name> <概念名>」；
没有 `inverse_name` 的自关联只读 `name` 一个方向。
借款人→借据写 `name: 持有`、`inverse_name: 持有人为`，读出「持有 借据」「持有人为 借款人」；写成
`name: 持有借据` 就会读出「持有借据 借据」。

### 约束

必须成立的条件。`id: cons:<slug>`、`kind`（`unique` / `cardinality` / `mandatory` /
`value_domain` / `referential` / `temporal` / `state_transition` / `derivation` /
`business_rule`）、`on`（概念、属性、关系或标识符）、`expression`（文字）、`strength`（`hard` / `soft`）。

```yaml
constraints:
  - id: cons:loan_no_unique
    kind: unique
    on: id:loan_no
    expression: no two loans share a loan_no, whatever the channel
    strength: hard
```

### 术语

人们用的一个说法及其指向。`term`、`refers_to`（任一 id）、`preferred`。术语没有 id。

```yaml
terms:
  - {term: 借据, refers_to: concept:loan, preferred: true}
  - {term: 对客借据, refers_to: concept:loan, preferred: false}
```

### 表现与绑定

映射层，写在 `mapping/` 下的文件里（`.yaml` 或 `.json`）：哪张表以什么身份承载哪个概念，每一列是什么。表现以 `table`
（`库.表`）为键，每张表只能有一个表现。

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `table` | 是 | `库.表`；不分大小写，`build` 一律写成小写 |
| `concept` | 是 | 它表现的概念 |
| `kind` | 是 | `core` / `extension`（与核心 1:1）/ `dependent` / `event_detail` / `state_history` / `identifier_map` / `role_view` / `summary` / `intermediate` |
| `grain` | 是 | `{identifiers: [id], extra: [文字], source: declared/inferred/proven}` |
| `time` | 是 | `snapshot` / `incremental` / `zipper` / `unknown` |
| `scope` | 否 | 表里收哪些记录，文字；`render` 按关键词把每行归入过滤类别（见 `scopes.md`） |
| `refresh` | 否 | 更新频率 |
| `table_status` | 是 | `active` / `deprecated` |
| `replaced_by` | 否 | 废弃表的替代表 |
| `bindings` | 是 | `[{column, to, ref?, via?, relation?, derivation?, code_map?, code_sets?, code_sets_by?, holds?, lang?}]` |

绑定的 `to` 说明这一列是什么：

| `to` | `ref` | 含义 |
| --- | --- | --- |
| `attribute` | 必填 | 所表现概念的一个属性（角色视图也可以绑定其承担者的） |
| `identifier` | 必填 | 所表现概念的一个标识符（角色视图也可以绑定其承担者的） |
| `foreign_identifier` | 必填 | 另一个概念的标识符——即物理上的关系；也可以是本概念自己的标识符（同一概念的另一个实例），前提是目录里有一条两端都是本概念的关系；可选 `relation: rel:<id>` 写这一列实现哪条关系 |
| `foreign_attribute` | 必填 | 另一个概念 X 的属性，在本行冗余存放（宽表）；`via` 必填，写本表中绑定为 `foreign_identifier`、指向 X 的标识符的那一列。也可以是所表现概念自己的属性，但只限同一概念另一条记录的：`via` 那一列须绑定为 `foreign_identifier`、指向标识该属性所属概念的标识符（即上一行的自关联列）；角色视图里经承担者标识符的列只能这样带出承担者的属性，不能带出角色的 |
| `technical` | 不写 | 分区、加载时间、代理键 |
| `unmapped` | 不写 | 尚未决定（会警告） |

```yaml
representations:
  - table: demo_dwd.dwd_lending_loan_df
    concept: concept:loan
    kind: core
    grain:
      identifiers: [id:loan_no]
      source: proven
    time: snapshot
    table_status: active
    bindings:
      - {column: loan_no, to: identifier, ref: id:loan_no}
      - {column: customer_id, to: foreign_identifier, ref: id:customer_id}
      - {column: orig_loan_no, to: foreign_identifier, ref: id:loan_no}
      - column: loan_status
        to: attribute
        ref: attr:loan.loan_status
        code_map: {"1": normal, "2": overdue, "3": settled}
      - column: customer_gender_cd
        to: foreign_attribute
        ref: attr:customer.gender
        via: customer_id
      - {column: dt, to: technical}
```

`code_map` 写本表特有的码值含义；含义还没确认的值，含义以「待确认：」开头，页面原样显示这个前缀。

`code_sets` 写这一列的值与哪些码值集相关、按查找顺序：先查第一个，查不到再查下一个——SQL 里
`coalesce(g1.code_desc, g2.code_desc)` 这样的回退。按顺序回退是**列**的事实，不是任何一个码值集的事实，
所以写在绑定上，不写进码值集。它与 `code_map` 并存：`code_map` 是写死在目录里、本表特有的码值含义。
所绑属性有 `code_set` 时，它应出现在 `code_sets` 里，否则警告（`binding_code_sets_miss_attribute`）：

```yaml
      - column: reason_cd
        to: attribute
        ref: attr:fee_waiver.reason
        code_sets: [code:waiver_reason, code:waiver_channel]
```

`code_sets_by` 写这个列表怎么读。`lookup` 与不写相同，即上面的查找顺序。`source` 表示写入这一列的每个来源或分支
（一个 UNION 分支，或写这张表的几条语句之一）各用其中一个码值集、用自己的：顺序没有含义，一个值不会再去第二个码值集里查。
页面与查询这时写「按来源分别查 A、B」，不写「先查 A，查不到查 B」；哪个分支用哪个，需要时写在 `derivation`。
`code_sets_by` 必须配 `code_sets`，`source` 至少要两个码值集（只有一个时两种读法相同），否则报 `binding_code_sets_by`。
`build` 不输出 `lookup`。它不改别的：`binding_code_sets_miss_attribute` 与 `holds` 对两种读法一视同仁。

```yaml
      - column: reason_label           # branch 1: CASE over source A's codes; branch 2: over source B's
        to: attribute
        ref: attr:fee_waiver.reason
        code_sets: [code:waiver_reason, code:waiver_channel]
        code_sets_by: source
        holds: [meaning, code]
```

`holds` 写这一列的值是那些码值集（绑定的 `code_sets`；没写时是所绑属性的 `code_set`）的哪种形式：
`code`（码）、`meaning`（含义）或 `key`（码值表的 `key_column`，代理键），按约定翻译后的形式在前、
原码在后。不写等于 `[code]`，上面所有列都是这样读的；写 `[code]` 构建出的文档与不写相同。多于一项时，本列的一个值是其中之一：
可能因为查找落空，也可能因为表的不同来源写法不同（码值集本身是按顺序查还是按来源各查各的，由 `code_sets_by` 说）；
哪个来源写哪种形式不进结构，要说就写 `derivation`。
`lang` 写存下的含义是哪种语言（只能与 `meaning` 同用；码值集有 `lookup` 时应是其某个 `meaning_columns[].lang`）。
`code_sets` 的顺序与 `holds` 的顺序互不相干：`code_sets: [A, B], holds: [key, code]` 即「A 的代理键，A 查不到用 B 的，都查不到存原码」。
列由几个来源写入、各来源写不同形式时（如一个分支存代理键、另一个分支存原码）同样写 `[key, code]`；这时 `holds` 的顺序
只是约定，不表示先后，也不是回退顺序，哪个分支写哪种形式写进 `derivation`：

```yaml
      - column: reason_key             # branch 1: the dictionary's dict_key; branch 2: the raw code
        to: attribute
        ref: attr:fee_waiver.reason
        code_sets: [code:waiver_reason]
        holds: [key, code]
```

```yaml
      - column: reason_desc            # coalesce(d.code_desc, t.reason_cd)
        to: attribute
        ref: attr:fee_waiver.reason
        holds: [meaning, code]
        lang: zh
```

码值集的 `value` 永远是码——码值表（或 SQL 里的内联字典）按它键的那个值；内联字典按上文写成 `values` 时，
`value` 写源码、`meaning` 写翻译后的标签——即使列里存的是翻译后的含义或代理键：
那是列的事，在每个这样的列上写 `holds`；一列按序查多个码值集时，`code_sets` 写在**这一列**上，与 SQL 的查找顺序一致
（含义列、代理键列与码列各写各的）。边界情况：

- 一列由几个来源写入（几个 UNION 分支，或写这张表的几条语句）、各来源用自己的码值集：`code_sets` 全列上，
  再写 `code_sets_by: source`；页面与查询读成「按来源分别查 A、B」。只有真回退（每一行都先查 A、查不到查 B）才不写这个键。
- 同一属性按来源拆成几个码值集时，属性不写 `code_set`；各列在 `code_sets` 写本来源的码值集，属性的码就是它们的全部
  （见「属性」一节的规则）。这时 `holds` 含 `meaning` 或 `key` 的列必须写自己的 `code_sets`，否则报 `binding_holds_code_set`。
- 属性没有任何码值集（自身不写 `code_set`，绑到它的列也都不写 `code_sets`；字典没被关联、码值未知）时，随记录存名称的列
  也写 `holds: [meaning]`（加 `lang`），与码列区分开。只要有一列给这个属性带了码值集，这一列就必须写自己的 `code_sets`；
  `key` 总要有码值集。
- CASE 的某个分支（如 ELSE）没有源码：不编码，规则写进 `derivation`（需要时也写进码值集的 `definition`）。
- 只列 `values` 的码值集没有代理键列，`holds: [key]` 的列必然报 `binding_key_without_key_column`（目录翻不了这个键）；
  `[key]` 仍是对的写法。
- 查码值表只为翻译的列是码列，绑成 `attribute`；`foreign_identifier` 上也允许写 `code_sets`（`holds` 此时必须配 `code_sets`），
  只在查询与 `code_sets.md` 里显示，`identifiers.md` 不显示。
- 重编码（`Y/N` → `1/0`、码映射成另一套码、经映射表两步得到目标码）：列存目标码值集的码，不写 `holds`，映射写进 `derivation`。

示例里的借据表有两种以前表达不了的列。`customer_gender_cd` 是客户的性别，冗余在借据行上、紧挨着客户号：
它绑定为 `foreign_attribute`，`via: customer_id` 说明它说的是哪个客户。`orig_loan_no` 是续借借据所续的原借据号，
即同一概念的另一个实例：它绑定为 `foreign_identifier` 并指向借据自己的标识符，这只在目录登记了从借据到借据的关系时才允许：

```yaml
relations:
  - id: rel:loan_renews_loan
    kind: association
    from: concept:loan
    to: concept:loan
    name: renews
    inverse_name: is renewed by
    cardinality: {from: "0..1", to: "0..1"}
```

一个概念可以有多条自关联（直接的一层、隔一层的两层……），各有自己的列。这时每个自关联列都要写
`relation` 指明它实现哪一条，否则页面、查询与 JOIN 证据会把它归给该概念的每一条自关联（并警告
`self_reference_relation_unnamed`）。只有一条自关联时可以不写，行为不变：

```yaml
      - {column: orig_loan_no, to: foreign_identifier, ref: id:loan_no, relation: rel:loan_renews_loan}
```

`relation` 也可以写在指向别的概念的 `foreign_identifier` 上（两个概念之间有多条关系时说清是哪一条），
包括事件参与者派生的 `rel:<事件 slug>.<role_name>`；它只接受这样的关系：一端是本表的概念（角色视图含承担者），
另一端是 `ref` 所标识的概念（或以它为承担者的角色）；自关联列只接受本概念到自己的关系。

## 校验

```bash
scope-lineage catalog validate examples/catalog-demo
scope-lineage catalog validate examples/catalog-demo --json
```

校验分两段。**结构**：每个文件按它的 JSON Schema 校验（随包提供，
`scope_lineage/schemas/catalog-*.schema.json`，每类文件一个；未知键是错误，拼错的键不会被放过）。
**引用与警告**只在结构干净之后才跑：一个坏文件会让它里面的对象从索引里消失，
否则每个指向它们的引用都会被报成"不存在"。

退出码：`0` 有效（允许警告），`1` 有错误，`2` 目录读不了（目录不存在、缺清单、有 YAML 但没装 PyYAML）。

### 错误

| 规则 | 哪里不对 |
| --- | --- |
| `parse_error` | 文件不是合法的 YAML / JSON |
| `schema` | 文件不符合它的 schema；报告里给出路径，例如 `concepts[0].kind` |
| `duplicate_id` | 同一个 id 声明了两次（包括手写关系的 id 与派生参与关系的 id 相同） |
| `id_prefix` | 前缀与对象类型不一致，或属性 id 不在所属概念的 slug 下 |
| `identifier_identifies` | `identifies` 不是实体或事件 |
| `identifier_scope` | `scope.per` 里有一项不是概念 |
| `identifier_state` | `arises_when.state` 指向的概念没有状态，或没有这个状态值 |
| `identifier_maps_to` | `maps_to` 的目标不是标识符 |
| `concept_domain` | `domain` 不是业务域 |
| `concept_identifier` | `identifiers` 里有一项不是标识符 |
| `primary_identifier` | `primary_identifier` 不在该概念的 `identifiers` 里 |
| `role_player` | 角色的 `player` 不是实体 |
| `role_context` | 角色的 `context` 不是业务域 |
| `event_participant` | 参与者不是实体或角色 |
| `duplicate_role_name` | 同一事件的两个参与者用了同一个 `role_name` |
| `event_occurred_at` | `occurred_at` 不是该事件自己的属性 |
| `state_attribute` | `states.attribute` 不是该实体自己的属性 |
| `state_event` | 迁移的 `event` 不是事件 |
| `state_value` | 迁移的 `from` / `to` 不在状态值里 |
| `attribute_code_set` | 属性的 `code_set` 不是码值集 |
| `duplicate_code_value` | 码值集里同一个值出现两次 |
| `relation_endpoint` | 关系的 `from` / `to` 不是概念 |
| `constraint_on` | `on` 不是概念、属性、关系或标识符 |
| `term_refers_to` | `refers_to` 不存在 |
| `representation_concept` | 表现的 `concept` 不是概念 |
| `representation_grain` | 粒度里有一项不是标识符 |
| `duplicate_table` | 同一张表有两个表现（表名不分大小写） |
| `duplicate_column` | 同一个表现里一列绑定了两次 |
| `binding_attribute` | 该属性不属于所表现的概念（角色视图：也不属于其承担者） |
| `binding_identifier` | 该标识符不属于所表现的概念（角色视图：也不属于其承担者） |
| `binding_foreign_identifier` | `ref` 根本不是标识符（或不存在） |
| `self_reference_without_relation` | 该标识符属于所表现概念自己，但目录里没有两端都是该概念的关系 |
| `binding_relation` | 绑定的 `relation` 不是关系（或不存在）；两端不是「本表的概念」与「`ref` 所标识的概念」；或该列是自关联列而关系不是本概念到自己的 |
| `binding_foreign_attribute` | `ref` 不是属性；或属于所表现概念自己（角色视图：或其承担者），而 `via` 那一列不是指向该属性所属概念另一条记录的 `foreign_identifier`——本行自己的属性应绑定为 `attribute` |
| `binding_foreign_attribute_via` | `via` 不是本表的列，该列不是 `foreign_identifier`，或它指向的标识符不属于该属性的概念 |
| `binding_code_set` | 绑定的 `code_sets` 里有一项不是码值集 |
| `binding_code_sets_by` | 绑定写了 `code_sets_by` 却没写 `code_sets`，或 `code_sets_by: source` 而码值集少于两个 |
| `binding_holds_code_set` | 绑定的 `holds` 含 `meaning` 或 `key`，而绑定没写 `code_sets`、所绑属性也没有 `code_set`——不属于任何码值集的含义或代理键。例外：只含 `meaning`、且所绑属性按「属性」一节的规则没有任何码值集时不报 |
| `binding_lang` | 绑定写了 `lang`，其 `holds` 却不含 `meaning` |

"标识符属于某概念"指：概念在 `identifiers` 里列了它，或标识符的 `identifies` 指向该概念。
因此子类型可以列出父类型的标识符（示例里分期借据列了 `id:loan_no`）。

### 警告

| 规则 | 含义 |
| --- | --- |
| `drafted_ratio` | 还有多少对象是 `drafted`——未经确认的内容不应当作定论 |
| `concept_without_definition` | 概念没有定义 |
| `relation_without_name` | 关系没有动词 |
| `empty_code_set` | 码值集没有任何取值，也没有 `lookup` |
| `binding_code_sets_miss_attribute` | 绑定写了 `code_sets`，所绑属性的 `code_set` 却不在其中 |
| `binding_key_without_key_column` | 绑定的 `holds` 含 `key`，其码值集却没有一个带 `key_column` 的 `lookup`——目录翻不了这个代理键 |
| `binding_lang_unknown` | 绑定的 `lang` 不是其码值集 `lookup` 里任何含义列的语言（只列取值的码值集不查） |
| `unmapped_binding` | 某列绑定为 `to: unmapped` |
| `self_reference_relation_unnamed` | 自关联列没写 `relation`，而该概念有两条或更多自关联——说不清它实现哪一条，会被归给每一条 |
| `unknown_file` | 布局里没有的文件；已忽略 |

### 报告

文本形式每条发现一行：`error` / `warning`、规则、文件、对象与说明。`--json` 输出同样的内容，
格式为 `catalog-report/1`：

```json
{
  "doc_format": "catalog-report/1",
  "catalog": "demo-lending",
  "ok": true,
  "references_checked": true,
  "errors": [],
  "warnings": [
    {
      "rule": "unmapped_binding",
      "file": "mapping/party.yaml",
      "at": "demo_dwd.dwd_party_customer_ext_df.ext_json",
      "message": "column not yet bound to anything in the concept layer"
    }
  ],
  "counts": {
    "domains": 3,
    "concepts": 10,
    "concepts_by_kind": {"entity": 5, "event": 4, "role": 1},
    "representations": 9,
    "status": {"drafted": 20, "confirmed": 30, "deprecated": 0}
  }
}
```

（这里的 `counts` 有删节；它还统计标识符、码值集、属性、关系、约束、术语与绑定。）

## 构建：`ontology-json/3`

```bash
scope-lineage catalog build examples/catalog-demo --out out/
```

`build` 先校验，有任何错误就**什么也不写**。否则写出 `out/ontology.json`，其 schema 随包提供，
为 `scope_lineage/schemas/ontology-v3.schema.json`。写出前，`build` 会拿这份 schema 把生成的文档（连同
`--lineage/--tables` 挂上的证据）再核对一遍；不符合时逐条报出路径、什么也不写、退出码 `1`——这说明
构建器与 schema 不一致，是 scope-lineage 的缺陷，不是目录写错了：

```json
{
  "doc_format": "ontology-json/3",
  "catalog": {"name": "demo-lending", "description": "...", "format": "catalog-yaml/1"},
  "counts": {"domains": 3, "concepts": 10, "relations": 12, "derived_relations": 7},
  "domains": [],
  "identifiers": [],
  "code_sets": [],
  "concepts": [],
  "relations": [
    {
      "id": "rel:repayment.loan",
      "kind": "participation",
      "from": "concept:repayment",
      "to": "concept:loan",
      "name": "loan",
      "cardinality": {"from": "0..*", "to": "1..*"},
      "derived_from": {"event": "concept:repayment", "role_name": "loan"},
      "status": "confirmed",
      "source": "sql",
      "evidence": []
    }
  ],
  "constraints": [],
  "terms": [],
  "representations": []
}
```

（列表有删节。）"规范化"指：

- 每个对象都有 `status`、`source`（未知为 `null`）与 `evidence`；属性与绑定继承所属概念 / 表现的；
- 每类对象的键按固定顺序输出；码值与状态值一律为文字，每个码值都带布尔 `unconfirmed`（标了
  `unconfirmed: true`，或含义为空、以「待确认」开头）；写成 `1` 的基数端输出为 `"1"`；
  文字形式的 `arises_when` 变成 `{condition}`；
- 表名一律小写（表现的 `table` 与 `replaced_by`、标识符拼写的 `table`、`maps_to` 的 `via`、码值集
  `lookup` 的 `table`）：Hive 表名
  不分大小写，血缘契约里的表名都是小写，这样证据合并与查询才对得上；
- 顶层列表排序——按 `id`，术语按词再按指向，表现按表名——所以把对象挪到别的文件不改变输出。
  对象内部的列表（属性、状态值、绑定）保持作者的顺序；
- 绑定原样带出 `via` 与 `relation`；指向本概念自己标识符的 `foreign_identifier` 带 `self_reference: true`；
  `relation` 是可选的附加字段，没写它的目录输出不变；
- 码值集的 `lookup` 按上表的键序带出（`filter` 按列名排序，字面量一律为文字），绑定的 `code_sets` 按作者的顺序带出。
  这两个字段是可选的附加字段，`doc_format` 仍是 `ontology-json/3`；没写它们的目录，输出与以前逐字节相同；
- 绑定的 `code_sets_by`、`holds`、`lang` 原样带出，跟在 `code_sets` 之后；`code_sets_by: lookup` 与 `holds: [code]` 不输出（与不写同义），
  所以没写它们的目录输出与以前逐字节相同；
- 每个事件参与者变成一条 `participation` 关系 `rel:<事件 slug>.<role_name>`，从事件指向参与者，
  基数为 `{from: "0..*", to: "1"}`（`one`）或 `"1..*"`（`many`），带 `derived_from` 以及事件的
  status 与 source。这样的 id 不能再手写一次。

## 证据：`--lineage` 与 `--tables`

目录写的是人的判断；血缘语料和它的表卡写的是数仓实际在做什么。`build` 可以同时读两者，把它们
显示的事实放在目录旁边：

```bash
scope-lineage parse --input-dir examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/lineage
scope-lineage tables --lineage out/lineage --out out/tables
scope-lineage catalog build examples/catalog-demo --out out/ \
  --lineage out/lineage --tables out/tables/tables.json
```

[`examples/catalog-demo-corpus/`](../../examples/catalog-demo-corpus/) 里是八个虚构的调度任务，
读写示例目录里的表。证据写进 `ontology.json` 顶层的一个 `evidence` 块，按目录自己的名字作键。
**目录对象一个都不改**；两个参数都不给时根本没有 `evidence` 键，文档与原来逐字节相同。

| 位置 | 键 | 来自 | 含义 |
| --- | --- | --- | --- |
| `representations["库.表"]` | `producing_tasks` | `--lineage` | 写这张表的语句所属的任务 |
| `representations["库.表"]` | `refresh` | `--lineage` | 这些任务的调度周期（或 cron） |
| `representations["库.表"]` | `upstream_tables` / `downstream_tables` | `--lineage` | 表级血缘一跳：写它的任务读了什么，读它的任务写了什么 |
| `representations["库.表"]` | `grain_proof` | `--lineage` | 所有生产语句里证据最强的粒度：`confidence`（`proven` / `candidate` / `none`）、`keys`、`basis`、`task` |
| `representations["库.表"]` | `conflicts` | `--lineage` | `grain_not_proven`（目录声明 `proven`，血缘证明不了）或 `grain_mismatch`（两边都已证明，列不同） |
| `representations["库.表"]` | `table_comment` | `--tables` | 表卡上的表注释 |
| `representations["库.表"]` | `declared_columns` / `used_columns` | `--tables` | 元数据声明了几列、语料用到了几列 |
| `bindings["库.表.列"]` | `sources` / `expression` | `--lineage` | 上游物理列与最终表达式（最多 200 个字符），仅当绑定没有手写 `derivation` 时补充 |
| `bindings["库.表.列"]` | `declared_only` | `--tables` | 元数据里有这一列，语料里没有任何任务碰过它 |
| `code_sets["code:..."]` | `table` / `missing_columns` | `--tables` | 码值集 `lookup` 所指的表有表卡、表卡却没声明其中某些列时：哪些列（只在有这样的列时出现；`build` 同时在 stderr 打一行 `lookup_column_missing` 警告） |
| `relations["rel:..."]` | `joins` | `--lineage` | 连接两个概念表现表、且两侧连接列绑定到同一个它们的标识符的 JOIN：`count` 与至多三个 `samples` |
| `relations["rel:..."]` | `source_joins` | `--lineage` | 生产任务内的 JOIN：写某一端表现表的语句里、为填这张表的外键列而做的 JOIN，`count` 与至多三个 `samples`（多一个 `column`：被填的外键列）；与 `joins` 分开计，只在有这样的 JOIN 时出现 |

```json
{
  "inputs": {
    "lineage": {"tasks": 8, "statements": 8, "representations_matched": 7, "relations_checked": 7},
    "tables": {"cards": 15, "representations_matched": 7}
  },
  "representations": {
    "demo_dwd.dwd_lending_loan_df": {
      "producing_tasks": ["dwd_lending_loan_daily"],
      "refresh": ["day"],
      "upstream_tables": ["demo_ods.ods_loan_contract_df", "demo_ods.ods_loan_penalty_di"],
      "downstream_tables": ["demo_ads.ads_collection_overdue_loan_df", "demo_dwd.dwd_lending_borrower_df"],
      "grain_proof": {"confidence": "candidate", "keys": ["loan_no"], "basis": "driving_table_rows", "task": "dwd_lending_loan_daily"},
      "conflicts": [{"rule": "grain_not_proven", "declared_source": "proven", "confidence": "candidate"}],
      "table_comment": "Loan snapshot",
      "declared_columns": 8,
      "used_columns": 8
    }
  },
  "bindings": {
    "demo_dwd.dwd_lending_loan_df.principal_amt": {"sources": ["demo_ods.ods_loan_contract_df.principal"], "expression": "`l`.`principal`"},
    "demo_dwd.dwd_lending_loan_status_his.loan_status": {"declared_only": true}
  },
  "relations": {
    "rel:borrower_owes_loan": {
      "joins": {"count": 1, "samples": [{"task": "ads_collection_overdue_borrower_daily", "statement_id": "stmt:001", "on": "demo_dwd.dwd_lending_borrower_df.customer_id = demo_dwd.dwd_lending_loan_df.customer_id"}]}
    },
    "rel:repayment.loan": {
      "joins": {"count": 1, "samples": [{"task": "ads_collection_overdue_borrower_daily", "statement_id": "stmt:001", "on": "demo_dwd.dwd_lending_loan_df.loan_no = demo_dwd.dwd_lending_repayment_di.loan_no"}]},
      "source_joins": {"count": 1, "samples": [{"task": "dwd_lending_repayment_daily", "statement_id": "stmt:001", "column": "demo_dwd.dwd_lending_repayment_di.loan_no", "on": "demo_ods.ods_repay_txn_di.loan_no = demo_dwd.dwd_lending_loan_df.loan_no"}]}
    }
  }
}
```

（有删节。）证据怎样对上目录：

- **表**按最后两段匹配：示例里的借据任务写的是 `spark_catalog.demo_dwd.dwd_lending_loan_df`，
  它落到表现 `demo_dwd.dwd_lending_loan_df` 上。语料没提到的表没有条目。
- **粒度**：比较前两边都去掉分区列，所以目录粒度里写了 `stat_date`、而语句只写一个 `stat_date`
  分区时不算矛盾。声明粒度里某个标识符在本表没有绑定列时，不做比较。
- **关系**只在两端概念都有表现表时统计；统计过但没有 JOIN 支持的是 `count: 0`，无法统计的没有 `joins`（没有 `source_joins` 时也就没有条目）。
  一次 JOIN 计数的条件是：两侧分别是两个概念的表现表，且同一对连接列的**两侧**都绑定（为
  `identifier` 或 `foreign_identifier`）到同一个标识符，而这个标识符标识关系的某一端：关系两端的概念自己，
  或角色的表现表所绑定的承担者标识符。客户号对上手机号，或两个客户号把一通电话连到一个联系人，都不是
  「电话—联系人」关系的样例。participation 关系同样统计。
  两端是同一概念的关系只数至少一侧连接列带 `self_reference` 且实现这条关系（`relation` 指向它，或没写 `relation`）的 JOIN
  （表自连接也算）：同一实例出现在两张表里不说明关系。
- **生产任务内的 JOIN**（`source_joins`）是另一种证据，**不计入** `joins`：`joins` 回答「下游是否这样连两端的表」，
  `source_joins` 回答「生产任务是否这样取外键」。一次计数的条件是：语句写入某一端的表现表；这张表有一列绑定为
  `foreign_identifier`、指向另一端的标识符 K；JOIN 一侧的连接列是这一列的**血缘来源列**，另一侧的连接列持有 K
  （绑定到 K，或是 K 的已登记拼写）。示例里还款任务用来源表的 `loan_no` 连借据表的 `loan_no`，
  填的正是还款表指向借据的外键，所以 `rel:repayment.loan` 得到 1 次。只需被写的那一端有表现表，
  所以一端没有表现表的关系也可能有这一项（此时条目里没有 `joins`，也不计入 `relations_checked`）。
  `identifier` 绑定不作锚（表自己的键不指向另一端）；一张来源表带着几个概念的标识拼写，并不说明它表现哪个概念，
  不据此判断。两端是同一概念时只认带 `self_reference` 的列；绑定写了 `relation` 时只算给它指向的那条关系。
- `build` 的摘要行把两种分开写：`N of M relation(s) backed by a JOIN between catalog tables`（`joins`）
  与 `K relation(s) by a JOIN inside a producing task`（`source_joins`）。
- 语料用 `tables` 与 `ontology` 同一套读取器读；JOIN 的一侧是 CTE 时，顺着它追到提供行的物理表。
  连接列是 ON 子句比较的那个值所在的物理列：改名的列（`caller_phone AS dialed_no`）按物理列名报告，
  只由一列算出的键（`TRIM`、`CAST`、`COALESCE(x, '')`）报告为那一列。由多列算出的键
  （`IF(a.id = '' AND b.phone IS NOT NULL, b.id, a.id)`）不是其中任何一列——只在条件里读到的列绝不会被报告为键——
  它以 ON 子句写的列名、落在该 ON 引用所指作用域的表上。

## 页面：`catalog render`

```bash
scope-lineage catalog render out/ontology.json --out out/pages \
  [--semantics out/pages/semantics]
```

`render` 只读构建出的文档，从不回读目录文件夹，所以页面展示的就是构建结果（含证据）。标题用中文，
与其他渲染文档一致；名称用目录自己的。

`--semantics` 指向 `semantic render` 写出的表语义页目录（`<db.table>.md`）。给了它，概念页里列出的每张表
（一页纸概览的「数据在哪 / 记录在」与附录 A2 数据清单）都链到这张表的表语义页，链接相对 `concepts/` 计算；
目录里没有页面的表照旧不加链接。不给时页面逐字节不变。表语义页反过来用 `semantic render --ontology`
链回概念页，见[表语义](table-semantics.md)；码值集 `lookup` 所指的码值表，其表语义页开头写「本表是码值集…的码值来源」，
链到 `code_sets.md`。

两个方向都要链时顺序固定：`--semantics` 的目录必须已经存在（不存在时退出 2），而 `semantic render --ontology`
要读构建好的 `ontology.json`，所以先构建、再渲染表语义页、最后渲染概念页：

```bash
scope-lineage catalog build <catalog-dir> --out out/catalog
scope-lineage semantic render <documents> --out out/pages/semantics \
  --ontology out/catalog/ontology.json
scope-lineage catalog render out/catalog/ontology.json --out out/pages \
  --semantics out/pages/semantics
```

| 文件 | 内容 |
| --- | --- |
| `index.md` | 按域列出概念（名称、种类、定义、表现表数、状态）、标识符、码值集（及码值所在的表）、治理缺口汇总、记录范围汇总 |
| `concepts/<slug>.md` | 每个概念一页（`concept:fee_waiver` → `fee_waiver.md`）：先是一页纸概览，再是附录七节 |
| `identifiers.md` | 每个标识符的完整说明，及绑定到它的列 |
| `code_sets.md` | 每个码值集：取值，或去哪张表、按什么条件查（`lookup`）；用它的属性（按「属性」一节的规则）；按 `code_sets` 查它的列（行名「查它的列」）、各列怎么查（按顺序，或按来源各查各的：`code_sets_by`）、各列存什么（`holds`） |
| `governance.md` | 所有概念的全部缺口，每类缺口一个列表；含义待确认的码值；另按表列出冗余属性列（信息项，不算缺口；同一概念另一条记录的属性同样标出） |
| `scopes.md` | 每张表的记录范围按过滤类别归组；没写记录范围的表；引用了表的业务规则与值域约束 |

概念页开头一行写种类、所属域和本页草拟占比，接着是 **一页纸概览**：用中文白话、只写名称
（不出现 `id:…`、`attr:…` 这类编号，不出现英文枚举词，不放多于两列的表），回答打开页面的人最先问的几件事。
内容为空的行不写；已确认的条目后标 ✓：

| 行 | 内容 |
| --- | --- |
| 是什么 | 概念的定义 |
| 怎么认出来 | 每个标识符一条：名称、何时产生（没写 `arises_when` 时是「一开始就有」，写了就是条件及其状态）、唯一范围（「全局唯一」或「每个客户×App 一个」）、是否主标识 |
| 状态 | 状态值按顺序用 → 连起来，推动迁移的事件写在箭头上（`未认证 —实名认证→ 已认证`）；不相邻值之间的迁移附在括号里 |
| 数据在哪 | 实体的核心表与扩展表（角色是角色视图表），各带表注释或备注首行（≤30 字）；已废弃的表写「已废弃，改用 …」；再写另有几张表带本概念的标识、分布在几个域（见附录 A3）。事件这一行叫「记录在」，列事件明细表 |
| 拥有的 | 本概念是整体的组成关系：「动词 对端名称」 |
| 关联的 | 其余关联、组成、泛化关系，从本概念一侧读：本概念是关系的 `to` 端时用 `inverse_name`，没有反向名时写整句；有 `inverse_name` 的自关联两个方向都写（「<name> / <inverse_name> <概念名>」） |
| 参与的事件 | 本概念参与的事件，按事件所属域分组 |
| 扮演的角色 | 以本概念为承担者的角色，带成立条件（≤30 字） |
| 参与者 / 发生时间 | 仅事件：每个参与者「角色名 → 概念名」；发生时间属性的名称 |
| 承担者 / 成立条件 | 仅角色 |
| 要注意 | 至多 5 条：作用于本概念、其属性或标识符，强度为硬或种类为业务规则的约束，已确认的在前，写表达式（≤60 字，超出用 … 截断） |

概览之后是 **附录**，A1–A7 七节回答打开它的人要问的七件事（A1 的表
有一行「编号」写出概念 id）：

| 节 | 内容 |
| --- | --- |
| A1 定义与身份 | 定义、种类、状态、同义词；标识符（产生条件、唯一范围、物理拼写、对照）；状态机（值、迁移事件）；事件的参与者，角色的承担者、语境与成立条件 |
| A2 数据清单 | 按表现类型分组的表（核心、扩展、从属、事件明细、状态历史、标识映射、角色视图、汇总、中间）：说明（表卡的表注释、表现的 `notes`）、粒度（标识符、来源，以及血缘证明了什么）、时间语义及取数方式（快照「按单个 dt 分区取数」，拉链按有效期窗口）、更新频率、记录范围、生产任务、废弃及替代；每张表的血缘一跳 |
| A3 带本概念标识的表 | 所有概念的表里，把本概念的某个标识符绑定为 `identifier` 或 `foreign_identifier` 的每一列：表、表的概念、列、标识符、方式（自关联单独标出）。没有自己表现表的概念也能看到它从哪些表关联进来；角色没有自己的标识符，指向承担者 |
| A4 属性 | 按类别（描述、状态、度量、时间）：定义、类型与单位、码值（值=含义；码值在码值表里的写出查找方式；有几个码值集时逐个前缀集名，「A：1=…；B：0=…」）、承载它的每个表列（含码值映射；列按 `code_sets` 查码值集时写「先查 A，查不到查 B」，`code_sets_by: source` 的列写「按来源分别查 A、B」；写了 `holds` 的列再写它存什么，如「存含义（zh）或码」，跟在码值集之后写成「（码值：查 A；存代理键）」；别的表冗余存放的标为「冗余（经 via 列）」，同一概念另一条记录的标为「冗余（同一<概念>的另一条记录，经 via 列）」）、加工口径 |
| A5 关系 | 从本概念一侧读的关联、组成、泛化，带基数与 JOIN 次数（自关联的对端写「本概念」及承载它的列——写了 `relation` 的列只列在它指向的那条下，没写的列在每条自关联下——有 `inverse_name` 时读法两个方向都写）；有生产任务内的 JOIN（`source_joins`）时，另写「生产任务内连接 N 次（如 …，填 <外键列>）」，与 JOIN 次数分开；JOIN 次数为 0 或无法统计时，补上目录自己的依据：同表携带两端的表（表现某一端或绑定它的标识符；角色用承担者的标识符；自关联只看实现它的自关联列）与关系的 `evidence`；参与的事件（本概念的角色、事件的表现表数）；本概念承担的角色，或在角色页上反向链到承担者 |
| A6 约束 | 作用于概念本身、其属性、标识符与关系的约束，按种类列出，带强度与状态 |
| A7 治理缺口 | 草拟占比、未绑定列、没有落表的属性、缺码值的状态/码值类属性、有没有表现表；有证据时还有证据与目录矛盾、没人用的绑定列、没有 JOIN 支持的关系 |

凡是来自语料的内容都标「血缘」；没有证据时这些格子写「—」，不猜。

`scopes.md` 把每条 `scope` 按关键词归入过滤类别；一行说到几类时每类都列，一类都不像的归「其他」。
中文关键词任意位置命中，英文关键词按整词命中（下划线分词，所以 `is_deleted` 算 `deleted`）：

| 类别 | kind | 关键词（节选） |
| --- | --- | --- |
| 有效记录/记录状态 | `validity` | 有效、生效、状态、`valid`、`active`、`status` |
| 删除/注销 | `deletion` | 删除、注销、作废、`deleted`、`cancelled`、`void` |
| 去重/最新 | `dedup` | 去重、最新、`distinct`、`latest`、`row_number`、`rn` |
| 分区/快照日期 | `partition` | 分区、快照、`dt`、`ds`、`partition`、`snapshot` |
| 其他 | `other` | 以上都不像 |

同一页还列出没写 `scope` 的表，以及种类为 `business_rule` / `value_domain`、在 `evidence` 或表达式里引用了某张表现表的约束。

## 查询：`catalog query`

```bash
scope-lineage catalog query out/ontology.json concept 用户
scope-lineage catalog query out/ontology.json table spark_catalog.demo_dwd.dwd_lending_loan_df --json
```

| kind | term | 回答 |
| --- | --- | --- |
| `concept` | id、名称、同义词或术语 | 身份、标识符、属性、状态、表现表、该读的页面，以及概念页的一页纸概览（`overview`，字段与页面相同） |
| `table` | `库.表`（忽略 catalog 前缀） | 它承载的概念、时间语义与取数方式（`usage`）、表注释与 `notes`、记录范围、引用它的业务规则与值域约束（`constraints`），以及每个绑定列指向什么，带证据；冗余列写 `→ 冗余属性 <属性> of <概念>（经 <via>）`，自关联列写出关系；码值表（码值集 `lookup` 所指的表）回答它装着哪些码值集及各自的查找方式（`code_sets`），表同时有表现时表现答案多一个 `code_sets`，退出码 `0` |
| `column` | `库.表.列` | 它承载的属性或标识符及其概念（冗余属性带 `via`，是同一概念另一条记录的属性时另带 `other_instance: true`；写了 `code_sets` 的列按顺序带出码值集及查找方式，`code_sets_by` 为 `source` 时带出这个键（文字读成「按来源分别查 A、B」）；写了 `holds` 的列说出它存什么，如「存含义（zh）或码」，并带 `holds`、`lang`）——或它是码值表的哪种列（码、含义、代理键、筛选、有效期，`role`）、服务哪些码值集——或它是哪个标识符的物理拼写；自关联列带 `self_relations`（它实现的自关联：写了 `relation` 的只有那一条，没写的是全部） |
| `identifier` | id、名称或物理拼写 | 识别什么、唯一范围与拼写、绑定到它的列 |
| `attribute` | id、名称或术语 | 所属概念、码值（码值集有 `lookup` 时 `code_set` 带上查找方式与表；属性自己没写 `code_set` 时答 `code_sets`，即各列写的码值集，每项同 `code_set` 的形状并带 `name`）、口径、每个表列 |
| `related` | 概念的 id、名称、同义词或术语 | 一跳邻居：从本概念一侧读的关系（有 `inverse_name` 的自关联两个方向都读）、事件、参与者、角色、承担者、表、带本概念标识的表（`carriers`）；每条关系与事件带 `carried_together`（同表携带两端的表）与 `evidence`，没有 JOIN 时文本里写出；有生产任务内的 JOIN 时另带 `source_joins`（次数），文本写「生产任务内连接 N 次」，与 `joins` 分开 |
| `carriers` | 概念的 id、名称、同义词或术语 | 所有概念的表里绑定了本概念标识符的列：表、表的概念、列、标识符、方式 |
| `scope` | 过滤类别（`validity`/有效记录、`deletion`/删除、`dedup`/去重、`partition`/分区、`other`/其他，类别名或其一半都行）或关键词 | 记录范围或所引约束说到它的表，各带这些行（与其类别）、约束与取数方式 |

名称精确匹配（忽略大小写与首尾空格），依次试 id、名称、同义词、术语；不猜。`table`、`column` 与按拼写查
`identifier` 时，表名和列名同样不分大小写。文本回答只有几行，
`concept` 先给出与概念页概览相同的「是什么 / 怎么认出来 / 数据在哪」（事件是「记录在」）：

```text
客户 concept:customer · 实体 · 客户与账户 · 已确认（owner）
  是什么：A person the shop has registered, whether or not they ever borrow.
  怎么认出来：客户号：一开始就有，全局唯一（主标识） ✓；认证客户号：assigned when the customer passes identity verification（进入「已认证」状态时），全局唯一
  数据在哪：demo_dwd.dwd_party_customer_info_df（Customer master, one row per …） ✓；demo_dwd.dwd_party_customer_ext_df；另有 4 张表带本概念的标识，分布在 2 个域
  标识符：客户号 id:customer_id（主）、认证客户号 id:verified_customer_no
  属性：性别、注册时间、认证状态
  状态：未认证、已认证
  表：demo_dwd.dwd_party_customer_ext_df（扩展）、demo_dwd.dwd_party_customer_info_df（核心）
  页面：concepts/customer.md
```

没有自己表现表的概念，用 `carriers` 找到从哪里关联它：

```text
带 渠道 concept:channel 标识的表（渠道编码 id:channel_code）
  - demo_dwd.dwd_party_account_map_df（应用账户）：channel_code → 外部标识符 渠道编码
  - demo_dws.dws_lending_loan_summary_1d（借据）：channel_code → 外部标识符 渠道编码
```

`--json` 输出 `{"query": {"kind", "term"}, "matches": [...]}`，给 Agent 用。退出码：`0` 有匹配，
`1` 没有匹配，`2` 文件读不了（不是 `ontology-json/3` 文档时也是 `1`）。

## 起草：`catalog digest` 与 `catalog merge`

已经给一批表写好[表语义](table-semantics.md)（`table-semantics/1`）时，目录可以从它们起草，而不用每次写临时脚本：

1. `catalog digest` 把表语义浓缩成起草材料，并对照现有目录标出还没覆盖的表和列；
2. 人或模型据此起草概念与关系（`concepts/`、`relations`、`identifiers` 文件）；片段不能新增概念、不能改已有
   标识符，所以各组要用的新概念（事件连同它的时间属性）、新标识符和已有标识符的新拼写都在这一步写好；
   一组的表会引用的别组概念的属性（如外部标识列旁边的名称列）也在这一步建好。片段只给本组概念新增属性：
   目录里缺的别组属性写进片段的 `notes`，先绑成本概念的属性，合并后再改成 `foreign_attribute`；
3. 把表分组，每组写一个片段（`catalog-fragment/1`）：属性、码值集、约束、术语、每张表的表现与列绑定；
4. `catalog merge` 把片段合并进目录的一份拷贝，报告冲突，自动校验，并给出覆盖报告；
5. `catalog build` / `catalog render` 后交 owner 审读。

Agent 技能里的完整流程与片段提示词见 `skills/scope-lineage/references/catalog-fragment-prompt.md`。

### `catalog-fragment/1`

一个片段是一组表的起草结果。每个条目的形状与它要落进的目录文件**完全相同**（schema 里的条目定义就是目录
schema 的拷贝，有测试保证两者一致），所以合并只搬运条目，不做转换。下表「合并到」一列只写文件名的主干：已有的文件
保持它原来的格式（`.yaml` / `.yml` / `.json`），新建的文件与清单 `catalog.*` 同一种格式（见下文 `catalog merge` 第 4 步）。

| 键 | 内容 | 合并到 |
| --- | --- | --- |
| `doc_format` | `catalog-fragment/1`（必需） | — |
| `group` | 组名，小写字母、数字、`_`、`-`（必需） | 新表现写进 `mapping/<group>.*` |
| `attributes` | `{"concept:<id>": [属性, ...]}`，形状同概念里的 `attributes` | 该概念所在的 `concepts/` 文件 |
| `code_sets` | 码值集，形状同 `code_sets` 文件里的条目（码值在码值表里时写 `lookup`；定义在任务内的 `VALUES` / `CASE` 字典写 `values`，`evidence` 写任务名，不写 `lookup`） | `code_sets.*` |
| `identifiers` | 标识符，形状同 `identifiers` 文件里的条目；只在确实缺时新增 | `identifiers.*` |
| `constraints` | 约束，形状同 `constraints` 文件里的条目；只写有证据的 | `constraints.*` |
| `terms` | 术语，形状同 `terms` 文件里的条目 | `terms.*` |
| `representations` | 表现与绑定，形状同 `mapping/` 文件里的条目 | `mapping/<group>.*` |
| `notes` | 给 owner 的问题或冲突，文字列表 | 只在合并报告里打印 |

示例 [`examples/catalog-fragments/disbursement.json`](../../examples/catalog-fragments/disbursement.json)
给演示目录补上放款表（下面是节选）：

```json
{
  "doc_format": "catalog-fragment/1",
  "group": "disbursement",
  "attributes": {
    "concept:disbursement": [
      {"id": "attr:disbursement.pay_method", "name": "放款方式", "definition": "How the money reached the borrower.", "category": "descriptive", "type": "string", "code_set": "code:pay_method"}
    ]
  },
  "code_sets": [
    {"id": "code:pay_method", "name": "放款方式", "values": [{"value": "BANK", "meaning": "bank transfer"}, {"value": "WALLET", "meaning": "in-app wallet"}]}
  ],
  "representations": [
    {
      "table": "demo_dwd.dwd_lending_disbursement_di",
      "concept": "concept:disbursement",
      "kind": "event_detail",
      "grain": {"identifiers": ["id:disbursement_txn_no"], "source": "inferred"},
      "time": "incremental",
      "table_status": "active",
      "bindings": [
        {"column": "disburse_txn_no", "to": "identifier", "ref": "id:disbursement_txn_no"},
        {"column": "pay_method", "to": "attribute", "ref": "attr:disbursement.pay_method"},
        {"column": "remark", "to": "unmapped"},
        {"column": "dt", "to": "technical"}
      ]
    }
  ],
  "notes": ["remark holds free text; is any of it a business attribute?"]
}
```

Schema 在 `scope_lineage/schemas/catalog-fragment.schema.json`。

### `catalog digest`

```bash
scope-lineage catalog digest out/semantics [--catalog examples/catalog-demo] \
  [--lineage out/lineage [--schema examples/metadata]] \
  [--only demo_dwd.dwd_party_customer_info_df ...] --out out/digest
```

读目录下每份合法的 `table-semantics/1` 文档（确认文件等工具自己的文档跳过；不合 schema 的文档跳过并在
stderr 说明），按表名排序写出 `digest.md` 与 `digest.json`（`catalog-digest/1`）。每张表一段：

- 一句话说明、文档写的概念与表现类型；
- 行含义、粒度列（及来源、是否唯一）、时间语义（`snapshot` / `incremental` / `zipper`）与取数方式、记录范围；
- 标识列、外部标识列、状态列、时间列、度量列、描述列（各带含义，有码值时带码值），技术列只列名；
- 由哪些表加工而来（带角色）、被哪些表读取；要注意的点（`watch`）与未回答的问题。

给 `--catalog` 时，开头多一段「目录覆盖」：没有表现的表，以及已有表现的表里没有绑定的列（表名忽略大小写与
catalog 前缀）；某个码值集 `lookup` 所指的表算「码值来源」（`code_set_sources`：表 → 码值集 id），不算没有表现的表；
每张表的段落末尾也标出它在目录里的情况。输出是确定的：同样的输入，逐字节相同。

给 `--lineage`（一个 `lineage.json`，或在其下递归查找的目录，与 `catalog build --lineage` 相同）时，每个列出的列
还会按写这张表的语句说明：它的值经过哪些被关联的输入读出、这些行按什么常量条件挑出——也就是写码值集
`lookup.filter`、绑定 `code_sets` 的顺序与绑定 `holds` 所需的事实，起草时不必为此回头读 SQL：

- `lookups`：值经过的被关联输入，按表达式读它们的顺序排列（`COALESCE(d1.x, d2.x, a.c)` 回退的参数顺序）。每项是
  `{table, where, reads, key, rule}`：`table` 中 `where` 每一列都等于其字符串字面量的行、读这些行的 `reads` 列、
  被关联输入一侧的物理关联列 `key`（一对键一项，按键对顺序；JOIN 比较的是表达式、说不出列时不写，不猜），
  以及血缘里这个 JOIN 的逻辑块 id；
- `fallback`：同一个值回退到的、不经查找的物理列（`COALESCE` 末尾的原码），只与 `lookups` 一起出现，且只列与某个
  查找同来源的；
- `lookups_by: "source"`：这一列由几个来源写入（几个 UNION 分支，或写这张表的几条语句），各来源分别读：每项
  `lookups` 带 `source`（一条语句写全部来源时是 UNION 分支的作用域 id，否则是 `<任务>/<语句>`，分支再拆时加
  `/<分支>`），只有同一来源内部的查找才有回退顺序。只有 UNION 上方没有把几个输入合成一个值的表达式时才按分支拆：
  主输入是 UNION CTE 的 `COALESCE` 仍是一次回退；被关联输入里的 UNION 就是那一个输入，不算来源。键名与目录的
  `code_sets_by: source` 对应；
- `other_sources`：与 `lookups_by` 一起出现，`{来源: [库.表.列]}`，是没有查找的来源直接存的物理列——不是回退。
  只把目标表自己的列原样带下来的来源，带的是别的来源写的值，不列出；
- `key_of`：本身没有 `lookups` 的列，是哪些读取的关联键，`{table, where, key, rule, read_by}`，`read_by` 是同表里经这个
  JOIN 读值的列；`read_by` 为空（`read by no column`）的是死关联或只用来过滤行，不是码值集的证据，起草时
  不为它建码值集——码值集只为有列读取的 `where` 组合建。顺序取这些列回退的顺序，不取 JOIN 书写顺序；两列回退顺序相反时保留 JOIN 顺序，并用
  `key_of_order: "unknown"` 标明。

什么算：只有经 JOIN 进入（或途经被关联的子查询 / CTE）的值才有条件；条件是与字符串字面量的单个等值比较，
写在 JOIN 的 `ON` 里、被关联子查询 / CTE 的 `WHERE` 里，或同一查询 `WHERE` 里限定被关联别名本身的位置。
数值（`rn = 1`）、`${…}` 参数、`IN` 列表与分区列上的比较都不算：分区的判定与材料包相同，给了 `--schema` 按其
分区列，否则按血缘的分区标记与 `dt`/`ds`/`pt`/`p_date` 名字规则。没有这种条件的 JOIN 只是补字段，不列出；
值来自内联 `VALUES` 列表或其他非表来源的也不列出。措辞是中性的——「读 <表> 中 <列> = '<字面量>' 的行」——
因为同样的形状挑出角色、语言或行版本的次数不比挑字典类型少。同时给 `--catalog` 时，表与 `where` 恰好等于某个
码值集 `lookup.table` 与 `lookup.filter` 的读取加上 `code_set: <id>`，`reads` 是该码值集的含义列或代理键列时
加上 `reads_as: "meaning"` / `"key"`。读取给出了 `key`、而 `key` 不含该码值集的 `lookup.code_column` 时——按存下的含义
反查回码——它不是这个码值集的翻译：不写 `code_set`，改写 `code_set_mismatch: {code_set, code_column}`（md 写
`code set <id> looks up by <列> (reverse lookup?)`）。没有 `key` 的读取照旧按表与 filter 打标签。

粒度列或 `identifier` 类别的列上的 `key_of` 项加上 `keyed_by: "row_identifier"`，读它的各列里同一次读取（规则与表
相同）的 `lookups` 项也加上：这个关联挑的是描述同一条记录的行——这个实体的属性行、这次通话的参与方——不是码值
翻译。读出的列是属性，不是码值集的证据。键是外部标识列的读取不带这个标记，仍可能是别的实体的属性行。

`key`、`lookups_by`、`source`、`other_sources`、`code_set_mismatch` 与 `keyed_by` 不改 `catalog-digest/1`；
两处含义收窄：`fallback` 只是同来源内的真回退，已知关联列时 `code_set` 要求关联列匹配。

```json
{
  "column": "c_desc",
  "meaning": "type description",
  "lookups": [
    {"table": "demo_dim.dim_code_dict", "where": {"code_type": "TypeA"}, "reads": "code_desc", "key": ["code_val"], "rule": "logic:ROOT:join:002", "code_set": "code:type_a", "reads_as": "meaning"},
    {"table": "demo_dim.dim_code_dict", "where": {"code_type": "TypeB"}, "reads": "code_desc", "key": ["code_val"], "rule": "logic:ROOT:join:001"}
  ],
  "fallback": ["demo_ods.ods_order_df.c"]
}
```

一个 UNION 分支查字典代理键、另一个分支存原码的列：

```json
{
  "column": "st_id",
  "meaning": "status key",
  "lookups_by": "source",
  "lookups": [
    {"table": "demo_dim.dim_code_dict", "where": {"code_type": "TypeOut"}, "reads": "dict_key", "key": ["code_val"], "rule": "logic:union:main:b01:join:001", "source": "union:main:b01"}
  ],
  "other_sources": {"union:main:b02": ["demo_ods.ods_order_b_df.st"]}
}
```

`digest.md` 在「Joined inputs read (from the lineage)」下给每个这样的列一行。血缘里没有任何语句写的表照常输出、
不加任何键，命令打印这样的表有几张。不给 `--lineage` 时输出与原来逐字节相同；它也不改血缘、材料包、表语义与
目录构建。

退出码：`0` 写出；`1` 没有合法文档、有文档被跳过（其余照常写出），`--only` 点名的表没有文档，或 `--lineage` 目录下没有
`lineage.json`；`2` 目录、`--catalog`、`--lineage` 或 `--schema` 读不了，或给了 `--schema` 却没给 `--lineage`。

### `catalog merge`

```bash
scope-lineage catalog merge examples/catalog-demo \
  examples/catalog-fragments/disbursement.json --out out/merged
scope-lineage catalog merge <catalog-dir> <group>.json ... --in-place
```

1. 先读所有片段并按 schema 检查；有一处不合就什么都不写。基础目录的文件读不了或不合 schema 时也不合并。
2. 把基础目录拷到 `--out`（新目录或空目录；隐藏文件不拷）。`--out` 等于基础目录会被拒绝，除非用
   `--in-place`；`--out` 在基础目录里面也会被拒绝。
3. 按命令行顺序合并片段。每个条目按键在整个目录和先合并的片段里找：属性、码值集、标识符、约束按 `id`，术语按
   `term` + `refers_to`，表现按 `table`。内容相同算「未变」；**同键内容不同是冲突**，列进报告，后来的那个不应用。
   属性挂到它的概念所在的文件；概念不存在是错误，其属性不应用；同一个属性 id 已挂在别的概念上也是冲突。
4. 只重写有变化的文件（YAML 用 YAML 1.2 布尔规则读、按安全方式写回；JSON 写回 JSON），没动的文件逐字节不变。
   目录里还没有、需要新建的文件（如 `constraints`、`mapping/<组>`）与 `catalog.*` 同一种格式：全 JSON 的目录新建 `.json`，
   合并全程不需要 PyYAML。
   被重写的 YAML 文件里的注释会丢失。
5. 在进程内对结果跑 `catalog validate`，打印错误与警告；最后打印覆盖报告：片段里的每张表有没有表现、
   列按绑定去向（`identifier`、`foreign_identifier`、`attribute`、`foreign_attribute`、`technical`、`unmapped`）
   各多少。

```text
Merged 1 fragment(s) into out/merged: added attribute=1, code_set=1, constraint=1, term=2, representation=1; 1 unchanged; 0 conflict(s), 0 unknown concept(s)
  files written: code_sets.yaml, concepts/lending.yaml, constraints.yaml, mapping/disbursement.yaml, terms.yaml
note    (disbursement) remark holds free text; is any of it a business attribute?
Catalog demo-lending (catalog-yaml/1): 0 error(s), 3 warning(s)
...
Coverage: 1 table(s) in the fragments, 1 with a representation, 1 unmapped column(s)
  demo_dwd.dwd_lending_disbursement_di  concept:disbursement  event_detail  8 column(s): identifier=1 foreign_identifier=2 attribute=3 technical=1 unmapped=1
```

| 退出码 | 含义 |
| --- | --- |
| `0` | 合并完成，结果校验没有错误（可以有警告） |
| `1` | 片段不合 schema、基础目录不合 schema（都不写任何东西）；或有冲突、未知概念、合并后校验有错误（已写出，便于就地查看） |
| `2` | 片段或基础目录读不了；`--out` 是基础目录（没有 `--in-place`）、在基础目录里面，或不是空目录 |

## 安全地写 YAML

- 目录按 YAML 1.2 的布尔规则读取：只有 `true` / `false` 是布尔，所以 `on:`（约束的键）以及
  `no`、`off` 这样的码值都保持为文字。
- 基数端（`"1"`）以及需要保留前导零的码值（`"01"`）请加引号。
- 不加引号的日期（`2026-01-31`）读成文字 `"2026-01-31"`。
