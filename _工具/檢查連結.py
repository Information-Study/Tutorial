#!/usr/bin/env python3
"""檢查 vault 內所有 [[wikilink]] 是否都指得到實際存在的筆記。

用法：
    python3 _工具/檢查連結.py
離開碼 1 代表有斷掉的連結。
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".obsidian", "_附件"}
LINK = re.compile(r"\[\[([^\]|#]+)")

notes = {}
for p in VAULT.rglob("*.md"):
    if any(part in SKIP_DIRS for part in p.parts):
        continue
    notes[p.stem] = p

broken = defaultdict(list)
for p in notes.values():
    if "_範本" in p.parts:
        continue
    in_fence = False
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = re.sub(r"`[^`]*`", "", line)          # 略過行內程式碼
        for target in LINK.findall(line):
            target = target.strip()
            if target and target not in notes:
                broken[str(p.relative_to(VAULT))].append((line_no, target))

if broken:
    for f, items in sorted(broken.items()):
        print(f"\n{f}")
        for line_no, target in items:
            print(f"  第 {line_no} 行 → [[{target}]]  ✗ 找不到")
    total = sum(len(v) for v in broken.values())
    print(f"\n共 {total} 個斷掉的連結。")
    sys.exit(1)

print(f"檢查 {len(notes)} 篇筆記，所有 wikilink 都指得到。")
