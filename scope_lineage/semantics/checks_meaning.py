"""Cross checks 10-11: row multiplication and derived codes.

Checks 1-9 hold a document's form to the packet; a page can pass all of them and still
tell a reader the wrong thing. These two read what the lineage already knows about the
rows and the values:

- 10 ``fan_out`` -- a JOIN whose right side the profile did not prove unique on the join
  keys can repeat a row per match; the reader has to be told, by name; a platform query's
  observation of that right side (``input:`` in the confirmations files) lets a sentence
  say it does not multiply rows *in the observed partition*, and nothing more;
- 11 ``derived_codes`` -- a CASE / IF with literal outputs defines the column's values,
  so each must be listed, and one that sounds like a single state (成功, 正常 ...) while
  gathering several source values needs a warning.

A packet written before these facts existed has none of them, and nothing is checked.
"""

from __future__ import annotations

import re

from .checks import _plain, result
from .names import bare_table
from .observed import partition_text
from .packet_notes import GRAIN_PATH

# 10 ------------------------------------------------------------------ fan out

_NO_EFFECT = re.compile(
    r"无影响|不影响(?:行数|粒度|记录数)?|不会(?:导致|造成|使)?(?:行数|记录)?(?:放大|膨胀|重复|增加|变多)"
    r"|不放大|行数不变"
)
# What just before a no-effect phrase turns it into its opposite: 不保证不放大, 未必不影响行数.
_NEGATED = re.compile(
    r"(?:(?:不能|无法|不|未|没有?|并不|并未|难以)(?:保证|确保|一定|见得|代表|意味着)"
    r"|未必|不一定|并非|不是|并不是)\s*$"
)
_LEFT_WORDS = re.compile(r"left\s*(?:outer\s*)?join|左关联|左连接|左联", re.IGNORECASE)
# A clause of a sentence, and the words that make a claim in it cover every join.
_CLAUSE_MARKS = "，,、：:（("
_UNIVERSAL = re.compile(r"都|均|全部|所有|一律|任何|皆")
_SENTENCES = re.compile(r"[。；;\n]")
# A no-effect claim made under a condition, with the case where the condition fails said: the
# condition before the claim, the rows multiplying after it or in the next sentence. "X 成立时 /
# 唯一时 / 不重复时" is a condition too; "不成立时 / 不唯一时" is its failing case, not one.
_CONDITION = re.compile(
    r"若|如果|假如|倘若|假设|只要|只有|一旦|除非|[当在][^，,。；;]*时"
    r"|(?<![不未])(?:成立|满足|唯一|不重复)时"
)
_MULTIPLIES = re.compile(
    r"(?<![不没未])(?:会|可能)[^，,。；;]{0,8}?(?:放大|膨胀|重复)|关联出多[行条]"
)
# A next sentence opening with the condition failing. "重复时" counts only at its very start, so
# a sentence opening "不重复时 …" is not taken for the failing case.
_FAILS_FIRST = re.compile(
    r"\s*(?:(?:若|如果|一旦)[^，,。；;]*?(?:不成立|不唯一|不满足)|(?:不成立|不满足|不唯一|重复)时)"
)
_OTHERWISE_FIRST = re.compile(r"\s*(?:否则|不然|反之)")
# A sentence saying it reports an observation, and the form the writer is given for one
# (「观测（查询 …，分区 …，… 执行）：…」, D16 5).
_OBSERVED = re.compile(r"观测")
_OBSERVED_FORM = re.compile(r"观测\s*[（(]\s*查询")


