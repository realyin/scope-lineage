"""A conversation's memory on the ask panel: today's date, the state card, the guard.

Three parts, all code (no extra model call):

- **Today** (``today_line``): every question's message starts with
  ``今天：YYYY-MM-DD（时区 ±HH:MM）`` from the server clock, read again for every question (a
  long conversation may cross midnight). It is in the user message, never the system prompt,
  which stays byte-identical so the provider can cache it.
- **The increment block** (``parse_block``): the walk's multi-turn brief, a ```text block at
  the end of the answer, now with ``话题``, ``SQL角色``, ``说法``, ``提议缺口`` and four optional
  lines (``撤销说法``, ``名字映射``, ``偏好``, ``未决问题``). ``check_block`` holds it to the
  conversation: the topic exists (or is new), the SQL roles number the answer's ```sql blocks,
  each ``提问者第 N 轮`` and ``原话第 N 轮`` names a turn that exists. A statement whose quote is not
  word for word in that turn's message does not invalidate the block; the whole message is kept
  as a 待定说法 instead.
- **The state card** (``apply_turn``, ``render_card``): what the next question carries instead
  of the previous brief. Code keeps the turn number, the catalog version, the topic index (turn
  range and SQL versions), the current SQL (only the segment the block marks 当前版, versioned by
  code), its check-sql result (run again by code), the placeholders, the asker's statements word
  for word (taken from the asker's message, the model only points), withdrawn statements and the
  one open question (cleared after the next question). The model's increment replaces the
  topic's 表 / 关联 / 条件 / 假设 as a whole group when it marks a new 当前版, and adds name
  mappings and preferences. A missing or invalid block leaves every model field as it was and
  the turn is counted as 缺失; the code fields still move.

**The guard** (``guard``): a statement has a scope (a topic and tables). When this question
stays in that topic, or its current SQL reads a table in scope, and none of the block's 条件
lines cites the statement's turn, the answer gets one line: 「这次没有沿用你第 N 轮说的 X，要不要
加上？」. Only statements from earlier turns are checked, only when this question produced a
current SQL, and never across a topic switch that touches none of the scope's tables.

**Budget** (``compact``): the card has a budget (6,000 characters by default). Over it, the
least recently used topics other than the current one are archived to one index line each
(their details stay in the full record, reachable with ``recall``), then the current topic's
older SQL versions are listed by number and change note only. The asker's statements are never
archived: they have a reserve of 1,500 characters, and past it the answer lists them and asks
which to drop.

The state is a plain JSON-ready dict, so the store (``store.py``) writes it as it is.
"""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

DEFAULT_CARD_BUDGET = 6_000
STATEMENT_RESERVE = 1_500
GUARD_QUOTE_CHARS = 60

BLOCK_KEYS = ("话题", "问题", "结论", "SQL角色", "SQL", "表", "关联", "条件", "假设", "说法",
              "提议缺口", "待确认", "check-sql", "撤销说法", "名字映射", "偏好", "未决问题")
