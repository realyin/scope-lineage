[English](../en/domain-profile.md) | 中文

# 领域配置（`domain-profile/1`）

Scope Lineage 不绑定业务领域：包里只带通用的默认值。一个业务用来表示限定、事件、度量和生命周期状态的词，
以及一个数仓用来标记全量快照表或增量表的表名后缀，都作为数据传进来——由调用方用 `--domain-profile` 传一份 JSON
文件，或者放进环境变量 `SCOPE_LINEAGE_DOMAIN_PROFILE`（见下文）。包级架构测试
（`tests/architecture/test_domain_neutral_literals.py`）保证包内的字符串字面量里没有公开的借贷、金融领域词，也没有
`df` / `di` 这类表名后缀（唯一的豁免列在该测试的豁免表里并写明理由：修剪注释尾部的存储后缀，不判角色和种类）。

## 谁读它

| 命令 | 读取的部分 | 不给配置时 |
| --- | --- | --- |
| `semantic packet` | `table_name_convention` | 每张输入表的 `name_convention` 都是 `unknown`，没有一张是 `full_snapshot`，所以第 9 项「全量快照上写了 incremental」的失败不会触发 |
| `semantic validate` | `qualifier_terms` | 第 12 项只找通用限定词 增值税、税、手续费、测试 |
| `ontology` | `concept_words`、`table_name_convention` | 概念层用自带的通用词表投票、排序；任何表名后缀都不说明一张表是哪一份副本：成员角色不按后缀判 `snapshot`，`increment_with_event_time` 这条种类票不出现，没有注释的表按完整短表名命名（`ods.gadget_df` → `gadget_df`）；表族（`families[]` 与待确认问题的分组）只折 `_tmp` / `_bak` / `_new` / `_old` 和数字段，`ods.gadget_di` 和 `ods.gadget_df` 是两个族 |

每个命令只读自己那一部分、忽略其余部分，所以一次运行用同一份文件即可。文件读不了、`doc_format` 不对、有未知的键、
值的形状不对时，退出码 2，并指出是哪个字段。

## 用环境变量传

三个命令在没给 `--domain-profile` 时读环境变量 `SCOPE_LINEAGE_DOMAIN_PROFILE`（非空才算）：一次运行设一次，
每条命令都拿到同一份配置。两者都给时以命令行参数为准。读到配置时，命令在 stderr 打一行，写明用的是哪份文件、
来自参数还是环境变量，免得环境里残留的设置悄悄改变输出。变量指向的文件读不了或不合格式时，同样退出码 2，报错里写明
路径来自 `SCOPE_LINEAGE_DOMAIN_PROFILE`。

runbook（`skills/scope-lineage-ontology`）用 `init_run.py --domain-profile <文件>` 把路径写进运行目录的 `env.sh`，
`runlib.sh` 再把它导出成这个变量，所以 runbook 里的 `semantic packet`、`semantic validate`、`ontology` 都读同一份配置。

## 格式

```json
{
  "doc_format": "domain-profile/1",
  "qualifier_terms": ["运费", "优惠券"],
  "table_name_convention": {
    "full": ["df", "da", "full", "snapshot", "hf", "mf", "wf", "all"],
    "incremental": ["di", "hi", "inc", "incr", "delta", "mi", "wi"]
  },
  "concept_words": {
    "event": ["下单", "发货", "退货"],
    "entity": ["商品", "门店"],
    "summary": ["周报"],
    "measure_suffixes": ["运费", "销量"],
    "filter_words": ["已发货", "未发货", "已签收"]
  }
}
```

这就是 `examples/domain-profile/domain-profile.json`，一个合成的零售示例。

| 键 | 形状 | 含义 |
| --- | --- | --- |
| `doc_format` | `"domain-profile/1"` | 必填 |
| `qualifier_terms` | 字符串列表 | 加到第 12 项通用限定词上的限定词。中文词成词时才算（见[表语义](table-semantics.md)第 12 项）；拉丁字母的词按整词匹配，不分大小写 |
| `table_name_convention` | 含 `full` 和/或 `incremental` 的对象，各是一个后缀列表 | 表名最后一段以 `_<后缀>` 结尾的表为 `full`（每个分区一份全量）或 `incremental`。后缀只含字母和数字，不写前面的 `_`，不分大小写；先试 `full`。材料包按它给输入表标 `name_convention`；概念层（`ontology`）按它判成员角色（无表外列的 `full` 表是主副本、`incremental` 表是快照副本）、给增量表投 `increment_with_event_time` 票、在判定维度概念时排除增量表，在给没有注释的表取名时去掉这些后缀，表族（`families[]` 与待确认问题的分组）也按它折叠副本（`full` 与 `incremental` 的并集） |
| `concept_words` | 含 `event`、`entity`、`summary`、`measure_suffixes`、`filter_words` 中任意几个的对象，各是一个字符串列表 | 加到概念层通用词表上的词：前三个是概念种类的词票（中文按子串，拉丁字母按整词），`measure_suffixes` 与 `filter_words` 把一条名字候选标成说的是度量或概念的一个切片，而不是概念本身（见[键折叠候选](ontology-doc.md)的 `junk_reason`） |