def check_fan_out(document: dict, packet: dict, confirmed=None) -> list[dict]:
    """Every right side not proven unique on its join keys is named in the note or a risk.

    Joins onto one right side (the same table joined under several aliases) are one item:
    naming the table once tells the reader. A sentence calling such a LEFT join harmless to
    the row count warns once, wherever it stands.

    Only a verdict on the grain path is about the row count: a JOIN below an aggregate
    (``fan_out.path`` ``argument`` and the like) can count a value twice but copies no
    output row, so it is neither asked to be named nor warned about when called harmless.
    A verdict without a path (a packet written before paths) is on the grain path. Every
    unproven join, on any path, still keeps its names from passing for a proven one's.

    An alias is unique within one SELECT, not within a packet: a right side is named for
    sure by its table, an alias no other right side carries, or its rule number (pN). A
    sentence naming it only by an alias another right side shares may be about that one,
    and warns.

    ``confirmed`` (:class:`~.confirmed.TableConfirmed`; None when no confirmations path was
    given, and then nothing below applies) carries what platform queries observed of the
    input tables. The naming stays required. An observation only lets a sentence call a
    join harmless in the observed partition (:func:`_observed_claim`); a sentence written
    in the observation form about a join no observation backs warns (:func:`_unbacked`);
    an observation that found duplicates is quoted in the failure to name the join.
    """
    summary = document["summary"]
    said = _sentences("summary.row.note", summary["row"].get("note"))
    everywhere = list(said)
    for index, watch in enumerate(summary["watch"]):
        found = _sentences(f"summary.watch[{index}]", watch["text"])
        everywhere += found
        said += found if watch["kind"] == "risk" else []
    groups: dict[tuple, list[dict]] = {}
    for rule in packet["lineage"]["rules"]:
        verdict = rule.get("fan_out") if rule["kind"] == "join" else None
        if verdict and verdict.get("status") != "safe":
            groups.setdefault(_right_side(rule), []).append(rule)
    held = {key: grain for key, rules in groups.items()
            if (grain := [r for r in rules if r["fan_out"].get("path") in (None, GRAIN_PATH)])}
    owners = _alias_owners(packet)
    results = [_named(rules, said, owners, confirmed) for rules in held.values()]
    left = [r for rules in held.values() for r in rules if "LEFT" in str(r.get("join_type")).upper()]
    every_name = [
        name for rule in packet["lineage"]["rules"] if rule["kind"] == "join"
        for name in join_names(rule)
    ]
    unproven = [rule for rules in groups.values() for rule in rules]
    return results + _harmless_left(
        left, everywhere, _safe_names(packet, groups), every_name, owners, confirmed,
    ) + _unbacked(unproven, everywhere, owners, confirmed)


def _right_side(rule: dict) -> tuple:
    """One right side: the tables a join reads (the same table under several aliases is one)."""
    return tuple(rule.get("right_tables") or [rule.get("right")])


def _alias_owners(packet: dict) -> dict[str, dict[tuple, list[str]]]:
    """Each right-side alias (lower case): the right sides carrying it, with their rule ids."""
    owners: dict[str, dict[tuple, list[str]]] = {}
    for rule in packet["lineage"]["rules"]:
        if rule["kind"] != "join":
            continue
        for alias in rule.get("right_aliases") or []:
            owners.setdefault(alias.lower(), {}).setdefault(_right_side(rule), []).append(rule["id"])
    return owners


def _shared_aliases(rules: list[dict], owners: dict) -> list[str]:
    """The aliases of these joins that another right side carries as well."""
    return list(dict.fromkeys(
        alias for rule in rules for alias in rule.get("right_aliases") or []
        if len(owners.get(alias.lower(), {})) > 1
    ))


def _sure_names(rules: list[dict], owners: dict) -> list[str]:
    """Names that point at these joins and no other: tables, unshared aliases, rule ids."""
    shared = {alias.lower() for alias in _shared_aliases(rules, owners)}
    names = [name for rule in rules for name in join_names(rule) if name.lower() not in shared]
    return list(dict.fromkeys(names + [rule["id"] for rule in rules]))


def _safe_names(packet: dict, groups: dict[tuple, list[dict]]) -> list[str]:
    """What a writer may call a join proven unique, less any name an unproven join shares."""
    unproven = {name.lower() for rules in groups.values() for r in rules for name in join_names(r)}
    return list(dict.fromkeys(
        name
        for rule in packet["lineage"]["rules"]
        if rule["kind"] == "join" and (rule.get("fan_out") or {}).get("status") == "safe"
        for name in join_names(rule) if name.lower() not in unproven
    ))


