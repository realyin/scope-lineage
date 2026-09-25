[English](../en/ontology-catalog.md) | 中文

# 本体目录（`catalog-yaml/1`）与 `ontology-json/3`

本体目录是一个由人维护的文件夹，里面是 YAML（或 JSON）文件。它**先**说清业务世界里有什么，
**再**说由哪些表承载：业务域，实体、事件与角色，它们的标识符、属性与状态，它们之间的关系与约束，
人们对它们的叫法——然后在单独的映射层里写明哪张表表现哪个概念、每一列绑定到什么。

**目录是本体新的、概念先行的唯一事实来源。**生成器（血缘、表卡、LLM）可以对它提出变更，但不拥有它。
`scope-lineage catalog validate` 校验目录，`scope-lineage catalog build` 把它规范化成一份给机器读的
`ontology-json/3` 文档（可同时带上血缘语料与表卡显示的证据），`scope-lineage catalog render` 把这份
文档写成每个概念一页，`scope-lineage catalog query` 从中回答一个问题。

> **过渡期。**现有的 [`scope-lineage ontology`](ontology-doc.md) 命令从血缘语料自下而上推出
> `ontology-json/2` 候选，它**再保留一个版本**，行为不变。目录不读它，它也不读目录。血缘与表卡证据
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

映射层，写在 `mapping/*.yaml`：哪张表以什么身份承载哪个概念，每一列是什么。表现以 `table`
（`库.表`）为键，每张表只能有一个表现。

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `table` | 是 | `库.表` |
| `concept` | 是 | 它表现的概念 |
| `kind` | 是 | `core` / `extension`（与核心 1:1）/ `dependent` / `event_detail` / `state_history` / `identifier_map` / `role_view` / `summary` / `intermediate` |
| `grain` | 是 | `{identifiers: [id], extra: [文字], source: declared/inferred/proven}` |
| `time` | 是 | `snapshot` / `incremental` / `zipper` / `unknown` |
| `scope` | 否 | 表里收哪些记录，文字；`render` 按关键词把每行归入过滤类别（见 `scopes.md`） |
| `refresh` | 否 | 更新频率 |
| `table_status` | 是 | `active` / `deprecated` |
| `replaced_by` | 否 | 废弃表的替代表 |
| `bindings` | 是 | `[{column, to, ref?, via?, derivation?, code_map?}]` |

绑定的 `to` 说明这一列是什么：

| `to` | `ref` | 含义 |
| --- | --- | --- |
| `attribute` | 必填 | 所表现概念的一个属性（角色视图也可以绑定其承担者的） |
| `identifier` | 必填 | 所表现概念的一个标识符（角色视图也可以绑定其承担者的） |
| `foreign_identifier` | 必填 | 另一个概念的标识符——即物理上的关系；也可以是本概念自己的标识符（同一概念的另一个实例），前提是目录里有一条两端都是本概念的关系 |
| `foreign_attribute` | 必填 | 另一个概念 X 的属性，在本行冗余存放（宽表）；`via` 必填，写本表中绑定为 `foreign_identifier`、指向 X 的标识符的那一列 |
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
| `duplicate_table` | 同一张表有两个表现 |
| `duplicate_column` | 同一个表现里一列绑定了两次 |
| `binding_attribute` | 该属性不属于所表现的概念（角色视图：也不属于其承担者） |
| `binding_identifier` | 该标识符不属于所表现的概念（角色视图：也不属于其承担者） |
| `binding_foreign_identifier` | `ref` 根本不是标识符（或不存在） |
| `self_reference_without_relation` | 该标识符属于所表现概念自己，但目录里没有两端都是该概念的关系 |
| `binding_foreign_attribute` | `ref` 不是属性，或属于所表现概念自己（角色视图：或其承担者）——那应绑定为 `attribute` |
| `binding_foreign_attribute_via` | `via` 不是本表的列，该列不是 `foreign_identifier`，或它指向的标识符不属于该属性的概念 |

