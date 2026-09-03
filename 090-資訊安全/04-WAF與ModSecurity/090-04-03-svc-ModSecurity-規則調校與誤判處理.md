---
title: "ModSecurity 規則調校與誤判處理"
desc: "四階段導入節奏、誤判與真攻擊的判別、精準排除規則的正確寫法，以及日誌統計找誤判的方法"
aliases: [exclusion, false positive, 誤判, 調校]
tags: [群組/資訊安全, 安全/waf, 主題/調校]
category: WAF與ModSecurity
difficulty: 專家
status: 完成
distro: [ubuntu, rhel]
prerequisites: ["[[090-04-02-guide-OWASP-CRS規則集]]"]
updated: 2026-09-03
---

# ModSecurity 規則調校與誤判處理

> [!abstract] 這篇你會學到
> - ★★★★★ **為什麼誤判是 WAF 導入失敗的頭號原因**，以及怎麼避免那個結局
> - 四階段導入節奏，每階段的**進入條件與退出條件**
> - 怎麼判斷一筆命中是誤判還是真攻擊
> - ★★★★★ 誤判排除的**正確做法與錯誤做法**，含完整規則範本
> - 常見誤判來源：富文字編輯器、檔案上傳、JSON API、特殊字元密碼、中文編碼
> - 用 `grep` / `awk` 從稽核日誌統計最常命中的規則 —— **找誤判最快的方法**
> - 效能與日誌量的控制
> - 一整套「後台編輯器系統導入 WAF」的完整流程，從觀察到切 `On`

---

## 這篇你會學到

這是本章**最重要的一篇**。前兩篇教你把 WAF 裝好、把規則掛上，
但決定這個 WAF 半年後還活著、還是躺在 `SecRuleEngine Off` 的，是這一篇。

| # | 目標 | 重要度 |
| --- | --- | --- |
| 1 | 說清楚為什麼「先擋再說」一定會失敗 | ★★★★★ |
| 2 | 訂出一份有進入／退出條件的導入計畫 | ★★★★★ |
| 3 | 拿到一筆命中，能在五分鐘內判斷是誤判還是攻擊 | ★★★★ |
| 4 | 寫出範圍最小、可審核、可回退的排除規則 | ★★★★★ |
| 5 | 認得五大類誤判來源，上線前就先預期到 | ★★★★ |
| 6 | 用三條指令從幾萬行日誌裡撈出誤判排行 | ★★★★★ |
| 7 | 控制稽核日誌的量與效能開銷 | ★★★ |
| 8 | 帶著證據跟主管說「現在可以切 On 了」 | ★★★★★ |

---

## 前置知識

- ✅ 已完成 [[090-04-01-svc-WAF-WAF概念與ModSecurity安裝]]（引擎裝好，日誌寫得出來）
- ✅ 已完成 [[090-04-02-guide-OWASP-CRS規則集]]，特別是：
  - ★★★★★ **異常評分機制**：命中不等於阻擋
  - ★★★★★ **三種排除寫法**的影響範圍差異與 Include 順序
  - 規則 ID 號段對照
- ✅ `SecAuditLogParts` 含 `H` 段（沒有的話本篇所有方法都做不了）
- ✅ 基本的 `grep`、`awk`、`sort`、`uniq` 使用 —— 見 `020-01` 群組
- ✅ 對這個站台的業務有基本了解：哪些是後台、哪些會上傳檔案、哪些是 API

> [!warning] ★★★★★ 開始前的三項確認
> ```bash
> grep '^SecRuleEngine'    /etc/nginx/modsec/modsecurity.conf
> grep '^SecAuditLogParts' /etc/nginx/modsec/modsecurity.conf
> grep '^SecAuditEngine'   /etc/nginx/modsec/modsecurity.conf
> ```
> ```text
> SecRuleEngine DetectionOnly
> SecAuditLogParts ABIJDEFHZ
> SecAuditEngine RelevantOnly
> ```
> 三項有任何一項不對，本篇的方法都無法進行。

---

## 觀念說明

### ★★★★★ 誤判是 WAF 導入失敗的頭號原因

先看一個機關裡真實會發生的劇本：

```text
週一 09:00  資訊室完成 WAF 安裝，設定 SecRuleEngine On、CRS PL2
週一 09:30  人事室反映「線上請假系統送不出去」
週一 10:15  秘書室反映「公文系統上傳附件會出錯」
週一 11:00  ★ 有位同仁姓「歐陽」，英文姓名欄填 O'Brien，登入被擋
週一 13:40  網頁小組反映「後台文章存不了，一按儲存就跳 403」
週一 14:20  累積 17 通客訴電話，科長要求「先解決再說」
週一 14:25  SecRuleEngine 改成 Off
週一 14:26  所有問題消失
週二 起     再也沒有人提起 WAF 這件事

三年後的資安稽核：「貴單位 WAF 已建置」——
              實際狀態：SecRuleEngine Off，從未提供任何防護
```

> [!danger] ★★★★★ 這個劇本的每一步都不是技術問題
> 安裝沒錯、規則沒錯、CRS 也沒錯。**錯的是導入節奏。**
>
> WAF 導入的真正工作量分布是：
>
> | 工作 | 佔比 |
> | --- | --- |
> | 安裝設定 | ★ 約 10% |
> | 掛上 CRS | ★ 約 5% |
> | **誤判調校** | ★★★★★ **約 80%** |
> | 切換到阻擋模式 | 約 5% |
>
> 只準備 15% 的時間就想上線，結局必然是上面那個劇本。
> **導入計畫書裡如果沒有「兩週觀察期」這一項，這個計畫就是錯的。**

### 為什麼誤判必然會發生 ★★★★

CRS 的規則是**通用**的 —— 它不認識你的應用，只認得「長得像攻擊的字串」。

| WAF 看到 | WAF 的判斷 | 實際是 |
| --- | --- | --- |
| `content=<p>公告</p><img src="a.jpg">` | XSS 攻擊 | ★★★★★ 後台編輯器的正常內容 |
| `name=O'Brien` | SQL Injection | 一個愛爾蘭姓氏 |
| `password=P@ss'--word` | SQL Injection | 一個好密碼 |
| `path=/uploads/2026/報告.pdf` | 路徑穿越 | 檔案下載連結 |
| `callback=https://partner.example.gov.tw/cb` | 遠端檔案引入 | OAuth 回呼網址 |
| `keyword=select 相關法規` | SQL Injection | 中文搜尋（含英文字 select）|
| `remark=請將資料 cat 起來後彙整` | 遠端指令執行 | 一段中文備註（含 `cat`）|

> [!note] ★★★★ 這不是 CRS 的 bug
> 從純文字的角度，`<script>` 就是 `<script>`，WAF 無從得知
> 「這個欄位在你的系統裡本來就允許 HTML」。
> **告訴 WAF 這件事，就是「調校」的定義。**

### 誤判的真正代價 ★★★★★

| 代價 | 說明 |
| --- | --- |
| 直接的服務中斷 | 使用者做不了事，等同系統故障 |
| ★★★★★ **信任崩潰** | 一次大規模誤判，之後兩年沒人願意再讓你碰 WAF |
| 被關掉 = 防護歸零 | 最終的資安風險**比沒裝之前更高**（因為以為有保護） |
| 稽核造假 | 報告寫「已建置」，實際 `SecRuleEngine Off` |
| 掩蓋真攻擊 | 誤判太多 → 日誌沒人看 → 真的攻擊淹沒在雜訊裡 ★★★★★ |

> [!danger] ★★★★★ 最危險的不是被關掉，是「開著但沒人看」
> 一天一萬筆誤判紀錄的 WAF，跟關掉的 WAF 在偵測能力上沒有差別 ——
> 因為沒有人會去看那一萬筆。真正的攻擊就藏在裡面。
>
> **調校的目標不只是「不擋到人」，更是「讓日誌回到人類可以閱讀的量」。**
> 一個健康的 WAF，日誌應該是**每天十幾筆到幾十筆**，
> 每一筆都值得看一眼。

---

## 安裝或基礎操作

### ★★★★★ 四階段導入節奏（本篇骨幹）

```text
┌─ 階段一 ─────────────────────────────────────────┐
│ DetectionOnly + PL1 ，什麼都不擋                   │
│ 至少兩週（跨過月初月底與各種週期性作業）              │
└───────────────┬─────────────────────────────────┘
                │ 退出條件：蒐集到足夠涵蓋所有業務情境的日誌
                ▼
┌─ 階段二 ─────────────────────────────────────────┐
│ 分析日誌，找出誤判並逐一寫排除規則                    │
│ 仍然 DetectionOnly                                │
└───────────────┬─────────────────────────────────┘
                │ 退出條件：連續 5 個工作日 0 筆誤判
                ▼
┌─ 階段三 ─────────────────────────────────────────┐
│ 對「單一低風險站台」切 SecRuleEngine On             │
│ 在低流量時段執行，回退方案就緒                        │
└───────────────┬─────────────────────────────────┘
                │ 退出條件：兩週零客訴、零非預期 403
                ▼
┌─ 階段四 ─────────────────────────────────────────┐
│ 逐站台擴大，每站台重跑階段一到三                      │
└─────────────────────────────────────────────────┘
```

---

#### 階段一：DetectionOnly 觀察期 ★★★★★

**目的**：在**完全不影響使用者**的前提下，蒐集「這個站台的正常流量長什麼樣」。

| 項目 | 內容 |
| --- | --- |
| **進入條件** | ① 引擎裝好且 `nginx -t` 通過 ② CRS 已載入 ③ `SecRuleEngine DetectionOnly` ④ `PL1` ⑤ 稽核日誌可寫且有 logrotate ⑥ 已通知業務單位（不會有任何影響，但要留紀錄）|
| **時間** | ★★★★★ **至少兩週**，且必須涵蓋月初、月底 |
| **期間做什麼** | 每天看一次日誌量趨勢；不要做任何排除；不要改 PL |
| **退出條件** | ① 已滿兩週 ② 涵蓋所有主要業務情境（可用清單逐項確認）③ 日誌量穩定（不再每天冒出全新的規則 ID）|

> [!danger] ★★★★★ 觀察期不能只跑三天
> 機關系統有強烈的**週期性**：
>
> | 週期 | 會出現的特殊操作 |
> | --- | --- |
> | 每日 | 一般查詢、送公文 |
> | 每週 | 週報上傳、例行會議資料 |
> | ★ 月初 | 上月結算、報表匯出、大量檔案上傳 |
> | ★ 月底 | 請款、核銷、批次作業 |
> | 每季／年度 | 統計報表、預算作業、大量匯入 |
>
> 只跑三天，你只會看到「每日」那一列的誤判。
> 兩週後切 `On`，**月底那一批誤判會在你毫無準備時炸開**。
>
> 如果能跑一個完整月份（跨月初月底）更好。

**觀察期的每日檢查**（三條指令，五分鐘）：

```bash
# 1) 今天累積多少筆稽核紀錄
sudo grep -c '^---.*---A--' /var/log/nginx/modsec_audit.log

# 2) 今天有沒有出現「新的」規則 ID
sudo grep -oP '\[id "\K[0-9]+' /var/log/nginx/modsec_audit.log \
  | sort -u > /tmp/ids-today.txt
diff /tmp/ids-yesterday.txt /tmp/ids-today.txt
cp /tmp/ids-today.txt /tmp/ids-yesterday.txt

# 3) 有多少筆「如果切 On 就會被擋」
sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
```

★★★★★ **第 3 條是給主管看的數字**：
「如果現在切 On，今天會有 N 個請求被擋。」

> [!tip] ★★★★ 用一張表追蹤觀察期
> | 日期 | 稽核筆數 | 會被擋筆數 | 新規則 ID | 備註 |
> | --- | --- | --- | --- | --- |
> | 09/03 | 1,240 | 187 | 12 個 | 開始 |
> | 09/04 | 1,180 | 165 | 2 個 | |
> | 09/10 | 1,090 | 152 | 0 個 | 趨於穩定 |
> | 09/30 | 2,850 | 410 | ★ 5 個 | **月底批次作業** |
>
> 「新規則 ID 連續五天為 0」是階段一可以結束的重要訊號。
> 月底那一列說明了為什麼不能只跑三天。

---

#### 階段二：分析與排除 ★★★★★

**目的**：把誤判逐一處理掉，讓「會被擋的請求數」降到零。

| 項目 | 內容 |
| --- | --- |
| **進入條件** | 階段一退出條件全部滿足 |
| **仍然是** | ★★★★★ `SecRuleEngine DetectionOnly` —— 這個階段不切 On |
| **做什麼** | ① 統計規則命中排行 ② 逐條判斷誤判／真攻擊 ③ 為誤判寫精準排除 ④ 每寫一條就驗證 |
| **退出條件** | ★★★★★ **連續 5 個工作日，`Anomaly Score Exceeded` 的請求裡沒有任何一筆是正常業務** |

工作方式是**排行榜逐條攻破**：處理前五名，重新統計，再處理前五名。
因為誤判分布通常極度不均 —— 前三名往往佔掉 80% 以上的量。