def _sentences(at: str, text) -> list[tuple[str, str]]:
    return [(at, part) for part in _SENTENCES.split(str(text or "")) if part.strip()]


def _label(rules: list[dict]) -> str:
    return "、".join(rules[0].get("right_tables") or [rules[0].get("right") or "?"])


def _named(rules: list[dict], said: list, owners: dict, confirmed=None) -> dict:
    at = "summary.row.note"
    if any(_mentions(text, _sure_names(rules, owners)) for _, text in said):
        return result("fan_out", "pass", at)
    shared = _shared_aliases(rules, owners)
    for where, text in said:
        aliases = [alias for alias in shared if _mentions(text, [alias])]
        if aliases:
            return _alias_only(rules, aliases, owners, where)
    names = [name for name in dict.fromkeys(n for rule in rules for n in join_names(rule))
             if name not in shared]
    first = rules[0]
    joins = "、".join(dict.fromkeys(str(rule.get("join_type") or "JOIN") for rule in rules))
    where = (f"ON {_plain(first['expression'])}，{first['task']}，材料包 {first['id']}"
             if len(rules) == 1 else f"{len(rules)} 处，材料包 {'、'.join(r['id'] for r in rules)}")
    return result("fan_out", "fail", at, (
        f"关联 {_label(rules)}（{joins}，{where}）的右侧没有被证明按关联键唯一"
        f"（{first['fan_out'].get('reason')}），一条记录可能匹配多条、让行数放大；在 "
        "summary.row.note 或一条 kind 为 risk 的 summary.watch 里点名它"
        f"（{'、'.join(names)} 任一），写明会不会放大行数、为什么{_duplicates(rules, confirmed)}"))


def _duplicates(rules: list[dict], confirmed) -> str:
    """「；观测到 N 个重复键（分区 P）」 for each observation that found the right side repeat."""
    seen = [obs for rule in rules for obs in observations(rule, confirmed, unique="no")]
    return "".join(dict.fromkeys(
        f"；观测到 {obs['duplicate_keys']} 个重复键（{partition_text(obs['partition'])}）"
        for obs in seen))


def observations(rule: dict, confirmed, unique: str | None = "yes") -> list[dict]:
    """The confirmed observations of a join's right side on its keys (D16 3.3).

    Only a right side reading a single table T (``right_tables == [T]``: a physical table
    or a subquery over one table) has one: an ``input:T`` observation whose columns are
    among the join's columns on T -- unique on fewer columns is unique on more. ``unique``
    keeps those that found it so (``yes`` / ``no``); None keeps both.
    """
    tables = rule.get("right_tables") or []
    if confirmed is None or len(tables) != 1:
        return []
    table = bare_table(tables[0])
    keys = {
        reference.rsplit(".", 1)[1].lower() for reference in rule.get("columns") or []
        if "." in reference and bare_table(reference.rsplit(".", 1)[0]) == table
    }
    return [
        fact.value for (name, columns), fact in confirmed.observed_inputs.items()
        if name == table and columns and set(columns) <= keys
        and (unique is None or fact.value.get("unique") == unique)
    ]


def _alias_only(rules: list[dict], aliases: list[str], owners: dict, where: str) -> dict:
    """The warning for joins a sentence names only by an alias other right sides share."""
    key, label = _right_side(rules[0]), _label(rules)
    ids = "、".join(rule["id"] for rule in rules)
    others = "、".join(dict.fromkeys(
        rule_id for alias in aliases for side, rule_ids in owners[alias.lower()].items()
        if side != key for rule_id in rule_ids
    ))
    said = "、".join(aliases)
    return result("fan_out", "warn", where, (
        f"关联 {label}（{ids}）只被别名 {said} 点到，而 {said} 也是 {others} 的右侧；"
        f"这句可能在说 {others}，{label} 可能没写——用表名或 pN 点名 {label}，"
        "写明会不会放大行数"))


