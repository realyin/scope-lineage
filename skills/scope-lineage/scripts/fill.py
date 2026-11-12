#!/usr/bin/env python3
"""Fill one subagent prompt template: ``fill.py <template> <output file> KEY=value ...``.

The run's ``fill`` shell function (``scripts/runlib.sh``) calls this with the run's
``env.sh`` variables in the environment. ``<template>`` is a number or a name (T4 / 修订 /
fix); a value written ``@file`` is replaced by that file's content. The rules each template
is checked against are the ``<!-- fill: ... -->`` line under its heading. Exit 1 means the
prompt must not be sent: the message says what to change.
"""
import os, re, sys
if len(sys.argv) < 3:
    sys.exit("用法：fill <模板编号或名字> <输出文件> KEY=值 …")
name, out, pairs = sys.argv[1], sys.argv[2], sys.argv[3:]
skill = os.environ.get("SKILL") or os.path.join(os.environ.get("TOOL", ""), "skills/scope-lineage")
folder = os.path.join(skill, "references/templates")
if not os.path.isdir(folder):
    sys.exit("找不到模板目录：" + folder + "。SKILL 没指向 skill 目录，或 skill 是 0.12.0 之前的版本")
src = "\n".join(open(os.path.join(folder, name), encoding="utf-8").read()
                for name in sorted(os.listdir(folder)) if re.fullmatch(r"T\d+\.md", name))
meta = {}   # 模板编号 -> {"names": [...], "MODE": [...], "rules": [(规则, 只在哪个 MODE 生效, 值)]}
for m in re.finditer(r"^<!-- fill: (.*?) -->$", src, re.M):
    entry = {"rules": []}
    for part in m.group(1).split(";"):
        rule = re.fullmatch(r"\s*([A-Za-z]+)(?:\[MODE=([^\]]+)\])?=(.*?)\s*", part)
        if not rule:
            sys.exit("模板的 fill 注释写坏了：" + part.strip() + "。交 owner，不要自己改")
        if rule.group(1) in ("names", "MODE"):
            entry[rule.group(1)] = [x.strip() for x in rule.group(3).split(",") if x.strip()]
        else:
            entry["rules"].append((rule.group(1), rule.group(2), rule.group(3)))
    if not entry.get("names"):
        sys.exit("模板有一行 fill 注释没写 names=。交 owner，不要自己改")
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
