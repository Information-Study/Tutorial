# Linux 系列教學

一套從基礎指令寫到正式環境部署與資安強化的 Linux 教學筆記，以 **Obsidian vault** 的形式組織。

- **主線環境**：Ubuntu / Debian（撰寫時為 Ubuntu 26.04 LTS）
- **對照環境**：每篇附「Rocky / AlmaLinux（RHEL 系）對照」摺疊區塊
- **規模**：11 個主章節、197 篇教學、40 個索引頁

## 快速開始

用 Obsidian 開啟這個資料夾作為 vault，從 `00-索引/00-首頁.md` 開始；
第一次閱讀請先看 `00-索引/01-學習路徑.md`，依目標挑一條路線。

不用 Obsidian 也可以直接讀 Markdown，只是 `[[wikilink]]` 不會變成可點連結。

## 目錄結構

```
00-索引/              總入口、學習路徑與四份速查表
01-Linux基礎/         檔案系統、權限、程序、套件、systemd、日誌、Shell 腳本
02-常用工具/          Git、編輯器、系統監控、網路診斷、終端機工作流、檔案傳輸
03-SSH與遠端管理/     金鑰認證、設定檔、隧道轉發、SFTP、安全強化
04-Web伺服器/         Nginx、Apache、選型與共存
05-應用執行環境/       PHP-FPM、Node.js 與 PM2、Python 服務化
06-資料庫與資料儲存/   MySQL、PostgreSQL、Qdrant、Redis
07-AI服務/            Ollama、OpenWebUI、RAG 知識庫、整合實戰
08-容器化/            Docker、Docker Compose、六組 Compose 範例
09-監控與日誌分析/     GoAccess、日誌輪替、監控告警、健康檢查
10-安全性/            防火牆、Fail2ban、TLS、ModSecurity、稽核與應變
11-專案部署實戰/       Vue、Nuxt、Laravel、前後端分離架構、部署自動化
98-附錄/              發行版差異、錯誤訊息對照、實驗環境搭建
99-收件匣/            尚未歸類的草稿

_範本/                Obsidian 範本（教學文章、索引、速查表）
_附件/                圖片與附件
_設定檔範例/           可直接取用的完整設定檔（nginx / apache / systemd / compose / …）
_工具/                維護腳本
```

## 文件慣例

### Frontmatter

```yaml
---
title: 檔案權限與擁有者      # 標題
desc: rwx 權限模型…          # 一句話說明，索引表格會自動抓這欄
aliases: [chmod, chown]      # Obsidian 別名，方便搜尋
tags: [linux/基礎, 主題/權限]
category: Linux基礎
difficulty: 入門             # 入門 / 進階 / 專家
status: 待撰寫               # 待撰寫 / 撰寫中 / 完成
distro: [ubuntu, rhel]
prerequisites: ["[[05-路徑導覽與檔案操作]]"]
updated: 2026-08-27
---
```

### 章節骨架

每篇教學固定包含：這篇你會學到 → 前置知識 → 觀念說明 → 安裝或基礎操作 →
進階應用 → 完整實戰範例 → 常見錯誤與排錯 → 安全性注意事項 → 速查表 → 練習題 → 延伸閱讀。

### Callout

| 寫法 | 用途 |
| --- | --- |
| `> [!abstract]` | 這篇你會學到 |
| `> [!note]` | 觀念補充 |
| `> [!tip]` | 實務建議 |
| `> [!example]` | 範例 |
| `> [!warning]` | 注意事項 |
| `> [!danger]` | 危險或不可逆操作 |
| `> [!info]- Rocky / AlmaLinux（RHEL 系）對照` | 發行版差異，預設摺疊 |
| `> [!question]- 練習解答` | 練習題解答，預設摺疊 |

### 其他

- 交叉引用一律用 `[[檔名]]`，不要用相對路徑。
- 程式碼區塊一定標語言：`bash` `nginx` `apache` `yaml` `ini` `sql` `php` `json` `dockerfile`。
- 長設定檔放 `_設定檔範例/`，內文只放關鍵片段並連結過去。
- 檔名格式 `NN-標題.md`，全 vault 檔名唯一（`[[wikilink]]` 才不會撞名）。

## 維護工具

```bash
python3 _工具/重建索引.py          # 新增／改名／搬移筆記後，重建所有索引表格
python3 _工具/重建索引.py --check  # 只檢查不寫入（適合 pre-commit / CI）
python3 _工具/檢查連結.py          # 檢查斷掉的 wikilink
python3 _工具/進度統計.py          # 各章撰寫進度
python3 _工具/新增筆記.py <資料夾> <標題> [選項]   # 依慣例建立新筆記
```

索引頁的「本章導覽」與「建議閱讀順序」是手寫的，重建時會保留；
只有「子分類」與「篇章列表」兩張表會依 frontmatter 重新產生。

### 新增一篇教學

```bash
python3 _工具/新增筆記.py "04-Web伺服器/02-Nginx" "Nginx限流與防爆量" \
    --kind svc --difficulty 進階 \
    --desc "用 limit_req 與 limit_conn 擋住暴衝流量" \
    --tags "服務/nginx,主題/效能" \
    --prereq "08-Nginx-效能調校" --related "09-Nginx-安全設定"
python3 _工具/重建索引.py
```

`--kind` 決定章節骨架：`cmd`（指令教學）、`svc`（服務教學）、`guide`（觀念與實戰）、`ref`（速查頁）。

### 新增一個章節

1. 建資料夾 `NN-章節名/`
2. 從 `_範本/索引MOC範本.md` 複製出 `00-章節名-索引.md`，填好 frontmatter 的 `desc` 與「本章導覽」「建議閱讀順序」
3. 用 `新增筆記.py` 加入教學文
4. 跑 `重建索引.py`，父層索引會自動出現這個子分類

## 提交規範

```
docs(nginx): 新增反向代理與負載平衡教學
docs(linux基礎): 補充 chmod 特殊權限範例
chore: 調整 vault 目錄結構
fix(連結): 修正 Laravel 部署章節的斷掉連結
```

## 撰寫進度

執行 `python3 _工具/進度統計.py` 查看即時進度。

目前狀態：骨架完成（目錄結構、frontmatter、章節大綱、交叉連結、索引頁），
教學內容依章節分批撰寫中。
