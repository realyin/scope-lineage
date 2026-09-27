English | [中文](../zh-CN/questions.md)

# Acceptance question sets (`question-set/1`): sheets, grading material, scores

Whether the generated pages ([table-semantics pages](table-semantics.md), [the catalog's concept pages](ontology-catalog.md)) are usable is tested with a question set:
an answerer reads only the pages and answers, a grader holds each answer to the reference answer and the material and scores it 2 / 1 / 0, and the round is summed.
The two model calls (answering, grading) belong to the agent skill; Core does the deterministic parts only and never calls a model:

- `scope-lineage questions validate` checks a question set or a grades file: its schema, unique ids, non-blank reference answers;
- `scope-lineage questions sheet` writes the answerer's sheet -- ids, tables and question text only;
- `scope-lineage questions grading-sheet` writes the grader's material -- question, reference answer, evidence, the owner check,
  and the answer taken from the answers file by question id;
- `scope-lineage questions score` sums one grading round: total, by type, by table, by gap, the lost points, and earlier rounds beside it.

The prompts are `skills/scope-lineage/references/answer-prompt.md` and `grade-prompt.md`; the orchestration is the 「验收」 (acceptance) section of the skill's `SKILL.md`.

## Formats

Question sets and grades files may be YAML (`.yaml` / `.yml`, needs PyYAML; YAML 1.2 booleans, so only `true` / `false`
are booleans) or JSON.

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

| Field | Required | Meaning |
| --- | --- | --- |
| `doc_format` | yes | Always `question-set/1` |
| `subject` | no | What the set tests; used in the titles of the sheets and the score |
| `status` | no | `draft` or `confirmed` |
| `scoring` | no | Keys `2` / `1` / `0` to the scoring text; missing keys use the default text; copied into the grading material |
| `questions[].id` | yes | The question id, no whitespace, unique in the set |
| `questions[].table` | no | The table the question is about (`db.table`) |
| `questions[].concept` | no | A catalog question may name a concept id instead of a table |
| `questions[].type` | no | Free-text category (scope, retrieval, codes, measure, risk, table choice, grain, ...); scores are grouped by it |
| `questions[].text` | yes | The question; the only thing the answerer sees |
| `questions[].answer_key` | yes | The reference answer; must not be blank |
| `questions[].evidence` | no | What the reference answer rests on: a list of strings (a single string also works) |
| `questions[].owner_check` | no | The part only the owner can answer; graded by the owner-only rule |

Other keys are kept and not checked, so older hand-written sets stay valid.

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

`score` is 0, 1 or 2; `round` labels the round (text or an integer); `set` records which set was graded. `gap` says where the lost points mainly belong:

| gap | Used when |
| --- | --- |
| `page_missing` | The material has the fact; the page does not |
| `page_wrong` | The page states it wrongly and the answer followed it |
| `page_contradiction` | Two places on the page contradict each other |
| `answerer` | The page has it right; the answer missed it, misread it or over-hedged |
| `key_wrong` | The reference answer is wrong or incomplete; the answer is not penalized |
| `owner_only` | The material cannot decide it; only the owner can |
| `none` | Full marks, nothing to fix |

The scoring rules (in `grade-prompt.md`): 2 = correct and complete, pinned to columns, codes, conditions; 1 = right direction but incomplete, or reasoning with a claim
that contradicts the material; 0 = wrong or not found. When the material truly cannot decide a fact, answering the known part and marking the rest owner-to-confirm earns
full credit; marking as uncertain what the material does decide loses a point, unless the page itself wrongly
hedged and the answer repeated it (no deduction; the gap is `page_wrong`). A 2 may still carry a page gap: the
answer is right but the page needs a fix (two statements contradict, say). Only points the question asks
about cost marks; material the reference answer adds beyond the question does not.

### Answers file

The answerer writes one markdown file, one section per question, each starting with `## <id>`:

```markdown
# Answers

## Q01

One customer per dt partition, keyed by cust_id + dt (demo_dwd.dwd_party_customer_info_df.md, one-page summary).

## Q02 (codes)

1 means active. The page leaves 2 unexplained: owner to confirm.
```

- Only headings with exactly two `#` split questions; `<id>` is the first whitespace-free word after `## `, and the rest of the line is ignored.
- `###` and deeper headings, and fenced code blocks (even lines starting with `## ` inside them), stay in the current answer.
- Text before the first `## ` is ignored; an id that appears twice keeps its first section, with a warning.

## Commands

### `questions validate`

```bash
scope-lineage questions validate questions.yaml
scope-lineage questions validate run/grades.yaml
```

Picks the question-set or grades schema by the file's `doc_format`, then checks that ids are unique and that no question text or reference answer is blank.
Each error reads `place: message`, for example `questions[2].id: id 'Q01' repeats questions[0]`.

### `questions sheet`

```bash
scope-lineage questions sheet questions.yaml --pages pages --out run/sheet.md
```

The sheet's header tells the answerer to read only the pages (the `--pages` directory is named there), to cite page and section for every claim, to mark
owner-to-confirm only what the pages truly cannot decide, and to split the answers file by `## <id>`; then one section per question: id, table or concept, text.
Reference answers, evidence, `owner_check` and the question type stay out of the sheet.

### `questions grading-sheet`

```bash
scope-lineage questions grading-sheet questions.yaml --answers run/answers.md --out run/grading.md
```

The material opens with the scoring text (the set's `scoring`, defaults for missing keys), the three rules and the `question-grades/1` shape to output;
then one section per question: table or concept, type, question, reference answer, evidence, owner check, and the answer (as a block quote). A question with no answer reads
「（未作答）」 (not answered) and is warned about on stderr; answers for ids the set does not have are warned about too.

### `questions score`

```bash
scope-lineage questions score run/grades.yaml --set questions.yaml \
  --previous run-1/grades.yaml --out run/score
```

Writes `score.md` and `score.json` (`question-score/1`):

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

- The maximum counts graded questions only (2 points each); questions in the set with no grade are listed in `ungraded`, left out of the total, and warned about on stderr.
- A grades file that scores an id the set does not have is refused (exit 1); in a `--previous` round such ids are only warned about and ignored.
- Grouped by type and by table (`concept` when there is no `table`); `rounds` is each round's percentage over the same questions, `null` when none of them was graded.
- `lost` lists this round's questions below full marks; `key_wrong` the questions whose reference answer needs fixing (whatever their score); `changes` the questions whose score differs between rounds.
- Each round is labelled by its `round`, or by its file name without the extension when `round` is missing or already taken.

### Subsets

`sheet`, `grading-sheet` and `score` all take `--ids <id> ...` and `--only-table <db.table or concept> ...` (case-insensitive; both together select the intersection),
and keep the set's order. An id or table the set does not have exits 1. While tuning prompts, run on a few tables and a dozen questions to save tokens; keep a holdout set
on tables not used while tuning, and run it once at the end.

### Exit codes

| Exit code | Meaning |
| --- | --- |
| 0 | Success (warnings allowed) |
| 1 | The file has errors, an id / table is not in the set, or the grades score an id the set does not have |
| 2 | An input cannot be read (missing, not valid YAML / JSON, PyYAML not installed) |