"标识符属于某概念"指：概念在 `identifiers` 里列了它，或标识符的 `identifies` 指向该概念。
因此子类型可以列出父类型的标识符（示例里分期借据列了 `id:loan_no`）。

### 警告

| 规则 | 含义 |
| --- | --- |
| `drafted_ratio` | 还有多少对象是 `drafted`——未经确认的内容不应当作定论 |
| `concept_without_definition` | 概念没有定义 |
| `relation_without_name` | 关系没有动词 |
| `empty_code_set` | 码值集没有任何取值 |
| `unmapped_binding` | 某列绑定为 `to: unmapped` |
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
为 `scope_lineage/schemas/ontology-v3.schema.json`：

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
- 顶层列表排序——按 `id`，术语按词再按指向，表现按表名——所以把对象挪到别的文件不改变输出。
  对象内部的列表（属性、状态值、绑定）保持作者的顺序；
- 绑定原样带出 `via`；指向本概念自己标识符的 `foreign_identifier` 带 `self_reference: true`；
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
| `relations["rel:..."]` | `joins` | `--lineage` | 在标识列上连接两个概念表现表的 JOIN：`count` 与至多三个 `samples` |

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
    }
  }
}
```

（有删节。）证据怎样对上目录：

- **表**按最后两段匹配：示例里的借据任务写的是 `spark_catalog.demo_dwd.dwd_lending_loan_df`，
  它落到表现 `demo_dwd.dwd_lending_loan_df` 上。语料没提到的表没有条目。
- **粒度**：比较前两边都去掉分区列，所以目录粒度里写了 `stat_date`、而语句只写一个 `stat_date`
  分区时不算矛盾。声明粒度里某个标识符在本表没有绑定列时，不做比较。
- **关系**只在两端概念都有表现表时统计；统计过但没有 JOIN 支持的是 `count: 0`，无法统计的没有条目。
  一次 JOIN 计数的条件是：两侧分别是两个概念的表现表，且至少一侧的连接列绑定为标识符或外部标识符。
  两端是同一概念的关系只数至少一侧连接列带 `self_reference` 的 JOIN（表自连接也算）：同一实例出现在两张表里不说明关系。
  participation 关系同样统计。
- 语料用 `tables` 与 `ontology` 同一套读取器读；JOIN 的一侧是 CTE 时，顺着它追到提供行的物理表。

## 页面：`catalog render`

```bash
scope-lineage catalog render out/ontology.json --out out/pages
```

`render` 只读构建出的文档，从不回读目录文件夹，所以页面展示的就是构建结果（含证据）。标题用中文，
与其他渲染文档一致；名称用目录自己的。

| 文件 | 内容 |
| --- | --- |
| `index.md` | 按域列出概念（名称、种类、定义、表现表数、状态）、标识符、治理缺口汇总、记录范围汇总 |
| `concepts/<slug>.md` | 每个概念一页（`concept:fee_waiver` → `fee_waiver.md`），七节 |
| `identifiers.md` | 每个标识符的完整说明，及绑定到它的列 |
| `governance.md` | 所有概念的全部缺口，每类缺口一个列表；含义待确认的码值；另按表列出冗余属性列（信息项，不算缺口） |
| `scopes.md` | 每张表的记录范围按过滤类别归组；没写记录范围的表；引用了表的业务规则与值域约束 |

概念页的七节回答打开它的人要问的七件事：

| 节 | 内容 |
| --- | --- |
| 1. 定义与身份 | 定义、种类、状态、同义词；标识符（产生条件、唯一范围、物理拼写、对照）；状态机（值、迁移事件）；事件的参与者，角色的承担者、语境与成立条件 |
| 2. 数据清单 | 按表现类型分组的表（核心、扩展、从属、事件明细、状态历史、标识映射、角色视图、汇总、中间）：说明（表卡的表注释、表现的 `notes`）、粒度（标识符、来源，以及血缘证明了什么）、时间语义及取数方式（快照「按单个 dt 分区取数」，拉链按有效期窗口）、更新频率、记录范围、生产任务、废弃及替代；每张表的血缘一跳 |
| 3. 带本概念标识的表 | 所有概念的表里，把本概念的某个标识符绑定为 `identifier` 或 `foreign_identifier` 的每一列：表、表的概念、列、标识符、方式（自关联单独标出）。没有自己表现表的概念也能看到它从哪些表关联进来；角色没有自己的标识符，指向承担者 |
| 4. 属性 | 按类别（描述、状态、度量、时间）：定义、类型与单位、码值（值=含义）、承载它的每个表列（含码值映射；别的表冗余存放的标为「冗余（经 via 列）」）、加工口径 |
| 5. 关系 | 从本概念一侧读的关联、组成、泛化，带基数与 JOIN 次数（自关联的对端写「本概念」及承载它的列）；JOIN 次数为 0 或无法统计时，补上目录自己的依据：同表携带两端的表（表现某一端或绑定它的标识符；角色用承担者的标识符；自关联只看自关联列）与关系的 `evidence`；参与的事件（本概念的角色、事件的表现表数）；本概念承担的角色，或在角色页上反向链到承担者 |
| 6. 约束 | 作用于概念本身、其属性、标识符与关系的约束，按种类列出，带强度与状态 |
| 7. 治理缺口 | 草拟占比、未绑定列、没有落表的属性、缺码值的状态/码值类属性、有没有表现表；有证据时还有证据与目录矛盾、没人用的绑定列、没有 JOIN 支持的关系 |

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
| `concept` | id、名称、同义词或术语 | 身份、标识符、属性、状态、表现表、该读的页面 |
| `table` | `库.表`（忽略 catalog 前缀） | 它承载的概念、时间语义与取数方式（`usage`）、表注释与 `notes`、记录范围、引用它的业务规则与值域约束（`constraints`），以及每个绑定列指向什么，带证据；冗余列写 `→ 冗余属性 <属性> of <概念>（经 <via>）`，自关联列写出关系 |
| `column` | `库.表.列` | 它承载的属性或标识符及其概念——或它是哪个标识符的物理拼写 |
| `identifier` | id、名称或物理拼写 | 识别什么、唯一范围与拼写、绑定到它的列 |
| `attribute` | id、名称或术语 | 所属概念、码值、口径、每个表列 |
| `related` | 概念的 id、名称、同义词或术语 | 一跳邻居：从本概念一侧读的关系、事件、参与者、角色、承担者、表、带本概念标识的表（`carriers`）；每条关系与事件带 `carried_together`（同表携带两端的表）与 `evidence`，没有 JOIN 时文本里写出 |
| `carriers` | 概念的 id、名称、同义词或术语 | 所有概念的表里绑定了本概念标识符的列：表、表的概念、列、标识符、方式 |
| `scope` | 过滤类别（`validity`/有效记录、`deletion`/删除、`dedup`/去重、`partition`/分区、`other`/其他，类别名或其一半都行）或关键词 | 记录范围或所引约束说到它的表，各带这些行（与其类别）、约束与取数方式 |

名称精确匹配（忽略大小写与首尾空格），依次试 id、名称、同义词、术语；不猜。文本回答只有几行：

```text
客户 concept:customer · 实体 · 客户与账户 · 已确认（owner）
  A person the shop has registered, whether or not they ever borrow.
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

## 安全地写 YAML

- 目录按 YAML 1.2 的布尔规则读取：只有 `true` / `false` 是布尔，所以 `on:`（约束的键）以及
  `no`、`off` 这样的码值都保持为文字。
- 基数端（`"1"`）以及需要保留前导零的码值（`"01"`）请加引号。
- 不加引号的日期（`2026-01-31`）读成文字 `"2026-01-31"`。
