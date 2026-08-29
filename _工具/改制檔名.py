#!/usr/bin/env python3
"""全 vault 檔名改制

新格式（編號段數＝資料夾深度，各段補零）：

    三層： <大章 3碼>-<小章 2碼>-<序 2碼>-<類型>-<主題前綴>-<標題>.md
    四層： <大章 3碼>-<小章 2碼>-<子章 2碼>-<序 2碼>-<類型>-<主題前綴>-<標題>.md

用法：
    python3 _工具/改制檔名.py --dry-run    # 只輸出對照表，不動檔案
    python3 _工具/改制檔名.py --apply      # git mv 搬移
    python3 _工具/改制檔名.py --fix-links  # 改寫所有 wikilink（含 frontmatter）
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".obsidian", ".trash", "_附件"}
MAP_FILE = ROOT / "_規劃" / "檔名對照表.tsv"

# ── 主題前綴：資料夾 → 短代號 ───────────────────────────────
# 沒列到的資料夾，取其名稱去掉數字前綴後直接使用
FOLDER_PREFIX = {
    "000-索引": "索引",
    "010-基礎概論/01-計算機概論": "計概",
    "010-基礎概論/02-計算機網路": "網概",
    "020-Linux/01-Linux基礎": "Linux",
    "020-Linux/02-Linux伺服器管理/01-SSH與遠端管理": "SSH",
    "020-Linux/02-Linux伺服器管理/02-系統服務與排程": "systemd",
    "020-Linux/02-Linux伺服器管理/03-伺服器建置與標準化": "標準化",
    "030-Windows/01-Windows系統管理/01-WindowsServer基礎": "WinServer",
    "030-Windows/01-Windows系統管理/02-ActiveDirectory": "AD",
    "030-Windows/01-Windows系統管理/03-群組原則GPO": "GPO",
    "030-Windows/01-Windows系統管理/04-WDS系統部署": "WDS",
    "030-Windows/01-Windows系統管理/05-Windows故障排除": "Win排錯",
    "040-網路與網路設備/01-網路基礎與設備": "網路設備",
    "040-網路與網路設備/02-機房與硬體管理": "機房",
    "050-虛擬機與容器/01-虛擬化平台": "PVE",
    "050-虛擬機與容器/02-容器化/01-Docker": "Docker",
    "050-虛擬機與容器/02-容器化/02-DockerCompose": "Compose",
    "050-虛擬機與容器/02-容器化/03-Compose範例集": "範例",
    "060-軟體與開發工具/01-常用工具/01-Git": "Git",
    "060-軟體與開發工具/01-常用工具/02-編輯器": "編輯器",
    "060-軟體與開發工具/01-常用工具/03-系統監控": "監控",
    "060-軟體與開發工具/01-常用工具/04-網路診斷": "網路診斷",
    "060-軟體與開發工具/01-常用工具/05-終端機工作流": "終端機",
    "060-軟體與開發工具/01-常用工具/06-檔案傳輸與同步": "傳輸",
    "060-軟體與開發工具/02-Web伺服器": "Web",
    "060-軟體與開發工具/02-Web伺服器/02-Nginx": "Nginx",
    "060-軟體與開發工具/02-Web伺服器/03-Apache": "Apache",
    "060-軟體與開發工具/02-Web伺服器/05-MyGuard套件庫與Angie": "MyGuard",
    "060-軟體與開發工具/03-應用執行環境": "執行環境",
    "060-軟體與開發工具/03-應用執行環境/01-PHP": "PHP",
    "060-軟體與開發工具/03-應用執行環境/02-Node.js": "Node",
    "060-軟體與開發工具/04-資料庫與資料儲存": "DB",
    "060-軟體與開發工具/04-資料庫與資料儲存/01-MySQL": "MySQL",
    "060-軟體與開發工具/04-資料庫與資料儲存/02-PostgreSQL": "PostgreSQL",
    "060-軟體與開發工具/04-資料庫與資料儲存/03-Qdrant": "Qdrant",
    "070-系統及工具開發/01-前端基礎": "前端",
    "070-系統及工具開發/02-Vue與Nuxt": "Vue",
    "070-系統及工具開發/03-PHP與Laravel": "Laravel",
    "070-系統及工具開發/04-Python開發": "Python",
    "070-系統及工具開發/05-Shell與PowerShell": "Shell",
    "070-系統及工具開發/06-自動化測試": "測試",
    "070-系統及工具開發/07-n8n流程自動化": "n8n",
    "080-專案管理/01-專案管理基礎": "專管",
    "080-專案管理/02-需求與規格管理": "需求",
    "080-專案管理/03-版本與發布管理": "發布",
    "080-專案管理/04-協作與知識管理": "協作",
    "090-資訊安全/01-憑證與PKI": "PKI",
    "090-資訊安全/02-系統與網路防護": "防護",
    "090-資訊安全/03-應用與資料安全": "應用安全",
    "090-資訊安全/04-WAF與ModSecurity": "WAF",
    "090-資訊安全/05-資安防護設備與軟體": "資安設備",
    "090-資訊安全/06-TWGCB政府組態基準": "TWGCB",
    "090-資訊安全/07-資安實踐與規範": "資安實踐",
    "090-資訊安全/08-Wazuh資安監控": "Wazuh",
    "100-系統維運/01-監控與日誌分析": "日誌",
    "100-系統維運/01-監控與日誌分析/01-GoAccess": "GoAccess",
    "100-系統維運/02-維運實務": "維運",
    "110-AI人工智慧/01-AI服務基礎": "AI服務",
    "110-AI人工智慧/02-Ollama": "Ollama",
    "110-AI人工智慧/03-OpenWebUI": "OpenWebUI",
    "110-AI人工智慧/04-ComfyUI": "ComfyUI",
    "110-AI人工智慧/05-AI輔助開發": "AI開發",
    "120-雲端與架構/01-雲端與架構": "雲端",
    "130-實務案例/01-專案部署實戰": "部署",
    "130-實務案例/01-專案部署實戰/02-Vue部署": "Vue部署",
    "130-實務案例/01-專案部署實戰/03-Nuxt部署": "Nuxt部署",
    "130-實務案例/01-專案部署實戰/04-Laravel部署": "Laravel部署",
    "130-實務案例/01-專案部署實戰/05-前後端分離架構": "前後端",
    "980-附錄": "附錄",
    "990-收件匣": "收件匣",
}


def content_of(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


SVC_WORDS = ("安裝", "部署", "設定檔", "初始化", "架設", "建置", "啟動",
             "調校", "複寫", "高可用", "叢集", "升級", "備份與還原")
CMD_WORDS = ("指令", "操作", "用法", "快速上手", "入門與", "基礎操作")


def kind_of(p: Path, text: str) -> str:
    """推導文件類型代碼。

    ★★★ 未撰寫的骨架不能用段落標題判斷 —— `批次建立骨架.sh` 對每一篇
    都寫了 `## 環境準備與安裝`，一律當 svc 會錯。骨架改用標題關鍵字判斷。
    """
    if p.name.startswith("00-") or re.search(r"^type:\s*MOC", text, re.M):
        return "idx"

    name = p.stem
    if any(k in name for k in ("速查", "對照表", "總表", "術語", "名詞解釋", "地圖", "範本")):
        return "ref"

    written = bool(re.search(r"^status:\s*完成", text, re.M))
    if written:
        # 已撰寫：段落標題最可信
        if re.search(r"^## (環境準備與安裝|安裝與設定|基礎設定|環境準備)", text, re.M):
            return "svc"
        if re.search(r"^## (基礎操作|進階用法)", text, re.M):
            return "cmd"
        return "guide"

    # 骨架：只能看標題關鍵字
    if any(k in name for k in SVC_WORDS):
        return "svc"
    if any(k in name for k in CMD_WORDS):
        return "cmd"
    return "guide"


def folder_prefix(rel_dir: str) -> str:
    if rel_dir in FOLDER_PREFIX:
        return FOLDER_PREFIX[rel_dir]
    last = rel_dir.split("/")[-1]
    return re.sub(r"^\d+-", "", last)


def split_stem(stem: str) -> tuple[str, str, str]:
    """把 `NN-前綴-標題` 或 `NN-標題` 拆成 (序號, 前綴或空, 標題)。"""
    m = re.match(r"^(\d+)-(.+)$", stem)
    if not m:
        return "", "", stem
    num, rest = m.group(1), m.group(2)
    m2 = re.match(r"^([A-Za-z0-9._+#-]{2,20}|[一-鿿]{2,6})-(.+)$", rest)
    if m2:
        return num, m2.group(1), m2.group(2)
    return num, "", rest


def build_map() -> list[tuple[Path, Path]]:
    pairs = []
    for p in sorted(ROOT.rglob("*.md")):
        if any(x in SKIP_DIRS for x in p.parts):
            continue
        parts = p.relative_to(ROOT).parts
        if len(parts) < 2 or not re.match(r"^\d{3}-", parts[0]):
            continue

        text = content_of(p)
        num, fpref, title = split_stem(p.stem)
        if not num:
            continue

        rel_dir = "/".join(parts[:-1])
        group = parts[0][:3]

        # 各層編號
        segs = [group]
        for folder in parts[1:-1]:
            m = re.match(r"^(\d+)-", folder)
            segs.append(f"{int(m.group(1)):02d}" if m else "00")
        segs.append(f"{int(num):02d}")

        kind = kind_of(p, text)
        prefix = fpref or folder_prefix(rel_dir)

        # 索引頁的標題常是「XXX-索引」或「XXX-總覽-索引」，去掉贅字
        if kind == "idx":
            title = re.sub(r"-?索引$", "", title)
            title = re.sub(r"-?總覽$", "總覽", title)
            title = title or prefix
            # 前綴與標題重複時（如 計算機概論-計算機概論）只留標題
            if prefix == title or title.startswith(prefix):
                prefix = ""

        parts_out = segs + [kind] + ([prefix] if prefix else []) + [title]
        new_stem = "-".join(parts_out)
        new_stem = re.sub(r"-{2,}", "-", new_stem).strip("-")
        new_path = p.parent / f"{new_stem}.md"
        if new_path != p:
            pairs.append((p, new_path))
    return pairs


def check_unique(pairs):
    seen = {}
    dupes = []
    allnames = {p.stem for p in ROOT.rglob("*.md")
                if not any(x in SKIP_DIRS for x in p.parts)}
    for old, new in pairs:
        allnames.discard(old.stem)
    for old, new in pairs:
        if new.stem in seen:
            dupes.append((new.stem, seen[new.stem], old))
        seen[new.stem] = old
        if new.stem in allnames:
            dupes.append((new.stem, "（與未改名的檔案撞名）", old))
    return dupes


def main():
    pairs = build_map()
    dupes = check_unique(pairs)

    if "--dry-run" in sys.argv:
        MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with MAP_FILE.open("w", encoding="utf-8") as f:
            for old, new in pairs:
                f.write(f"{old.relative_to(ROOT)}\t{new.relative_to(ROOT)}\n")
        for old, new in pairs:
            print(f"{old.stem}\n  → {new.stem}")
        print(f"\n共 {len(pairs)} 個檔案要改名，對照表寫入 {MAP_FILE.relative_to(ROOT)}")
        if dupes:
            print(f"\n★★★★ 撞名 {len(dupes)} 組：")
            for n, a, b in dupes:
                print(f"  {n}\n    {a}\n    {b}")
            sys.exit(1)
        print("✓ 新檔名全 vault 唯一")
        return

    if "--apply" in sys.argv:
        if dupes:
            print("★★★★ 有撞名，拒絕執行。先跑 --dry-run 檢查。")
            sys.exit(1)
        for old, new in pairs:
            subprocess.run(["git", "mv", str(old.relative_to(ROOT)),
                            str(new.relative_to(ROOT))], cwd=ROOT, check=True)
        print(f"✓ 已搬移 {len(pairs)} 個檔案")
        return

    if "--fix-links" in sys.argv:
        rename = {}
        for line in MAP_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            o, n = line.split("\t")
            rename[Path(o).stem] = Path(n).stem
        changed = 0
        for p in ROOT.rglob("*.md"):
            if any(x in SKIP_DIRS for x in p.parts):
                continue
            text = orig = p.read_text(encoding="utf-8")

            def repl(m):
                target = m.group(1).strip()
                alias = m.group(2) or ""
                if target in rename:
                    return f"[[{rename[target]}{alias}]]"
                return m.group(0)

            text = re.sub(r"\[\[([^\]|#]+)((?:\|[^\]]*)?)\]\]", repl, text)
            if text != orig:
                p.write_text(text, encoding="utf-8")
                changed += 1
        print(f"✓ 已改寫 {changed} 個檔案中的 wikilink")
        return

    print(__doc__)


if __name__ == "__main__":
    main()