> [!warning] ★★★★ 「排除數量」不是越少越好，也不是越多越好
> - 排除規則只有兩三條 → 通常代表觀察期不夠長，還有誤判沒發現
> - 排除規則超過三、四十條 → 通常代表你用了太粗的寫法，或該考慮這個應用是否適合上 WAF
>
> 一個典型的機關網站，調校完成後大約會有 **5～20 條**排除規則。

---

#### 階段三：切換到 On ★★★★★

| 項目 | 內容 |
| --- | --- |
| **進入條件** | ① 階段二退出條件滿足 ② 已備妥**一分鐘內可執行的回退指令** ③ 已通知業務單位切換時間與回報管道 ④ 選在**低流量時段**（機關通常是下班後或週五下午）⑤ ★ 選的是**單一、低風險**站台，不是全部一起切 |
| **切換動作** | 改 `SecRuleEngine On` → `nginx -t` → `reload` |
| **切換後 30 分鐘** | 盯著 403 的數量與日誌 |
| **退出條件** | ★★★★ 連續兩週：零客訴、零非預期 403 |

**回退指令要先寫好貼在牆上** ★★★★★：

```bash
# === WAF 緊急回退（30 秒內完成）===
sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine DetectionOnly/' \
     /etc/nginx/modsec/modsecurity.conf
sudo nginx -t && sudo systemctl reload nginx
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

> [!danger] ★★★★★ 不要在週五下班前切，然後就下班
> 也不要在連假前切。切換後至少要有一個工作日的完整觀察，
> 而且切換的人要在場。
>
> 更不要「趁大家都在放假沒人用」切換 —— 那樣你觀察不到任何東西，
> 收假第一天才會一次爆開。

**切換後的即時監控**：

```bash
# 每 10 秒印出最近的 403 數量
watch -n 10 "sudo tail -n 2000 /var/log/nginx/access.log \
  | awk '\$9==403' | wc -l"
```

```bash
# 即時看被擋的請求是哪些
sudo tail -f /var/log/nginx/modsec_audit.log \
  | grep --line-buffered -E 'Anomaly Score Exceeded|\[uri '
```

---

#### 階段四：逐步擴大 ★★★★

| 項目 | 內容 |
| --- | --- |
| **進入條件** | 第一個站台階段三退出條件滿足 |
| **做什麼** | 下一個站台**從階段一重新開始**（不能直接套用前一個站台的排除規則就切 On）|
| **順序建議** | 低風險 → 中風險 → 核心業務系統 |
| **注意** | ★★★★ 排除規則要分檔管理，一個站台一個檔，不要全部混在一起 |

```text
/etc/nginx/modsec/exclusions/
├── 00-common.conf              ← 全站共用
├── 10-www.conf                 ← 官網
├── 20-doc-system.conf          ← 公文系統
├── 30-hr-system.conf           ← 人事系統
└── 40-api.conf                 ← API
```

> [!warning] ★★★★ 不要把 A 站台的排除規則套用到 B 站台
> 「反正都是我們的系統」是一個危險的假設。
> A 站台的 `/admin/save` 需要放行 HTML，不代表 B 站台的 `/admin/save` 也需要。
> **每個排除規則都要有它自己的證據（來自那個站台的日誌）。**

---

### ★★★★ 怎麼判斷是誤判還是真攻擊

拿到一筆命中，依序看這五件事。

#### 判斷點 1：命中了哪個規則、哪個欄位 ★★★★

```text
[id "942xxx"] [msg "SQL Injection Attack Detected via libinjection"]
[data "Matched Data: 1' OR '1'='1 found within ARGS:id: 1' OR '1'='1"]
[uri "/product/detail"]
```

**`data` 欄位裡的實際內容是最直接的證據。**

| `data` 內容 | 判斷 |
| --- | --- |
| `1' OR '1'='1`、`UNION SELECT`、`; cat /etc/passwd` | ★★★★★ 這不會是正常輸入 → **真攻擊** |
| `<p>本府公告</p>`、`O'Brien`、`/uploads/2026/報告.pdf` | ★★★★ 一看就是業務內容 → **誤判** |
| `select`（單獨一個字）出現在搜尋框 | 可能是誤判，需再看其他判斷點 |

#### 判斷點 2：來源 IP 與行為模式 ★★★★

```bash
# 這個 IP 一共命中幾次？
sudo grep -c '192.0.2.55' /var/log/nginx/modsec_audit.log

# 這個 IP 打了哪些 URI？
sudo grep -A5 '192.0.2.55' /var/log/nginx/modsec_audit.log \
  | grep -oP '\[uri "\K[^"]+' | sort | uniq -c | sort -rn
```

| 模式 | 判斷 |
| --- | --- |
| 單一內網 IP、只打**一個** URI、每天固定幾次 | ★★★★ 極可能是誤判（某位同仁的日常作業）|
| 外部 IP、短時間打**幾十個不同** URI、payload 一直變形 | ★★★★★ **掃描或攻擊** |
| 大量不同外部 IP、同一個 payload | 自動化攻擊 |
| 內網 IP、命中的是掃描器偵測規則 | ★★★ 可能是排定的弱點掃描作業 |

#### 判斷點 3：時間分布 ★★★

```bash
sudo grep -oP '^\[\K[0-9]{2}/[A-Za-z]{3}/[0-9]{4}:[0-9]{2}' \
  /var/log/nginx/modsec_audit.log | sort | uniq -c
```

| 分布 | 判斷 |
| --- | --- |
| 集中在上班時間 08:00～17:00 | ★★★★ 傾向誤判（是同仁在用系統）|
| 凌晨 03:00 的密集爆發 | ★★★★ 傾向攻擊 |
| 每月 1 號集中出現 | ★★★★ 月結批次作業的誤判 |

#### 判斷點 4：★★★★★ 問開發或廠商

這是最有效但最常被跳過的一步。**問這三個問題**：

> 1. 「`/admin/article/save` 這支 API 的 `content` 參數，
>    **本來就會有 HTML 標籤嗎**？」
> 2. 「使用者送出的內容裡出現 `<img src=...>` 是**正常業務**嗎？」
> 3. 「這個欄位在存進資料庫之前，你們有做**輸出編碼／輸入驗證**嗎？」

| 回答 | 你該做什麼 |
| --- | --- |
| 「對，那是富文字編輯器，本來就有 HTML」 | ★★★★ 誤判，寫精準排除 |
| 「不對，那個欄位只該收數字」 | ★★★★★ **這是真攻擊，而且應用有輸入驗證缺陷** —— 一併通報要求修正 |
| 「我不知道，那是三年前離職的同事寫的」 | ★★★ 保守處理：先精準排除，同時列入應用改善清單 |

> [!warning] ★★★★★ 第三個問題的答案決定了排除的風險
> 如果應用**本身有做輸出編碼**，那麼放行 HTML 進來是安全的（存進去也不會執行）。
> 如果應用**沒有做**，你的排除規則等於幫攻擊者開了一條路。
>
> 這種情況下正確的做法是：**排除規則加上更嚴格的前置條件**
> （限定登入後的管理員路徑、限定來源 IP 為內網），
> 並把「應用需補上輸出編碼」寫進改善追蹤 ——
> 見 [[090-03-02-guide-應用安全-應用層安全]]。

#### 判斷點 5：復現 ★★★★

最終確認：請使用者當著你的面重做一次那個操作，同時 `tail -f` 日誌。

```bash
sudo tail -f /var/log/nginx/modsec_audit.log | grep --line-buffered '\[id "'
```

看到命中訊息在使用者按下按鈕的同一秒出現 → **確定是誤判**。

---

### ★★★★★ 誤判排除：錯誤做法與正確做法

#### ❌ 四種錯誤做法

| # | 錯誤做法 | 為什麼錯 | 危險度 |
| --- | --- | --- | --- |
| 1 | 把 `SecRuleEngine` 改成 `Off` | 防護歸零，而且通常再也不會改回來 | ★★★★★ |
| 2 | 把 `inbound_anomaly_score_threshold` 從 5 調到 50 | 全站所有攻擊都不會被擋，等同關閉 | ★★★★★ |
| 3 | 把 PL 從 1 降到「更低」（或關掉整個規則檔） | 大面積削弱，而且解決不了真正的問題參數 | ★★★★ |
| 4 | `SecRuleRemoveById` / `SecRuleRemoveByTag` 全站關規則 | 為了一個後台頁面，讓整個站台失去該類保護 | ★★★★★ |

> [!danger] ★★★★★ 這四種做法的共同特徵
> **它們都是「降低整體防護」來換取「解決一個局部問題」。**
>
> 判斷一個排除做法對不對，只要問一句：
> 「這樣改，**除了那個誤判的頁面之外**，還有哪些地方的保護被拿掉了？」
> 答案如果是「全站」，就是錯的做法。

#### ✅ 正確做法：URI + 參數 + 規則 ID 三重限定

```apache
# 放在 crs-exclusions-before.conf（★★★★★ 必須在 CRS 規則之前）
SecRule REQUEST_URI "@beginsWith /admin/article/save" \
    "id:1100001,\
     phase:2,\
     pass,\
     nolog,\
     ctl:ruleRemoveTargetById=<從日誌抄來的規則ID>;ARGS:content"
```

三重限定的意義：

```text
只有這個 URI  ×  只有這個參數  ×  只有這條規則  ──▶ 才放行

其他 URI 的 content 參數      → 仍受保護 ✅
這個 URI 的其他參數           → 仍受保護 ✅
這個參數的其他規則（SQLi 等）  → 仍受保護 ✅
```

> [!warning] ★★★★★ 規則 ID 一定要從自己的日誌抄
> 本篇刻意不寫任何具體的 CRS 規則 ID。
> 抄別人文章裡的 ID，很可能跟你安裝的 CRS 版本對不上 ——
> 結果是排除規則寫了、以為處理完了，**誤判照樣發生**。
>
> 取得 ID 的正確方式：
> ```bash
> sudo grep -B2 -A2 '/admin/article/save' /var/log/nginx/modsec_audit.log \
>   | grep -oP '\[id "\K[0-9]+' | sort | uniq -c | sort -rn
> ```

#### 排除規則範本庫 ★★★★

以下每一個都是可以直接改用的骨架。`<ID>` 一律替換成你日誌裡的真實 ID。

**範本 A：單一 URI 的單一參數，排除單一規則**（最常用 ★★★★★）

```apache
# 放 crs-exclusions-before.conf
# 用途：後台編輯器儲存 HTML
SecRule REQUEST_URI "@beginsWith /admin/article/save" \
    "id:1100001,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=<ID>;ARGS:content"
```

**範本 B：一個 URI、一個參數、排除多條規則** ★★★★

`ctl:` 每次只能處理一條規則，所以用**串接**的方式：

```apache
SecRule REQUEST_URI "@beginsWith /admin/article/save" \
    "id:1100002,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=<ID1>;ARGS:content,\
     ctl:ruleRemoveTargetById=<ID2>;ARGS:content,\
     ctl:ruleRemoveTargetById=<ID3>;ARGS:content"
```

**範本 C：整類規則的排除（用 tag）** ★★★

當同一個參數命中十幾條 XSS 規則，一條條列太累：

```apache
SecRule REQUEST_URI "@beginsWith /admin/article/save" \
    "id:1100003,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetByTag=attack-xss;ARGS:content"
```

> [!warning] ★★★★ 用 tag 排除要格外小心
> 這等於「這個 URI 的 `content` 參數完全不做 XSS 檢查」。
> 只有在確認**應用本身有做輸出編碼**時才可以這樣寫，
> 而且務必在註解裡寫清楚這個前提。

**範本 D：正規表示式比對多個 URI** ★★★

```apache
SecRule REQUEST_URI "@rx ^/admin/(article|news|announcement)/save" \
    "id:1100004,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=<ID>;ARGS:content"
```

**範本 E：多重條件（URI + 方法 + 內網來源）** ★★★★★

風險最低的寫法 —— 加上更多限定條件：

```apache
SecRule REQUEST_URI "@beginsWith /admin/article/save" \
    "id:1100005,phase:2,pass,nolog,chain"
    SecRule REQUEST_METHOD "@streq POST" "chain"
        SecRule REMOTE_ADDR "@ipMatch 10.20.0.0/16" \
            "ctl:ruleRemoveTargetById=<ID>;ARGS:content"
```

意思是：**只有從內網、用 POST、打這個 URI 時**才放行。
外部來源打同一個 URI 仍然完整受保護。

**範本 F：JSON API 的巢狀欄位** ★★★

JSON 解析後的欄位在 ModSecurity 裡以 `ARGS:` 加上路徑表示：

```apache
SecRule REQUEST_URI "@beginsWith /api/v1/posts" \
    "id:1100006,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=<ID>;ARGS:json.body"
```

> [!warning] 未實機驗證
> JSON 欄位的變數命名方式（`ARGS:json.body` 還是其他形式）
> **依 ModSecurity 版本與 JSON 解析器實作而異**。
> 正確做法：先發一個測試請求，從稽核日誌的 `data` 欄位看
> 「found within **ARGS:xxx**」裡的 `xxx` 實際長什麼樣，照抄。

