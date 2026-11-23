"""The browse page: its static files and the endpoints it calls.

The page is a fixed set of packaged files served at fixed paths; the browse endpoints
answer what ``scope_lineage.cli_catalog_answers`` answers, a page at a time. Each test
starts the server on an ephemeral port of 127.0.0.1; nothing leaves the machine.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
from importlib import resources
from urllib.parse import urlencode

import pytest
from service_paths import CUSTOMER, LOAN
from synthetic import synthetic_catalog, synthetic_semantics

from scope_lineage import cli_catalog_answers as answers
from scope_lineage_service.http_server import STATIC_FILES, make_server
from scope_lineage_service.state import CatalogState


def _start(state: CatalogState):
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    return httpd


@pytest.fixture
def server(inputs):
    state = CatalogState(
        str(inputs["ontology"]), semantics=str(inputs["semantics"]), pending=str(inputs["pending"])
    )
    httpd = _start(state)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def bare_server(inputs):
    httpd = _start(CatalogState(str(inputs["ontology"])))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _request(httpd, method, path, body=None, headers=None):
    host, port = httpd.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=30)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _get(httpd, endpoint, **params):
    query = urlencode(params, doseq=True)
    return _request(httpd, "GET", f"{endpoint}?{query}" if query else endpoint)


def _json(httpd, endpoint, **params):
    status, _, body = _get(httpd, endpoint, **params)
    return status, json.loads(body)


def _static_dir():
    return resources.files("scope_lineage_service") / "static"


# ------------------------------------------------------------------ static files


def test_the_page_is_served_at_the_root_with_a_strict_policy(server) -> None:
    status, headers, body = _get(server, "/")

    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    policy = headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "script-src 'self'" in policy and "'unsafe-inline'" not in policy
    assert "frame-ancestors 'none'" in policy
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert b'src="app.js"' in body


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/app.css", "text/css; charset=utf-8"),
        ("/app.js", "text/javascript; charset=utf-8"),
        ("/dom.js", "text/javascript; charset=utf-8"),
        ("/graph.js", "text/javascript; charset=utf-8"),
        ("/views.js", "text/javascript; charset=utf-8"),
        ("/ask.js", "text/javascript; charset=utf-8"),
        ("/askview.js", "text/javascript; charset=utf-8"),
    ],
)
def test_each_static_file_has_its_content_type(server, path, content_type) -> None:
    status, headers, body = _get(server, path)

    assert status == 200 and headers["Content-Type"] == content_type
    assert body == (_static_dir() / path.lstrip("/")).read_bytes()
    assert "Content-Security-Policy" in headers


def test_the_served_set_is_exactly_the_packaged_files() -> None:
    packaged = {item.name for item in _static_dir().iterdir() if item.is_file()}
    assert {name for name, _ in STATIC_FILES.values()} == packaged


@pytest.mark.parametrize(
    "path",
    [
        "/index.html", "/static/app.js", "/../app.js", "/%2e%2e/app.js", "/app.js/",
        "/APP.JS", "/app.js%00", "/favicon.ico", "/state.py", "/__init__.py",
        "/static/../http_server.py",
    ],
)
def test_anything_else_is_404(server, path) -> None:
    status, headers, body = _request(server, "GET", path)

    assert status == 404
    assert json.loads(body)["error"]["kind"] == "not_found"


def test_a_static_file_takes_no_parameters(server) -> None:
    assert _get(server, "/app.js", v="1")[0] == 400
    assert _request(server, "POST", "/", body=b"", headers={"Content-Length": "0"})[0] == 405


def test_the_page_is_refused_to_a_foreign_host(server) -> None:
    status, _, _ = _request(server, "GET", "/", headers={"Host": "evil.example"})
    assert status == 403


def test_the_page_runs_no_inline_code_and_writes_no_markup_from_data() -> None:
    html = (_static_dir() / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline script"
    assert not re.search(r"\son\w+\s*=", html), "inline event handler"
    assert not re.search(r"\sstyle\s*=", html) and "<style" not in html
    assert not re.search(r"https?://", html), "the page loads nothing from elsewhere"
    for name, _ in STATIC_FILES.values():
        if name.endswith(".js"):
            code = (_static_dir() / name).read_text(encoding="utf-8")
            # the SVG namespace is a name, not a place anything is loaded from
            code = code.replace('"http://www.w3.org/2000/svg"', "SVG_NAMESPACE")
            for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                           "eval(", "new Function", "setAttribute(\"style\"", "http://",
                           "https://"):
                assert unsafe not in code, f"{name} uses {unsafe}"


# ------------------------------------------------------------------ endpoints


def test_the_endpoint_list_names_the_browse_endpoints(server) -> None:
    listing = json.loads(_get(server, "/api")[2])
    paths = {(item["method"], item["path"]) for item in listing["endpoints"]}
    for path in ("/api/browse", "/api/list", "/api/neighbourhood", "/api/semantics",
                 "/api/questions"):
        assert ("GET", path) in paths


def test_browse_is_the_core_answer(server, inputs) -> None:
    document = answers.load_ontology(str(inputs["ontology"]))
    status, headers, body = _get(server, "/api/browse")

    assert status == 200
    assert body == (answers.browse_index(document).json_text() + "\n").encode("utf-8")
    assert headers["X-Scope-Lineage-Exit-Code"] == "0"


def test_list_pages_tables(server, inputs) -> None:
    status, first = _json(server, "/api/list", kind="tables", limit=3)
    _, second = _json(server, "/api/list", kind="tables", limit=3, offset=3)

    assert status == 200
    assert first["total"] == second["total"] == 9
    assert len(first["items"]) == 3
    assert not {i["table"] for i in first["items"]} & {i["table"] for i in second["items"]}


def test_list_filters(server) -> None:
    _, of_customer = _json(server, "/api/list", kind="tables", concept="concept:customer")
    _, party = _json(server, "/api/list", kind="concepts", domain="domain:party")
    _, texted = _json(server, "/api/list", kind="tables", text="loan")

    assert CUSTOMER in [item["table"] for item in of_customer["items"]]
    assert {item["domain"]["id"] for item in party["items"]} == {"domain:party"}
    assert all("loan" in item["table"] for item in texted["items"])


def test_an_empty_page_is_still_200(server) -> None:
    status, page = _json(server, "/api/list", kind="tables", text="no-such-table")
    assert status == 200 and page["items"] == [] and page["total"] == 0


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/list", {}),
        ("/api/list", {"kind": "rows"}),
        ("/api/list", {"kind": "tables", "limit": "0"}),
        ("/api/list", {"kind": "tables", "limit": "201"}),
        ("/api/list", {"kind": "tables", "offset": "-1"}),
        ("/api/list", {"kind": "tables", "offset": "x"}),
        ("/api/list", {"kind": "tables", "sort": "name"}),
        ("/api/list", {"kind": "tables", "format": "text"}),
        ("/api/list", {"kind": ["tables", "concepts"]}),
        ("/api/neighbourhood", {}),
        ("/api/neighbourhood", {"concept": "concept:loan", "limit": "0"}),
        ("/api/semantics", {}),
        ("/api/semantics", {"table": CUSTOMER, "path": "/etc/passwd"}),
        ("/api/questions", {"status": "closed"}),
        ("/api/questions", {"source": "mail"}),
        ("/api/questions", {"limit": "1000"}),
        ("/api/browse", {"x": "1"}),
    ],
)
def test_bad_browse_requests_are_400(server, path, params) -> None:
    status, body = _json(server, path, **params)
    assert status == 400 and body["error"]["kind"] == "bad_input"


def test_the_neighbourhood_of_a_concept(server) -> None:
    status, graph = _json(server, "/api/neighbourhood", concept="借据", limit=3)

    assert status == 200
    assert graph["centre"] == "concept:loan"
    assert len(graph["nodes"]) == 4 and graph["truncated"] > 0


def test_no_concept_no_neighbourhood_is_404(server) -> None:
    status, graph = _json(server, "/api/neighbourhood", concept="nothing")
    assert status == 404 and graph["centre"] is None


def test_semantics_of_a_table(server, inputs) -> None:
    status, answer = _json(server, "/api/semantics", table=CUSTOMER)
    assert status == 200 and answer["document"]["table"] == CUSTOMER

    status, answer = _json(server, "/api/semantics", table=LOAN)
    assert status == 404 and answer["document"] is None and answer["in_catalog"] is True


def test_the_questions_board_takes_the_pending_file(server) -> None:
    status, board = _json(server, "/api/questions")
    assert status == 200
    assert board["checked"] == {"semantics": True, "pending": True}
    assert [item["source"] for item in board["items"]] == ["semantics"]

    request = {"question": "一个问题", "missing": "从没定义过的口径", "tables": [LOAN]}
    _request(server, "POST", "/api/pending", body=json.dumps(request).encode("utf-8"),
             headers={"Content-Type": "application/json"})
    _, board = _json(server, "/api/questions", table=LOAN)

    (item,) = board["items"]
    assert item["source"] == "pending" and item["in_catalog"] is False
    assert item["concepts"][0]["id"] == "concept:loan"


def test_the_board_without_a_pending_file(bare_server) -> None:
    status, board = _json(bare_server, "/api/questions")
    assert status == 200
    assert board["checked"] == {"semantics": False, "pending": False}
    assert board["items"] == []


def test_the_browse_endpoints_write_nothing(server, inputs) -> None:
    before = {p: p.read_bytes() for p in inputs["semantics"].rglob("*.json")}
    ontology = inputs["ontology"].read_bytes()
    for path, params in (
        ("/", {}), ("/api/browse", {}), ("/api/list", {"kind": "tables"}),
        ("/api/neighbourhood", {"concept": "concept:loan"}),
        ("/api/semantics", {"table": CUSTOMER}), ("/api/questions", {"status": "all"}),
    ):
        _get(server, path, **params)
    assert not inputs["pending"].exists()
    assert inputs["ontology"].read_bytes() == ontology
    assert {p: p.read_bytes() for p in inputs["semantics"].rglob("*.json")} == before


# ------------------------------------------------------------------ scale


@pytest.fixture
def large_server(tmp_path):
    tables = 3000
    ontology = tmp_path / "ontology.json"
    ontology.write_text(json.dumps(synthetic_catalog(tables), ensure_ascii=False), encoding="utf-8")
    semantics = tmp_path / "semantics"
    synthetic_semantics(tables, semantics)
    httpd = _start(CatalogState(str(ontology), semantics=str(semantics)))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_a_large_catalog_is_answered_a_page_at_a_time(large_server) -> None:
    sizes = {}
    for name, path, params in (
        ("index", "/api/browse", {}),
        ("domain", "/api/list", {"kind": "concepts", "domain": "domain:d01"}),
        ("tables", "/api/list", {"kind": "tables", "concept": "concept:c0001"}),
        ("all_tables", "/api/list", {"kind": "tables"}),
        ("graph", "/api/neighbourhood", {"concept": "concept:c0001"}),
        ("board", "/api/questions", {}),
    ):
        status, _, body = _get(large_server, path, **params)
        assert status == 200, name
        sizes[name] = len(body)

    _, page = _json(large_server, "/api/list", kind="tables")
    assert page["total"] == 3000 and len(page["items"]) == 50
    _, board = _json(large_server, "/api/questions")
    assert board["total"] == 1000 and len(board["items"]) == 50
    assert all(size < 64_000 for size in sizes.values()), sizes
