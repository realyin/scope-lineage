"""The corrections list a rewrite hands its writer (runbook S4, template T1 ``{CORRECTIONS}``).

``skills/scope-lineage/scripts/make_corrections.py`` reads the old review, the fix log and
the rebuilt packet, and sorts every finding into A 段 (fixed last time: follow it), B 段
(worth a look: check it first) or out. The tests run it as the runbook does -- a
subprocess over files -- and pin what a wrong list would cost: a fixed finding falling to
B 段 or out, a stale finding slipping in, a finding the script could not read vanishing
without a word, and a re-reviewed table losing what its first review got fixed.

The rewrite preparation itself (runbook S4) is run from the runbook's own block, so the
names it gives the old files are the names ``semantic status`` is checked against.

Every table, column and value here is made up (``demo_dim.dim_party_group_dc``,
``grp_name``, ``site_id``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "scope-lineage" / "scripts" / "make_corrections.py"
RUNBOOK = REPO / "skills" / "scope-lineage" / "references" / "runbook.md"
TABLE = "demo_dim.dim_party_group_dc"

PACKET = """# 材料包 demo_dim.dim_party_group_dc
| p3 | dedup | stmt:001 | `ROW_NUMBER() OVER (PARTITION BY grp_name, env ORDER BY upd DESC)` |
| p7 | join（LEFT_OUTER） | stmt:001 | `a.site_id = c.id` | unknown：表卡说明 |
| p9 | window | stmt:001 | `LEAD(beg_dt, 1, '99991231') OVER (PARTITION BY grp_name ORDER BY beg_dt)` |
"""

FRONT = "---\nreviewed_doc_digest: {doc}\nreviewed_packet_digest: 2222222222222222\nhigh: {h}\nmedium: {m}\nlow: {l}\n{extra}---\n"

# A rewrite-after review in every heading style the script has to read.
PRIOR = FRONT.format(doc="1111111111111111", h=0, m=2, l=3, extra="fixed_doc_digest: 3333333333333333\n") + """
审读提示词 table-semantics-review@9。

## 旧审读各条的处理结果

| 编号 | 旧编号 | 问题 | 适用 | 新文档 |
| --- | --- | --- | --- | --- |
| o1 | 第 1 轮 H1 | 取数缺前置条件 `PARTITION BY grp_name, env` | 适用 | 已避免：how_to_read 写了 |
| o2 | 第 1 轮 L3 | category 应改 | 不适用：现行提示词第 1 项 | — |
| o3 | 第 1 轮 L1 | 去重键不含 id | 适用 | 又犯了 → L1 |

## 本轮发现

### 中

#### M1.（第 12 项）终止值含义写成当前版本
- 位置：`columns[end_dt].meaning`
- 文档原话：「当前版本」
- 材料包事实：p9 `LEAD(beg_dt, 1, '99991231') OVER (PARTITION BY grp_name ORDER BY beg_dt)`
- 应改成：写成该代码的最后一个版本

#### 中-2（旧写法）右侧判定写成事实
- 位置：`rules[r7]`
- 材料包事实：p7「risk：右侧未被证明按连接键唯一」
- 应改成：按材料包判定写

### 低

### L1.（又犯了）去重键不含 id
- 位置：`summary.scope[1]`
- 材料包事实：p3 `ROW_NUMBER() OVER (PARTITION BY grp_name, env ORDER BY upd DESC)`
- 应改成：补「同名不同 id 只留一条」

#### 低-2 缺小标题的写法
- 位置与原话：见各条
- 应改成：见各条

#### L3. 修订判不成立的那条
- 位置：`x`
- 材料包事实：p3 `PARTITION BY grp_name, env ORDER BY upd DESC`
- 应改成：随便