除 `doc_format` 外每个键都可省略；每个列表都是加在自带通用词表之上，而不是替换它；空配置什么都不改变。

## 从语料生成配置

领域配置不需要凭记忆手写：数仓的约定已经写在语料里，比如表名后缀、表怎样被读取、列注释和表注释。生成配置分五步：

1. 工具从语料里数出证据（`domain-profile evidence`）；
2. 模型读证据，写出配置草稿和逐条理由（写作提示词是 `skills/scope-lineage-ontology/references/domain-profile-prompt.md`）；
3. 工具核对草稿（`domain-profile check`）；
4. 人对「待确认」的条目逐条拍板，答复写成 `confirmed.json`，确认的条目加进草稿；
5. 工具连同人的答复再核对一次，然后启用。

工具在这里只报观察，不替你下结论；证据不足以下定论的地方，一律留给人。runbook 里这一步是 S2a
（`skills/scope-lineage-ontology/references/steps/S2a.md`）。

```bash
# 1. 数证据：只读已解析的语料和元数据，不调模型
scope-lineage domain-profile evidence \
  --lineage out/artifacts --schema table_metadata/ \
  --out profile/

# 2. 写草稿：把写作提示词和 profile/evidence.md 交给模型，模型写出
#    profile/domain-profile.draft.json 与 profile/domain-profile.reasons.md

# 3. 核对草稿
scope-lineage domain-profile check \
  --profile profile/domain-profile.draft.json \
  --reasons profile/domain-profile.reasons.md \
  --evidence profile/evidence.json

# 4. 人对「待确认」逐条拍板，答复写成 profile/confirmed.json，确认的条目加进草稿

# 5. 连同答复再核对一次；通过后复制为正式文件
scope-lineage domain-profile check \
  --profile profile/domain-profile.draft.json \
  --reasons profile/domain-profile.reasons.md \
  --evidence profile/evidence.json \
  --confirmed profile/confirmed.json
cp profile/domain-profile.draft.json profile/domain-profile.json
```

### `domain-profile evidence`

| 参数 | 含义 |
| --- | --- |
| `--lineage` | `parse` 的输出目录（或单个 `lineage.json`），与 `semantic packet --lineage` 相同。必填 |
| `--schema` | 元数据，与 `parse --schema` 相同。必填：没有元数据，工具认不出不叫常见名字的分区列，读法统计会悄悄失真 |
| `--schema-fallback` | 与 `semantic packet` 相同，可重复 |
| `--metadata-patch` | 与 `semantic packet` 相同，可重复。runbook 里打了补丁就同样带上，保证证据读到的注释和材料包是同一份 |
| `--out` | 输出目录，写 `evidence.json`（`domain-profile-evidence/1`，全量，给 `check` 用）与 `evidence.md`（给模型读） |

只看语料读过或写过的表（「语料表」），不读任何领域配置，输出里也不带包内的业务词。成功时 stdout 打一行摘要：

```
Evidence for 12 corpus table(s), 12 found in metadata (100%): 4 suffix(es) -- 1 incremental, 0 pending, 3 without suggestion; qualifier material 16 entries, concept material 25 entries (truncated 0)
```

退出码 0 为写出了证据，2 为用法错误或输入读不了。语料表在元数据里查到的比例低于 80% 时照常写出证据，但所有后缀都不给建议，
`notes` 和 `evidence.md` 开头写明原因。

**表名后缀**：取每张语料表名最后一段（小写、去掉反引号）最后一个 `_` 之后的部分，只含字母和数字（表名没有 `_` 的不计）。
按后缀汇总下游每条语句读这类表时分区怎么取，统计单位是「一条语句读一张表」：

| 读法 | 含义 |
| --- | --- |
| `equality` | 只取一个分区 |
| `multi_equality` | 取几个固定分区（例如两个时点对比） |
| `range` | 按范围取 |
| `unconditioned` | 表有分区，这次读取却没带分区条件 |
| `unpartitioned` | 表本身没有分区 |

