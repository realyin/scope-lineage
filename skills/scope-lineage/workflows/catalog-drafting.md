### "从表语义起草本体目录" — drafting procedure (digest → fragments → merge)

一批表已经有表语义（`table-semantics/1`）后，本体目录（`catalog-yaml/1`）从它们起草，不写临时脚本：
`catalog digest` → 起草概念、标识符、关系与共用码值集并分组 → 每组一个片段（`catalog-fragment/1`）→ `catalog merge` →
`catalog build` → `semantic render --ontology` → `catalog render --semantics`。**照 `references/runbook.md` 的 S10a–S10g 做**；
起草（第 2 步）用 runbook-templates 的 T5，片段用 T6（它包着 `references/catalog-fragment-prompt.md`，码值集、`holds`、
`code_sets` 的规则都在那份提示词里）。不可违反的三条：

1. **digest 是起草的全部输入**，不要把整份表语义读进一次调用；digest 固定带 `--lineage`（有元数据再带 `--schema`）。
2. **片段不能新增概念、不能改已有标识符**：新概念（事件连同它的时间属性）、新标识符、新拼写、跨组属性在起草这一步写好。
3. **合并冲突逐条交回对应的组**，不要手工挑一个；合并后的手工修正只改 `merged/` 并留记录。

片段格式、合并规则和退出码见 `../../docs/zh-CN/ontology-catalog.md` 的「起草」一节。