def _harmless_left(
    left: list[dict], everywhere: list, safe_names: list[str], every_name: list[str],
    owners: dict, confirmed=None,
) -> list[dict]:
    """One warning per place that calls an unproven LEFT join harmless to the row count.

    A sentence naming no unproven join but saying 左关联 is taken to mean them all, unless
    it names a join proven unique and makes no claim about every join (都, 所有 ...) in the
    clause that says 不放大. A claim made under a condition whose failing case is said
    (:func:`_conditional`) is no claim. A sentence naming some joins for sure (table,
    unshared alias, pN) is about those; only one naming none that way is read by alias.
    Nor is a claim reporting an observation the confirmations back (:func:`_observed_claim`).
    """
    if not left:
        return []
    results, warned = [], set()
    for index, (where, text) in enumerate(everywhere):
        named = [rule for rule in left if _mentions(text, _sure_names([rule], owners))] or [
            rule for rule in left if _mentions(text, join_names(rule))]
        following = everywhere[index + 1] if index + 1 < len(everywhere) else None
        after = following[1] if following and following[0] == where else ""
        claims = [
            claim for claim in _no_effect_claims(text)
            if not _conditional(text, claim, after, every_name)
        ]
        if where in warned or not claims:
            continue
        if named and _observed_claim(text, claims, _about(text, named), confirmed):
            continue
        about_safe = _mentions(text, safe_names) and not any(
            _UNIVERSAL.search(_clause(text, claim)) for claim in claims
        )
        if named or (_LEFT_WORDS.search(text) and not about_safe):
            warned.add(where)
            label = "、".join(dict.fromkeys(_label([rule]) for rule in named or left))
            results.append(result("fan_out", "warn", where, (
                f"把左关联写成了不影响行数，但 {label} 的右侧没有被证明按关联键唯一："
                "LEFT JOIN 只保证左侧记录不丢，右侧一对多时照样放大行数；改写这句话，"
                "写明右侧什么情况下会有多条")))
    return results


def _about(text: str, named: list[dict]) -> list[dict]:
    """The joins a sentence speaks of: those it names by rule number (pN) when it names any
    that way, else all it names. 「T 按 (k) 无重复，p62 不放大」 is about p62, though the
    table's name also names every other join onto T."""
    return [rule for rule in named if _mentions(text, [rule["id"]])] or named


def _observed_claim(text: str, claims: list[re.Match], about: list[dict], confirmed) -> bool:
    """Whether a sentence's no-effect claims report observations the confirmations back.

    The sentence says 观测; no claim's clause speaks of every join (都, 所有 ...); and each
    join it is about has its own observation found unique, whose partition the sentence
    names (a value, an end of the range, or 全表).
    """
    if confirmed is None or not _OBSERVED.search(text):
        return False
    if any(_UNIVERSAL.search(_clause(text, claim)) for claim in claims):
        return False
    return all(
        any(_names_partition(text, obs["partition"]) for obs in observations(rule, confirmed))
        for rule in about
    )


def _names_partition(text: str, partition: dict) -> bool:
    if partition.get("column") is None:
        return "全表" in text
    marks = [str(value) for value in partition.get("values") or []]
    marks += [str(partition[end]) for end in ("from", "to") if partition.get(end)]
    return any(mark and mark in text for mark in marks)


