# CLAUDE.md

給 Claude Code 的專案指引。動工前先讀這份，再讀 `_規劃/手冊升級規劃.md`。

## 這是什麼

**資訊設備安裝、部署、設定、優化、維護教學手冊** — 一個 Obsidian vault，同時是 git repo。
讀者是負責機關／企業資訊設備的維運人員，不是想學程式的開發者。

- 涵蓋：Linux、工作站環境、網路設備、軟路由、機房硬體、虛擬化、容器、Windows/AD、
  Web/DB/AI 服務、憑證 PKI、資訊安全、監控、維運制度、專案部署
- 規模目標：**360 篇教學 / 418 個檔案**（現有 197 篇骨架，規劃新增 163 篇）
- 語言：**繁體中文**，技術名詞保留英文原文

## 現況

- 骨架已建立、內容尚未撰寫（所有教學文 `status: 待撰寫`）
- **正在進行**：依 `_規劃/手冊升級規劃.md` 從「Linux 教學」升級為「資訊設備維運手冊」
- 升級分五批 B1～B5，B1 是資料夾重編號搬遷，尚未執行

## 目錄結構

**依十一個群組編排**，十位數分群編號，群組間留空號方便插入。
每篇 frontmatter 的 `tags` 第一個標籤固定是 `群組/<群組名>`，
Obsidian 標籤面板可直接依群組篩選。

```
00-索引/            首頁、學習路徑、速查表

① 基礎概論      01-計算機概論/  02-計算機網路/          零基礎入門
② Linux         10-Linux基礎/   11-Linux伺服器管理/
③ Windows       20-Windows系統管理/
④ 網路與設備    30-網路基礎與設備/  31-機房與硬體管理/
⑤ 虛擬機與容器  40-虛擬化平台/  41-容器化/
⑥ 軟體與開發    50-常用工具/    51-Web伺服器/
                52-應用執行環境/ 53-資料庫與資料儲存/   ← 51 含 MyGuard/Angie 子章
⑦ 資訊安全      60-憑證與PKI/   61-資訊安全/            ← 61 含 TWGCB 子章
⑧ 系統維運      70-監控與日誌分析/  71-維運實務/
⑨ AI 人工智慧   80-AI服務/
⑩ 雲端與架構    82-雲端與架構/
⑪ 實務案例      85-專案部署實戰/                        ← LXMP 全套整合

90-附錄/  99-收件匣/
_範本/ _附件/ _設定檔範例/ _表單範本/ _工具/ _規劃/
```

**群組標籤對照**（`tags` 第一項）：

| 群組 | 標籤 | 章節 |
| --- | --- | --- |
| 基礎概論 | `群組/基礎概論` | 01、02 |
| Linux | `群組/Linux` | 10、11 |
| Windows | `群組/Windows` | 20 |
| 網路與設備 | `群組/網路與設備` | 30、31 |
| 虛擬機與容器 | `群組/虛擬機與容器` | 40、41 |
| 軟體與開發工具 | `群組/軟體與開發工具` | 50、51、52、53 |
| 資訊安全 | `群組/資訊安全` | 60、61 |
| 系統維運 | `群組/系統維運` | 70、71 |
| AI 人工智慧 | `群組/AI人工智慧` | 80 |
| 雲端與架構 | `群組/雲端與架構` | 82 |
| 實務案例 | `群組/實務案例` | 85 |
| 附錄 | `群組/附錄` | 90、99 |

> 2026-08-28 完成架構重整（原 12→50、20→30、22→31、30→40、31→41、
> 40→11、41→20、50→51、51→52、52→53、53→80、80→85，新增 82）。

## 撰寫規範

### Frontmatter（每篇必備）

```yaml
---
title: 檔案權限與擁有者
desc: rwx 權限模型…            # 一句話，索引表格自動抓這欄
aliases: [chmod, chown]
tags: [linux/基礎, 主題/權限]
category: Linux基礎
difficulty: 入門                # 入門 / 進階 / 專家
status: 待撰寫                  # 待撰寫 / 撰寫中 / 完成
distro: [ubuntu, rhel]
prerequisites: ["[[05-路徑導覽與檔案操作]]"]
updated: 2026-08-27
---
```

TWGCB 相關篇章另加 `baseline_version: TWGCB-01-014 v1.2`，記錄對應的基準編號與版本。