**範本 G：整條路徑完全不過 WAF（最後手段）** ★★★★★

```apache
# ★★★★★ 極危險，只用於「確定不接受使用者輸入」的內部端點
SecRule REQUEST_URI "@streq /internal/webhook/receipt" \
    "id:1100099,phase:1,pass,nolog,\
     ctl:ruleEngine=Off"
```

> [!danger] ★★★★★ 用這條之前先回答三個問題
> 1. 這個端點有沒有 IP 白名單保護？
> 2. 有沒有簽章／token 驗證？
> 3. 如果被打進來，最壞會發生什麼事？
>
> 三個問題答不出來就不要用這條。
> 這是 WAF 上的一個永久破口，而且日後沒人會記得它的存在。

#### 排除規則的必要註解格式 ★★★★★

```apache
# ===============================================================
# ID       : 1100001
# 建立日期  : 2026-09-03
# 站台      : doc.example.gov.tw（公文系統）
# 症狀      : 後台編輯公文內容按儲存 → 403
# 誤判來源  : 富文字編輯器送出 HTML，被 XSS 規則判定為攻擊
# 影響 URI  : /admin/article/save
# 影響參數  : ARGS:content
# 排除規則  : <ID>（來源：2026-08-20~09-02 稽核日誌統計）
# 前提確認  : 已與廠商確認該欄位輸出時有做 HTML 編碼（郵件 2026-08-28）
# 申請      : 資訊室 王小明
# 核可      : 資安承辦 李大華 2026-09-02
# 複核日期  : 2027-03-01（系統改版後需重新評估此排除是否仍必要）
# ===============================================================
SecRule REQUEST_URI "@beginsWith /admin/article/save" \
    "id:1100001,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=<ID>;ARGS:content"
```

> [!tip] ★★★★★ 註解不是形式主義
> 兩年後有人問「這條為什麼在這裡？可以刪嗎？」——
> 沒有註解的答案永遠是「不知道，不敢動」，那個破口就永遠留著。
> **有註解的排除規則才是可管理的資產。**

---

### ★★★★ 五大常見誤判來源

#### 1. ★★★★★ 後台富文字編輯器

**症狀**：後台編輯文章、公告、公文內容，按儲存跳 403。

**原因**：編輯器送出的是 HTML（`<p>`、`<img>`、`<a href>`、有時還有 `onclick`），
XSS 規則看到就命中，而且通常一次命中好幾條，分數輕鬆破 20。

**排除**：範本 A 或 C，限定後台儲存的 URI 與內容參數。

**額外確認**：★★★★★ 一定要問清楚應用有沒有做輸出編碼。
如果沒有，這個系統本身就有儲存型 XSS 風險，排除規則會讓風險實現。

#### 2. ★★★★ 檔案上傳

**症狀**：上傳附件失敗，或上傳大檔時 413。

**多重原因**：

| 原因 | 徵狀 | 解法 |
| --- | --- | --- |
| `SecRequestBodyLimit` 太小 | 413，日誌有 body limit 訊息 | 調大 limit，**維持 `Reject`** ★★★★ |
| 檔名含中文或特殊字元 | 命中協定或 LFI 規則 | 針對上傳 URI 排除 `FILES_NAMES` |
| 檔案內容含攻擊特徵字串 | 命中 SQLi/XSS 規則 | ★★★ 常見於上傳 `.sql`、`.csv`、含程式碼的文件 |
| 副檔名在限制清單 | 命中副檔名限制規則 | 調整 `tx.restricted_extensions` |
| multipart 格式規則 | 命中 multipart 相關規則 | 檢查前端送出的 multipart 是否標準 |

```apache
# 上傳頁面：放寬檔名與檔案內容的檢查
SecRule REQUEST_URI "@beginsWith /doc/attachment/upload" \
    "id:1100010,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=<ID>;FILES_NAMES,\
     ctl:requestBodyAccess=On"
```

> [!warning] ★★★★★ 上傳功能不要用 `ctl:ruleEngine=Off` 解決
> 檔案上傳是 **web shell 植入的主要途徑**，
> 把整個上傳路徑排除在 WAF 之外，等於把最危險的入口打開。
> 一定要逐項排除具體的規則，並確認應用端有做副檔名白名單與存放目錄不可執行。

#### 3. ★★★★ JSON API

**症狀**：整個 API 全部 403，或特定欄位的請求失敗。

**三個層次的原因**：

| 層次 | 檢查 |
| --- | --- |
| Content-Type 不在允許清單 | ★★★★★ `tx.allowed_request_content_type` 要有 `application/json` |
| HTTP 方法不在允許清單 | ★★★★ `tx.allowed_methods` 要有 `PUT`、`PATCH`、`DELETE`、`OPTIONS` |
| 某個欄位的內容誤判 | 針對該 URI 的該 JSON 欄位排除 |

> [!danger] ★★★★★ API 站台切 On 之前一定要先測這兩項
> Content-Type 與方法這兩關卡在最前面，
> 一旦沒設對，**症狀不是「零星誤判」而是「整個 API 全掛」**。
> 而 API 掛掉通常是前端整個白畫面，比 403 頁面更難第一時間診斷。

#### 4. ★★★★ 含特殊字元的密碼與姓名

**症狀**：某些使用者永遠登入不了，某些人的資料存不進去。

**原因**：

| 輸入 | 命中 |
| --- | --- |
| `P@ss'word` | SQLi（撇號）|
| `myPass--2026` | SQLi（`--` 是 SQL 註解）|
| `O'Brien`、`D'Angelo` | SQLi |
| `<Ken>` 之類的暱稱 | XSS |

```apache
# 登入表單：密碼欄位不做注入檢查
# 前提：後端使用參數化查詢並對密碼做雜湊（已與廠商確認）
SecRule REQUEST_URI "@streq /auth/login" \
    "id:1100020,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetByTag=attack-sqli;ARGS:password"
```

> [!warning] ★★★★ 排除密碼欄位是**合理**的，但要有前提
> 密碼欄位本來就該接受任意字元，而且後端一定會雜湊而非直接拼進 SQL。
> 所以排除它是**正確的**設計決策，不是妥協。
>
> 但前提是：**確認後端真的用參數化查詢**。
> 如果那是一套把密碼直接串進 SQL 的老系統，排除規則就是幫攻擊者開門 ——
> 這時該做的是要求修正應用，而不是調 WAF。

#### 5. ★★★★★ 中文內容的編碼問題

這是台灣機關環境**特有且最容易被忽略**的一類。

| 情境 | 現象 |
| --- | --- |
| 中文以 UTF-8 URL 編碼送出 | 一個中文字變成 `%E5%85%AC` 三組百分號序列 |
| ★★★★ 舊系統用 Big5 編碼 | 位元組序列可能剛好落在 CRS 認為可疑的範圍 |
| 雙重編碼 | 前端已編碼一次，框架又編一次 → 命中「多重編碼」類規則 |
| 中文夾雜英文關鍵字 | 「請 select 適當選項」→ 命中 SQLi 規則 |
| 中文檔名上傳 | 「113年度預算表.xlsx」→ 檔名規則誤判 |

**診斷方法** ★★★★：

```bash
# 從日誌把命中的實際內容抓出來看
sudo grep -oP 'Matched Data: \K[^ ]+' /var/log/nginx/modsec_audit.log \
  | sort | uniq -c | sort -rn | head -20
```

如果看到大量 `%E5%`、`%E6%`、`%E7%` 開頭的序列，就是中文編碼相關。

> [!warning] ★★★★ 先確認全鏈路都是 UTF-8
> 中文編碼誤判有相當比例其實是**應用本身的編碼設定問題**：
> 資料庫是 Big5、頁面宣告 UTF-8、表單沒設 `accept-charset`。
> 先把編碼統一成 UTF-8，很多誤判會自然消失 ——
> 這比寫一堆排除規則正確得多。

> [!info]- Apache 對照：排除規則放哪
> Apache 的排除規則寫法與 Nginx **完全相同**，差別只在檔案位置與載入方式：
>
> ```apache
> # /etc/apache2/mods-enabled/security2.conf
> <IfModule security2_module>
>     IncludeOptional /etc/modsecurity/modsecurity.conf
>     IncludeOptional /etc/modsecurity/crs-setup.conf
>     IncludeOptional /etc/modsecurity/exclusions-before/*.conf
>     IncludeOptional /usr/share/modsecurity-crs/rules/*.conf
>     IncludeOptional /etc/modsecurity/exclusions-after/*.conf
> </IfModule>
> ```
>
> ★★★★ Apache 額外的一個好處是可以用 `<Location>` 區塊，
> 語意上比 `SecRule REQUEST_URI` 更清楚：
>
> ```apache
> <Location "/admin/article/save">
>     SecRuleUpdateTargetById <ID> "!ARGS:content"
> </Location>
> ```
>
> ★★★★ 注意：ModSecurity 指令**不能**寫在 `.htaccess` 裡。
> 見 [[060-02-03-04-guide-Apache-htaccess與Rewrite]]
> 與 [[060-02-03-07-guide-Apache-安全與效能]]。

---

## 進階應用

### ★★★★★ 日誌分析：三條指令找出誤判

這一節是全篇實務價值最高的部分。

#### 第一步：規則命中排行 ★★★★★

```bash
sudo grep -oP '\[id "\K[0-9]+' /var/log/nginx/modsec_audit.log \
  | sort | uniq -c | sort -rn | head -15
```

```text
   4821 942xxx
   3980 941xxx
   2210 949110
   1877 980130
    645 932xxx
    312 920xxx
    108 913xxx
```

★★★★★ **從第一名開始處理。** 誤判分布極度不均，
處理掉前三名通常就消掉 80% 的量。

> [!note] ★★★ 949 與 980 不是誤判來源
> `949xxx`（入站評估）與 `980xxx`（關聯總結）是**機制性規則**，
> 每個超過門檻的請求都會命中一次。它們出現在排行榜上是正常的，
> **不要試圖排除它們**。要處理的是它們上面那些偵測規則。

#### 第二步：對每個規則看它命中在哪些 URI ★★★★★

```bash
RULE_ID=942xxx
sudo awk -v RS='---[a-zA-Z0-9]+---A--' \
  -v id="\\[id \"$RULE_ID\"\\]" \
  '$0 ~ id' /var/log/nginx/modsec_audit.log \
  | grep -oP '\[uri "\K[^"]+' | sort | uniq -c | sort -rn | head
```

更簡單但同樣有效的版本（在同一筆日誌區塊內找 uri）：

```bash
sudo grep -B20 '\[id "942xxx"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP '^(GET|POST|PUT|DELETE|PATCH) \K[^ ?]+' \
  | sort | uniq -c | sort -rn | head
```

```text
   4102 /admin/article/save
    530 /search
    120 /api/v1/comment
     69 /product/detail
```

★★★★★ **判讀**：4102 次集中在 `/admin/article/save`
→ 這幾乎確定是後台編輯器誤判，而不是攻擊
（攻擊不會四千次都打同一個需要登入的後台頁面）。

#### 第三步：看實際命中的內容 ★★★★★

```bash
sudo grep '\[id "942xxx"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP 'Matched Data: \K.{0,80}' | head -10
```

```text
<p>本府 113 年度施政計畫</p><img src="/upload/plan.
<h2>公告事項</h2><ul><li>請於 9 月 30 日前完成
O'Brien
select 適當的申請類別
' OR '1'='1
```

★★★★★ **前四筆一看就是正常業務內容 → 誤判。
第五筆是真攻擊。** 這就是為什麼要看實際內容，
而不是只看規則命中次數。

#### 綜合腳本：一次產出誤判分析報告 ★★★★

```bash
#!/bin/bash
# /usr/local/bin/waf-report.sh
# WAF 誤判分析日報

LOG=/var/log/nginx/modsec_audit.log
OUT=/var/log/nginx/waf-report-$(date +%F).txt

{
  echo "================================================"
  echo " WAF 誤判分析報告  $(date '+%F %T')"
  echo " 日誌檔：$LOG"
  echo "================================================"
  echo

  echo "── 1. 稽核紀錄總筆數 ──"
  grep -c -- '---A--' "$LOG"
  echo

  echo "── 2. 會被阻擋的請求數（分數超過門檻）──"
  grep -c 'Anomaly Score Exceeded' "$LOG"
  echo

  echo "── 3. 規則命中排行（前 15）──"
  grep -oP '\[id "\K[0-9]+' "$LOG" | sort | uniq -c | sort -rn | head -15
  echo

  echo "── 4. 命中最多的 URI（前 15）──"
  grep -oP '\[uri "\K[^"]+' "$LOG" | sort | uniq -c | sort -rn | head -15
  echo

  echo "── 5. 來源 IP 排行（前 15）──"
  grep -oP '\[client \K[0-9.]+' "$LOG" | sort | uniq -c | sort -rn | head -15
  echo

  echo "── 6. 異常分數分布 ──"
  grep -oP 'Total Score: \K[0-9]+' "$LOG" | sort -n | uniq -c
  echo

  echo "── 7. 命中內容樣本（前 20，人工判讀用）──"
  grep -oP 'Matched Data: \K.{0,70}' "$LOG" | sort | uniq -c \
    | sort -rn | head -20
} > "$OUT"

echo "報告已產生：$OUT"
```

