#!/usr/bin/env python3
"""按 docs/AGENTS.md 的约束检查仓库内的 Markdown 文档。

错误（退出码 1）：字数超出预算、相对链接指向不存在的文件、指代无法在 HEAD 定位。
警告：历史叙述、推导过程、跨文档重复的句子。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUDGET_FILE = Path(__file__).with_name("budget.json")

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__"}

LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
MARKUP = re.compile(r"[#>*_" + chr(96) + r"|\-]+")
SPACE = re.compile(r"\s")
H2 = re.compile(r"^##\s")
HEADING = re.compile(r"^#{1,6}\s")
TABLE = re.compile(r"^\s*\|")
LIST = re.compile(r"^\s*([-*+]|\d+\.)\s")
FENCE = re.compile(r"^\s*" + chr(96) * 3)
PR_REF = re.compile(r"PR\s*#\d+")
SENTENCE = re.compile(r"[^。！？\n]+")
TRIM = re.compile(r"[\s，。、；：？！\"'“”‘’()（）\[\]{}<>《》·—\-]+")

INDEXICAL = ("见上文", "见下文", "如上所述", "如前所述")
HISTORY = ("已实现", "即将支持", "原来是", "本次调整")
NARRATION = ("我们先", "然后我们", "经过讨论")
MIN_SENTENCE = 14

errors = []
warnings = []


def visible(text):
    return len(SPACE.sub("", MARKUP.sub("", LINK.sub(r"\1", text))))


def quoted(line, start, end):
    return 0 < start and end < len(line) and line[start - 1] == "\u201c" and line[end] == "\u201d"


def report(kind, rel, line, message):
    item = f"::{kind} file={rel},line={line}::{message}"
    (errors if kind == "error" else warnings).append(item)


def load_budget():
    data = json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
    return data.pop("default"), data


def budget_for(directory, default, overrides):
    keys = [k for k in overrides if directory == k or directory.startswith(k + "/")]
    if not keys:
        return dict(default), "default"
    key = max(keys, key=len)
    return {**default, **overrides[key]}, key


def blocks_of(lines, start):
    """按空行、标题、表格行切分，列表项各算一段。"""
    out, buffer, at = [], [], start
    for offset, line in enumerate(lines):
        number = start + offset
        if not line.strip():
            if buffer:
                out.append((at, buffer))
            buffer = []
            continue
        if HEADING.match(line) or TABLE.match(line):
            if buffer:
                out.append((at, buffer))
            buffer = []
            continue
        if LIST.match(line):
            if buffer:
                out.append((at, buffer))
            at, buffer = number, [line]
            continue
        if not buffer:
            at = number
        buffer.append(line)
    if buffer:
        out.append((at, buffer))
    return out


def sections_of(lines):
    out, start, title, body = [], 1, "", []
    for number, line in enumerate(lines, start=1):
        if H2.match(line):
            out.append((start, title, body))
            start, title, body = number, line.strip(), []
        body.append(line)
    out.append((start, title, body))
    return out


def check_document(path, default, overrides):
    rel = path.relative_to(ROOT)
    name = rel.as_posix()
    parent = rel.parent.as_posix()
    budget, key = budget_for("" if parent == "." else parent, default, overrides)

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    total = visible(text)
    if total > budget["total"]:
        report("error", name, 1, f"全篇 {total} 字符，超出 {key} 的上限 {budget['total']}；按第 5 节先搬迁或压缩")

    for start, title, body in sections_of(lines):
        chars = visible("\n".join(body))
        if chars > budget["section"]:
            report("error", name, start, f"{title or '文首'} {chars} 字符，超出章节上限 {budget['section']}")
        for at, chunk in blocks_of(body, start):
            size = visible("\n".join(chunk))
            if size > budget["paragraph"]:
                report("error", name, at, f"单段 {size} 字符，超出段落上限 {budget['paragraph']}")

    for number, line in enumerate(lines, start=1):
        for match in LINK.finditer(line):
            target = match.group(2)
            if not target or target.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            local = target.split("#", 1)[0]
            if local and not (path.parent / local).exists():
                report("error", name, number, f"链接指向不存在的文件：{target}")

    fenced = False
    for number, line in enumerate(lines, start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for word in INDEXICAL:
            at = line.find(word)
            if at >= 0 and not quoted(line, at, at + len(word)):
                report("error", name, number, f"指代无法在 HEAD 定位：{word}")
                break
        match = PR_REF.search(line)
        if match and not quoted(line, match.start(), match.end()):
            report("error", name, number, f"指代无法在 HEAD 定位：{match.group(0)}")
        for word in HISTORY:
            at = line.find(word)
            if at >= 0 and not quoted(line, at, at + len(word)):
                report("warning", name, number, f"只写当前状态：{word}")
                break
        for word in NARRATION:
            if word in line:
                report("warning", name, number, f"删去推导过程：{word}")
                break

    return name, total, budget["total"]


def repeat_check(corpus):
    seen = {}
    for name, lines in corpus:
        fenced = False
        for number, line in enumerate(lines, start=1):
            if FENCE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            stripped = line.lstrip()
            if stripped.startswith("|") or stripped.startswith("#"):
                continue
            for match in SENTENCE.finditer(line):
                key = TRIM.sub("", match.group(0))
                if len(key) < MIN_SENTENCE:
                    continue
                seen.setdefault(key, []).append((name, number))

    for places in seen.values():
        if len(places) < 2:
            continue
        first = places[0]
        for name, number in places[1:]:
            warnings.append(
                f"::warning file={name},line={number}::与 {first[0]}:{first[1]} 重复；同一事实只保留一处"
            )


def main():
    default, overrides = load_budget()
    for key in overrides:
        if not (ROOT / key).is_dir():
            warnings.append(f"::warning file=tools/doccheck/budget.json,line=1::预算目录不存在：{key}")

    docs = [
        path
        for path in sorted(ROOT.rglob("*.md"))
        if not (set(path.relative_to(ROOT).parts) & SKIP_DIRS)
    ]

    rows, corpus = [], []
    for path in docs:
        rows.append(check_document(path, default, overrides))
        corpus.append((path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8").split("\n")))

    repeat_check(corpus)

    table = ["| 文件 | 字符 | 上限 | 余量 |", "|---|---|---|---|"]
    for name, chars, limit in rows:
        table.append(f"| {name} | {chars} | {limit} | {max(0, round((1 - chars / limit) * 100))}% |")

    for item in errors + warnings:
        print(item)
    print(f"检查 {len(rows)} 个文档：{len(errors)} 个错误，{len(warnings)} 个警告")

    summary = "\n".join(["### 文档字数", "", *table, ""])
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
