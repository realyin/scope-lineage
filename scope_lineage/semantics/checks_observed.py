"""What checks 3, 4 and 6 hold a document's observations to (:mod:`.observed`).

Validation takes an observation from the run's confirmations files only. A document's
``observed*`` slots -- ``summary.row.observed``, a column's ``observed_values``, the
top-level ``observed_inputs`` -- are what ``semantic confirm`` wrote there from those files,
and never the evidence: a slot the files do not carry proves nothing. ``confirmed`` is the
table's state (:class:`~.confirmed.TableConfirmed`) and tells three cases apart:

- ``None``: no confirmations path was given -- a slot cannot be checked and warns
  (「无法核对观测来源」);
- an empty state: a path was given and has nothing for this table -- a run's empty
  ``confirmations/`` too -- every slot fails;
- a state with entries: each slot must be the confirmation's.

A slot that is not the confirmation's is no writer's to fix: the message says to replay
the confirmations and, if they still disagree, 「拿回确认文件改」.

Without any observation in the files or the document, none of these functions returns
anything, so every report is what it was before observations existed.
"""

from __future__ import annotations

from ..observation_words import value_word
from ..render.semantic_text import PASS_THROUGH_TEXT_PREFIXES
from .names import bare_column, bare_table
from .observed import IDENTIFIER_CATEGORIES, input_key, observation_text

GIVE_BACK = ("观测由 semantic confirm 照确认文件写，写作者不写也不改：先重放确认（semantic confirm），"
             "还对不上就拿回确认文件改")
UNCHECKED = "没有给确认文件，无法核对观测来源；用 --confirmations 指向运行目录的 confirmations/"


def _result(check: str, status: str, at: str, message: str = "") -> dict:
    return {"check": check, "status": status, "at": at, "message": message}


def _columns(columns) -> str:
    return f"({', '.join(str(column) for column in columns)})"


# 3 ------------------------------------------------------------------ code values


def comparable_values(packet: dict, column: dict, confirmed) -> dict | None:
    """The confirmed observation of a column's values when they can be held against its code
    list; else None.

    An observation of the column itself always can. One made on a source column
    (``observed_on``) only when the column passes that one column through: a single
    producer reading a single source by direct projections, with no CASE outputs and
    nothing computed -- a recoded or derived column holds other values than its source.
    """
    fact = confirmed.observed_values.get(column["column"]) if confirmed else None
    if fact is None:
        return None
    value = fact.value
    observed_on = value.get("observed_on")
    if observed_on is None:
        return value
    producers = [producer for entry in packet["lineage"]["columns"]
                 if entry["column"] == column["column"] for producer in entry["producers"]]
    if len(producers) != 1:
        return None
    (producer,) = producers
    prefixes = tuple(PASS_THROUGH_TEXT_PREFIXES.values())
    passed_through = (
        [bare_column(source) for source in producer["sources"]] == [bare_column(observed_on)]
        and not producer.get("case_outputs") and not producer.get("computed_by")
        and all(str(step).startswith(prefixes) for step in producer["steps"])
    )
    return value if passed_through else None


def seen_value(observation: dict | None, value: str) -> bool:
    """Whether a comparable observation saw ``value``."""
    return bool(observation) and any(
        str(item["value"]) == value for item in observation.get("values") or [])


def check_observed_values(ci: int, column: dict, packet: dict, confirmed) -> list[dict]:
    """Check 3 on one column's observation: the slot is the confirmation's; an identifier
    column carries no values; observed values off the code list warn once. A code value
    the observation asked about and did not see is not reported (D16 3.1): a few
    partitions cannot tell a code is gone, no writer could clear the warning, and the page
    shows 「没有出现 …」 beside the code list."""
    name, at = column["column"], f"columns[{ci}].observed_values"
    slot = column.get("observed_values")
    fact = confirmed.observed_values.get(name) if confirmed else None
    observation = fact.value if fact else None
    results = _slot("code_values", at, slot, observation, confirmed,
                    f"列 {name} 的取值观测（column:{name}.observed_values）")
    identifier = column.get("category") in IDENTIFIER_CATEGORIES
    if identifier and any((item or {}).get("values") or (item or {}).get("absent")
                          for item in (slot, observation)):
        results.append(_result("code_values", "fail", at, (
            f"列 {name} 是标识类列（{column['category']}），观测只给计数、不带取值：去掉 values / "
            "absent 要拿回确认文件改；列的分类写错了就改 category")))
        return results
    comparable = comparable_values(packet, column, confirmed)
    if comparable is None:
        return results
    where = observation_text(comparable)
    codes = column.get("code_values") or []
    listed = {str(code["value"]) for code in codes}
    items = comparable.get("values") or []
    if items and not codes:
        results.append(_result("code_values", "warn", f"columns[{ci}].code_values", (
            f"列 {name} 有观测取值、没有码值表（{where}）：观测到的值不是码值；它是码值列就问含义，"
            "或写成 unconfirmed 的码值")))
    else:
        off = [item for item in items if str(item["value"]) not in listed]
        if off:
            seen = "、".join(f"{value_word(item['value'])}（{item['count']} 行）" for item in off)
            results.append(_result("code_values", "warn", f"columns[{ci}].code_values", (
                f"列 {name} 观测到码值表外的值 {seen}（{where}）；问含义，或写成 unconfirmed")))
    return results


