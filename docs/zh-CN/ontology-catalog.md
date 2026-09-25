[English](../en/ontology-catalog.md) | 中文

# 本体目录（`catalog-yaml/1`）与 `ontology-json/3`

本体目录是一个由人维护的文件夹，里面是 YAML（或 JSON）文件。它**先**说清业务世界里有什么，
**再**说由哪些表承载：业务域，实体、事件与角色，它们的标识符、属性与状态，它们之间的关系与约束，
人们对它们的叫法——然后在单独的映射层里写明哪张表表现哪个概念、每一列绑定到什么。

**目录是本体新的、概念先行的唯一事实来源。**生成器（血缘、表卡、LLM）可以对它提出变更，但不拥有它。
`scope-lineage catalog validate` 校验目录，`scope-lineage catalog build` 把它规范化成一份给机器读的
`ontology-json/3` 文档。

> **过渡期。**现有的 [`scope-lineage ontology`](ontology-doc.md) 命令从血缘语料自下而上推出
> `ontology-json/2` 候选，它**再保留一个版本**，行为不变。目录不读它，它也不读目录。语料里的证据
> （血缘、表卡、值词典）在后续步骤里挂到目录上；本版本只定义格式、校验与构建。

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
`values: [{value, meaning, retired?}]`、`definition?`。取值是文字或整数；`0` 与 `"0"` 是同一个码。

```yaml
code_sets:
  - id: code:loan_status
    name: 借据状态
    values:
      - {value: "1", meaning: normal}
      - {value: "2", meaning: overdue}
      - {value: "3", meaning: settled, retired: false}
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
| `scope` | 否 | 表里收哪些记录，文字 |
| `refresh` | 否 | 更新频率 |
| `table_status` | 是 | `active` / `deprecated` |
| `replaced_by` | 否 | 废弃表的替代表 |
| `bindings` | 是 | `[{column, to, ref?, derivation?, code_map?}]` |

绑定的 `to` 说明这一列是什么：

| `to` | `ref` | 含义 |
| --- | --- | --- |
| `attribute` | 必填 | 所表现概念的一个属性（角色视图也可以绑定其承担者的） |
| `identifier` | 必填 | 所表现概念的一个标识符（角色视图也可以绑定其承担者的） |
| `foreign_identifier` | 必填 | 另一个概念的标识符——即物理上的关系 |
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
      - column: loan_status
        to: attribute
        ref: attr:loan.loan_status
        code_map: {"1": normal, "2": overdue, "3": settled}
      - {column: dt, to: technical}
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
| `binding_foreign_identifier` | 该标识符属于所表现概念自己，或根本不是标识符 |

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
  "counts": {"domains": 3, "concepts": 10, "relations": 11, "derived_relations": 7},
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
- 每类对象的键按固定顺序输出；码值与状态值一律为文字；写成 `1` 的基数端输出为 `"1"`；
  文字形式的 `arises_when` 变成 `{condition}`；
- 顶层列表排序——按 `id`，术语按词再按指向，表现按表名——所以把对象挪到别的文件不改变输出。
  对象内部的列表（属性、状态值、绑定）保持作者的顺序；
- 每个事件参与者变成一条 `participation` 关系 `rel:<事件 slug>.<role_name>`，从事件指向参与者，
  基数为 `{from: "0..*", to: "1"}`（`one`）或 `"1..*"`（`many`），带 `derived_from` 以及事件的
  status 与 source。这样的 id 不能再手写一次。

## 安全地写 YAML

- 目录按 YAML 1.2 的布尔规则读取：只有 `true` / `false` 是布尔，所以 `on:`（约束的键）以及
  `no`、`off` 这样的码值都保持为文字。
- 基数端（`"1"`）以及需要保留前导零的码值（`"01"`）请加引号。
- 不加引号的日期（`2026-01-31`）读成文字 `"2026-01-31"`。
