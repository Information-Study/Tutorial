#!/usr/bin/env python3
"""依照全書慣例新增一篇教學筆記（含完整 frontmatter 與章節骨架）。

用法：
    python3 _工具/新增筆記.py "04-Web伺服器/02-Nginx" "Nginx 限流與防爆量" --kind svc --difficulty 進階 \
        --desc "用 limit_req 與 limit_conn 擋住暴衝流量" --tags "服務/nginx,主題/效能"

編號會自動接續該資料夾現有的最大編號。建立完請執行 `python3 _工具/重建索引.py`。
"""
import argparse
import re
from datetime import date
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent

BODY = {
    "cmd": ["觀念說明", "基礎操作", "__RHEL__", "進階用法", "完整實戰範例",
            "__ERR__", "__SEC__", "__CHEAT__", "__EX__"],
    "svc": ["觀念說明", "環境準備與安裝", "__RHEL__", "基礎設定", "進階設定與調校",
            "完整實戰範例", "__ERR__", "__SEC__", "__CHEAT__", "__EX__"],
    "guide": ["觀念說明", "逐步說明", "__RHEL__", "完整實戰範例", "__ERR__",
              "__LIST__", "__EX__"],
    "ref": ["__REF__"],
}
BLOCKS = {
    "__RHEL__": "> [!info]- Rocky / AlmaLinux（RHEL 系）對照\n> <!-- TODO: 待撰寫 -->\n",
    "__ERR__": "## 常見錯誤與排錯\n\n| 現象 | 原因 | 解法 |\n| --- | --- | --- |\n|  |  |  |\n",
    "__SEC__": "## 安全性注意事項\n\n> [!warning] 注意\n> <!-- TODO: 待撰寫 -->\n",
    "__CHEAT__": "## 速查表\n\n| 指令 / 參數 | 說明 | 範例 |\n| --- | --- | --- |\n|  |  |  |\n",
    "__EX__": "## 練習題\n\n> [!question]- 練習 1\n> <!-- TODO: 待撰寫 -->\n",
    "__LIST__": "## 檢查清單\n\n- [ ] <!-- TODO: 待撰寫 -->\n",
    "__REF__": "> [!tip] 用法\n> 這是速查頁，用全域搜尋直接找關鍵字。\n\n"
               "## 速查內容\n\n| 項目 | 說明 | 備註 |\n| --- | --- | --- |\n|  |  |  |\n",
}


def next_number(directory: Path) -> str:
    nums = [int(m.group(1)) for p in directory.glob("*.md")
            if (m := re.match(r"^(\d+)-", p.name)) and not p.name.startswith("00-")]
    return f"{max(nums, default=0) + 1:02d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", help="相對於 vault 根目錄的資料夾")
    ap.add_argument("title", help="文章標題")
    ap.add_argument("--kind", default="guide", choices=list(BODY))
    ap.add_argument("--difficulty", default="入門", choices=["入門", "進階", "專家"])
    ap.add_argument("--desc", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--aliases", default="")
    ap.add_argument("--prereq", default="", help="逗號分隔的筆記名稱（不含 .md）")
    ap.add_argument("--related", default="", help="逗號分隔的筆記名稱（不含 .md）")
    args = ap.parse_args()

    directory = VAULT / args.directory
    if not directory.is_dir():
        raise SystemExit(f"找不到資料夾：{directory}")

    def lst(s):
        items = [x.strip() for x in s.split(",") if x.strip()]
        return "[" + ", ".join(items) + "]"

    def links(s):
        items = [x.strip() for x in s.split(",") if x.strip()]
        return "[" + ", ".join(f'"[[{x}]]"' for x in items) + "]"

    def bullets(s, fallback="- [[00-首頁]]"):
        items = [x.strip() for x in s.split(",") if x.strip()]
        return "\n".join(f"- [[{x}]]" for x in items) if items else fallback

    num = next_number(directory)
    path = directory / f"{num}-{args.title.replace(' ', '')}.md"
    if path.exists():
        raise SystemExit(f"檔案已存在：{path}")

    parts = [
        "---",
        f'title: "{args.title}"',
        f'desc: "{args.desc}"',
        f"aliases: {lst(args.aliases)}",
        f"tags: {lst(args.tags)}",
        f"category: {re.sub(r'^\d+-', '', args.directory.split('/')[0])}",
        f"difficulty: {args.difficulty}",
        "status: 待撰寫",
        "distro: [ubuntu, rhel]",
        f"prerequisites: {links(args.prereq)}",
        f"updated: {date.today().isoformat()}",
        "---",
        "",
        f"# {args.title}",
        "",
        "> [!abstract] 這篇你會學到",
        "> - <!-- TODO: 待撰寫 -->",
        "",
        "## 前置知識",
        "",
        bullets(args.prereq),
        "",
    ]
    for sec in BODY[args.kind]:
        parts.append(BLOCKS[sec] if sec.startswith("__") else f"## {sec}\n\n<!-- TODO: 待撰寫 -->\n")
    parts += ["## 延伸閱讀", "", bullets(args.related), ""]

    path.write_text("\n".join(parts), encoding="utf-8")
    print(f"已建立：{path.relative_to(VAULT)}")
    print("接著執行：python3 _工具/重建索引.py")


if __name__ == "__main__":
    main()
