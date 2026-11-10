# scope-lineage 分步操作手册（runbook）

这份手册写给**编排者**：用 scope-lineage 从 Spark/Hive SQL 任务生成表语义、本体目录和页面，并用问题集做回归验收。
照字面一步一步做，不需要读别的会话。

- 读法：本页是目录，每一步是 `steps/` 下的一个文件（见下面「文件对照」）。从 [`steps/00-before.md`](steps/00-before.md)（0. 开跑前）读起，然后按 S0 → S13 的顺序做，做到哪一步读哪一个文件。每一步都有七栏：目的 / 前提检查 / 命令 / 产出与自检 /
  常见失败与处理 / 完成判据 / 下一步。前提检查不满足、或完成判据不成立，就停在这一步，不要往下走。
- 子代理（写作、审读、修订、目录起草、片段、作答、判分）由编排者派发。给子代理的话一律用
  [`runbook-templates.md`](runbook-templates.md) 里的填空模板 T1–T8，不要现写。子代理不读本手册。
- 本手册与 `SKILL.md` 或别的文档说法不一致时，以本手册为准，并把不一致记进账本的「问题清单」。
- 例子里的表名都是虚构的（`demo_dwd.dwd_party_customer_info_df` 等，取自仓库 `examples/`）。

## 文件对照

手册里说「S7」「0.2」「附录 A」，指的都是下表对应的文件。子代理的模板 T1–T8、检查清单、账本和交付报告模板见
[`runbook-templates.md`](runbook-templates.md)。

| 节 | 内容 | 文件 |
| --- | --- | --- |
| 0.1–0.4 | 开跑前：`env.sh`、七条调用规则、小样原则、账本与恢复 | [`steps/00-before.md`](steps/00-before.md) |
| 0.5、0.6 | 主流程总览、进度脚本 | 本页 |
| S0 | 环境、版本与运行目录 | [`steps/S0.md`](steps/S0.md) |
| S1 | 血缘解析 | [`steps/S1.md`](steps/S1.md) |
| S2 | 表卡与术语 | [`steps/S2.md`](steps/S2.md) |
| S3 | 选表与材料包 | [`steps/S3.md`](steps/S3.md) |
| S4 | 写作 | [`steps/S4.md`](steps/S4.md) |
| S5 | 校验与 blocked | [`steps/S5.md`](steps/S5.md) |
| S6 | 审读 | [`steps/S6.md`](steps/S6.md) |
| S7 | 修订 | [`steps/S7.md`](steps/S7.md) |
| S8 | 状态推进与复审 | [`steps/S8.md`](steps/S8.md) |
| S9 | 全量校验与渲染表语义页 | [`steps/S9.md`](steps/S9.md) |
| S10 | 本体目录：七小步的总述 | [`steps/S10.md`](steps/S10.md) |
| S10a | 起点目录 | [`steps/S10a.md`](steps/S10a.md) |
| S10b | 起草材料 digest | [`steps/S10b.md`](steps/S10b.md) |
| S10c | 起草概念与分组方案 | [`steps/S10c.md`](steps/S10c.md) |
| S10d | 片段 | [`steps/S10d.md`](steps/S10d.md) |
| S10e | 合并 | [`steps/S10e.md`](steps/S10e.md) |
| S10f | 合并后的手工修正 | [`steps/S10f.md`](steps/S10f.md) |
| S10g | 构建与渲染 | [`steps/S10g.md`](steps/S10g.md) |
| S11 | 回归验收 | [`steps/S11.md`](steps/S11.md) |
| S12 | 确认回写（可选） | [`steps/S12.md`](steps/S12.md) |
| S13 | 交付 | [`steps/S13.md`](steps/S13.md) |
| 附录 A | 决策表：`status` 显示什么 → 下一步 | [`steps/appendix-A.md`](steps/appendix-A.md) |
| 附录 B | 目录与文件约定 | [`steps/appendix-B.md`](steps/appendix-B.md) |
| 附录 C | 报错与退出码速查 | [`steps/appendix-C.md`](steps/appendix-C.md) |
| 附录 D | 成本与并发 | [`steps/appendix-D.md`](steps/appendix-D.md) |

## 0. 开跑前（0.1–0.4 在 [`steps/00-before.md`](steps/00-before.md)）

### 0.5 主流程总览

| 步 | 做什么 | 谁做 | 主要产出 | 模板 |
| --- | --- | --- | --- | --- |
| S0 | 环境、版本、运行目录、账本 | 编排者 | `env.sh`、`TOOL_VERSION`、`ledger.md` | 账本模板 |
| S1 | 血缘解析 | 编排者 | `artifacts/` | — |
| S2 | 表卡与术语 | 编排者 | `corpus/tables.json`、`corpus/glossary.json` | — |
| S3 | 选表与材料包 | 编排者 | `tables.txt`、`packets/` | — |
| S4 | 写作 | 子代理（每表一个） | `docs/<表>.json` | T1 |
| S5 | 校验与 blocked | 编排者 | 校验结论、`blocked.txt` | T1（补失败） |
| S6 | 审读 | 子代理（每表一个） | `reviews/<表>.md` | T2 |
| S7 | 修订 | 子代理（每表一个） | 改过的文档 + 修订回执 | T4 |
| S8 | 状态推进与复审 | 编排者 + 子代理 | 全部 `fixed` | T3、T4 |
| S9 | 全量校验与渲染表语义页 | 编排者 | `validation.json`、`site/semantics/` | — |
| S10 | 本体目录（S10a–S10g） | 编排者 + 子代理 | `catalog/`、`fragments/`、`merged/`、`onto/`、`site/` | T5、T6 |
| S11 | 回归验收 | 编排者 + 子代理 | `round1/score/` | T7、T8 |
| S12 | 确认回写（可选） | 编排者 | 带确认的文档 | — |
| S13 | 交付 | 编排者 | `RESULT.md` | 交付报告模板 |

### 0.6 每一步做完：跑进度脚本

**每一步做完（`note` 之后），跑一次进度脚本，按它打印的「当前」那一步往下做。** 它只读 `$RUN` 里的文件，不改任何东西：

```bash
python3 "$SKILL/scripts/next_step.py" "$RUN"
```

它打印三样东西：

- S0–S13 的进度清单：`[x]` 做完，`[ ]` 没做，`[-]` 跳过（`Q` 为空时的 S11、可选的 S12），`[?]` 不知道；
- 当前步、为什么是它、去读哪个文件（`steps/` 下那一步的文件，绝对路径）；
- 表语义进行中（S4–S9）时，每张表的下一步和模板（附录 A）。

几条读法：

- 它说「当前：刷新状态」，是 `status.json` 不存在或比 `docs/`、`reviews/`、`packets/`、表语义页旧，
  它不知道每张表到了哪一步。照它打印的命令刷新 `status.json`，再跑一次。
- 「做完」只表示这一步该写的文件已经在了，**不表示内容对**。每一步的完成判据仍然要照本手册跑。
- 它和账本、和你的记忆不一致时，以它为准，把不一致记进问题清单。

