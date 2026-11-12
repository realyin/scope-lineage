你负责目录片段的一个组：`main`。只处理这个组的概念和分给它的表。独立完成，不许派子代理。

**已知**

- 模式：返工
- 每条 Bash 命令都以 `. /RUN/env.sh && ` 开头。
- 读长文件：任何文件（包括提示词）一次读不完、或 Bash 输出被截断时，先 `grep -n '^#' <文件>` 列出小节，再按行号分段读完（Read 的 offset / limit，或 `sed -n '起,止p'`），不要跳过任何小节。
- 写入被拦截：Write 工具写 `/RUN` 下的文件被钩子拦截时，先写到本模板写明的 `/SCRATCH` 路径，再用 Bash 的 `cp` 拷到目标路径——这一步已获调用方授权。`cp` 也被拒绝就不要再试，在回复里写「文件在 <SCRATCH 路径>，未拷贝」，调用方会代为拷贝。

**只读这些**

1. 片段提示词 `/SKILL/references/catalog-fragment-prompt.md`：完整照做。里面的占位这样换：
   `<group>` = `main`，`<catalog-dir>` = `/RUN/catalog`，`<digest-dir>` = `/RUN/digest`，`<docs-dir>` = `/RUN/docs`，
   `<packets-dir>` = `/RUN/packets`，`<fragments-dir>` = `/RUN/fragments`，`<scratch-dir>` = `/SCRATCH`。
   它点名的格式文档只读那三节，示例只看形状。
2. 分配：`/RUN/catalog_plan.md` 的「通用约定」「码值来源表」「组 main」「跨组属性」「已建在目录里的共用码值集」五节。
3. 目录里已有的码值集、属性直接引用，不要用同一个 id 写不同的内容。
   **义务清单**（逐条做，回复里报数）：
   - 你新建的每个 `category: measure` 属性都写 `unit` 和 `additivity`（`additive` / `semi_additive` / `non_additive`，含义同 T5）；
     单位材料没写的，按列注释暂填并在 `notes` 写「待 owner 确认：单位」。
   - 状态列（`category: state`）有码值的：绑到**本表自己的概念**上（事件表的状态列绑在那个 `event` 概念的属性上，不绑到事件
     发生在其身上的 entity 上）。目录里该概念已有这个属性就直接绑定，没有的照常建。只有 `entity` 概念才有 `states`：entity 的
     这个属性在目录里没有对应的 `states` 时，在回复的「需要编排者处理」里列出「<概念> 缺 <属性> 的 states」（不写进 `notes`，
     `notes` 只留给 owner 的问题）——片段不能改概念，`states` 由 T5 返工补。`event`、`role` 概念的状态属性不报缺 `states`。
   - 本表概念**自己的**标识列（分组方案或目录里它是本概念的标识符）绑 `identifier`，哪怕分组方案写错成 `foreign_identifier`；
     在回复「需要编排者处理」里写明你改了哪一列。
   - 分给本组的拉链表（分组方案时间语义写 `zipper`）：有效期开始列、结束列的绑定加 `time_role: valid_from` / `valid_to`，列名取自
     分组方案的说明或 digest 的 Time 一节；两处都没写就读那张表的文档，不要按常见列名猜；
     任何表的分区列绑定加 `time_role: partition`；事件表里事件发生时间列的绑定加 `time_role: event_time`。
   - 分组方案或 owner 决定与本清单不一致时，以 owner 决定为准；`foreign_attribute` 的 `via` 必须是本表已绑 `foreign_identifier` 的列，
     找不到这样的列，就把编码列绑 `foreign_identifier`、名称列按普通属性绑，并在回复「需要编排者处理」里写明。
   - 列名以 `_cd`、`_id`、`_no`、`_code` 结尾、指向另一个概念（有那个概念的标识符）的列绑成 `foreign_identifier`，不要绑成普通属性；
     只是本表自己的编码值的，属性带上 `code_set`。
4. 片段的 `notes` 每条都以「待 owner 确认：」开头（例如「待 owner 确认：remark 是否有业务属性」）；不要自己写「owner 确认」。
   目录里已标 `source: owner` 的条目是 owner 的决定，照它绑定，不要再提问。

**不许读**：任何题集或判分文件；任何别的运行目录；别的组的片段。不改 `/RUN/catalog/`。

**写到哪里**：只写 `/RUN/fragments/main.json`。Write 被拦截时先写 `/SCRATCH/main/main.json` 再 `cp`。
临时文件只放 `/SCRATCH/main/`。

**自检**（退出码 0 才算写完）

```bash
. /RUN/env.sh && rm -rf "$SCRATCH/check-main" && sl catalog merge "$RUN/catalog" "$RUN/fragments/main.json" --out "$SCRATCH/check-main"; echo "exit=$?"
```

每次重跑都先删掉自检目录（目录非空时退出 2）。`Coverage:` 下每张分给本组的表都要有表现（码值来源表除外）。

**返工模式**：只改下面这些问题涉及的条目，别的不动：

```text
一行报错原文
```

**回复**（中文，只写这些行）

```text
组：main
自检：exit=<n>；Merged 行原样
属性 <n>、码值集 <n>、表现 <n>、绑定 <n>（identifier <n> / foreign_identifier <n> / attribute <n> / foreign_attribute <n> / technical <n> / unmapped <n>）
义务清单：度量属性 <n>（有 unit <n>、有 additivity <n>）；带 time_role 的绑定 <n>（valid_from <n> / valid_to <n> / partition <n> / event_time <n>）；缺 states、列进「需要编排者处理」的状态属性 <n>
unmapped 列及原因：…（没有写「无」）
notes 原文：…（没有写「无」）
需要编排者合并后改成 foreign_attribute 的列：…（没有写「无」）
工具 / 提示词问题：每条一句（没有写「无」）
```