每种读法另附最多三种典型写法，除运算符、SQL 关键字和函数名外一律打码（分区列写成「分区列」，其他列写成「列」，常量写成「常量」），
方便人看出读法判定的粗糙之处：`substr(分区列, 常量, 常量) = 常量` 实际取一个月，却算作 `equality`。写入一侧只是观察：写这类表的语句数、
其中按窗口型业务日期筛选上游的条数、静态与动态分区写入的条数。

「带分区条件的读取」是 `equality`、`multi_equality`、`range` 之和；`multi_equality` 计入分母，不计入任何一类的分子。阈值原样写在
`evidence.json` 的 `suffix_rules` 里：

| 观察 | 条件 |
| --- | --- |
| `range_reads` | 至少 3 张表有带分区条件的读取，带分区条件的读取至少 5 次，其中 `range` 不少于 90% |
| `single_partition_reads` | 同样的门槛，`equality` 不少于 90% |
| `mixed` | 够门槛，但两者都不到 90% |
| `too_few` | 不够门槛 |

| 建议 | 条件 |
| --- | --- |
| `incremental` | 观察为 `range_reads`：对全量快照按范围读会重复计数，这个方向的推断站得住 |
| 待确认（倾向全量） | 观察为 `single_partition_reads`；语料里至少有一条写入这类表的语句，且没有一条按窗口日期筛选上游；`unconditioned` 读取不超过这类有分区表全部读取的 10% |
| 待确认（无倾向） | 观察为 `single_partition_reads`，但上面任一条件不满足（写明是哪一条） |
| 无 | 观察为 `mixed` 或 `too_few` |

只看读法分不出「每个分区一份全量」和「每天只取当天那一批增量」（沿分区传递的增量链路在 SQL 里和全量链路没有区别），
所以**工具从不直接建议 `full`**。够不上门槛、也没有任何分区读取的后缀（多半是表名里的普通单词）在 `evidence.md` 里合并成一行；
只写不读的后缀单独列在 `write_only_suffixes`。

**材料**：修饰词材料是语料里被用到的列（取值、条件、JOIN 键、GROUP BY）的注释和语料表的表注释，各自去重、按出现次数列出、
带一个出处，数值列排在前面；概念词材料是表注释、写入语句键列（GROUP BY、JOIN 键）的注释，以及表名词元（对完整表名取连续的字母和数字串，
与概念层投票的切法一致）。注释先查 `--schema`（及 fallback、补丁），查不到时用 lineage 里解析时带进来的注释，`from` 写明来自哪一份。
`builtin` 列出包内置的修饰词和概念词。`evidence.md` 的修饰词材料最多列 1200 条（数值列的注释排在最前，其余按出现次数），概念词材料最多列 400 条（按出现次数）；超出时写明「另有 N 条未列出，见 evidence.json」。

### 写草稿与理由

模型按写作提示词写两份文件：`domain-profile.draft.json`（`domain-profile/1`）和 `domain-profile.reasons.md`（分「已写入」「待确认」两节）。
草稿里的每一个条目在「已写入」都占一行，键写完整路径；`check` 按「键路径 + 值」对应，冒号用全角或半角都可以：

```
- `table_name_convention.incremental` `inc`：带分区条件的读取全是范围读（12/12）。依据：evidence 后缀 inc
- `qualifier_terms` `运费`：多个金额列的注释写明运费口径。依据：shop.order_inc.freight_amt 的注释
```

证据标为「待确认」或没有建议的后缀，以及拿不准的词，都放「待确认」，不写进草稿。模型不得写 `confirmed.json`，也不得在理由里声称已经过人工确认。

### 人确认（`confirmed.json`）

人看理由文件的「待确认」一节逐条拍板。后缀最直接的判断办法，是挑这类表里的一张，比较相邻两个分区的行数：行数接近、且大体随时间缓慢增长，
每个分区是一份全量，归 `full`；行数差很多、各分区只有当天新增的量级，每个分区是一批增量，归 `incremental`；判断不了就不写。
答复由编排者（或人自己）照写成 `domain-profile-confirmations/1`，`accept` 的条目加进草稿，理由行挪到「已写入」：

```json
{
  "doc_format": "domain-profile-confirmations/1",
  "confirmed_by": "<姓名>",
  "confirmed_at": "2026-11-22",
  "entries": [
    {"key": "table_name_convention.full", "value": "<后缀>", "decision": "accept"},
    {"key": "qualifier_terms", "value": "<词>", "decision": "reject", "note": "只是一列的说明"}
  ]
}
```

### `domain-profile check`

