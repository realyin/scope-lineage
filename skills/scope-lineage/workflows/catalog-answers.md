### "客户是什么 / 这张表装的是什么 / 这个字段指什么" — 用目录回答业务问题

有人维护的本体目录（`catalog-yaml/1`）时，业务问题先问目录，不要从 SQL 重新推。

```bash
scope-lineage catalog build <catalog-dir> --out <dir> \
  [--lineage <artifacts-root>] [--tables <tables.json>]     # once: ontology.json + evidence
scope-lineage catalog query <dir>/ontology.json <kind> <term> --json
scope-lineage catalog render <dir>/ontology.json --out <pages-dir>   # the fallback
```

**query 优先，页面兜底。** `query` 的八种 kind 各答一类问题：`concept`（这是什么）、
`table`（这张表承载什么、怎么取数、记录范围、每列指向什么）、`column`（`库.表.列` 是哪个属性/标识符）、
`identifier`（怎么唯一识别、落在哪些列）、`attribute`（这个属性在哪些表列、码值、口径）、
`related`（一跳邻居：关系、事件、角色、表）、`carriers`（哪些表带着这个概念的标识符）、
`scope`（哪些表只收有效记录、去掉删除注销、去重、按分区快照）。`--json` 的 `{query, matches[]}` 直接引用；
没有匹配时退出 1，**如实说目录里没有**，不要拿近似名去猜。只有一个问题要连着看概念页
（开头的一页纸概览，附录 A1–A7：定义、数据清单、带本概念标识的表、属性、关系、约束、治理缺口）时，才读 `render` 出的
`concepts/<slug>.md`；不要把整个 `ontology.json` 读进上下文。答案里带上状态
（`drafted` = 草拟，未经确认）和证据标签（「血缘」是语料证明的，不是目录的声明）；
`conflicts` 或页面附录 A7 的「证据与目录矛盾」要原样转述。细节见
`references/catalog-questions.md`。
