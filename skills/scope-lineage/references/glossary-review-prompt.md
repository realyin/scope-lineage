# 把「取值含义待填模板」变成凭证据自答 + 一张能答完的问题清单

读 `glossary.md` 与 `glossary.overrides.template.md` 之后用这份提示词。目标不是写一份
字典报告，而是**先把语料自己已经回答过的取值关掉**，再把剩下的整理成业务方五分钟内答得完的
问题——两半都落回 `glossary.overrides.json`，让
`scope-lineage glossary --overrides` 把它们升成已确认的事实。

与 `ontology-review-prompt.md` 的关系：那份处理**结构**假设（键、基数），这份处理**取值含义**。
纪律完全一致：只有表里列出的证据可以自答，每条自答必须写 `basis`，问人的条数有上限，
不许把推断写成事实。

## 先读什么

1. `glossary.overrides.template.md`：本轮的工作台。一列一节，一取值一行，
   已经按「有证据的列在前，再按这列承载了多少语料」排好序。
2. 每行的**「候选来源」列**：`comment` / `case_label` / `same_name_confirmed` / `—`。
   前三种就是下面三类证据，`—` 的那些行才是要去问人的候选。
3. `glossary.md` 对应列的小节：该列名跨表的注释、这个取值被哪些语境写过、封闭集是否已证明。
4. 需要时读任务画像 `semantic.md`（就在该任务 `lineage.json` 旁边）：取值出现在哪条规则里，
   答错会影响哪些行。**没有 `semantic.md` 就先跑 `describe`**：

   ```bash
   scope-lineage describe --lineage <corpus>   # semantic.json + semantic.md 写在每个 lineage.json 旁边
   ```

## 凭证据自答：Agent 先答，剩下的才去问人

一轮人工评审最贵的资源是业务方的注意力，而待填表里有一部分取值根本不需要业务方——语料自己
已经把答案写在注释或 SQL 里，字典按纪律只肯把它标成候选（`?`），不肯自己升级。Agent 的第一件事
是把这些取值**用证据关掉**。

只有下面三类证据可以关掉一个取值，别的都不行：

| # | 证据 | 含义写什么 | 写进 `basis` 的话术 |
| --- | --- | --- | --- |
| 1 | 该列自己的注释把这个取值枚举了出来（`0-未生效，1-生效`；模板「候选来源」为 `comment`） | 属于这个取值的那一半（`生效`） | `列注释 <原注释> 把该取值枚举为 <含义>` |
| 2 | 语料里有 CASE 把这个取值映射到一个标签（`WHEN status = 'A' THEN '有效'`；「候选来源」为 `case_label`） | 该标签（`有效`） | `<任务/规则 id> 的 CASE 把该取值标为 <标签>` |
| 3 | 同名列上的同一个取值已被**人**确认过（「候选来源」为 `same_name_confirmed`） | 那条已确认的含义，原文照抄 | `同名列 <表>.<列> 的同一取值已由 <确认人> 确认为 <含义>，按同名规则沿用` |

- 关掉的方式就是写进 `glossary.overrides.json`，并且**每条都必须带 `basis`**：没有 `basis`
  的自答等于把推断写成事实，下一轮没人能复核它凭什么是已确认。工具会直接拒绝它，
  并记进 `overrides_applied.rejected`（`reason: "missing_basis"`）。
- `confirmed_by` 写 Agent 自己的标识（例如 `confirmed_by: "agent:glossary-review"`），
  **不要冒充人**。`agent:` 前缀是这条确认能不能被下一轮当成证据 3 的分界线：
  同名规则只认人确认过的，不认 Agent 自己确认过的，否则一条推断会沿着同名列自我扩散。
- **不许覆盖人的确认**。一个取值已经有人签过名，就不要再写一条；字典也不会替你比较谁更晚。
- 证据 1 与 2 只能确认**这一个取值的含义**；它们**不能**用来判断这个列的取值集合是否封闭，
  不能用来给同名的别的列下结论（那要走证据 3，而且要在 `basis` 里说清楚是同名规则）。
- 两条证据互相矛盾（注释说 A、CASE 标成 B）时**一条都不许关**：原样留着，写成问人的问题，
  并把两边都摆出来。
- **其余取值一律原样留在待填表里**，不许按取值的拼写猜（`'PAID'` 看起来像"已支付"不是证据），
  不许翻译，不许同义扩写。

自答不限条数（表里有多少行可关就关多少行），但**去问人的问题一次最多 8 条**。

## 去问人的那部分：只问这三类

