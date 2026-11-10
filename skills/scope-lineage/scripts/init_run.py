#!/usr/bin/env python3
"""Write a run's ``env.sh``: ``init_run.py --run DIR --scratch DIR --tasks DIR --schema PATH``.

``env.sh`` holds the run's paths and ends by sourcing ``runlib.sh`` (``sl``, ``fill``,
``note``, ``load_tables``). Every Bash call of the run starts with ``. <run>/env.sh``.
The skill directory is the one this script lives in; the tool checkout is its repository
when there is one, otherwise empty (the installed ``scope-lineage`` is used). An existing
``env.sh`` is never overwritten: edit its right-hand sides, or pass ``--force``.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def _tool() -> str:
    root = os.path.dirname(os.path.dirname(SKILL))
    inside = os.path.basename(os.path.dirname(SKILL)) == "skills" and os.path.isfile(os.path.join(root, "pyproject.toml"))
    return root if inside else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, help="运行目录（新建，不复用旧的）")
    parser.add_argument("--scratch", required=True, help="临时目录，不放在运行目录里面")
    parser.add_argument("--tasks", required=True, help="任务 JSON 目录")
    parser.add_argument("--schema", required=True, help="表元数据：rich-JSON 目录或文件")
    parser.add_argument("--ddl", default="", help="目标表 DDL 元数据；和 --schema 是同一目录就写同一个值")
    parser.add_argument("--patch", default="", help="owner 审过的 metadata-patch.json")
    parser.add_argument("--overrides", default="", help="owner 审过的 glossary.overrides.json")
    parser.add_argument("--questions", default="", help="回归题集（question-set/1）")
    parser.add_argument("--tool", default=None, help="工具仓库根目录；不写时自动判断，pip 安装时为空")
    parser.add_argument("--force", action="store_true", help="覆盖已有的 env.sh")
    args = parser.parse_args()

    run, scratch = os.path.abspath(args.run), os.path.abspath(args.scratch)
    if os.path.commonpath([run, scratch]) == run:
        print(f"SCRATCH 不能放在运行目录里面：{scratch}", file=sys.stderr)
        return 1
    target = os.path.join(run, "env.sh")
    if os.path.exists(target) and not args.force:
        print(f"{target} 已经存在，没有改它。要换路径就直接改它等号右边；确实要重写加 --force", file=sys.stderr)
        return 1

    def absolute(path: str) -> str:
        return os.path.abspath(path) if path else ""

    values = [
        ("TOOL", absolute(args.tool) if args.tool is not None else _tool(), "工具仓库根目录；pip 安装、没有仓库就是空的"),
        ("SKILL", SKILL, "skill 目录（有 SKILL.md、references/、scripts/）"),
        ("TASKS", absolute(args.tasks), "任务 JSON 目录（parse --input-dir）"),
        ("SCHEMA", absolute(args.schema), "表元数据（parse --schema）"),
        ("DDL", absolute(args.ddl), "目标表 DDL 元数据；没有就是空的"),
        ("PATCH", absolute(args.patch), "owner 审过的 metadata-patch.json；没有就是空的"),
        ("OVERRIDES", absolute(args.overrides), "owner 审过的 glossary.overrides.json；没有就是空的"),
        ("RUN", run, "运行目录"),
        ("SCRATCH", scratch, "临时目录"),
        ("Q", absolute(args.questions), "回归题集；没有就是空的"),
    ]
    lines = ["# ===== scope-lineage 运行环境（init_run.py 生成）：要改只改等号右边，全部写绝对路径，一律用正斜杠 ====="]
    lines += [f"export {name}={shlex.quote(value)}   # {comment}" for name, value, comment in values]
    lines += [
        'export PAGES="$RUN/site"                 # 页面根目录（概念页、index.md）',
        'export SEMPAGES="$RUN/site/semantics"    # 表语义页目录',
        "# Windows 上 python3 指向应用商店占位程序（退出码 49、「Python was not found」）时，取消下一行注释：",
        '# python3() { python "$@"; }',
        '. "$SKILL/scripts/runlib.sh"             # sl、fill、note、load_tables',
    ]
    os.makedirs(run, exist_ok=True)
    os.makedirs(scratch, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"写好了 {target}。每次 Bash 调用的第一条命令：. {shlex.quote(target)}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