```bash
sudo chmod 755 /usr/local/bin/waf-report.sh
sudo /usr/local/bin/waf-report.sh
```

```text
報告已產生：/var/log/nginx/waf-report-2026-09-03.txt
```

排入每日排程：

```bash
sudo tee /etc/cron.d/waf-report > /dev/null <<'EOF'
5 6 * * * root /usr/local/bin/waf-report.sh > /dev/null 2>&1
EOF
```

> [!tip] ★★★★ 觀察期間每天早上看這份報告
> 五分鐘看完，重點看三個數字：
> 1. **第 2 項（會被擋數）** 有沒有下降 → 排除規則有沒有生效
> 2. **第 3 項排行** 有沒有出現新的規則 ID → 有新的業務情境出現
> 3. **第 7 項內容樣本** 有沒有真的長得像攻擊的 → 有的話單獨處理

#### 稽核日誌的一筆長什麼樣 ★★★★

拿一筆完整的紀錄來拆解：

```text
---xY9kL2mQ---A--
[03/Sep/2026:14:22:41 +0800] 175698736138.512345 10.20.3.88 51234 10.20.1.10 443
  │                          │                   │           │     │          │
  時間                       交易 ID              來源 IP    來源埠  目的 IP   目的埠

---xY9kL2mQ---B--
POST /admin/article/save HTTP/1.1          ← 請求行：URI 在這裡
Host: doc.example.gov.tw
Content-Type: application/x-www-form-urlencoded
Cookie: PHPSESSID=abc123...

---xY9kL2mQ---C--
title=%E5%85%AC%E5%91%8A&content=%3Cp%3E%E6%9C%AC%E5%BA%9C...
                                  └─ 請求本體（★★★★ 含個資風險）

---xY9kL2mQ---F--
HTTP/1.1 200
Content-Type: text/html; charset=UTF-8

---xY9kL2mQ---H--
ModSecurity: Warning. Pattern match "..." at ARGS:content.
 [file "/etc/nginx/modsec/crs/rules/REQUEST-941-APPLICATION-ATTACK-XSS.conf"]
 [line "..."] [id "941xxx"] [rev ""] [msg "XSS Filter - Category 1"]
 [data "Matched Data: <p> found within ARGS:content: <p>本府113年度..."]
 [severity "CRITICAL"] [tag "attack-xss"] [tag "OWASP_CRS"]
 [hostname "doc.example.gov.tw"] [uri "/admin/article/save"]
 [unique_id "175698736138.512345"]

ModSecurity: Warning. Operator GE matched 5 at TX:inbound_anomaly_score.
 [file "/etc/nginx/modsec/crs/rules/REQUEST-949-BLOCKING-EVALUATION.conf"]
 [id "949110"] [msg "Inbound Anomaly Score Exceeded (Total Score: 20)"]

---xY9kL2mQ---Z--
```

★★★★★ **從這一筆你能讀出全部調校所需的資訊**：

| 問題 | 從哪看 |
| --- | --- |
| 哪條規則？ | `[id "941xxx"]` |
| 什麼類型？ | `[tag "attack-xss"]`、規則檔名 |
| 命中哪個欄位？ | ★★★★★ `at ARGS:content` |
| 實際內容是什麼？ | ★★★★★ `[data "Matched Data: ..."]` |
| 哪個 URI？ | `[uri "/admin/article/save"]` |
| 累加幾分？ | ★★★★★ `Total Score: 20` |
| 會不會被擋？ | `Anomaly Score Exceeded` 有出現 → 切 `On` 後會被擋 |
| 誰送的？ | A 段的來源 IP |
| 怎麼跟 access log 對？ | `unique_id` / transaction id |

日誌欄位的完整說明與告警串接見 [[090-04-04-guide-ModSecurity-日誌分析與監控]]。

---

### 效能與日誌量控制 ★★★

誤判調校的副產品是**日誌會變得非常大**。這一節處理量的問題。

#### `SecAuditEngine` 的三個值 ★★★★

| 值 | 行為 | 一天的量（中型機關網站估） |
| --- | --- | --- |
| `On` | ★★★★★ 記錄**每一個**請求 | 數 GB～數十 GB，硬碟很快滿 |
| `RelevantOnly` | ★★★★ 只記命中規則或狀態碼符合的 | 數 MB～數百 MB |
| `Off` | 不記 | 0（但等於白裝）|

```apache
SecAuditEngine RelevantOnly
SecAuditLogRelevantStatus "^(?:5|4(?!04))"
```

> [!danger] ★★★★★ 觀察期不要用 `SecAuditEngine On`
> 有人以為「觀察期要看全部流量，所以開 On」。錯。
> `RelevantOnly` 已經會記錄**所有命中規則的請求** —— 那正是你要分析的東西。
> 開 `On` 只會多出海量的正常請求紀錄，把你要找的東西淹掉，順便塞爆硬碟。

#### `SecRequestBodyLimit` 的取捨 ★★★★

```apache
SecRequestBodyLimit 52428800          # 50 MB
SecRequestBodyNoFilesLimit 1048576    # 1 MB
SecRequestBodyLimitAction Reject
```

| 指令 | 調整原則 |
| --- | --- |
| `SecRequestBodyLimit` | ★★★★ 設成「應用允許的最大上傳 + 一點餘裕」 |
| `SecRequestBodyNoFilesLimit` | ★★★ 大型 JSON API 的請求可能超過預設 128 KB |
| `SecRequestBodyLimitAction` | ★★★★★ **維持 `Reject`**。`ProcessPartial` 是繞過 WAF 的後門 |

同時要跟 Nginx 的限制對齊：

```nginx
client_max_body_size 50m;
```

> [!warning] ★★★★ 兩個限制要一致
> `client_max_body_size` 比 `SecRequestBodyLimit` 小 → Nginx 先擋，回 413
> `SecRequestBodyLimit` 比較小 → ModSecurity 擋，也是 413
> 兩邊訊息不同，排錯時容易搞混。**設成一樣的值**，並在註解裡寫明。

#### 什麼情況該只記命中的請求 ★★★★

| 情境 | 建議 |
| --- | --- |
| 觀察期（階段一、二） | ★★★★ `RelevantOnly` + `SecAuditLogParts ABIJDEFHZ`（完整）|
| 穩定運行（階段三之後） | ★★★★ `RelevantOnly`，可考慮拿掉 `C` 段（減少個資留存）|
| 高流量站台 | ★★★ 考慮 `SecAuditLogType Concurrent`，避免單檔寫入競爭 |
| 磁碟吃緊 | ★★★ 縮短 logrotate 保存週期，或即時送出到集中式日誌 |
| 需長期保存供稽核 | ★★★★ 送到 SIEM，本機只留 7～14 天 |

> [!tip] ★★★★ 穩定後拿掉 `C` 段的取捨
> `C` 段（請求本體）是調校時最有價值的資訊，但也是個資風險最高的部分。
>
> - 調校期間：★★★★★ **一定要留**，沒有它看不到誤判內容
> - 穩定運行後：可改成 `ABIJDEFHZ` 去掉 `C`，改用 `I` 段（精簡版）
> - 需要重新調校時再開回來
>
> 這個切換要寫進 SOP，不要臨時決定。

#### logrotate 設定 ★★★★

```bash
sudo tee /etc/logrotate.d/modsecurity > /dev/null <<'EOF'
/var/log/nginx/modsec_audit.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 "$(cat /var/run/nginx.pid)"
    endscript
}
EOF

sudo logrotate -d /etc/logrotate.d/modsecurity
```

```text
reading config file /etc/logrotate.d/modsecurity
Handling 1 logs
rotating pattern: /var/log/nginx/modsec_audit.log  after 1 days (14 rotations)
```

> [!danger] ★★★★ 稽核日誌權限
> `create 0640 www-data adm` —— **不可以是 0644**。
> 稽核日誌含使用者輸入的原始內容（帳號、身分證號、地址、有時是密碼）。
> 完整的日誌管理見 [[100-01-02-guide-日誌-日誌集中與輪替]]。

#### 效能相關的其他調整 ★★★

| 調整 | 效果 |
| --- | --- |
| 靜態資源 `modsecurity off;` | ★★★★ 省下最大宗的無謂檢查 |
| 關閉 `SecResponseBodyAccess` | ★★★ 省下整個回應緩衝，但失去外洩偵測 |
| `SecDebugLogLevel 0` | ★★★★★ 正式環境必須；開 9 會嚴重拖慢並塞爆硬碟 |
| `tx.sampling_percentage` | ★★ 導入期工具，穩定後調回 100 |
| 減少不必要的規則檔 | ★★ 例如完全不用 PHP 可考慮不載入 PHP 注入規則 |

深入的效能量測方法見 [[090-04-05-guide-ModSecurity-效能與實戰情境]]。

---

## 完整實戰範例

**情境**：機關的「公文管理系統」（`doc.example.gov.tw`）要導入 WAF。

| 項目 | 內容 |
| --- | --- |
| 系統 | 三年前委外開發的 PHP 系統，廠商仍有維護合約 |
| 特徵 | ★★★★★ **後台有富文字編輯器**（公告與公文內容）|
| | 有檔案上傳（附件，最大 30 MB）|
| | 有一支給另一個系統呼叫的 JSON API |
| 使用者 | 約 300 位同仁，上班時間使用 |
| 架構 | Nginx 反向代理（WAF 在這裡）→ PHP-FPM |
| 目標 | 六週內完成導入，切到 `SecRuleEngine On` |

### 第 0 週：前置準備

#### 步驟 0-1：環境盤點 ★★★★

```bash
# 確認引擎與 CRS 都就緒
sudo nginx -t
sudo nginx -T | grep -c 'SecRule '
```

```text
nginx: configuration file /etc/nginx/nginx.conf test is successful
1043
```

```bash
grep -E '^SecRuleEngine|^SecAuditEngine|^SecAuditLogParts' \
     /etc/nginx/modsec/modsecurity.conf
grep -n 'paranoia_level\|anomaly_score_threshold' \
     /etc/nginx/modsec/crs-setup.conf | grep -v '^\s*#'
```

```text
SecRuleEngine DetectionOnly
SecAuditEngine RelevantOnly
SecAuditLogParts ABIJDEFHZ
78:  setvar:tx.blocking_paranoia_level=1"
112:  setvar:tx.inbound_anomaly_score_threshold=5,
```

★★★★★ 四項全對才往下走。

#### 步驟 0-2：調整上傳限制

```bash
sudo sed -i 's/^SecRequestBodyLimit .*/SecRequestBodyLimit 33554432/' \
     /etc/nginx/modsec/modsecurity.conf
grep '^SecRequestBody' /etc/nginx/modsec/modsecurity.conf
```

```text
SecRequestBodyAccess On
SecRequestBodyLimit 33554432
SecRequestBodyNoFilesLimit 131072
SecRequestBodyLimitAction Reject
```

Nginx 端對齊：

```nginx
server {
    server_name doc.example.gov.tw;
    client_max_body_size 32m;   # 與 SecRequestBodyLimit 一致
    ...
}
```

#### 步驟 0-3：API 的方法與 Content-Type ★★★★

先問廠商拿 API 文件，確認用到哪些方法與 Content-Type，
對照 `crs-setup.conf` 的允許清單補齊。

```bash
grep -n 'allowed_methods\|allowed_request_content_type' \
     /etc/nginx/modsec/crs-setup.conf
```

★★★★ 這一步在階段一之前做，因為它不是「誤判調校」，
而是「基本設定沒設對」。留到後面會浪費一整輪觀察。

#### 步驟 0-4：日誌與報告腳本

```bash
sudo tee /etc/logrotate.d/modsecurity > /dev/null <<'EOF'
/var/log/nginx/modsec_audit.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data adm
}
EOF
# 前面〈進階應用〉的 waf-report.sh 也一併部署
sudo chmod 755 /usr/local/bin/waf-report.sh
```

#### 步驟 0-5：通知業務單位 ★★★

發一封通知：

> 本室將於 9/3 起在公文系統前端啟用 Web 應用防火牆的**監測模式**。
> 此階段**不會阻擋任何操作**，僅記錄。預計 10 月中旬評估是否啟用阻擋。
> 若期間系統有任何異常，請立即通知資訊室（分機 xxxx）。

★★★ 就算真的完全不影響，也要留下這封信 ——
兩週後如果有其他系統故障，你需要證明不是 WAF 造成的。

---

### 第 1～2 週：階段一 —— DetectionOnly 觀察

#### 步驟 1-1：啟動觀察

```bash
sudo truncate -s 0 /var/log/nginx/modsec_audit.log
sudo systemctl reload nginx
date '+觀察期起始：%F %T' | sudo tee /var/log/nginx/waf-phase1-start.txt
```

