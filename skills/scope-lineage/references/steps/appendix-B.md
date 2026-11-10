## 附录 B 目录与文件约定

```text
$RUN/
  env.sh                     变量块（S0 写，之后只读）
  TOOL_VERSION               工具版本与提交号（S0）
  ledger.md                  编排者账本（每次派发、回收都更新）
  candidates.tsv             有生产任务的表（S3）
  tables.txt                 本轮范围内的表，一行一个 库.表（S3 写；blocked 时删行）
  blocked.txt                blocked 的表（S5）
  artifacts/[<子目录>/]<任务名>/  血缘 lineage.json（S1；子目录照搬 $TASKS 的）
  corpus/                    tables.json、glossary.json（S2）
  packets/<表>/              packet.md、packet.json（S3；只由 semantic packet 写）
  docs/<表>.json             表语义（写作写、修订改、confirm 改；编排者不手改）
  reviews/<表>.md            当前审读（审读员写；fixed_doc_digest 只由 semantic fixed 写）
  reviews/<表>.fixlog.txt    修订记录：T4 回复里的逐条处理，每段前一行来源（S7 编排者追加；.txt，status 不读）
  reviews/<表>.prior.md      重写前的旧审读（S4 重写准备；给重写后的首审和修正点清单脚本）
  reviews/<表>.prior.json    重写前的旧文档（S4 重写准备；只给审读员，不给写作者）
  reviews/<表>.prior.fixlog.txt   重写前的修订记录（S4 重写准备；只给修正点清单脚本）
  reviews_prev/<表>.round1.md   复审前备份的首轮审读（S8）
  reviews_prev/<表>.prior.round1.md   重写前的首轮审读备份（S4 重写准备；只给修正点清单脚本）
  reviews_prev/<表>.prior-<时间>.{md,json,fixlog.txt,round1.md}   再上一次重写的旧文件（S4 重写准备；同一个时间）
  reviews_prev/<表>.<时间>.md   其他被替换下来的审读（S6）
  prev/docs/<表>.json        重写前的旧文档（写作者看不到的位置）
  blocked/docs/<表>.json     blocked 的文档；blocked/<表>.validate.txt 是它的 FAIL 原文
  next.json  status.json     最近一次 --next / --json 的输出
  validation.json            全量校验报告（S9；只能由不带 --only 的 validate 写）
  digest/                    digest.md、digest.json（S10b）
  catalog/                   起点目录 + T5 的修改（S10a、S10c）
  catalog_plan.md            分组方案（S10c）
  fragments/<组名>.json       片段（S10d）
  merge_report.txt           合并输出（S10e）
  merged/                    合并后的目录；手工修正只改这里（S10f）
  catalog_changes.md         手工修正记录（不放进 merged/）
  onto/ontology.json         构建结果（S10g）
  site/                      概念页、index.md（catalog render）
  site/semantics/            表语义页（semantic render）
  round1/                    sheet.md、answers.md、grading.md、grades.yaml、score/（S11；几套题就 round1、round2 …）
  catalog_touched.txt        旧目录里提到本轮表的条目（S10a 走 C 时）
  confirmations/<日期>.json   owner 的回答（S12）
  RESULT.md                  交付报告（S13）
$SCRATCH/<表>/               该表子代理的私有临时目录（目录名含表名）
$SCRATCH/<组名>/、check-<组名>/  片段子代理的临时目录与自检目录
```

文件规则：

- 子代理的临时文件只放 `$SCRATCH/<表>/`（或 `$SCRATCH/<组名>/`），文件名带表名，不用 `doc.json`、`orig.json` 这类通用名。
  几个子代理共用一个 scratchpad，通用名会互相覆盖。
- 文件放回 `docs/<表>.json` 之前，先确认文件里的 `table` 就是 `<表>`。
- Write 工具写 `$RUN` 被钩子拦截时：先写 `$SCRATCH/<表>/` 下同名文件，再 `cp` 过去。
- `.prior.md`、`.prior.json`、`.fixlog.txt`、`reviews_prev/`、`prev/` 里的文件 `status` 都不读；不要删，交付时留着。
  `reviews/` 下别放其他 `.md`：`status` 把不以 `.prior.md` 结尾的 `.md` 都当成一张表的审读。

