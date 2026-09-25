# 用目录回答业务问题

本体目录（`catalog-yaml/1`）是有人维护的业务事实来源：概念、标识符、属性、关系、约束，以及
表和列落在哪些概念上。有目录时，"X 是什么""这张表装的是什么""这个字段指什么"先问目录，
不要从 SQL 重新推一遍。格式说明见 `docs/zh-CN/ontology-catalog.md`。

## 准备：build 一次

```bash
scope-lineage catalog build <catalog-dir> --out <dir> \
  --lineage <artifacts-root> --tables <tables.json>
```

`--lineage` 和 `--tables` 可选。给了才有证据：生产任务、调度、上下游一跳、血缘证明的粒度、
每个绑定列的来源列和表达式、每条关系背后的 JOIN 次数、元数据有但语料没用的列。证据写在
`ontology.json` 顶层的 `evidence` 里，不改目录对象。

## 先 query

```bash
scope-lineage catalog query <dir>/ontology.json <kind> <term> --json
```

| 问题 | kind | term |
| --- | --- | --- |
| 这是什么，怎么识别，有哪些表 | `concept` | id、名称、同义词或术语 |
| 这张表承载什么、怎么取数、收哪些记录、每列指向什么 | `table` | `库.表`（带 catalog 前缀也行） |
| 这个字段是什么意思 | `column` | `库.表.列` |
| 这个号怎么产生、在哪唯一、落在哪些列 | `identifier` | id、名称或物理列名 |
| 这个属性在哪些表列、码值、口径 | `attribute` | id、名称或术语 |
| 和它有关的有什么 | `related` | 概念的 id、名称、同义词或术语 |
| 从哪些表能关联到它（它自己没有表时尤其要问） | `carriers` | 概念的 id、名称、同义词或术语 |
| 哪些表只收有效记录 / 去掉了删除注销 / 去重取最新 / 按分区快照 | `scope` | 类别（`validity`/有效记录、`deletion`/删除、`dedup`/去重、`partition`/分区、`other`/其他）或关键词 |

- `matches` 为空（退出码 1）：回答"目录里没有"，并说查的是什么。不要换近似名重试到命中为止，
  也不要自己补一个定义。可以建议把它补进目录。
- 多个匹配：全部列出，让用户选，不要替他挑。
- `matched_by` 是 `synonym` 或 `term` 时，回答里用目录的正式名称，并注明用户说的是同义词。

## 再看页面

只有一个问题要连着看几节时才读页面：

```bash
scope-lineage catalog render <dir>/ontology.json --out <pages-dir>
```

读 `concepts/<slug>.md`（slug 是概念 id 冒号后的部分），七节依次是：定义与身份、数据清单、
带本概念标识的表、属性、关系、约束、治理缺口。`index.md` 按域列出全部概念，`governance.md` 列出
全部缺口（含含义待确认的码值），`scopes.md` 按过滤类别列出每张表的记录范围和引用了表的业务规则。
不要把整个 `ontology.json` 读进上下文。

## 回答时带上什么

1. **状态**：`drafted`（草拟）是还没人确认的内容，说"目录草拟为……"；`confirmed` 才能当事实说。
2. **证据标签**：页面里标「血缘」的、JSON 里 `evidence` 下的，是语料证明的事实，不是目录的声明。
   两者一致时一句带过；不一致时两边都说。
3. **矛盾原样转述**：`evidence.representations[表].conflicts` 或页面第 7 节「证据与目录矛盾」
   有内容时，原样转述，例如"目录声明粒度已证明，但血缘只能给出候选键"。不要替任何一边圆。
4. **没有证据不等于没有**：关系的证据连接是 0 次，说"语料里没有看到连接"，不说"关系不存在"；
   一端没有表现表的关系本来就不统计。这时看同一格（或 `related` 的 `carried_together` 与
   `evidence`）里目录自己的依据：「同表携带两端」的表就是能同时拿到两端的地方，「目录证据」是
   维护者引用的列或表。概念没有自己的表时，先问 `carriers`，用那些表里的标识列关联进来。
5. **冗余列和自关联列说清是谁的**：`to: foreign_attribute` 的列是另一个概念的属性冗余在本表上，
   回答"这是<概念>的<属性>，经 `via` 列关联到那个<概念>"，不要说成本表概念的属性；
   `self_reference` 的列指向同一概念的另一个实例，带上 `self_relations` 里的关系名。
6. **取数口径先问表**：写 SQL 或数数之前先 `table`（或按类别问 `scope`）。`usage` 是
   「按单个 dt 分区取数」的快照表，不要跨分区求和；拉链表按有效期窗口取；`scope` 与
   `constraints` 里的过滤（有效记录、删除注销、去重）要写进条件，或明说没有写进去。
7. **含义待确认的码值照实说**：页面与查询里写成「值（含义待确认：猜测）」的码值，说"目录里这个
   值的含义还没确认，猜测是……"，不要当成已确认的含义用。