def _unbacked(rules: list[dict], everywhere: list, owners: dict, confirmed) -> list[dict]:
    """One warning per place whose sentence, in the observation form 「观测（查询 …」, speaks
    of an unproven join the confirmations hold no observation of (a single-table right side,
    the join's keys). Without a confirmations path there is nothing to hold it to."""
    if confirmed is None:
        return []
    results, warned = [], set()
    for where, text in everywhere:
        if where in warned or not _OBSERVED_FORM.search(text):
            continue
        named = [rule for rule in rules if _mentions(text, _sure_names([rule], owners))] or [
            rule for rule in rules if _mentions(text, join_names(rule))]
        missing = [rule for rule in _about(text, named)
                   if not observations(rule, confirmed, unique=None)]
        if not missing:
            continue
        warned.add(where)
        joins = "、".join(f"{_label([rule])}（{rule['id']}）" for rule in missing)
        inputs = "、".join(dict.fromkeys(
            f"input:{bare_table(rule['right_tables'][0])}" if len(rule.get("right_tables") or []) == 1
            else f"右侧读 {len(rule.get('right_tables') or [])} 张表，单表观测不适用"
            for rule in missing))
        results.append(result("fan_out", "warn", where, (
            f"这句用了观测的写法（观测（查询 …）），但确认文件里没有 {joins} 右侧按关联键的观测"
            f"（{inputs}）：观测只照 semantic facts 里「观测：」开头的行写；没有观测就照旧写右侧"
            "未被证明按关联键唯一、会不会放大行数")))
    return results


def _no_effect_claims(text: str) -> list[re.Match]:
    """The no-effect phrases of ``text`` not negated by what stands just before them."""
    return [m for m in _NO_EFFECT.finditer(text) if not _NEGATED.search(text[: m.start()])]


def _conditional(text: str, claim: re.Match, after: str, every_name: list[str]) -> bool:
    """Whether a no-effect claim is made under a condition with its failing case said.

    One of: a condition before the claim and the rows multiplying after it in the sentence;
    a next sentence opening with the condition failing (若 … 不成立 / 不唯一 / 不满足, or
    不成立时 / 不满足时 / 不唯一时 / 重复时) that says the rows multiply; a condition before the claim and a next sentence opening with
    否则 / 不然 / 反之 that says so. The failing case must name no join the sentence has not
    named up to the claim: a case about another join says nothing about this one.
    """
    before, rest = text[: claim.end()], text[claim.end():]
    conditioned = bool(_CONDITION.search(text[: claim.start()]))
    if conditioned and _MULTIPLIES.search(rest):
        case = rest
    elif after and _MULTIPLIES.search(after) and (
        _FAILS_FIRST.match(after) or (conditioned and _OTHERWISE_FIRST.match(after))
    ):
        case = after
    else:
        return False
    return not _mentions(case, [name for name in every_name if not _mentions(before, [name])])


def _clause(text: str, claim: re.Match) -> str:
    """The clause of ``text`` holding ``claim``: up to the nearest mark on either side."""
    start = max(text.rfind(mark, 0, claim.start()) for mark in _CLAUSE_MARKS) + 1
    ends = [i for i in (text.find(mark, claim.end()) for mark in _CLAUSE_MARKS) if i >= 0]
    return text[start: min(ends, default=len(text))]


def join_names(rule: dict) -> list[str]:
    """What a writer may call a JOIN's right side: its tables (whole and bare), its aliases."""
    names = []
    for table in rule.get("right_tables") or []:
        names += [table, table.rsplit(".", 1)[-1]]
    right = str(rule.get("right") or "")
    names += [right] if right and ":" not in right else []
    names += list(rule.get("right_aliases") or [])
    return list(dict.fromkeys(name for name in names if name))


def _mentions(text: str, names: list[str]) -> bool:
    return any(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text, re.IGNORECASE)
        for name in names
    )


# 11 ------------------------------------------------------------------ derived codes

# A meaning that names a single good state; "没有成功…" and an aside "（有效期外）" do not.
_SUCCESS_WORD = re.compile(r"成功|正常|通过|有效")
# A negation written straight before the word (未成功, 不通过) ...
_NEGATION_CHARS = "不未非无没"
# ... or a negating phrase a little before it (未能通过, 无法正常使用, 未能正常通过). A
# phrase is matched whole, so 非常成功 ("very successful") is not read as 非 + 成功.
_NEGATION_PHRASES = ("未能", "无法", "不曾", "没能", "未曾", "不能", "没有", "尚未", "从未")
_NEGATION_WINDOW = 4
_CLAUSE_BREAK = re.compile(r"[，,；;。、：:！!？?\s]")
# A parenthetical aside, full-width or ASCII; check 12 drops it too.
ASIDE = re.compile(r"（[^）]*）|\([^)]*\)")


