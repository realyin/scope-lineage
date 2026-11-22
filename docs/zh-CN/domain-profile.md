[English](../en/domain-profile.md) | 中文

# 领域配置（`domain-profile/1`）

Scope Lineage 不绑定业务领域：包里只带通用的默认值。一个业务用来表示限定、事件、度量和生命周期状态的词，
以及一个数仓用来标记全量快照表或增量表的表名后缀，都作为数据传进来——由调用方用 `--domain-profile` 传一份 JSON
文件。包级架构测试（`tests/architecture/test_domain_neutral_literals.py`）保证包内的字符串字面量里没有公开的借贷、
金融领域词，也没有 `df` / `di` 这类表名后缀（尚未迁出的两处列在该测试的豁免表里并写明理由）。

## 谁读它

| 命令 | 读取的部分 | 不给配置时 |
| --- | --- | --- |
| `semantic packet` | `table_name_convention` | 每张输入表的 `name_convention` 都是 `unknown`，没有一张是 `full_snapshot`，所以第 9 项「全量快照上写了 incremental」的失败不会触发 |
| `semantic validate` | `qualifier_terms` | 第 12 项只找通用限定词 增值税、税、手续费、测试 |
| `ontology` | `concept_words`、`table_name_convention` | 概念层用自带的通用词表投票、排序；任何表名后缀都不说明一张表是哪一份副本：成员角色不按后缀判 `snapshot`，`increment_with_event_time` 这条种类票不出现，没有注释的表按完整短表名命名（`ods.gadget_df` → `gadget_df`） |

每个命令只读自己那一部分、忽略其余部分，所以一次运行用同一份文件即可。文件读不了、`doc_format` 不对、有未知的键、
值的形状不对时，退出码 2，并指出是哪个字段。

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
| `table_name_convention` | 含 `full` 和/或 `incremental` 的对象，各是一个后缀列表 | 表名最后一段以 `_<后缀>` 结尾的表为 `full`（每个分区一份全量）或 `incremental`。后缀只含字母和数字，不写前面的 `_`，不分大小写；先试 `full`。材料包按它给输入表标 `name_convention`；概念层（`ontology`）按它判成员角色（无表外列的 `full` 表是主副本、`incremental` 表是快照副本）、给增量表投 `increment_with_event_time` 票、在判定维度概念时排除增量表，并在给没有注释的表取名时去掉这些后缀 |
| `concept_words` | 含 `event`、`entity`、`summary`、`measure_suffixes`、`filter_words` 中任意几个的对象，各是一个字符串列表 | 加到概念层通用词表上的词：前三个是概念种类的词票（中文按子串，拉丁字母按整词），`measure_suffixes` 与 `filter_words` 把一条名字候选标成说的是度量或概念的一个切片，而不是概念本身（见[键折叠候选](ontology-doc.md)的 `junk_reason`） |

除 `doc_format` 外每个键都可省略；每个列表都是加在自带通用词表之上，而不是替换它；空配置什么都不改变。

## 恢复以前的默认值

这次改动之前，包里把两套表名后缀约定和几个借贷、支付领域的词当作默认值。依赖它们的下游项目，把它们写进自己的
配置就能保持原来的行为：

- 材料包原来的后缀是 `_df` / `_da` / `_full` / `_snapshot` 为全量，`_di` / `_hi` / `_inc` / `_incr` / `_delta`
  为增量；
- 概念层原来的后缀是 `_df` / `_hf` / `_mf` / `_wf` / `_all` 为全量，`_di` / `_hi` / `_mi` / `_wi` 为增量。

现在两者读同一个 `table_name_convention`，上面示例里的列表是两套的并集。并集让每一层都多认几个后缀：只想逐字
保留某一层原来的读法时，只写那一层原来的列表。自己的限定词写进 `qualifier_terms`，自己的事件词、度量后缀和
生命周期筛选词写进 `concept_words`。带和不带这条约定生成的材料包，`name_convention` 与 `full_snapshot` 不同，
`packet_digest` 也就不同：同一次运行每次都用同一份配置重建材料包。概念层同理：不带约定时成员角色、种类票和
无注释表的名字会变，同一个语料每次都用同一份配置跑 `ontology`。
