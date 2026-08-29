#!/usr/bin/env python3
"""vault 健檢 —— 一次跑完所有結構性檢查

用法：
    python3 _工具/健檢.py          # 完整檢查
    python3 _工具/健檢.py --quiet  # 只顯示問題
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUIET = "--quiet" in sys.argv

GROUPS = sorted(p for p in ROOT.iterdir() if p.is_dir() and re.match(r"^\d{3}-", p.name))
SKIP_DIRS = {".git", ".obsidian", ".trash"}
# ★ 只有這 13 個群組裡的篇章算「教學文」，需要完整的 13 段骨架與小測驗
#   000-索引（MOC/速查）、980-附錄、990-收件匣 不在此列
CONTENT_RE = re.compile(r"^(0[1-9]0|1[0-3]0)-")

# 索引頁判定：新命名帶 `-idx-`，舊命名以 00- 開頭
def IS_IDX(f) -> bool:
    return "-idx-" in f.name or f.name.startswith("00-")

REQUIRED = ["title", "desc", "aliases", "tags", "category", "status", "updated"]
NOTE_ONLY = ["difficulty", "distro", "prerequisites"]
VALID_STATUS = {"待撰寫", "撰寫中", "完成"}
VALID_DIFF = {"入門", "進階", "專家"}

# 新命名：<群組3碼>-<章2碼>[-<子章2碼>]-<序2碼>-<類型>-<主題前綴>-<標題>.md
SEQ_RE = re.compile(r"^(\d{3}(?:-\d{2})+)-(cmd|svc|guide|ref|idx|exam)-")

problems: list[str] = []
notices: list[str] = []


def say(msg: str = "") -> None:
    if not QUIET:
        print(msg)


def problem(msg: str) -> None:
    problems.append(msg)


def notice(msg: str) -> None:
    notices.append(msg)


def all_md() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def frontmatter(path: Path) -> dict[str, str]:
    """粗略解析 frontmatter（只取頂層 key: value）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if km:
            fm[km.group(1)] = km.group(2).strip()
    return fm


# ══════════════════════════════════════════════════════════
files = all_md()
def is_note(f: Path) -> bool:
    """教學文：位於 13 個內容群組中、且非索引頁。"""
    rel = f.relative_to(ROOT).parts
    return (
        len(rel) > 1
        and bool(CONTENT_RE.match(rel[0]))
        and not IS_IDX(f)
    )


notes = [f for f in files if is_note(f)]
indexes = [f for f in files if IS_IDX(f)]

say("═" * 62)
say("  vault 健檢")
say("═" * 62)
say(f"\n檔案：{len(files)} 個 .md（教學文 {len(notes)}、索引 {len(indexes)}）")

# ── 1. 檔名唯一性 ────────────────────────────────────────
say("\n【1】檔名唯一性（wikilink 靠檔名解析）")
by_name: dict[str, list[Path]] = defaultdict(list)
for f in files:
    by_name[f.name].append(f)
dupes = {k: v for k, v in by_name.items() if len(v) > 1}
if dupes:
    for name, paths in dupes.items():
        problem(f"檔名重複：{name}")
        for p in paths:
            say(f"    {p.relative_to(ROOT)}")
else:
    say("  ✓ 無重複")

# ── 2. 章節編號 ──────────────────────────────────────────
say("\n【2】章節內編號")
num_issues = 0
for d in sorted({f.parent for f in files}):
    if d == ROOT or any(part in SKIP_DIRS for part in d.parts):
        continue
    nums, idx_nums = [], set()
    for f in sorted(d.glob("*.md")):
        m = SEQ_RE.match(f.name)
        if not m:
            continue
        seq = int(m.group(1).split("-")[-1])
        # 索引頁（idx）不參與連號檢查，但其佔用的號碼不算跳號
        (idx_nums.add(seq) if m.group(2) == "idx" else nums.append(seq))
    if not nums:
        continue
    sub = {int(x.name[:2]) for x in d.iterdir() if x.is_dir() and re.match(r"^\d\d-", x.name)}
    dup = [n for n, c in Counter(nums).items() if c > 1]
    gaps = [n for n in range(1, max(nums) + 1)
            if n not in nums and n not in sub and n not in idx_nums]
    if dup or gaps:
        num_issues += 1
        rel = d.relative_to(ROOT)
        if dup:
            problem(f"編號重複 {rel}：{sorted(dup)}")
        if gaps:
            notice(f"編號跳號 {rel}：{gaps}")
if not num_issues:
    say("  ✓ 全部連續無重號")

