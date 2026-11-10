### "这个概念改了会影响谁" — concept-level impact

```bash
python3 scripts/query.py concept-impact <concept id | 概念名> \
  --ontology <ontology-dir>/ontology.json --lineage <artifacts-root> \
  [--depth N] [--attribute <属性名>] [--json]
```

`impact` / `trace` 回答的是表和列，业务方问的是概念。这个子命令把两层接起来：从
`ontology.json`（必须是 `ontology-json/2`）取这个概念的**表现表**（含 role）与**概念关系**
（方向、type、cardinality、tier），再用与 `trace` 同一套语料下游机制，列出每张表现表的
**下游任务**——按任务去重，每条说明读的是哪张表、在第几跳（`--depth` 默认 1）。
`--attribute <属性名>` 把答案收窄到该属性 `sources[]` 的源列：只留读到这些列的任务，
并只列出 JOIN 列包含该属性的概念关系。`--json` 输出同一份答案
（`{concept, tables[], relations[], downstream[], attribute?}`）。

先跑一次 `scope-lineage ontology`（见上一节「键折叠候选」）拿到 `ontology.json`，语料产物用同一个
`--lineage` 根目录，首次运行会复用/生成 `.scope-lineage-index.json`。概念可以按 id、
按完整概念名、或按唯一前缀指定；前缀撞上多个概念时脚本列出候选并退出 2，**不猜**。
本体缺失或版本过旧、概念或属性不存在，都是一句话 + 退出码 2。回答时把 tier 带上：
`hypothesis` 的关系是作者假设，不能说成事实（见上一节的分级规则）。这里的「概念」是键折叠候选，
回答时照此称呼，不要说成业务本体的概念。

**只认键折叠的 `ontology-json/2`。**`catalog build` 写的 `ontology-json/3`（业务目录）会被拒绝：一句话 + 退出码 2，
提示里的「re-run `scope-lineage ontology`」说的是键折叠候选，不是让你把目录换掉。问的是业务目录里的概念时，
先用 `catalog query <dir>/ontology.json carriers <概念>`（带这个概念标识符的表）和 `related <概念>`（它自己的表、
一跳关系与事件及同表携带的表）列出表，再对这些表跑 `impact` / `trace` 看下游任务；见下一节。