高 0、中 2、低 3
"""

# The fixer's reply kept as it came (T4): one section per review, every finding on its own
# line, number first. The older section has the same numbers with other verdicts.
FIXLOG = """来源：reviews/demo_dim.dim_party_group_dc.md reviewed_doc_digest=0000000000000000
逐条处理：
M1 不成立：理由
中-2 不成立：理由
来源：reviews/demo_dim.dim_party_group_dc.md reviewed_doc_digest=1111111111111111
逐条处理：
M1 已改：columns[end_dt].meaning
中-2 已改：rules[r7]
未改的低级发现：
L1 未改：低级不修
L3 不成立：材料包里没有这一说
"""


def _packet(tmp_path: Path) -> Path:
    directory = tmp_path / "packets" / TABLE
    directory.mkdir(parents=True)
    (directory / "packet.md").write_text(PACKET, encoding="utf-8")
    (directory / "packet.json").write_text(json.dumps({"packet_digest": "4444444444444444"}), encoding="utf-8")
    return directory


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(tmp_path: Path, prior: str, fixlog: str | None = None, round1: str | None = None):
    args = [sys.executable, str(SCRIPT), str(_write(tmp_path / "prior.md", prior)), str(_packet(tmp_path)),
            "--out", str(tmp_path / "corrections.txt"), "--report", str(tmp_path / "report.json")]
    if fixlog is not None:
        args += ["--fixlog", str(_write(tmp_path / "fixlog.txt", fixlog))]
    if round1 is not None:
        args += ["--round1", str(_write(tmp_path / "round1.md", round1))]
    done = subprocess.run(args, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    text = (tmp_path / "corrections.txt").read_text(encoding="utf-8")
    return {item["id"]: item for item in report}, text, done.stderr


def _section(text: str, name: str) -> str:
    return text.split(f"## {name} 段", 1)[1].split("\n## ", 1)[0]


def test_every_heading_style_and_table_row_lands_where_its_verdict_sends_it(tmp_path):
    items, text, stderr = _run(tmp_path, PRIOR, FIXLOG)
    assert items["M1"]["dest"] == "A"                       # fixed medium: follow it
    assert items["中-2"]["dest"] == "dropped"               # its risk quote is unknown now
    assert items["L1"]["dest"] == "B"                       # low, never fixed: check it first
    assert items["低-2"]["dest"] == "unparsed" and "未解析：低-2" in stderr
    assert items["L3"]["dest"] == "dropped"                 # the fixer said it does not hold
    assert items["o1 第 1 轮 H1"]["dest"] == "B" and items["o1 第 1 轮 H1"]["severity"] == "高"
    assert items["o2 第 1 轮 L3"]["dest"] == "dropped"      # judged 不适用 last time
    assert items["o3 第 1 轮 L1"]["dest"] == "skipped"      # 又犯了: the L1 section covers it
    assert "[M1（中）]" in _section(text, "A") and "L1" not in _section(text, "A")
    assert "[L1（低）]" in _section(text, "B") and "o1 第 1 轮 H1" in _section(text, "B")
    assert "reviewed_doc_digest=1111111111111111" in text and "packet_digest=4444444444444444" in text


def test_the_fix_log_section_of_another_review_is_not_read(tmp_path):
    """Two sections reuse M1; only the one opened by this review's digest counts."""
    items, _, _ = _run(tmp_path, PRIOR, FIXLOG)
    assert items["M1"]["dest"] == "A"
    older_only = FIXLOG.split("来源：reviews/demo_dim.dim_party_group_dc.md reviewed_doc_digest=1111")[0]
    items, _, stderr = _run(tmp_path / "older", PRIOR, older_only)
    assert items["M1"]["dest"] == "B" and items["中-2"]["dest"] == "dropped"
    assert "reviewed_doc_digest=1111111111111111" in stderr      # said, not silently B


def test_a_fix_reply_with_its_first_finding_on_the_heading_line_is_still_read(tmp_path):
    reply = ("来源：reviews/demo_dim.dim_party_group_dc.md reviewed_doc_digest=1111111111111111\n"
             "逐条处理：M1 已改：columns[end_dt].meaning\n- 中-2 已改：rules[r7]\n")
    items, _, _ = _run(tmp_path, PRIOR, reply)
    assert items["M1"]["dest"] == "A"