| 类 | 什么时候问 | 为什么值得问 |
| --- | --- | --- |
| 1. 分流取值 | 这个取值出现在 `filter_eq` / `filter_in` / `case_condition` 里，答错就等于漏一批行 | 它决定这个任务算哪些数据 |
| 2. 跨表同名冲突 | 同一个列名在两张表上注释说法不同（`glossary.md` 标了 ⚠ 注释冲突） | 两边不是一回事的话，下游合并口径就是错的 |
| 3. 集合是否封闭 | 该列 `closed_set` 未证明，且取值分布像一张码表 | 漏一个取值等于漏一批数据 |

**不问的事**：`Y`/`N` 这类开关、裸数字、日期形字面量（待填表本来就不问它们）、
已被上面三类证据关掉的取值、"请把这张码表补全"这种一句话答不完的问题、
列本身的中文名（那是 `术语:` 的事，不是取值的事）。

## 交付两个文件

1. `glossary.overrides.json`：自答的部分，直接可跑。
2. 一份开放问题 markdown（例如 `glossary.open-questions.md`）：要问人的部分，一条一段：

```
Q<n>. <一句问题，业务方不看 SQL 也能懂>
- 证据：<glossary.md 的列小节 / 某任务的某条规则>
- 候选答案：<A / B / C，或「无候选」>
- 回写目标：值域:<表.列>=<去引号取值>
- 影响：<答错会怎样，写具体的后果>
- 答案：（待填）
```

- `- 回写目标：` 逐字照抄模板里的键（`<表.列>=<去引号取值>`），一条问题只能有一个。
- `- 答案：（待填）` 这一行**必须写出来**，不写业务方就没有落笔的地方。
- 业务方答完之后，用 `scripts/confirmations.py apply` 或手工把答案并进同一个
  `glossary.overrides.json`，答案里的 `confirmed_by` 写**人名**。

## overrides 长什么样

```json
{
  "values": {
    "ods.app_order.pay_status=PAID": {
      "meaning": "已支付",
      "basis": "列注释 支付状态：PAID-已支付，REFUND-已退款 把该取值枚举为 已支付",
      "note": "补充说明，可省",
      "confirmed_by": "agent:glossary-review",
      "date": "2026-09-21"
    }
  },
  "terms": {
    "pay_status": {
      "meaning": "支付状态",
      "basis": "<凭什么，自由文本>",
      "confirmed_by": "<名字>",
      "date": "<YYYY-MM-DD>"
    }
  }
}
```

- `basis` 与 `note` 都是自由文本，发布在 `confirmed_by` / `date` 旁边（`basis` 发布成
  `meaning.confirmed_basis`，`glossary.md` 的含义列会打印成「（依据：…）」）。
- `meaning` 留空串**不算答案**：它会被记进 `overrides_applied.blank` 并跳过。
- 除 `meaning` / `text` / `confirmed_by` / `date` / `basis` / `note` 之外的字段本版本读不懂，
  会被列进 `overrides_applied.ignored_fields`，那条确认里的这个字段不生效。

```bash
scope-lineage glossary --lineage <corpus> --out <dir> \
  --overrides <dir>/glossary.overrides.json \
  --template <dir>/glossary.overrides.template.md --template-top 0
```

跑完检查四件事：`overrides_applied.values` / `terms` 的条数与你合并的条数相等；
`rejected` 为空——它非空说明某条 `agent:` 确认忘了写 `basis`，那条**没有生效**；
`unmatched` 为空——它非空说明某个键抄错了；`ignored_fields` 为空——它非空说明某个字段名拼错了。
下一轮的待填表比上一轮短，短掉的行数等于你这一轮合并的条数。

## 自检

| # | 检查项 | 通过 |
| --- | --- | --- |
| 1 | 每条自答只用了表里那三类证据，没有按拼写猜、没有翻译 | |
| 2 | 每条自答都写了 `basis`，且 `basis` 指得出具体的注释原文 / 规则 id / 同名列 | |
| 3 | 自答的 `confirmed_by` 都带 `agent:` 前缀，没有冒充人 | |
| 4 | 没有覆盖任何一条人已经确认过的含义 | |
| 5 | 同名规则只用在**人**确认过的取值上，且 `basis` 里写明了是同名沿用 | |
| 6 | 证据互相矛盾的取值一条都没关，进了问人清单并摆出了两边 | |
| 7 | 去问人的总数 ≤ 8 条，且每条都有一个回写目标与一行 `- 答案：（待填）` | |
| 8 | 跑完 `--overrides` 后 `rejected`、`unmatched`、`ignored_fields` 都是空的 | |
