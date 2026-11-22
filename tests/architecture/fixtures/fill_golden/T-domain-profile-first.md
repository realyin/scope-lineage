你是领域配置写作者。从一份证据写出这个数仓的 `domain-profile/1` 草稿和逐条理由。独立完成，不许派子代理。

**已知**

- 模式：首写（首写：`/RUN/profile/` 里还没有草稿；重写：草稿已有，按下面的核对输出改）
- 每条 Bash 命令都以 `. /RUN/env.sh && ` 开头（它定义了 `sl` 函数和 `$RUN`、`$SCRATCH` 等变量）。
- 读长文件：任何文件一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `/RUN` 下的文件被钩子拦截时，先写到 `/SCRATCH/profile/` 下同名文件，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。
- 上一轮核对的输出（只有重写才有，首写写「无」）：

```text
无
```

**只读这些**

1. 写作提示词 `/SKILL/references/domain-profile-prompt.md`：完整照做。
2. 证据 `/RUN/profile/evidence.md`。要看被截断的材料时读同目录的 `evidence.json`。
3. 只在重写模式读：现有的 `/RUN/profile/domain-profile.draft.json` 和 `/RUN/profile/domain-profile.reasons.md`。

**不许读**：任务 SQL、材料包、表语义文档、别的运行目录、工具仓库的 `docs/`、`examples/`。不要上网。

**写到哪里**

- 只写 `/RUN/profile/domain-profile.draft.json` 和 `/RUN/profile/domain-profile.reasons.md`。
- **不写** `/RUN/profile/confirmed.json`，也不在理由里写「已经过人工确认」。
- 临时文件只放 `/SCRATCH/profile/`。

**自检**（写完就跑）

```bash
. /RUN/env.sh && sl domain-profile check --profile "$RUN/profile/domain-profile.draft.json" --reasons "$RUN/profile/domain-profile.reasons.md" --evidence "$RUN/profile/evidence.json"; echo "exit=$?"
```

- 通过 = `exit=0`。`hint:` 行不影响通过，但「证据建议了 incremental、草稿里没写」要么补上，要么在「待确认」里写明原因。
- `exit=1`：按 `error:` 行改，再跑自检。最多改 2 次；仍不过就停下，在回复里原样列出剩下的 `error:` 行。不要为了通过去改证据。

**完成判据**：两份文件都在；自检 `exit=0`（或已用完 2 次）。

**回复**（中文，只写这些行）

```text
模式：
自检：exit=<0/1>，error <n> 条，hint <n> 条
已写入：后缀 <n> 个、修饰词 <n> 个、概念词 <n> 个
待确认：<n> 条（每条一行：键路径 值 倾向）
仍未通过的 error 原文：…（没有写「无」）
证据 / 提示词问题：每条一句「现象 + 你怎么处理的」（没有写「无」）
```