### 章節骨架（固定 13 段）

這篇你會學到 → 前置知識 → 觀念說明 → 安裝或基礎操作 → 進階應用 → 完整實戰範例
→ 常見錯誤與排錯 → 安全性注意事項 → 速查表 → 練習題 → **小測驗** → 延伸閱讀

### 小測驗（每篇必備，含未來所有新篇章）

- 位置：`## 練習題` 之後、`## 延伸閱讀` 之前
- **最多 10 題**，題目針對該篇的**關鍵細節與易錯觀念**（不是考記憶，是考理解）
- 題型混用：選擇、是非、簡答、「這行指令會發生什麼」
- 題目直接列在 `## 小測驗` 下（編號 Q1～Q10），答案集中放在**一個預設摺疊的**
  `> [!question]- 測驗答案` callout 內，每題附一到兩句解釋，並指回篇內對應段落
- 骨架階段留空白模板即可，撰寫內容時必須一併完成

### 內容原則

- **由淺至深**，每個指令都要附「輸入 → 預期輸出」
- **每篇都要有可照做的完整範例**，不能只有片段
- **常見錯誤與排錯**用表格：現象 / 原因 / 解法
- 長設定檔放 `_設定檔範例/`，內文只放關鍵片段並連結過去
- 未在實機驗證過的內容加 `> [!warning] 未實機驗證`

### 平台對照（雙主線寫法）

主線寫一種，另一種用**預設摺疊的 callout** 並列，不要拆成兩篇：

| 主題 | 主線 | 對照區塊 |
| --- | --- | --- |
| Linux | Ubuntu / Debian | `> [!info]- Rocky / AlmaLinux（RHEL 系）對照` |
| 交換器 | Cisco IOS | `> [!info]- Juniper JunOS 對照` |
| Windows | GUI 操作步驟 | PowerShell 指令並陳（不摺疊） |

### Callout

`[!abstract]` 學習目標 ／ `[!note]` 觀念 ／ `[!tip]` 實務建議 ／ `[!example]` 範例
／ `[!warning]` 注意 ／ `[!danger]` 不可逆操作 ／ `[!info]-` 平台對照（摺疊）
／ `[!question]-` 練習解答（摺疊）

### 其他硬規則

- 交叉引用一律 `[[檔名]]`，**不用相對路徑**
- 檔名格式 `NN-標題.md`，**全 vault 唯一**（wikilink 靠檔名解析，撞名會指錯）
  新增篇章請加主題前綴：`Cisco-`、`PVE-`、`GPO-`、`Nginx-`…
- 程式碼區塊一定標語言：`bash` `powershell` `nginx` `yaml` `ini` `sql` `php` `json` `dockerfile` `cisco`

## 工具

```bash
python3 _工具/重建索引.py          # 新增／改名／搬移筆記後必跑，重建索引表格
python3 _工具/重建索引.py --check  # 只檢查不寫入
python3 _工具/檢查連結.py          # 檢查斷掉的 wikilink，必須 0
python3 _工具/進度統計.py          # 各章撰寫進度
python3 _工具/新增筆記.py <資料夾> <標題> --kind {cmd|svc|guide|ref} [選項]
```

索引頁的「本章導覽」與「建議閱讀順序」是手寫的，重建時**會保留**；
只有「子分類」與「篇章列表」兩張表依 frontmatter 重新產生。

`--kind` 決定章節骨架：`cmd` 指令教學／`svc` 服務教學／`guide` 觀念與實戰／`ref` 速查頁。

## 工作流程

任何改動 vault 內容後，依序執行：

```bash
python3 _工具/重建索引.py
python3 _工具/檢查連結.py
git add -A && git commit -m "docs(<章節>): <做了什麼>"
```

**遠端**：`origin = https://github.com/Information-Study/Tutorial.git`。
**每完成一個章節（或一批筆記）commit 後必須 `git push`**。
認證走 gh CLI（`gh auth login` 後 `gh auth setup-git`）；
push 失敗時提醒使用者重新登入，不要略過。

提交訊息格式：

```
docs(nginx): 新增反向代理與負載平衡教學
docs(cisco): 補充 VLAN Trunk 設定範例
chore: B1 章節重編號搬遷
fix(連結): 修正 Laravel 部署章節的斷掉連結
```

