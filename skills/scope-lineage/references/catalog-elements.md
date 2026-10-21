<!-- 由 docs/zh-CN/ontology-catalog.md 的「元素」「起草」两节原样复制，供没有工具仓库（pip 安装）的运行读；tests/architecture/test_skill_bundle.py 保证两者一致。改内容请改 docs 那一份再复制。 -->

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
| `scope` | 是 | `global`，或 `{per?: [<概念 id>, ...], by?: [{column, table?}]}`（至少写一个）：`per` 是只在这些概念的每个组合内唯一；`by` 是只在这些物理列（来源系统、环境这类不是业务概念的判别列，形状同 `spellings`）的每个取值内唯一 |
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
`values: [{value, meaning, key?, retired?, unconfirmed?}]`、`definition?`。取值是文字或整数；`0` 与 `"0"`
是同一个码。`key`（文字或整数）是内联字典给这个码配的代理键：列存代理键（`holds: [key]`）时，目录靠它翻译，
不再报 `binding_key_without_key_column`；页面与查询写成「值=含义（代理键 k）」。数据里见到、含义还没人确认的值写 `unconfirmed: true`，或让 `meaning` 留空、以「待确认」
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
`code_set?`、`derivation?`（文字口径）、`additivity?`（`additive` 任何维度都可相加 /
`semi_additive` 部分维度可加、跨时间不可加，如余额 / `non_additive` 不可加，如比率）。

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
可选：`rules`——这条约束承接的表语义规则，每条写 `<库.表>#<规则 id>`（如 `demo_dwd.t#r2`；digest 列出每张表的规则）；
`predicate`——把条件写成单列判断 `{column, op, value}`，`op` 取 `=` `!=` `<` `<=` `>` `>=` `in` `not_in`
`is_null` `not_null` `like`（`in` / `not_in` 的 `value` 是列表，`is_null` / `not_null` 不写 `value`）。

```yaml
constraints:
  - id: cons:loan_no_unique
    kind: unique
    on: id:loan_no
    expression: no two loans share a loan_no, whatever the channel
    strength: hard
  - id: cons:principal_positive
    kind: value_domain
    on: attr:loan.principal
    expression: principal > 0
    strength: hard
    rules: [demo_dwd.dwd_lending_loan_df#r1]
    predicate: {column: principal_amt, op: ">", value: 0}
```

### 指标

业务从某个概念上读出的一个数。`id: metric:<slug>`、`name`、`on`（被计数或汇总的概念）、`aggregation`
（`sum` / `count` / `count_distinct` / `avg` / `min` / `max` / `ratio` / `other`）。可选：`definition`、
`measure`（被汇总的属性）、`filter`（哪些实例计入，文字）、`constraints`（限定口径的 `cons:` id）、
`time_window`（文字）、`dimensions`（可下钻的维度：`on` 的属性，或与 `on` 相连的概念——事件的参与者、
关系的另一端）、`additivity`（同属性）、`unit` 与通用字段。
`on` 必须是概念，`measure` 必须是属性，每个维度必须是属性或与 `on` 相连的概念，每个约束必须存在（`metric_on`、`metric_measure`、
`metric_dimension`、`metric_constraint`）。

```yaml
metrics:
  - id: metric:principal_outstanding
    name: 在贷本金
    on: concept:loan
    measure: attr:loan.principal
    aggregation: sum
    filter: loans not settled
    dimensions: [attr:loan.loan_status, concept:borrower]
    additivity: semi_additive
    unit: CNY
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
| `bindings` | 是 | `[{column, to, ref?, via?, relation?, derivation?, time_role?, code_map?, code_sets?, code_sets_by?, holds?, lang?}]` |

绑定可选的 `time_role` 说明这一列承载哪种时间：`valid_from` / `valid_to`（拉链行的有效期起止）、
`partition`（分区）、`event_time`（事件发生时间）、`record_time`（行写入时间）、`business_date`（所属业务日）。

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
- 只列 `values` 的码值集没有代理键列：给每个值写上 `key`（内联字典里与这个码配对的代理键），`holds: [key]` 的列
  就能翻译；没写 `key` 时这一列报 `binding_key_without_key_column`（目录翻不了这个键），`[key]` 仍是对的写法。
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
| `metrics` | 指标，形状同 `metrics` 文件里的条目 | `metrics.*` |
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
  [--lineage out/lineage [--schema examples/metadata]] [--tables out/tables/tables.json] \
  [--only demo_dwd.dwd_party_customer_info_df ...] [--packets out/packets] --out out/digest
```

读目录下每份合法的 `table-semantics/1` 文档（确认文件等工具自己的文档跳过；不合 schema 的文档跳过并在
stderr 说明），按表名排序写出 `digest.md` 与 `digest.json`（`catalog-digest/1`）。每张表一段：

- 一句话说明、文档写的概念与表现类型；
- 行含义、粒度列（及来源、是否唯一）、时间语义（`snapshot` / `incremental` / `zipper`）与取数方式、记录范围；
- 标识列、外部标识列、状态列、时间列、度量列、描述列（各带含义，有码值时带码值；`digest.json` 里文档有时还带
  `derivation`、`null_meaning`、`watch`，给 `--tables`（`scope-lineage tables` 写的 `tables.json`）时带物理类型 `type`），技术列只列名；
- 表的 `rules`（`[{id, kind, text}]`，`digest.md` 里是 `- Rule r1 (filter): ...`）；承接某条规则的约束在 `rules` 里写 `<库.表>#<id>`；
- 由哪些表加工而来（带角色）、被哪些表读取；要注意的点（`watch`）与未回答的问题。

给 `--catalog` 时，开头多一段「目录覆盖」：没有表现的表，以及已有表现的表里没有绑定的列（表名忽略大小写与
catalog 前缀）；某个码值集 `lookup` 所指的表算「码值来源」（`code_set_sources`：表 → 码值集 id），不算没有表现的表；
每张表的段落末尾也标出它在目录里的情况。输出是确定的：同样的输入，逐字节相同。

`packet_stale`（按另一版材料包写成）、`invalid`（`semantic validate` 有检查失败）或没有材料包的文档照常进摘要，
但与 `semantic render` 一样在 stderr 按标记各打一行点名：对照 `--packets`（不给时用文档目录旁边的 `packets/`，
存在才读）判定；没有材料包时打印一行说明没有检查。产出和退出码不变。

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

退出码：`0` 写出；`1` 没有合法文档、有文档被跳过（其余照常写出），`--only` 点名的表没有文档，`--lineage` 目录下没有
`lineage.json`，或 `--tables` 声明的是别的格式；`2` 目录、`--catalog`、`--lineage`、`--tables` 或 `--schema` 读不了，或给了 `--schema` 却没给 `--lineage`。

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