def test_a_finding_with_nothing_to_look_up_is_marked_unchecked(tmp_path):
    prior = PRIOR.replace("- 材料包事实：p3 `ROW_NUMBER() OVER (PARTITION BY grp_name, env ORDER BY upd DESC)`",
                          "- 材料包事实：p3 的去重只按名称和环境分组", 1)
    items, text, stderr = _run(tmp_path, prior, FIXLOG)
    assert items["L1"]["dest"] == "B" and items["L1"]["checked"] == 0
    assert "[L1（低，未核）]" in _section(text, "B")
    assert "[M1（中）]" in _section(text, "A")                     # quoted and found: no mark
    assert "未核" in text.split("## A 段")[0]                        # the usage says what it means
    assert "未核 1" in stderr or "未核 2" in stderr                 # o1 has a quote; L1 does not


def test_a_no_fan_out_fix_is_tagged_and_left_as_written(tmp_path):
    prior = PRIOR.replace("- 应改成：写成该代码的最后一个版本", "- 应改成：写「按 site_id 关联不放大」")
    _, text, _ = _run(tmp_path, prior, FIXLOG)
    entry = _section(text, "A")
    assert "应改成：写「按 site_id 关联不放大」（句式：" in entry
    assert "不成立时" in entry


def test_a_re_reviewed_table_keeps_the_fixes_of_its_first_review(tmp_path):
    """The re-review lists only what still holds; the first review's fixed findings come
    from the first review itself, matched by its own digest in the fix log."""
    round1 = FRONT.format(doc="5555555555555555", h=1, m=1, l=0, extra="fixed_doc_digest: 6666666666666666\n") + """
## 本轮发现

#### H1.（第 1 项）粒度写成全局唯一
- 位置：`summary.row.text`
- 材料包事实：p3 `ROW_NUMBER() OVER (PARTITION BY grp_name, env ORDER BY upd DESC)`
- 应改成：只在同一环境内唯一

#### M1.（第 13 项）推断写成事实
- 位置：`summary.what`
- 材料包事实：p9 `LEAD(beg_dt, 1, '99991231') OVER (PARTITION BY grp_name ORDER BY beg_dt)`
- 应改成：标推断
"""
    rereview = FRONT.format(doc="7777777777777777", h=0, m=0, l=1, extra="") + """
## 上一轮发现的处理结果

| 编号 | 上一轮编号 | 处理 |
| --- | --- | --- |
| o1 | H1 | 已改 |
| o2 | M1 | 上一轮判错 |

## 本轮发现

#### L1. 措辞
- 位置：`summary.what`
- 材料包事实：p7「unknown：表卡说明」
- 应改成：改措辞
"""
    fixlog = ("来源：reviews/demo_dim.dim_party_group_dc.md reviewed_doc_digest=5555555555555555\n"
              "逐条处理：\nH1 已改：summary.row.text\nM1 不成立：材料包已标推断\n")
    items, text, stderr = _run(tmp_path, rereview, fixlog, round1)
    assert items["首审 H1"]["dest"] == "A" and "[首审 H1（高）]" in _section(text, "A")
    assert items["首审 M1"]["dest"] == "dropped"
    assert items["L1"]["dest"] == "B"
    assert "未解析：" not in stderr                                   # the re-review's table is known
    assert "reviewed_doc_digest=7777777777777777" in stderr          # no fix-log section for it: said


def test_an_older_table_without_o_numbers_is_read_by_its_first_column(tmp_path):
    """review@9 and before put the old number in the first column, with no o column."""
    prior = PRIOR.replace("| 编号 | 旧编号 | 问题 | 适用 | 新文档 |", "| 旧编号 | 问题 | 适用 | 新文档 |")
    prior = prior.replace("| --- | --- | --- | --- | --- |", "| --- | --- | --- | --- |")
    for number in ("o1", "o2", "o3"):
        prior = prior.replace(f"| {number} | ", "| ", 1)
    items, _, stderr = _run(tmp_path, prior, FIXLOG)
    assert items["第 1 轮 H1"]["dest"] == "B" and items["第 1 轮 H1"]["severity"] == "高"
    assert items["第 1 轮 L3"]["dest"] == "dropped" and items["第 1 轮 L1"]["dest"] == "skipped"
    assert "未解析：旧审读" not in stderr


def test_a_table_under_an_unknown_heading_is_reported_not_skipped(tmp_path):
    prior = PRIOR.replace("## 旧审读各条的处理结果", "## 其他")
    items, _, stderr = _run(tmp_path, prior, FIXLOG)
    assert "未解析：旧审读处理表格的 o1、o2、o3" in stderr
    assert not any(key.startswith("o") for key in items)


