## 附录 A 决策表：`status` 显示什么 → 下一步

先看账本，再看这张表。「账本」指 `$RUN/ledger.md` 里这张表的记录。

| `status` 显示 | 账本 / 文件情况 | 下一步 | 谁做 |
| --- | --- | --- | --- |
| `no_packet` | — | S3：核对 `tables.txt` 拼写（不带 catalog 前缀）后建材料包 | 编排者 |
| `packet` | 没写过，或写作被中断 | S4 新写 | T1 |
| `drafted packet_stale` | — | S4 重写准备 → 修正点清单 → T1 新写（带清单）；之后首审带旧审读 | T1 → T2 |
| `drafted invalid` | 写作第 1 轮 | S5 补失败 | T1（补失败） |
| `drafted invalid` | 写作第 2 轮，或修订两轮后 | S5 标 blocked | 编排者 |
| `valid` | 没有 `.prior.md` | S6 首审 | T2 |
| `valid` | 有 `reviews/<表>.prior.md` | S6 重写后首审 | T2（带旧审读） |
| `valid review_packet_stale` | — | 旧审读移到 `reviews_prev/` → S6 首审 | T2 |
| `valid review_stale` | 刚做过确认回写 | `sl semantic fixed "$RUN" --only <表>` | 编排者 |
| `valid review_stale` | 其他 | 旧审读移到 `reviews_prev/` → S6 首审，记进问题清单 | T2 |
| `reviewed` | — | S7 修订（存修订记录） | T4（首修） |
| `reviewed fix_unconfirmed` | 刚做过确认回写 | `sl semantic fixed "$RUN" --only <表>` | 编排者 |
| `reviewed fix_unconfirmed` | 修订被中断，或其他 | S7 核对模式 | T4（核对） |
| `reviewed review_unparsed` | — | 审读移到 `reviews_prev/<表>.unparsed.md` → S6 首审 | T2 |
| `fixed` | 首审 H ≥ 1，还没复审 | S8 复审（先备份首轮审读） | T3 |
| `fixed` | 其他 | 等其余表；全部 `fixed` 后 S9 | 编排者 |
| `fixed render_stale` | — | S9（有目录再 S10g） | 编排者 |
| `rendered` | — | 完成 | — |
| 任何阶段 + `doc_misfiled` | — | 停：用 S4 的 python 命令看每个 `docs/*.json` 的 `table`，把文件改名为 `docs/<table>.json`，同一张表只留一个文件；查是哪个子代理写错的 | 编排者 |
| （不出现在 `status`） | 在 `blocked.txt` | 不派任何子代理；S13 报告里列出 | — |

几条硬规则：

- 复审只在首审有高级时做一次；复审前备份到 `reviews_prev/<表>.round1.md`。
- 低级问题不修：高 + 中 = 0 的表就是 `fixed`，不派修订。
- 被中断的调用不计轮次；完成的写作 2 轮、修订 2 次仍有 FAIL 就 blocked。
- 「材料包变了」一律整份重写（重写准备 + 修正点清单），不允许只改 `packet_digest`。
- 每次 T4 回报后都把回复存进 `reviews/<表>.fixlog.txt`（S7）：下次重写的修正点清单靠它。

