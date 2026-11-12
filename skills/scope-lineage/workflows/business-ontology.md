### "整理这批任务的实体关系 / 本体 / 这批表对应哪些业务概念" — business ontology: where to start

业务本体（有哪些概念、客户是哪几张表、概念之间什么关系、有哪些事件）一律走**表语义 → 本体目录**，
不要用下一节的 `scope-lineage ontology` 回答：

1. 目录已经有了（`catalog-yaml/1` 或它 build 出的 `ontology.json`）→ 直接问目录，见
   「"客户是什么 / 这张表装的是什么 / 这个字段指什么" — 用目录回答业务问题」。
2. 还没有目录，这批表已经有表语义 → 按「"从表语义起草本体目录" — drafting procedure (digest → fragments → merge)」
   跑 `catalog digest` → 起草 → 片段 → `catalog merge` / `build` / `render`，再用 `catalog query` 回答。
3. 连表语义也没有 → 先按「"这张表是什么意思 / 给这批表写表语义" — table semantics」写表语义
   （`semantic *`），再走第 2 步。

键折叠候选（下一节）可以在起草时作为交叉证据旁读，但它的概念不是业务本体，不能直接当答案。
