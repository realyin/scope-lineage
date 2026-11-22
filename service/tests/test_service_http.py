"""The HTTP server: every answer is the bytes ``scope-lineage catalog ... --json`` prints.

Each test starts the server on an ephemeral port of 127.0.0.1 and talks to it with
``http.client``; nothing leaves the machine.
"""

from __future__ import annotations

import http.client
import json
import threading
from urllib.parse import urlencode

import pytest
from service_paths import CUSTOMER, LOAN

from scope_lineage.cli import main
from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState


@pytest.fixture
def server(inputs):
    state = CatalogState(
        str(inputs["ontology"]), semantics=str(inputs["semantics"]), pending=str(inputs["pending"])
    )
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True, max_body=4096)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def bare_server(inputs):
    """Started with the ontology alone: no semantics, no pending file."""
    httpd = make_server(CatalogState(str(inputs["ontology"])), port=0, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _request(httpd, method, path, body=None, headers=None):
    host, port = httpd.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _get(httpd, path, **params):
    query = urlencode(params, doseq=True)
    return _request(httpd, "GET", f"{path}?{query}" if query else path)


def _cli(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out.encode("utf-8")


# ------------------------------------------------------------------ acceptance


def test_search_is_the_cli_json(server, inputs, capsys) -> None:
    code, out = _cli(
        capsys, "catalog", "search", str(inputs["ontology"]), "客户", "--semantics",
        str(inputs["semantics"]), "--kind", "concept", "--kind", "table", "--limit", "4", "--json",
    )
    status, headers, body = _get(
        server, "/api/search", text="客户", kind=["concept", "table"], limit=4
    )

    assert (status, body) == (200, out)
    assert headers["X-Scope-Lineage-Exit-Code"] == str(code) == "0"
    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_nothing_found_is_404_with_the_cli_json(server, inputs, capsys) -> None:
    code, out = _cli(capsys, "catalog", "query", str(inputs["ontology"]), "table", "x.none", "--json")
    status, headers, body = _get(server, "/api/query", kind="table", term="x.none")

    assert (status, body) == (404, out)
    assert headers["X-Scope-Lineage-Exit-Code"] == str(code) == "1"


def test_query_is_the_cli_json(server, inputs, capsys) -> None:
    _, out = _cli(capsys, "catalog", "query", str(inputs["ontology"]), "table", LOAN, "--json")

    assert _get(server, "/api/query", kind="table", term=LOAN)[2] == out


def test_context_is_the_cli_json(server, inputs, capsys) -> None:
    _, out = _cli(
        capsys, "catalog", "context", str(inputs["ontology"]), "--semantics",
        str(inputs["semantics"]), "--table", CUSTOMER, "--columns", "gender_cd",
        "--concept", "customer", "--brief", "--focus", "--json",
    )
    status, _, body = _get(
        server, "/api/context", table=CUSTOMER, columns="gender_cd", concept="customer",
        brief="true", focus="1",
    )

    assert (status, body) == (200, out)


def test_context_with_a_column_is_the_cli_json(server, inputs, capsys) -> None:
    _, out = _cli(
        capsys, "catalog", "context", str(inputs["ontology"]), "--semantics",
        str(inputs["semantics"]), "--column", f"{CUSTOMER}.gender_cd", "--json",
    )

    assert _get(server, "/api/context", column=f"{CUSTOMER}.gender_cd")[2] == out


def test_check_sql_is_the_cli_json(server, inputs, capsys, tmp_path) -> None:
    sql = f"SELECT c.gender_cd, count(*) FROM {CUSTOMER} c JOIN x.unknown u ON c.id = u.id"
    path = tmp_path / "q.sql"
    path.write_text(sql, encoding="utf-8")
    code, out = _cli(capsys, "catalog", "check-sql", str(inputs["ontology"]), str(path), "--json")
    status, headers, body = _request(
        server, "POST", "/api/check-sql", body=sql.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )

    assert (status, body) == (200, out)
    assert headers["X-Scope-Lineage-Exit-Code"] == str(code)


def test_check_sql_also_takes_a_json_body(server, inputs, capsys, tmp_path) -> None:
    sql = f"SELECT gender_cd FROM {CUSTOMER}"
    path = tmp_path / "q.sql"
    path.write_text(sql, encoding="utf-8")
    _, out = _cli(capsys, "catalog", "check-sql", str(inputs["ontology"]), str(path), "--json")
    status, _, body = _request(
        server, "POST", "/api/check-sql", body=json.dumps({"sql": sql}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    assert (status, body) == (200, out)


def test_pending_add_then_list_is_the_cli_json(server, inputs, capsys) -> None:
    request = {
        "question": "上月新增客户数", "missing": "注销的客户算不算", "tables": [CUSTOMER],
        "date": "2026-01-02",
    }
    status, _, body = _request(
        server, "POST", "/api/pending", body=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert status == 201
    written = [json.loads(line) for line in inputs["pending"].read_text("utf-8").splitlines()]
    assert json.loads(body) == {"appended": 1, "lines": written}

    code, out = _cli(
        capsys, "catalog", "pending", "list", str(inputs["pending"]), "--ontology",
        str(inputs["ontology"]), "--semantics", str(inputs["semantics"]), "--json",
    )
    status, headers, body = _get(server, "/api/pending")
    assert (status, body) == (200, out)
    assert headers["X-Scope-Lineage-Exit-Code"] == str(code) == "0"


def test_text_rendering_on_request(server, inputs, capsys) -> None:
    main(["catalog", "search", str(inputs["ontology"]), "客户", "--semantics", str(inputs["semantics"])])
    out = capsys.readouterr().out
    status, headers, body = _get(server, "/api/search", text="客户", format="text")

    assert (status, body.decode("utf-8")) == (200, out)
    assert headers["Content-Type"] == "text/plain; charset=utf-8"


# ------------------------------------------------------------------ discovery


def test_health(server) -> None:
    status, _, body = _get(server, "/health")
    health = json.loads(body)

    assert status == 200
    assert health["status"] == "ok" and health["read_only"] is True


def test_endpoint_list_is_machine_readable(server, bare_server) -> None:
    listing = json.loads(_get(server, "/api")[2])
    paths = {(item["method"], item["path"]) for item in listing["endpoints"]}

    assert {
        ("GET", "/health"), ("GET", "/api"), ("GET", "/api/search"), ("GET", "/api/context"),
        ("GET", "/api/query"), ("POST", "/api/check-sql"), ("GET", "/api/pending"),
        ("POST", "/api/pending"),
    } <= paths
    assert all("description" in item and "params" in item for item in listing["endpoints"])
    bare = {(item["method"], item["path"]) for item in json.loads(_get(bare_server, "/api")[2])["endpoints"]}
    assert ("GET", "/api/pending") not in bare and ("POST", "/api/pending") not in bare


# ------------------------------------------------------------------ refusals


def _error(body: bytes) -> dict:
    return json.loads(body)["error"]


def test_bad_options_are_400_with_the_cli_sentence(server, inputs, capsys) -> None:
    code = main(["catalog", "context", str(inputs["ontology"]), "--columns", "a"])
    err = capsys.readouterr().err
    status, headers, body = _get(server, "/api/context", columns="a")

    assert status == 400
    assert _error(body) == {"kind": "bad_input", "exit_code": code, "message": err.rstrip("\n")}
    assert headers["X-Scope-Lineage-Exit-Code"] == "2"


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/search", {}),
        ("/api/search", {"text": "x", "limit": "many"}),
        ("/api/search", {"text": "x", "limit": "0"}),
        ("/api/search", {"text": "x", "kind": "nonsense"}),
        ("/api/search", {"text": ["x", "y"]}),
        ("/api/search", {"text": "x", "unknown": "1"}),
        ("/api/query", {"kind": "nonsense", "term": "x"}),
        ("/api/context", {"table": CUSTOMER, "brief": "maybe"}),
        ("/api/search", {"text": "x", "format": "xml"}),
    ],
)
def test_malformed_requests_are_400(server, path, params) -> None:
    status, _, body = _get(server, path, **params)

    assert status == 400
    assert _error(body)["kind"] == "bad_input"


def test_sql_that_does_not_parse_is_400(server) -> None:
    status, _, body = _request(
        server, "POST", "/api/check-sql", body=b"SELECT FROM (", headers={"Content-Type": "text/plain"}
    )
    assert status == 400 and _error(body)["exit_code"] == 2


def test_a_body_over_the_limit_is_413_and_not_read(server) -> None:
    status, _, body = _request(
        server, "POST", "/api/check-sql", body=b"x" * 5000, headers={"Content-Type": "text/plain"}
    )
    assert status == 413 and _error(body)["kind"] == "too_large"


def test_pending_add_needs_a_json_body(server, inputs) -> None:
    status, _, _ = _request(
        server, "POST", "/api/pending", body=b"question=x", headers={"Content-Type": "text/plain"}
    )
    assert status == 415
    assert not inputs["pending"].exists()


def test_pending_add_refused_writes_nothing(server, inputs) -> None:
    request = {"question": "q", "sql": "SELECT 1"}
    status, _, body = _request(
        server, "POST", "/api/pending", body=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert status == 422 and _error(body)["exit_code"] == 1
    assert not inputs["pending"].exists()


def test_pending_add_rejects_fields_it_does_not_know(server, inputs) -> None:
    request = {"question": "q", "missing": "m", "path": "/elsewhere"}
    status, _, _ = _request(
        server, "POST", "/api/pending", body=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
    assert not inputs["pending"].exists()


def test_pending_without_a_pending_file_is_404(bare_server) -> None:
    status, _, body = _get(bare_server, "/api/pending")
    assert status == 404 and _error(body)["kind"] == "not_configured"


def test_an_unknown_path_is_404_and_a_wrong_method_405(server) -> None:
    assert _get(server, "/api/../../etc/passwd")[0] == 404
    status, headers, _ = _request(server, "POST", "/api/search", body=b"", headers={"Content-Length": "0"})
    assert status == 405 and headers["Allow"] == "GET"


def test_a_foreign_host_or_origin_is_refused(server) -> None:
    assert _request(server, "GET", "/health", headers={"Host": "evil.example"})[0] == 403
    status, _, _ = _request(server, "GET", "/health", headers={"Origin": "http://evil.example"})
    assert status == 403


def test_an_ontology_broken_after_start_is_503_until_fixed(server, inputs) -> None:
    import os

    good = inputs["ontology"].read_text("utf-8")
    inputs["ontology"].write_text("{half", encoding="utf-8")
    stat = inputs["ontology"].stat()
    os.utime(inputs["ontology"], ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))

    status, _, body = _get(server, "/api/query", kind="table", term=LOAN)
    assert status == 503 and _error(body)["kind"] == "input_unavailable"
    assert json.loads(_get(server, "/health")[2])["status"] == "unavailable"

    inputs["ontology"].write_text(good, encoding="utf-8")
    os.utime(inputs["ontology"], ns=(stat.st_atime_ns, stat.st_mtime_ns + 20_000_000_000))
    assert _get(server, "/api/query", kind="table", term=LOAN)[0] == 200