```text
觀察期起始：2026-09-03 09:00:12
```

#### 步驟 1-2：每天早上五分鐘

```bash
sudo /usr/local/bin/waf-report.sh
sudo head -30 /var/log/nginx/waf-report-$(date +%F).txt
```

第 1 天：

```text
── 1. 稽核紀錄總筆數 ──
1487

── 2. 會被阻擋的請求數（分數超過門檻）──
243

── 3. 規則命中排行（前 15）──
    892 941xxx
    401 942xxx
    243 949110
    243 980130
    155 932xxx
     88 920xxx
     31 930xxx
```

★★★★★ **關鍵數字：243**。
如果今天就切 `On`，會有 243 個請求被擋。這個數字要降到 0。

#### 步驟 1-3：追蹤表

| 日期 | 稽核筆數 | 會被擋 | 新規則 ID | 備註 |
| --- | --- | --- | --- | --- |
| 09/03 | 1,487 | 243 | 12 | 第一天 |
| 09/04 | 1,392 | 228 | 3 | |
| 09/05 | 1,410 | 235 | 1 | |
| 09/08 | 1,455 | 240 | 0 | |
| 09/12 | 1,388 | 231 | 0 | ★ 連續 5 天無新 ID |
| 09/16 | 1,502 | 251 | 2 | 新 ID：來自季報上傳 |
| 09/30 | 3,120 | 502 | ★ 4 | **月底批次**，新增誤判 |
| 10/02 | 1,401 | 236 | 0 | 恢復平常 |

> [!warning] ★★★★★ 看到 09/30 那一列了嗎
> 月底那天不只請求量翻倍，還冒出 4 個全新的規則 ID。
> **如果 09/16 就切 `On`，月底那天會有 500 個請求被擋。**
> 這就是「觀察期至少兩週、最好跨月底」的具體理由。

#### 步驟 1-4：階段一退出檢查

| 條件 | 狀態 |
| --- | --- |
| 已滿兩週 | ✅ 09/03～10/02 |
| 跨過月初月底 | ✅ 涵蓋 09/30 |
| 主要業務情境已涵蓋 | ✅ 逐項確認（見下表）|
| 新規則 ID 趨於 0 | ✅ 10/01 起連續為 0 |

業務情境涵蓋確認表 ★★★★：

| 情境 | 已在觀察期發生 |
| --- | --- |
| 登入 / 登出 | ✅ |
| 公文查詢與檢視 | ✅ |
| ★ 後台新增公告（富文字） | ✅ |
| ★ 後台編輯既有公告 | ✅ |
| ★ 上傳附件（Word / PDF / Excel） | ✅ |
| ★ 上傳中文檔名附件 | ✅ |
| 下載附件 | ✅ |
| ★ JSON API 被外部系統呼叫 | ✅ |
| 月底批次結算 | ✅ 09/30 |
| 報表匯出 | ✅ |

---

### 第 3～4 週：階段二 —— 分析與排除

#### 步驟 2-1：統計前五名 ★★★★★

```bash
sudo cat /var/log/nginx/modsec_audit.log \
         /var/log/nginx/modsec_audit.log.*.gz 2>/dev/null \
  | grep -oP '\[id "\K[0-9]+' | sort | uniq -c | sort -rn | head -8
```

```text
  12480 941xxx-A     ← XSS Category 1
   9820 941xxx-B     ← XSS 另一條
   5610 942xxx-A     ← SQLi
   3402 949110       ← （機制性，不處理）
   3402 980130       ← （機制性，不處理）
   2180 932xxx       ← RCE
    940 930xxx       ← LFI
    311 920xxx       ← 協定
```

（★★★ `941xxx-A` 這種寫法只是本文的佔位標記，你的日誌裡是實際數字。）

#### 步驟 2-2：第 1 名 —— 逐項分析 ★★★★★

**A. 命中在哪些 URI？**

```bash
sudo grep -B25 '\[id "941xxx-A"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP '^(GET|POST) \K[^ ?]+' | sort | uniq -c | sort -rn | head
```

```text
  11890 /admin/article/save
    420 /admin/announcement/save
    170 /search
```

**B. 命中哪個欄位、內容是什麼？**

```bash
sudo grep '\[id "941xxx-A"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP 'found within \K[^:]+' | sort | uniq -c | sort -rn
```

```text
  12310 ARGS:content
    170 ARGS:q
```

```bash
sudo grep '\[id "941xxx-A"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP 'Matched Data: \K.{0,60}' | head -5
```

```text
<p> found within ARGS:content: <p>本府113年度施政計畫公告</p><
<img found within ARGS:content: ...<img src="/upload/2026/plan
<a href found within ARGS:content: <a href="/doc/1234">相關附件
<p> found within ARGS:content: <p>各單位請於 9 月 30 日前
<h2> found within ARGS:content: <h2>公告事項</h2><ul><li>
```

★★★★★ **結論**：全部是後台編輯器的正常 HTML。**誤判確認。**

**C. 來源 IP 模式**

```bash
sudo grep -B25 '\[id "941xxx-A"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP '^\[.*?\] [0-9.]+ [0-9]+ \K' >/dev/null
sudo grep -oP '\[client \K[0-9.]+' /var/log/nginx/modsec_audit.log \
  | sort | uniq -c | sort -rn | head -5
```

```text
   4210 10.20.3.88
   3980 10.20.3.91
   2100 10.20.4.15
    890 10.20.3.77
```

★★★★ 全部是內網 IP，且集中在幾位固定人員 → 更確認是誤判（承辦人員在編輯公告）。

**D. 問廠商 ★★★★★**

寄信給廠商：

> 請確認：`/admin/article/save` 的 `content` 參數是否為富文字編輯器內容、
> 本來就會包含 HTML 標籤？
> 另外，該內容在前台顯示時，貴公司是否有做 HTML 輸出編碼／過濾？

廠商回覆（2026-10-05）：

> 是，`content` 為 TinyMCE 編輯器內容，包含 HTML。
> 前台顯示時使用 HTMLPurifier 過濾，僅允許白名單標籤。

★★★★★ **有了這個回覆，排除規則才有正當性**（存進來的 HTML 不會被當程式執行）。
把這封信存檔，作為排除規則的核可依據。

#### 步驟 2-3：寫第一條排除規則 ★★★★★

```bash
sudo mkdir -p /etc/nginx/modsec/exclusions
sudo tee /etc/nginx/modsec/exclusions/20-doc-system.conf > /dev/null <<'EOF'
# ===============================================================
# 站台：doc.example.gov.tw（公文管理系統）
# ===============================================================

# --- 排除 001 ---------------------------------------------------
# 症狀    : 後台儲存公告／公文內容 → 分數破門檻（切 On 後會 403）
# 原因    : TinyMCE 富文字編輯器送出 HTML，被 XSS 規則判為攻擊
# URI     : /admin/article/save、/admin/announcement/save
# 參數    : ARGS:content
# 規則    : 941xxx-A / 941xxx-B（來源：2026-09-03~10-02 稽核日誌統計）
# 前提    : 廠商已確認前台以 HTMLPurifier 白名單過濾（郵件 2026-10-05）
# 申請    : 資訊室 王小明   核可：資安承辦 李大華 2026-10-06
# 複核    : 2027-04-01
# ---------------------------------------------------------------
SecRule REQUEST_URI "@rx ^/admin/(article|announcement)/save" \
    "id:1100001,\
     phase:2,\
     pass,\
     nolog,\
     ctl:ruleRemoveTargetById=941xxxA;ARGS:content,\
     ctl:ruleRemoveTargetById=941xxxB;ARGS:content"
EOF
```

> [!warning] ★★★★★ `941xxxA` 只是本文的佔位
> 實際撰寫時把它換成你日誌裡的六位數字 ID。
> **不要照抄本文的佔位字串，那不是合法的規則 ID。**

掛進載入順序（★★★★★ 必須在 CRS 之前）：

```bash
sudo tee /etc/nginx/modsec/main.conf > /dev/null <<'EOF'
Include /etc/nginx/modsec/modsecurity.conf
Include /etc/nginx/modsec/crs-setup.conf
Include /etc/nginx/modsec/exclusions/*.conf
Include /etc/nginx/modsec/crs/rules/*.conf
Include /etc/nginx/modsec/crs-exclusions-after.conf
EOF

sudo nginx -t && sudo systemctl reload nginx
```

```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

#### 步驟 2-4：驗證這條排除有效 ★★★★★

```bash
sudo truncate -s 0 /var/log/nginx/modsec_audit.log

# 模擬後台儲存（帶 HTML 的 content）
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://doc.example.gov.tw/admin/article/save \
  --data-urlencode 'title=測試公告' \
  --data-urlencode 'content=<p>本府113年度施政計畫</p><img src="/a.jpg">'
```

```text
200
```

```bash
sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
```

```text
0
```

★★★★★ **0 就是排除生效了。**

**再驗證「其他地方的保護還在」** —— 這一步不能省：

```bash
sudo truncate -s 0 /var/log/nginx/modsec_audit.log

# 測試 1：同一個 URI 的「其他參數」仍受保護
curl -s -o /dev/null -X POST http://doc.example.gov.tw/admin/article/save \
  --data-urlencode 'title=<script>alert(1)</script>'
sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
```

```text
1
```

```bash
sudo truncate -s 0 /var/log/nginx/modsec_audit.log
# 測試 2：其他 URI 的 content 參數仍受保護
curl -s -o /dev/null -X POST http://doc.example.gov.tw/comment/add \
  --data-urlencode 'content=<script>alert(1)</script>'
sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
```

```text
1
```

```bash
sudo truncate -s 0 /var/log/nginx/modsec_audit.log
# 測試 3：同一 URI 同一參數，但是 SQLi 規則仍受保護
curl -s -o /dev/null -X POST http://doc.example.gov.tw/admin/article/save \
  --data-urlencode "content=1' UNION SELECT username,password FROM users--"
sudo grep -c 'Anomaly Score Exceeded' /var/log/nginx/modsec_audit.log
```

```text
1
```

> [!tip] ★★★★★ 這三個測試是排除規則的驗收標準
> 每寫一條排除規則，都要證明：
> 1. 誤判消失了
> 2. **同 URI 的其他參數還在保護**
> 3. **其他 URI 的同名參數還在保護**
> 4. **同 URI 同參數的其他類型攻擊還在保護**
>
> 只做第 1 項就宣告完成，是排除寫太寬卻沒發現的主因。

#### 步驟 2-5：處理第 2～5 名

重新統計，處理下一批：

```bash
sudo /usr/local/bin/waf-report.sh
sudo sed -n '/規則命中排行/,/^$/p' /var/log/nginx/waf-report-$(date +%F).txt
```

```text
── 3. 規則命中排行（前 15）──
   5610 942xxx-A
   2180 932xxx
    940 930xxx
    311 920xxx
```

★★★★ XSS 那兩條已經從排行榜消失 —— 排除生效。

**第 2 名 `942xxx-A`（SQLi）分析**：

```bash
sudo grep '\[id "942xxx-A"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP 'found within \K[^:]+' | sort | uniq -c | sort -rn
sudo grep '\[id "942xxx-A"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP 'Matched Data: \K.{0,50}' | head -8
```

```text
   4980 ARGS:content
    520 ARGS:password
    110 ARGS:q
```

```text
' found within ARGS:content: ...簽准後辦理，詳見『附件一』...
-- found within ARGS:content: <p>------------------</p>
' found within ARGS:password: P@ss'w0rd2026
-- found within ARGS:password: MyPass--2026
select found within ARGS:q: select 相關法規
```

三類誤判，分別處理：

```bash
sudo tee -a /etc/nginx/modsec/exclusions/20-doc-system.conf > /dev/null <<'EOF'

# --- 排除 002 ---------------------------------------------------
# 症狀 : 公告內容含全形引號、連續破折號 → 命中 SQLi 規則
# 原因 : 公文用語常有『』與 ------ 分隔線，被判為 SQL 註解與字串跳脫
# URI  : /admin/(article|announcement)/save   參數：ARGS:content
# 前提 : 廠商確認後端使用 PDO 參數化查詢（郵件 2026-10-05）
# 核可 : 資安承辦 李大華 2026-10-08   複核：2027-04-01
# ---------------------------------------------------------------
SecRule REQUEST_URI "@rx ^/admin/(article|announcement)/save" \
    "id:1100002,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetByTag=attack-sqli;ARGS:content"

# --- 排除 003 ---------------------------------------------------
# 症狀 : 密碼含 ' 或 -- 的同仁無法登入
# 原因 : 密碼欄位本來就該接受任意字元
# URI  : /auth/login   參數：ARGS:password
# 前提 : 廠商確認密碼經 password_hash() 處理，不進 SQL 字串（郵件 2026-10-05）
# 核可 : 資安承辦 李大華 2026-10-08   複核：2027-04-01
# ---------------------------------------------------------------
SecRule REQUEST_URI "@streq /auth/login" \
    "id:1100003,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetByTag=attack-sqli;ARGS:password,\
     ctl:ruleRemoveTargetByTag=attack-xss;ARGS:password"