| 参数 | 含义 |
| --- | --- |
| `--profile` | 要核对的配置。必填 |
| `--reasons` | 理由文件。不带 `--format-only` 时必填 |
| `--evidence` | `evidence.json`。不带 `--format-only` 时必填 |
| `--confirmed` | 人的答复。给了就放行其中 `accept` 的后缀归类 |
| `--lineage` | 可选。给了就检查证据是否过期 |
| `--format-only` | 只查格式，用于核对人手改过的正式配置；这时只需要 `--profile` |

格式与各命令读 `--domain-profile` 时用同一套校验，一次只报第一条。判断一个词是否有依据，用的是下游命令匹配这个词时的同一套规则，
所以过了核对的词，下游一定用得上：

| 草稿里的条目 | 有依据的条件 |
| --- | --- |
| `table_name_convention.incremental` 的后缀 | 证据的建议是 `incremental`，或 `confirmed.json` 里有这一条的 `accept` |
| `table_name_convention.full` 的后缀 | `confirmed.json` 里有这一条的 `accept` |
| `qualifier_terms` 的词 | 按第 12 项的成词规则，在修饰词材料里至少命中一条注释 |
| `concept_words.event` / `entity` / `summary` | 按概念层投票的规则（中文按子串，拉丁字母按整词、不分大小写），在概念词材料里至少命中一条 |
| `concept_words.measure_suffixes` | 某条概念词材料以它结尾 |
| `concept_words.filter_words` | 某条概念词材料包含它 |

错误（任何一条都退出 1，依据错误一次全部列出）：格式不对；某个条目没有依据；草稿里的某个条目在「已写入」里没有对应行；
`confirmed.json` 格式不对，或其中 `accept` 的条目不在草稿里；`confirmed.json` 里 `reject` 的条目出现在草稿里。`accept` 只放行后缀的归类，
词即使被 `accept` 仍要满足材料依据（这个词下游匹配不到）。

提示（不影响退出码）：证据建议了 `incremental`、草稿里没写的后缀；加了这个词以后命中的注释集合与只用内置词时完全相同；重复的条目；
工具版本与证据记下的不同；给了 `--lineage` 时，它的内容摘要与证据记下的不同（目录下全部 `lineage.json` 按相对路径排序，逐个算 sha256，
再把这些串起来算一次 sha256；元数据不参与，因为 `--schema` 往往是整个数仓的目录）。

| 退出码 | 含义 |
| --- | --- |
| 0 | 没有错误，可以有提示 |
| 1 | 有错误。草稿不是合法 JSON 也算 1，因为这是写作的错误，应当重写 |
| 2 | 用法错误，或文件读不了 |

第 3 步不过，就把 `check` 的输出连同证据交回模型重写，最多两轮；两轮后仍不过，由人处理。第 5 步不过，说明答复和草稿对不上，由编排者或人改正。

### 什么时候重新生成

- 语料换了一批，或新加了别的数仓的表；
- 元数据（注释、分区信息）更新过，或打了新的补丁；
- 工具升级后，内置词表或读法判定变了（`check` 会提示）；
- 下游命令的输出里出现明显的约定问题（例如某类表一直没被认成全量快照）。

同一次运行自始至终用同一份配置：配置变了，材料包要从头重建（`packet_digest` 会变），`ontology` 也要重跑。

## 恢复以前的默认值

这次改动之前，包里把两套表名后缀约定和几个借贷、支付领域的词当作默认值。依赖它们的下游项目，把它们写进自己的
配置就能保持原来的行为：

- 材料包原来的后缀是 `_df` / `_da` / `_full` / `_snapshot` 为全量，`_di` / `_hi` / `_inc` / `_incr` / `_delta`
  为增量；
- 概念层原来的后缀是 `_df` / `_hf` / `_mf` / `_wf` / `_all` 为全量，`_di` / `_hi` / `_mi` / `_wi` 为增量；
  表族原来折掉的后缀就是概念层这一套。

现在两者读同一个 `table_name_convention`，上面示例里的列表是两套的并集。并集让每一层都多认几个后缀：只想逐字
保留某一层原来的读法时，只写那一层原来的列表。自己的限定词写进 `qualifier_terms`，自己的事件词、度量后缀和
生命周期筛选词写进 `concept_words`。带和不带这条约定生成的材料包，`name_convention` 与 `full_snapshot` 不同，
`packet_digest` 也就不同：同一次运行每次都用同一份配置重建材料包。概念层同理：不带约定时成员角色、种类票和
无注释表的名字会变，同一个语料每次都用同一份配置跑 `ontology`。
