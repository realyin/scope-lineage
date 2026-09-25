"""The four sections of a packet: target, tasks, inputs, lineage.

Each section reads the producing statements' semantic profiles, the corpus's table cards
and, when the caller has one, the schema metadata. Metadata wins where both speak (it
holds every column, the profile only the ones the statement used), and every comment is
masked the way ``parse`` masks comments by default.
"""

from __future__ import annotations

from ..redaction import redact
from . import packet_facts as facts
from .names import bare_table


def _comment(text) -> str | None:
    return redact(text) if text else None


# ------------------------------------------------------------------ target


def target_section(table: str, statements: list, corpus) -> dict:
    meta = corpus.metadata(table) or {}
    first = statements[0][1].get("task") or {}
    columns, source = _target_columns(meta, first, statements)
    partitions = {
        name
        for _, statement in statements
        for name in ((statement.get("task") or {}).get("partition") or {}).get("columns") or []
    }
    card = corpus.card(table)
    return {
        "table": table,
        "comment": _comment(meta.get("comment") or first.get("target_table_comment")),
        "description": _comment(meta.get("description")),
        "layer": meta.get("layer") or card.get("layer"),
        "domain": meta.get("domain") or card.get("domain"),
        "metadata_source": source,
        "columns": [
            {"name": column["name"], "type": column.get("type"),
             "comment": _comment(column.get("comment")), "partition": column["name"] in partitions}
            for column in columns
        ],
    }


def _target_columns(meta: dict, first: dict, statements: list) -> tuple[list[dict], str]:
    """The target's columns in table order: the schema's, the lineage's, or the fields'."""
    if meta.get("columns"):
        return list(meta["columns"]), "schema"
    if first.get("target_declared_columns"):
        return list(first["target_declared_columns"]), "lineage"
    columns: list[dict] = []
    for _, statement in statements:
        partition = ((statement.get("task") or {}).get("partition") or {}).get("columns") or []
        written = [
            {"name": f.get("column"), "type": f.get("type"), "comment": f.get("target_comment")}
            for f in statement.get("fields") or []
        ] + [{"name": name, "type": None, "comment": None} for name in partition]
        columns.extend(c for c in written if c["name"] not in {k["name"] for k in columns})
    return columns, "fields"


# ------------------------------------------------------------------ tasks


def tasks_section(statements: list, corpus) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for task, statement in statements:
        grouped.setdefault(task, []).append(statement)
    return [_task_entry(task, group, corpus) for task, group in grouped.items()]


def _task_entry(task: str, group: list[dict], corpus) -> dict:
    info = group[0].get("task") or {}
    meta = info.get("meta") or {}
    record = corpus.tasks.find([task, meta.get("task_name")], meta.get("source_file")) or {}
    return {
        "name": task,
        "task_id": meta.get("task_id"),
        "description": meta.get("description"),
        "schedule": meta.get("schedule"),
        "schedule_cycle": meta.get("schedule_cycle"),
        "project": meta.get("project"),
        "upstream_tasks": list(meta.get("upstream_tasks") or []),
        "downstream_tasks": list(meta.get("downstream_tasks") or []),
        "header_comments": list(info.get("header_comments") or []),
        "statements": [statement.get("statement_id") for statement in group],
        "source_file": meta.get("source_file") or record.get("source_file"),
        "sql": record.get("sql"),
    }


# ------------------------------------------------------------------ inputs


def inputs_section(statements: list, rules: list[dict], corpus) -> list[dict]:
    merged: dict[str, dict] = {}
    for _, statement in statements:
        for item in statement.get("inputs") or []:
            table = bare_table(item.get("table"))
            entry = merged.setdefault(table, _new_input(table, item, corpus))
            entry["roles"].extend(r for r in item.get("roles") or [] if r not in entry["roles"])
            entry["driving"] = entry["driving"] or bool(item.get("driving"))
            for column in item.get("used_columns") or []:
                usages = entry["_used"].setdefault(str(column.get("name")), [])
                usages.extend(u for u in column.get("usages") or [] if u not in usages)
    return [_finish_input(merged[table], rules) for table in sorted(merged)]


def _new_input(table: str, item: dict, corpus) -> dict:
    meta = corpus.metadata(table) or {}
    producers = [p.get("task") for p in corpus.card(table).get("produced_by") or []]
    return {
        "table": table,
        "comment": _comment(meta.get("comment") or item.get("comment")),
        "layer": meta.get("layer") or item.get("layer"),
        "roles": [],
        "driving": False,
        "producers": sorted({str(task) for task in producers if task}),
        "_declared": list(meta.get("columns") or item.get("declared_columns") or []),
        "_used": {},
    }


def _finish_input(entry: dict, rules: list[dict]) -> dict:
    declared, used = entry.pop("_declared"), entry.pop("_used")
    names = [str(column.get("name")) for column in declared]
    declared = declared + [{"name": name} for name in used if name not in names]
    columns = [
        {"name": str(column.get("name")), "type": column.get("type"),
         "comment": _comment(column.get("comment")),
         "used": str(column.get("name")) in used, "usages": used.get(str(column.get("name")), [])}
        for column in declared
    ]
    return {**entry, **facts.input_time_facts(entry["table"], rules, columns), "columns": columns}


# ------------------------------------------------------------------ lineage


def lineage_section(table: str, statements: list, rules: list[dict], target: dict, corpus) -> dict:
    producers = {task for task, _ in statements}
    inputs = sorted({
        bare_table(item.get("table"))
        for _, statement in statements
        for item in statement.get("inputs") or []
    })
    return {
        "columns": _column_lineage(target, statements),
        "rules": rules,
        "keys": [facts.statement_keys(task, statement) for task, statement in statements],
        "partition": [facts.statement_partition(task, statement) for task, statement in statements],
        "upstream_tables": inputs,
        "upstream_tasks": _upstream_tasks(inputs, statements, producers, corpus),
        "downstream": _downstream(table, statements, producers, corpus),
    }


def _column_lineage(target: dict, statements: list) -> list[dict]:
    return [
        {
            "column": column["name"],
            "producers": [
                facts.column_producer(task, statement, field)
                for task, statement in statements
                for field in statement.get("fields") or []
                if str(field.get("column")) == column["name"]
            ],
        }
        for column in target["columns"]
    ]


def _upstream_tasks(inputs: list[str], statements: list, producers: set, corpus) -> list[str]:
    found = {
        str(producer.get("task"))
        for table in inputs
        for producer in corpus.card(table).get("produced_by") or []
    }
    for _, statement in statements:
        found.update(((statement.get("task") or {}).get("meta") or {}).get("upstream_tasks") or [])
    return sorted(found - producers)


def _downstream(table: str, statements: list, producers: set, corpus) -> list[dict]:
    """Who reads the table: the corpus's proven consumers, then the declared ones."""
    entries: dict[str, dict] = {}
    for consumer in corpus.card(table).get("consumed_by") or []:
        task = str(consumer.get("task"))
        if task in producers:
            continue
        entry = entries.setdefault(task, _downstream_entry(task, "lineage", corpus))
        role = consumer.get("role_in_task")
        if role and role not in entry["roles"]:
            entry["roles"].append(role)
    for _, statement in statements:
        for task in ((statement.get("task") or {}).get("meta") or {}).get("downstream_tasks") or []:
            if task not in entries and task not in producers:
                entries[task] = _downstream_entry(task, "task_meta", corpus)
    return [entries[task] for task in sorted(entries)]


def _downstream_entry(task: str, source: str, corpus) -> dict:
    return {"task": task, "tables": corpus.tables_written_by(task), "source": source, "roles": []}