EOF
```

> [!warning] ★★★★ 搜尋框的 `q=select 相關法規` 怎麼辦
> 這一類**不要**排除。理由：
> - 搜尋框是最常被拿來試 SQL Injection 的地方
> - 只有 110 次，量很小
> - 使用者輸入「select」作為搜尋詞是低頻率的偶發狀況
>
> 正確做法是**接受這個誤判**：切 `On` 後，
> 極少數使用者搜尋這類詞會被擋，在 403 頁面提供聯絡方式即可。
> ★★★★★ **不是每個誤判都要排除。低頻率、高風險欄位的誤判，容忍它。**

**第 3 名 `932xxx`（RCE）**：

```bash
sudo grep '\[id "932xxx"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP 'Matched Data: \K.{0,50}' | head -5
```

```text
cat found within ARGS:content: ...請將各單位資料 cat 彙整後...
id found within ARGS:content: ...申請人 id 欄位請填寫...
env found within ARGS:content: ...環境 env 設定說明...
```

同樣是 `ARGS:content` 的中文內容夾雜英文短字。已被排除 002 涵蓋部分，
但 RCE 是不同 tag，需要另外處理：

```bash
sudo tee -a /etc/nginx/modsec/exclusions/20-doc-system.conf > /dev/null <<'EOF'

# --- 排除 004 ---------------------------------------------------
# 症狀 : 公告內文含 cat / id / env 等英文短字 → 命中 RCE 規則
# URI  : /admin/(article|announcement)/save   參數：ARGS:content
# 核可 : 資安承辦 李大華 2026-10-08   複核：2027-04-01
# ---------------------------------------------------------------
SecRule REQUEST_URI "@rx ^/admin/(article|announcement)/save" \
    "id:1100004,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetByTag=attack-rce;ARGS:content"
EOF

sudo nginx -t && sudo systemctl reload nginx
```

**第 4 名 `930xxx`（LFI）—— 附件下載**：

```bash
sudo grep '\[id "930xxx"\]' /var/log/nginx/modsec_audit.log \
  | grep -oP 'Matched Data: \K.{0,50}' | head -3
```

```text
../ found within ARGS:path: /uploads/2026/09/../09/預算表.xlsx
```

★★★★ 這一筆要小心。`../` 出現在下載參數裡 ——
問廠商後確認是前端組路徑時的產物，且後端有做 `realpath()` 檢查。

> [!danger] ★★★★★ 這種情況先修應用，不要先排除
> 參數裡出現 `../` 是**應用端的路徑處理有問題**的徵兆。
> 正確順序是：
> 1. 要求廠商修正前端路徑組合方式（不要產出 `../`）
> 2. 確認後端的 `realpath()` 檢查確實有效
> 3. **修好之後這個誤判自然消失，不需要排除規則**
>
> 如果直接寫排除規則放行 `../`，就等於幫真正的路徑穿越攻擊開門。
> **能修應用就修應用，寫排除規則永遠是第二選擇。**

#### 步驟 2-6：階段二退出檢查 ★★★★★

連續五個工作日執行：

```bash
sudo /usr/local/bin/waf-report.sh
sudo sed -n '/會被阻擋的請求數/,+2p' /var/log/nginx/waf-report-$(date +%F).txt
```

| 日期 | 會被擋筆數 | 內容判讀 |
| --- | --- | --- |
| 10/13 | 8 | 5 筆外部 IP 掃描（真攻擊）+ 3 筆搜尋框 select |
| 10/14 | 3 | 全部是外部掃描 |
| 10/15 | 11 | 全部是外部掃描（同一個 IP 段）|
| 10/16 | 2 | 外部掃描 |
| 10/17 | 6 | 5 筆外部掃描 + 1 筆搜尋框 |

★★★★★ **退出條件達成**：
連續五天，會被擋的請求裡**沒有任何一筆是正常業務操作**
（搜尋框那幾筆是已決定容忍的低頻誤判，且已在 403 頁面提供聯絡方式）。

---

### 第 5 週：階段三 —— 切換到 On

#### 步驟 3-1：切換前檢查表 ★★★★★

| # | 檢查項 | 狀態 |
| --- | --- | --- |
| 1 | 階段二退出條件連續五天達成 | ✅ |
| 2 | 排除規則全部有註解、有核可紀錄 | ✅ |
| 3 | 排除規則已納入版控 | ✅ `git commit` |
| 4 | ★★★★★ 回退指令已寫好、已演練過一次 | ✅ |
| 5 | 已通知業務單位切換時間與回報管道 | ✅ |
| 6 | 選在低流量時段（週五 16:00）| ✅ |
| 7 | 切換後兩小時有人在場 | ✅ |
| 8 | 自訂 403 頁面已就緒（含聯絡分機與事件編號）| ✅ |
| 9 | 監控告警已設好（403 數量異常時通知）| ✅ |

自訂 403 頁面 ★★★：

```nginx
server {
    server_name doc.example.gov.tw;
    error_page 403 /waf-blocked.html;

    location = /waf-blocked.html {
        internal;
        root /var/www/errors;
    }
}
```

```html
<h1>您的請求無法完成</h1>
<p>系統偵測到此次操作可能包含不合規的內容而暫停處理。</p>
<p>若您確認操作正常，請聯絡資訊室（分機 1234）並提供下列編號：</p>
<p>事件編號：<code>{{ request_id }}</code></p>
```

> [!danger] ★★★★ 403 頁面不要顯示規則細節
> 不要寫「您觸發了規則 942100 SQL Injection」——
> 那等於教攻擊者怎麼調整 payload。只給一組事件編號，
> 資訊室拿編號去日誌裡查即可。

#### 步驟 3-2：演練回退 ★★★★★

**在真的切換之前，先演練一次回退。**

```bash
# 演練：先切 On
sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine On/' \
     /etc/nginx/modsec/modsecurity.conf
sudo nginx -t && sudo systemctl reload nginx
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

```text
SecRuleEngine On
```

```bash
# 立刻演練回退，計時
time (sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine DetectionOnly/' \
      /etc/nginx/modsec/modsecurity.conf && \
      sudo nginx -t && sudo systemctl reload nginx)
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

```text
nginx: configuration file /etc/nginx/nginx.conf test is successful

real    0m0.412s
SecRuleEngine DetectionOnly
```

★★★★★ 確認回退**不到一秒**完成，而且指令是可以直接貼上執行的。

#### 步驟 3-3：正式切換

```bash
date '+切換時間：%F %T' | sudo tee -a /var/log/nginx/waf-phase3.log
sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine On/' \
     /etc/nginx/modsec/modsecurity.conf
sudo nginx -t && sudo systemctl reload nginx
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

```text
切換時間：2026-10-17 16:00:03
nginx: configuration file /etc/nginx/nginx.conf test is successful
SecRuleEngine On
```

#### 步驟 3-4：立即冒煙測試 ★★★★★

```bash
# 1) 正常首頁
curl -s -o /dev/null -w '首頁      : %{http_code}\n' \
  https://doc.example.gov.tw/

# 2) 後台儲存（帶 HTML）—— 排除規則保護的路徑
curl -s -o /dev/null -w '後台儲存  : %{http_code}\n' \
  -X POST https://doc.example.gov.tw/admin/article/save \
  --data-urlencode 'title=切換測試' \
  --data-urlencode 'content=<p>測試內容</p><img src="/a.jpg">'

# 3) 含特殊字元的密碼登入
curl -s -o /dev/null -w '特殊密碼  : %{http_code}\n' \
  -X POST https://doc.example.gov.tw/auth/login \
  --data-urlencode 'account=test' \
  --data-urlencode "password=P@ss'w0rd--2026"

# 4) 真攻擊 —— 應該被擋
curl -s -o /dev/null -w '攻擊測試  : %{http_code}\n' \
  --get --data-urlencode "id=1' OR '1'='1" \
  https://doc.example.gov.tw/doc/view
```

```text
首頁      : 200
後台儲存  : 200
特殊密碼  : 200
攻擊測試  : 403
```

★★★★★ **前三個 200、第四個 403** —— 這四行就是切換成功的定義。

#### 步驟 3-5：切換後兩小時盯場

```bash
watch -n 30 '
echo "=== $(date +%T) ==="
echo -n "近 5 分鐘 403 數："
sudo awk -v t="$(date -d "5 min ago" "+%d/%b/%Y:%H:%M")" \
  "\$0 >= t && \$9==403" /var/log/nginx/access.log | wc -l
echo "--- 最近被擋的 URI ---"
sudo grep "Anomaly Score Exceeded" /var/log/nginx/modsec_audit.log \
  | tail -3
'
```

正常情況下每 5 分鐘應該是 0～2 筆（外部掃描）。
**突然出現十幾筆且來源是內網 IP → 立刻回退。**

#### 步驟 3-6：兩週觀察

| 日期 | 403 總數 | 內網來源 403 | 客訴 | 處置 |
| --- | --- | --- | --- | --- |
| 10/17（切換日）| 14 | 0 | 0 | — |
| 10/20 | 22 | 1 | 1 | ★ 搜尋「select」被擋，已說明 |
| 10/24 | 18 | 0 | 0 | — |
| 10/31（月底）| 41 | 0 | 0 | ★★★★ **月底批次順利通過** |

★★★★★ 10/31 那一列是最重要的驗證 ——
因為階段一有涵蓋月底，所以月底批次的誤判早就處理掉了。

#### 步驟 3-7：階段三退出與交付

```bash
cd /etc/nginx/modsec
sudo git add exclusions/ main.conf crs-setup.conf modsecurity.conf
sudo git commit -m "WAF: 公文系統完成調校並切換至 On（2026-10-17）"
```

交付文件應包含：

| 文件 | 內容 |
| --- | --- |
| 導入紀錄 | 四階段各自的起訖日期與退出條件達成證據 |
| 排除規則清單 | 每條的原因、URI、參數、規則 ID、核可紀錄、複核日期 ★★★★★ |
| 觀察期數據 | 追蹤表、報告檔 |
| 回退程序 | 貼在機房與資訊室 ★★★★★ |
| 待辦 | 「應用端待修正」清單（如 `../` 路徑問題）★★★★ |
| 複核排程 | 排除規則的下次複核日期 |

---

### 第 6 週：階段四 —— 擴大

下一個站台（人事系統）**從階段一重新開始**。
排除規則放在 `exclusions/30-hr-system.conf`，
不要把 `20-doc-system.conf` 的內容複製過去。

---

## 常見錯誤與排錯

| # | 現象 | 原因 | 解法 |
| --- | --- | --- | --- |
| 1 | 切 `On` 當天大量客訴，只好整個關掉 | ★★★★★ 沒跑觀察期，或觀察期太短 | 回到階段一，跑滿兩週且跨月底 |
| 2 | 排除規則寫了完全沒效果，也不報錯 | ★★★★★ `ctl:` 放在 CRS 規則**之後**載入 | 移到 `crs-exclusions-before.conf` 或 `exclusions/*.conf`，確認 Include 順序 |
| 3 | `SecRuleRemoveById` 寫了沒效果 | 放在 CRS 規則**之前**（規則還沒載入）| 移到 `-after` |
| 4 | 排除規則寫了但誤判照樣發生 | ★★★★★ 抄了別人文章的規則 ID，與本機版本不符 | 從自己的稽核日誌抄 ID |
| 5 | 排除之後發現整個站台的 XSS 保護都沒了 | 用了 `SecRuleRemoveByTag` 而非 `ctl:` 限定 URI | 改用 URI + 參數 + 規則 ID 三重限定 ★★★★★ |
| 6 | 誤判解決了但真攻擊也不擋了 | 調高了 `inbound_anomaly_score_threshold` | 改回 5，用精準排除處理誤判 ★★★★★ |
| 7 | 日誌一天數 GB，磁碟滿了 | `SecAuditEngine On` 或誤判量太大 | 改 `RelevantOnly`；先處理前三名誤判；設 logrotate ★★★★ |
| 8 | 日誌看不到規則 ID 與分數 | `SecAuditLogParts` 缺 `H` | 改成 `ABIJDEFHZ` ★★★★★ |
| 9 | 統計指令跑出來全是 0 | 日誌被 rotate 了，只讀到新的空檔 | 一併讀 `.gz`：`zcat modsec_audit.log.*.gz` |
| 10 | 整個 API 在切 `On` 後全掛 | ★★★★★ 允許方法／Content-Type 沒設對 | 補 `tx.allowed_methods` 與 `tx.allowed_request_content_type` |
| 11 | 上傳大檔 413 | `SecRequestBodyLimit` 或 `client_max_body_size` 太小 | 兩邊一起調大並保持一致 ★★★★ |
| 12 | 中文內容大量誤判 | 編碼不一致（Big5／UTF-8 混用）或雙重編碼 | ★★★★ 先統一全鏈路 UTF-8，很多誤判會自然消失 |
| 13 | 頁面顯示不完整、內容被截斷 | 出站規則誤判，或 `SecResponseBodyLimit` 太小 | 檢查 95xxxx 命中；調整 limit 或針對該路徑關出站檢查 ★★★★ |
| 14 | 排定的弱點掃描全被擋 | 掃描器 User-Agent 命中 913 | 掃描期間對掃描來源 IP 做限時例外，事後移除 ★★★ |
| 15 | 內部監控腳本被協定規則擋 | 腳本 HTTP 實作不標準 | 修腳本；或針對監控 IP 做例外 ★★★ |
| 16 | 某個使用者永遠登入不了，別人都可以 | ★★★★ 他的密碼含 `'` 或 `--` | 對登入 URI 的 password 參數排除注入規則 |
| 17 | 排除規則越寫越多、超過 40 條 | 用了太細的 URI 逐一列舉，或觀察期資料不足 | 用正規表示式合併同類；檢討是否該從應用端修 ★★★ |
| 18 | 兩年後沒人知道某條排除規則能不能刪 | ★★★★★ 排除規則沒寫註解 | 每條都要有原因、核可、複核日期 |
| 19 | 稽核日誌被一般帳號讀到，含個資 | 權限 0644 | 改 `create 0640 www-data adm` ★★★★ |
| 20 | 切 `On` 後 CPU 明顯升高 | 靜態資源也在過 WAF | 靜態 location 加 `modsecurity off;` ★★★ |
| 21 | 排除規則的 ID 互相衝突，Nginx 起不來 | 自訂規則 ID 重複 | 自訂 ID 統一用 1100000 起編號並集中管理 ★★★ |
| 22 | 換了新的 CRS 版本後誤判又冒出來 | 規則 ID 變動，舊排除規則失效 | ★★★★ 升級 CRS 後重跑一次縮短版觀察期 |

