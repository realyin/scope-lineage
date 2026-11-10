### "这张表是什么意思 / 给这批表写表语义" — table semantics

一张表对业务读者意味着什么（一行是什么、怎么取数、收哪些记录、每个字段什么意思、要注意什么），由模型按提示词写、
CLI 对照材料包校验、独立审读、修订，再渲染成页面（`semantic packet` / `status` / `validate` / `digest` / `fixed` /
`render` / `confirm`）。**要给一批表写表语义时，照 `references/runbook.md` 的 S0–S9 一步一步做**，派子代理用
`references/runbook-templates.md` 的 T1（写作）、T2 / T3（审读、复审）、T4（修订）；状态与下一步查 runbook 附录 A。
不可违反的三条：

1. **每张表的每一步各是一个独立子代理**：写作、审读、修订互不共享上下文，审读不能是写作者自己（审读用最强模型）。
2. **验收题集不给写作、审读、修订**：那是考卷。
3. **低级问题不修；材料包变了就整份重写**（不许只改 `packet_digest`）；写作或修订两轮后仍有校验 FAIL 的表标为
   blocked，不渲染、不进目录，交 owner。

只读已经渲染好的页面时：✓ 是已确认，⚠ 是矛盾或风险，✗n 是校验未通过（文末「校验」一节），`值（含义待确认）`
是只有值没有含义的码值。格式、十三项检查、确认文件和 `semantic status` 的阶段与标记见
`../../docs/zh-CN/table-semantics.md`。
