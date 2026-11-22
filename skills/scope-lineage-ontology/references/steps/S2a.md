## S2a 从语料生成领域配置（可选）

**目的**：S0 没有现成的领域配置（`env.sh` 的 `DOMAIN_PROFILE` 为空）时，在 S3 建材料包之前，从语料生成一份
`domain-profile/1`：工具数证据，子代理写草稿和理由，工具核对，owner 拍板「待确认」的条目，再核对一次后启用。
证据只依赖 S1 的解析结果；放在 S2 之后，是因为 S3 是第一个读配置的步骤。工具只报观察，从不直接建议 `full`：
单分区读为主的后缀一律「待确认」，由 owner 定。

**前提检查**

- S1 完成，`$RUN/artifacts` 下有 `lineage.json`；S2 完成。
- `DOMAIN_PROFILE` 为空。不为空就跳过本步（进度脚本显示 `[-] S2a`），直接 S3。
- `$RUN/profile/DECISION` 不存在。存在说明本步已经定了，直接 S3。
- 不做这一步（owner 说不需要）：写 `DECISION` 为 `skipped 不需要` 后去 S3，照旧不带配置运行：

```bash
mkdir -p "$RUN/profile" && echo "skipped 不需要" > "$RUN/profile/DECISION"; echo "exit=$?"
```

**命令**

```bash
. "$RUN/env.sh"
mkdir -p "$RUN/profile" "$SCRATCH/profile"
# 1. 数证据（PATCH 为空用 A，非空用 B）
# A：PATCH 为空
sl domain-profile evidence --lineage "$RUN/artifacts" --schema "$SCHEMA" --out "$RUN/profile"; echo "exit=$?"
# B：PATCH 非空
sl domain-profile evidence --lineage "$RUN/artifacts" --schema "$SCHEMA" --metadata-patch "$PATCH" --out "$RUN/profile"; echo "exit=$?"
# 2. 派写作子代理（模板 T-domain-profile），回报后核对
fill domain-profile "$SCRATCH/prompts/T-domain-profile-r1.md" MODE=首写 REWORK=无; echo "exit=$?"
sl domain-profile check --profile "$RUN/profile/domain-profile.draft.json" \
  --reasons "$RUN/profile/domain-profile.reasons.md" --evidence "$RUN/profile/evidence.json" \
  > "$SCRATCH/profile/check-r1.txt" 2>&1; echo "exit=$?"
cat "$SCRATCH/profile/check-r1.txt"
# 3. check 退出 1：把输出交回子代理重写（最多两轮），再核对
fill domain-profile "$SCRATCH/prompts/T-domain-profile-r2.md" MODE=重写 REWORK=@"$SCRATCH/profile/check-r1.txt"; echo "exit=$?"
```

**4. 停下问 owner。** `check` 退出 0 后，把理由文件 `$RUN/profile/domain-profile.reasons.md` 的「待确认」一节和下面的判断办法给
owner 看，逐条拍板：

- 后缀：先看 `evidence.md` 里这个后缀的读法分布、写入一栏和典型写法。最直接的办法是挑这类表里的一张，比较相邻两个分区的行数：
  行数接近、且大体随时间缓慢增长，每个分区是一份全量，归 `full`；行数差很多、各分区只有当天新增的量级，每个分区是一批增量，归
  `incremental`；判断不了就不写。
- 词：看理由里引用的注释原文，判断它是不是本数仓的业务口径。

**5. owner 答复后**：编排者照答复用 Write 写 `$RUN/profile/confirmed.json`（子代理不写），把 `accept` 的条目加进草稿、
把它们的理由行从「待确认」挪到「已写入」，再带 `--confirmed` 核对一次；退出 0 后启用：

```json
{
  "doc_format": "domain-profile-confirmations/1",
  "confirmed_by": "<owner 姓名>",
  "confirmed_at": "<YYYY-MM-DD>",
  "entries": [
    {"key": "table_name_convention.full", "value": "<后缀>", "decision": "accept"},
    {"key": "qualifier_terms", "value": "<词>", "decision": "reject", "note": "<原因>"}
  ]
}
```

```bash
. "$RUN/env.sh"
sl domain-profile check --profile "$RUN/profile/domain-profile.draft.json" \
  --reasons "$RUN/profile/domain-profile.reasons.md" --evidence "$RUN/profile/evidence.json" \
  --confirmed "$RUN/profile/confirmed.json"; echo "exit=$?"
cp "$RUN/profile/domain-profile.draft.json" "$RUN/profile/domain-profile.json"; echo "exit=$?"
shasum -a 256 "$RUN/profile/domain-profile.json" "$RUN/profile/confirmed.json"
```

然后：用 Edit 把 `env.sh` 里 `export DOMAIN_PROFILE=` 那一行等号右边改成 `$RUN/profile/domain-profile.json` 的绝对路径，
重新 `. "$RUN/env.sh"`；写 `$RUN/profile/DECISION`，一行 `enabled <domain-profile.json 的 sha256>`；账本记一行：
配置文件和 `confirmed.json` 各自的路径与 sha256。

**owner 不在、或不同意启用**：写 `$RUN/profile/DECISION`，一行 `skipped <原因>`，不带配置进 S3。之后 owner 回来、
确认启用了，照第 5 步启用后**回到 S3 重建全部材料包**（`packet_digest` 会变），`ontology` 也要重跑。

**产出与自检**

- `evidence` 的摘要行 `Evidence for N corpus table(s), M found in metadata (P%): K suffix(es) -- a incremental, b pending, c without suggestion; qualifier material … entries, concept material … entries (truncated …)`；
  `P` 低于 80% 时证据里没有任何后缀建议（`evidence.md` 开头写明原因），把这一行记进问题清单。
- `$RUN/profile/evidence.json`、`evidence.md`、`domain-profile.draft.json`、`domain-profile.reasons.md`。
- `check` 的末行 `Checked N entr(ies): E error(s), H hint(s)`。
- 启用时还有 `confirmed.json`、`domain-profile.json`、`DECISION`；跳过时只有 `DECISION`。

**常见失败与处理**

| 现象（原文） | 退出码 | 处理 |
| --- | --- | --- |
| `evidence` 报 `the following arguments are required: --schema` | 2 | `SCHEMA` 为空。本步需要元数据，没有就跳过本步（`DECISION` 写 `skipped 没有元数据`） |
| `check` 有 `error: 没有依据：…` 或 `error: 缺理由：…` | 1 | 把输出交回子代理重写（第 3 步），最多两轮；两轮后仍不过，停下交 owner |
| 第 5 步 `check` 有 `error: confirmed.json 里 …` | 1 | 答复和草稿对不上：编排者对照 owner 的答复改草稿或 `confirmed.json`，不要改证据 |
| `hint: 证据过期…` | 0 | 证据之后重新解析过语料或换了工具版本：重跑第 1 步，再从第 2 步重做 |

**完成判据**：`$RUN/profile/DECISION` 存在。是 `enabled …` 时，带 `--confirmed` 的 `check` 退出 0，`env.sh` 的
`DOMAIN_PROFILE` 指向 `$RUN/profile/domain-profile.json`，账本已记两份文件的 sha256。

**下一步**：S3。
