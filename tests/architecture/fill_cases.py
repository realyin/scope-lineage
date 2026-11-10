"""Every template and mode ``fill`` can produce, rendered with fixed stand-in paths.

``render_all(fill)`` runs one ``fill`` call per case in its own run directory and returns
``{case: prompt text}`` with the machine's paths replaced by ``/RUN``, ``/SCRATCH`` and
``/SKILL``. The golden copies under ``fixtures/fill_golden/`` were written by the ``fill``
function that used to live inside ``env.sh`` (0.11.2), so a change to where ``fill`` or the
templates live cannot change what a subagent is told without a test saying so.
"""

from __future__ import annotations

from pathlib import Path

T = "demo_x.t"
WRITE = ("FACTS=无", "CONCEPT=不写 concept")

# case -> (template, files that must exist under the run directory, arguments)
CASES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "T1-new": ("T1", (), (f"TABLE={T}", "MODE=新写", "CORRECTIONS=无", "FAILURES=无", *WRITE)),
    "T1-rewrite": ("T1", (f"reviews/{T}.prior.md", "corrections.txt"),
                   (f"TABLE={T}", "MODE=新写", "CORRECTIONS=@{RUN}/corrections.txt", "FAILURES=无", *WRITE)),
    "T1-failures": ("T1", (f"docs/{T}.json", "failures.txt"),
                    (f"TABLE={T}", "MODE=补失败", "CORRECTIONS=无", "FAILURES=@{RUN}/failures.txt", *WRITE)),
    "T2-first": ("T2", (f"docs/{T}.json",), (f"TABLE={T}", "MODE=首审", "FACTS=无")),
    "T2-after-rewrite": ("T2", (f"docs/{T}.json", f"reviews/{T}.prior.md", f"reviews/{T}.prior.json"),
                         (f"TABLE={T}", "MODE=重写后首审", "FACTS=一条已确认的事实")),
    "T3": ("T3", (f"reviews_prev/{T}.round1.md",), (f"TABLE={T}", "FACTS=无")),
    "T4-first": ("T4", (f"reviews/{T}.md",), (f"TABLE={T}", "MODE=首修", "FACTS=无")),
    "T4-check": ("T4", (f"reviews/{T}.md",), (f"TABLE={T}", "MODE=核对", "FACTS=无")),
    "T5-new": ("T5", ("digest/digest.md",),
               ("MODE=新建", "SIZE=小样：只分 1 组，组名 main", "TOUCHED=无", "REWORK=无", "DECISIONS=无")),
    "T5-incremental": ("T5", ("digest/digest.md", "catalog_touched.txt", "owner_decisions.md"),
                       ("MODE=增量", "SIZE=扩表：按概念分组", "TOUCHED=@{RUN}/catalog_touched.txt", "REWORK=无",
                        "DECISIONS=@{RUN}/owner_decisions.md")),
    "T6-first": ("T6", ("catalog_plan.md",), ("GROUP=main", "MODE=首写", "REWORK=无")),
    "T6-rework": ("T6", ("catalog_plan.md",), ("GROUP=main", "MODE=返工", "REWORK=一行报错原文")),
    "T7": ("T7", ("round1/sheet.md",), ("ROUND={RUN}/round1",)),
    "T8": ("T8", ("round1/grading.md",), ("ROUND={RUN}/round1", "ROUND_LABEL=r1")),
}


def render_all(fill, tmp_path: Path, skill: Path) -> dict[str, str]:
    """``fill(run, scratch, *args)`` must return a completed process with ``returncode``."""
    rendered = {}
    for case, (template, files, arguments) in CASES.items():
        run, scratch = tmp_path / case / "run", tmp_path / case / "scratch"
        for name in ("docs", "reviews", "reviews_prev", "round1", "digest"):
            (run / name).mkdir(parents=True)
        for name in files:
            (run / name).write_text(f"内容：{name}\n", encoding="utf-8")
        out = tmp_path / case / "prompt.md"
        done = fill(run, scratch, template, str(out), *(a.replace("{RUN}", str(run)) for a in arguments))
        assert done.returncode == 0, f"{case}: {done.stderr}"
        text = out.read_text(encoding="utf-8")
        for path, name in ((scratch, "/SCRATCH"), (run, "/RUN"), (skill, "/SKILL")):
            text = text.replace(str(path), name)
        rendered[case] = text
    return rendered
