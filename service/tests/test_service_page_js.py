"""The page's pure JavaScript functions, run with node when it is on PATH.

There is no JavaScript test framework here and nothing is installed: node runs a small
module that imports the page's own files and prints JSON, and the assertions are Python.
The graph layout (one line and one label per related pair; no two labels meeting, none on
a concept), the column filter of a wide table, the table sorts offered and the document
title are pure functions, so their geometry and text can be checked without a browser.
What a browser does with them (drawing, clicking, scrolling) is not exercised here.
Skipped where node is not available.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def _run(script: str):
    static = resources.files("scope_lineage_service") / "static"
    base = static.joinpath("graph.js").as_uri().rsplit("/", 1)[0]
    module = script.replace("STATIC", base)
    done = subprocess.run(
        [NODE, "--input-type=module", "-e", module], capture_output=True, text=True, timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _node(id_, centre=False):
    return {"id": id_, "name": f"概念{id_}", "kind": "entity", "tables": 1, "centre": centre}


def _edge(id_, source, target, name):
    return {"id": id_, "kind": "association", "from": source, "to": target, "name": name}


def _layout(graph):
    return _run(
        "import { layoutGraph } from 'STATIC/graph.js';\n"
        f"console.log(JSON.stringify(layoutGraph({json.dumps(graph, ensure_ascii=False)})));"
    )


def _overlap(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and \
        a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def _boxes(layout):
    nodes = [
        {"x": n["x"] - n["w"] / 2, "y": n["y"] - n["h"] / 2, "w": n["w"], "h": n["h"]}
        for n in layout["nodes"]
    ]
    labels = [edge["label"] for edge in layout["edges"] if edge["label"]]
    return nodes, labels


GRAPH = {
    "nodes": [_node("a", centre=True), _node("b"), _node("c")],
    "edges": [
        _edge("r1", "a", "b", "借款人"), _edge("r2", "a", "b", "付款人"),
        _edge("r3", "b", "a", "担保人"), _edge("r4", "a", "c", "持有"),
        _edge("r5", "a", "a", "续借"), _edge("r6", "a", "a", "合并"),
        {"kind": "role", "from": "c", "to": "a", "name": ""},
    ],
}


def _participation(event, concept, role):
    return {"id": f"rel:{event}.{role}", "kind": "participation", "from": event, "to": concept,
            "name": role}


def _crowded(neighbours: int) -> dict:
    """An event among ``neighbours`` concepts: a participation to each, three more roles
    for the first and two for the second, a named relation to each beside it, every
    neighbour related to the next, and long names."""
    nodes = [_node("e", centre=True)] + [
        {**_node(f"n{i:02d}"), "name": f"一个名字相当长的概念第{i}号"} for i in range(neighbours)
    ]
    edges = []
    for i in range(neighbours):
        edges.append(_participation("e", f"n{i:02d}", f"role_{i}"))
        edges.append(_edge(f"r{i}", "e", f"n{i:02d}", f"一条名字也很长的关系第{i}号"))
        edges.append(_edge(f"s{i}", f"n{i:02d}", f"n{(i + 1) % neighbours:02d}", "相邻"))
    edges += [_participation("e", "n00", f"extra_{k}") for k in range(3)]
    edges += [_participation("e", "n01", f"other_{k}") for k in range(2)]
    return {"nodes": nodes, "edges": edges}


def _assert_legible(layout) -> None:
    nodes, labels = _boxes(layout)
    for i, label in enumerate(labels):
        assert not any(_overlap(label, node) for node in nodes), label
        assert not any(_overlap(label, other) for other in labels[i + 1:]), (label, labels)


def test_the_relations_of_one_pair_share_one_line_and_one_label() -> None:
    layout = _layout(GRAPH)

    pairs = sorted(tuple(sorted((edge["from"], edge["to"]))) for edge in layout["edges"])
    assert pairs == [("a", "a"), ("a", "b"), ("a", "c")]
    between = next(edge for edge in layout["edges"] if {edge["from"], edge["to"]} == {"a", "b"})
    assert between["label"]["lines"] == ["借款人", "付款人", "担保人"]
    assert between["forward"] and between["backward"]
    with_role = next(edge for edge in layout["edges"] if {edge["from"], edge["to"]} == {"a", "c"})
    assert with_role["label"]["lines"] == ["持有", "角色"]
    _assert_legible(layout)


@pytest.mark.parametrize("neighbours", [3, 7, 12, 23])
def test_no_two_labels_meet_and_none_covers_a_concept(neighbours: int) -> None:
    layout = _layout(_crowded(neighbours))

    assert layout["labelled"] is True
    assert all(edge["label"] for edge in layout["edges"])
    _assert_legible(layout)
    view = [float(n) for n in layout["viewBox"].split()]
    for edge in layout["edges"]:
        label = edge["label"]
        assert view[0] <= label["x"] and label["x"] + label["w"] <= view[0] + view[2]
        assert view[1] <= label["y"] and label["y"] + label["h"] <= view[1] + view[3]


def test_a_participation_is_labelled_in_words_and_its_roles_kept_whole() -> None:
    layout = _layout(_crowded(7))

    first = next(edge for edge in layout["edges"] if {edge["from"], edge["to"]} == {"e", "n00"})
    assert first["label"]["lines"] == ["参与者（4 个角色）", "一条名字也很长的关系第0号"]
    second = next(edge for edge in layout["edges"] if {edge["from"], edge["to"]} == {"e", "n01"})
    assert second["label"]["lines"][0] == "参与者（3 个角色）"
    every = " ".join(line for edge in layout["edges"] for line in edge["label"]["lines"])
    assert "role_" not in every and "extra_" not in every
    titles = _run(
        "import { relationTitle } from 'STATIC/graph.js';\n"
        "const names = new Map([['e', '某事件'], ['n00', '某概念']]);\n"
        "console.log(JSON.stringify([relationTitle({kind: 'participation', from: 'e', to: 'n00',"
        " name: 'extra_0'}, names), relationTitle({kind: 'role', from: 'n00', to: 'e', name: ''},"
        " names)]));"
    )
    assert titles == ["某事件 的参与者：某概念（角色名 extra_0）", "某概念 是 某事件 承担的角色"]


def test_a_long_label_line_is_shortened_only_with_its_full_text_kept() -> None:
    long = "一条非常非常非常非常非常非常长的关系名字"
    graph = {"nodes": [_node("a", centre=True), _node("b")],
             "edges": [_edge("r1", "a", "b", long)]}
    (edge,) = _layout(graph)["edges"]

    assert edge["label"]["full"] == [long]
    assert edge["label"]["lines"][0].endswith("…") and len(edge["label"]["lines"][0]) <= 18
    many = {"nodes": graph["nodes"],
            "edges": [_edge(f"r{i}", "a", "b", f"关系{i}") for i in range(6)]}
    (edge,) = _layout(many)["edges"]
    assert edge["label"]["lines"] == ["关系0", "关系1", "关系2", "等 6 条关系"]
    assert edge["label"]["full"] == [f"关系{i}" for i in range(6)]


def test_past_the_limit_lines_carry_no_labels() -> None:
    layout = _layout(_crowded(30))

    assert layout["labelled"] is False
    assert all(edge["label"] is None for edge in layout["edges"])


def test_a_small_graph_is_drawn_at_a_small_natural_size() -> None:
    layout = _layout({"nodes": GRAPH["nodes"], "edges": GRAPH["edges"][:4]})

    assert layout["width"] <= 760 and layout["height"] <= 460, layout["viewBox"]
    view = [float(n) for n in layout["viewBox"].split()]
    assert view[2:] == [layout["width"], layout["height"]]


def test_a_crowded_neighbourhood_spreads_its_nodes_apart() -> None:
    nodes = [_node("c", centre=True)] + [_node(f"n{i}") for i in range(30)]
    edges = [_edge(f"r{i}", f"n{i}", "c", "参与") for i in range(30)]

    boxes, _ = _boxes(_layout({"nodes": nodes, "edges": edges}))

    for i, box in enumerate(boxes):
        assert not any(_overlap(box, other) for other in boxes[i + 1:])


def test_the_title_names_the_view_shown_and_the_site_once() -> None:
    titles = _run(
        "import { pageTitle } from 'STATIC/dom.js';\n"
        "console.log(JSON.stringify([pageTitle('本体目录：样例', '本体目录', false),"
        " pageTitle('db.t', '表', false), pageTitle(null, '待确认问题', false),"
        " pageTitle(null, '概念', true), pageTitle(null, '本体目录', true),"
        " pageTitle(null, null, false)]));"
    )

    assert titles == [
        "本体目录：样例", "db.t · 本体目录", "待确认问题 · 本体目录", "正在加载：概念 · 本体目录",
        "正在加载 · 本体目录", "本体目录",
    ]


COLUMNS = [
    {"column": "cust_id", "to": "identifier", "ref": "id:customer", "ref_name": "客户号"},
    {"column": "amt", "to": "attribute", "ref": "attr:x.amount", "ref_name": "金额"},
    {"column": "status_cd", "to": "attribute", "ref": "attr:x.status", "ref_name": "状态",
     "code_map": {"1": "正常"}},
    {"column": "fee", "to": "attribute", "ref": "attr:x.fee", "ref_name": "费用",
     "derivation": "两项相加"},
    {"column": "etl_ts", "to": "technical"},
    {"column": "misc", "to": "unmapped"},
]
UNITS = [["amt", {"column": "amt", "text": "材料未给"}]]


def _filter(needle, binding=None):
    return _run(
        "import { filterColumns } from 'STATIC/views.js';\n"
        f"const columns = {json.dumps(COLUMNS, ensure_ascii=False)};\n"
        f"const units = new Map({json.dumps(UNITS, ensure_ascii=False)});\n"
        f"console.log(JSON.stringify(filterColumns(columns, {json.dumps(needle, ensure_ascii=False)},"
        f" {json.dumps(binding)}, units)));"
    )


def test_the_column_filter_looks_in_names_targets_codes_derivations_and_units() -> None:
    assert _filter("") == [0, 1, 2, 3, 4, 5]
    assert _filter("  CUST ") == [0]
    assert _filter("金额") == [1]
    assert _filter("正常") == [2]
    assert _filter("两项") == [3]
    assert _filter("材料未给") == [1]
    assert _filter("技术列") == [4]
    assert _filter("", "attribute") == [1, 2, 3]
    assert _filter("费", "attribute") == [3]
    assert _filter("nothing") == []


def test_the_binding_choices_count_each_kind() -> None:
    counts = _run(
        "import { bindingCounts } from 'STATIC/views.js';\n"
        f"console.log(JSON.stringify(bindingCounts({json.dumps(COLUMNS, ensure_ascii=False)})));"
    )
    assert counts == [["identifier", 1], ["attribute", 3], ["technical", 1], ["unmapped", 1]]


def test_a_table_name_may_wrap_only_after_a_dot_or_an_underscore() -> None:
    segments = _run(
        "import { nameSegments } from 'STATIC/dom.js';\n"
        "console.log(JSON.stringify([nameSegments('demo_dwd.dwd_lending_loan_df'),"
        " nameSegments('plain')]));"
    )
    assert segments == [["demo_", "dwd.", "dwd_", "lending_", "loan_", "df"], ["plain"]]


def test_the_wide_lists_give_every_column_a_width_class() -> None:
    classes = _run(
        "import { GRID_CLASSES, TABLE_LIST_CLASSES } from 'STATIC/views.js';\n"
        "console.log(JSON.stringify([TABLE_LIST_CLASSES, GRID_CLASSES]));"
    )
    # table list: 表, 概念, 种类, 时间形态, 绑定列, 说明 (the by-table columns are short too)
    assert classes[0] == ["col-name", "short", "short", "short", "short", "col-prose"]
    # a table's columns: 列, 绑定, 指向, 血缘, the detail button
    assert classes[1] == ["short", "short", "col-prose", "col-expr", "short"]


def test_the_table_sorts_offered_are_the_ones_the_server_takes() -> None:
    from scope_lineage.render.catalog_browse import TABLE_SORTS

    choices = _run(
        "import { TABLE_SORT_CHOICES } from 'STATIC/views.js';\n"
        "console.log(JSON.stringify(TABLE_SORT_CHOICES));"
    )
    values = [value for value, _ in choices]
    assert values[0] == ""
    assert {value.lstrip("-") for value in values[1:]} == set(TABLE_SORTS)
    assert len(values) == len(set(values))