def test_a_missing_input_exits_1(tmp_path):
    done = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "no.md"), str(tmp_path)],
                          capture_output=True, text=True)
    assert done.returncode == 1 and "no.md" in done.stderr


# ---- the rewrite preparation of runbook S4 -------------------------------------------

def _prep_block() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    found = re.search(r"```bash\n(# 重写准备.*?)```", text, re.S)
    assert found, "runbook S4 has no block starting with '# 重写准备'"
    return found.group(1)


def _status_tables(run: Path) -> list[str]:
    from scope_lineage.cli import main

    out = run.parent / "status.json"
    assert main(["semantic", "status", str(run), "--json", str(out)]) in (0, 1)
    return sorted(table["table"] for table in json.loads(out.read_text(encoding="utf-8"))["tables"])


def _one_round(run: Path, label: str) -> None:
    _write(run / "docs" / f"{TABLE}.json", json.dumps({"table": TABLE, "round": label}))
    _write(run / "reviews" / f"{TABLE}.md", FRONT.format(doc="1111111111111111", h=1, m=0, l=0, extra=""))
    _write(run / "reviews" / f"{TABLE}.fixlog.txt", f"来源：{label}\n")
    _write(run / "reviews_prev" / f"{TABLE}.round1.md", f"round1 {label}\n")


@pytest.mark.parametrize("shell", [
    pytest.param(shell, marks=pytest.mark.skipif(shutil.which(shell) is None, reason=f"{shell} is not installed"))
    for shell in ("bash", "zsh")
])
def test_two_rewrite_preparations_keep_every_old_file_and_add_no_table(tmp_path, shell):
    run = tmp_path / "run"
    for name in ("packets", "docs", "reviews", "reviews_prev", "prev/docs"):
        (run / name).mkdir(parents=True)
    script = tmp_path / "prep.sh"
    script.write_text('sl() { "$PY" -c \'import sys; from scope_lineage.cli import main; sys.exit(main(sys.argv[1:]))\' "$@"; }\n'
                      f"T={TABLE}\n" + _prep_block().replace("T=demo_dwd.dwd_party_customer_info_df", "", 1),
                      encoding="utf-8")
    env = dict(os.environ, RUN=str(run), SCRATCH=str(tmp_path / "scratch"), TOOL=str(REPO),
               SEMPAGES=str(run / "site/semantics"), PY=sys.executable)
    for label in ("first", "second"):
        _one_round(run, label)
        assert _status_tables(run) == [TABLE]
        done = subprocess.run([shell, str(script)], env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        assert _status_tables(run) == []                      # the document moved out; no stray table
    reviews = sorted(path.name for path in (run / "reviews").iterdir())
    assert reviews == [f"{TABLE}.prior.fixlog.txt", f"{TABLE}.prior.json", f"{TABLE}.prior.md"]
    archived = sorted(path.name for path in (run / "reviews_prev").iterdir())
    assert len(archived) == 5, archived                       # the first round's four, and round1
    stamps = {re.match(rf"{re.escape(TABLE)}\.prior-(\d{{8}}T\d{{6}})\.", name).group(1)
              for name in archived if ".prior-" in name}
    assert len(stamps) == 1
    for suffix in ("md", "json", "fixlog.txt", "round1.md"):
        assert f"{TABLE}.prior-{next(iter(stamps))}.{suffix}" in archived
    assert f"{TABLE}.prior.round1.md" in archived
    assert json.loads((run / "reviews" / f"{TABLE}.prior.json").read_text())["round"] == "second"


def test_an_old_file_named_into_reviews_would_be_read_as_a_table(tmp_path):
    """Why the rewrite preparation keeps the first review in ``reviews_prev/``: under
    ``reviews/`` only a name ending in ``.prior.md`` is skipped by ``semantic status``."""
    run = tmp_path / "run"
    (run / "packets").mkdir(parents=True)
    _write(run / "reviews" / f"{TABLE}.prior.round1.md", FRONT.format(doc="1111111111111111", h=0, m=0, l=0, extra=""))
    assert _status_tables(run) == ["prior.round1"]