**排錯的固定順序** ★★★★★

```bash
# 1) 設定真的生效了嗎
sudo nginx -T | grep -A3 'ctl:ruleRemoveTargetById'

# 2) 載入順序對嗎（排除規則要在 CRS 之前）
sudo nginx -T | grep -n 'Include.*modsec' 

# 3) 規則 ID 對嗎
sudo grep -oP '\[id "\K[0-9]+' /var/log/nginx/modsec_audit.log | sort -u

# 4) 命中的欄位名對嗎
sudo grep -oP 'found within \K[^:]+' /var/log/nginx/modsec_audit.log \
  | sort | uniq -c

# 5) 現在是什麼模式
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

---

## 安全性注意事項

> [!danger] ★★★★★ 六條紅線
> 1. **不要用 `SecRuleEngine Off` 解決誤判。** 那不是解決，是放棄。
> 2. **不要調高異常分數門檻來減少誤判。** 那會讓真攻擊也通過。
> 3. **不要用 `SecRuleRemoveByTag` 關掉整類規則。**
> 4. **不要在沒有觀察期的情況下切 `On`。**
> 5. **不要抄別人文章裡的規則 ID。**
> 6. **不要寫沒有註解的排除規則。**

### 排除規則本身就是攻擊面 ★★★★★

每一條排除規則都是你親手在 WAF 上開的一個洞。攻擊者只要知道
「`/admin/article/save` 的 `content` 參數不做 XSS 檢查」，
就會把 payload 塞進那裡。

因應方式：

| 措施 | 說明 | 重要度 |
| --- | --- | --- |
| 排除範圍最小化 | URI + 參數 + 規則 ID 三重限定 | ★★★★★ |
| 加上額外限定條件 | 限定方法、限定來源網段（範本 E）| ★★★★ |
| 排除的路徑要有認證保護 | 後台路徑本來就該要登入 | ★★★★★ |
| 確認應用端有對應防護 | 排除 XSS 前先確認有輸出編碼 | ★★★★★ |
| 定期複核 | 應用改版後舊排除可能已不需要 | ★★★★ |
| 排除清單納入資安文件 | 稽核時要說得出每一條的理由 | ★★★★ |

> [!warning] ★★★★★ 「能修應用就修應用」
> 排除規則永遠是第二選擇。優先順序：
>
> ```text
> 1. 修正應用（改編碼、改路徑組合、改欄位驗證）  ← ★★★★★ 最好
> 2. 調整應用的資料格式（例如前端先做 HTML 白名單過濾再送）
> 3. 寫範圍最小的排除規則                        ← 可接受
> 4. 容忍低頻誤判                                ← 有時是對的
> 5. 放寬 WAF 設定                               ← ★★★★★ 最差
> ```

### 其他要點

| 項目 | 說明 | 重要度 |
| --- | --- | --- |
| 排除規則納入版控 | `/etc/nginx/modsec/` 用 git 管理 | ★★★★ |
| 每次變更都能回退 | commit 訊息寫清楚為什麼 | ★★★★ |
| 稽核日誌權限與保存期限 | 含個資，`0640` + 保存期限管理 | ★★★★ |
| 切 `On` 要有變更管理紀錄 | 誰核可、什麼時候、怎麼回退 | ★★★★ |
| 日誌送 SIEM | 本機日誌可能被攻擊者清掉 | ★★★★ 見 [[100-01-03-guide-日誌-系統監控與告警]] |
| 與 Fail2ban 串接 | 重複觸發的 IP 在防火牆層封掉 | ★★★ 見 [[090-02-05-guide-防護-Fail2ban入侵防護]] |
| CRS 升級後重跑縮短觀察期 | 規則 ID 與內容都可能變 | ★★★★ |
| 不要把 WAF 當唯一防線 | 見 [[090-05-01-guide-資安設備-資安全景圖與縱深防禦]] | ★★★★★ |

---

## 速查表

### 四階段導入

| 階段 | 模式 | 時間 | 退出條件 |
| --- | --- | --- | --- |
| 一 觀察 | `DetectionOnly` + PL1 | ★★★★★ 至少兩週，跨月底 | 業務情境涵蓋齊全、新規則 ID 趨於 0 |
| 二 排除 | `DetectionOnly` | 一至兩週 | ★★★★★ 連續 5 個工作日無業務誤判 |
| 三 切換 | `On`（單站台）| 兩週觀察 | 零客訴、零非預期 403 |
| 四 擴大 | 逐站台 | — | 每站台重跑階段一～三 |

### 誤判 vs 真攻擊判斷點

| 判斷點 | 傾向誤判 | 傾向真攻擊 |
| --- | --- | --- |
| `data` 內容 | 業務內容、HTML、中文 | 明確 payload |
| 來源 IP | 內網、固定幾個 | 外部、大量不同 |
| URI 分布 | 集中一個 | 大量不同 |
| 時間 | 上班時間 | 深夜、密集爆發 |
| 頻率 | 每天穩定量 | 短時間爆發 |
| 廠商回覆 | 「那欄位本來就有 HTML」 | 「那欄位只該收數字」★★★★★ |

### ❌ 錯誤做法 / ✅ 正確做法

| ❌ 錯誤 | ✅ 正確 |
| --- | --- |
| `SecRuleEngine Off` | 精準排除該 URI 該參數 |
| 門檻 5 → 50 | 維持 5 |
| `SecRuleRemoveByTag "attack-sqli"` | `ctl:ruleRemoveTargetById=<ID>;ARGS:x` + 限定 URI |
| 降 PL | 維持 PL1 |
| 抄文章的規則 ID | 從自己日誌抄 |
| 沒註解的排除 | 完整註解 + 核可 + 複核日期 |

### 排除規則寫法對照

| 寫法 | 範圍 | 放哪 | 建議 |
| --- | --- | --- | --- |
| `SecRuleRemoveById` | 全站全參數 | `-after` | ★ 少用 |
| `SecRuleRemoveByTag` | 整類 | `-after` | ★★★★★ 幾乎不該用 |
| `SecRuleUpdateTargetById <id> "!ARGS:x"` | 全站單參數 | `-after` | ★★ 可用 |
| `ctl:ruleRemoveTargetById=<id>;ARGS:x` | 單 URI 單參數 | ★★★★★ `-before` | **首選** |
| `ctl:ruleRemoveTargetByTag=<tag>;ARGS:x` | 單 URI 單參數整類 | `-before` | ★★★ 謹慎 |
| `ctl:ruleEngine=Off` | 整個請求 | `-before` | ★★★★★ 最後手段 |

### 日誌分析三連指令 ★★★★★

```bash
# 1) 規則命中排行
grep -oP '\[id "\K[0-9]+' modsec_audit.log | sort | uniq -c | sort -rn | head

# 2) 某規則命中在哪些欄位
grep '\[id "<ID>"\]' modsec_audit.log \
  | grep -oP 'found within \K[^:]+' | sort | uniq -c | sort -rn

# 3) 實際命中的內容
grep '\[id "<ID>"\]' modsec_audit.log \
  | grep -oP 'Matched Data: \K.{0,60}' | head -20
```

### 其他常用統計

| 目的 | 指令 |
| --- | --- |
| 會被擋的請求數 | `grep -c 'Anomaly Score Exceeded' modsec_audit.log` |
| 命中最多的 URI | `grep -oP '\[uri "\K[^"]+' modsec_audit.log \| sort \| uniq -c \| sort -rn` |
| 來源 IP 排行 | `grep -oP '\[client \K[0-9.]+' modsec_audit.log \| sort \| uniq -c \| sort -rn` |
| 分數分布 | `grep -oP 'Total Score: \K[0-9]+' modsec_audit.log \| sort -n \| uniq -c` |
| 一併讀壓縮檔 | `zcat modsec_audit.log.*.gz \| grep ...` |
| 稽核紀錄總筆數 | `grep -c -- '---A--' modsec_audit.log` |

### 日誌 `H` 段欄位判讀

| 欄位 | 意義 |
| --- | --- |
| `[id "..."]` | 規則 ID ★★★★★ |
| `[msg "..."]` | 規則描述 |
| `[data "Matched Data: ..."]` | ★★★★★ 實際命中的內容 |
| `at ARGS:xxx` / `found within ARGS:xxx` | ★★★★★ 命中哪個欄位 |
| `[uri "..."]` | 請求路徑 |
| `[severity "..."]` | 決定加幾分 |
| `[tag "attack-xxx"]` | 攻擊分類 |
| `Total Score: N` | ★★★★★ 累計分數 |
| `Anomaly Score Exceeded` | ★★★★★ 出現 = 切 `On` 後會被擋 |
| `[unique_id "..."]` | 與 access log 對照用 |

### 效能與日誌量

| 設定 | 建議值 |
| --- | --- |
| `SecAuditEngine` | `RelevantOnly` ★★★★ |
| `SecAuditLogParts` | 調校期 `ABIJDEFHZ`；穩定後可去 `C` |
| `SecRequestBodyLimit` | 應用最大上傳 + 餘裕 |
| `SecRequestBodyLimitAction` | ★★★★★ `Reject` |
| `client_max_body_size` | 與上者一致 |
| `SecDebugLogLevel` | ★★★★★ `0`～`3` |
| logrotate | `daily`、`rotate 14~30`、`create 0640` |
| 靜態資源 | `modsecurity off;` |

### 緊急回退 ★★★★★

```bash
sudo sed -i 's/^SecRuleEngine .*/SecRuleEngine DetectionOnly/' \
     /etc/nginx/modsec/modsecurity.conf
