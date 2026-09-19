# 把本体候选的「待人工判定」变成业务方能答的问题清单

读 `ontology.md` 与 `tables/<表>.md` 之后用这份提示词。目标不是写一份本体报告，而是问出
**业务方五分钟内答得完、答完就能让下一轮少问一次**的问题——并且把答案落回
`ontology.overrides.json`，让 `scope-lineage ontology --overrides` 把它们升到 `confirmed`。

与 `semantic-profile-prompt.md` 的关系：那份把**一个任务**变成业务画像，这份把**一份语料**
的结构假设变成确认清单。五行格式、`[推断]` / `[待确认]` 标注规则、"不许把假设写成事实"的
底线，两份完全一致。

## 先读什么

1. `ontology.md` 的 `erDiagram`：整份语料一屏，先看清有哪几个实体、谁连谁。
2. `ontology.md` 的「待人工判定」表：跨任务矛盾（`cardinality_conflict`）优先级最高。
3. 每张涉及的 `tables/<表>.md` 的第 11 节「待人工判定」：该表所有 `hypothesis` 断言，
   每条末尾已经打印好回写目标字符串，**照抄，不要自己拼**。

## 只问四类

| 类 | 什么时候问 | 为什么值得问 |
| --- | --- | --- |
| 1. 跨任务矛盾 | `findings[].kind = cardinality_conflict` | 两个任务对同一张表的同一组键给出相反判断，其中一个一定错：要么关联放大了行数，要么去重是多余的 |
| 2. 被假设唯一的身份键 | 候选键 tier 为 `hypothesis`，且该表在某条边上是被直接关联的一侧 | 答"不唯一"就意味着下游有行数放大，是能改数的答案 |
| 3. 关系基数 | 边的 tier 为 `hypothesis`（`many_to_one_assumed`） | 同上；一次确认能让这条边在所有任务里都不用再猜 |
| 4. 值集是否封闭 | `in_set` 且 `completeness = unknown`，且该列参与了分流逻辑 | 漏一个取值等于漏一批数据 |

**不问的事**：实体的业务名字（那是命名，不是判定，猜错代价高、答对收益低）、类层次与父子类、
某列的中文含义（走 `glossary.overrides.template.md`，不在这里问）、"请核对整张表"这类
一句话答不了的问题、`proven` 与 `implied` 的断言（它们已经被证明了，再问等于不信任证据）。

**一次最多 8 条**，按影响排序。超出的放在清单末尾的「备查项」里，一行一条，不用五行格式。

## 每条固定五行加一行留白

```
Q<n>. <一句问题，业务方不看 SQL 也能懂>
- 证据：<ontology.json 路径或卡片小节，允许写结构词>
- 候选答案：<A / B / C，或「无候选」>
- 回写目标：关系:<from 实体>.<列+列>-><to 实体>.<列+列> | 键:<表>=<列+列>
- 影响：<答错会怎样，写具体的数字后果>
- 答案：（待填）
```

- `- 证据：` 这一行**豁免「正文不得出现结构词」**：`cardinality`、`hypothesis`、
  `candidate_keys`、`many_to_one_assumed` 这类原词照写，它是给复核者的指针。
- **`- 回写目标：` 必须写成两种形式之一、且只写一种**，并且**逐字照抄卡片第 11 节打印的那串**：
  - `关系:<from 实体>.<列+列>-><to 实体>.<列+列>` —— 例 `关系:ods.orders.customer_id->ods.customer.id`
  - `键:<表>=<列+列>` —— 例 `键:ods.customer=id`
  - 多列用 `+` 连接，顺序与卡片一致。把两种并列写在一行等于没填。
- `- 答案：（待填）` 这一行**必须写出来**，不写业务方就没有落笔的地方。

## 提问时的措辞底线

- 问题正文里**不许把假设写成事实**。不写"`ods.customer` 的主键是 `id`，对吗"——语料从没
  证明过这件事；写"有 2 个任务直接按 `id` 关联 `ods.customer`，等于假设一个 `id` 只对应
  一行。这张表里一个 `id` 会出现多行吗？"
- 矛盾类的问题要把**两边都摆出来**，不要替业务方选一边：`T1` 先按 `k` 去重再关联，`T2` 直接
  按 `k` 关联，问"哪一种是对的口径"。
- 不要合并两个不同的假设成一条问题。一条问题只能有一个回写目标。

## 答案回来之后

业务方把答案写在每条的 `- 答案：` 行，然后按回写目标合并进 `ontology.overrides.json`：

```json
{
  "relations": {
    "ods.orders.customer_id->ods.customer.id": {
      "cardinality": "many_to_one",
      "confirmed_by": "<名字>",
      "date": "<YYYY-MM-DD>"
    }
  },
  "keys": {
    "ods.customer": {
      "columns": ["id"],
      "confirmed_by": "<名字>",
      "date": "<YYYY-MM-DD>"
    }
  }
}
```

- `relations` 的键就是 `关系:` 后面那一串（去掉 `关系:` 前缀）；`keys` 的键是 `键:` 与 `=`
  之间那一段，`columns` 是 `=` 之后按 `+` 拆开的列表。
- `cardinality` 取 `one_to_many` / `many_to_one` / `many_to_one_assumed` /
  `one_to_one_assumed` / `unknown`；业务方只说"唯一"而没说方向时，不要替他选，留空——
  不写 `cardinality` 就是沿用语料原来的 claim、只把层级升到 `confirmed`。
- 答"不唯一"**不写成 override**：那不是确认，那是证实了风险。把它写进交付文本，并提示相关
  任务存在行数放大。override 只记录确认，不记录否认。

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --overrides <dir>/ontology.overrides.json
```

跑完检查两件事：`overrides_applied.relations` / `keys` 的条数与你合并的条数相等；
`overrides_applied.unmatched` 为空——它非空就说明某个回写目标字符串抄错了。

## 自检

| # | 检查项 | 通过 |
| --- | --- | --- |
| 1 | 每条问题业务方不看 SQL 也能懂，正文没有结构词（`- 证据：` 行除外） | |
| 2 | 每条只有一个回写目标，且逐字抄自卡片第 11 节 | |
| 3 | 正文没有把 `hypothesis` / `assumed` 写成事实 | |
| 4 | 矛盾类问题把两边任务都列出来了，没有替业务方选边 | |
| 5 | 总数 ≤ 8 条，超出的进「备查项」 | |
| 6 | 每条都有 `- 答案：（待填）` 行 | |
| 7 | 没有问实体业务名、类层次、取值含义 | |
