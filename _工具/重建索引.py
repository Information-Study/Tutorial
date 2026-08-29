#!/usr/bin/env python3
"""重建所有索引（MOC）頁的「子分類」與「篇章列表」表格。

用途：新增／刪除／改名／搬移筆記之後執行一次，索引就會跟著更新。
保留每個索引頁手寫的「本章導覽」與「建議閱讀順序」段落，只重寫兩張表。

用法：
    python3 _工具/重建索引.py            # 重建
    python3 _工具/重建索引.py --check    # 只檢查、不寫入（適合放進 CI 或 pre-commit）
"""
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".obsidian", "_範本", "_附件", "_設定檔範例", "_工具", "_規劃", "_表單範本"}
TABLE_HEADS = ("## 子分類", "## 篇章列表")
TAIL_HEAD = "## 建議閱讀順序"


def front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    fm = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm


def is_index(path: Path) -> bool:
    # 新命名：<編號段>-idx-<主題>-<標題>.md；舊命名：00-…索引.md
    return "-idx-" in path.name or (
        path.name.startswith("00-") and path.name.endswith("索引.md"))


def find_index(directory: Path):
    for p in sorted(x for x in directory.glob("*.md") if is_index(x)):
        return p
    return None


def build_tables(directory: Path, index_path: Path) -> str:
    out = []

    subs = sorted(d for d in directory.iterdir() if d.is_dir() and d.name not in SKIP_DIRS)
    rows = []
    for d in subs:
        sidx = find_index(d)
        if not sidx:
            continue
        fm = front_matter(sidx)
        rows.append(f"| [[{sidx.stem}]] | {fm.get('desc', '')} |")
    if rows:
        out += ["## 子分類", "", "| 分類 | 內容 |", "| --- | --- |", *rows, ""]

    notes = sorted(
        p for p in directory.glob("*.md")
        if p != index_path and not is_index(p) and "-idx-" not in p.name
    )
    rows = []
    for p in notes:
        fm = front_matter(p)
        num = p.stem.split("-")[0]
        rows.append(f"| {num} | [[{p.stem}]] | {fm.get('difficulty', '')} | {fm.get('desc', '')} |")
    if rows:
        out += ["## 篇章列表", "", "| # | 篇章 | 難度 | 說明 |", "| --- | --- | --- | --- |", *rows, ""]

    return "\n".join(out)


def rebuild(index_path: Path, check: bool) -> bool:
    text = index_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    start = next((i for i, l in enumerate(lines) if l.strip() in TABLE_HEADS), None)
    tail = next((i for i, l in enumerate(lines) if l.strip() == TAIL_HEAD), None)
    if tail is None:
        print(f"  略過（找不到「{TAIL_HEAD}」）：{index_path.relative_to(VAULT)}")
        return False
    if start is None:
        start = tail

    head = "\n".join(lines[:start]).rstrip() + "\n\n"
    body = build_tables(index_path.parent, index_path)
    rest = "\n".join(lines[tail:]).rstrip() + "\n"
    new = head + body + ("\n" if body and not body.endswith("\n\n") else "") + rest

    if new == text:
        return False
    if check:
        print(f"  需更新：{index_path.relative_to(VAULT)}")
    else:
        index_path.write_text(new, encoding="utf-8")
        print(f"  已更新：{index_path.relative_to(VAULT)}")
    return True


def main() -> int:
    check = "--check" in sys.argv
    changed = 0
    total = 0
    for path in sorted(x for x in VAULT.rglob("*.md") if is_index(x)):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        total += 1
        if rebuild(path, check):
            changed += 1
    verb = "需更新" if check else "已更新"
    print(f"索引共 {total} 個，{verb} {changed} 個。")
    return 1 if (check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