# ── 3. frontmatter ───────────────────────────────────────
say("\n【3】frontmatter")
missing = Counter()
bad_status = []
bad_diff = []
for f in files:
    rel = f.relative_to(ROOT).parts
    if f.parent == ROOT or rel[0].startswith("_"):
        continue
    fm = frontmatter(f)
    if not fm:
        problem(f"無 frontmatter：{f.relative_to(ROOT)}")
        continue
    for k in REQUIRED:
        if k not in fm:
            missing[k] += 1
    if f in notes:
        for k in NOTE_ONLY:
            if k not in fm:
                missing[k] += 1
    st = fm.get("status", "").split("#")[0].strip()
    if st and st not in VALID_STATUS and "表單" not in str(f):
        bad_status.append((f, st))
    df = fm.get("difficulty", "").split("#")[0].strip()
    if df and df not in VALID_DIFF:
        bad_diff.append((f, df))

if missing:
    for k, n in missing.most_common():
        problem(f"缺欄位 {k}：{n} 篇")
else:
    say("  ✓ 必要欄位齊全")
for f, v in bad_status:
    problem(f"status 值異常「{v}」：{f.relative_to(ROOT)}")
for f, v in bad_diff:
    problem(f"difficulty 值異常「{v}」：{f.relative_to(ROOT)}")

# ── 4. 索引頁覆蓋 ────────────────────────────────────────
say("\n【4】索引頁覆蓋")
no_index = []
for d in sorted({f.parent for f in files}):
    if d == ROOT or any(part in SKIP_DIRS for part in d.parts):
        continue
    if not str(d.relative_to(ROOT))[0].isdigit():
        continue
    if not [x for x in d.glob("*.md") if IS_IDX(x)]:
        no_index.append(d.relative_to(ROOT))
if no_index:
    for d in no_index:
        problem(f"缺索引頁：{d}")
else:
    say("  ✓ 每個目錄都有索引")

# ── 5. 小測驗與骨架 ──────────────────────────────────────
say("\n【5】已完成篇章的必備段落")
need = ["## 小測驗", "測驗答案", "## 練習題", "## 延伸閱讀"]
lack = defaultdict(list)
# 總結小考（exam）本身就是考卷，不需要「小測驗／練習題」那幾段
def is_exam(f: Path) -> bool:
    m = SEQ_RE.match(f.name)
    return bool(m) and m.group(2) == "exam"


done_notes = [f for f in notes
              if frontmatter(f).get("status", "").startswith("完成") and not is_exam(f)]
exams = [f for f in notes if is_exam(f)]
for f in done_notes:
    text = f.read_text(encoding="utf-8")
    for seg in need:
        if seg not in text:
            lack[seg].append(f)

# 小考另有自己的規格：100 題、每題都要指回原文
for f in exams:
    text = f.read_text(encoding="utf-8")
    nq = len(re.findall(r"^Q\d+\.", text, re.M))
    nref = text.count("→ 詳見")
    if nq != 100:
        problem(f"總結小考題數 {nq} ≠ 100：{f.relative_to(ROOT)}")
    if nref < nq:
        problem(f"總結小考有 {nq - nref} 題缺「→ 詳見」原文連結：{f.relative_to(ROOT)}")
if lack:
    for seg, fs in lack.items():
        problem(f"{len(fs)} 篇已完成的文章缺「{seg}」")
        for f in fs[:3]:
            say(f"    {f.relative_to(ROOT)}")
else:
    say(f"  ✓ {len(done_notes)} 篇已完成的文章段落齊全，{len(exams)} 份總結小考規格符合")

# ── 6. 群組標籤一致性 ────────────────────────────────────
say("\n【6】群組標籤一致性")
tag_bad = 0
for g in GROUPS:
    tags = Counter()
    for f in g.rglob("*.md"):
        t = frontmatter(f).get("tags", "")
        m = re.match(r"\[([^,\]]+)", t)
        if m:
            tags[m.group(1).strip()] += 1
    if len(tags) > 1:
        tag_bad += 1
        problem(f"{g.name} 群組標籤不一致：{dict(tags)}")
if not tag_bad:
    say(f"  ✓ {len(GROUPS)} 個群組標籤各自統一")

# ── 7. 進度 ──────────────────────────────────────────────
say("\n【7】撰寫進度")
st = Counter()
for f in notes:
    st[frontmatter(f).get("status", "?").split("#")[0].strip()] += 1
total = sum(st.values())
for k in ["完成", "撰寫中", "待撰寫"]:
    n = st.get(k, 0)
    say(f"  {k:<6} {n:4d}  ({n / total * 100:5.1f}%)")

# ══════════════════════════════════════════════════════════
print()
print("═" * 62)
if problems:
    print(f"  ★★★★ {len(problems)} 項問題")
    for p in problems:
        print(f"    ✗ {p}")
else:
    print("  ★ 沒有發現問題")
if notices:
    print(f"\n  提示 {len(notices)} 項（多為四層結構的正常跳號）")
    for n in notices[:5]:
        print(f"    · {n}")
print("═" * 62)
sys.exit(1 if problems else 0)
