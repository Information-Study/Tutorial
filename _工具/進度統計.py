#!/usr/bin/env python3
"""統計各章節的撰寫進度（依 frontmatter 的 status 欄位）。"""
import re
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".obsidian", "_範本", "_附件", "_設定檔範例", "_工具", "_規劃", "_表單範本"}

by_section = defaultdict(Counter)
moc = 0
for p in sorted(VAULT.rglob("*.md")):
    if any(part in SKIP_DIRS for part in p.parts):
        continue
    if p.parent == VAULT:          # 根目錄的 README.md / CLAUDE.md 不是教學
        continue
    text = p.read_text(encoding="utf-8")
    if re.search(r"^type:\s*MOC", text, re.M):
        moc += 1
        continue
    m = re.search(r"^status:\s*(\S+)", text, re.M)
    status = m.group(1) if m else "未標註"
    by_section[p.relative_to(VAULT).parts[0]][status] += 1

print(f"{'章節':<24}{'完成':>6}{'撰寫中':>8}{'待撰寫':>8}{'總計':>6}  進度")
print("-" * 72)
grand = Counter()
for section in sorted(by_section):
    c = by_section[section]
    grand.update(c)
    total = sum(c.values())
    done = c["完成"]
    bar = "█" * round(done / total * 20) + "░" * (20 - round(done / total * 20))
    print(f"{section:<24}{done:>6}{c['撰寫中']:>8}{c['待撰寫']:>8}{total:>6}  {bar} {done/total:.0%}")
print("-" * 72)
total = sum(grand.values())
done = grand["完成"]
print(f"{'總計':<24}{done:>6}{grand['撰寫中']:>8}{grand['待撰寫']:>8}{total:>6}  {done/total:.0%}")
print(f"\n另有 {moc} 個索引（MOC）頁，不計入教學進度。")
