[English](../en/questions.md) | 中文

# 验收问题集（`question-set/1`）：题单、判分材料、评分

生成的页面（[表语义页](table-semantics.md)、[本体目录的概念页](ontology-catalog.md)）好不好用，用一套问题集来考：
作答者只读页面答题，判分者对照参考答案和材料打 2 / 1 / 0 分，最后汇总。两次需要模型的调用（作答、判分）
属于 Agent 技能；Core 只做确定性的部分，从不调用模型：

- `scope-lineage questions validate` 检查问题集或判分文件的格式、题号唯一、参考答案非空；
- `scope-lineage questions sheet` 写给作答者的题单——只有题号、表和题目；
- `scope-lineage questions grading-sheet` 写给判分者的材料——题目、参考答案、证据、需 owner 确认的说明，
  以及按题号从作答文件里取出的回答；
- `scope-lineage questions score` 汇总一轮判分：总分、按题型、按表、按缺口、失分清单，以及与前几轮的对比。

提示词在 `skills/scope-lineage/references/answer-prompt.md` 与 `grade-prompt.md`，编排见技能 `SKILL.md` 的「验收」一节。

## 格式

问题集和判分文件都可以写成 YAML（`.yaml` / `.yml`，需要 PyYAML，按 YAML 1.2 只把 `true` / `false`
读成布尔）或 JSON。

### `question-set/1`

```yaml
doc_format: question-set/1
subject: demo customer slice
status: draft
scoring:
  2: correct and complete, pinned to columns, codes and conditions
  1: right direction but incomplete, or a claim that contradicts the material
  0: wrong or not found
questions:
  - id: Q01
    table: demo_dwd.dwd_party_customer_info_df
    type: grain
    text: What is one row of this table?
    answer_key: One customer per dt partition; the key is cust_id + dt.
    evidence: [packet grain section, "SQL: GROUP BY cust_id"]
  - id: Q02
    table: demo_dwd.dwd_party_customer_info_df
    type: codes
    text: What does cust_status = 1 mean?
    answer_key: 1 means active.
    evidence: [column comment of cust_status]
    owner_check: The material does not say what 2 means; the owner has to confirm it.
  - id: Q03
    concept: concept:customer
    type: table choice
    text: Which table holds the customer's basic information?
    answer_key: demo_dwd.dwd_party_customer_info_df.
    evidence: [concept page, data inventory]
```

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `doc_format` | 是 | 固定为 `question-set/1` |
| `subject` | 否 | 这套题考的是什么，写进题单和评分的标题 |
| `status` | 否 | `draft` 或 `confirmed` |
| `scoring` | 否 | 键 `2` / `1` / `0` 到评分标准的说明；缺的键用默认说明，写进判分材料 |
| `questions[].id` | 是 | 题号，不含空白，整套唯一 |
| `questions[].table` | 否 | 题目针对的表（`库.表`） |
| `questions[].concept` | 否 | 目录题可以写概念 id 代替表 |
| `questions[].type` | 否 | 题型，自由文本（范围、取数、码值、口径、风险、选表、粒度……），按它分组计分 |
| `questions[].text` | 是 | 题目，作答者只看到它 |
| `questions[].answer_key` | 是 | 参考答案，不能是空白 |
| `questions[].evidence` | 否 | 参考答案的依据，字符串列表（单个字符串也可） |
| `questions[].owner_check` | 否 | 哪部分只有 owner 能答；判分时按 owner-only 规则处理 |

其余键原样保留、不校验，手写的旧问题集照样可用。

### `question-grades/1`

```yaml
doc_format: question-grades/1
set: questions.yaml
round: r2
grades:
  - id: Q01
    score: 2
    gap: none
    reason: Grain and key both right, cited from the one-page summary.
  - id: Q02
    score: 1
    gap: page_missing
    reason: The column comment also defines 2; the page leaves it out.
  - id: Q03
    score: 2
    gap: key_wrong
    reason: The answer is right; the key misses the history table.
```

`score` 只能是 0、1、2；`round` 是这一轮的标签（文本或整数）；`set` 记录判的是哪套题。`gap` 说失分主要落在哪里：

| gap | 用在 |
| --- | --- |
| `page_missing` | 材料里有这个事实，页面没写 |
| `page_wrong` | 页面写错了，作答照着答错 |
| `page_contradiction` | 页面两处说法矛盾 |
| `answerer` | 页面写对了，作答漏看、看错或过度保留 |
| `key_wrong` | 参考答案错了或不全；不扣作答的分 |
| `owner_only` | 材料定不了，只有 owner 能答 |
| `none` | 满分，没有要改的 |

评分规则（写在 `grade-prompt.md` 里）：2 = 正确且完整，落到列、码值、条件；1 = 方向对但不完整，或推理里有与材料
矛盾的说法；0 = 错误或没找到。材料确实定不了的事实，答出已知部分、其余标明待 owner 确认算满分；材料能定的却写成
待确认扣一分。

### 作答文件

作答者输出一个 markdown 文件，每题一节，以 `## <id>` 开头：

```markdown
# Answers

## Q01

One customer per dt partition, keyed by cust_id + dt (demo_dwd.dwd_party_customer_info_df.md, one-page summary).

## Q02 (codes)

1 means active. The page leaves 2 unexplained: owner to confirm.
```

