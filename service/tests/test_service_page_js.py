"""The page's pure JavaScript functions, run with node when it is on PATH.

There is no JavaScript test framework here and nothing is installed: node runs a small
module that imports the page's own files and prints JSON, and the assertions are Python.
The graph layout and the document title are pure functions, so their geometry and text
can be checked without a browser. Skipped where node is not available.
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


def test_labels_of_parallel_edges_never_coincide_or_cover_a_node() -> None:
    layout = _layout(GRAPH)
    nodes, labels = _boxes(layout)

    assert len(labels) == len(GRAPH["edges"])
    for i, label in enumerate(labels):
        assert not any(_overlap(label, node) for node in nodes), label
        assert not any(_overlap(label, other) for other in labels[i + 1:]), label
    centres = {(round(label["cx"]), round(label["cy"])) for label in labels}
    assert len(centres) == len(labels)


def test_parallel_edges_run_apart_and_a_label_sits_beside_its_line() -> None:
    layout = _layout(GRAPH)
    between = [edge for edge in layout["edges"] if {edge["from"], edge["to"]} == {"a", "b"}]

    middles = {(round(edge["mid"]["x"]), round(edge["mid"]["y"])) for edge in between}
    assert len(middles) == 3
    for edge in layout["edges"]:
        label, mid = edge["label"], edge["mid"]
        inside = label["x"] <= mid["x"] <= label["x"] + label["w"] and \
            label["y"] <= mid["y"] <= label["y"] + label["h"]
        assert not inside, edge


def test_a_small_graph_is_drawn_at_a_small_natural_size() -> None:
    layout = _layout({"nodes": GRAPH["nodes"], "edges": GRAPH["edges"][:4]})

    assert layout["width"] <= 760 and layout["height"] <= 420, layout["viewBox"]
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