# 4 ------------------------------------------------------------------ grain


def check_observed_grain(row: dict, confirmed, owner_row: bool) -> list[dict]:
    """Check 4 on the row's observation.

    An ``observed`` grain has the slot and says what it observed (its ``unique``, grain
    columns that contain the counted ones when unique, else the counted ones) and its
    prose says it is an observation. The slot is the confirmation's. With a confirmed
    observation an ``inferred`` grain fails (the replay writes ``observed``; when the owner
    confirmed the row, the owner's check already fails it) and a ``declared`` one warns
    when the observation contradicts it (yes against no, other columns; ``unique:
    unknown`` contradicts nothing) -- a comment's word is no writer's to change.
    ``proven`` is not judged here."""
    source, slot = row["grain_source"], row.get("observed")
    fact = confirmed.observed_row if confirmed else None
    observation = fact.value if fact else None
    results = []
    if source == "observed":
        results += _observed_source(row, slot)
    if confirmed is None:
        if source == "observed" or slot is not None:
            results.append(_result("grain", "warn", "summary.row.grain_source",
                                   f"行粒度写了观测，但{UNCHECKED}"))
    elif observation is None:
        if source == "observed" or slot is not None:
            results.append(_result("grain", "fail", "summary.row.grain_source", (
                "确认文件里没有本表的行观测（summary.row.observed），文档不能写 grain_source: "
                "observed 或 row.observed：改回 inferred 或 declared 并删掉 row.observed；确有这次"
                "查询就拿回确认文件改（补上条目再 semantic confirm）")))
    else:
        if slot is None:
            if source != "observed":
                results.append(_result("grain", "fail", "summary.row.observed", (
                    f"确认文件里有本表的行观测（{observation_text(observation)}），row.observed "
                    f"没有；{GIVE_BACK}")))
        elif slot != observation:
            results.append(_result("grain", "fail", "summary.row.observed", (
                f"row.observed 与确认文件里的行观测（{observation_text(observation)}）不一致；"
                f"{GIVE_BACK}")))
        else:
            results.append(_result("grain", "pass", "summary.row.observed"))
        results += _against(row, observation, owner_row)
    return results


def _observed_source(row: dict, slot: dict | None) -> list[dict]:
    if slot is None:
        return [_result("grain", "fail", "summary.row.grain_source", (
            "grain_source 写了 observed，但没有 row.observed：observed 只能由 semantic confirm 照"
            "确认文件的行观测写；没有观测就改回 inferred 或 declared"))]
    results = []
    if row["unique"] != slot["unique"]:
        results.append(_result("grain", "fail", "summary.row.unique", (
            f"粒度来源是观测，unique 必须是观测的 {slot['unique']}，这里写成 {row['unique']}；"
            "照 row.observed 写")))
    counted, grain = set(slot["grain_columns"]), set(row["grain_columns"])
    if not (grain >= counted if slot["unique"] == "yes" else grain == counted):
        wanted = "包含" if slot["unique"] == "yes" else "等于"
        results.append(_result("grain", "fail", "summary.row.grain_columns", (
            f"粒度来源是观测，粒度列必须{wanted}观测计数的列 {_columns(slot['grain_columns'])}，"
            f"这里写成 {_columns(row['grain_columns'])}；照 row.observed 写")))
    prose = f"{row.get('text') or ''}\n{row.get('note') or ''}"
    if "观测" not in prose:
        results.append(_result("grain", "warn", "summary.row.text", (
            "行粒度来自观测，text / note 都没说是观测：写明「观测：在分区 …（… 执行）内按 (…) "
            "无重复」，只说明这些分区，不写裸「唯一」")))
    return results