_KEY_PATTERN = "|".join(re.escape(key) for key in sorted(BLOCK_KEYS, key=len, reverse=True))
_BLOCK_LINE = re.compile(rf"^({_KEY_PATTERN})\s*[：:](.*)$")
_SQL_BLOCK = re.compile(r"```sql[^\n]*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_TEXT_BLOCK = re.compile(r"```text[^\n]*\n(.*?)```", re.DOTALL)
_ASKER_TURN = re.compile(r"提问者\s*第\s*(\d+)\s*轮")
_QUOTE_TURN = re.compile(r"原话\s*第\s*(\d+)\s*轮")
_ROLE = re.compile(r"^段\s*(\d+)\s*[=＝:：]\s*([^（(]*?)\s*(?:[（(](.*)[)）])?\s*$")
_STATEMENT = re.compile(r"^第\s*(\d+)\s*轮\s*「(.*)」(.*)$", re.DOTALL)
_WITHDRAW = re.compile(r"^第\s*(\d+)\s*轮\s*(?:「(.*)」)?")
_TOPIC = re.compile(r"^#\s*(\d+)\s*(.*)$")
_NEW_TOPIC = re.compile(r"^新\s*[：:]\s*(.*)$")
# Words an answer uses when it takes a correction; with no 说法 line marked, the whole
# message is kept as a 待定说法 (generic words, no business term).
_CORRECTION_WORDS = ("纠正", "更正", "按你说的", "按你的说法", "按提问者")
CURRENT = "当前版"


# ---------------------------------------------------------------------- today


def today_line(now: datetime) -> str:
    """``今天：2026-11-25（时区 +08:00）`` for an aware ``now``."""
    offset = now.strftime("%z") or "+0000"
    return f"今天：{now.date().isoformat()}（时区 {offset[:3]}:{offset[3:]}）"


# ---------------------------------------------------------------------- catalog version

_VERSIONS: dict = {}


def catalog_version(path) -> str:
    """What identifies the loaded ontology: the first 12 hex digits of its sha256, cached by
    the file's size and modification time."""
    try:
        file = Path(path)
        stat = file.stat()
        key = (str(file), stat.st_size, stat.st_mtime_ns)
        if key not in _VERSIONS:
            _VERSIONS.clear()
            _VERSIONS[key] = "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()[:12]
        return _VERSIONS[key]
    except OSError:
        return "unknown"


# ---------------------------------------------------------------------- the block


def sql_segments(answer: str) -> list[str]:
    """Every ```sql block of an answer, in order (segment 1 first)."""
    return [block.strip() for block in _SQL_BLOCK.findall(answer or "")]


def block_text(answer: str) -> str | None:
    """The answer's last ```text block that starts with 话题 or 问题: the increment block."""
    blocks = [block.strip() for block in _TEXT_BLOCK.findall(answer or "")
              if block.strip().startswith(("话题", "问题"))]
    return blocks[-1] if blocks else None


def _present(value: str) -> bool:
    return bool(value) and value.strip() not in ("无", "-", "（无）")


def _split_basis(value: str) -> tuple[str, str]:
    for dash in (" — ", "—", " -- "):
        if dash in value:
            head, _, tail = value.partition(dash)
            return head.strip(), tail.strip()
    return value.strip(), ""


def _items(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[；;]", value) if part.strip()]


def parse_block(text: str | None) -> dict | None:
    """The labelled lines of an increment block; a line without a label continues the one
    before it (a SQL over several lines). None when there is no block."""
    if not text:
        return None
    fields: list = []
    for line in text.splitlines():
        match = _BLOCK_LINE.match(line.strip())
        if match:
            fields.append([match.group(1), match.group(2).strip()])
        elif fields:
            fields[-1][1] += "\n" + line
    values = lambda key: [value.strip() for name, value in fields if name == key]  # noqa: E731
    one = lambda key: (values(key) or [None])[0]  # noqa: E731
    block: dict = {"topic": None, "problems": []}
    topic = one("话题")
    if topic is not None:
        new, old = _NEW_TOPIC.match(topic), _TOPIC.match(topic)
        if new:
            block["topic"] = {"new": True, "name": new.group(1).strip()}
        elif old:
            block["topic"] = {"id": int(old.group(1)), "name": old.group(2).strip()}
        else:
            block["problems"].append(f"话题行看不懂：{topic}")
    block["question"] = one("问题")
    block["conclusion"] = one("结论")
    roles = one("SQL角色")
    if roles is None:
        block["roles"] = None
    else:
        block["roles"] = []
        for item in _items(roles) if _present(roles) else []:
            match = _ROLE.match(item)
            if not match:
                block["problems"].append(f"SQL角色看不懂：{item}")
                continue
            block["roles"].append({"segment": int(match.group(1)), "role": match.group(2).strip(),
                                   "note": (match.group(3) or "").strip()})
    block["tables"] = [v for v in values("表") if _present(v)]
    block["joins"] = [v for v in values("关联") if _present(v)]
    block["conditions"] = [v for v in values("条件") if _present(v)]
    block["params"] = [v for v in values("假设") if _present(v)]
    block["pending"] = [v for v in values("待确认") if _present(v)]
    block["check"] = one("check-sql")
    block["statements"] = [_statement(v) for v in values("说法") if _present(v)]
    block["gaps"] = [_gap(v) for v in values("提议缺口") if _present(v)]
    block["withdraw"] = []
    for value in values("撤销说法"):
        match = _WITHDRAW.match(value)
        if match:
            block["withdraw"].append({"turn": int(match.group(1)), "quote": match.group(2)})
        elif _present(value):
            block["problems"].append(f"撤销说法看不懂：{value}")
    block["mappings"] = [v for v in values("名字映射") if _present(v)]
    block["preferences"] = [v for v in values("偏好") if _present(v)]
    question = one("未决问题")
    block["open_question"] = question if question and _present(question) else None
    return block


def _statement(value: str) -> dict:
    match = _STATEMENT.match(value)
    if not match:
        return {"raw": value, "turn": None, "quote": None, "topic": None, "tables": []}
    rest = match.group(3)
    scope = rest.split("范围", 1)[1] if "范围" in rest else ""
    topic = re.search(r"#\s*(\d+)", scope)
    tables: list = []
    table_part = re.search(r"表\s*(.*)$", scope)
    if table_part:
        tables = [t.strip() for t in re.split(r"[、,，\s]+", table_part.group(1)) if _present(t.strip())]
    return {"raw": value, "turn": int(match.group(1)), "quote": match.group(2),
            "topic": int(topic.group(1)) if topic else None, "tables": tables}


def _gap(value: str) -> dict:
    missing, rest = _split_basis(value)
    parts = _items(rest)
    column = parts[0] if parts and not parts[0].startswith(("提议", "原话")) else None
    proposed = next((p.split("：", 1)[-1].split(":", 1)[-1].strip() for p in parts
                     if p.startswith("提议")), None)
    turn = _QUOTE_TURN.search(value)
    return {"raw": value, "missing": missing, "column": column if column and _present(column) else None,
            "proposed": proposed if proposed and _present(proposed) else None,
            "turn": int(turn.group(1)) if turn else None}


def cited_turns(conditions: list[str]) -> set[int]:
    """The turns the 条件 lines cite as 提问者第 N 轮."""
    return {int(n) for line in conditions for n in _ASKER_TURN.findall(line)}


def check_block(block: dict, state: dict, turn: int, segments: int) -> list[str]:
    """Why the block cannot be trusted (an empty list: it can). A statement quote that is not
    word for word is not here: it falls back to a 待定说法."""
    problems = list(block.get("problems") or [])
    topic = block.get("topic")
    known = {item["id"] for item in state["topics"]}
    if topic is None:
        problems.append("没有话题行")
    elif not topic.get("new") and topic["id"] not in known:
        problems.append(f"话题 #{topic['id']} 不存在")
    roles = block.get("roles")
    if roles:
        numbers = [role["segment"] for role in roles]
        if len(set(numbers)) != len(numbers):
            problems.append("SQL角色里有重复的段号")
        if any(not 1 <= n <= segments for n in numbers):
            problems.append(f"SQL角色的段号与答案里的 SQL 段数（{segments}）对不上")
        if sum(1 for role in roles if role["role"].startswith("当前")) > 1:
            problems.append("SQL角色标了不止一段当前版")
    elif roles == [] and segments:
        problems.append(f"SQL角色写了无，答案里却有 {segments} 段 SQL")
    for n in sorted(cited_turns(block.get("conditions") or [])):
        if not 1 <= n <= turn:
            problems.append(f"条件引用的第 {n} 轮不存在")
    for gap in block.get("gaps") or []:
        if gap["turn"] is not None and not 1 <= gap["turn"] <= turn:
            problems.append(f"提议缺口引用的第 {gap['turn']} 轮不存在")
    return problems


# ---------------------------------------------------------------------- the state


def new_state() -> dict:
    return {
        "catalog": None, "catalog_changed": None, "turn": 0, "current_topic": None,
        "topics": [], "statements": [], "withdrawn": [], "mappings": [], "preferences": [],
        "open_question": None, "missing_streak": 0, "last_block": None, "last_problems": [],
        "compact": False,
    }


def _topic(state: dict, topic_id: int | None) -> dict | None:
    return next((item for item in state["topics"] if item["id"] == topic_id), None)


def _new_topic(state: dict, name: str, turn: int) -> dict:
    topic = {"id": max((item["id"] for item in state["topics"]), default=0) + 1,
             "name": name or f"第 {turn} 轮的问题", "first": turn, "last": turn, "versions": [],
             "sql": None, "tables": [], "joins": [], "conditions": [], "params": [],
             "archived": False}
    state["topics"].append(topic)
    return topic


def _dedupe(items: list) -> list:
    seen, kept = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            kept.append(item)
    return kept


def _check_summary(result: dict | None, error: str | None) -> str:
    if error:
        return f"没有通过：{error[:200]}"
    if result is None:
        return "没跑"
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in result.get("findings", []):
        counts[finding.get("severity")] = counts.get(finding.get("severity"), 0) + 1
    return f"错误 {counts['error']}，警告 {counts['warning']}，提示 {counts['info']}"


def _sql_tables(result: dict | None) -> set[str]:
    return {item.get("table", "").lower() for item in (result or {}).get("tables", []) if item.get("table")}


def _in_scope(scope_tables: list[str], tables: set[str]) -> bool:
    for name in scope_tables:
        name = name.lower()
        if any(table == name or table.endswith("." + name) for table in tables):
            return True
    return False


def _corrected(answer: str, block: dict | None, turn: int) -> bool:
    if block and turn in cited_turns(block.get("conditions") or []):
        return True
    return any(word in (answer or "") for word in _CORRECTION_WORDS)


def statement_chars(state: dict) -> int:
    return sum(len(_statement_line(item)) for item in state["statements"])


def apply_turn(
    state: dict, *, turn: int, question: str, answer: str, segments: list[str],
    user_messages: dict, check: Callable[[str], tuple], catalog: str,
) -> dict:
    """The state after a finished question, and what this question showed: a dict with
    ``state`` (a new dict; ``state`` is not changed), ``block`` (parsed or None),
    ``block_status`` (ok / missing / invalid), ``problems``, ``topic``, ``segments`` (each
    with its role and the version code gave the 当前版), ``sql`` (the segment to show: the
    当前版, else the first), ``check`` and ``check_error`` (of that SQL), ``guard`` (the lines
    the guard adds), ``statements_over`` (a line when the statements passed their reserve),
    ``new_statements``.

    ``check(sql)`` returns ``(check-sql result or None, error text or None)``;
    ``user_messages`` maps each turn number to the asker's message of that turn."""
    state = copy.deepcopy(state)
    previous_catalog = state.get("catalog")
    state["catalog_changed"] = ([previous_catalog, catalog]
                                if previous_catalog and previous_catalog != catalog else None)
    state["catalog"] = catalog
    state["turn"] = turn
    block = parse_block(block_text(answer))
    problems = check_block(block, state, turn, len(segments)) if block is not None else ["没有增量块"]
    status = "missing" if block is None else ("invalid" if problems else "ok")
    valid = status == "ok"

    # the topic of this question
    topic = None
    if valid and block["topic"].get("new"):
        topic = _new_topic(state, block["topic"]["name"], turn)
    elif valid:
        topic = _topic(state, block["topic"]["id"])
        if block["topic"].get("name") and not topic.get("name"):
            topic["name"] = block["topic"]["name"]
    else:
        topic = _topic(state, state["current_topic"]) or _new_topic(state, question.strip()[:20], turn)
    topic["last"] = turn
    topic["archived"] = False
    state["current_topic"] = topic["id"]

    # the SQL: only the segment marked 当前版 becomes the current SQL
    roles = {role["segment"]: role for role in (block or {}).get("roles") or []} if valid else {}
    shown_segments = []
    current_index = next((n for n, role in roles.items() if role["role"].startswith("当前")), None)
    sql_missing = bool(segments) and (not valid or block.get("roles") is None)
    if sql_missing:
        problems = problems + ([] if not valid else ["答案里有 SQL，增量块没有标 SQL角色：当前 SQL 不更新"])
    new_version = None
    if current_index is not None:
        text = segments[current_index - 1]
        current = topic.get("sql")
        if current is None or current["text"] != text:
            number = len(topic["versions"]) + 1
            topic["versions"].append({"v": number, "turn": turn, "note": roles[current_index]["note"]})
            topic["sql"] = {"v": number, "text": text, "turn": turn}
            new_version = number
        topic["tables"] = _dedupe(block["tables"])
        topic["joins"] = _dedupe(block["joins"])
        topic["conditions"] = _dedupe(block["conditions"])
        topic["params"] = _dedupe(block["params"])
    for index, text in enumerate(segments, start=1):
        role = roles.get(index)
        shown_segments.append({
            "index": index, "sql": text, "role": role["role"] if role else None,
            "note": role["note"] if role else None,
            "version": topic["sql"]["v"] if index == current_index else None,
            "topic": topic["id"] if index == current_index else None,
        })

    # the check-sql of the topic's current SQL, run again by code
    current_check = current_error = None
    if topic.get("sql"):
        current_check, current_error = check(topic["sql"]["text"])
        topic["sql"]["check"] = _check_summary(current_check, current_error)
        topic["sql"]["placeholders"] = [p.get("text") for p in (current_check or {}).get("placeholders", [])]
    shown = segments[current_index - 1] if current_index else (segments[0] if segments else None)
    if shown is not None and topic.get("sql") and shown == topic["sql"]["text"]:
        shown_check, shown_error = current_check, current_error
    elif shown is not None:
        shown_check, shown_error = check(shown)
    else:
        shown_check = shown_error = None

    # statements: the asker's words, taken from the message, never from the model's quote
    added: list = []
    fallback = False
    if valid:
        for item in block["statements"]:
            source = user_messages.get(item["turn"]) if item["turn"] else None
            if item["turn"] and source and item["quote"] and item["quote"] in source:
                start = source.index(item["quote"])
                words = source[start:start + len(item["quote"])]
                if any(s["turn"] == item["turn"] and s["text"] == words for s in state["statements"]):
                    continue
                entry = {"turn": item["turn"], "text": words, "topic": item["topic"] or topic["id"],
                         "tables": item["tables"], "pending": False}
                state["statements"].append(entry)
                added.append(entry)
            else:
                problems = problems + [f"说法的原话不在第 {item['turn']} 轮的消息里：{item['raw'][:80]}"]
                fallback = True
        for item in block["withdraw"]:
            kept = []
            for entry in state["statements"]:
                if entry["turn"] == item["turn"] and (not item["quote"] or item["quote"] in entry["text"]):
                    state["withdrawn"].append({"turn": entry["turn"], "text": entry["text"], "at": turn})
                else:
                    kept.append(entry)
            state["statements"] = kept
        state["mappings"] = _dedupe(state["mappings"] + block["mappings"])
        state["preferences"] = _dedupe(state["preferences"] + block["preferences"])
        state["open_question"] = block["open_question"]
    else:
        state["open_question"] = None
    marked = valid and bool(block["statements"])
    if fallback or (not marked and _corrected(answer, block if valid else None, turn)):
        if not any(s["turn"] == turn and s["pending"] for s in state["statements"]):
            entry = {"turn": turn, "text": question, "topic": topic["id"], "tables": [], "pending": True}
            state["statements"].append(entry)
            added.append(entry)

    # the guard
    guard_lines = guard(state, block if valid else None, turn, topic["id"], current_index is not None,
                        _sql_tables(current_check) | {t.split(" ")[0].lower() for t in topic["tables"]})

    over = None
    if added and statement_chars(state) > STATEMENT_RESERVE:
        listed = "；".join(f"第 {s['turn']} 轮「{_short(s['text'])}」" for s in state["statements"])
        over = (f"你给过的说法已经很多（{len(state['statements'])} 条，超过 {STATEMENT_RESERVE} 字的保留额度），"
                f"下面这几条我会继续沿用：{listed}。要不要撤掉哪些？")

    state["last_block"] = status
    state["last_problems"] = problems
    state["missing_streak"] = 0 if valid else state.get("missing_streak", 0) + 1
    return {
        "state": state, "block": block, "block_status": status, "problems": problems,
        "topic": topic["id"], "topic_name": topic["name"], "segments": shown_segments,
        "version": topic["sql"]["v"] if topic.get("sql") else None, "new_version": new_version,
        "sql_missing": sql_missing, "sql": shown, "check": shown_check, "check_error": shown_error,
        "guard": guard_lines, "statements_over": over, "new_statements": added,
        "gaps": block["gaps"] if valid else [],
    }


def _short(text: str, limit: int = GUARD_QUOTE_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def guard(state: dict, block: dict | None, turn: int, topic: int, has_current_sql: bool,
          sql_tables: set[str]) -> list[str]:
    """The lines to add when a statement in scope was not carried into this answer."""
    if not has_current_sql:
        return []
    cited = cited_turns((block or {}).get("conditions") or [])
    lines, seen = [], set()
    for item in state["statements"]:
        if item["turn"] >= turn or item["turn"] in cited:
            continue
        if item["topic"] != topic and not _in_scope(item.get("tables") or [], sql_tables):
            continue
        key = (item["turn"], item["text"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"这次没有沿用你第 {item['turn']} 轮说的「{_short(item['text'])}」，要不要加上？")
    return lines


# ---------------------------------------------------------------------- the card


def _statement_line(item: dict) -> str:
    scope = f"范围：#{item['topic']}"
    if item.get("tables"):
        scope += "；表 " + "、".join(item["tables"])
    head = "待定 " if item.get("pending") else ""
    tail = "（模型没有标出哪句是说法，整句存下）" if item.get("pending") else ""
    return f"- {head}第 {item['turn']} 轮「{item['text']}」— {scope}{tail}"


def _versions(topic: dict, compact: bool) -> str:
    if not topic["versions"]:
        return "还没有 SQL"
    if compact:
        return "、".join(f"v{v['v']}" + (f" {v['note']}" if v["note"] else "") for v in topic["versions"])
    return "、".join(f"v{v['v']}（第 {v['turn']} 轮" + (f"，{v['note']}" if v["note"] else "") + "）"
                     for v in topic["versions"])


def _index_line(topic: dict, current: bool, compact: bool) -> str:
    span = f"第 {topic['first']}–{topic['last']} 轮"
    if topic["archived"]:
        final = f"最终 v{topic['sql']['v']}" if topic.get("sql") else "没有 SQL"
        return f"- #{topic['id']} {topic['name']} — {span}；{final}（已归档，详情用 recall）"
    mark = "（当前）" if current else ""
    return f"- #{topic['id']} {topic['name']}{mark} — {span}；SQL {_versions(topic, compact and current)}"


def render_card(state: dict, *, turn: int, catalog: str | None = None,
                compact: bool | None = None) -> str:
    """The card the question of number ``turn`` carries (after the date line)."""
    compact = state.get("compact", False) if compact is None else compact
    catalog = catalog or state.get("catalog") or "unknown"
    lines = [f"【对话状态卡】服务维护；本轮是第 {turn} 轮；目录版本：{catalog}"]
    if state.get("catalog") and catalog != state["catalog"]:
        lines.append(f"目录版本变了（{state['catalog']} → {catalog}）：前面的答案可能要重看，要用的表重取取数包。")
    if not state["topics"]:
        lines.append("这是对话的第一个问题，还没有话题。")
        return "\n".join(lines)
    current = _topic(state, state["current_topic"])
    lines.append("话题索引（回到旧话题、要旧版 SQL 时用 recall 按轮号或话题与版本取回）：")
    lines.extend(_index_line(topic, topic is current, compact) for topic in state["topics"])
    if current is not None:
        lines.append(f"当前话题：#{current['id']} {current['name']}")
        sql = current.get("sql")
        if sql:
            lines += [f"当前 SQL（#{current['id']} v{sql['v']}，第 {sql['turn']} 轮）：", "```sql", sql["text"], "```",
                      f"check-sql（服务对 #{current['id']} v{sql['v']} 重跑）：{sql.get('check', '没跑')}"]
            if sql.get("placeholders"):
                lines.append("待确认占位：" + "；".join(sql["placeholders"]))
        for label, key in (("表", "tables"), ("关联", "joins"), ("条件", "conditions"), ("假设", "params")):
            lines.extend(f"{label}：{value}" for value in current[key])
    if state["statements"]:
        lines.append("提问者的说法（逐字；落在范围内的题要沿用，条件的依据写「提问者第 N 轮」）：")
        lines.extend(_statement_line(item) for item in state["statements"])
    if state["withdrawn"]:
        lines.append("已撤销的说法（不再沿用）：")
        lines.extend(f"- 第 {item['turn']} 轮「{item['text']}」（第 {item['at']} 轮撤销）" for item in state["withdrawn"])
    lines.extend(f"名字映射：{value}" for value in state["mappings"])
    lines.extend(f"偏好：{value}" for value in state["preferences"])
    if state.get("open_question"):
        lines.append(f"未决问题（上一轮问的；这轮没回答就按默认做法并说明）：{state['open_question']}")
    if state.get("last_block") in ("missing", "invalid"):
        why = "；".join(state.get("last_problems") or [])[:300]
        lines.append(f"上一轮的增量块：{'缺失' if state['last_block'] == 'missing' else '没通过校验'}（{why}）；"
                     "没变的字段沿用更早的。")
    return "\n".join(lines)


def compact(state: dict, *, turn: int, budget: int = DEFAULT_CARD_BUDGET) -> tuple[dict, list[int], str]:
    """Fit the card for question ``turn`` into ``budget`` characters: archive the least
    recently used topics other than the current one, then list the current topic's SQL
    versions by number and change note only. Statements are never archived. Returns the new
    state, the topics archived now, and the card."""
    state = copy.deepcopy(state)
    state["compact"] = False
    card = render_card(state, turn=turn)
    archived: list[int] = []
    while len(card) > budget:
        candidates = sorted((t for t in state["topics"]
                             if not t["archived"] and t["id"] != state["current_topic"]),
                            key=lambda t: (t["last"], t["id"]))
        if not candidates:
            break
        candidates[0]["archived"] = True
        archived.append(candidates[0]["id"])
        card = render_card(state, turn=turn)
    if len(card) > budget:
        state["compact"] = True
        card = render_card(state, turn=turn)
    return state, archived, card


def archive_notice(state: dict, archived: list[int]) -> str | None:
    if not archived:
        return None
    names = "、".join(f"#{t['id']} {t['name']}" for t in state["topics"] if t["id"] in archived)
    return f"对话状态卡超出预算，已把话题 {names} 归档成一行索引；要回到它们时直接说，我会按轮号取回。"


def view(state: dict) -> dict:
    """What the page shows of the card: the topic, the effective assumptions and statements."""
    current = _topic(state, state["current_topic"])
    return {
        "topic": current["id"] if current else None,
        "topic_name": current["name"] if current else None,
        "version": current["sql"]["v"] if current and current.get("sql") else None,
        "conditions": list(current["conditions"]) if current else [],
        "params": list(current["params"]) if current else [],
        "statements": [{"turn": s["turn"], "text": s["text"], "topic": s["topic"], "pending": s["pending"]}
                       for s in state["statements"]],
        "withdrawn": [{"turn": s["turn"], "text": s["text"]} for s in state["withdrawn"]],
        "topics": [{"id": t["id"], "name": t["name"], "first": t["first"], "last": t["last"],
                    "versions": [v["v"] for v in t["versions"]], "archived": t["archived"]}
                   for t in state["topics"]],
        "open_question": state.get("open_question"),
        "missing_streak": state.get("missing_streak", 0),
    }


# ---------------------------------------------------------------------- recall

MAX_RECALL_ANSWER = 20_000


def recall(turns: list[dict], *, turn: int | None = None, topic: int | None = None,
           version: int | None = None) -> tuple[bool, str, dict]:
    """One earlier turn of this conversation's record: ``(ok, text for the model, data)``.
    By ``turn``, or by ``topic`` and ``version`` (the turn that version was written in;
    ``topic`` alone: its latest version)."""
    if turn is None and topic is None:
        return False, "recall: give turn, or topic (and version)", {}
    if turn is None:
        found = None
        for record in turns:
            for segment in record.get("segments") or []:
                if segment.get("topic") == topic and (version is None or segment.get("version") == version):
                    found = record
            if version is not None and found is not None:
                break
        if found is None:
            what = f"话题 #{topic}" + (f" 的 v{version}" if version is not None else "")
            return False, f"recall: 本对话没有{what}的 SQL（看状态卡的话题索引）", {}
        turn = found["turn"]
    record = next((item for item in turns if item.get("turn") == turn), None)
    if record is None:
        last = max((item.get("turn", 0) for item in turns), default=0)
        return False, f"recall: 本对话没有第 {turn} 轮（现在到第 {last} 轮）", {}
    status = record.get("status")
    lines = [f"第 {turn} 轮（话题 #{record.get('topic')}；{STATUS_WORDS.get(status, status)}）",
             f"问题：{record.get('question')}"]
    answer = record.get("answer")
    if status == "running":
        lines.append("这一轮还在进行，没有回答。")
    elif answer:
        cut = answer if len(answer) <= MAX_RECALL_ANSWER else answer[:MAX_RECALL_ANSWER] + "\n（回答过长，后面省略）"
        lines += ["回答：", cut]
    else:
        lines.append("这一轮没有回答。")
    for segment in record.get("segments") or []:
        role = segment.get("role") or "没标角色"
        label = f"段{segment['index']}（{role}" + (f"，#{segment['topic']} v{segment['version']}"
                                                  if segment.get("version") else "") + "）"
        if version is not None and segment.get("version") == version and segment.get("topic") == topic:
            label += " ← 要取的这一版"
        lines += [label + "：", "```sql", segment.get("sql", ""), "```"]
    data = {"turn": turn, "topic": record.get("topic"), "status": status,
            "versions": [s.get("version") for s in record.get("segments") or [] if s.get("version")]}
    return True, "\n".join(lines), data


STATUS_WORDS = {"done": "完成", "running": "进行中", "interrupted": "中断（服务重启）",
                "cancelled": "已停止", "error": "出错", "cap_reached": "到达上限",
                "refused": "模型拒答", "max_tokens": "输出被截断"}
