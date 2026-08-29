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

**十三個群組資料夾**，群組內再分章節。每個群組有 `00-<群組>-總覽-索引.md`，
每個章節有一個 `-idx-` 索引頁。`重建索引.py` 會自動遞迴處理所有層級。

```
000-索引/                    首頁、學習路徑、速查表

010-基礎概論/      01-計算機概論  02-計算機網路
                   03-網路服務與通訊協定（規劃中，見規劃第十一節）
020-Linux/         01-Linux基礎  02-Linux伺服器管理
030-Windows/       01-Windows系統管理
040-網路與網路設備/ 01-網路基礎與設備  02-機房與硬體管理
050-虛擬機與容器/  01-虛擬化平台  02-容器化
060-軟體與開發工具/ 01-常用工具  02-Web伺服器  03-應用執行環境
                   04-資料庫與資料儲存               ← 02 含 MyGuard/Angie
070-系統及工具開發/ 01-前端基礎  02-Vue與Nuxt  03-PHP與Laravel
                   04-Python開發  05-Shell與PowerShell
                   06-自動化測試  07-n8n流程自動化
080-專案管理/      01-專案管理基礎  02-需求與規格管理
                   03-版本與發布管理  04-協作與知識管理
090-資訊安全/      01-憑證與PKI  02-系統與網路防護  03-應用與資料安全
                   04-WAF與ModSecurity  05-資安防護設備與軟體
                   06-TWGCB政府組態基準  07-資安實踐與規範
                   08-Wazuh資安監控
100-系統維運/      01-監控與日誌分析  02-維運實務
110-AI人工智慧/    01-AI服務基礎  02-Ollama  03-OpenWebUI  04-ComfyUI
                   05-AI輔助開發（規劃中，見規劃第十節）  ← Codex / Claude Code
120-雲端與架構/    01-雲端與架構
130-實務案例/      01-專案部署實戰                   ← LXMP 全套整合

980-附錄/  990-收件匣/
_範本/ _附件/ _設定檔範例/ _表單範本/ _工具/ _規劃/
```

**編號規則**：群組資料夾一律**三位數等距**（010、020…130），
間隔 10 讓日後插入新群組不必重編號；索引 `000`、附錄 `980`、收件匣 `990`。

**群組標籤**（`tags` 第一項固定為此）：

| 群組 | 標籤 |
| --- | --- |
| 基礎概論 | `群組/基礎概論` |
| Linux | `群組/Linux` |
| Windows | `群組/Windows` |
| 網路與設備 | `群組/網路與設備` |
| 虛擬機與容器 | `群組/虛擬機與容器` |
| 軟體與開發工具 | `群組/軟體與開發工具` |
| 系統及工具開發 | `群組/系統及工具開發` |
| 專案管理 | `群組/專案管理` |
| 資訊安全 | `群組/資訊安全` |
| 系統維運 | `群組/系統維運` |
| AI 人工智慧 | `群組/AI人工智慧` |
| 雲端與架構 | `群組/雲端與架構` |
| 實務案例 | `群組/實務案例` |
| 附錄／索引 | `群組/附錄`、`群組/索引` |

## 撰寫優先順序（使用者指定）

**最優先的五章，以 LXMP 全套整合為主軸**：

1. `40-軟體與開發工具/01-常用工具`（Git 含 **git-flow**、編輯器、監控、網路診斷、終端機、傳輸）
2. `40-軟體與開發工具/02-Web伺服器`（**Nginx / Apache2**、MyGuard/Angie）
3. `40-軟體與開發工具/03-應用執行環境`（**PHP-FPM**、**Node.js 與 PM2**、Python）
4. `70-資訊安全/01-憑證與PKI`（**申請憑證** + **自簽憑證鏈**）
5. `95-實務案例/01-專案部署實戰`（**LXMP 全套整合**）

**LXMP 定義（貫穿這五章的主軸）**：

```
Linux + (Nginx | Apache2) + MySQL + PHP
  + 前端：Vue / Nuxt（含「使用 PM2」與「不使用 PM2」兩種做法）
  + 後端：Laravel + Nova / Filament
  + SSL：自簽憑證鏈（含瀏覽器相容的 CN/SAN）與 向 CA 申請憑證
  + WAF：ModSecurity + OWASP CRS
  + 部署來源：【已開發完成、放在 GitHub 上的 git 專案】
```

**參考素材**（使用者提供，位於本機 scratchpad，非 vault 內）：
Wazuh 手冊（45 檔）、Wazuh TW-GCB SCA 政策（6 檔）、
n8n 手冊（15 檔）、地端 AI 手冊 OpenWebUI/Ollama/Qdrant/ComfyUI（47 檔）。

> 2026-08-28 完成第二次架構重整：改為十三群組資料夾分類，
> 新增 50-系統及工具開發、60-專案管理、70-資訊安全/03-Wazuh資安監控、
> 85-AI人工智慧/04-ComfyUI、50-系統及工具開發/07-n8n流程自動化。

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
prerequisites: ["[[020-01-05-cmd-Linux-路徑導覽與檔案操作]]"]
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
| 交換器 | **Juniper JunOS** | `> [!info]- Cisco IOS 對照` |
| Windows | GUI 操作步驟 | PowerShell 指令並陳（不摺疊） |

### Callout

`[!abstract]` 學習目標 ／ `[!note]` 觀念 ／ `[!tip]` 實務建議 ／ `[!example]` 範例
／ `[!warning]` 注意 ／ `[!danger]` 不可逆操作 ／ `[!info]-` 平台對照（摺疊）
／ `[!question]-` 練習解答（摺疊）

### 其他硬規則

- 交叉引用一律 `[[檔名]]`，**不用相對路徑**
- **檔名格式**（2026-08-29 改制完成，全 vault 已套用）：

  ```
  三層目錄： <群組3碼>-<章2碼>-<序2碼>-<類型>-<主題前綴>-<標題>.md
  四層目錄： <群組3碼>-<章2碼>-<子章2碼>-<序2碼>-<類型>-<主題前綴>-<標題>.md
  ```

  例：`010-02-03-guide-網概-網路分層模型.md`、`060-04-01-05-svc-MySQL-備份與還原.md`
  索引頁序號固定 `00`、類型固定 `idx`，如 `090-01-00-idx-PKI-憑證與PKI.md`。
  編號段數＝資料夾深度；**全 vault 檔名唯一**（wikilink 靠檔名解析，撞名會指錯）。
  ★★★ 新增篇章一律用 `_工具/新增筆記.py` 產生，不要手動命名。
- 程式碼區塊一定標語言：`bash` `powershell` `nginx` `yaml` `ini` `sql` `php` `json` `dockerfile` `cisco`

## 工具

```bash
python3 _工具/重建索引.py          # 新增／改名／搬移筆記後必跑，重建索引表格
python3 _工具/重建索引.py --check  # 只檢查不寫入
python3 _工具/檢查連結.py          # 檢查斷掉的 wikilink，必須 0
python3 _工具/進度統計.py          # 各章撰寫進度
python3 _工具/健檢.py              # ★ 一次跑完所有結構檢查（提交前建議跑）
python3 _工具/健檢.py --quiet      # 只顯示問題
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
- 新增章節時：建資料夾（依 `NN-名稱` 編號）→ 從 `_範本/索引MOC範本.md` 複製索引頁，
  依新命名規則改名為 `…-00-idx-<主題前綴>-<章節名>.md` 並填好 `desc` 與導覽
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
- 手冊入口：`000-索引/000-00-idx-索引-首頁.md`