def _against(row: dict, observation: dict, owner_row: bool) -> list[dict]:
    """A confirmed observation held against the document's grain source."""
    at = "summary.row.grain_source"
    source = row["grain_source"]
    if source == "inferred" and not owner_row:
        return [_result("grain", "fail", at, (
            f"确认文件里有本表的行观测（{observation_text(observation)}），grain_source 不能写 "
            "inferred：重放确认（semantic confirm）会写成 observed，不要自己改回 inferred"))]
    if source != "declared":
        return []
    if _agrees(row, observation):
        return [_result("grain", "pass", at)]
    return [_result("grain", "warn", at, (
        f"声明与观测不一致：文档按 {_columns(row['grain_columns'])} unique: {row['unique']}，"
        f"观测（{observation_text(observation)}）按 {_columns(observation['grain_columns'])} "
        f"unique: {observation['unique']}；核对声明的来源，两说并列写进 note 并记 conflict 的 watch")
    )]


def _agrees(row: dict, observation: dict) -> bool:
    """Whether a declared grain and the observation can both hold. ``unique: unknown``
    claims nothing an observation could contradict; other columns than those counted, or
    yes against no, do."""
    counted, grain = set(observation["grain_columns"]), set(row["grain_columns"])
    if row["unique"] not in ("unknown", observation["unique"]):
        return False
    return grain >= counted if observation["unique"] == "yes" else grain == counted


# 6 ------------------------------------------------------------------ neighbours


def check_observed_inputs(document: dict, packet: dict, confirmed) -> list[dict]:
    """Check 6 on ``observed_inputs``: each table is one of the lineage's input tables, and
    the items are the confirmations' (per input table and set of columns)."""
    items = document.get("observed_inputs") or []
    upstream = set(packet["lineage"]["upstream_tables"])
    results = []
    for index, item in enumerate(items):
        at = f"observed_inputs[{index}].table"
        if bare_table(item["table"]) in upstream:
            results.append(_result("neighbours", "pass", at))
        else:
            results.append(_result("neighbours", "fail", at, (
                f"观测的输入表 {item['table']} 不在本表血缘的输入表里（材料包 4.4）：观测记错了目标表"
                "或表名，拿回确认文件改；写作者不改 observed_inputs")))
    if confirmed is None:
        if items:
            results.append(_result("neighbours", "warn", "observed_inputs",
                                   f"写了上游观测，但{UNCHECKED}"))
        return results
    wanted = {key: fact.value for key, fact in confirmed.observed_inputs.items()}
    written = {}
    for index, item in enumerate(items):
        key = input_key(item["table"], item["columns"])
        written[key] = item
        at = f"observed_inputs[{index}]"
        if key not in wanted:
            results.append(_result("neighbours", "fail", at, (
                f"确认文件里没有本表对 {item['table']} 按 {_columns(item['columns'])} 的观测"
                f"（input:{bare_table(item['table'])}）；{GIVE_BACK}")))
        elif item != wanted[key]:
            results.append(_result("neighbours", "fail", at, (
                f"对 {item['table']} 的观测与确认文件不一致；{GIVE_BACK}")))
        else:
            results.append(_result("neighbours", "pass", at))
    for key, value in wanted.items():
        if key not in written:
            results.append(_result("neighbours", "fail", "observed_inputs", (
                f"确认文件里有本表对 {value['table']} 按 {_columns(value['columns'])} 的观测"
                f"（{observation_text(value)}），observed_inputs 没有；{GIVE_BACK}")))
    return results


# ------------------------------------------------------------------ shared


def _slot(check: str, at: str, slot, observation, confirmed, what: str) -> list[dict]:
    """A document's observation slot held to the confirmation of it."""
    if confirmed is None:
        return [_result(check, "warn", at, f"写了{what}，但{UNCHECKED}")] if slot is not None else []
    if observation is None:
        return [] if slot is None else [_result(check, "fail", at, (
            f"确认文件里没有{what}，文档却写了；{GIVE_BACK}"))]
    if slot is None:
        return [_result(check, "fail", at, (
            f"确认文件里有{what}（{observation_text(observation)}），文档没有；{GIVE_BACK}"))]
    if slot != observation:
        return [_result(check, "fail", at, (
            f"{what}与确认文件不一致（{observation_text(observation)}）；{GIVE_BACK}"))]
    return [_result(check, "pass", at)]
