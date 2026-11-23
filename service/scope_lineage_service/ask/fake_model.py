"""A scripted stand-in for the model, for reviewing the ask panel without a key: a dev aid.

Started only with ``--ask-dev-fake-model``; with ``--ask-models`` as well, every model in
the file is played by one of these (named after the model's id), so the page's model
picker can be reviewed without a key. It calls no model and opens no connection: it
answers through the same loop with a fixed sequence of real tool calls against the loaded
catalog -- search, then the best table's column list beside a metric search (two calls in
one turn), then a context pack, then a check of a SQL it assembles with 待确认
placeholders -- and ends with an answer in the walk's format that says on its first line
that it is not one. It never calls ``add_pending``, so a review does not write lines into
a real pending file (the page's own fill-in still does, when the reader submits one). Its
token counts are made up from text lengths. The page shows a banner whenever the server
runs in this mode.
"""

from __future__ import annotations

import json
import time
from typing import Callable

from .loop import Cancelled

NAME = "dev-fake-model"
NOTICE = "【开发用假模型】下面的过程和答案是脚本按目录拼出来的，没有调用任何模型，不是答案。"


class FakeModel:
    name = NAME
    fake = True
    provider = "fake"
    effort = None
    fallback = None

    def __init__(self, state, *, delay: float = 0.8, name: str = NAME) -> None:
        self.state = state
        self.delay = delay
        self.name = name

    def turn(self, request: dict, should_stop: Callable[[], bool]) -> dict:
        self._pause(should_stop)
        messages = request["messages"]
        step = sum(1 for message in messages if message["role"] == "assistant")
        question = _question(messages[0])
        plan = self._plan(question)
        content = self._step(step, question, plan)
        stop = "tool_use" if any(block["type"] == "tool_use" for block in content) else "end_turn"
        prefix = len(json.dumps([request["system"], request["tools"]], ensure_ascii=False)) // 3
        tail = len(json.dumps(messages, ensure_ascii=False)) // 3
        usage = {
            "input_tokens": tail, "output_tokens": len(json.dumps(content, ensure_ascii=False)) // 3,
            "cache_creation_input_tokens": prefix if step == 0 else 0,
            "cache_read_input_tokens": prefix if step else 0,
        }
        return {"content": content, "stop_reason": stop, "stop_details": None, "usage": usage,
                "model": self.name}

    def _pause(self, should_stop) -> None:
        end = time.monotonic() + self.delay
        while True:
            if should_stop():
                raise Cancelled()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 0.1))

    # ------------------------------------------------------------------ the script

    def _plan(self, question: str) -> dict:
        hits = self.state.search(question, None, 10).result["hits"]
        tables = {rep["table"]: rep for rep in self.state.inputs().document.get("representations", [])}
        table = next((hit["id"] for hit in hits if hit["kind"] == "table" and hit["id"] in tables), None)
        if table is None:
            for hit in hits:
                for name in str(hit.get("where") or "").split("、"):
                    if name.strip() in tables:
                        table = name.strip()
                        break
                if table:
                    break
        columns = []
        if table:
            columns = [b["column"] for b in tables[table].get("bindings", [])
                       if b.get("to") not in ("technical", "unmapped")][:2]
        return {"table": table, "columns": columns, "sql": _sql(question, table, columns)}

    def _step(self, step: int, question: str, plan: dict) -> list:
        table, columns, sql = plan["table"], plan["columns"], plan["sql"]
        if step == 0:
            return [_text(NOTICE + "\n先检索。"), _call("fake-1", "search_catalog", text=question)]
        if table is None or step >= 4:
            return [_text(self._answer(question, plan))]
        if step == 1:
            return [_text("看最像的那张表的列清单，同时找指标。"),
                    _call("fake-2", "query_catalog", kind="table", term=table),
                    _call("fake-3", "search_catalog", text=question, kinds=["metric"])]
        if step == 2:
            request = {"tables": [table], "brief": True}
            if columns:
                request.update(columns_of_table=[",".join(columns)], focus=True)
            return [_text("取数包。"), _call("fake-4", "catalog_context", **request)]
        return [_text("检查 SQL。"), _call("fake-5", "check_sql", sql=sql)]

    def _answer(self, question: str, plan: dict) -> str:
        table, columns, sql = plan["table"], plan["columns"], plan["sql"]
        if table is None:
            brief = f"问题：{question}\n结论：（假模型）目录里没有找到对得上的表\nSQL：无\n表：无\n关联：无\n条件：无\n假设：无\n待确认：无\ncheck-sql：未跑"
            return f"{NOTICE}\n\n定不了：假模型在检索结果里没有找到一张目录里的表。\n\n```text\n{brief}\n```\n"
        check = self.state.check_sql(sql).result
        errors = sum(1 for f in check["findings"] if f["severity"] == "error")
        warnings = sum(1 for f in check["findings"] if f["severity"] == "warning")
        holes = [p["text"] for p in check.get("placeholders", [])]
        conditions = [f"t.{column} IN (…) — 假模型占位，没有依据" for column in columns[:1]] or ["无"]
        pending = [f"{text} — {column}；无；未记入（假模型不记）"
                   for text, column in zip(holes, columns[:1] + ["无"] * len(holes))] or ["无"]
        brief = "\n".join([
            f"问题：{question}", "结论：（假模型）没有结论", f"SQL：{sql}",
            f"表：{table} — 一行是（假模型没有读）", "关联：无",
            *[f"条件：{line}" for line in conditions], "假设：无",
            *[f"待确认：{line}" for line in pending],
            f"check-sql：错误 {errors}，警告 {warnings}；留着的警告：无",
        ])
        return "\n".join([
            NOTICE, "", "1. **SQL**", "", "```sql", sql, "```", "",
            f"2. **表和关联**：{table} — 一行是什么假模型没有读；没有关联。",
            "3. **条件和依据**：", *[f"   - {line}" for line in conditions],
            "4. **假设**：无", "5. **待确认（交目录负责人）**：", *[f"   - {line}" for line in pending],
            f"6. check-sql：错误 {errors}，警告 {warnings}。", "", "```text", brief, "```", "",
        ])


def _sql(question: str, table: str | None, columns: list) -> str:
    if table is None:
        return ""
    lines = ["SELECT COUNT(*) AS cnt", f"FROM {table} t", "WHERE 1 = 1"]
    if columns:
        lines.append(f"  AND t.{columns[0]} IN (/* 待确认：{columns[0]} 取哪些值算数（假模型占位） */ '待确认')")
    words = " ".join(question.split())[:40] or "问题"
    lines.append(f"  AND /* 待确认：「{words}」的口径（假模型占位） */ 1 = 1")
    return "\n".join(lines)


def _question(message: dict) -> str:
    content = message["content"]
    text = content if isinstance(content, str) else "".join(
        block.get("text", "") for block in content if block.get("type") == "text")
    return text.rsplit("问题：", 1)[-1].strip()


def _text(value: str) -> dict:
    return {"type": "text", "text": value}


def _call(id_: str, name: str, **args) -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": args}