## 撰寫內容時的注意事項

- **不要動索引頁的表格**，改 frontmatter 的 `desc` / `difficulty` 然後跑重建腳本
- 一篇寫完把 `status` 改成 `完成`、更新 `updated`
- 分批撰寫，一批一個 commit，不要一次改動大量檔案
- 新增章節時：建資料夾 → 從 `_範本/索引MOC範本.md` 複製索引頁並填好 `desc` 與導覽
  → 用 `新增筆記.py` 加教學文 → 跑重建索引（父層索引會自動出現這個子分類）

## 兩個需要背景知識的主題

### MyGuard（`deb.myguard.nl`）

**不是**端點防護代理。是 [myguard-labs](https://github.com/myguard-labs) 維護的第三方
Debian／Ubuntu APT 套件庫，提供**強化版 NGINX 與 Angie**：mainline、HTTP/3 (QUIC)、kTLS、
Brotli、Zstandard、ModSecurity v3、Lua／NJS，加上 100 多個動態模組，每日重建。

自行開發的模組（直接影響本手冊的 HTTPS／WAF／效能章節）：

| 模組 | 作用 |
| --- | --- |
| `autocert` | NGINX 內建 ACME 客戶端，`autocert on;` 就自動申請與續期，**不需 certbot 與 cron** |
| `http-shield` | 攔截 SQLi、Log4Shell、Shellshock、RCE 鏈等已知攻擊 |
| `error-abuse` | 對 404 濫用來源限流 |
| `sentinel` | 用戶端信譽評分與 AI 爬蟲 tarpit（實驗中） |
| `cache-turbo` | 共享記憶體邊緣快取、stale-while-revalidate |
| `strip-filter` | HTML／CSS／JS／JSON 回應體精簡 |
| `zstd` | Zstandard 壓縮 |

另有 OWASP CRS 外掛（wordpress-hardening、vaultwarden、vimbadmin）與每日重建的 Docker 映像。

> **範圍界線**：myguard-labs 的郵件相關套件（Mailstrix、rspamd 外掛、ViMbAdmin）
> **不寫入本手冊** — 已確定不納入郵件伺服器主題。

- **主教學位置**：`51-Web伺服器/04-MyGuard套件庫與Angie/`（8 篇）
- **套件庫加入方式的通用寫法**：`11-Linux伺服器管理/03-伺服器建置與標準化/03-第三方APT套件庫實務`
- 動筆前到 <https://deb.myguard.nl/how-to-use/> 確認當前套件庫路徑、金鑰與支援 codename

### TWGCB（台灣政府組態基準）

國家資通安全研究院（NICS）發布，行政院國家資通安全會報技術服務中心（NCCST）提供下載。
原則是**版本對應** — 不同 OS 版本各有專屬基準文件。

- **優先做 Linux 部分**（`61-資訊安全/12-TWGCB政府組態基準/` 第 01～08 篇）
- 必須同時提供**本機導入**與 **AD 網域導入**兩種方法
- Windows 與應用軟體基準（第 09 篇）先建佔位骨架，等使用者提供資料再彙整
- 已知 Linux 基準：TWGCB-01-014（Ubuntu 22.04 LTS v1.2）、TWGCB-01-008（RHEL 8 v1.3）、
  TWGCB-01-012（RHEL 9 伺服器 v1.2）
- **動筆前先到 <https://www.nccst.nat.gov.tw/GCB> 確認最新版本**，寫進 `baseline_version`
- 注意本手冊 Linux 主線版本比基準文件新，需說明版本不吻合時的對應原則

## 待確認事項

1. **TWGCB Windows／應用軟體基準**：等使用者提供資料
2. **實機環境**：Cisco／Juniper／PVE／OPNsense／Windows AD 是否有可驗證環境；沒有的話標註「未實機驗證」
3. **表單輸出格式**：巡檢表、盤點表要不要同時給 CSV／Excel

已排除的範圍：**郵件伺服器**（Postfix／Dovecot／rspamd／Mailstrix）— 使用者已決定不納入。

## 參考

- 完整規劃與篇章清單：`_規劃/手冊升級規劃.md`
- 使用者說明：`README.md`
- 手冊入口：`00-索引/00-首頁.md`
