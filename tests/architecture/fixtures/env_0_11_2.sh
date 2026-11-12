# ===== scope-lineage 运行环境：只改等号右边，全部写绝对路径，一律用正斜杠（Git Bash 会吞掉反斜杠） =====
export TOOL=/abs/path/to/scope-lineage        # 工具仓库根目录（里面有 skills/ docs/ examples/ pyproject.toml）；pip 安装、没有仓库就留空
export SKILL="${TOOL:+$TOOL/skills/scope-lineage}"   # skill 目录（有 SKILL.md、references/、scripts/）；TOOL 留空时写它的绝对路径
export TASKS=/abs/path/to/tasks               # 任务 JSON 目录（parse --input-dir）
export SCHEMA=/abs/path/to/schema             # 表元数据：rich-JSON 目录或文件（parse --schema）
export DDL=                                   # 目标表 DDL 元数据；和 SCHEMA 是同一目录就写同一个值；没有就留空
export PATCH=                                 # owner 审过的 metadata-patch.json；没有就留空
export OVERRIDES=                             # owner 审过的 glossary.overrides.json；没有就留空
export RUN=/abs/path/to/runs/run-20260101     # 运行目录（新建，不要复用别的运行目录）
export SCRATCH=/abs/path/to/scratchpad/run-20260101   # 临时目录，不放在 RUN 里面
export Q=                                     # 回归题集（question-set/1）；没有就留空
export PAGES="$RUN/site"                      # 页面根目录（概念页、index.md）
export SEMPAGES="$RUN/site/semantics"         # 表语义页目录
sl() { if [ -n "$TOOL" ]; then uv run --project "$TOOL" --extra catalog scope-lineage "$@"; else scope-lineage "$@"; fi; }
# Windows 上 python3 指向应用商店占位程序（退出码 49、「Python was not found」）时，取消下一行注释：
# python3() { python "$@"; }
export SCHEMAS="${TOOL:+$TOOL/scope_lineage/schemas}"   # 工具自带的 JSON Schema；TOOL 留空时由下一行从已安装的包里找
[ -n "$SCHEMAS" ] || SCHEMAS="$(python3 -c 'import importlib.util as u, os; print(os.path.join(u.find_spec("scope_lineage").submodule_search_locations[0], "schemas"))' 2>/dev/null)"
load_tables() {   # 把 tables.txt 读进数组 TABLES；读到 0 张表就报错
  TABLES=(); while IFS= read -r t; do [ -n "$t" ] && TABLES+=("$t"); done < "$RUN/tables.txt"
  echo "tables=${#TABLES[@]}"; [ "${#TABLES[@]}" -gt 0 ]
}
note() {         # 账本流水：每一步做完的最后一条命令，例：note "S4 派 T1 demo_dwd.x 第1轮"
  printf -- '- %s %s\n' "$(date '+%F %T')" "$*" >> "$RUN/ledger.md"
}
fill() {         # 填模板：fill <模板> <输出文件> KEY=值 …；<模板> 写编号或名字（T4 / 修订 / fix），值写 @文件 表示取文件内容
  python3 - "$@" <<'PY'
import os, re, sys
if len(sys.argv) < 3:
    sys.exit("用法：fill <模板编号或名字> <输出文件> KEY=值 …")
name, out, pairs = sys.argv[1], sys.argv[2], sys.argv[3:]
skill = os.environ.get("SKILL") or os.path.join(os.environ.get("TOOL", ""), "skills/scope-lineage")
src = open(os.path.join(skill, "references/runbook-templates.md"), encoding="utf-8").read()
meta = {}   # 模板编号 -> {"names": [...], "MODE": [...], "rules": [(规则, 只在哪个 MODE 生效, 值)]}
for m in re.finditer(r"^<!-- fill: (.*?) -->$", src, re.M):
    entry = {"rules": []}
    for part in m.group(1).split(";"):
        rule = re.fullmatch(r"\s*([A-Za-z]+)(?:\[MODE=([^\]]+)\])?=(.*?)\s*", part)
        if not rule:
            sys.exit("runbook-templates.md 的 fill 注释写坏了：" + part.strip() + "。交 owner，不要自己改")
        if rule.group(1) in ("names", "MODE"):
            entry[rule.group(1)] = [x.strip() for x in rule.group(3).split(",") if x.strip()]
        else:
            entry["rules"].append((rule.group(1), rule.group(2), rule.group(3)))
    if not entry.get("names"):
        sys.exit("runbook-templates.md 有一行 fill 注释没写 names=。交 owner，不要自己改")
    meta[entry["names"][0]] = entry
tid = next((t for t, e in meta.items() if name.lower() in [n.lower() for n in e["names"]]), None)
if tid is None:
    sys.exit("没有模板 " + name + "；可用：" + "；".join(" / ".join(e["names"]) for e in meta.values()))
m = re.search(r"^## " + re.escape(tid) + r" (.*?)$.*?^----8<----\n(.*?)^----8<----$", src, re.S | re.M)
title, text = m.group(1), m.group(2)
label = tid + "（" + title + "）"
wanted = set(re.findall(r"\{([A-Z_]+)\}", text))
AUTO = {"RUN", "TOOL", "SKILL", "SCHEMAS", "SCRATCH", "TASKS", "PAGES", "SEMPAGES", "ENV", "ROUND_NAME"}
vals = {k: os.environ.get(k, "") for k in ("RUN", "TOOL", "SCRATCH", "TASKS", "PAGES", "SEMPAGES")}
vals["SKILL"] = skill
vals["SCHEMAS"] = os.environ.get("SCHEMAS") or (os.path.join(os.environ["TOOL"], "scope_lineage/schemas") if os.environ.get("TOOL") else "")
vals["ENV"] = os.path.join(os.environ["RUN"], "env.sh")
raw = {}
for pair in pairs:
    key, eq, value = pair.partition("=")
    if not eq or not re.fullmatch(r"[A-Z_]+", key):
        sys.exit("参数要写成 KEY=值：" + pair)
    if key not in wanted:
        sys.exit(label + "没有占位 {" + key + "}：模板选错了，或这个参数不属于它。它要的是：" + " ".join(sorted(wanted - AUTO)))
    if value.startswith("@") and not os.path.isfile(value[1:]):
        sys.exit(key + " 的取值文件不存在：" + value[1:])
    raw[key] = value
    vals[key] = open(value[1:], encoding="utf-8").read().strip() if value.startswith("@") else value
modes = meta[tid].get("MODE", [])
if "MODE" in wanted and vals.get("MODE") not in modes:
    sys.exit(tid + " 的 MODE 只能是：" + " / ".join(modes) + "（收到：" + vals.get("MODE", "") + "）")
if vals.get("ROUND"):
    vals["ROUND_NAME"] = os.path.basename(vals["ROUND"].rstrip("/"))
def expand(path):
    for key, value in vals.items():
        path = path.replace("{" + key + "}", value)
    left = sorted(set(re.findall(r"\{([A-Z_]+)\}", path)))
    if left:
        sys.exit(label + "缺参数：" + " ".join(k + "=…" for k in left) + "。先补上再填")
    return path
for rule, mode, value in meta[tid]["rules"]:
    if mode is not None and vals.get("MODE") != mode:
        continue
    when = "（MODE=" + mode + "）" if mode else ""
    if rule == "NEEDS" and not os.path.exists(expand(value)):
        sys.exit(label + when + "的前提文件不存在：" + expand(value) + "。模板或模式选错了，或前一步还没做完")
    if rule == "ABSENT" and os.path.exists(expand(value)):
        sys.exit(label + when + "要求这个文件不存在，它却存在：" + expand(value) + "。模板或模式选错了")
    if rule == "ATFILE":
        key, _, path = value.partition(":")
        if os.path.exists(expand(path)) and not raw.get(key, "").startswith("@"):
            sys.exit(label + when + "：" + expand(path) + " 存在，" + key + " 要写成 @文件")
        if not os.path.exists(expand(path)) and raw.get(key) != "无":
            sys.exit(label + when + "：" + expand(path) + " 不存在，" + key + " 要写「无」")
for key, value in vals.items():
    if value:
        text = text.replace("{" + key + "}", value)
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
open(out, "w", encoding="utf-8").write(text)
left = sorted(set(re.findall(r"\{[A-Z_]+\}", text)))
print(tid + " " + title + " -> " + out)
if left:
    sys.exit("未填的占位：" + " ".join(left))
PY
}
set -o pipefail
