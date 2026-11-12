## 编排者检查清单

**开跑前（S0–S3）**

- [ ] `env.sh` 写好，每个 Bash 调用都先 `. <RUN>/env.sh`。
- [ ] `sl --version` 通过版本判断（runbook S0），`TOOL_VERSION` 已写。
- [ ] 写入检查、PyYAML 检查都 `exit=0`；Write 被拦时的「先写 SCRATCH 再 cp」已知晓。
- [ ] `ledger.md` 已由 `init_run.py` 建好，「工具版本」「范围」两行已填；之后每一步最后一条命令是 `note "…"`（runbook 0.4）。
- [ ] `tables.txt` 只有本轮的表：小样 ≤5 张，没有中间表、临时表，不带 catalog 前缀。
- [ ] 材料包 `Packed N table(s)` 的 N 等于 `tables.txt` 行数。
- [ ] 题集来自 owner；没有题集就不做 S11。
- [ ] 模型档位按 runbook 附录 D 定好；并发 ≤5。

**每一轮（S4–S8、S10d、S11 每次派发）**

- [ ] 先跑这一步的 `status --next`（或 runbook 指定的前提检查），只派它列出的表。
- [ ] 同时在跑的子代理 ≤5。
- [ ] 每个子代理只做一张表的一步（片段是一组）；审读和写作不是同一个子代理。`REVIEW_PASSES=2` 时每张表首审后补审一次（S6，T9），补审员不是第一遍的审读员。
- [ ] 用 `fill` 填模板且 `exit=0`；输出文件就是存档。
- [ ] 子代理回报「文件在 SCRATCH、未拷贝」时，编排者代为 `cp` 到目标路径再自检。
- [ ] 子代理回报后，跑 runbook 该步的「产出与自检」，**不只看回报**。
- [ ] 账本更新：轮次（中断的不计）、首审 H/M/L、保留的 WARN、blocked、问题清单。

**交付前（S9–S13）**

- [ ] `tables.txt` 里的表全部 `rendered`；`blocked.txt` 里的表每张都有 `blocked/<表>.validate.txt`。
- [ ] `validation.json` 是不带 `--only` 的全量报告，`tables_with_failures` 为 0。
- [ ] 有目录时：`merge` 退出 0；`catalog validate merged` 0 error；三条渲染命令按顺序、都退出 0。
- [ ] 做了验收时：`ungraded` 为空，`grading.stderr` / `score.stderr` 没有漏答漏判的警告。
- [ ] `RESULT.md` 按交付报告模板写完，问题清单每条有「现象 / 表 / 怎么处理」。
- [ ] 工具仓库没被改动（`TOOL` 非空时 `git -C "$TOOL" status --short` 为空），真实表名只在运行目录里。