- 只有恰好两个 `#` 的标题分题；`<id>` 是 `## ` 后第一个不含空白的词，同一行后面的文字忽略。
- `###` 及更深的标题、围栏代码块里的内容（哪怕以 `## ` 开头）都算在当前这题里。
- 第一个 `## ` 之前的内容忽略；同一题号出现两次时保留第一次，并给出警告。

## 命令

### `questions validate`

```bash
scope-lineage questions validate questions.yaml
scope-lineage questions validate run/grades.yaml
```

按文件里的 `doc_format` 选用问题集或判分文件的 Schema，再检查题号唯一、题目和参考答案不是空白。
每条错误写成「位置: 说明」，例如 `questions[2].id: id 'Q01' repeats questions[0]`。

### `questions sheet`

```bash
scope-lineage questions sheet questions.yaml --pages pages --out run/sheet.md
```

题单开头告诉作答者只读页面（`--pages` 给出的目录写进开头）、每个结论注明页面和小节、只有页面确实定不了的才写
待 owner 确认、作答文件按 `## <id>` 分题；然后每题一节：题号、表或概念、题目。参考答案、证据、`owner_check`
和题型都不写进题单。

### `questions grading-sheet`

```bash
scope-lineage questions grading-sheet questions.yaml --answers run/answers.md --out run/grading.md
```

判分材料开头是评分标准（问题集的 `scoring`，缺的用默认说明）、三条规则和要输出的 `question-grades/1` 格式；
然后每题一节：表或概念、题型、题目、参考答案、证据、需 owner 确认、作答（引用块）。没有作答的题写「（未作答）」
并在 stderr 警告；作答文件里有问题集没有的题号也会警告。

### `questions score`

```bash
scope-lineage questions score run/grades.yaml --set questions.yaml \
  --previous run-1/grades.yaml --out run/score
```

写出 `score.md` 与 `score.json`（`question-score/1`）：

```json
{
  "doc_format": "question-score/1",
  "set": "questions.yaml",
  "subject": "demo customer slice",
  "round": "r2",
  "total": {"questions": 3, "graded": 3, "points": 5, "max": 6, "percent": 83.3},
  "by_type": [
    {"key": "grain", "questions": 1, "graded": 1, "points": 2, "max": 2, "percent": 100.0,
     "rounds": {"r1": 50.0, "r2": 100.0}}
  ],
  "by_table": [
    {"key": "demo_dwd.dwd_party_customer_info_df", "questions": 2, "graded": 2, "points": 3,
     "max": 4, "percent": 75.0, "rounds": {"r1": 50.0, "r2": 75.0}}
  ],
  "by_gap": [
    {"gap": "page_missing", "count": 1, "lost": 1},
    {"gap": "key_wrong", "count": 1, "lost": 0},
    {"gap": "none", "count": 1, "lost": 0}
  ],
  "lost": [
    {"id": "Q02", "table": "demo_dwd.dwd_party_customer_info_df", "type": "codes", "score": 1,
     "gap": "page_missing", "reason": "The column comment also defines 2; the page leaves it out."}
  ],
  "key_wrong": [
    {"id": "Q03", "table": "concept:customer", "type": "table choice", "score": 2,
     "gap": "key_wrong", "reason": "The answer is right; the key misses the history table."}
  ],
  "ungraded": [],
  "rounds": [
    {"round": "r1", "total": {"questions": 3, "graded": 3, "points": 4, "max": 6, "percent": 66.7}},
    {"round": "r2", "total": {"questions": 3, "graded": 3, "points": 5, "max": 6, "percent": 83.3}}
  ],
  "changes": [{"id": "Q01", "scores": {"r1": 1, "r2": 2}}]
}
```

- 满分只算已判的题（每题 2 分）；问题集里有、判分文件里没有的题列在 `ungraded`，不计入总分，并在 stderr 警告。
- 判分文件里出现问题集没有的题号时拒绝汇总（退出 1）；`--previous` 的轮次里出现时只警告并忽略。
- 按题型、按表（没有 `table` 时用 `concept`）分组；`rounds` 是每一轮在同一组题上的得分率，没判到的写 `null`。
- `lost` 是本轮没拿满分的题；`key_wrong` 是参考答案要修正的题（不论分数）；`changes` 是各轮分数不同的题。
- 每一轮的标签取文件里的 `round`，没有或与别的轮次重名时用文件名（不含扩展名）。

### 子集

`sheet`、`grading-sheet`、`score` 都接受 `--ids <id> ...` 和 `--only-table <库.表或概念> ...`（不分大小写，
可以同时给，取交集），题目保持问题集里的顺序。给出的题号、表在问题集里不存在时退出 1。调提示词时先在几张表、
十来道题上跑，省 token；另备一套覆盖没参与调优的表的留出题，收尾时跑一次。

### 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功（可能有警告） |
| 1 | 文件有错误，或题号 / 表在问题集里不存在，或判分文件有问题集没有的题号 |
| 2 | 输入文件读不了（不存在、不是合法 YAML / JSON、缺 PyYAML） |
