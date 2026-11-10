# runbook 模板：编排者检查清单、子代理提示词 T1–T8、账本与交付报告

配合 [`runbook.md`](runbook.md) 用。编排者读 runbook；子代理只拿到这里的**一份**填好的模板。

## 文件对照

每份模板是 `templates/` 下的一个文件。编排者不用打开 T1–T8：`fill` 按名字找到它们。

| 模板 | 文件 |
| --- | --- |
| 编排者检查清单 | [`templates/checklist.md`](templates/checklist.md) |
| T1 写作（S4、S5） | [`templates/T1.md`](templates/T1.md) |
| T2 审读：首审 / 重写后首审（S6） | [`templates/T2.md`](templates/T2.md) |
| T3 复审（S8） | [`templates/T3.md`](templates/T3.md) |
| T4 修订（S7、S8） | [`templates/T4.md`](templates/T4.md) |
| T5 目录起草第 2 步：概念、标识符、关系、共用码值集与分组方案（S10c） | [`templates/T5.md`](templates/T5.md) |
| T6 目录片段（S10d、S10e） | [`templates/T6.md`](templates/T6.md) |
| T7 作答（S11） | [`templates/T7.md`](templates/T7.md) |
| T8 判分（S11） | [`templates/T8.md`](templates/T8.md) |
| 运行账本模板（`$RUN/ledger.md`） | [`templates/ledger.md`](templates/ledger.md) |
| 交付报告模板（`$RUN/RESULT.md`） | [`templates/result.md`](templates/result.md) |

## 怎么填模板

用 `env.sh` 里的函数 `fill`（runbook 0.1）填，不要手工复制替换：

```bash
fill write "$SCRATCH/prompts/T1-write-<表>-r1.md" TABLE=<库.表> MODE=新写 FACTS=无 CORRECTIONS=无 CONCEPT="不写 concept" FAILURES=无; echo "exit=$?"
fill write "$SCRATCH/prompts/T1-write-<表>-r2.md" TABLE=<库.表> MODE=补失败 FACTS=无 CORRECTIONS=无 CONCEPT="不写 concept" FAILURES=@"$SCRATCH/<表>.failures.txt"; echo "exit=$?"
```

- `fill` 自动把 `{ENV}`、`{RUN}`、`{TOOL}`、`{SKILL}`、`{SCHEMAS}`、`{SCRATCH}`、`{TASKS}`、`{PAGES}`、`{SEMPAGES}` 换成 `env.sh` 里的绝对路径，
  给了 `ROUND=<目录>` 时 `{ROUND_NAME}` 换成这个目录的最后一段（例如 `round2`）；
  其余占位按命令行的 `KEY=值` 换；值写成 `@文件` 时取那个文件的内容（贴多行报错用）。
- 模板可以写编号，也可以写名字：T1 写作 / write、T2 审读 / review、T3 复审 / rereview、T4 修订 / fix、
  T5 目录起草 / catalog、T6 片段 / fragment、T7 作答 / answer、T8 判分 / grade。手册里的命令都写名字。
- 下面几种情况 `fill` 都退出 1、不能发：参数不属于这个模板（多半是模板选错了）；`MODE` 不是这个模板的取值；
  模板或模式的前提不成立（复审要有 `reviews_prev/<表>.round1.md`；修订要有 `reviews/<表>.md`；有 `reviews/<表>.prior.md`
  时审读只能用「重写后首审」，没有时只能用「首审」；写作新写时，有 `reviews/<表>.prior.md` 就要写 `CORRECTIONS=@<修正点清单>`，
  没有就写 `CORRECTIONS=无`）。照报错改命令，不要删参数硬过。前提规则写在每个模板标题下那行 `<!-- fill: … -->` 注释里，
  这行不会进子代理的提示词。
- 还有没填的占位时它照样写出文件，但退出 1 并打印「未填的占位：…」。**`exit=0` 才能发。**
- 派发时两种做法等价：把输出文件的全部内容原样粘贴给子代理；或者只告诉它「用 Read 工具完整读 `<输出文件绝对路径>`，照里面的要求做，读不完就分段读」。不要改写、删减。然后在账本「派发记录」记一行，再 `note`。

各占位的含义（路径一律绝对路径）：
   - `{TABLE}`：`库.表`；`{GROUP}`：组名；`{ROUND}`：本轮验收目录（例如 `<RUN>/round1`）；
   - `{ENV}`、`{RUN}`、`{TOOL}`、`{SKILL}`、`{SCHEMAS}`、`{SCRATCH}`、`{TASKS}`、`{PAGES}`、`{ROUND_NAME}`：`fill` 自动填；
   - `{MODE}`：只能填模板标题下那行 `fill:` 注释里列出的值（例如 T4 是「首修 / 核对」），填别的 `fill` 会拒绝；
     只属于别的模式的段落可以删掉。
   - `{FACTS}`：调用方附带的已确认事实（owner 确认过的业务事实，每条一行）；没有写「无」。
   - `{CORRECTIONS}`（T1）：重写时写 `@<修正点清单文件>`（runbook S4 用脚本生成）；第一次写和补失败写「无」。
   - `{CONCEPT}`（T1）：有本体目录时写「concept 写 <concept id> / <表现类型>」（用 `sl catalog query <onto>/ontology.json table <表> --json` 查），否则写「不写 concept」。
   - `{FAILURES}`（T1）：补失败模式贴 S5 打印的 FAIL / WARN 行原文；新写写「无」。
   - `{SIZE}`（T5）：「小样：只分 1 组，组名 main」或「扩表：按概念分组」。
   - `{TOUCHED}`（T5）：增量模式写 `@<RUN>/catalog_touched.txt`（runbook S10a 的 C 生成）；新建模式写「无」。
   - `{DECISIONS}`（T5）：`<RUN>/owner_decisions.md` 存在时写 `@<RUN>/owner_decisions.md`，不存在时写「无」（`fill` 会核对）。
   - `{REWORK}`（T5、T6）：返工时贴要改的报错原文；第一次派发写「无」。
   - `{ROUND_LABEL}`（T8）：轮次标签（例如 `r1`）。

输出文件就是存档：放在 `$SCRATCH/prompts/<编号>-<名字>-<表、组或 ROUND 目录名>[-<轮次>].md`（例如 `T4-fix-<表>-1.md`），中断后照它重派。