sudo nginx -t && sudo systemctl reload nginx
grep '^SecRuleEngine' /etc/nginx/modsec/modsecurity.conf
```

---

## 練習題

> [!example] 練習 1（★★★★）
> 用本篇的三連指令，對你的稽核日誌做一次完整分析，
> 產出一份「前五名規則 + 各自命中的 URI + 實際內容樣本」的表格，
> 並為每一項標註「誤判／真攻擊／待確認」。

> [!question]- 參考解答
> ```bash
> LOG=/var/log/nginx/modsec_audit.log
> for id in $(sudo grep -oP '\[id "\K[0-9]+' "$LOG" \
>             | sort | uniq -c | sort -rn | head -5 | awk '{print $2}'); do
>   echo "===== 規則 $id ====="
>   echo "-- 命中欄位 --"
>   sudo grep "\[id \"$id\"\]" "$LOG" \
>     | grep -oP 'found within \K[^:]+' | sort | uniq -c | sort -rn | head -5
>   echo "-- 內容樣本 --"
>   sudo grep "\[id \"$id\"\]" "$LOG" \
>     | grep -oP 'Matched Data: \K.{0,60}' | head -3
>   echo
> done
> ```
> ★★★★ 判讀重點：內容樣本一看就是業務內容 → 誤判；
> 是明確 payload → 真攻擊；不確定 → 問廠商。
> 記得 949/980 是機制性規則，不列入處理對象。

> [!example] 練習 2（★★★★★）
> 為一個「後台編輯器 `/cms/page/update` 的 `body` 參數被 XSS 誤判」的情境，
> 寫出排除規則，並設計**四個**驗證測試，證明排除範圍夠精準。

> [!question]- 參考解答
> ```apache
> # exclusions/10-cms.conf（在 CRS 規則之前載入）
> # 症狀/原因/前提/核可/複核 註解略
> SecRule REQUEST_URI "@beginsWith /cms/page/update" \
>     "id:1100030,phase:2,pass,nolog,\
>      ctl:ruleRemoveTargetByTag=attack-xss;ARGS:body"
> ```
> 四個驗證：
> ```bash
> # 1. 誤判消失
> curl -X POST .../cms/page/update -d 'body=<p>正常內容</p>'   → 不記分
> # 2. 同 URI 其他參數仍保護
> curl -X POST .../cms/page/update -d 'title=<script>alert(1)</script>' → 記分
> # 3. 其他 URI 的 body 仍保護
> curl -X POST .../comment/add -d 'body=<script>alert(1)</script>'      → 記分
> # 4. 同 URI 同參數的 SQLi 仍保護
> curl -X POST .../cms/page/update -d "body=1' UNION SELECT ..."        → 記分
> ```
> ★★★★★ 四項全過才算排除寫對。

> [!example] 練習 3（★★★★★）
> 你的主管說：「觀察期太久了，明天直接開 On 吧，出問題再說。」
> 寫一段 200 字以內的書面回覆說服他。

> [!question]- 參考解答
> 回覆要點：
> 1. **量化風險**：「依目前日誌，若明日切換，預估將有 N 個正常請求被阻擋，
>    影響約 M 位同仁的日常作業。」（用第 2 項統計數字）
> 2. **說明後果不可逆**：一次大規模誤判會造成使用單位長期不信任，
>    後續要再導入的阻力遠高於現在多等兩週。
> 3. **指出最壞結果**：實務上「出問題再說」的結局幾乎都是把 WAF 關掉，
>    最終防護等於零，但稽核報告寫「已建置」——這是更大的風險。
> 4. **給替代方案**：可先對單一低風險站台切換，兩週後再擴大。
>
> ★★★★★ 關鍵是給**數字**，不是講道理。

> [!example] 練習 4（★★★★）
> 設計一份「排除規則複核表」，用於一年後檢查每條排除是否仍必要。
> 至少五個欄位。

> [!question]- 參考解答
> | 欄位 | 說明 |
> | --- | --- |
> | 排除 ID | 1100001 |
> | 建立日期 / 核可人 | 追溯用 |
> | 影響 URI / 參數 / 規則 | 範圍 |
> | 原始症狀 | 當初為什麼要排除 |
> | ★ 應用是否已改版 | 改版後可能不再需要 |
> | ★★★★ 移除後測試結果 | 拿掉這條，誤判會不會回來 |
> | 結論 | 保留 / 移除 / 縮小範圍 |
> | 下次複核日期 | |
>
> ★★★★ 複核的具體做法：在測試環境把該條註解掉，
> 重放一段正式環境的流量，看誤判會不會出現。

> [!example] 練習 5（★★★★）
> 你發現一個誤判：附件下載參數 `path=/uploads/2026/../2026/報告.pdf`
> 命中 LFI 規則。說明你會怎麼處理，以及為什麼不直接寫排除規則。

> [!question]- 參考解答
> **不直接排除的理由**：參數裡出現 `../` 是**應用端路徑處理有缺陷**的徵兆。
> 寫排除規則放行 `../`，等於把真正的路徑穿越攻擊也一起放行。
>
> 正確處理順序：
> 1. ★★★★★ 要求廠商修正前端路徑組合，不要產出 `../`
> 2. 確認後端有 `realpath()` 或等效的路徑正規化與根目錄檢查
> 3. 修好後誤判自然消失，**不需要任何排除規則**
> 4. 若廠商短期無法修改，暫時排除但必須：
>    - 限定到那個 URI 的那個參數
>    - 加上來源網段限定
>    - 設定明確的複核日期並追蹤廠商修正進度
>
> ★★★★★ 原則：**能修應用就修應用，排除規則永遠是第二選擇。**

> [!example] 練習 6（★★★）
> 部署 `waf-report.sh` 並排入每日 cron，連續跑五天，
> 畫出「會被阻擋請求數」的趨勢，判斷是否可以進入階段三。

> [!question]- 參考解答
> ```bash
> for f in /var/log/nginx/waf-report-*.txt; do
>   printf '%s  %s\n' "$(basename "$f" | grep -oP '\d{4}-\d{2}-\d{2}')" \
>     "$(sed -n '/會被阻擋/,+2p' "$f" | tail -1)"
> done
> ```
> 判斷標準不是「數字降到 0」，而是 ★★★★★
> **「剩下的那些，逐筆看過確認都不是正常業務」**。
> 外部掃描造成的阻擋是**應該保留的**，那正是 WAF 在工作。

---

## 小測驗

**Q1.** WAF 導入的總工作量中，佔比最大的是哪一項？

**Q2.**（是非）觀察期跑三天，日誌量已經穩定，就可以進入下一階段。

**Q3.** 下面哪一個**不是**誤判排除的正確做法？
（A）針對特定 URI 的特定參數排除特定規則 ID
（B）把 `inbound_anomaly_score_threshold` 從 5 調到 30
（C）確認應用有輸出編碼後，用 `ctl:ruleRemoveTargetByTag` 排除該欄位的 XSS 檢查
（D）要求廠商修正應用端的路徑組合方式

**Q4.** 這條排除規則放在 `crs-exclusions-after.conf`，會發生什麼？為什麼？

```apache
SecRule REQUEST_URI "@beginsWith /admin/save" \
    "id:1100001,phase:2,pass,nolog,\
     ctl:ruleRemoveTargetById=941100;ARGS:content"
```

**Q5.** 你在稽核日誌看到 `[data "Matched Data: <p> found within ARGS:content:
<p>本府113年度公告</p>"]`，來源是內網 IP、URI 是 `/admin/article/save`、
每天約 4000 次。這是誤判還是攻擊？你的下一步是什麼？

**Q6.** 寫一條排除規則之後，除了「誤判消失」，還要驗證哪三件事？

**Q7.** 階段二的退出條件是什麼？為什麼不是「會被擋的請求數降到 0」？

**Q8.** 為什麼說「開著但沒人看的 WAF」比「被關掉的 WAF」更危險？

**Q9.** 廠商回覆「那個欄位只該收數字，不該有 HTML」。
你原本以為的誤判，現在該怎麼處理？

**Q10.** 這三條指令各自回答什麼問題？

```bash
grep -oP '\[id "\K[0-9]+' modsec_audit.log | sort | uniq -c | sort -rn
grep '\[id "942100"\]' modsec_audit.log | grep -oP 'found within \K[^:]+'
grep -c 'Anomaly Score Exceeded' modsec_audit.log
```

> [!question]- 測驗答案
> **A1. 誤判調校，約佔 80%。**
> 安裝約 10%、掛 CRS 約 5%、切換約 5%。
> 導入計畫如果沒有為調校預留足夠時間，必然失敗。
> ★★★★★ 參見〈觀念說明〉的工作量分布表。
>
> **A2. 錯。**
> 機關系統有強烈的週期性：月初結算、月底請款核銷、季報、年度作業。
> 只跑三天只會看到「每日」情境的誤判，
> **月底那批誤判會在切 `On` 之後才爆發**。
> 觀察期至少兩週，最好跨過一次月初與月底。★★★★★
>
> **A3. (B)**
> 調高門檻是**全面降低防護**來換取局部問題的解決 ——
> 誤判不見了，真攻擊也不會被擋了。
> (A) 是首選做法；(C) 在確認應用有輸出編碼的前提下是可接受的；
> (D) 是最好的做法（能修應用就修應用）。★★★★★
>
> **A4. 完全沒有效果，而且不會有任何錯誤訊息。**
> `ctl:` 是**執行期**動作，必須在目標規則執行**之前**被觸發。
> 放在 `-after`（CRS 規則之後）時，941100 早就跑完並加分了。
> 必須移到 CRS 規則之前載入的檔案。★★★★★
>
> **A5. 誤判。** 判斷依據：
> - `data` 內容是中文公告的正常 HTML
> - 命中欄位是 `ARGS:content`，URI 是後台儲存頁
> - 來源是內網、量大且穩定（承辦人員日常作業）
>
> **下一步是問廠商兩個問題**：
> ① `content` 是否為富文字編輯器內容、本來就有 HTML？
> ② 前台顯示時有沒有做輸出編碼／HTML 過濾？
> ★★★★★ 第二個問題的答案決定排除規則安不安全。
> 得到書面回覆後，才寫 URI + 參數 + 規則 ID 三重限定的排除規則。
>
> **A6.** 還要驗證：
> 1. **同一 URI 的其他參數**仍受保護
> 2. **其他 URI 的同名參數**仍受保護
> 3. **同一 URI 同一參數的其他類型攻擊**（如 SQLi）仍受保護
>
> 只驗證「誤判消失」而不驗證這三項，是排除規則寫太寬卻沒發現的主因。
> ★★★★★ 參見實戰範例步驟 2-4。
>
> **A7.** 退出條件是 **「連續 5 個工作日，會被阻擋的請求裡沒有任何一筆是正常業務」**。
>
> 不是「降到 0」，因為**外部掃描與真實攻擊造成的阻擋是應該存在的** ——
> 那正是 WAF 在工作。要求降到 0 反而會逼你去排除真正該擋的東西。
> ★★★★★
>
> **A8.** 因為誤判量大時，日誌一天上萬筆，沒有人會去看；
> **真正的攻擊就淹沒在那些雜訊裡**，等同沒有偵測能力。
> 而管理層以為「WAF 有在運作」，於是不會補其他防護措施 ——
> 這種「虛假的安全感」比明確知道沒有防護更危險。
> ★★★★★ 這也是為什麼調校的目標包含「把日誌降到人類可讀的量」。
>
> **A9. 這不是誤判，是真攻擊，而且揭露了應用的輸入驗證缺陷。**
> 應該做的是：
> 1. ★★★★★ **不要寫排除規則**
> 2. 分析來源 IP 與請求模式，判斷是掃描還是針對性攻擊
> 3. 通報資安承辦，依事件處理程序辦理
> 4. 要求廠商為該欄位補上輸入驗證（只收數字）
> 5. 保留日誌作為佐證
>
> **A10.**
> 1. 第一條：**「哪些規則命中最多？」** —— 決定先處理哪個誤判（誤判分布極不均）
> 2. 第二條：**「這條規則命中在哪個欄位？」** —— 決定排除規則要限定哪個參數
> 3. 第三條：**「如果現在切 `On`，會有幾個請求被擋？」** ——
>    這是給主管看的關鍵數字，也是階段二退出條件的依據
>
> ★★★★★ 這三條是本篇最實用的三行指令。

---

## 延伸閱讀

### 本章其他篇

- [[090-04-01-svc-WAF-WAF概念與ModSecurity安裝]] —— 引擎安裝、`DetectionOnly` 的意義
- [[090-04-02-guide-OWASP-CRS規則集]] —— ★★★★★ 異常評分與三種排除寫法的機制
- [[090-04-04-guide-ModSecurity-日誌分析與監控]] —— 稽核日誌深入判讀與告警串接
- [[090-04-05-guide-ModSecurity-效能與實戰情境]] —— 效能量測與真實攻擊處置
- [[090-04-00-idx-ModSecurity]] —— 本章索引

### 相關主題

- [[090-03-02-guide-應用安全-應用層安全]] —— ★★★★★ 「能修應用就修應用」的那一半
- [[090-03-06-guide-應用安全-委外系統上線前資安檢測]] —— 跟廠商溝通的依據
- [[090-05-04-guide-資安設備-Web應用防火牆WAF]] —— WAF 選型與市場全景
- [[090-05-01-guide-資安設備-資安全景圖與縱深防禦]] —— WAF 不是唯一防線
- [[090-02-05-guide-防護-Fail2ban入侵防護]] —— 重複攻擊的 IP 在防火牆層封鎖
- [[090-02-08-guide-防護-系統強化與稽核]] —— WAF 節點本身的強化

### 日誌與監控

- [[100-01-02-guide-日誌-日誌集中與輪替]] —— logrotate 與日誌保存
- [[100-01-03-guide-日誌-系統監控與告警]] —— 403 異常告警
- [[100-01-05-guide-監控-監控策略與告警設計]] —— 告警不要造成新的雜訊

### Web 伺服器

- [[060-02-02-09-guide-Nginx-安全設定]]
- [[060-02-02-07-guide-Nginx-日誌與除錯]]
- [[060-02-03-04-guide-Apache-htaccess與Rewrite]] —— Apache 對照
- [[060-02-03-07-guide-Apache-安全與效能]]
- [[060-02-05-08-guide-MyGuard-MyGuard實戰組合]] —— 強化模組與 CRS 的組合

### 部署

- [[130-01-01-guide-部署-部署共通觀念]] —— 變更管理與回退方案

### 官方資源

| 資源 | 網址 |
| --- | --- |
| CRS 誤判處理文件 | <https://coreruleset.org/docs/> |
| CRS 原始碼與 Issue 討論 | <https://github.com/coreruleset/coreruleset> |
| ModSecurity 參考手冊 | <https://github.com/owasp-modsecurity/ModSecurity/wiki> |