def success_like(meaning: str) -> bool:
    """Whether a meaning names a good state that no nearby negation takes back."""
    text = ASIDE.sub("", meaning)
    return any(not _negated(text[:match.start()]) for match in _SUCCESS_WORD.finditer(text))


def _negated(before: str) -> bool:
    """A negation char right before the word, or a negating phrase in the clause's last
    few characters before it."""
    window = _CLAUSE_BREAK.split(before[-_NEGATION_WINDOW:])[-1]
    return before.endswith(tuple(_NEGATION_CHARS)) or any(
        phrase in window for phrase in _NEGATION_PHRASES
    )


def check_derived_codes(document: dict, packet: dict) -> list[dict]:
    """A CASE / IF column lists each literal it returns; a merged success value is watched."""
    outputs = _case_outputs(packet)
    watched = {ref for watch in document["summary"]["watch"] for ref in watch.get("refs") or []}
    results = []
    for ci, column in enumerate(document["columns"]):
        for output in outputs.get(column["column"], {}).values():
            results += _derived_code(ci, column, output, watched)
    return results


def _case_outputs(packet: dict) -> dict[str, dict[str, dict]]:
    """``column -> value -> output``, one output per value over every producer.

    A literal beside an ELSE that computes something other than the compared source
    (``else: computed``, a stamp or a default) is published but is not a code the column
    holds, so it is not asked for; a recode of the source (``else: source``) is.
    """
    merged: dict[str, dict[str, dict]] = {}
    for entry in packet["lineage"]["columns"]:
        for producer in entry["producers"]:
            for output in producer.get("case_outputs") or []:
                if output.get("else") == "computed":
                    continue
                values = merged.setdefault(entry["column"], {})
                seen = values.setdefault(
                    output["value"], {**output, "when": [], "source_values": None, "many": False}
                )
                seen["when"] += [w for w in output["when"] if w not in seen["when"]]
                seen["catch_all"] = seen["catch_all"] or output["catch_all"]
                # A producer that cannot list its source values (a range, a computed
                # test) says nothing about how many there are; it must not erase the
                # list another producer gives -- that erased the warning it earned.
                sources = output["source_values"]
                if sources is not None:
                    seen["source_values"] = list(dict.fromkeys(
                        (seen["source_values"] or []) + sources))
                seen["many"] = seen["many"] or output["catch_all"] or len(sources or []) > 1
    return merged


def _derived_code(ci: int, column: dict, output: dict, watched: set) -> list[dict]:
    name, value = column["column"], output["value"]
    when = "；".join("其余值（ELSE）" if w == "ELSE" else _plain(w) for w in output["when"])
    codes = {str(code["value"]).strip().strip("'\""): code for code in column.get("code_values") or []}
    code = codes.get(value)
    if code is None:
        return [result("derived_codes", "fail", f"columns[{ci}].code_values", (
            f"列 {name} 由 CASE/IF 派生，会输出 {value!r}（条件：{when}），但 code_values 里"
            "没有这个值；补上它和它的含义（依据分支条件与注释），拿不准含义就标 "
            "unconfirmed: true 并在 questions 里提问"))]
    passed = result("derived_codes", "pass", f"columns[{ci}].code_values")
    many = (output.get("many") or output["catch_all"]
            or len(output["source_values"] or []) > 1)
    if not (many and success_like(code["meaning"])):
        return [passed]
    if column.get("watch") or f"column:{name}" in watched:
        return [passed]
    return [passed, result("derived_codes", "warn", f"columns[{ci}].watch", (
        f"码值 {value!r} 写成「{code['meaning']}」，但它由多个来源值归并而来（{when}）；"
        f"在列 {name} 的 watch 里写明哪些来源值被算作「{code['meaning']}」，"
        "免得读者以为它只对应一种状态"))]
