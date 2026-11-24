"""How an observation is said in words: where, by which query, on which day, what it counted.

An observation -- what a platform query found in the partitions it read -- is no
definition, so none of these sentences says 「唯一」: a row or an input table is "counted
by (columns) without a duplicate" within the partitions read, a column's values come with
their counts and are no code list. ``semantic facts``, validation messages and every
reader of a table-semantics document (the table page, the context pack, the catalog
index, ...) say it the same way, so the words live in this leaf module, which imports
nothing from ``scope_lineage`` and so every layer can reach it.

Each function takes the observation as ``table-semantics/1`` carries it (``observation``
plus ``grain_columns`` / ``columns`` / ``values``) and reads nothing else.
"""

from __future__ import annotations


def partition_text(partition: dict) -> str:
    """The partitions an observation read, in words: 「分区 dt=20261119」, 「分区 dt 20261118、
    20261119」, 「分区 dt 20261116–20261122 共 7 个分区」, or 「全表」."""
    column = partition.get("column")
    if column is None:
        return "全表"
    if "from" in partition:
        count = f" 共 {partition['count']} 个分区" if partition.get("count") else ""
        return f"分区 {column} {partition['from']}–{partition['to']}{count}"
    values = [str(item) for item in partition.get("values") or []]
    if len(values) == 1:
        return f"分区 {column}={values[0]}"
    return f"分区 {column} {'、'.join(values)}" if values else f"分区 {column}"


def where_text(value: dict) -> str:
    """「在分区 … 内（查询 …，… 执行，N 行）」: where and by which query an observation was made."""
    text = partition_text(value["partition"])
    place = f"在{text}内" if text == "全表" or text.endswith("个分区") else f"在{text} 内"
    parts = [f"查询 {one_line(value['query'])}"]
    if value.get("requested"):
        parts.append(f"原定 {one_line(value['requested'])}，回退到最近可用分区")
    if value.get("filter"):
        parts.append(f"条件 {one_line(value['filter'])}")
    parts.append(f"{value['on']} 执行")
    parts.append(f"{value['rows']} 行")
    if value.get("observed_on"):
        parts.append(f"取自 {one_line(value['observed_on'])}")
    return f"{place}（{'，'.join(parts)}）"


def counted_text(value: dict, columns) -> str:
    """「按 (a, b) 计数无重复（N 个键）」, or with duplicates; how the partitions were counted
    when there were several."""
    keys = value.get("keys")
    if value["unique"] == "yes":
        text = f"按 {columns_text(columns)} 计数无重复" + (f"（{keys} 个键）" if keys is not None else "")
    else:
        duplicates = value.get("duplicate_keys")
        counts = [f"{keys} 个键里" if keys is not None else None,
                  f"{duplicates} 个重复" if duplicates is not None else None]
        detail = " ".join(item for item in counts if item)
        text = f"按 {columns_text(columns)} 计数有重复" + (f"（{detail}）" if detail else "")
    partition = value["partition"]
    several = "from" in partition or len(partition.get("values") or []) > 1
    if several:
        text += ("，每个分区内分别计数" if value["within"] == "each_partition"
                 else "，所有观测分区合起来计数")
    return text


def values_text(value: dict) -> str:
    """The values a column was seen to hold, with counts; the values not seen; the counts."""
    parts = []
    items = value.get("values") or []
    if items:
        seen = "、".join(f"{value_word(item['value'])}（{item['count']} 行）" for item in items)
        parts.append(f"出现 {seen}，{'已列全' if value['complete'] else '未列全'}")
    absent = value.get("absent") or []
    if absent:
        parts.append(f"没有出现 {'、'.join(value_word(item) for item in absent)}")
    counts = [f"去重 {value['distinct']} 个" if value.get("distinct") is not None else "",
              f"空值 {value['nulls']} 个" if value.get("nulls") is not None else ""]
    counts = "、".join(item for item in counts if item)
    if not items:
        parts.append(f"只给计数：{counts}" if counts else "只给计数")
    elif counts:
        parts.append(counts)
    return "；".join(parts)


def columns_text(columns) -> str:
    return f"({', '.join(str(column) for column in columns)})"


def one_line(text) -> str:
    return " ".join(str(text if text is not None else "").split())


EMPTY_STRING = "''（空串）"


def value_word(value) -> str:
    """An observed value as a reader sees it: the empty string as 「''（空串）」, not as nothing."""
    return EMPTY_STRING if str(value) == "" else one_line(value)


def observed_row_text(value: dict) -> str:
    """The row's observation as a reader says it: 「在分区 … 内（查询 …，… 执行，N 行）按 (k)
    计数无重复（N 个键），只说明这些分区，不是定义」."""
    return f"{where_text(value)}{counted_text(value, value['grain_columns'])}，只说明这些分区，不是定义"


def observed_input_text(value: dict) -> str:
    """An input table's observation after the table's name: where, what it counted, and what
    that means for a join on these columns -- under this table's read conditions only."""
    if value["unique"] == "yes":
        effect = "按这几列关联它时在该分区内不放大；别的分区、别的目标表没观测"
    else:
        effect = "按这几列关联它时会放大行数"
    return f"{where_text(value)}{counted_text(value, value['columns'])}；{effect}"


def observed_values_text(column: dict) -> str:
    """A column's observed values as a reader says them: 「观测：在分区 … 内（…）出现 …」, the
    values off its code list and the codes not seen, and that they are no code list.

    Values are compared with the code list only when the query read this column itself: a
    value read from a source column (``observed_on``) need not be this column's value."""
    value = column["observed_values"]
    parts = [f"观测：{where_text(value)}{values_text(value)}"]
    codes = [str(item.get("value")) for item in column.get("code_values") or []]
    if codes and not value.get("observed_on"):
        seen = [str(item["value"]) for item in value.get("values") or []]
        off = [item for item in seen if item not in codes]
        if off:
            parts.append(f"码值表外：{'、'.join(value_word(item) for item in off)}")
        absent = {str(item) for item in value.get("absent") or []}
        unseen = [item for item in codes if item not in seen and item not in absent]
        if value["complete"] and unseen:
            parts.append(f"码值表里没出现：{'、'.join(value_word(item) for item in unseen)}")
    parts.append("观测不给含义，不是码值表")
    return "；".join(parts)
