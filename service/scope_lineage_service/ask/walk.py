"""The system prompt: a short service preamble, then the skill's walk, word for word.

The walk is ``skills/scope-lineage/workflows/catalog-answers.md`` and the reference it
cites, ``skills/scope-lineage/references/catalog-questions.md``. ``skills/`` is in neither
distribution, so this package carries exact copies (``catalog-answers.md``,
``catalog-questions.md`` beside this module) and ``service/tests/test_ask_walk.py`` fails
whenever a copy differs from its source: edit the skill file, then copy it here.

The preamble only maps the walk's commands to the tools offered and states what this
service cannot do; it does not restate or change a step. ``catalog pending add`` maps to no
tool: on this service the asker records a gap with the page's button (``POST /api/pending``),
so the model never writes the pending file and is told not to claim it recorded anything.

The prompt has nothing that varies between requests (no date, path, id or catalog name),
so the model provider can cache it with the tool definitions as one stable prefix.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

WALK_FILES = ("catalog-answers.md", "catalog-questions.md")

_COMMANDS = """\
你在一个只读的目录问数服务里回答提问者的数据问题。后面附的「用目录回答业务问题」是你要照做的步骤（分题、第 1–7 步、占位约定、多轮简报），\
附录是它引用的 `references/catalog-questions.md`。步骤里的命令在这里换成同名参数的工具，`<O>` `<S>` `<P>` 由服务定好，不用传：

- `catalog search <O> "<文字>" [--kind K]... [--limit N]` → `search_catalog(text, kinds, limit)`
- `catalog query <O> <kind> <term>` → `query_catalog(kind, term)`
- `catalog context <O> --table … --column … --columns … --concept … --brief --focus` → \
`catalog_context(tables, columns, columns_of_table, concepts, brief, focus)`
- `catalog check-sql <O> query.sql` → `check_sql(sql)`：直接传 SQL 文本，不存文件
"""

_PENDING_ON = """\
- `catalog pending add`：没有这个工具，你不能记入待确认文件。在本服务上由提问者自己记：页面在答案的「待确认」下给 SQL 里每个占位\
一个「记入待确认」按钮，提问者点了服务才写。第 6 步照样把缺口列在「待确认」里，告诉提问者要记就点那个按钮；第 7 步每条写"未记入"，\
不要说已记入或已替他记下。提问者在对话里说"记下来"时，也请他点按钮。
"""

_PENDING_OFF = """\
- `catalog pending add`：本服务没有待确认文件，没有这个工具，页面也不能记；第 6 步只把缺口列在「待确认」里，不问记不记，\
第 7 步写"未记入（服务没有待确认文件）"。
"""

_LIMITS = """\

工具返回的是命令不加 `--json` 时打印的文字；命令拒绝的输入以工具错误返回同一句话；退出码 1（没找到）照常是一个回答。

本服务的限制：
- 不执行 SQL，连不到任何数据库：不要说查到了什么数。
- 读不到任何文件：`catalog render`、页面、`index.md`、`workflows/` 与 `docs/` 下的其他文件在这里都没有，需要它们的那一试算作找不到。
- 一个问题一次运行：你既做第 1–6 步（第 6 步按上面那条），也写给提问者的答案。回复先按第 7 步写（不写 SQL 的题按「先分题」那段），用提问者的语言；\
SQL 放在一个 ```sql 代码块里；最后附「多轮问数」那节格式的简报，放在一个 ```text 代码块里，第一行以"问题："开头。\
追问时服务把上一题的简报和新问题一起给你。
- 每题的模型轮数、工具调用次数、输出 token 和时长有上限；工具说已到上限时，用手里的材料作答。
"""


@lru_cache(maxsize=None)
def walk_text(name: str) -> str:
    """One packaged walk file; ``name`` is one of ``WALK_FILES``."""
    if name not in WALK_FILES:
        raise ValueError(f"not a walk file: {name}")
    return (resources.files(__package__) / name).read_text(encoding="utf-8")


def preamble(pending: bool) -> str:
    return _COMMANDS + (_PENDING_ON if pending else _PENDING_OFF) + _LIMITS


def system_blocks(pending: bool) -> list[dict]:
    """The ``system`` content: preamble, walk, reference; cached up to the last block."""
    return [
        {"type": "text", "text": preamble(pending)},
        {"type": "text", "text": walk_text("catalog-answers.md")},
        {
            "type": "text",
            "text": "# 附录：references/catalog-questions.md\n\n" + walk_text("catalog-questions.md"),
            "cache_control": {"type": "ephemeral"},
        },
    ]
